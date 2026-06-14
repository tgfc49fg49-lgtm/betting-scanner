
import itertools
import math
import re
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st
from pathlib import Path

# =========================================================
# CD BETTING — CLEAN SPORTSBOOK BUILD
# =========================================================
# Fixes:
# - No broken MN_APP_TYPE_MAP syntax
# - No right-side sidebar/research slip
# - Auto-loads all sports
# - Sport -> Matchup -> Betting Lines hierarchy
# - Common sportsbook markets only
# - Live/in-game score display
# - AI confidence capped 0-100 with evidence
# - Minnesota app routing on bet cards and arbitrage
# - Player history/research section without fake stats
# =========================================================

SGO_API_KEY = "d14f806f422028626a29b398fd9a879e"
SGO_EVENTS_URL = "https://api.sportsgameodds.com/v2/events"

LEAGUES = {
    "MLB": "MLB",
    "WNBA": "WNBA",
    "NBA": "NBA",
    "NFL": "NFL",
    "NHL": "NHL",
    "UFC/MMA": "UFC",
    "Soccer": "MLS",
}

# Some SportsGameOdds sports can use different league IDs depending on feed/event.
# V62 tries multiple IDs so fighting and soccer do not disappear.
LEAGUE_ID_OPTIONS = {
    "MLB": ["MLB"],
    "WNBA": ["WNBA"],
    "NBA": ["NBA"],
    "NFL": ["NFL"],
    "NHL": ["NHL"],
    "UFC/MMA": ["UFC", "MMA", "UFCMMA"],
    "Soccer": ["MLS", "EPL", "UCL", "UEFA", "WorldCup"],
}

SPORT_EMOJI = {
    "MLB": "⚾",
    "WNBA": "🏀",
    "NBA": "🏀",
    "NFL": "🏈",
    "NHL": "🏒",
    "UFC/MMA": "🥊",
    "Soccer": "⚽",
}

BOOKS_TO_IGNORE = {
    "Bovada",
    "BetOnline.ag",
    "LowVig.ag",
    "Matchbook",
    "Polymarket",
    "Kalshi",
    "Consensus",
    "Unknown",
}

MN_APP_LINKS = {
    "Underdog": "https://underdogsports.com/",
    "PrizePicks": "https://www.prizepicks.com/states/minnesota",
    "Sleeper": "https://sleeper.com/",
    "Chalkboard": "https://www.chalkboard.io/",
    "DraftKings Pick6 / DFS": "https://www.draftkings.com/fantasy-sports",
    "FanDuel DFS": "https://www.fanduel.com/fantasy",
    "Dabble": "https://www.dabble.com/",
}

MN_APP_TYPE_MAP = {
    "Player Props": [
        "Underdog",
        "PrizePicks",
        "Sleeper",
        "Chalkboard",
        "DraftKings Pick6 / DFS",
        "Dabble",
    ],
    "Moneyline": [
        "Underdog",
        "Sleeper",
        "PrizePicks",
        "Chalkboard",
    ],
    "Spread": [
        "Underdog",
        "PrizePicks",
        "Sleeper",
        "Chalkboard",
    ],
    "Totals": [
        "Underdog",
        "PrizePicks",
        "Sleeper",
        "Chalkboard",
    ],
    "Other": [
        "Underdog",
        "Sleeper",
        "PrizePicks",
        "Chalkboard",
        "DraftKings Pick6 / DFS",
    ],
}

PREFERRED_USER_APPS = ["underdog", "prizepicks", "sleeper", "chalkboard"]

MARKET_NAMES = {
    "points": "Points",
    "assists": "Assists",
    "rebounds": "Rebounds",
    "steals": "Steals",
    "blocks": "Blocks",
    "turnovers": "Turnovers",
    "threePointersMade": "3PT Made",
    "pointsReboundsAssists": "Pts + Reb + Ast",
    "pointsRebounds": "Pts + Reb",
    "pointsAssists": "Pts + Ast",
    "reboundsAssists": "Reb + Ast",
    "hits": "Hits",
    "totalBases": "Total Bases",
    "homeRuns": "Home Runs",
    "rbis": "RBIs",
    "runs": "Runs",
    "strikeouts": "Strikeouts",
    "walks": "Walks",
    "passingYards": "Passing Yards",
    "passingTouchdowns": "Passing TDs",
    "rushingYards": "Rushing Yards",
    "receivingYards": "Receiving Yards",
    "receptions": "Receptions",
    "touchdowns": "Touchdowns",
    "shots": "Shots",
    "goals": "Goals",
    "savesMade": "Saves",
}

COMMON_PROP_STATS = set(MARKET_NAMES.keys())


# Sport-specific player prop allowlist.
# This prevents garbage like MLB player "Points" or NHL skater "Points" without context.
SPORT_ALLOWED_PROP_STATS = {
    "MLB": {
        "hits", "totalBases", "homeRuns", "rbis", "runs", "strikeouts", "walks"
    },
    "WNBA": {
        "points", "assists", "rebounds", "pointsReboundsAssists",
        "pointsRebounds", "pointsAssists", "reboundsAssists",
        "threePointersMade", "steals", "blocks", "turnovers"
    },
    "NBA": {
        "points", "assists", "rebounds", "pointsReboundsAssists",
        "pointsRebounds", "pointsAssists", "reboundsAssists",
        "threePointersMade", "steals", "blocks", "turnovers"
    },
    "NFL": {
        "passingYards", "passingTouchdowns", "rushingYards",
        "receivingYards", "receptions", "touchdowns"
    },
    "NHL": {
        "points", "assists", "shots", "goals", "savesMade"
    },
    "UFC/MMA": {
        "significantStrikes", "takedowns", "submissionAttempts", "knockdowns",
        "rounds", "method", "winner"
    },
    "Soccer": {
        "shots", "shotsOnTarget", "goals", "assists", "savesMade", "passes", "tackles"
    },
}


def norm_stat_text(text):
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


SPORT_ALLOWED_PROP_TOKENS = {
    "MLB": [
        "hit", "hits", "totalbase", "totalbases", "homerun", "homeruns",
        "rbi", "rbis", "run", "runs", "strikeout", "strikeouts", "walk", "walks"
    ],
    "WNBA": [
        "point", "points", "assist", "assists", "rebound", "rebounds",
        "pra", "pointsreboundsassists", "three", "threepointer", "threepointersmade",
        "steal", "steals", "block", "blocks", "turnover", "turnovers"
    ],
    "NBA": [
        "point", "points", "assist", "assists", "rebound", "rebounds",
        "pra", "pointsreboundsassists", "three", "threepointer", "threepointersmade",
        "steal", "steals", "block", "blocks", "turnover", "turnovers"
    ],
    "NFL": [
        "passingyard", "passingyards", "passingtd", "passingtouchdowns",
        "rushingyard", "rushingyards", "receivingyard", "receivingyards",
        "reception", "receptions", "touchdown", "touchdowns"
    ],
    "NHL": [
        "point", "points", "assist", "assists", "shot", "shots", "goal", "goals",
        "save", "saves", "savesmade"
    ],
    "UFC/MMA": [
        "significantstrike", "significantstrikes", "strike", "strikes",
        "takedown", "takedowns", "submission", "submissions",
        "knockdown", "knockdowns", "round", "rounds", "method", "winner"
    ],
    "Soccer": [
        "shot", "shots", "shotontarget", "shotsontarget",
        "goal", "goals", "assist", "assists", "save", "saves",
        "pass", "passes", "tackle", "tackles"
    ],
}

SPORT_BLOCKED_PROP_TOKENS = {
    # This is the important one: do not show MLB player "points".
    "MLB": ["point", "points", "fantasypoint", "fantasypoints"],
}


def sport_prop_allowed(league, stat, market_raw):
    league = str(league)
    stat_norm = norm_stat_text(stat)
    market_norm = norm_stat_text(market_raw)
    combined = f"{stat_norm} {market_norm}"

    for bad in SPORT_BLOCKED_PROP_TOKENS.get(league, []):
        if bad in combined:
            return False

    allowed = SPORT_ALLOWED_PROP_TOKENS.get(league)
    if not allowed:
        # For sports with no prop map, do not show props.
        return False

    # Accept if any known useful stat token appears in either statID or market name.
    return any(token in combined for token in allowed)


BAD_MARKET_PHRASES = [
    "3-way",
    "three way",
    "quarter",
    "1st quarter",
    "2nd quarter",
    "3rd quarter",
    "4th quarter",
    "1st half",
    "2nd half",
    "inning",
    "period",
    "race to",
    "odd/even",
    "yes/no",
    "batting bases on balls",
    "bases on balls",
    "pitcher hits allowed",
    "not_draw",
    "draw no bet",
]



# =========================================================
# V56 STABILITY HELPERS
# =========================================================

REQUIRED_COL_DEFAULTS = {
    "League": "",
    "Game Time": "",
    "Matchup": "",
    "Live Score": "",
    "Game Score": "",
    "Bucket": "",
    "Market": "",
    "Player": "",
    "Bet Side": "",
    "Prop Line": "",
    "Pick": "",
    "Pick Key": "",
    "Side": "",
    "Line": "",
    "Best Odds": 0,
    "Best Book": "",
    "Best MN App": "",
    "Available MN Apps": "",
    "MN App Badges": "",
    "Book Implied %": 0.0,
    "Market Avg %": 0.0,
    "Edge %": 0.0,
    "Model Probability %": 50.0,
    "High Rate Score": 0.0,
    "Priority Score": 0.0,
    "MLB Prop Tier": 0,
    "Rating": "",
    "Units": 0.0,
    "Books Compared": 0,
    "Is Prop": False,
    "DFS Projection": 0.0,
    "DFS Value": 0.0,
    "DFS Confidence": 0.0,
    "Salary Estimate": 0,
    "Ownership Estimate %": 0.0,
    "Ceiling": 0.0,
    "Floor": 0.0,
    "Leverage": 0.0,
}

def ensure_schema(df):
    """
    Creates missing columns so every tab can render without KeyError.
    """
    if df is None:
        return pd.DataFrame(columns=list(REQUIRED_COL_DEFAULTS.keys()))

    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame(columns=list(REQUIRED_COL_DEFAULTS.keys()))

    work = df.copy()

    for col, default in REQUIRED_COL_DEFAULTS.items():
        if col not in work.columns:
            work[col] = default

    return work


def safe_cols(df, cols):
    """
    Returns only existing columns. Prevents df[cols] KeyErrors.
    """
    df = ensure_schema(df)
    return [c for c in cols if c in df.columns]


def safe_dataframe(df, cols=None, **kwargs):
    """
    Safe st.dataframe wrapper.
    """
    df = ensure_schema(df)

    if cols:
        cols = safe_cols(df, cols)
        if cols:
            df = df[cols]

    st.dataframe(df, **kwargs)


def safe_metric_value(value, default=0):
    try:
        if pd.isna(value):
            return default
        return value
    except Exception:
        return default


# =========================================================
# STYLE
# =========================================================

st.set_page_config(page_title="CD Betting", page_icon="🏆", layout="wide")

st.markdown(
    """
<style>
[data-testid="stSidebar"] {display:none;}
[data-testid="collapsedControl"] {display:none;}
.block-container {max-width: 1320px; padding-top: .75rem; padding-bottom: 4rem;}

.stApp {
    background: radial-gradient(circle at top left, rgba(225,29,72,.18), transparent 28%),
                linear-gradient(180deg, #050816 0%, #0f172a 42%, #111827 100%);
    color: #f8fafc;
}

button[data-baseweb="tab"] {
    background: #111827 !important;
    color: #f8fafc !important;
    border-radius: 14px !important;
    padding: 10px 15px !important;
    margin-right: 7px !important;
    font-weight: 950 !important;
    border: 1px solid #334155 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    background: #e11d48 !important;
    color: #fff !important;
    border: 1px solid #fb7185 !important;
}
button[data-baseweb="tab"] p {color: inherit !important; font-size: 15px !important;}

.hero {
    background: linear-gradient(135deg, rgba(15,23,42,.98), rgba(127,29,29,.92));
    color: white;
    padding: 24px 28px;
    border-radius: 26px;
    border: 1px solid rgba(148,163,184,.28);
    box-shadow: 0 20px 48px rgba(0,0,0,.35);
    margin-bottom: 16px;
}
.hero-title {font-size: 42px; font-weight: 950; letter-spacing: -1.5px; line-height: 1;}
.hero-sub {margin-top: 8px; color: #cbd5e1; font-size: 15px; font-weight: 750;}
.pill {
    display: inline-block; background: rgba(255,255,255,.09);
    border: 1px solid rgba(255,255,255,.20); color: #f8fafc;
    padding: 6px 10px; border-radius: 999px; margin-right: 6px; margin-top: 12px;
    font-size: 12px; font-weight: 900;
}

.left-rail, .match-card {
    background: rgba(15,23,42,.92);
    border: 1px solid rgba(148,163,184,.25);
    border-radius: 22px;
    box-shadow: 0 16px 36px rgba(0,0,0,.24);
}
.left-rail {padding: 14px; position: sticky; top: 10px;}
.rail-title {
    font-size: 12px; color: #94a3b8; font-weight: 950;
    text-transform: uppercase; letter-spacing: .08em; margin-bottom: 10px;
}
.rail-item {
    display: flex; justify-content: space-between; gap: 8px;
    background: rgba(30,41,59,.85); border: 1px solid rgba(148,163,184,.16);
    color: #e2e8f0; padding: 10px 12px; border-radius: 14px;
    margin-bottom: 8px; font-weight: 900; font-size: 13px;
}
.rail-item.hot {background: linear-gradient(135deg, #e11d48, #991b1b); color: #fff; border: 1px solid #fb7185;}

.match-card {padding: 16px; margin: 12px 0;}
.match-title {font-size: 21px; font-weight: 950; color: #f8fafc;}
.match-sub {color: #94a3b8; font-weight: 800; margin-top: 4px;}
.badge {
    display:inline-block; padding: 5px 9px; border-radius: 999px;
    background: rgba(225,29,72,.16); color: #fecdd3;
    border: 1px solid rgba(251,113,133,.35); font-size: 12px;
    font-weight: 900; margin-right: 6px; margin-top: 9px;
}

.market-header {
    margin-top: 16px; padding: 12px 14px; background: rgba(30,41,59,.86);
    border: 1px solid rgba(148,163,184,.2); border-radius: 16px;
    color: #fff; font-weight: 950;
}

.odds-row {
    display: grid; grid-template-columns: minmax(240px, 1fr) repeat(3, minmax(108px, 138px));
    gap: 10px; align-items: center; background: rgba(15,23,42,.78);
    border: 1px solid rgba(148,163,184,.17); border-radius: 16px;
    padding: 11px; margin: 8px 0;
}
.odds-pick {color: #f8fafc; font-weight: 950; font-size: 14px;}
.odds-sub {color: #94a3b8; font-weight: 750; font-size: 12px; margin-top: 3px; line-height: 1.35;}
.odds-button {
    background: #e11d48; color: white; border: 1px solid #fb7185;
    border-radius: 13px; padding: 10px; text-align: center; font-weight: 950;
    box-shadow: inset 0 -8px 18px rgba(0,0,0,.12);
}
.odds-book {color: #fecdd3; font-size: 11px; font-weight: 850; margin-top: 2px;}

div[data-testid="stMetric"] {
    background: #0b1220 !important; border: 1px solid #334155 !important;
    border-radius: 20px !important; padding: 14px 16px !important;
    box-shadow: 0 10px 25px rgba(0,0,0,.24) !important;
}
div[data-testid="stMetric"] label, div[data-testid="stMetric"] div, div[data-testid="stMetricValue"] {color:white!important;}
[data-testid="stDataFrame"] {border-radius:18px; overflow:hidden; box-shadow:0 14px 32px rgba(0,0,0,.25);}
div.stButton > button {background:#e11d48; color:white; border:0; border-radius:14px; font-weight:950;}
div.stButton > button:hover {background:#be123c; color:white;}
h1,h2,h3,h4,h5,h6,p,label,span {color: inherit;}
</style>
""",
    unsafe_allow_html=True,
)


# =========================================================
# ODDS + UTILS
# =========================================================

def american_to_decimal(odds):
    odds = int(float(odds))
    return 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)


def decimal_to_american(decimal_odds):
    decimal_odds = float(decimal_odds)
    return round((decimal_odds - 1) * 100) if decimal_odds >= 2 else round(-100 / (decimal_odds - 1))


def american_to_prob(odds):
    return 1 / american_to_decimal(odds)


def format_odds(odds):
    try:
        return f"{int(float(odds)):+d}"
    except Exception:
        return str(odds)


def clean_line(line):
    if line in ["", None, "nan"]:
        return ""
    try:
        value = float(line)
        if value > 0:
            return f"+{value:g}"
        return f"{value:g}"
    except Exception:
        return str(line)


def clean_prop_line(line):
    if line in ["", None, "nan"]:
        return ""
    try:
        value = float(line)
        return f"{value:g}"
    except Exception:
        return str(line)


def parse_game_date(game_time_text):
    """
    Parses app display dates like 'Jan 03 • 12:00 PM CT'.
    If the date already passed by more than 7 days, treat it as next calendar year.
    That keeps January NFL games from showing in summer as if they are current.
    """
    if not game_time_text:
        return None
    try:
        clean = str(game_time_text).replace("•", "").replace("CT", "").strip()
        dt = datetime.strptime(clean, "%b %d %I:%M %p")

        now = datetime.now(ZoneInfo("America/Chicago")).replace(tzinfo=None)
        dt = dt.replace(year=now.year)

        if (dt - now).days < -7:
            dt = dt.replace(year=now.year + 1)

        return dt
    except Exception:
        return None


def is_far_future_nfl(row, days=45):
    """
    Hide NFL if the game is too far away. During summer this removes January
    futures/offseason lines from Sportsbook, AI, Arbitrage, and Parlays.
    """
    if str(row.get("League", "")) != "NFL":
        return False

    dt = parse_game_date(row.get("Game Time", ""))
    if dt is None:
        return True

    now = datetime.now(ZoneInfo("America/Chicago")).replace(tzinfo=None)
    return (dt - now).days > days



def pretty_market(market):
    market = str(market)
    if market in MARKET_NAMES:
        return MARKET_NAMES[market]
    text = market.replace("_", " ")
    out = ""
    for ch in text:
        if ch.isupper() and out:
            out += " "
        out += ch
    return out.title()


def clean_market_label(label):
    """
    Convert API/stat wording into sportsbook-friendly wording.
    """
    text = str(label)

    replacements = {
        "Batting Bases On Balls": "Walks",
        "Pitching Bases On Balls": "Pitcher Walks",
        "Bases On Balls": "Walks",
        "Rbis": "RBIs",
        "Rbi": "RBI",
        "Homeruns": "Home Runs",
        "Home Runs": "Home Runs",
        "Totalbases": "Total Bases",
        "Three Pointers Made": "3PT Made",
    }

    for old, new in replacements.items():
        text = re.sub(old, new, text, flags=re.I)

    text = text.replace("  ", " ").strip()
    return text


def clean_pick_label(pick):
    text = str(pick)
    text = re.sub(r"Batting Bases On Balls", "Walks", text, flags=re.I)
    text = re.sub(r"Pitching Bases On Balls", "Pitcher Walks", text, flags=re.I)
    text = re.sub(r"Bases On Balls", "Walks", text, flags=re.I)
    text = re.sub(r"Rbis", "RBIs", text, flags=re.I)
    text = re.sub(r"Rbi", "RBI", text, flags=re.I)
    return text



def rating(edge):
    edge = float(edge)
    if edge >= 8:
        return "🔥 MAX BET WATCH"
    if edge >= 5:
        return "🔥 BET NOW"
    if edge >= 3:
        return "👀 STRONG WATCH"
    if edge >= 1.5:
        return "🟡 WATCH"
    return "PASS"


def units(edge):
    edge = float(edge)
    if edge >= 8:
        return 1.5
    if edge >= 5:
        return 1.0
    if edge >= 3:
        return 0.5
    if edge >= 1.5:
        return 0.25
    return 0


def make_links(matchup):
    q = quote_plus(str(matchup))
    return {
        "News": f"https://www.google.com/search?q={q}+team+news&tbm=nws",
        "Preview": f"https://www.google.com/search?q={q}+betting+preview",
        "Injuries": f"https://www.google.com/search?q={q}+injury+report",
    }


def format_book_name(book):
    return str(book).replace("_", " ").replace("-", " ").title()


def is_preferred_user_app(book):
    b = str(book).lower().replace(" ", "").replace("_", "").replace("-", "")
    return any(app in b for app in PREFERRED_USER_APPS)


# =========================================================
# PARSING SPORTSGAMEODDS
# =========================================================

def safe_json(response):
    try:
        return response.json()
    except Exception:
        return None


def val(d, *keys, default=""):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in ["", None]:
            return d[k]
    return default


def extract_events(payload):
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ["data", "events", "results", "items", "games"]:
        value = payload.get(key)
        if isinstance(value, list):
            return value

    data = payload.get("data")
    if isinstance(data, dict):
        for key in ["events", "results", "items", "games"]:
            value = data.get(key)
            if isinstance(value, list):
                return value

    for value in payload.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value

    return []


def clean_team_name(obj, fallback=""):
    if isinstance(obj, dict):
        names = obj.get("names")
        if isinstance(names, dict):
            return str(names.get("long") or names.get("medium") or names.get("short") or fallback)
        return str(obj.get("name") or obj.get("teamName") or obj.get("displayName") or fallback)
    return str(obj or fallback)


def get_teams_map(event):
    teams = event.get("teams", {}) if isinstance(event, dict) else {}
    return teams if isinstance(teams, dict) else {}


def get_team_roles(event):
    teams = get_teams_map(event)
    away_name = ""
    home_name = ""

    for _, team in teams.items():
        if isinstance(team, dict):
            role = str(team.get("statEntityID", "")).lower()
            if role == "away":
                away_name = clean_team_name(team)
            elif role == "home":
                home_name = clean_team_name(team)

    if not away_name and isinstance(teams.get("away"), dict):
        away_name = clean_team_name(teams.get("away"))
    if not home_name and isinstance(teams.get("home"), dict):
        home_name = clean_team_name(teams.get("home"))

    return away_name, home_name


def get_matchup_name(event):
    away, home = get_team_roles(event)
    if away and home:
        return f"{away} @ {home}"
    return str(val(event, "eventName", "name", "shortName", "title", "displayName", "eventID", "eventId", default="Unknown Matchup"))


def get_entity_name(event, entity_id):
    if not entity_id:
        return ""

    entity_id = str(entity_id)
    lower = entity_id.lower()
    teams = get_teams_map(event)

    if lower in ["away", "home"]:
        away, home = get_team_roles(event)
        return away if lower == "away" else home

    if entity_id in teams:
        return clean_team_name(teams[entity_id], entity_id)

    for _, team in teams.items():
        if isinstance(team, dict):
            if str(team.get("teamID", "")) == entity_id or str(team.get("statEntityID", "")) == entity_id:
                return clean_team_name(team, entity_id)

    players = event.get("players", {}) if isinstance(event, dict) else {}
    if isinstance(players, dict):
        p = players.get(entity_id)
        if isinstance(p, dict):
            return str(p.get("name") or f"{p.get('firstName', '')} {p.get('lastName', '')}".strip() or entity_id)

    return entity_id


def event_time(event):
    raw = val(event, "startTime", "startDate", "commenceTime", "eventTime", "gameTime", "scheduledTime")
    if not raw:
        status = event.get("status") if isinstance(event, dict) else None
        if isinstance(status, dict):
            raw = status.get("startsAt")
    if not raw:
        return ""

    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/Chicago")).strftime("%b %d • %I:%M %p CT")
    except Exception:
        return str(raw)


def live_score(event):
    status = event.get("status") if isinstance(event, dict) else None
    if isinstance(status, dict):
        if status.get("live"):
            return "Live"
        if status.get("completed") or status.get("ended"):
            return "Final"
        return str(status.get("displayLong") or status.get("displayShort") or "Upcoming")
    return "Upcoming"


def extract_score_value(obj):
    if isinstance(obj, dict):
        for key in ["score", "points", "runs", "goals", "total", "value"]:
            v = obj.get(key)
            if v not in ["", None]:
                return v
        return None
    return obj if obj not in ["", None] else None


def game_score_display(event):
    if not isinstance(event, dict):
        return "Score unavailable"

    away_name, home_name = get_team_roles(event)
    status = event.get("status", {}) if isinstance(event.get("status"), dict) else {}

    away_score = (
        status.get("awayScore") or status.get("awayPoints") or status.get("awayRuns") or status.get("awayGoals")
    )
    home_score = (
        status.get("homeScore") or status.get("homePoints") or status.get("homeRuns") or status.get("homeGoals")
    )

    scores = event.get("scores") or event.get("score") or event.get("boxScore")
    if isinstance(scores, dict):
        away_score = away_score or scores.get("away") or scores.get("awayScore") or scores.get("awayPoints")
        home_score = home_score or scores.get("home") or scores.get("homeScore") or scores.get("homePoints")

    away_score = extract_score_value(away_score)
    home_score = extract_score_value(home_score)

    teams = get_teams_map(event)
    for _, team in teams.items():
        if isinstance(team, dict):
            role = str(team.get("statEntityID", "")).lower()
            team_score = extract_score_value(team)
            if role == "away" and away_score in ["", None]:
                away_score = team_score
            if role == "home" and home_score in ["", None]:
                home_score = team_score

    period = status.get("currentPeriodID") or status.get("period") or status.get("quarter") or status.get("inning") or ""
    clock = status.get("clock") or status.get("displayClock") or status.get("timeRemaining") or ""

    if away_score not in ["", None] and home_score not in ["", None] and away_name and home_name:
        extra = " • ".join(str(x) for x in [period, clock] if x not in ["", None])
        if extra:
            return f"{away_name} {away_score} - {home_score} {home_name} • {extra}"
        return f"{away_name} {away_score} - {home_score} {home_name}"

    return f"{live_score(event)}" + (f" • {event_time(event)}" if event_time(event) else "")


def is_line_value(v):
    if v in ["", None, "nan"]:
        return False
    try:
        x = float(str(v).replace("+", ""))
    except Exception:
        return False
    if abs(x) >= 100:
        return False
    return -80 <= x <= 80


def first_real_line(odd):
    if not isinstance(odd, dict):
        return ""

    official = [
        "overUnder", "bookOverUnder", "fairOverUnder", "openOverUnder",
        "spread", "bookSpread", "fairSpread", "openSpread",
        "line", "points", "handicap", "total", "propLine", "statLine",
    ]

    for key in official:
        v = odd.get(key)
        if is_line_value(v):
            return v

    return ""


def parse_odds(odd):
    raw = val(
        odd,
        "bookOdds", "odds", "price", "americanOdds", "american",
        "oddsAmerican", "fairOdds", "openBookOdds", "openFairOdds"
    )

    if raw not in ["", None]:
        try:
            return int(float(str(raw).replace("+", "")))
        except Exception:
            return None

    dec = val(odd, "decimalOdds", "decimal")
    if dec not in ["", None]:
        try:
            return decimal_to_american(float(dec))
        except Exception:
            return None

    return None


def get_odds_rows(event):
    if not isinstance(event, dict):
        return []

    odds = event.get("odds", {})
    rows = []

    if isinstance(odds, list):
        return odds

    if isinstance(odds, dict):
        for odd_key, odd_data in odds.items():
            if not isinstance(odd_data, dict):
                continue

            by_bookmaker = odd_data.get("byBookmaker", {})

            if isinstance(by_bookmaker, dict) and by_bookmaker:
                for book_name, book_data in by_bookmaker.items():
                    if not isinstance(book_data, dict):
                        continue

                    row = dict(odd_data)
                    row.update(book_data)
                    row["oddID"] = odd_key
                    row["sportsbook"] = book_name
                    row["bookmaker"] = book_name

                    if "odds" in book_data:
                        row["bookOdds"] = book_data["odds"]
                    if "overUnder" in book_data:
                        row["bookOverUnder"] = book_data["overUnder"]
                    if "spread" in book_data:
                        row["bookSpread"] = book_data["spread"]

                    rows.append(row)

            elif odd_data.get("bookOdds") or odd_data.get("fairOdds"):
                row = dict(odd_data)
                row["oddID"] = odd_key
                row["sportsbook"] = "Consensus"
                rows.append(row)

    return rows


def is_common_market(market_raw, stat, is_prop, league=None):
    """
    Keep only markets a normal sportsbook bettor expects.
    Game lines: moneyline, spread/run line, total.
    Props: sport-specific common props only.
    """
    raw = str(market_raw).lower()
    stat_s = str(stat)

    if any(bad in raw for bad in BAD_MARKET_PHRASES):
        return False

    if is_prop:
        return sport_prop_allowed(league, stat_s, market_raw)

    if any(word in raw for word in COMMON_GAME_MARKET_WORDS["moneyline"]):
        return True
    if any(word in raw for word in COMMON_GAME_MARKET_WORDS["spread"]):
        return True
    if any(word in raw for word in COMMON_GAME_MARKET_WORDS["totals"]):
        return True

    return False

    if is_prop:
        return stat_s in COMMON_PROP_STATS

    if "moneyline" in raw:
        return True

    if any(x in raw for x in ["spread", "handicap", "run line", "puck line"]):
        return True

    if any(x in raw for x in ["total", "over/under", "over under"]):
        return True

    return False


def market_bucket(row):
    market = str(row.get("Market", "")).lower()
    pick = str(row.get("Pick", "")).lower()

    if str(row.get("Bucket", "")).lower() == "event" or market == "event":
        return "Event"

    if row.get("Is Prop"):
        return "Player Props"
    if "moneyline" in market or "moneyline" in pick:
        return "Moneyline"
    if "spread" in market or "handicap" in market or "run line" in market or "puck line" in market:
        return "Spread"
    if "total" in market or pick.startswith("over ") or pick.startswith("under "):
        return "Totals"
    return "Other"


def recommend_mn_apps(bucket, pick, market, is_prop):
    if is_prop:
        apps = MN_APP_TYPE_MAP["Player Props"]
        best = "Underdog"
    else:
        apps = MN_APP_TYPE_MAP.get(bucket, MN_APP_TYPE_MAP["Other"])
        best = "Underdog"
    return best, ", ".join(apps)


def mn_app_badges(best_app, available_apps):
    apps = [x.strip() for x in str(available_apps).split(",") if x.strip()]
    rows = []
    for app in apps[:5]:
        marker = "★" if app == best_app else "✓"
        rows.append(f"{marker} {app}")
    return " • ".join(rows)


def normalize_odd(league, event, odd):
    odds = parse_odds(odd)
    if odds is None:
        return None

    book = str(val(odd, "sportsbook", "sportsbookID", "sportsbookName", "book", "bookmaker", "bookmakerID", default="Unknown"))
    if book in BOOKS_TO_IGNORE:
        return None

    matchup = get_matchup_name(event)
    links = make_links(matchup)

    market_raw = str(val(odd, "marketName", "market", "betName", "statName", "statID", "oddType", "betTypeID", default="Unknown Market"))
    stat = str(val(odd, "statID", "statName", "stat", default=""))
    stat_entity_id = str(val(odd, "statEntityID", "entityID", "playerID", default=""))
    side_id = str(val(odd, "sideID", "side", "outcome", "selection", "betSide", "overUnder", default=""))
    line = first_real_line(odd)
    odd_id = str(val(odd, "oddID", "id", "marketID", default=""))

    players = event.get("players", {}) if isinstance(event, dict) else {}
    is_prop = isinstance(players, dict) and stat_entity_id in players

    if not is_common_market(market_raw, stat, is_prop, league):
        return None

    entity_name = get_entity_name(event, stat_entity_id)
    side_name = get_entity_name(event, side_id)

    if side_id.lower() in ["over", "under"]:
        side_clean = side_id.title()
    elif side_id.lower() in ["away", "home"]:
        side_clean = side_name or side_id.title()
    else:
        side_clean = side_id

    stat_label = pretty_market(stat or market_raw)
    clean_market = pretty_market(market_raw)
    odds_text = format_odds(odds)
    line_text = clean_line(line)

    if is_prop:
        if not is_line_value(line):
            return None
        player = entity_name
        base_pick = f"{player} {side_clean} {line_text} {stat_label}".strip()
        pick = f"{base_pick} ({odds_text})"
        clean_market = f"Player Prop • {stat_label}"
        pick_key = f"{player}|{side_clean}|{line_text}|{stat_label}"
    else:
        player = ""
        selection = side_name or entity_name or side_clean or clean_market
        market_lower = clean_market.lower()

        if "moneyline" in market_lower:
            base_pick = f"{selection} Moneyline"
        elif "spread" in market_lower or "handicap" in market_lower or "run line" in market_lower or "puck line" in market_lower:
            if not is_line_value(line):
                return None
            base_pick = f"{selection} {line_text}".strip()
        elif "total" in market_lower:
            if not is_line_value(line):
                return None
            base_pick = f"{side_clean} {line_text}".strip()
        else:
            return None

        pick = f"{base_pick} ({odds_text})"
        pick_key = f"{base_pick}|{clean_market}|{side_clean}|{line_text}"

    return {
        "League": league,
        "Matchup": matchup,
        "Game Time": event_time(event),
        "Live Score": live_score(event),
        "Game Score": game_score_display(event),
        "Market": clean_market_label(clean_market),
        "Bucket": "",
        "Player": player,
        "Bet Side": side_clean,
        "Prop Line": line,
        "Pick": clean_pick_label(pick),
        "Pick Key": pick_key,
        "Side": side_clean,
        "Line": line,
        "Best Odds": odds,
        "Best Book": book,
        "Book Implied %": round(american_to_prob(odds) * 100, 2),
        "Odd ID": odd_id,
        "Is Prop": is_prop,
        "News": links["News"],
        "Preview": links["Preview"],
        "Injuries": links["Injuries"],
    }


def event_only_row(league, event, api_league_id=""):
    """
    Creates a no-fake-odds row so Soccer/UFC events still appear when the API has
    events but no usable prices. These rows are display-only and do not create edges.
    """
    matchup = get_matchup_name(event)
    links = make_links(matchup)

    return {
        "League": league,
        "API League": api_league_id,
        "Matchup": matchup,
        "Game Time": event_time(event),
        "Live Score": live_score(event),
        "Game Score": game_score_display(event),
        "Market": "Event",
        "Bucket": "Event",
        "Player": "",
        "Bet Side": "",
        "Prop Line": "",
        "Pick": "Odds not available yet",
        "Pick Key": f"{matchup}|event|{api_league_id}",
        "Side": "",
        "Line": "",
        "Best Odds": 0,
        "Best Book": "Odds unavailable",
        "Book Implied %": 50.0,
        "Odd ID": "",
        "Is Prop": False,
        "Market Avg %": 50.0,
        "Edge %": 0.0,
        "Model Probability %": 50.0,
        "High Rate Score": 0.0,
        "Rating": "EVENT",
        "Units": 0.0,
        "Books Compared": 0,
        "Best MN App": "",
        "Available MN Apps": "",
        "MN App Badges": "",
        "News": links["News"],
        "Preview": links["Preview"],
        "Injuries": links["Injuries"],
    }



def mlb_prop_tier(row):
    """
    MLB user-facing ranking.
    Walk/base-on-balls props are removed elsewhere; if they leak through, rank dead last.
    """
    if str(row.get("League", "")) != "MLB":
        return 1

    if not bool(row.get("Is Prop", False)):
        return 0

    if is_walk_or_base_on_balls(row):
        return 99

    market = norm_stat_text(f"{row.get('Market', '')} {row.get('Pick', '')} {row.get('Player', '')}")

    tier1 = [
        "hit", "hits", "totalbase", "totalbases", "homerun", "homeruns",
        "rbi", "rbis", "run", "runs", "strikeout", "strikeouts",
        "hitsrunsrbi", "hitsrunsrbis", "hitrunrbi", "hitrunrbis"
    ]

    tier2 = [
        "hitallowed", "hitsallowed", "earnedrun", "earnedruns",
        "stolenbase", "stolenbases", "single", "singles", "double", "doubles"
    ]

    if any(x in market for x in tier1):
        return 1

    if any(x in market for x in tier2):
        return 2

    return 3

    if not bool(row.get("Is Prop", False)):
        return 0

    market = norm_stat_text(f"{row.get('Market', '')} {row.get('Pick', '')} {row.get('Player', '')}")

    tier1 = [
        "hit", "hits", "totalbase", "totalbases", "homerun", "homeruns",
        "rbi", "rbis", "run", "runs", "strikeout", "strikeouts",
        "hitsrunsrbi", "hitsrunsrbis"
    ]

    tier2 = [
        "walk", "walks", "baseonballs", "basesonballs",
        "stolenbase", "stolenbases", "single", "singles", "double", "doubles"
    ]

    # Specific order matters: total bases includes "base" but not walks.
    if any(x in market for x in tier1) and "walk" not in market and "baseonballs" not in market and "basesonballs" not in market:
        return 1

    if any(x in market for x in tier2):
        return 2

    return 3


def is_low_interest_walk_prop(row):
    if str(row.get("League", "")) != "MLB":
        return False

    market = norm_stat_text(f"{row.get('Market', '')} {row.get('Pick', '')}")
    if "walk" in market or "baseonballs" in market or "basesonballs" in market:
        return True

    return False


def board_priority_score(row):
    """
    Sort score that favors common sportsbook props instead of API clutter.
    """
    base = float(row.get("High Rate Score", 0))
    edge = float(row.get("Edge %", 0))
    bucket = str(row.get("Bucket", ""))

    score = base + edge

    if bucket in ["Moneyline", "Spread", "Totals"]:
        score += 8

    if is_walk_or_base_on_balls(row):
        score -= 100

    if str(row.get("League", "")) == "MLB" and bool(row.get("Is Prop", False)):
        tier = mlb_prop_tier(row)
        if tier == 1:
            score += 14
        elif tier == 2:
            score += 3
        else:
            score -= 12

    return round(score, 2)

    score = base + edge

    if bucket in ["Moneyline", "Spread", "Totals"]:
        score += 8

    if str(row.get("League", "")) == "MLB" and bool(row.get("Is Prop", False)):
        tier = mlb_prop_tier(row)
        if tier == 1:
            score += 10
        elif tier == 2:
            score -= 6
        else:
            score -= 14

        # Walk unders are usually low-value display clutter. Only keep them high if edge is extreme.
        if is_low_interest_walk_prop(row):
            if edge < 15:
                score -= 25
            else:
                score -= 8

    return round(score, 2)



def text_blob(row):
    return norm_stat_text(
        f"{row.get('League', '')} {row.get('Bucket', '')} {row.get('Market', '')} "
        f"{row.get('Pick', '')} {row.get('Player', '')}"
    )


def is_walk_or_base_on_balls(row):
    blob = text_blob(row)
    return (
        "walk" in blob
        or "walks" in blob
        or "baseonballs" in blob
        or "basesonballs" in blob
        or "battingbaseonballs" in blob
        or "battingbasesonballs" in blob
        or "pitchingbaseonballs" in blob
        or "pitchingbasesonballs" in blob
    )


def is_allowed_user_prop(row):
    """
    High-quality props only.
    Removes low-interest/exotic stuff from dashboard, AI, parlays and matchup boards.
    """
    if not bool(row.get("Is Prop", False)):
        return True

    league = str(row.get("League", ""))
    blob = text_blob(row)

    # Completely remove walk/base-on-balls markets.
    if is_walk_or_base_on_balls(row):
        return False

    allowed_tokens = {
        "MLB": [
            "hit", "hits", "totalbase", "totalbases", "homerun", "homeruns",
            "rbi", "rbis", "run", "runs", "strikeout", "strikeouts",
            "hitsrunsrbi", "hitsrunsrbis", "hitrunrbi", "hitrunrbis",
            "hitallowed", "hitsallowed", "earnedrun", "earnedruns"
        ],
        "WNBA": [
            "point", "points", "rebound", "rebounds", "assist", "assists",
            "pointsreboundsassists", "pra", "pointsrebounds", "pointsassists",
            "reboundsassists", "threepointer", "threepointers", "threepointersmade",
            "3pt", "3pm"
        ],
        "NBA": [
            "point", "points", "rebound", "rebounds", "assist", "assists",
            "pointsreboundsassists", "pra", "pointsrebounds", "pointsassists",
            "reboundsassists", "threepointer", "threepointers", "threepointersmade",
            "3pt", "3pm"
        ],
        "NFL": [
            "passingyard", "passingyards", "rushingyard", "rushingyards",
            "receivingyard", "receivingyards", "reception", "receptions",
            "touchdown", "touchdowns", "anytimetd", "passingtd", "passingtouchdown"
        ],
        "NHL": [
            "shot", "shots", "point", "points", "assist", "assists",
            "goal", "goals", "save", "saves", "savesmade"
        ],
        "Soccer": [
            "shot", "shots", "goal", "goals", "assist", "assists",
            "save", "saves", "savesmade"
        ],
    }

    tokens = allowed_tokens.get(league)
    if not tokens:
        return False

    return any(token in blob for token in tokens)


def is_quality_user_row(row):
    """
    Final user-facing quality gate.
    Game lines stay. Props must pass sport-specific quality.
    """
    bucket = str(row.get("Bucket", ""))
    if bucket in ["Moneyline", "Spread", "Totals"]:
        return True

    return is_allowed_user_prop(row)



def clean_user_facing_board(df, hide_low_interest=True):
    """
    User-facing board used for Dashboard, AI, Parlays, and sportsbook cards.
    V56 keeps all common game lines and filters only low-quality props.
    """
    work = ensure_schema(df)
    if work.empty:
        return work

    if "Market" in work.columns:
        work["Market"] = work["Market"].apply(clean_market_label)
    if "Pick" in work.columns:
        work["Pick"] = work["Pick"].apply(clean_pick_label)

    is_game_line = work["Bucket"].isin(["Moneyline", "Spread", "Totals", "Run Line", "Puck Line", "Event"])
    is_prop_quality = work.apply(is_allowed_user_prop, axis=1) if "is_allowed_user_prop" in globals() else True
    work = work[is_game_line | is_prop_quality].copy()

    work = ensure_schema(work)

    if work.empty:
        return work

    work["MLB Prop Tier"] = work.apply(mlb_prop_tier, axis=1) if "mlb_prop_tier" in globals() else 1
    work["Priority Score"] = work.apply(board_priority_score, axis=1) if "board_priority_score" in globals() else work["High Rate Score"]

    return ensure_schema(work.sort_values(["Priority Score", "High Rate Score", "Edge %"], ascending=False))

    work = df.copy()

    if "Market" in work.columns:
        work["Market"] = work["Market"].apply(clean_market_label)
    if "Pick" in work.columns:
        work["Pick"] = work["Pick"].apply(clean_pick_label)

    work = work[work.apply(is_quality_user_row, axis=1)].copy()

    if work.empty:
        return work

    work["MLB Prop Tier"] = work.apply(mlb_prop_tier, axis=1) if "mlb_prop_tier" in globals() else 1
    work["Priority Score"] = work.apply(board_priority_score, axis=1) if "board_priority_score" in globals() else work.get("High Rate Score", 0)

    return work.sort_values(["Priority Score", "High Rate Score", "Edge %"], ascending=False)

    work = df.copy()

    # Friendly labels.
    if "Market" in work:
        work["Market"] = work["Market"].apply(clean_market_label)
    if "Pick" in work:
        work["Pick"] = work["Pick"].apply(clean_pick_label)

    work["MLB Prop Tier"] = work.apply(mlb_prop_tier, axis=1)
    work["Priority Score"] = work.apply(board_priority_score, axis=1)

    if hide_low_interest:
        # Hide walk props unless there is a very large edge.
        walk_mask = work.apply(is_low_interest_walk_prop, axis=1)
        edge_ok = pd.to_numeric(work["Edge %"], errors="coerce").fillna(0) >= 15
        work = work[(~walk_mask) | edge_ok].copy()

    return work.sort_values(["Priority Score", "High Rate Score", "Edge %"], ascending=False)

def is_realistic_bet_row(row):
    try:
        odds = int(float(row.get("Best Odds", 0)))
    except Exception:
        return False

    try:
        edge = float(row.get("Edge %", 0))
    except Exception:
        edge = 0

    try:
        model = float(row.get("Model Probability %", 0))
    except Exception:
        model = 0

    bucket = str(row.get("Bucket", "")).lower()
    book = str(row.get("Best Book", "")).lower().strip()
    pick = str(row.get("Pick", "")).lower()

    if bucket == "event":
        return True

    bad_books = {"matchbook", "polymarket", "kalshi", "consensus", "unknown", "novig", "betfair exchange"}
    if book in bad_books:
        return False

    if abs(odds) > 2500:
        return False
    if bucket == "moneyline" and abs(odds) > 1200:
        return False
    if bucket == "spread" and abs(odds) > 350:
        return False
    if bucket == "totals" and abs(odds) > 350:
        return False
    if bucket == "player props" and abs(odds) > 2500:
        return False

    if edge > 35:
        return False
    if model < 8 or model > 92:
        return False

    if "line n/a" in pick or " ?" in pick:
        return False
    if "not_draw" in pick or "no draw" in pick or "3-way" in pick:
        return False

    return True


def clean_board(df):
    df = ensure_schema(df)
    if df.empty:
        return df

    work = df[df.apply(is_realistic_bet_row, axis=1)].copy()

    if not work.empty:
        work = work[~work.apply(is_far_future_nfl, axis=1)].copy()

    if not work.empty:
        # Always keep game lines. Only prop rows go through quality prop filtering.
        is_game_line = work["Bucket"].isin(["Moneyline", "Spread", "Totals", "Run Line", "Puck Line", "Event"])
        is_quality_prop = work.apply(is_allowed_user_prop, axis=1) if "is_allowed_user_prop" in globals() else True
        work = work[is_game_line | is_quality_prop].copy()

    return ensure_schema(work)

    work = df[df.apply(is_realistic_bet_row, axis=1)].copy()

    if not work.empty:
        work = work[~work.apply(is_far_future_nfl, axis=1)].copy()

    if not work.empty and "Bucket" in work.columns:
        work = work[work.apply(is_quality_user_row, axis=1)].copy()

    return work

    work = df[df.apply(is_realistic_bet_row, axis=1)].copy()

    if not work.empty:
        work = work[~work.apply(is_far_future_nfl, axis=1)].copy()

    return work


def score_board(rows):
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["Group"] = (
        df["Matchup"].astype(str)
        + "|" + df["Market"].astype(str)
        + "|" + df["Pick Key"].astype(str)
        + "|" + df["Side"].astype(str)
        + "|" + df["Line"].astype(str)
    )

    scored = []

    for _, group in df.groupby("Group"):
        best = group.sort_values("Book Implied %", ascending=True).iloc[0]
        avg = group["Book Implied %"].mean()

        edge = max(0, round(avg - float(best["Book Implied %"]), 2))
        model = round(avg, 2)
        high_rate_score = round((model * 0.55) + (edge * 3.2), 2)

        row = best.to_dict()
        row["Market Avg %"] = round(avg, 2)
        row["Edge %"] = edge
        row["Model Probability %"] = model
        row["High Rate Score"] = high_rate_score
        row["Rating"] = rating(edge)
        row["Units"] = units(edge)
        row["Books Compared"] = len(group)
        row["Bucket"] = market_bucket(row)
        mn_best, mn_apps = recommend_mn_apps(row["Bucket"], row.get("Pick", ""), row.get("Market", ""), row.get("Is Prop", False))
        row["Best MN App"] = mn_best
        row["Available MN Apps"] = mn_apps
        row["MN App Badges"] = mn_app_badges(mn_best, mn_apps)
        scored.append(row)

    board = pd.DataFrame(scored).sort_values(["High Rate Score", "Edge %"], ascending=False)
    cleaned = clean_board(board)

    # If a league would go completely blank, keep only sane non-NFL-future game lines as fallback.
    # This prevents the entire app from showing nothing due to naming differences in the API.
    if cleaned.empty and not board.empty:
        fallback = board[board["Bucket"].isin(["Moneyline", "Spread", "Totals", "Event"])].copy()
        fallback = fallback[~fallback.apply(is_far_future_nfl, axis=1)].copy()
        cleaned = fallback.head(200)

    return ensure_schema(cleaned)


def choose_display_rows(df):
    if df.empty:
        return df

    group_cols = ["Matchup", "Pick Key", "Market", "Line"]
    out = []

    for _, group in df.groupby(group_cols, dropna=False):
        preferred = group[group["Best Book"].apply(is_preferred_user_app)]
        if not preferred.empty:
            row = preferred.sort_values(["Edge %", "High Rate Score"], ascending=False).iloc[0].copy()
            row["Display Source"] = "Preferred MN/Pick'em App"
        else:
            row = group.sort_values(["High Rate Score", "Edge %"], ascending=False).iloc[0].copy()
            row["Display Source"] = "Best Available Sportsbook"
        out.append(row)

    return pd.DataFrame(out).sort_values(["High Rate Score", "Edge %"], ascending=False)


# =========================================================
# FETCHING
# =========================================================

@st.cache_data(ttl=90, show_spinner=False)
def fetch_league_cached(league):
    """
    V62 multi-ID fetcher.
    Tries multiple SportsGameOdds league IDs for sports that can disappear:
    - UFC/MMA: UFC, MMA, UFCMMA
    - Soccer: MLS, EPL, UCL, UEFA, WorldCup

    Also adds event-only fallback rows if events exist but no usable odds parse.
    """
    headers = {
        "Accept": "application/json",
        "x-api-key": SGO_API_KEY,
        "Authorization": f"Bearer {SGO_API_KEY}",
    }

    all_rows = []
    all_events = {}
    statuses = []
    urls = []
    errors = []
    total_pages = 0

    league_ids = LEAGUE_ID_OPTIONS.get(league, [LEAGUES.get(league, league)])

    try:
        for api_league_id in league_ids:
            cursor = None
            page_size = 8
            max_pages = 20

            for _ in range(max_pages):
                params = {
                    "apiKey": SGO_API_KEY,
                    "leagueID": api_league_id,
                    "oddsAvailable": "true",
                    "limit": page_size,
                }

                if cursor:
                    params["cursor"] = cursor

                r = requests.get(SGO_EVENTS_URL, params=params, headers=headers, timeout=(5, 20))
                urls.append(r.url)
                statuses.append(r.status_code)
                total_pages += 1

                payload = safe_json(r)

                if r.status_code != 200:
                    errors.append(f"{api_league_id}: HTTP {r.status_code} {r.text[:200]}")
                    break

                events = extract_events(payload)
                for ev in events:
                    key = str(val(ev, "eventID", "id", "gameID", default=get_matchup_name(ev) + "|" + event_time(ev)))
                    all_events[key] = (api_league_id, ev)

                    for odd in get_odds_rows(ev):
                        try:
                            row = normalize_odd(league, ev, odd)
                            if row:
                                row["API League"] = api_league_id
                                all_rows.append(row)
                        except Exception as parse_error:
                            errors.append(f"{api_league_id}: skipped odds row {type(parse_error).__name__}: {parse_error}")

                cursor = None
                if isinstance(payload, dict):
                    cursor = payload.get("nextCursor") or payload.get("cursor")
                    data = payload.get("data")
                    if not cursor and isinstance(data, dict):
                        cursor = data.get("nextCursor") or data.get("cursor")

                if not cursor:
                    break

            # If we got rows from an ID, keep going only for Soccer because multiple soccer leagues matter.
            if all_rows and league != "Soccer":
                break

        # Fallback: if oddsAvailable=true gave nothing, try event list without oddsAvailable.
        if not all_events and not all_rows:
            for api_league_id in league_ids:
                params = {
                    "apiKey": SGO_API_KEY,
                    "leagueID": api_league_id,
                    "limit": 12,
                }

                r = requests.get(SGO_EVENTS_URL, params=params, headers=headers, timeout=(5, 20))
                urls.append(r.url)
                statuses.append(r.status_code)
                total_pages += 1

                payload = safe_json(r)

                if r.status_code != 200:
                    errors.append(f"{api_league_id} fallback: HTTP {r.status_code} {r.text[:200]}")
                    continue

                events = extract_events(payload)
                for ev in events:
                    key = str(val(ev, "eventID", "id", "gameID", default=get_matchup_name(ev) + "|" + event_time(ev)))
                    all_events[key] = (api_league_id, ev)

                if all_events and league != "Soccer":
                    break

        # Add event-only rows for events that have no parsed rows.
        matchups_with_rows = {str(r.get("Matchup", "")) for r in all_rows}
        for _, (api_league_id, ev) in all_events.items():
            matchup = get_matchup_name(ev)
            if matchup not in matchups_with_rows:
                all_rows.append(event_only_row(league, ev, api_league_id))

        return all_rows, {
            "ok": True,
            "status": statuses[-1] if statuses else "NO_REQUEST",
            "error": " | ".join(errors[:5]),
            "text": f"league_ids={league_ids}, events_seen={len(all_events)}, raw_rows={len(all_rows)}, pages={total_pages}",
            "json": None,
            "url": urls[-1] if urls else SGO_EVENTS_URL,
            "events_seen": len(all_events),
            "pages": total_pages,
            "raw_rows": len(all_rows),
        }

    except Exception as e:
        return all_rows, {
            "ok": False,
            "status": "ERROR",
            "error": f"{type(e).__name__}: {e}",
            "text": str(e),
            "json": None,
            "url": urls[-1] if urls else SGO_EVENTS_URL,
            "events_seen": len(all_events),
            "pages": total_pages,
            "raw_rows": len(all_rows),
        }



def fetch_league(league):
    try:
        rows, report = fetch_league_cached(league)
        board = score_board(rows)
        report["scored_rows"] = 0 if board.empty else len(board)
        return board, report
    except Exception as e:
        return pd.DataFrame(), {
            "ok": False,
            "status": "ERROR",
            "error": f"{type(e).__name__}: {e}",
            "text": str(e),
            "json": None,
            "url": SGO_EVENTS_URL,
            "events_seen": "",
            "pages": "",
            "raw_rows": "",
            "scored_rows": 0,
        }


def fetch_all_sports():
    frames = []
    reports = []

    for league in LEAGUES.keys():
        df, report = fetch_league(league)
        reports.append({
            "League": league,
            "Status": report.get("status"),
            "Events": report.get("events_seen", ""),
            "Pages": report.get("pages", ""),
            "Raw Rows": report.get("raw_rows", ""),
            "Rows": 0 if df.empty else len(df),
            "Games": 0 if df.empty else df["Matchup"].nunique(),
            "Error": report.get("error", ""),
            "URL": report.get("url", ""),
        })
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(), pd.DataFrame(reports)

    full = pd.concat(frames, ignore_index=True)
    full_clean = clean_board(full)

    # If global cleaning blanks everything, keep sane game lines as a fallback.
    if full_clean.empty and not full.empty:
        full_clean = full[full["Bucket"].isin(["Moneyline", "Spread", "Totals", "Event"])].copy()
        full_clean = full_clean[~full_clean.apply(is_far_future_nfl, axis=1)].copy()

    full_clean = full_clean.sort_values(["High Rate Score", "Edge %"], ascending=False)
    return ensure_schema(full_clean), pd.DataFrame(reports)


# =========================================================
# AI, ARB, PARLAY, HISTORY
# =========================================================

def add_ai_columns(df):
    if df.empty:
        return df

    ai = clean_board(df.copy())
    if ai.empty:
        return ai

    raw_score = (
        pd.to_numeric(ai["Edge %"], errors="coerce").fillna(0) * 3.0
        + (pd.to_numeric(ai["Model Probability %"], errors="coerce").fillna(50) - 50) * 0.7
        + pd.to_numeric(ai["Books Compared"], errors="coerce").fillna(0).clip(upper=12) * 1.2
        + 50
    )
    ai["AI Confidence"] = raw_score.clip(lower=0, upper=100).round(2)

    def grade(score):
        if score >= 90:
            return "A+ AI Lean"
        if score >= 78:
            return "A AI Lean"
        if score >= 65:
            return "B Watch"
        return "C Low Confidence"

    ai["AI Grade"] = ai["AI Confidence"].apply(grade)
    return ai


def ai_reason_text(row):
    reasons = []

    try:
        edge = float(row.get("Edge %", 0))
    except Exception:
        edge = 0

    try:
        model = float(row.get("Model Probability %", 0))
    except Exception:
        model = 0

    try:
        books = int(float(row.get("Books Compared", 0)))
    except Exception:
        books = 0

    try:
        tier = row.get("MLB Prop Tier", "")
    except Exception:
        tier = ""

    if edge >= 8:
        reasons.append("large edge versus the market average")
    elif edge >= 3:
        reasons.append("positive edge versus the market average")

    if model >= 60:
        reasons.append("model probability is meaningfully above implied probability")
    elif model >= 52:
        reasons.append("model probability is slightly above implied probability")

    if books >= 8:
        reasons.append(f"line compared across {books} books")
    elif books >= 3:
        reasons.append(f"line compared across {books} books")

    if str(row.get("League", "")) == "MLB" and str(tier) == "1":
        reasons.append("high-priority MLB market type")

    if row.get("Best MN App"):
        reasons.append(f"best Minnesota app route: {row.get('Best MN App')}")

    if not reasons:
        reasons.append("best clean price on the current board")

    return "; ".join(reasons).capitalize() + "."


def render_bet_card(row):
    st.markdown(
        f"""
        <div class="odds-row">
          <div>
            <div class="odds-pick">{row['Pick']}</div>
            <div class="odds-sub">
              {row['Market']} • Edge {row['Edge %']}% • Model {row['Model Probability %']}%<br>
              MN Apps: {row.get('MN App Badges', '')}<br>
              Why: {ai_reason_text(row)}
            </div>
          </div>
          <div class="odds-button">{format_odds(row['Best Odds'])}<div class="odds-book">{format_book_name(row['Best Book'])}</div></div>
          <div class="odds-button">{row['Rating']}<div class="odds-book">{row['Books Compared']} books</div></div>
          <div class="odds-button">{row['Units']}u<div class="odds-book">suggested</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_odds_board(df, title):
    st.markdown(f'<div class="market-header">{title}</div>', unsafe_allow_html=True)
    if df.empty:
        st.info("No markets in this section.")
        return

    show = choose_display_rows(df).head(80)
    for _, row in show.iterrows():
        render_bet_card(row)


def render_top_ai_cards(ai_df, count=5):
    if ai_df.empty:
        st.info("No clean AI picks found.")
        return

    show = choose_display_rows(ai_df).head(count)

    for i, (_, row) in enumerate(show.iterrows(), start=1):
        with st.container(border=True):
            st.markdown(f"### #{i} {row['Pick']}")
            st.caption(f"{row['League']} • {row['Matchup']}")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("AI Grade", row.get("AI Grade", ""))
            c2.metric("Confidence", row.get("AI Confidence", ""))
            c3.metric("Edge", f"{row['Edge %']}%")
            c4.metric("Best MN App", row.get("Best MN App", ""))
            st.write(f"**Evidence:** {ai_reason_text(row)}")
            st.write(
                f"**Best Book:** {format_book_name(row['Best Book'])} • "
                f"**Model:** {row['Model Probability %']}% • "
                f"**Suggested:** {row['Units']}u • "
                f"**Books Compared:** {row['Books Compared']}"
            )
            st.caption(f"Available MN Apps: {row.get('Available MN Apps', '')}")


def safe_key(text):
    return re.sub(r"[^a-zA-Z0-9_]+", "_", str(text))[:90]


def render_game_summary_card(sport_df, matchup, state_key="open_matchup"):
    md = sport_df[sport_df["Matchup"] == matchup]
    if md.empty:
        return

    main_md = md[md["Bucket"].isin(["Moneyline", "Spread", "Totals", "Event"])]
    best_pool = main_md if not main_md.empty else md
    best = best_pool.sort_values(["High Rate Score", "Edge %"], ascending=False).iloc[0]

    with st.container(border=True):
        st.markdown(f"### {matchup}")
        st.caption(f"{best['League']} • {best['Game Time']} • {best['Live Score']}")
        st.write(f"**Score:** {best.get('Game Score', 'Score unavailable')}")
        if str(best.get("Bucket", "")) == "Event":
            st.write("**Lines:** Odds not available yet")
        else:
            st.write(f"**Best common line:** {best['Pick']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Edge", f"{best['Edge %']}%")
        c2.metric("Lines", len(main_md))
        c3.metric("Props", int(md["Is Prop"].sum()))

        if st.button(f"📊 Open {matchup}", key=f"open_{safe_key(matchup)}", use_container_width=True):
            st.session_state[state_key] = matchup
            st.session_state["sportsbook_view"] = "detail"
            st.rerun()


def render_player_history_panel(md):
    """
    Player history research panel.
    Uses unique Streamlit keys so repeated matchups/players never crash the app.
    """
    md = ensure_schema(md)
    props = md[md["Is Prop"] == True].copy()

    if props.empty:
        st.info("No player props available for player-history research.")
        return

    props = props.drop_duplicates(subset=["Player", "Pick", "Market", "Line"], keep="first").reset_index(drop=True)

    matchup_name = str(md["Matchup"].iloc[0]) if not md.empty and "Matchup" in md.columns else "matchup"
    panel_key = safe_key(matchup_name)

    options = []
    option_map = {}

    for i, row in props.iterrows():
        label = f"{row.get('Player', '')} — {row.get('Pick', '')}"
        # Add a suffix only if label duplicates.
        if label in option_map:
            label = f"{label} #{i + 1}"
        options.append(label)
        option_map[label] = row

    selected_pick = st.selectbox(
        "Choose player prop to research",
        options,
        key=f"history_select_{panel_key}_{len(options)}",
    )

    row = option_map.get(selected_pick)
    if row is None:
        st.warning("Could not load that player prop.")
        return

    links = player_history_links(row)

    st.markdown(f"#### Research: {row.get('Player', '')}")
    st.write(f"**Pick:** {row.get('Pick', '')}")
    st.write(f"**Matchup:** {row.get('Matchup', '')}")
    st.write(f"**Market:** {row.get('Market', '')}")

    if not links:
        st.info("No history links available for this player.")
        return

    cols = st.columns(min(4, len(links)))
    for idx, (label, url) in enumerate(links.items()):
        with cols[idx % len(cols)]:
            st.link_button(label, url, use_container_width=True)

    st.markdown('<div class="market-header">Player History / Matchup Research</div>', unsafe_allow_html=True)
    st.caption(
        "This section links to matchup-history research. The app does not make up historical results. "
        "For exact all-time batter-vs-pitcher or player-vs-team logs, connect MLB StatsAPI/Statcast in the next build."
    )

    if props.empty:
        st.info("No player props available for matchup research.")
        return

    selected_pick = st.selectbox("Choose player prop to research", props["Pick"].tolist(), key=f"history_{md['Matchup'].iloc[0]}_{safe_key(str(selected_pick))}")
    row = props[props["Pick"] == selected_pick].iloc[0]

    st.write(f"**Research target:** {row['Pick']}")
    st.write(f"**Evidence starter:** {ai_reason_text(row)}")

    links = player_history_links(row)
    cols = st.columns(max(1, min(5, len(links))))
    for col, (label, url) in zip(cols, links.items()):
        col.link_button(label, url, use_container_width=True)


def render_matchup_detail(df, matchup):
    md = df[df["Matchup"] == matchup].copy()
    if md.empty:
        st.warning("No markets found for this matchup.")
        return

    first = md.iloc[0]
    st.markdown(f"## {matchup}")
    st.caption(f"{first['League']} • {first['Game Time']} • {first['Live Score']}")
    st.info(f"Live/In-Game Score: {first.get('Game Score', 'Score unavailable')}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lines", len(md[md["Bucket"].isin(["Moneyline", "Spread", "Totals"])]))
    c2.metric("Props", int(md["Is Prop"].sum()))
    c3.metric("Best Edge", f"{md['Edge %'].max()}%")
    c4.metric("Best Score", md["High Rate Score"].max())

    l1, l2, l3 = st.columns(3)
    l1.link_button("News", first["News"], use_container_width=True)
    l2.link_button("Preview", first["Preview"], use_container_width=True)
    l3.link_button("Injuries", first["Injuries"], use_container_width=True)

    st.markdown("### Betting Lines")
    render_odds_board(md[md["Bucket"].isin(["Moneyline", "Spread", "Totals"])], "Game Lines")
    render_odds_board(md[md["Bucket"] == "Player Props"], "Player Props")

    st.divider()
    research_tabs = st.tabs(["AI Evidence", "Arbitrage", "Player History"])

    with research_tabs[0]:
        ai = add_ai_columns(md).sort_values(["AI Confidence", "Edge %"], ascending=False)
        ai = ai.drop_duplicates(subset=["Matchup", "Pick Key", "Market", "Line"], keep="first")
        render_top_ai_cards(ai, count=5)
        save_today_top5_ai_picks_v2(ai)

    with research_tabs[1]:
        arbs = find_arbitrage(md)
        if arbs.empty:
            st.info("No clean arbitrage found for this matchup.")
        else:
            arb_cols = [
                "Profit %", "League", "Matchup", "Market", "Line",
                "Side A", "Book A", "Side B", "Book B",
                "Best MN App", "Available MN Apps",
            ]
            safe_dataframe(arbs, cols=arb_cols, use_container_width=True, hide_index=True)

    with research_tabs[2]:
        render_player_history_panel(md)


def ensure_loaded():
    if "all_df" not in st.session_state:
        st.session_state["all_df"] = pd.DataFrame()
    if "reports" not in st.session_state:
        st.session_state["reports"] = pd.DataFrame()


def auto_load_once():
    """
    Lightweight startup. Do not scan all sports at launch.
    """
    ensure_loaded()

    if "auto_loading_done" not in st.session_state:
        st.session_state["auto_loading_done"] = True


def header():
    st.markdown(
        """
        <div class="hero">
            <div class="hero-title">CD BETTING</div>
            <div class="hero-sub">Sportsbook edge scanner • AI tracker • robust DFS builder</div>
            <span class="pill">Common markets only</span>
            <span class="pill">No fake odds</span>
            <span class="pill">AI confidence 0-100</span>
            <span class="pill">History links</span>
        </div>
        """,
        unsafe_allow_html=True,
    )



def find_arbitrage(df):
    """
    Safe clean arbitrage finder.
    Must be defined before Dashboard calls arbs = find_arbitrage(df).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    work = clean_board(df.copy())
    if work.empty:
        return pd.DataFrame()

    required = ["Matchup", "Market", "Line", "Side", "Best Odds", "Best Book", "Book Implied %"]
    if any(c not in work.columns for c in required):
        return pd.DataFrame()

    work["SideNorm"] = work["Side"].astype(str).str.lower().str.strip()
    work["MarketKey"] = (
        work["Matchup"].astype(str)
        + "|"
        + work["Market"].astype(str)
        + "|"
        + work["Line"].astype(str)
    )

    arbs = []

    for _, group in work.groupby("MarketKey"):
        sides = sorted([s for s in group["SideNorm"].dropna().unique() if s])
        pairs = [("over", "under"), ("home", "away")]

        if len(sides) == 2:
            pairs.append((sides[0], sides[1]))

        checked = set()

        for a_side, b_side in pairs:
            if (a_side, b_side) in checked:
                continue

            checked.add((a_side, b_side))

            a = group[group["SideNorm"] == a_side]
            b = group[group["SideNorm"] == b_side]

            if a.empty or b.empty:
                continue

            best_a = a.sort_values("Book Implied %", ascending=True).iloc[0]
            best_b = b.sort_values("Book Implied %", ascending=True).iloc[0]

            if str(best_a["Best Book"]).lower() == str(best_b["Best Book"]).lower():
                continue

            try:
                inv = (1 / american_to_decimal(best_a["Best Odds"])) + (1 / american_to_decimal(best_b["Best Odds"]))
            except Exception:
                continue

            if inv < 1:
                profit_pct = round((1 - inv) * 100, 2)

                if profit_pct > 20:
                    continue

                bucket = str(best_a.get("Bucket", "Other"))
                mn_best, mn_apps = recommend_mn_apps(
                    bucket,
                    f"{best_a.get('Pick', '')} / {best_b.get('Pick', '')}",
                    best_a.get("Market", ""),
                    bool(best_a.get("Is Prop", False) or best_b.get("Is Prop", False)),
                )

                arbs.append({
                    "Profit %": profit_pct,
                    "League": best_a.get("League", ""),
                    "Matchup": best_a.get("Matchup", ""),
                    "Market": best_a.get("Market", ""),
                    "Line": best_a.get("Line", ""),
                    "Side A": best_a.get("Pick", ""),
                    "Book A": best_a.get("Best Book", ""),
                    "Side B": best_b.get("Pick", ""),
                    "Book B": best_b.get("Best Book", ""),
                    "Best MN App": mn_best,
                    "Available MN Apps": mn_apps,
                })

    if not arbs:
        return pd.DataFrame()

    return pd.DataFrame(arbs).sort_values("Profit %", ascending=False)


find_arbs = find_arbitrage
build_arbitrage = find_arbitrage



def view_cols(df):
    df = ensure_schema(df)
    cols = [
        "League", "Game Time", "Matchup", "Live Score", "Game Score",
        "Bucket", "Market", "Player", "Bet Side", "Prop Line", "Pick",
        "Best Odds", "Best Book", "Best MN App", "Available MN Apps",
        "Book Implied %", "Market Avg %", "Edge %",
        "Model Probability %", "High Rate Score", "Priority Score",
        "MLB Prop Tier", "Rating", "Units", "Books Compared",
    ]
    return df[safe_cols(df, cols)]

    cols = [
        "League",
        "Game Time",
        "Matchup",
        "Live Score",
        "Game Score",
        "Bucket",
        "Market",
        "Player",
        "Bet Side",
        "Prop Line",
        "Pick",
        "Best Odds",
        "Best Book",
        "Best MN App",
        "Available MN Apps",
        "Book Implied %",
        "Market Avg %",
        "Edge %",
        "Model Probability %",
        "High Rate Score",
        "Priority Score",
        "MLB Prop Tier",
        "Rating",
        "Units",
        "Books Compared",
    ]

    existing = [c for c in cols if c in df.columns]
    if not existing:
        return df

    return df[existing]



def render_sports_rail(df, selected_sport):
    """
    Left sports count rail. Safe fallback so Sportsbook page never crashes.
    """
    sports = list(LEAGUES.keys()) if "LEAGUES" in globals() else ["MLB", "WNBA", "NBA", "NFL", "NHL", "UFC/MMA", "Soccer"]
    rows = []

    for sport in sports:
        games = 0
        if df is not None and not df.empty and "League" in df.columns and "Matchup" in df.columns:
            try:
                games = df[df["League"].astype(str).eq(str(sport))]["Matchup"].nunique()
            except Exception:
                games = 0

        hot = " hot" if str(sport) == str(selected_sport) else ""
        emoji = SPORT_EMOJI.get(sport, "") if "SPORT_EMOJI" in globals() else ""
        rows.append(f'<div class="rail-item{hot}"><span>{emoji} {sport}</span><span>{games} games</span></div>')

    st.markdown(
        '<div class="left-rail"><div class="rail-title">Sports</div>' + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )



def player_history_links(row):
    """
    Safe history-link builder. Does not fake stats.
    Opens research links for player-vs-team / matchup / splits.
    """
    player = str(row.get("Player", "")).strip()
    matchup = str(row.get("Matchup", "")).strip()
    market = str(row.get("Market", "")).strip()

    if not player:
        return {}

    q1 = quote_plus(f"{player} game log vs {matchup}")
    q2 = quote_plus(f"{player} matchup history {matchup}")
    q3 = quote_plus(f"{player} splits {market} vs opponent")
    q4 = quote_plus(f"{player} recent game log {market}")

    links = {
        "Game Logs": f"https://www.google.com/search?q={q1}",
        "Matchup History": f"https://www.google.com/search?q={q2}",
        "Splits": f"https://www.google.com/search?q={q3}",
        "Recent Form": f"https://www.google.com/search?q={q4}",
    }

    if str(row.get("League", "")) == "MLB":
        links["Baseball Savant"] = f"https://baseballsavant.mlb.com/search?search={quote_plus(player)}"
        links["StatMuse"] = f"https://www.google.com/search?q={quote_plus(player + ' vs pitcher history')}"

    return links




def dfs_projection_score(row):
    """
    Converts prop edge/model data into a simple DFS projection score.
    This is not a salary-site official projection. It is a research estimate.
    """
    try:
        model = float(row.get("Model Probability %", 50))
    except Exception:
        model = 50

    try:
        edge = float(row.get("Edge %", 0))
    except Exception:
        edge = 0

    try:
        line = float(row.get("Line", 0))
    except Exception:
        line = 0

    market = str(row.get("Market", "")).lower()

    multiplier = 1.0
    if "points" in market:
        multiplier = 1.0
    elif "rebounds" in market:
        multiplier = 1.2
    elif "assists" in market:
        multiplier = 1.5
    elif "total bases" in market:
        multiplier = 2.0
    elif "hits" in market:
        multiplier = 3.0
    elif "strikeouts" in market:
        multiplier = 2.0
    elif "shots" in market:
        multiplier = 1.4
    elif "goals" in market or "home runs" in market:
        multiplier = 6.0

    base = max(0.5, line) * multiplier
    confidence_boost = (model - 50) / 10
    edge_boost = edge / 4

    return round(max(0, base + confidence_boost + edge_boost), 2)


def build_dfs_pool(df, league_filter=None):
    if df is None or df.empty:
        return pd.DataFrame()

    pool = clean_user_facing_board(df, hide_low_interest=True)
    pool = pool[pool["Is Prop"] == True].copy()

    if league_filter and league_filter != "All":
        pool = pool[pool["League"] == league_filter].copy()

    if pool.empty:
        return pool

    pool["DFS Projection"] = pool.apply(dfs_projection_score, axis=1)
    pool["DFS Value"] = (
        pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0)
        + pd.to_numeric(pool["Edge %"], errors="coerce").fillna(0) * 0.55
        + pd.to_numeric(pool["Model Probability %"], errors="coerce").fillna(50) * 0.05
    ).round(2)

    pool["DFS Confidence"] = (
        pd.to_numeric(pool["Model Probability %"], errors="coerce").fillna(50)
        + pd.to_numeric(pool["Edge %"], errors="coerce").fillna(0) * 1.5
    ).clip(0, 100).round(1)

    # DFS V2 estimated fields. Replace later with real DraftKings/FanDuel salary and ownership feeds.
    pool["Salary Estimate"] = (
        3000
        + pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0) * 450
        + pd.to_numeric(pool["DFS Confidence"], errors="coerce").fillna(50) * 18
    ).clip(3000, 12000).round(0).astype(int)

    pool["Ownership Estimate %"] = (
        pd.to_numeric(pool["DFS Confidence"], errors="coerce").fillna(50) * 0.35
        + pd.to_numeric(pool["Edge %"], errors="coerce").fillna(0) * 0.6
    ).clip(1, 45).round(1)

    pool["Ceiling"] = (
        pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0) * 1.45
        + pd.to_numeric(pool["Edge %"], errors="coerce").fillna(0) * 0.25
    ).round(2)

    pool["Floor"] = (
        pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0) * 0.55
    ).round(2)

    pool["Leverage"] = (
        pd.to_numeric(pool["DFS Value"], errors="coerce").fillna(0)
        - pd.to_numeric(pool["Ownership Estimate %"], errors="coerce").fillna(0) * 0.35
    ).round(2)

    pool = ensure_schema(pool.drop_duplicates(subset=["Player", "Matchup", "Market", "Line"], keep="first"))
    return pool.sort_values(["DFS Value", "Leverage", "DFS Projection", "Edge %"], ascending=False).head(MAX_DFS_POOL_ROWS)


def build_dfs_lineups(df, league_filter="All", lineup_size=6, max_lineups=8):
    pool = build_dfs_pool(df, league_filter)
    if pool.empty:
        return []

    players = pool.to_dict("records")
    lineups = []

    # Greedy diversified builder: start with top candidates, avoid duplicate players,
    # avoid too many from the same matchup unless necessary.
    for start_idx in range(min(max_lineups * 4, len(players))):
        lineup = []
        used_players = set()
        matchup_counts = {}

        for cand in players[start_idx:] + players[:start_idx]:
            player = str(cand.get("Player", "")).strip()
            matchup = str(cand.get("Matchup", "")).strip()

            if not player or player in used_players:
                continue

            if matchup_counts.get(matchup, 0) >= 2:
                continue

            lineup.append(cand)
            used_players.add(player)
            matchup_counts[matchup] = matchup_counts.get(matchup, 0) + 1

            if len(lineup) >= lineup_size:
                break

        if len(lineup) == lineup_size:
            total_proj = round(sum(float(x.get("DFS Projection", 0)) for x in lineup), 2)
            avg_conf = round(sum(float(x.get("DFS Confidence", 0)) for x in lineup) / lineup_size, 1)
            total_edge = round(sum(float(x.get("Edge %", 0)) for x in lineup), 2)

            key = tuple(sorted(x.get("Player", "") for x in lineup))
            if key not in [l["Key"] for l in lineups]:
                lineups.append({
                    "Key": key,
                    "Players": lineup,
                    "Projected Score": total_proj,
                    "Avg Confidence": avg_conf,
                    "Total Edge": total_edge,
                })

    lineups = sorted(lineups, key=lambda x: (x["Projected Score"], x["Avg Confidence"], x["Total Edge"]), reverse=True)
    return lineups[:max_lineups]


def render_dfs_lineups(lineups):
    if not lineups:
        st.warning("No DFS lineups could be built from the current player-prop pool.")
        return

    for idx, lineup in enumerate(lineups, start=1):
        with st.container(border=True):
            st.markdown(f"### AI DFS Lineup #{idx}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Projected Score", lineup["Projected Score"])
            c2.metric("Avg Confidence", f"{lineup['Avg Confidence']}%")
            c3.metric("Total Edge", f"{lineup['Total Edge']}%")

            rows = []
            for p in lineup["Players"]:
                rows.append({
                    "Player": p.get("Player", ""),
                    "League": p.get("League", ""),
                    "Matchup": p.get("Matchup", ""),
                    "Market": p.get("Market", ""),
                    "Line": clean_prop_line(p.get("Line", "")) if "clean_prop_line" in globals() else p.get("Line", ""),
                    "Pick": p.get("Pick", ""),
                    "Projection": p.get("DFS Projection", ""),
                    "Salary Estimate": p.get("Salary Estimate", ""),
                    "Ownership %": p.get("Ownership Estimate %", ""),
                    "Ceiling": p.get("Ceiling", ""),
                    "Floor": p.get("Floor", ""),
                    "Leverage": p.get("Leverage", ""),
                    "Confidence": p.get("DFS Confidence", ""),
                    "Best MN App": p.get("Best MN App", ""),
                    "Best Book": p.get("Best Book", ""),
                })

            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption("DFS builder uses current prop lines, edge, and model probability as research projections. It is not a guaranteed lineup optimizer.")




def load_one_sport_to_state(league):
    df, report = fetch_league(league)
    df = ensure_schema(df)

    existing = ensure_schema(st.session_state.get("all_df", pd.DataFrame()))

    # Remove old rows for this league, append fresh rows.
    if not existing.empty and "League" in existing.columns:
        existing = existing[existing["League"] != league].copy()

    merged = pd.concat([existing, df], ignore_index=True) if not df.empty else existing
    st.session_state["all_df"] = ensure_schema(merged)

    reports = st.session_state.get("reports", pd.DataFrame())
    new_report = pd.DataFrame([{
        "League": league,
        "Status": report.get("status"),
        "Events": report.get("events_seen", ""),
        "Pages": report.get("pages", ""),
        "Raw Rows": report.get("raw_rows", ""),
        "Rows": 0 if df.empty else len(df),
        "Games": 0 if df.empty else df["Matchup"].nunique(),
        "Error": report.get("error", ""),
        "URL": report.get("url", ""),
    }])

    if isinstance(reports, pd.DataFrame) and not reports.empty and "League" in reports.columns:
        reports = reports[reports["League"] != league].copy()
        reports = pd.concat([reports, new_report], ignore_index=True)
    else:
        reports = new_report

    st.session_state["reports"] = reports



def parlay_leg_label(row):
    return (
        f"{row.get('League', '')} — {row.get('Matchup', '')}\n"
        f"{row.get('Pick', '')}\n"
        f"Market: {row.get('Market', '')} | Line: {clean_prop_line(row.get('Line', '')) if 'clean_prop_line' in globals() else row.get('Line', '')}\n"
        f"Book: {format_book_name(row.get('Best Book', '')) if 'format_book_name' in globals() else row.get('Best Book', '')} | "
        f"MN App: {row.get('Best MN App', '')} | "
        f"Edge: {row.get('Edge %', 0)}% | Odds: {format_odds(row.get('Best Odds', 0)) if 'format_odds' in globals() else row.get('Best Odds', 0)}"
    )


def build_parlays(df, legs=3):
    """
    Safe V58 parlay builder.
    Avoids duplicate matchups/players, removes junk props through clean_user_facing_board,
    and always returns a dataframe instead of crashing.
    """
    df = ensure_schema(df)
    if df.empty:
        return pd.DataFrame()

    try:
        work = clean_user_facing_board(df, hide_low_interest=True)
    except Exception:
        work = df.copy()

    work = ensure_schema(work)

    if work.empty:
        return pd.DataFrame()

    # Only use decent edges and non-pass ratings when possible.
    edge = pd.to_numeric(work["Edge %"], errors="coerce").fillna(0)
    books = pd.to_numeric(work["Books Compared"], errors="coerce").fillna(0)

    filtered = work[(edge >= 1.5) & (books >= 1)].copy()
    if filtered.empty:
        filtered = work.copy()

    if "Priority Score" in filtered.columns:
        filtered = filtered.sort_values(["Priority Score", "High Rate Score", "Edge %"], ascending=False)
    else:
        filtered = filtered.sort_values(["High Rate Score", "Edge %"], ascending=False)

    # De-dupe same betting idea.
    filtered = filtered.drop_duplicates(subset=["Matchup", "Pick Key", "Market", "Line"], keep="first").head(80)

    rows = filtered.to_dict("records")
    parlays = []

    for combo in itertools.combinations(rows, int(legs)):
        # Avoid same matchup multiple times.
        matchups = [str(x.get("Matchup", "")) for x in combo]
        if len(matchups) != len(set(matchups)):
            continue

        # Avoid same player multiple times.
        players = [str(x.get("Player", "")).strip() for x in combo if str(x.get("Player", "")).strip()]
        if len(players) != len(set(players)):
            continue

        dec_total = 1.0
        hit = 1.0
        total_edge = 0.0

        valid = True
        for leg in combo:
            try:
                dec_total *= american_to_decimal(leg.get("Best Odds", 0))
                hit *= max(0.04, min(0.88, float(leg.get("Model Probability %", 50)) / 100))
                total_edge += float(leg.get("Edge %", 0))
            except Exception:
                valid = False
                break

        if not valid:
            continue

        row = {
            "Legs": int(legs),
            "Combined Odds": decimal_to_american(dec_total) if "decimal_to_american" in globals() else round(dec_total, 2),
            "Estimated Hit %": round(hit * 100, 2),
            "Total Edge": round(total_edge, 2),
            "Avg Edge": round(total_edge / int(legs), 2),
        }

        for i, leg in enumerate(combo, 1):
            row[f"Leg {i}"] = parlay_leg_label(leg)
            row[f"Leg {i} Pick"] = leg.get("Pick", "")
            row[f"Leg {i} Matchup"] = leg.get("Matchup", "")
            row[f"Leg {i} Market"] = leg.get("Market", "")
            row[f"Leg {i} Line"] = clean_prop_line(leg.get("Line", "")) if "clean_prop_line" in globals() else leg.get("Line", "")
            row[f"Leg {i} Book"] = leg.get("Best Book", "")
            row[f"Leg {i} MN App"] = leg.get("Best MN App", "")
            row[f"Leg {i} Edge"] = leg.get("Edge %", 0)

        parlays.append(row)

        if len(parlays) >= 60:
            break

    if not parlays:
        return pd.DataFrame()

    return pd.DataFrame(parlays).sort_values(["Estimated Hit %", "Avg Edge", "Total Edge"], ascending=False)


def render_parlay_cards(parlays, legs):
    parlays = ensure_schema(parlays) if isinstance(parlays, pd.DataFrame) else parlays

    if parlays is None or (isinstance(parlays, pd.DataFrame) and parlays.empty):
        st.warning("No clean parlays built from the current board.")
        return

    for _, row in parlays.head(10).iterrows():
        with st.container(border=True):
            st.markdown(f"### {int(legs)}-Leg Suggested Parlay")

            c1, c2, c3 = st.columns(3)
            c1.metric("Combined Odds", format_odds(row.get("Combined Odds", 0)) if "format_odds" in globals() else row.get("Combined Odds", 0))
            c2.metric("Estimated Hit %", f"{row.get('Estimated Hit %', 0)}%")
            c3.metric("Total Edge", f"{row.get('Total Edge', 0)}%")

            for i in range(1, int(legs) + 1):
                st.markdown(f"#### Leg {i}")
                st.write(f"**Pick:** {row.get(f'Leg {i} Pick', '')}")
                st.write(f"**Matchup:** {row.get(f'Leg {i} Matchup', '')}")
                st.write(f"**Market:** {row.get(f'Leg {i} Market', '')}")
                st.write(f"**Line:** {row.get(f'Leg {i} Line', '')}")
                st.write(f"**Book:** {format_book_name(row.get(f'Leg {i} Book', '')) if 'format_book_name' in globals() else row.get(f'Leg {i} Book', '')}")
                st.write(f"**Best MN App:** {row.get(f'Leg {i} MN App', '')}")
                st.write(f"**Edge:** {row.get(f'Leg {i} Edge', '')}%")

            st.divider()



def dfs_platform_salary(row, platform="DraftKings"):
    """
    Estimated salary until real DFS salary feeds are connected.
    DraftKings default cap: 50,000.
    FanDuel default cap: 60,000.
    """
    try:
        proj = float(row.get("DFS Projection", 0))
    except Exception:
        proj = 0

    try:
        conf = float(row.get("DFS Confidence", 50))
    except Exception:
        conf = 50

    try:
        edge = float(row.get("Edge %", 0))
    except Exception:
        edge = 0

    if platform == "FanDuel":
        salary = 3500 + proj * 520 + conf * 20 + edge * 30
        return int(max(3500, min(15000, round(salary / 100) * 100)))

    # DraftKings
    salary = 3000 + proj * 450 + conf * 18 + edge * 25
    return int(max(3000, min(12000, round(salary / 100) * 100)))


def dfs_default_budget(platform):
    return 60000 if platform == "FanDuel" else 50000


def dfs_platform_positions(row, platform="DraftKings"):
    """
    Simple position estimate from market type.
    Real positions can be added later from a DFS salary feed.
    """
    league = str(row.get("League", ""))
    market = str(row.get("Market", "")).lower()

    if league == "MLB":
        if "strikeout" in market or "earned run" in market or "hits allowed" in market:
            return "P"
        return "UTIL"

    if league in ["NBA", "WNBA"]:
        return "UTIL"

    if league == "NFL":
        if "passing" in market:
            return "QB"
        if "rushing" in market:
            return "RB/FLEX"
        if "receiving" in market or "reception" in market:
            return "WR/TE/FLEX"
        if "touchdown" in market:
            return "FLEX"
        return "FLEX"

    if league == "NHL":
        if "save" in market:
            return "G"
        return "UTIL"

    return "UTIL"


def optimize_dfs_lineups(df, platform="DraftKings", budget=50000, league_filter="All", lineup_size=6, max_lineups=8):
    """
    Budget-based greedy optimizer.
    Builds the highest value lineups under salary cap while avoiding duplicate players.
    """
    pool = build_dfs_pool(df, league_filter)
    pool = ensure_schema(pool)

    if pool.empty:
        return []

    pool["Platform"] = platform
    pool["Salary"] = pool.apply(lambda r: dfs_platform_salary(r, platform), axis=1)
    pool["Position"] = pool.apply(lambda r: dfs_platform_positions(r, platform), axis=1)

    # Better optimizer score: projection + leverage + confidence, adjusted for salary.
    pool["Optimizer Score"] = (
        pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0) * 1.15
        + pd.to_numeric(pool["Leverage"], errors="coerce").fillna(0) * 0.65
        + pd.to_numeric(pool["DFS Confidence"], errors="coerce").fillna(50) * 0.08
        + pd.to_numeric(pool["Edge %"], errors="coerce").fillna(0) * 0.35
    )

    pool["Value Per $1K"] = (
        pd.to_numeric(pool["Optimizer Score"], errors="coerce").fillna(0)
        / (pd.to_numeric(pool["Salary"], errors="coerce").fillna(9999) / 1000)
    ).round(3)

    pool = pool.sort_values(["Value Per $1K", "Optimizer Score", "DFS Projection"], ascending=False)
    players = pool.to_dict("records")

    lineups = []

    # Multiple starts give diversified builds.
    for start_idx in range(min(len(players), max_lineups * 10)):
        lineup = []
        used_players = set()
        matchup_counts = {}
        salary_total = 0

        ordered = players[start_idx:] + players[:start_idx]

        for cand in ordered:
            player = str(cand.get("Player", "")).strip()
            matchup = str(cand.get("Matchup", "")).strip()
            salary = int(cand.get("Salary", 0))

            if not player or player in used_players:
                continue

            if matchup_counts.get(matchup, 0) >= 2:
                continue

            if salary_total + salary > int(budget):
                continue

            lineup.append(cand)
            used_players.add(player)
            salary_total += salary
            matchup_counts[matchup] = matchup_counts.get(matchup, 0) + 1

            if len(lineup) >= int(lineup_size):
                break

        if len(lineup) == int(lineup_size):
            total_proj = round(sum(float(x.get("DFS Projection", 0)) for x in lineup), 2)
            total_score = round(sum(float(x.get("Optimizer Score", 0)) for x in lineup), 2)
            avg_conf = round(sum(float(x.get("DFS Confidence", 0)) for x in lineup) / int(lineup_size), 1)
            total_edge = round(sum(float(x.get("Edge %", 0)) for x in lineup), 2)
            remaining = int(budget) - salary_total

            key = tuple(sorted(x.get("Player", "") for x in lineup))
            if key not in [l["Key"] for l in lineups]:
                lineups.append({
                    "Key": key,
                    "Platform": platform,
                    "Budget": int(budget),
                    "Salary Used": salary_total,
                    "Salary Left": remaining,
                    "Players": lineup,
                    "Projected Score": total_proj,
                    "Optimizer Score": total_score,
                    "Avg Confidence": avg_conf,
                    "Total Edge": total_edge,
                })

    return sorted(
        lineups,
        key=lambda x: (x["Projected Score"], x["Optimizer Score"], -x["Salary Left"], x["Avg Confidence"]),
        reverse=True,
    )[:max_lineups]


def render_budget_dfs_lineups(lineups):
    if not lineups:
        st.warning("No lineup fit under that budget. Raise the budget, lower lineup size, or load more sports.")
        return

    for idx, lineup in enumerate(lineups, start=1):
        with st.container(border=True):
            st.markdown(f"### {lineup['Platform']} AI Lineup #{idx}")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Projected", lineup["Projected Score"])
            c2.metric("Salary Used", f"${lineup['Salary Used']:,}")
            c3.metric("Salary Left", f"${lineup['Salary Left']:,}")
            c4.metric("Confidence", f"{lineup['Avg Confidence']}%")

            rows = []
            for p in lineup["Players"]:
                rows.append({
                    "Pos": p.get("Position", ""),
                    "Player": p.get("Player", ""),
                    "League": p.get("League", ""),
                    "Matchup": p.get("Matchup", ""),
                    "Pick Used": p.get("Pick", ""),
                    "Salary": p.get("Salary", ""),
                    "Projection": p.get("DFS Projection", ""),
                    "Value/$1K": p.get("Value Per $1K", ""),
                    "Ceiling": p.get("Ceiling", ""),
                    "Floor": p.get("Floor", ""),
                    "Leverage": p.get("Leverage", ""),
                    "Best MN App": p.get("Best MN App", ""),
                })

            safe_dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)



# =========================================================
# AI PICK TRACKER
# =========================================================

AI_TRACKER_PATH = Path.cwd() / "ai_top5_pick_tracker.csv"


def today_ct_string():
    return datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")


def ai_pick_id(row, date_str=None):
    date_str = date_str or today_ct_string()
    raw = "|".join([
        date_str,
        str(row.get("League", "")),
        str(row.get("Matchup", "")),
        str(row.get("Market", "")),
        str(row.get("Line", "")),
        str(row.get("Pick", "")),
        str(row.get("Best Odds", "")),
    ])
    return re.sub(r"[^a-zA-Z0-9_]+", "_", raw)[:180]


def load_ai_tracker():
    if not AI_TRACKER_PATH.exists():
        return pd.DataFrame(columns=[
            "Pick ID", "Date", "League", "Game Time", "Matchup", "Market", "Player",
            "Line", "Pick", "Best Odds", "Best Book", "Best MN App",
            "Edge %", "Model Probability %", "AI Confidence",
            "Result", "Units Risked", "Units Won", "Graded At"
        ])

    try:
        df = pd.read_csv(AI_TRACKER_PATH)
    except Exception:
        return pd.DataFrame(columns=[
            "Pick ID", "Date", "League", "Game Time", "Matchup", "Market", "Player",
            "Line", "Pick", "Best Odds", "Best Book", "Best MN App",
            "Edge %", "Model Probability %", "AI Confidence",
            "Result", "Units Risked", "Units Won", "Graded At"
        ])

    for col in [
        "Pick ID", "Date", "League", "Game Time", "Matchup", "Market", "Player",
        "Line", "Pick", "Best Odds", "Best Book", "Best MN App",
        "Edge %", "Model Probability %", "AI Confidence",
        "Result", "Units Risked", "Units Won", "Graded At"
    ]:
        if col not in df.columns:
            df[col] = ""

    return df


def save_ai_tracker(df):
    try:
        df.to_csv(AI_TRACKER_PATH, index=False)
    except Exception as e:
        st.warning(f"Could not save AI tracker file: {e}")


def units_profit_from_result(result, odds, risk=1.0):
    result = str(result).lower()
    if result == "win":
        try:
            return round((american_to_decimal(float(odds)) - 1) * float(risk), 2)
        except Exception:
            return round(1.0 * float(risk), 2)
    if result == "loss":
        return round(-1.0 * float(risk), 2)
    if result == "push":
        return 0.0
    return 0.0


def save_today_top5_ai_picks(ai_df):
    """
    Saves today's Top 5 AI picks once. Does not overwrite graded results.
    """
    tracker = load_ai_tracker()
    existing_ids = set(tracker["Pick ID"].astype(str).tolist()) if not tracker.empty else set()
    today = today_ct_string()

    rows = []
    top5 = ensure_schema(ai_df).head(5)

    for _, row in top5.iterrows():
        pid = ai_pick_id(row, today)
        if pid in existing_ids:
            continue

        rows.append({
            "Pick ID": pid,
            "Date": today,
            "League": row.get("League", ""),
            "Game Time": row.get("Game Time", ""),
            "Matchup": row.get("Matchup", ""),
            "Market": row.get("Market", ""),
            "Player": row.get("Player", ""),
            "Line": row.get("Line", ""),
            "Pick": row.get("Pick", ""),
            "Best Odds": row.get("Best Odds", ""),
            "Best Book": row.get("Best Book", ""),
            "Best MN App": row.get("Best MN App", ""),
            "Edge %": row.get("Edge %", 0),
            "Model Probability %": row.get("Model Probability %", 50),
            "AI Confidence": row.get("AI Confidence", 0),
            "Result": "Pending",
            "Units Risked": 1.0,
            "Units Won": 0.0,
            "Graded At": "",
        })

    if rows:
        tracker = pd.concat([tracker, pd.DataFrame(rows)], ignore_index=True)
        if "Pick ID" in tracker.columns:
            tracker = tracker.drop_duplicates(subset=["Pick ID"], keep="last")
        save_ai_tracker(tracker)

    return load_ai_tracker()


def ai_tracker_summary(tracker):
    if tracker.empty:
        return {
            "Picks": 0, "Wins": 0, "Losses": 0, "Pushes": 0,
            "Pending": 0, "Win %": "0.0%", "Units": 0.0, "ROI": "0.0%"
        }

    t = tracker.copy()
    result = t["Result"].astype(str).str.lower()

    graded = t[result.isin(["win", "loss", "push"])].copy()
    wins = int((result == "win").sum())
    losses = int((result == "loss").sum())
    pushes = int((result == "push").sum())
    pending = int((result == "pending").sum())

    decisions = wins + losses
    win_pct = round((wins / decisions) * 100, 1) if decisions else 0.0

    units = pd.to_numeric(t["Units Won"], errors="coerce").fillna(0).sum()
    risked = pd.to_numeric(graded["Units Risked"], errors="coerce").fillna(0).sum() if not graded.empty else 0
    roi = round((units / risked) * 100, 1) if risked else 0.0

    return {
        "Picks": len(t),
        "Wins": wins,
        "Losses": losses,
        "Pushes": pushes,
        "Pending": pending,
        "Win %": f"{win_pct}%",
        "Units": round(units, 2),
        "ROI": f"{roi}%",
    }


def render_ai_tracker_v2():
    st.subheader("Top 5 AI Pick Tracker")

    tracker = load_ai_tracker()
    if tracker is None or tracker.empty:
        st.info("No AI picks saved yet. Load the board and save today's Top 5 AI picks.")
        return

    # Make sure required tracker columns exist.
    tracker = tracker.copy()
    needed = [
        "Pick ID", "Date", "League", "Game Time", "Matchup", "Pick",
        "Best Odds", "Best Book", "Best MN App", "AI Confidence",
        "Edge %", "Units Risked", "Units Won", "Graded At", "Result"
    ]
    for col in needed:
        if col not in tracker.columns:
            tracker[col] = ""

    # Remove duplicate pick IDs before any widgets are created.
    tracker["Pick ID"] = tracker["Pick ID"].astype(str)
    tracker = tracker.drop_duplicates(subset=["Pick ID"], keep="last").reset_index(drop=True)

    # Save cleaned tracker so old duplicate rows stop coming back.
    try:
        save_ai_tracker(tracker)
    except Exception:
        pass

    summary = ai_tracker_summary(tracker)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Record", f"{summary['Wins']}-{summary['Losses']}-{summary['Pushes']}")
    c2.metric("Win %", summary["Win %"])
    c3.metric("Units", summary["Units"])
    c4.metric("ROI", summary["ROI"])
    c5.metric("Pending", summary["Pending"])

    with st.expander("Grade pending picks"):
        pending = tracker[tracker["Result"].astype(str).str.lower().eq("pending")].copy().reset_index(drop=True)

        if pending.empty:
            st.success("No pending picks to grade.")
        else:
            for idx, row in pending.iterrows():
                pick_id = str(row.get("Pick ID", ""))
                row_key = unique_widget_key(
                    "grade",
                    idx,
                    pick_id,
                    row.get("Date", ""),
                    row.get("Matchup", ""),
                    row.get("Pick", ""),
                )

                with st.container(border=True):
                    st.write(f"**{row.get('Pick', '')}**")
                    st.caption(f"{row.get('League', '')} • {row.get('Matchup', '')} • {row.get('Date', '')}")

                    c_res, c_save = st.columns([2, 1])
                    with c_res:
                        result = st.selectbox(
                            "Result",
                            ["Pending", "Win", "Loss", "Push"],
                            key=unique_widget_key("grade_result", row_key),
                        )
                    with c_save:
                        if st.button("Save", key=unique_widget_key("grade_save", row_key), use_container_width=True):
                            full_tracker = load_ai_tracker()
                            full_tracker["Pick ID"] = full_tracker["Pick ID"].astype(str)

                            mask = full_tracker["Pick ID"].eq(pick_id)
                            if not mask.any():
                                mask = full_tracker.index == idx

                            full_tracker.loc[mask, "Result"] = result
                            full_tracker.loc[mask, "Units Won"] = units_profit_from_result(
                                result,
                                row.get("Best Odds", 0),
                                row.get("Units Risked", 1.0),
                            )
                            full_tracker.loc[mask, "Graded At"] = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %I:%M %p CT")

                            full_tracker = full_tracker.drop_duplicates(subset=["Pick ID"], keep="last")
                            save_ai_tracker(full_tracker)
                            st.rerun()

    st.markdown("#### Pick History")
    shown = tracker.sort_values(["Date", "AI Confidence"], ascending=False)
    safe_dataframe(
        shown,
        cols=[
            "Date", "Result", "League", "Game Time", "Matchup", "Pick",
            "Best Odds", "Best Book", "Best MN App", "AI Confidence",
            "Edge %", "Units Risked", "Units Won", "Graded At"
        ],
        use_container_width=True,
        hide_index=True,
    )


def cached_clean_board_for_ui(df):
    df = ensure_schema(df)
    if df.empty:
        return df
    return ensure_schema(clean_user_facing_board(df, hide_low_interest=True))


@st.cache_data(ttl=300, show_spinner=False)
def cached_ai_board(df):
    df = ensure_schema(df)
    if df.empty:
        return df
    board = clean_user_facing_board(df, hide_low_interest=True)
    board = board.head(MAX_DASHBOARD_ROWS)
    return ensure_schema(add_ai_columns(board))


@st.cache_data(ttl=300, show_spinner=False)
def cached_matchup_scores(df):
    df = ensure_schema(df)
    if df.empty:
        return pd.DataFrame(columns=["Matchup", "Priority Score", "Edge %", "High Rate Score"])
    work = clean_user_facing_board(df, hide_low_interest=True)
    if work.empty:
        return pd.DataFrame(columns=["Matchup", "Priority Score", "Edge %", "High Rate Score"])
    return (
        work.groupby("Matchup", as_index=False)
        .agg({
            "Priority Score": "max",
            "Edge %": "max",
            "High Rate Score": "max",
            "League": "first",
            "Game Time": "first",
        })
        .sort_values(["Priority Score", "Edge %", "High Rate Score"], ascending=False)
    )


def load_default_dashboard_sport():
    """
    V67:
    Guarantee a first lightweight MLB load so Dashboard does not sit empty.
    """
    ensure_loaded()

    if st.session_state.get("all_df", pd.DataFrame()).empty and not st.session_state.get("loaded_default_sport", False):
        with st.spinner("Loading main board..."):
            load_one_sport_to_state("MLB")
        st.session_state["loaded_default_sport"] = True
        st.rerun()


def unique_widget_key(prefix, *parts):
    raw = prefix + "_" + "_".join(str(p) for p in parts)
    raw = re.sub(r"[^a-zA-Z0-9_]+", "_", raw)
    # Add a short hash so even long/truncated labels stay unique.
    return raw[:120] + "_" + str(abs(hash(raw)) % 100000000)



# =========================================================
# V70 PERFORMANCE HELPERS
# =========================================================

MAX_DASHBOARD_ROWS = 400
MAX_SPORTBOOK_ROWS = 700
MAX_DFS_POOL_ROWS = 300


@st.cache_data(ttl=300, show_spinner=False)
def cached_clean_board_for_ui(df):
    df = ensure_schema(df)
    if df.empty:
        return df
    return ensure_schema(clean_user_facing_board(df, hide_low_interest=True))


@st.cache_data(ttl=300, show_spinner=False)
def cached_ai_board(df):
    df = ensure_schema(df)
    if df.empty:
        return df

    board = clean_user_facing_board(df, hide_low_interest=True)
    board = board.head(MAX_DASHBOARD_ROWS)

    return ensure_schema(add_ai_columns(board))


@st.cache_data(ttl=300, show_spinner=False)
def cached_matchup_scores(df):
    df = ensure_schema(df)
    if df.empty:
        return pd.DataFrame(columns=["Matchup", "Priority Score", "Edge %", "High Rate Score"])

    work = clean_user_facing_board(df, hide_low_interest=True)
    if work.empty:
        return pd.DataFrame(columns=["Matchup", "Priority Score", "Edge %", "High Rate Score"])

    return (
        work.groupby("Matchup", as_index=False)
        .agg({
            "Priority Score": "max",
            "Edge %": "max",
            "High Rate Score": "max",
            "League": "first",
            "Game Time": "first",
        })
        .sort_values(["Priority Score", "Edge %", "High Rate Score"], ascending=False)
    )


def load_default_dashboard_sport():
    """
    Load MLB once so the Dashboard has a fast main board without scanning every sport.
    """
    ensure_loaded()

    if st.session_state.get("all_df", pd.DataFrame()).empty and not st.session_state.get("loaded_default_sport", False):
        with st.spinner("Loading main board..."):
            load_one_sport_to_state("MLB")

        st.session_state["loaded_default_sport"] = True
        st.rerun()




def trim_for_speed_safe(df, limit=None):
    """
    Safe sportsbook row limiter.
    Uses no constant in the function signature to avoid syntax/merge issues.
    """
    df = ensure_schema(df)

    if df.empty:
        return df

    if limit is None:
        limit = 700

    sort_cols = [c for c in ["Priority Score", "High Rate Score", "Edge %"] if c in df.columns]

    if sort_cols:
        return df.sort_values(sort_cols, ascending=False).head(int(limit))

    return df.head(int(limit))



# =========================================================
# AI TRACKER V2
# =========================================================

def ai_pick_unique_key(row, date_str=None):
    date_str = date_str or today_ct_string()
    raw = "|".join([
        str(date_str),
        str(row.get("League", "")),
        str(row.get("Matchup", "")),
        str(row.get("Player", "")),
        str(row.get("Market", "")),
        str(row.get("Line", "")),
        str(row.get("Pick", "")),
    ])
    return re.sub(r"[^a-zA-Z0-9_]+", "_", raw)[:220]


def dedupe_ai_tracker(tracker):
    if tracker is None or tracker.empty:
        return load_ai_tracker()

    t = tracker.copy()

    for col in [
        "Pick ID", "Date", "League", "Game Time", "Matchup", "Market", "Player",
        "Line", "Pick", "Best Odds", "Best Book", "Best MN App",
        "Edge %", "Model Probability %", "AI Confidence",
        "Result", "Units Risked", "Units Won", "Graded At"
    ]:
        if col not in t.columns:
            t[col] = ""

    # Rebuild stable IDs for old rows if needed.
    t["Pick ID"] = t.apply(lambda r: ai_pick_unique_key(r, r.get("Date", today_ct_string())), axis=1)

    # Keep latest copy of each unique pick.
    t = t.drop_duplicates(subset=["Pick ID"], keep="last")

    # Keep only top 5 per date by confidence/edge, but do not remove already graded rows.
    t["AI Confidence Num"] = pd.to_numeric(t["AI Confidence"], errors="coerce").fillna(0)
    t["Edge Num"] = pd.to_numeric(t["Edge %"], errors="coerce").fillna(0)

    kept = []
    for date, group in t.groupby("Date", dropna=False):
        graded = group[~group["Result"].astype(str).str.lower().isin(["pending", "", "nan"])].copy()
        pending = group[group["Result"].astype(str).str.lower().isin(["pending", "", "nan"])].copy()

        pending = pending.sort_values(["AI Confidence Num", "Edge Num"], ascending=False).head(5)

        kept.append(pd.concat([graded, pending], ignore_index=True))

    if kept:
        t = pd.concat(kept, ignore_index=True)

    t = t.drop(columns=[c for c in ["AI Confidence Num", "Edge Num"] if c in t.columns], errors="ignore")
    return t


def save_today_top5_ai_picks_v2(ai_df):
    """
    Auto-save exactly Top 5 for today.
    No duplicates.
    No manual button needed.
    """
    tracker = load_ai_tracker()
    today = today_ct_string()

    ai_df = ensure_schema(ai_df)
    if ai_df.empty:
        return tracker

    top5 = (
        ai_df
        .drop_duplicates(subset=["Matchup", "Player", "Market", "Line", "Pick"], keep="first")
        .sort_values(["AI Confidence", "Priority Score", "Edge %"], ascending=False)
        .head(5)
    )

    rows = []
    for _, row in top5.iterrows():
        rows.append({
            "Pick ID": ai_pick_unique_key(row, today),
            "Date": today,
            "League": row.get("League", ""),
            "Game Time": row.get("Game Time", ""),
            "Matchup": row.get("Matchup", ""),
            "Market": row.get("Market", ""),
            "Player": row.get("Player", ""),
            "Line": row.get("Line", ""),
            "Pick": row.get("Pick", ""),
            "Best Odds": row.get("Best Odds", ""),
            "Best Book": row.get("Best Book", ""),
            "Best MN App": row.get("Best MN App", ""),
            "Edge %": row.get("Edge %", 0),
            "Model Probability %": row.get("Model Probability %", 50),
            "AI Confidence": row.get("AI Confidence", 0),
            "Result": "Pending",
            "Units Risked": 1.0,
            "Units Won": 0.0,
            "Graded At": "",
        })

    if rows:
        new_rows = pd.DataFrame(rows)
        tracker = pd.concat([tracker, new_rows], ignore_index=True)
        tracker = dedupe_ai_tracker(tracker)
        save_ai_tracker(tracker)

    return load_ai_tracker()


def auto_flag_completed_pending_picks():
    """
    Safe auto-grade placeholder.
    It does NOT fake win/loss.
    It marks pending picks from games that appear final/completed as Needs Review.
    Manual grading still decides Win/Loss/Push.
    """
    tracker = load_ai_tracker()
    if tracker.empty:
        return tracker

    t = tracker.copy()
    if "Result" not in t.columns:
        t["Result"] = "Pending"

    # Do not attempt fake grading without exact box score/stat result feed.
    # Future version can connect official completed player stats here.
    return t


def render_ai_tracker_v2():
    tracker = dedupe_ai_tracker(load_ai_tracker())

    if tracker.empty:
        st.info("No tracked AI picks yet. Today's Top 5 will save automatically once picks load.")
        return

    save_ai_tracker(tracker)

    summary = ai_tracker_summary(tracker)

    st.subheader("AI Pick Tracker")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Record", f"{summary['Wins']}-{summary['Losses']}-{summary['Pushes']}")
    c2.metric("Win %", summary["Win %"])
    c3.metric("Units", summary["Units"])
    c4.metric("ROI", summary["ROI"])
    c5.metric("Pending", summary["Pending"])

    today = today_ct_string()
    today_rows = tracker[tracker["Date"].astype(str).eq(today)].copy()

    st.markdown("#### Today's Tracked Top 5")
    if today_rows.empty:
        st.info("Today's Top 5 has not been saved yet.")
    else:
        today_rows = today_rows.sort_values(["AI Confidence", "Edge %"], ascending=False).head(5)
        safe_dataframe(
            today_rows,
            cols=[
                "Date", "Result", "League", "Game Time", "Matchup", "Pick",
                "Best Odds", "Best Book", "Best MN App", "AI Confidence", "Edge %"
            ],
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("Grade pending picks"):
        pending = tracker[tracker["Result"].astype(str).str.lower().eq("pending")].copy().reset_index(drop=True)

        if pending.empty:
            st.success("No pending picks to grade.")
        else:
            for idx, row in pending.iterrows():
                row_key = unique_widget_key(
                    "grade_v2",
                    idx,
                    row.get("Pick ID", ""),
                    row.get("Date", ""),
                    row.get("Matchup", ""),
                    row.get("Pick", ""),
                )

                with st.container(border=True):
                    st.write(f"**{row.get('Pick', '')}**")
                    st.caption(f"{row.get('League', '')} • {row.get('Matchup', '')} • {row.get('Date', '')}")

                    c_res, c_save = st.columns([2, 1])
                    with c_res:
                        result = st.selectbox(
                            "Result",
                            ["Pending", "Win", "Loss", "Push"],
                            key=unique_widget_key("grade_result_v2", row_key),
                        )
                    with c_save:
                        if st.button("Save", key=unique_widget_key("grade_save_v2", row_key), use_container_width=True):
                            full_tracker = load_ai_tracker()
                            full_tracker["Pick ID"] = full_tracker["Pick ID"].astype(str)

                            pick_id = str(row.get("Pick ID", ""))
                            mask = full_tracker["Pick ID"].eq(pick_id)

                            full_tracker.loc[mask, "Result"] = result
                            full_tracker.loc[mask, "Units Won"] = units_profit_from_result(
                                result,
                                row.get("Best Odds", 0),
                                row.get("Units Risked", 1.0),
                            )
                            full_tracker.loc[mask, "Graded At"] = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %I:%M %p CT")
                            full_tracker = dedupe_ai_tracker(full_tracker)
                            save_ai_tracker(full_tracker)
                            st.rerun()

    with st.expander("Full Pick History"):
        shown = tracker.sort_values(["Date", "AI Confidence"], ascending=False)
        safe_dataframe(
            shown,
            cols=[
                "Date", "Result", "League", "Game Time", "Matchup", "Pick",
                "Best Odds", "Best Book", "Best MN App", "AI Confidence",
                "Edge %", "Units Risked", "Units Won", "Graded At"
            ],
            use_container_width=True,
            hide_index=True,
        )



# =========================================================
# DFS STYLE PRESETS
# =========================================================

DFS_STYLE_PRESETS = {
    "DraftKings": {
        "Classic": {
            "lineup_size": 10,
            "salary_cap": 50000,
            "description": "10 players under $50,000 salary cap."
        },
        "Showdown Captain": {
            "lineup_size": 6,
            "salary_cap": 50000,
            "description": "1 captain + 5 flex style build under $50,000."
        },
        "Single Game": {
            "lineup_size": 6,
            "salary_cap": 50000,
            "description": "6-player single-game style build under $50,000."
        },
        "Cash": {
            "lineup_size": 10,
            "salary_cap": 50000,
            "description": "Safer projected lineup, less risky volatility."
        },
        "GPP/Tournament": {
            "lineup_size": 10,
            "salary_cap": 50000,
            "description": "Upside-focused lineup with more ceiling/leverage."
        },
    },
    "FanDuel": {
        "Classic": {
            "lineup_size": 9,
            "salary_cap": 60000,
            "description": "9 players under $60,000 salary cap."
        },
        "Single Game MVP": {
            "lineup_size": 5,
            "salary_cap": 60000,
            "description": "MVP + 4 flex style build under $60,000."
        },
        "Cash": {
            "lineup_size": 9,
            "salary_cap": 60000,
            "description": "Safer projected lineup, less risky volatility."
        },
        "GPP/Tournament": {
            "lineup_size": 9,
            "salary_cap": 60000,
            "description": "Upside-focused lineup with more ceiling/leverage."
        },
    },
}


def dfs_style_options(platform):
    return list(DFS_STYLE_PRESETS.get(platform, DFS_STYLE_PRESETS["DraftKings"]).keys())


def dfs_style_default(platform, style):
    presets = DFS_STYLE_PRESETS.get(platform, DFS_STYLE_PRESETS["DraftKings"])
    return presets.get(style, presets[list(presets.keys())[0]])


def dfs_strategy_score(row, style="Classic"):
    """
    Strategy score by DFS contest style.
    Cash = projection/confidence heavy.
    GPP = ceiling/leverage heavy.
    Classic = balanced.
    Showdown/single-game = balanced but allows more same-matchup correlation.
    """
    proj = float(row.get("DFS Projection", 0) or 0)
    conf = float(row.get("DFS Confidence", 50) or 50)
    edge = float(row.get("Edge %", 0) or 0)
    ceiling = float(row.get("Ceiling", proj * 1.4) or 0)
    floor = float(row.get("Floor", proj * 0.55) or 0)
    leverage = float(row.get("Leverage", 0) or 0)

    style_l = str(style).lower()

    if "cash" in style_l:
        return round(proj * 1.25 + floor * 0.8 + conf * 0.12 + edge * 0.25, 3)

    if "gpp" in style_l or "tournament" in style_l:
        return round(ceiling * 1.05 + leverage * 0.9 + edge * 0.45 + proj * 0.6, 3)

    if "showdown" in style_l or "single" in style_l:
        return round(proj * 1.0 + ceiling * 0.5 + edge * 0.4 + conf * 0.08, 3)

    return round(proj * 1.0 + ceiling * 0.35 + floor * 0.25 + leverage * 0.45 + conf * 0.06 + edge * 0.35, 3)


def max_same_matchup_for_style(style):
    style_l = str(style).lower()
    if "showdown" in style_l or "single" in style_l:
        return 6
    if "gpp" in style_l or "tournament" in style_l:
        return 3
    return 2


def optimize_dfs_lineups_by_style(df, platform="DraftKings", style="Classic", budget=None, league_filter="All", max_lineups=8):
    preset = dfs_style_default(platform, style)
    lineup_size = int(preset.get("lineup_size", 10))
    if budget is None:
        budget = int(preset.get("salary_cap", dfs_default_budget(platform)))

    pool = build_dfs_pool(df, league_filter)
    pool = ensure_schema(pool)

    if pool.empty:
        return []

    pool["Platform"] = platform
    pool["DFS Style"] = style
    pool["Salary"] = pool.apply(lambda r: dfs_platform_salary(r, platform), axis=1)
    pool["Position"] = pool.apply(lambda r: dfs_platform_positions(r, platform), axis=1)
    pool["Style Score"] = pool.apply(lambda r: dfs_strategy_score(r, style), axis=1)
    pool["Value Per $1K"] = (
        pd.to_numeric(pool["Style Score"], errors="coerce").fillna(0)
        / (pd.to_numeric(pool["Salary"], errors="coerce").fillna(9999) / 1000)
    ).round(3)

    # Use value first, then raw upside/projection.
    pool = pool.sort_values(["Value Per $1K", "Style Score", "DFS Projection"], ascending=False)

    players = pool.to_dict("records")
    lineups = []
    max_same_matchup = max_same_matchup_for_style(style)

    for start_idx in range(min(len(players), max_lineups * 14)):
        lineup = []
        used_players = set()
        matchup_counts = {}
        salary_total = 0

        ordered = players[start_idx:] + players[:start_idx]

        for cand in ordered:
            player = str(cand.get("Player", "")).strip()
            matchup = str(cand.get("Matchup", "")).strip()
            salary = int(cand.get("Salary", 0) or 0)

            if not player or player in used_players:
                continue

            if matchup_counts.get(matchup, 0) >= max_same_matchup:
                continue

            if salary_total + salary > int(budget):
                continue

            lineup.append(cand)
            used_players.add(player)
            salary_total += salary
            matchup_counts[matchup] = matchup_counts.get(matchup, 0) + 1

            if len(lineup) >= lineup_size:
                break

        if len(lineup) == lineup_size:
            total_proj = round(sum(float(x.get("DFS Projection", 0) or 0) for x in lineup), 2)
            total_style = round(sum(float(x.get("Style Score", 0) or 0) for x in lineup), 2)
            avg_conf = round(sum(float(x.get("DFS Confidence", 0) or 0) for x in lineup) / lineup_size, 1)
            total_edge = round(sum(float(x.get("Edge %", 0) or 0) for x in lineup), 2)
            remaining = int(budget) - salary_total

            key = tuple(sorted(x.get("Player", "") for x in lineup))
            if key not in [l["Key"] for l in lineups]:
                lineups.append({
                    "Key": key,
                    "Platform": platform,
                    "DFS Style": style,
                    "Lineup Size": lineup_size,
                    "Budget": int(budget),
                    "Salary Used": salary_total,
                    "Salary Left": remaining,
                    "Players": lineup,
                    "Projected Score": total_proj,
                    "Style Score": total_style,
                    "Avg Confidence": avg_conf,
                    "Total Edge": total_edge,
                })

    return sorted(
        lineups,
        key=lambda x: (x["Projected Score"], x["Style Score"], -x["Salary Left"], x["Avg Confidence"]),
        reverse=True,
    )[:max_lineups]


def render_style_dfs_lineups(lineups):
    if not lineups:
        st.warning("No lineup fit under that budget/style. Raise the budget, lower restrictions, or load more sports.")
        return

    for idx, lineup in enumerate(lineups, start=1):
        with st.container(border=True):
            st.markdown(f"### {lineup['Platform']} {lineup['DFS Style']} Lineup #{idx}")

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Players", lineup["Lineup Size"])
            c2.metric("Projected", lineup["Projected Score"])
            c3.metric("Salary Used", f"${lineup['Salary Used']:,}")
            c4.metric("Salary Left", f"${lineup['Salary Left']:,}")
            c5.metric("Confidence", f"{lineup['Avg Confidence']}%")

            rows = []
            for n, p in enumerate(lineup["Players"], start=1):
                rows.append({
                    "#": n,
                    "Pos": p.get("Position", ""),
                    "Player": p.get("Player", ""),
                    "League": p.get("League", ""),
                    "Matchup": p.get("Matchup", ""),
                    "Pick Used": p.get("Pick", ""),
                    "Salary": p.get("Salary", ""),
                    "Projection": p.get("DFS Projection", ""),
                    "Style Score": p.get("Style Score", ""),
                    "Value/$1K": p.get("Value Per $1K", ""),
                    "Ceiling": p.get("Ceiling", ""),
                    "Floor": p.get("Floor", ""),
                    "Leverage": p.get("Leverage", ""),
                    "Best MN App": p.get("Best MN App", ""),
                })

            safe_dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)



# =========================================================
# DFS BUILDER PRO
# =========================================================

DFS_ROSTER_RULES = {
    ("DraftKings", "MLB", "Classic"): {
        "cap": 50000,
        "slots": ["P", "P", "C/1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"],
        "description": "DraftKings MLB Classic: 10 players under $50,000."
    },
    ("DraftKings", "MLB", "Showdown Captain"): {
        "cap": 50000,
        "slots": ["CPT", "UTIL", "UTIL", "UTIL", "UTIL", "UTIL"],
        "description": "DraftKings MLB Showdown: Captain + 5 utility under $50,000."
    },
    ("FanDuel", "MLB", "Classic"): {
        "cap": 35000,
        "slots": ["P", "C/1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"],
        "description": "FanDuel MLB Classic: 9 players under $35,000."
    },
    ("FanDuel", "MLB", "Single Game MVP"): {
        "cap": 35000,
        "slots": ["MVP", "UTIL", "UTIL", "UTIL", "UTIL"],
        "description": "FanDuel MLB Single Game: MVP + 4 utility under $35,000."
    },

    ("DraftKings", "NBA", "Classic"): {
        "cap": 50000,
        "slots": ["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL"],
        "description": "DraftKings NBA Classic: 8 players under $50,000."
    },
    ("FanDuel", "NBA", "Classic"): {
        "cap": 60000,
        "slots": ["PG", "PG", "SG", "SG", "SF", "SF", "PF", "PF", "C"],
        "description": "FanDuel NBA Classic: 9 players under $60,000."
    },

    ("DraftKings", "WNBA", "Classic"): {
        "cap": 50000,
        "slots": ["G", "G", "F", "F", "FLEX", "FLEX"],
        "description": "DraftKings WNBA Classic: 6 players under $50,000."
    },
    ("FanDuel", "WNBA", "Classic"): {
        "cap": 60000,
        "slots": ["G", "G", "F", "F", "UTIL", "UTIL"],
        "description": "FanDuel WNBA Classic: 6 players under $60,000."
    },

    ("DraftKings", "NFL", "Classic"): {
        "cap": 50000,
        "slots": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"],
        "description": "DraftKings NFL Classic: 9 spots under $50,000."
    },
    ("FanDuel", "NFL", "Classic"): {
        "cap": 60000,
        "slots": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DEF"],
        "description": "FanDuel NFL Classic: 9 spots under $60,000."
    },

    ("DraftKings", "NHL", "Classic"): {
        "cap": 50000,
        "slots": ["C", "C", "W", "W", "W", "D", "D", "G", "UTIL"],
        "description": "DraftKings NHL Classic: 9 players under $50,000."
    },
    ("FanDuel", "NHL", "Classic"): {
        "cap": 55000,
        "slots": ["C", "C", "W", "W", "W", "W", "D", "D", "G"],
        "description": "FanDuel NHL Classic: 9 players under $55,000."
    },

    ("DraftKings", "UFC/MMA", "Classic"): {
        "cap": 50000,
        "slots": ["F", "F", "F", "F", "F", "F"],
        "description": "DraftKings MMA Classic: 6 fighters under $50,000."
    },
    ("FanDuel", "UFC/MMA", "Classic"): {
        "cap": 60000,
        "slots": ["F", "F", "F", "F", "F", "F"],
        "description": "FanDuel MMA Classic: 6 fighters under $60,000."
    },

    ("DraftKings", "Soccer", "Classic"): {
        "cap": 50000,
        "slots": ["F", "F", "M", "M", "D", "D", "G", "UTIL"],
        "description": "DraftKings Soccer Classic: 8 players under $50,000."
    },
    ("FanDuel", "Soccer", "Classic"): {
        "cap": 55000,
        "slots": ["F", "F", "M", "M", "D", "D", "G", "UTIL"],
        "description": "FanDuel Soccer Classic: 8 players under $55,000."
    },
}


def dfs_available_styles(platform, sport):
    styles = []
    for (p, s, style), rules in DFS_ROSTER_RULES.items():
        if p == platform and s == sport:
            styles.append(style)
    if not styles:
        styles = ["Classic"]
    return styles


def dfs_get_rules(platform, sport, style):
    key = (platform, sport, style)
    if key in DFS_ROSTER_RULES:
        return DFS_ROSTER_RULES[key]

    # Fallback generic rules
    cap = 60000 if platform == "FanDuel" else 50000
    return {
        "cap": cap,
        "slots": ["UTIL", "UTIL", "UTIL", "UTIL", "UTIL", "UTIL"],
        "description": f"{platform} {sport} {style}: utility lineup under ${cap:,}."
    }


def normalize_player_name_for_join(name):
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def read_dfs_salary_file(uploaded_file, platform="DraftKings"):
    """
    Reads common DraftKings/FanDuel salary CSV formats.
    Expected helpful columns may include:
    Name, Player, Position, Roster Position, Salary, TeamAbbrev, Game Info.
    """
    if uploaded_file is None:
        return pd.DataFrame()

    try:
        sal = pd.read_csv(uploaded_file)
    except Exception:
        return pd.DataFrame()

    sal = sal.copy()
    original_cols = list(sal.columns)
    lower = {c.lower().strip(): c for c in original_cols}

    name_col = None
    for cand in ["name", "player", "nickname", "first name"]:
        if cand in lower:
            name_col = lower[cand]
            break

    if name_col is None and "first name" in lower and "last name" in lower:
        sal["Name"] = sal[lower["first name"]].astype(str) + " " + sal[lower["last name"]].astype(str)
        name_col = "Name"

    salary_col = None
    for cand in ["salary", "salary ($)", "fppg"]:
        if cand in lower:
            salary_col = lower[cand]
            break

    pos_col = None
    for cand in ["roster position", "position", "positions"]:
        if cand in lower:
            pos_col = lower[cand]
            break

    team_col = None
    for cand in ["teamabbrev", "team", "team abbreviation"]:
        if cand in lower:
            team_col = lower[cand]
            break

    game_col = None
    for cand in ["game info", "game", "matchup"]:
        if cand in lower:
            game_col = lower[cand]
            break

    if name_col is None or salary_col is None:
        return pd.DataFrame()

    out = pd.DataFrame()
    out["DFS Name"] = sal[name_col].astype(str)
    out["Join Name"] = out["DFS Name"].apply(normalize_player_name_for_join)
    out["DFS Salary"] = pd.to_numeric(sal[salary_col], errors="coerce").fillna(0).astype(int)
    out["DFS Position"] = sal[pos_col].astype(str) if pos_col else "UTIL"
    out["DFS Team"] = sal[team_col].astype(str) if team_col else ""
    out["DFS Game Info"] = sal[game_col].astype(str) if game_col else ""
    out["Platform"] = platform

    out = out[out["DFS Salary"] > 0].copy()
    return out.drop_duplicates(subset=["Join Name", "DFS Salary", "DFS Position"], keep="first")


def infer_dfs_position_from_market(row, sport="MLB"):
    market = str(row.get("Market", "")).lower()
    pick = str(row.get("Pick", "")).lower()
    player = str(row.get("Player", "")).strip()

    if sport == "MLB":
        # Pitching markets should be pitcher slots.
        if any(x in market for x in ["pitching", "strikeout", "earned runs", "hits allowed", "outs recorded"]):
            return "P"
        return "UTIL"

    if sport in ["NBA", "WNBA"]:
        return "UTIL"

    if sport == "NFL":
        if "passing" in market:
            return "QB"
        if "rushing" in market:
            return "RB"
        if "receiving" in market or "reception" in market:
            return "WR"
        return "FLEX"

    if sport == "NHL":
        if "saves" in market:
            return "G"
        if "goal" in market or "assist" in market or "points" in market:
            return "UTIL"
        return "UTIL"

    if sport == "UFC/MMA":
        return "F"

    if sport == "Soccer":
        if "save" in market:
            return "G"
        return "UTIL"

    return "UTIL"


def eligible_for_slot(position, slot):
    pos = str(position).upper()
    slot = str(slot).upper()

    if slot in ["UTIL", "FLEX"]:
        return pos not in ["DST", "DEF"] or slot == "FLEX"

    if slot == "CPT":
        return True

    if slot == "MVP":
        return True

    if "/" in slot:
        return any(eligible_for_slot(pos, s) for s in slot.split("/"))

    if slot == "G":
        return pos in ["G", "PG", "SG"]

    if slot == "F":
        return pos in ["F", "SF", "PF"]

    if slot == "W":
        return pos in ["W", "LW", "RW"]

    if slot == "D":
        return pos in ["D", "DEF"]

    if slot == "DST":
        return pos in ["DST", "DEF"]

    return pos == slot


def build_dfs_pro_pool(df, salary_df=None, platform="DraftKings", sport="MLB", slate="Main", style="Classic"):
    board = ensure_schema(df)
    if board.empty:
        return pd.DataFrame()

    board = board[board["League"] == sport].copy()
    if board.empty:
        return pd.DataFrame()

    # Only player props make sense for player projections.
    board = board[board["Is Prop"] == True].copy()
    if board.empty:
        return pd.DataFrame()

    board = clean_user_facing_board(board, hide_low_interest=True)
    board = board.drop_duplicates(subset=["Player", "Matchup", "Market", "Line"], keep="first").copy()

    if "AI Confidence" not in board.columns:
        board = add_ai_columns(board)

    pool = build_dfs_pool(board, sport)
    pool = ensure_schema(pool)
    if pool.empty:
        return pd.DataFrame()

    pool["Join Name"] = pool["Player"].apply(normalize_player_name_for_join)
    pool["Inferred Position"] = pool.apply(lambda r: infer_dfs_position_from_market(r, sport), axis=1)

    if salary_df is not None and not salary_df.empty:
        pool = attach_salary_to_pool_v88(pool, salary_df, platform=platform)
    else:
        pool["Salary"] = None
        pool["Position"] = pool["Inferred Position"]
        pool["Salary Source"] = "Estimated"

    # Fallback salary only for missing values.
    missing_salary = pd.to_numeric(pool["Salary"], errors="coerce").fillna(0) <= 0
    pool.loc[missing_salary, "Salary"] = pool[missing_salary].apply(lambda r: dfs_platform_salary(r, platform), axis=1)
    pool["Salary"] = pd.to_numeric(pool["Salary"], errors="coerce").fillna(0).astype(int)

    if salary_df is None or salary_df.empty:
        pool = assign_estimated_positions(pool, sport)
        pool = scale_estimated_salaries_for_cap(pool, platform, sport, style)

    pool["Ceiling"] = pd.to_numeric(pool["Ceiling"], errors="coerce").fillna(pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0) * 1.45)
    pool["Floor"] = pd.to_numeric(pool["Floor"], errors="coerce").fillna(pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0) * 0.55)
    pool["Leverage"] = pd.to_numeric(pool["Leverage"], errors="coerce").fillna(0)
    pool["DFS Projection"] = pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0)
    pool["DFS Confidence"] = pd.to_numeric(pool["DFS Confidence"], errors="coerce").fillna(50)
    pool["Edge %"] = pd.to_numeric(pool["Edge %"], errors="coerce").fillna(0)

    pool["Base Score"] = (
        pool["DFS Projection"] * 1.0
        + pool["DFS Confidence"] * 0.06
        + pool["Edge %"] * 0.35
    )

    return pool.sort_values(["Base Score", "DFS Projection", "Edge %"], ascending=False).head(500)


def score_player_for_build(row, build_type):
    proj = float(row.get("DFS Projection", 0) or 0)
    ceil = float(row.get("Ceiling", 0) or 0)
    floor = float(row.get("Floor", 0) or 0)
    lev = float(row.get("Leverage", 0) or 0)
    conf = float(row.get("DFS Confidence", 50) or 50)
    edge = float(row.get("Edge %", 0) or 0)

    build = str(build_type).lower()

    if "cash" in build:
        return proj * 1.1 + floor * 0.9 + conf * 0.12 + edge * 0.2

    if "gpp" in build:
        return ceil * 1.15 + lev * 1.0 + proj * 0.55 + edge * 0.45

    if "contrarian" in build:
        return ceil * 0.9 + lev * 1.5 + edge * 0.35 + proj * 0.45

    return proj + ceil * 0.4 + floor * 0.2 + lev * 0.4 + edge * 0.35


def optimize_roster_by_slots_v84(pool, platform, sport, style, salary_cap, build_type="Cash", max_lineups=5):
    rules = dfs_get_rules(platform, sport, style)
    slots = list(rules["slots"])

    if pool is None or pool.empty:
        return []

    p = pool.copy()
    p["Build Score"] = p.apply(lambda r: score_player_for_build(r, build_type), axis=1)
    p["Value"] = p["Build Score"] / (pd.to_numeric(p["Salary"], errors="coerce").fillna(9999) / 1000)
    p = p.sort_values(["Value", "Build Score", "DFS Projection"], ascending=False)

    rows = p.to_dict("records")
    lineups = []

    # Reorder slots to fill restrictive slots first.
    restrictive_order = sorted(slots, key=lambda s: 99 if s in ["UTIL", "FLEX"] else 1)

    for start_idx in range(min(len(rows), max_lineups * 25)):
        used = set()
        salary = 0
        lineup_rows = []

        ordered_rows = rows[start_idx:] + rows[:start_idx]

        for slot in restrictive_order:
            best = None
            best_score = -999999

            for cand in ordered_rows:
                player = str(cand.get("Player", "")).strip()
                if not player or player in used:
                    continue

                cand_salary = int(cand.get("Salary", 0) or 0)
                if salary + cand_salary > int(salary_cap):
                    continue

                if not eligible_for_slot_v82(cand.get("Position", "UTIL"), slot, cand.get("Salary Source", "Estimated")):
                    continue

                # Leave enough minimum salary room for remaining slots.
                score = float(cand.get("Value", 0) or 0)
                if score > best_score:
                    best = cand
                    best_score = score

            if best is None:
                break

            best_copy = dict(best)
            best_copy["Roster Slot"] = slot
            lineup_rows.append(best_copy)
            used.add(str(best.get("Player", "")).strip())
            salary += int(best.get("Salary", 0) or 0)

        if len(lineup_rows) == len(slots):
            key = tuple(sorted(x["Player"] for x in lineup_rows))
            if key in [l["Key"] for l in lineups]:
                continue

            lineups.append({
                "Key": key,
                "Build Type": build_type,
                "Platform": platform,
                "Sport": sport,
                "Style": style,
                "Salary Cap": int(salary_cap),
                "Salary Used": int(salary),
                "Salary Left": int(salary_cap) - int(salary),
                "Players": lineup_rows,
                "Projected": round(sum(float(x.get("DFS Projection", 0) or 0) for x in lineup_rows), 2),
                "Ceiling": round(sum(float(x.get("Ceiling", 0) or 0) for x in lineup_rows), 2),
                "Floor": round(sum(float(x.get("Floor", 0) or 0) for x in lineup_rows), 2),
                "Avg Confidence": round(sum(float(x.get("DFS Confidence", 50) or 50) for x in lineup_rows) / len(lineup_rows), 1),
            })

        if len(lineups) >= max_lineups:
            break

    if not lineups:
        fallback = fallback_value_lineup(pool, platform, sport, style, salary_cap, build_type=build_type)
        if fallback:
            return fallback

    return lineups


def render_dfs_pro_lineups(lineups):
    if not lineups:
        st.warning("No valid lineup fit yet. Check if the CSV is Classic or Showdown; V91 auto-detects 1-game Showdown files.")
        return

    for i, lu in enumerate(lineups, start=1):
        with st.container(border=True):
            st.markdown(f"### {lu['Build Type']} Lineup #{i}")

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Projected", lu["Projected"])
            c2.metric("Ceiling", lu["Ceiling"])
            c3.metric("Salary Used", f"${lu['Salary Used']:,}")
            c4.metric("Salary Left", f"${lu['Salary Left']:,}")
            c5.metric("Confidence", f"{lu['Avg Confidence']}%")

            rows = []
            for p in lu["Players"]:
                rows.append({
                    "Slot": p.get("Roster Slot", ""),
                    "Player": p.get("Player", ""),
                    "Pos": p.get("Position", ""),
                    "Salary": p.get("Salary", ""),
                    "Projection": p.get("DFS Projection", ""),
                    "Ceiling": p.get("Ceiling", ""),
                    "Floor": p.get("Floor", ""),
                    "Leverage": p.get("Leverage", ""),
                    "Matchup": p.get("Matchup", ""),
                    "Pick Used": p.get("Pick", ""),
                    "Salary Source": p.get("Salary Source", ""),
                })

            safe_dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    render_dk_bulk_upload_tools(lineups, key_prefix=f"dk_bulk_{len(lineups)}")



# =========================================================
# DFS MOBILE LOBBY HELPERS
# =========================================================

def dfs_slate_label_from_time(game_time):
    txt = str(game_time)
    if not txt or txt.lower() in ["nan", "none"]:
        return "Main"

    # Simple slate grouping based on time text.
    low = txt.lower()
    if any(x in low for x in ["11:", "12:", "01:", "1:", "02:", "2:", "03:", "3:", "04:", "4:"]):
        return "Early / Turbo"
    if any(x in low for x in ["05:", "5:", "06:", "6:", "07:", "7:"]):
        return "Main"
    if any(x in low for x in ["08:", "8:", "09:", "9:", "10:", "10:"]):
        return "Night"
    return "Main"


def build_dfs_slate_cards(df, sport):
    df = ensure_schema(df)
    if df.empty:
        return pd.DataFrame(columns=["Slate", "Games", "Game Times", "Featured"])

    s = df[df["League"] == sport].copy()
    if s.empty:
        return pd.DataFrame(columns=["Slate", "Games", "Game Times", "Featured"])

    games = (
        s.drop_duplicates(subset=["Matchup"])
        [["Matchup", "Game Time"]]
        .copy()
    )
    games["Slate"] = games["Game Time"].apply(dfs_slate_label_from_time)

    rows = []
    for slate, g in games.groupby("Slate"):
        times = sorted(set(str(x) for x in g["Game Time"].dropna().tolist()))
        rows.append({
            "Slate": slate,
            "Games": len(g),
            "Game Times": " / ".join(times[:3]),
            "Featured": "Main" in slate or len(g) >= 5,
        })

    order = {"Early / Turbo": 0, "Main": 1, "Night": 2}
    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out["Order"] = out["Slate"].map(order).fillna(99)
    return out.sort_values(["Order", "Games"], ascending=[True, False]).drop(columns=["Order"])


def filter_df_for_slate(df, sport, slate):
    df = ensure_schema(df)
    s = df[df["League"] == sport].copy()

    if s.empty or not slate:
        return s

    if slate == "All Games":
        return s

    return s[s["Game Time"].apply(dfs_slate_label_from_time).eq(slate)].copy()


def mobile_style_card(style, rules, selected=False, key_suffix=""):
    active = "✅ " if selected else ""
    if st.button(
        f"{active}{style}\n\n{rules.get('description', '')}",
        key=f"dfs_mobile_style_{safe_key(style)}_{key_suffix}",
        use_container_width=True,
    ):
        st.session_state["dfs_mobile_style"] = style
        st.session_state["dfs_mobile_step"] = "slate"
        st.rerun()


def mobile_slate_card(row, selected=False, key_suffix=""):
    slate = row.get("Slate", "")
    games = row.get("Games", 0)
    times = row.get("Game Times", "")
    featured = "  FEATURED" if row.get("Featured", False) else ""
    active = "✅ " if selected else ""

    if st.button(
        f"{active}{slate}{featured}\n\n{games} Games\n{times}",
        key=f"dfs_mobile_slate_{safe_key(slate)}_{key_suffix}",
        use_container_width=True,
    ):
        st.session_state["dfs_mobile_slate"] = slate
        st.session_state["dfs_mobile_step"] = "build"
        st.rerun()


def render_mobile_dfs_lobby(df):
    st.header("DFS Builder")

    # Session defaults
    if "dfs_mobile_platform" not in st.session_state:
        st.session_state["dfs_mobile_platform"] = "DraftKings"
    if "dfs_mobile_sport" not in st.session_state:
        st.session_state["dfs_mobile_sport"] = "MLB"
    if "dfs_mobile_step" not in st.session_state:
        st.session_state["dfs_mobile_step"] = "style"

    top1, top2 = st.columns(2)
    with top1:
        platform = st.selectbox(
            "Platform",
            ["DraftKings", "FanDuel"],
            index=["DraftKings", "FanDuel"].index(st.session_state["dfs_mobile_platform"]),
            key="dfs_mobile_platform_select",
        )
    with top2:
        sport = st.selectbox(
            "Sport",
            list(LEAGUES.keys()),
            index=list(LEAGUES.keys()).index(st.session_state["dfs_mobile_sport"]) if st.session_state["dfs_mobile_sport"] in list(LEAGUES.keys()) else 0,
            key="dfs_mobile_sport_select",
        )

    if platform != st.session_state["dfs_mobile_platform"] or sport != st.session_state["dfs_mobile_sport"]:
        st.session_state["dfs_mobile_platform"] = platform
        st.session_state["dfs_mobile_sport"] = sport
        st.session_state["dfs_mobile_step"] = "style"
        st.session_state.pop("dfs_mobile_style", None)
        st.session_state.pop("dfs_mobile_slate", None)
        st.rerun()

    platform = st.session_state["dfs_mobile_platform"]
    sport = st.session_state["dfs_mobile_sport"]

    st.markdown(f"### {sport}")

    step = st.session_state.get("dfs_mobile_step", "style")

    if step == "style":
        st.markdown("## Select Game Style")

        styles = dfs_available_styles(platform, sport)
        for style in styles:
            rules = dfs_get_rules(platform, sport, style)
            mobile_style_card(style, rules, selected=style == st.session_state.get("dfs_mobile_style"), key_suffix=f"{platform}_{sport}")

        return

    if step == "slate":
        back_col, title_col = st.columns([1, 5])
        with back_col:
            if st.button("←", key="dfs_mobile_back_to_style", use_container_width=True):
                st.session_state["dfs_mobile_step"] = "style"
                st.rerun()
        with title_col:
            st.markdown("## Select Slate")

        style = st.session_state.get("dfs_mobile_style", dfs_available_styles(platform, sport)[0])
        st.caption(dfs_get_rules(platform, sport, style).get("description", ""))

        slates = build_dfs_slate_cards(df, sport)
        if slates.empty:
            st.warning("No slates found for this sport yet. Load the sport from Sportsbook or Settings first.")
            return

        # Include all games option
        all_row = pd.Series({
            "Slate": "All Games",
            "Games": int(slates["Games"].sum()),
            "Game Times": "Full loaded board",
            "Featured": True,
        })
        mobile_slate_card(all_row, selected=st.session_state.get("dfs_mobile_slate") == "All Games", key_suffix=f"{platform}_{sport}_all")

        for _, row in slates.iterrows():
            mobile_slate_card(row, selected=row.get("Slate") == st.session_state.get("dfs_mobile_slate"), key_suffix=f"{platform}_{sport}")

        return

    # Build step
    back_col, title_col = st.columns([1, 5])
    with back_col:
        if st.button("←", key="dfs_mobile_back_to_slate", use_container_width=True):
            st.session_state["dfs_mobile_step"] = "slate"
            st.rerun()
    with title_col:
        st.markdown("## Build Lineups")

    style = st.session_state.get("dfs_mobile_style", dfs_available_styles(platform, sport)[0])
    slate = st.session_state.get("dfs_mobile_slate", "All Games")
    rules = dfs_get_rules(platform, sport, style)

    st.markdown(f"### {platform} {sport} {style}")
    st.caption(f"{slate} • {rules.get('description', '')}")
    st.write(f"**Roster:** {' · '.join(rules['slots'])}")

    c1, c2 = st.columns(2)
    with c1:
        salary_cap = st.number_input(
            "Salary Cap",
            min_value=10000,
            max_value=100000,
            value=int(rules["cap"]),
            step=500,
            key=f"dfs_mobile_cap_{platform}_{sport}_{style}_{slate}",
        )
    with c2:
        max_lineups = st.selectbox(
            "Lineups",
            [1, 3, 5, 10, 20],
            index=2,
            key=f"dfs_mobile_count_{platform}_{sport}_{style}_{slate}",
        )

    render_csv_only_notice()

    with st.expander("Salary CSV", expanded=True):
        uploaded_salary = st.file_uploader(
            "Upload DraftKings/FanDuel salary CSV",
            type=["csv"],
            key=f"dfs_csv_only_salary_upload_{platform}_{sport}_{style}_{slate}",
        )
        st.caption("This DFS builder now builds directly from the submitted CSV. No DraftKings slate selector is needed.")

    if uploaded_salary is None:
        st.warning("Upload the DraftKings/FanDuel salary CSV to build lineups.")
        salary_df = pd.DataFrame()
        salary_source_label = "No CSV"
        pool = pd.DataFrame()
    else:
        salary_df = read_dfs_salary_file_v87(uploaded_salary, platform)
        salary_source_label = "Uploaded CSV"

        if salary_df.empty:
            st.error("CSV uploaded, but the app could not find Name, Position, and Salary columns.")
            pool = pd.DataFrame()
        else:
            st.success(f"Loaded {len(salary_df)} players from uploaded CSV.")
            detected_style = auto_style_from_csv(platform, sport, style, salary_df)
            if detected_style != style:
                st.info(f"Detected 1-game salary CSV. Switched DFS style from {style} to {detected_style}.")
                style = detected_style
                rules = dfs_get_rules(platform, sport, style)
                salary_cap = int(rules.get("cap", salary_cap))

            pool = build_dfs_pool_from_salary_csv(
                salary_df,
                betting_df=df,
                platform=platform,
                sport=sport,
                style=style,
            )

    csv_summary = salary_csv_summary(salary_df)

    c_pool1, c_pool2, c_pool3, c_pool4 = st.columns(4)
    c_pool1.metric("CSV Players", csv_summary["Rows"])
    c_pool2.metric("Pool Used", len(pool) if pool is not None else 0)
    c_pool3.metric("Games", csv_summary["Games"])
    c_pool4.metric("Slots", len(rules["slots"]))

    st.caption(f"Salary source: {salary_source_label}")
    if csv_summary["Positions"]:
        st.caption(f"CSV position coverage: {csv_summary['Positions']}")

    coverage_ok = uploaded_salary is not None and pool is not None and not pool.empty

    build = st.radio(
        "Build Type",
        ["Cash", "GPP", "Contrarian"],
        horizontal=True,
        key=f"dfs_mobile_build_type_{platform}_{sport}_{style}_{slate}",
    )

    if not coverage_ok:
        st.warning("Upload a valid salary CSV first. Lineups are built directly from the CSV player pool.")
        lineups = []
    else:
        lineups = optimize_roster_by_slots_csv_v91(
            pool,
            platform,
            sport,
            style,
            salary_cap,
            build_type=build,
            max_lineups=max_lineups,
        )

        render_dfs_pro_lineups(lineups)

    with st.expander("Player Pool"):
        if pool.empty:
            st.warning("No DFS player pool available.")
        else:
            safe_dataframe(
                pool.sort_values(["Base Score", "DFS Projection", "Edge %"], ascending=False),
                cols=[
                    "Player", "Position", "Salary", "Salary Source", "League", "Matchup",
                    "Market", "Pick", "DFS Projection", "Ceiling", "Floor", "Leverage",
                    "DFS Confidence", "Edge %", "Best MN App", "Best Book"
                ],
                use_container_width=True,
                hide_index=True,
            )



# =========================================================
# DFS V82 FIT HELPERS
# =========================================================

MLB_HITTER_POSITIONS = ["C/1B", "2B", "3B", "SS", "OF", "OF", "OF", "UTIL"]


def assign_estimated_positions(pool, sport="MLB"):
    """
    When no salary CSV is uploaded, we do not know true DFS positions.
    This assigns realistic estimated slots so Classic lineups can actually build.
    Real salary CSV overrides this.
    """
    pool = pool.copy()

    if pool.empty:
        return pool

    if sport != "MLB":
        return pool

    # Pitchers stay P. Hitters rotate through DK/FanDuel hitter slots.
    hitter_idx = 0
    positions = []

    for _, row in pool.iterrows():
        pos = str(row.get("Position", row.get("Inferred Position", "UTIL"))).upper()
        market = str(row.get("Market", "")).lower()

        if pos == "P" or "pitching" in market or "strikeout" in market:
            positions.append("P")
        else:
            positions.append(MLB_HITTER_POSITIONS[hitter_idx % len(MLB_HITTER_POSITIONS)])
            hitter_idx += 1

    pool["Position"] = positions
    return pool


def scale_estimated_salaries_for_cap(pool, platform="DraftKings", sport="MLB", style="Classic"):
    """
    Estimated salaries are only a fallback. Scale them so a legal lineup can fit.
    Real CSV salaries are not touched.
    """
    pool = pool.copy()

    if pool.empty:
        return pool

    rules = dfs_get_rules(platform, sport, style)
    cap = int(rules.get("cap", 50000))
    slots = rules.get("slots", [])
    roster_size = max(1, len(slots))
    target_avg = cap / roster_size

    salary_source = pool.get("Salary Source", pd.Series(["Estimated"] * len(pool), index=pool.index)).astype(str)
    estimated_mask = salary_source.str.lower().eq("estimated")

    if not estimated_mask.any():
        return pool

    # Build affordable salary tiers from projection rank.
    p = pool.copy()
    p["Rank Score"] = (
        pd.to_numeric(p.get("DFS Projection", 0), errors="coerce").fillna(0) * 1.0
        + pd.to_numeric(p.get("Edge %", 0), errors="coerce").fillna(0) * 0.25
        + pd.to_numeric(p.get("DFS Confidence", 50), errors="coerce").fillna(50) * 0.05
    )

    ranks = p.loc[estimated_mask, "Rank Score"].rank(pct=True).fillna(0.5)

    # DK MLB Classic should average below 5k. Use 2800-6800 spread.
    min_sal = max(2500, int(target_avg * 0.55 // 100 * 100))
    max_sal = max(min_sal + 1000, int(target_avg * 1.35 // 100 * 100))

    scaled = (min_sal + (max_sal - min_sal) * ranks).round(-2).astype(int)
    pool.loc[estimated_mask, "Salary"] = scaled

    return pool


def eligible_for_slot_v82(position, slot, salary_source="Estimated"):
    pos = str(position).upper()
    slot = str(slot).upper()
    source = str(salary_source).lower()

    # With estimated positions, allow UTIL hitters to fill non-pitcher hitter slots.
    if source == "estimated":
        if pos == "UTIL" and slot not in ["P", "QB", "DST", "DEF", "G"]:
            return True

    return eligible_for_slot(position, slot)


def fallback_value_lineup(pool, platform, sport, style, salary_cap, build_type="Cash"):
    """
    Backup builder if strict slot matching fails.
    Still respects cap and roster size. Used only when positions are estimated.
    """
    rules = dfs_get_rules(platform, sport, style)
    roster_size = len(rules["slots"])

    p = pool.copy()
    if p.empty:
        return []

    p["Build Score"] = p.apply(lambda r: score_player_for_build(r, build_type), axis=1)
    p["Value"] = p["Build Score"] / (pd.to_numeric(p["Salary"], errors="coerce").fillna(9999) / 1000)
    p = p.sort_values(["Value", "Build Score", "DFS Projection"], ascending=False)

    lineup = []
    used = set()
    salary = 0

    # Ensure at least required pitcher count for MLB Classic.
    slots = rules["slots"]
    required_p = sum(1 for s in slots if s == "P")

    if required_p:
        pitchers = p[p["Position"].astype(str).str.upper().eq("P")]
        for _, row in pitchers.iterrows():
            if len([x for x in lineup if x.get("Roster Slot") == "P"]) >= required_p:
                break
            sal = int(row.get("Salary", 0) or 0)
            player = str(row.get("Player", ""))
            if player in used or salary + sal > int(salary_cap):
                continue
            d = row.to_dict()
            d["Roster Slot"] = "P"
            lineup.append(d)
            used.add(player)
            salary += sal

    remaining_slots = [s for s in slots if not (s == "P" and len([x for x in lineup if x.get("Roster Slot") == "P"]) > slots[:slots.index(s)+1].count("P"))]
    # Simpler slot list after already filling pitchers.
    remaining_slots = slots[len(lineup):]

    for slot in remaining_slots:
        for _, row in p.iterrows():
            player = str(row.get("Player", ""))
            if player in used:
                continue
            sal = int(row.get("Salary", 0) or 0)
            if salary + sal > int(salary_cap):
                continue
            if slot == "P" and str(row.get("Position", "")).upper() != "P":
                continue

            d = row.to_dict()
            d["Roster Slot"] = slot
            lineup.append(d)
            used.add(player)
            salary += sal
            break

    if len(lineup) != roster_size:
        return []

    return [{
        "Key": tuple(sorted(x["Player"] for x in lineup)),
        "Build Type": build_type + " Research",
        "Platform": platform,
        "Sport": sport,
        "Style": style,
        "Salary Cap": int(salary_cap),
        "Salary Used": int(salary),
        "Salary Left": int(salary_cap) - int(salary),
        "Players": lineup,
        "Projected": round(sum(float(x.get("DFS Projection", 0) or 0) for x in lineup), 2),
        "Ceiling": round(sum(float(x.get("Ceiling", 0) or 0) for x in lineup), 2),
        "Floor": round(sum(float(x.get("Floor", 0) or 0) for x in lineup), 2),
        "Avg Confidence": round(sum(float(x.get("DFS Confidence", 50) or 50) for x in lineup) / len(lineup), 1),
    }]



# =========================================================
# DFS REAL SALARY SOURCE HELPERS V84
# =========================================================

@st.cache_data(ttl=600, show_spinner=False)
def read_dfs_salary_url_cached(url, platform="DraftKings"):
    """
    Pull exact DFS salaries from a pasted CSV URL.
    Works with DraftKings/FanDuel salary CSV links when the URL is accessible.
    """
    if not url or not str(url).strip():
        return pd.DataFrame(), "No URL provided."

    try:
        r = requests.get(str(url).strip(), timeout=(8, 25), headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return pd.DataFrame(), f"URL returned HTTP {r.status_code}."

        text = r.text
        if not text or "," not in text:
            return pd.DataFrame(), "URL did not return CSV text."

        from io import StringIO
        raw = pd.read_csv(StringIO(text))

        # Re-use the same normalizer by writing a temp-like object into dataframe parser logic.
        salary_df = normalize_dfs_salary_dataframe(raw, platform=platform)
        if salary_df.empty:
            return pd.DataFrame(), "CSV loaded but salary columns were not recognized."

        return salary_df, f"Loaded {len(salary_df)} salaries from URL."

    except Exception as e:
        return pd.DataFrame(), f"Could not load salary URL: {type(e).__name__}: {e}"


def normalize_dfs_salary_dataframe(sal, platform="DraftKings"):
    """
    Normalizes common DK/FD salary CSV formats.
    """
    if sal is None or sal.empty:
        return pd.DataFrame()

    sal = sal.copy()
    original_cols = list(sal.columns)
    lower = {str(c).lower().strip(): c for c in original_cols}

    name_col = None
    for cand in ["name", "player", "nickname", "player name"]:
        if cand in lower:
            name_col = lower[cand]
            break

    if name_col is None and "first name" in lower and "last name" in lower:
        sal["Name"] = sal[lower["first name"]].astype(str) + " " + sal[lower["last name"]].astype(str)
        name_col = "Name"

    salary_col = None
    for cand in ["salary", "salary ($)", "dk salary", "fd salary"]:
        if cand in lower:
            salary_col = lower[cand]
            break

    pos_col = None
    for cand in ["roster position", "position", "positions"]:
        if cand in lower:
            pos_col = lower[cand]
            break

    team_col = None
    for cand in ["teamabbrev", "team", "team abbreviation"]:
        if cand in lower:
            team_col = lower[cand]
            break

    game_col = None
    for cand in ["game info", "game", "matchup"]:
        if cand in lower:
            game_col = lower[cand]
            break

    if name_col is None or salary_col is None:
        return pd.DataFrame()

    out = pd.DataFrame()
    out["DFS Name"] = sal[name_col].astype(str)
    out["Join Name"] = out["DFS Name"].apply(normalize_player_name_for_join)
    out["DFS Salary"] = pd.to_numeric(sal[salary_col], errors="coerce").fillna(0).astype(int)
    out["DFS Position"] = sal[pos_col].astype(str) if pos_col else "UTIL"
    out["DFS Team"] = sal[team_col].astype(str) if team_col else ""
    out["DFS Game Info"] = sal[game_col].astype(str) if game_col else ""
    out["Platform"] = platform

    out = out[out["DFS Salary"] > 0].copy()
    return out.drop_duplicates(subset=["Join Name", "DFS Salary", "DFS Position"], keep="first")


def read_dfs_salary_file_v84(uploaded_file, platform="DraftKings"):
    if uploaded_file is None:
        return pd.DataFrame()

    try:
        sal = pd.read_csv(uploaded_file)
    except Exception:
        return pd.DataFrame()

    return normalize_dfs_salary_dataframe(sal, platform=platform)


def combine_salary_sources(uploaded_file=None, salary_url="", platform="DraftKings"):
    """
    Priority:
    1. URL exact salary source
    2. Uploaded CSV exact salary source
    3. Empty = estimated
    """
    url_df = pd.DataFrame()
    url_msg = ""

    if salary_url and str(salary_url).strip():
        url_df, url_msg = read_dfs_salary_url_cached(salary_url, platform)

    if not url_df.empty:
        url_df["Salary Source Label"] = f"{platform} URL"
        return url_df, f"{platform} URL", url_msg

    csv_df = read_dfs_salary_file_v84(uploaded_file, platform) if uploaded_file is not None else pd.DataFrame()
    if not csv_df.empty:
        csv_df["Salary Source Label"] = "CSV"
        return csv_df, "CSV", f"Loaded {len(csv_df)} salaries from uploaded CSV."

    return pd.DataFrame(), "Estimated", url_msg if url_msg else "Using estimated salaries."


def minimum_salary_used(platform, sport, style, salary_cap, salary_source_label):
    """
    With real salary data, force better cap usage.
    With estimated salaries, keep flexible because salaries are synthetic.
    """
    source = str(salary_source_label).lower()
    if "estimated" in source:
        return int(float(salary_cap) * 0.58)

    if style and ("showdown" in str(style).lower() or "single" in str(style).lower()):
        return int(float(salary_cap) * 0.90)

    return int(float(salary_cap) * 0.94)


def candidate_lineup_score(lineup_rows, salary_used, salary_cap, build_type, salary_source_label):
    proj = sum(float(x.get("DFS Projection", 0) or 0) for x in lineup_rows)
    ceil = sum(float(x.get("Ceiling", 0) or 0) for x in lineup_rows)
    floor = sum(float(x.get("Floor", 0) or 0) for x in lineup_rows)
    lev = sum(float(x.get("Leverage", 0) or 0) for x in lineup_rows)

    cap_use = float(salary_used) / max(float(salary_cap), 1)
    build = str(build_type).lower()

    if "cash" in build:
        base = proj * 1.15 + floor * 0.65
    elif "gpp" in build:
        base = ceil * 1.05 + lev * 0.75 + proj * 0.35
    elif "contrarian" in build:
        base = ceil * 0.8 + lev * 1.25 + proj * 0.25
    else:
        base = proj

    # Real salaries should use most of cap. Estimated salaries get lighter penalty.
    source = str(salary_source_label).lower()
    cap_bonus = cap_use * (25 if "estimated" not in source else 8)
    return base + cap_bonus


def optimize_roster_by_slots_v84(pool, platform, sport, style, salary_cap, build_type="Cash", max_lineups=5, salary_source_label="Estimated"):
    rules = dfs_get_rules(platform, sport, style)
    slots = list(rules["slots"])

    if pool is None or pool.empty:
        return []

    p = pool.copy()
    p["Build Score"] = p.apply(lambda r: score_player_for_build(r, build_type), axis=1)
    p["Value"] = p["Build Score"] / (pd.to_numeric(p["Salary"], errors="coerce").fillna(9999) / 1000)
    p = p.sort_values(["Build Score", "Value", "DFS Projection"], ascending=False)

    rows = p.to_dict("records")
    lineups = []
    min_salary = minimum_salary_used(platform, sport, style, salary_cap, salary_source_label)

    restrictive_slots = sorted(slots, key=lambda s: 99 if s in ["UTIL", "FLEX"] else 1)

    # Try a wider set of starts and scoring methods so cap usage improves.
    for start_idx in range(min(len(rows), max_lineups * 60)):
        used = set()
        salary = 0
        lineup_rows = []

        ordered_rows = rows[start_idx:] + rows[:start_idx]

        for slot in restrictive_slots:
            best = None
            best_score = -999999

            for cand in ordered_rows:
                player = str(cand.get("Player", "")).strip()
                if not player or player in used:
                    continue

                cand_salary = int(cand.get("Salary", 0) or 0)
                if salary + cand_salary > int(salary_cap):
                    continue

                if not eligible_for_slot_v82(cand.get("Position", "UTIL"), slot, cand.get("Salary Source", salary_source_label)):
                    continue

                # Prefer better projection but also spend salary responsibly.
                raw_score = float(cand.get("Build Score", 0) or 0)
                sal_score = cand_salary / 1000
                score = raw_score + (sal_score * (0.35 if "estimated" not in str(salary_source_label).lower() else 0.08))

                if score > best_score:
                    best = cand
                    best_score = score

            if best is None:
                break

            best_copy = dict(best)
            best_copy["Roster Slot"] = slot
            lineup_rows.append(best_copy)
            used.add(str(best.get("Player", "")).strip())
            salary += int(best.get("Salary", 0) or 0)

        if len(lineup_rows) == len(slots):
            if salary < min_salary:
                # Keep looking for better cap usage.
                continue

            key = tuple(sorted(x["Player"] for x in lineup_rows))
            if key in [l["Key"] for l in lineups]:
                continue

            lineups.append({
                "Key": key,
                "Build Type": build_type,
                "Platform": platform,
                "Sport": sport,
                "Style": style,
                "Salary Cap": int(salary_cap),
                "Salary Used": int(salary),
                "Salary Left": int(salary_cap) - int(salary),
                "Players": lineup_rows,
                "Projected": round(sum(float(x.get("DFS Projection", 0) or 0) for x in lineup_rows), 2),
                "Ceiling": round(sum(float(x.get("Ceiling", 0) or 0) for x in lineup_rows), 2),
                "Floor": round(sum(float(x.get("Floor", 0) or 0) for x in lineup_rows), 2),
                "Avg Confidence": round(sum(float(x.get("DFS Confidence", 50) or 50) for x in lineup_rows) / len(lineup_rows), 1),
                "Lineup Score": round(candidate_lineup_score(lineup_rows, salary, salary_cap, build_type, salary_source_label), 2),
            })

        if len(lineups) >= max_lineups:
            break

    if not lineups and "estimated" in str(salary_source_label).lower():
        fallback = fallback_value_lineup(pool, platform, sport, style, salary_cap, build_type=build_type)
        if fallback:
            return fallback

    return sorted(lineups, key=lambda x: (x.get("Lineup Score", 0), x["Projected"], -x["Salary Left"]), reverse=True)[:max_lineups]



# =========================================================
# DFS AUTO SALARY LOADER V85
# =========================================================

@st.cache_data(ttl=900, show_spinner=False)
def try_read_salary_csv_url_v87(url, platform="DraftKings"):
    try:
        r = requests.get(
            url,
            timeout=(6, 20),
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/csv,application/csv,text/plain,*/*",
            },
        )

        if r.status_code != 200:
            return pd.DataFrame(), f"HTTP {r.status_code}"

        text = r.text or ""
        if "," not in text or len(text) < 200:
            return pd.DataFrame(), "not a CSV response"

        from io import StringIO
        raw = pd.read_csv(StringIO(text))
        normalized = normalize_dfs_salary_dataframe(raw, platform=platform)

        if normalized.empty:
            return pd.DataFrame(), "CSV did not match known salary format"

        normalized["Auto Source URL"] = url
        normalized["Salary Source Label"] = f"{platform} Auto"
        return normalized, f"Loaded {len(normalized)} salaries"

    except Exception as e:
        return pd.DataFrame(), f"{type(e).__name__}: {e}"


def dk_sport_code(sport):
    mapping = {
        "MLB": "MLB",
        "NBA": "NBA",
        "WNBA": "WNBA",
        "NFL": "NFL",
        "NHL": "NHL",
        "UFC/MMA": "MMA",
        "Soccer": "SOC",
    }
    return mapping.get(str(sport), str(sport).upper())


@st.cache_data(ttl=900, show_spinner=False)
def discover_draftkings_salary_urls(sport="MLB"):
    """
    Experimental DraftKings salary discovery.
    DraftKings changes public endpoints often, so this returns candidate URLs and
    tests them. If none work, user can still upload a CSV.
    """
    sport_code = dk_sport_code(sport)

    candidates = []

    # Common manually downloadable salary CSV endpoint patterns.
    # These endpoints may be blocked/changed by DraftKings, but when public they work.
    base_candidates = [
        f"https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=0&draftGroupId={{draft_group_id}}",
        f"https://www.draftkings.com/lineup/getavailableplayerscsv?draftGroupId={{draft_group_id}}",
    ]

    # Try to discover draft groups from common lobby endpoints.
    lobby_urls = [
        "https://api.draftkings.com/contests/v1/contests/lobby",
        "https://www.draftkings.com/lobby/getcontests?sport=" + sport_code,
        "https://api.draftkings.com/draftgroups/v1/draftgroups?sport=" + sport_code,
    ]

    draft_group_ids = []

    for lobby_url in lobby_urls:
        try:
            r = requests.get(
                lobby_url,
                timeout=(6, 18),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            if r.status_code != 200:
                continue

            try:
                payload = r.json()
            except Exception:
                continue

            # Walk nested json looking for draftGroupId-like keys.
            stack = [payload]
            while stack:
                obj = stack.pop()
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        lk = str(k).lower()
                        if "draftgroupid" in lk or "draft_group_id" in lk:
                            if str(v).isdigit():
                                draft_group_ids.append(str(v))
                        elif isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(obj, list):
                    stack.extend(obj)
        except Exception:
            continue

    # Deduplicate and create salary CSV candidates.
    seen = set()
    for dg in draft_group_ids:
        if dg in seen:
            continue
        seen.add(dg)
        for pattern in base_candidates:
            candidates.append(pattern.format(draft_group_id=dg))

    return candidates[:30]


@st.cache_data(ttl=900, show_spinner=False)
def auto_load_dfs_salaries_v87(platform="DraftKings", sport="MLB"):
    """
    Auto-load salary feed.
    Currently DraftKings has the best chance through public salary CSV patterns.
    FanDuel often requires manual salary CSV download, so fallback is expected.
    """
    platform = str(platform)

    if platform == "DraftKings":
        urls = discover_draftkings_salary_urls(sport)
        errors = []

        for url in urls:
            df, msg = try_read_salary_csv_url_v87(url, platform=platform)
            if not df.empty:
                return df, f"Auto-loaded DraftKings salaries. {msg}"
            errors.append(f"{url} -> {msg}")

        return pd.DataFrame(), "Auto-loader could not access DraftKings salary CSV for this slate. Upload CSV as backup."

    if platform == "FanDuel":
        return pd.DataFrame(), "FanDuel automatic salary feed is not public/reliable yet. Upload FanDuel salary CSV as backup."

    return pd.DataFrame(), "Unsupported platform."


def combine_salary_sources_v85(uploaded_file=None, salary_url="", platform="DraftKings", sport="MLB", use_auto=False):
    """
    Priority:
    1. Auto loader when requested
    2. Pasted URL
    3. Uploaded CSV
    4. Estimated fallback
    """
    if use_auto:
        auto_df, auto_msg = auto_load_dfs_salaries_v87(platform=platform, sport=sport)
        if not auto_df.empty:
            auto_df["Salary Source Label"] = f"{platform} Auto"
            return auto_df, f"{platform} Auto", auto_msg

    salary_df, label, msg = combine_salary_sources(
        uploaded_file=uploaded_file,
        salary_url=salary_url,
        platform=platform,
    )

    return salary_df, label, msg



# =========================================================
# DFS DK SLATE DISCOVERY V86
# =========================================================

def flatten_json_items(obj):
    """Yield dictionaries from nested JSON."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from flatten_json_items(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from flatten_json_items(x)


def parse_dk_draft_groups_from_payload(payload, sport="MLB"):
    rows = []
    sport_code = dk_sport_code(sport).upper()

    for item in flatten_json_items(payload):
        if not isinstance(item, dict):
            continue

        keys = {str(k).lower(): k for k in item.keys()}

        dg_key = None
        for k in keys:
            if "draftgroupid" in k or "draft_group_id" in k:
                dg_key = keys[k]
                break

        if dg_key is None:
            continue

        dg = item.get(dg_key)
        if not str(dg).isdigit():
            continue

        name = ""
        for cand in ["name", "contestname", "draftgroupdescription", "description", "displayname", "gameType", "gameTypeName"]:
            if cand.lower() in keys:
                name = str(item.get(keys[cand.lower()], "") or "")
                if name:
                    break

        start_time = ""
        for cand in ["starttime", "startDate", "startDateEst", "startDateTime", "startsAt"]:
            if cand.lower() in keys:
                start_time = str(item.get(keys[cand.lower()], "") or "")
                if start_time:
                    break

        game_count = None
        for cand in ["gamecount", "gamescount", "numberofgames", "contestgamecount"]:
            if cand.lower() in keys:
                try:
                    game_count = int(float(item.get(keys[cand.lower()], 0) or 0))
                except Exception:
                    game_count = None
                break

        s_val = ""
        for cand in ["sport", "sportname", "sportCode"]:
            if cand.lower() in keys:
                s_val = str(item.get(keys[cand.lower()], "") or "")
                break

        # Keep if sport info matches or if the endpoint was sport-specific/unknown.
        joined = " ".join([name, s_val]).upper()
        if sport_code not in joined and sport.upper() not in joined and s_val:
            continue

        rows.append({
            "Draft Group ID": str(dg),
            "Slate Name": name if name else f"{sport} Draft Group {dg}",
            "Start Time": start_time,
            "Games": game_count if game_count is not None else 0,
        })

    if not rows:
        return pd.DataFrame(columns=["Draft Group ID", "Slate Name", "Start Time", "Games"])

    out = pd.DataFrame(rows).drop_duplicates(subset=["Draft Group ID"], keep="first")

    # Fill labels
    out["Slate Label"] = out.apply(
        lambda r: f"{r['Slate Name']} • {r['Games']} games • {r['Draft Group ID']}",
        axis=1,
    )
    return out.sort_values(["Games", "Start Time"], ascending=[False, True]).reset_index(drop=True)


@st.cache_data(ttl=900, show_spinner=False)
def discover_dk_slates_v86(sport="MLB"):
    sport_code = dk_sport_code(sport)

    urls = [
        f"https://api.draftkings.com/draftgroups/v1/draftgroups?sport={sport_code}",
        f"https://www.draftkings.com/lobby/getcontests?sport={sport_code}",
        "https://api.draftkings.com/contests/v1/contests/lobby",
    ]

    all_slates = []
    errors = []

    for url in urls:
        try:
            r = requests.get(
                url,
                timeout=(6, 20),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json,text/plain,*/*",
                },
            )

            if r.status_code != 200:
                errors.append(f"{url} HTTP {r.status_code}")
                continue

            try:
                payload = r.json()
            except Exception:
                errors.append(f"{url} non-json")
                continue

            parsed = parse_dk_draft_groups_from_payload(payload, sport=sport)
            if not parsed.empty:
                parsed["Source"] = url
                all_slates.append(parsed)

        except Exception as e:
            errors.append(f"{url} {type(e).__name__}: {e}")

    if all_slates:
        out = pd.concat(all_slates, ignore_index=True)
        out = out.drop_duplicates(subset=["Draft Group ID"], keep="first")
        out = out.sort_values(["Games", "Start Time"], ascending=[False, True]).reset_index(drop=True)
        out["Slate Label"] = out.apply(
            lambda r: f"{r['Slate Name']} • {r['Games']} games • ID {r['Draft Group ID']}",
            axis=1,
        )
        return out, "Found DraftKings slates."

    return pd.DataFrame(columns=["Draft Group ID", "Slate Name", "Start Time", "Games", "Slate Label"]), "Could not discover DraftKings slates. DK may be blocking the public endpoint."


def dk_salary_url_for_draft_group(draft_group_id):
    return f"https://www.draftkings.com/lineup/getavailableplayerscsv?draftGroupId={draft_group_id}"


@st.cache_data(ttl=900, show_spinner=False)
def load_dk_salary_by_draft_group_v87(draft_group_id, sport="MLB"):
    if not draft_group_id:
        return pd.DataFrame(), "No draft group selected."

    url = dk_salary_url_for_draft_group(str(draft_group_id))
    df, msg = try_read_salary_csv_url_v87(url, platform="DraftKings")

    if not df.empty:
        df["Draft Group ID"] = str(draft_group_id)
        df["Salary Source Label"] = "DraftKings Slate"
        return df, f"Loaded {len(df)} exact DK salaries for draft group {draft_group_id}."

    return pd.DataFrame(), f"Could not load DK salary CSV for draft group {draft_group_id}: {msg}"


def salary_coverage_report(pool):
    if pool is None or pool.empty:
        return {
            "Pool": 0,
            "Matched": 0,
            "Unmatched": 0,
            "Coverage": 0.0,
            "Positions": "",
        }

    p = pool.copy()
    source = p.get("Salary Source", pd.Series(["Estimated"] * len(p), index=p.index)).astype(str)
    matched = int((~source.str.lower().eq("estimated")).sum())
    total = int(len(p))
    unmatched = total - matched
    coverage = round((matched / total) * 100, 1) if total else 0.0

    pos_counts = p.get("Position", pd.Series([], dtype=str)).astype(str).value_counts().to_dict()
    pos_txt = " · ".join([f"{k}: {v}" for k, v in pos_counts.items()])

    return {
        "Pool": total,
        "Matched": matched,
        "Unmatched": unmatched,
        "Coverage": coverage,
        "Positions": pos_txt,
    }


def is_salary_coverage_good(report, salary_source_label="Estimated"):
    if str(salary_source_label).lower() == "estimated":
        return True

    # V88: allow optimizer once enough exact salaries exist to fill a legal slate,
    # but still block tiny/partial feeds.
    if report["Matched"] < 40:
        return False

    if report["Coverage"] < 25:
        return False

    return True


def combine_salary_sources_v87(uploaded_file=None, salary_url="", platform="DraftKings", sport="MLB", use_auto=False, draft_group_id=None):
    """
    Priority:
    1. Selected DraftKings slate draft group
    2. Auto loader
    3. Pasted URL
    4. Uploaded CSV
    5. Estimated
    """
    if platform == "DraftKings" and draft_group_id:
        slate_df, slate_msg = load_dk_salary_by_draft_group_v87(draft_group_id, sport=sport)
        if not slate_df.empty:
            return slate_df, "DraftKings Slate", slate_msg

    if use_auto:
        auto_df, auto_msg = auto_load_dfs_salaries_v87(platform=platform, sport=sport)
        if not auto_df.empty:
            auto_df["Salary Source Label"] = f"{platform} Auto"
            return auto_df, f"{platform} Auto", auto_msg

    return combine_salary_sources_v85(
        uploaded_file=uploaded_file,
        salary_url=salary_url,
        platform=platform,
        sport=sport,
        use_auto=False,
    )



# =========================================================
# DFS V87 DK SALARY PARSING + FUZZY MATCHING
# =========================================================

def normalize_dk_position(pos):
    txt = str(pos or "").upper().strip()

    if not txt or txt in ["NAN", "NONE"]:
        return "UTIL"

    # DraftKings files can contain UTIL/BN, C/1B, OF, RP/SP, etc.
    txt = txt.replace("UTIL/BN", "UTIL")
    txt = txt.replace("BN", "UTIL")
    txt = txt.replace("SP", "P")
    txt = txt.replace("RP", "P")
    txt = txt.replace("IF", "UTIL")

    parts = [p.strip() for p in re.split(r"[/,]", txt) if p.strip()]
    if not parts:
        return txt

    # Preserve useful DK combined slots.
    if "C" in parts and "1B" in parts:
        return "C/1B"

    # Pick the most DFS-useful position.
    priority = ["P", "C/1B", "C", "1B", "2B", "3B", "SS", "OF", "PG", "SG", "SF", "PF", "C", "QB", "RB", "WR", "TE", "DST", "D", "G", "F", "M", "W", "UTIL"]
    for p in priority:
        if p in parts or p == txt:
            if p in ["C", "1B"] and ("C" in parts or "1B" in parts):
                return "C/1B"
            return p

    return parts[0]


def normalize_dfs_salary_dataframe_v87(sal, platform="DraftKings"):
    """
    Stronger DK/FD salary parser.
    Handles:
    - DraftKings DKSalary CSV
    - FanDuel salary CSV
    - Name / Player / Nickname
    - Roster Position / Position
    - UTIL/BN -> UTIL
    """
    if sal is None or sal.empty:
        return pd.DataFrame()

    sal = sal.copy()
    original_cols = list(sal.columns)
    lower = {str(c).lower().strip(): c for c in original_cols}

    name_col = None
    for cand in ["name", "player", "nickname", "player name", "display name"]:
        if cand in lower:
            name_col = lower[cand]
            break

    if name_col is None and "first name" in lower and "last name" in lower:
        sal["Name"] = sal[lower["first name"]].astype(str) + " " + sal[lower["last name"]].astype(str)
        name_col = "Name"

    salary_col = None
    for cand in ["salary", "salary ($)", "dk salary", "fd salary"]:
        if cand in lower:
            salary_col = lower[cand]
            break

    pos_col = None
    # IMPORTANT: DraftKings usually has both Position and Roster Position.
    # Position is the player eligibility. Roster Position often says UTIL/BN.
    for cand in ["position", "positions", "player position", "eligible positions", "roster position"]:
        if cand in lower:
            pos_col = lower[cand]
            break

    roster_col = lower.get("roster position")

    team_col = None
    for cand in ["teamabbrev", "team", "team abbreviation", "teamabbr"]:
        if cand in lower:
            team_col = lower[cand]
            break

    game_col = None
    for cand in ["game info", "game", "matchup"]:
        if cand in lower:
            game_col = lower[cand]
            break

    if name_col is None or salary_col is None:
        return pd.DataFrame()

    out = pd.DataFrame()
    out["DFS Name"] = sal[name_col].astype(str)
    out["Join Name"] = out["DFS Name"].apply(normalize_player_name_for_join)
    out["DFS Salary"] = pd.to_numeric(sal[salary_col], errors="coerce").fillna(0).astype(int)

    if pos_col:
        out["DFS Position Raw"] = sal[pos_col].astype(str)
    elif roster_col:
        out["DFS Position Raw"] = sal[roster_col].astype(str)
    else:
        out["DFS Position Raw"] = "UTIL"

    out["DFS Position"] = out["DFS Position Raw"].apply(normalize_dk_position)

    # If Position was useless but Roster Position exists and is better, keep position raw.
    if roster_col and pos_col and out["DFS Position"].astype(str).str.upper().eq("UTIL").mean() > 0.75:
        alt = sal[roster_col].astype(str).apply(normalize_dk_position)
        # Only use alt if it improves.
        if alt.astype(str).str.upper().eq("UTIL").mean() < out["DFS Position"].astype(str).str.upper().eq("UTIL").mean():
            out["DFS Position"] = alt

    out["DFS Team"] = sal[team_col].astype(str) if team_col else ""
    out["DFS Game Info"] = sal[game_col].astype(str) if game_col else ""
    out["Platform"] = platform

    out = out[out["DFS Salary"] > 0].copy()
    return out.drop_duplicates(subset=["Join Name"], keep="first")


def read_dfs_salary_file_v87(uploaded_file, platform="DraftKings"):
    if uploaded_file is None:
        return pd.DataFrame()

    try:
        sal = pd.read_csv(uploaded_file)
    except Exception:
        return pd.DataFrame()

    out = normalize_dfs_salary_dataframe_v87(sal, platform=platform)
    if not out.empty:
        out["Salary Source Label"] = "Uploaded CSV"
    return out


@st.cache_data(ttl=600, show_spinner=False)
def read_dfs_salary_url_cached_v87(url, platform="DraftKings"):
    if not url or not str(url).strip():
        return pd.DataFrame(), "No URL provided."

    try:
        r = requests.get(str(url).strip(), timeout=(8, 25), headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return pd.DataFrame(), f"URL returned HTTP {r.status_code}."

        text = r.text
        if not text or "," not in text:
            return pd.DataFrame(), "URL did not return CSV text."

        from io import StringIO
        raw = pd.read_csv(StringIO(text))
        salary_df = normalize_dfs_salary_dataframe_v87(raw, platform=platform)

        if salary_df.empty:
            return pd.DataFrame(), "CSV loaded but salary columns were not recognized."

        salary_df["Salary Source Label"] = f"{platform} URL"
        return salary_df, f"Loaded {len(salary_df)} salaries from URL."

    except Exception as e:
        return pd.DataFrame(), f"Could not load salary URL: {type(e).__name__}: {e}"


@st.cache_data(ttl=900, show_spinner=False)
def try_read_salary_csv_url_v87(url, platform="DraftKings"):
    try:
        r = requests.get(
            url,
            timeout=(6, 20),
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/csv,application/csv,text/plain,*/*",
            },
        )

        if r.status_code != 200:
            return pd.DataFrame(), f"HTTP {r.status_code}"

        text = r.text or ""
        if "," not in text or len(text) < 200:
            return pd.DataFrame(), "not a CSV response"

        from io import StringIO
        raw = pd.read_csv(StringIO(text))
        normalized = normalize_dfs_salary_dataframe_v87(raw, platform=platform)

        if normalized.empty:
            return pd.DataFrame(), "CSV did not match known salary format"

        normalized["Auto Source URL"] = url
        normalized["Salary Source Label"] = f"{platform} Auto"
        return normalized, f"Loaded {len(normalized)} salaries"

    except Exception as e:
        return pd.DataFrame(), f"{type(e).__name__}: {e}"


def fuzzy_score_name(a, b):
    """
    Lightweight fuzzy score without extra dependencies.
    Good enough for J.J. vs JJ, accents, suffixes, initials.
    """
    import difflib

    aa = normalize_player_name_for_join(a)
    bb = normalize_player_name_for_join(b)

    if not aa or not bb:
        return 0

    if aa == bb:
        return 100

    if aa in bb or bb in aa:
        return 92

    return int(difflib.SequenceMatcher(None, aa, bb).ratio() * 100)


def attach_salary_to_pool_v87(pool, salary_df, platform="DraftKings"):
    """
    Exact join first, then fuzzy join for unmatched players.
    """
    pool = pool.copy()

    if salary_df is None or salary_df.empty:
        return pool

    sal = salary_df.copy()
    sal["Join Name"] = sal["DFS Name"].apply(normalize_player_name_for_join)

    pool["Join Name"] = pool["Player"].apply(normalize_player_name_for_join)

    merged = pool.merge(
        sal[["Join Name", "DFS Name", "DFS Salary", "DFS Position", "DFS Team", "DFS Game Info", "Salary Source Label"]],
        how="left",
        on="Join Name",
    )

    unmatched = merged["DFS Salary"].isna()
    if unmatched.any():
        sal_records = sal.to_dict("records")

        for idx in merged[unmatched].index:
            player = merged.at[idx, "Player"]
            best = None
            best_score = 0

            for srow in sal_records:
                score = fuzzy_score_name(player, srow.get("DFS Name", ""))
                if score > best_score:
                    best_score = score
                    best = srow

            if best is not None and best_score >= 88:
                merged.at[idx, "DFS Name"] = best.get("DFS Name", "")
                merged.at[idx, "DFS Salary"] = best.get("DFS Salary", None)
                merged.at[idx, "DFS Position"] = best.get("DFS Position", "")
                merged.at[idx, "DFS Team"] = best.get("DFS Team", "")
                merged.at[idx, "DFS Game Info"] = best.get("DFS Game Info", "")
                merged.at[idx, "Salary Source Label"] = best.get("Salary Source Label", "Fuzzy Salary Match")
                merged.at[idx, "Salary Match Score"] = best_score
            else:
                merged.at[idx, "Salary Match Score"] = best_score

    merged["Salary"] = pd.to_numeric(merged["DFS Salary"], errors="coerce")
    merged["Position"] = merged["DFS Position"].fillna(merged.get("Inferred Position", "UTIL")).apply(normalize_dk_position)
    merged["Salary Source"] = merged.apply(
        lambda r: r.get("Salary Source Label", "Salary CSV") if pd.notna(r.get("Salary")) and float(r.get("Salary", 0) or 0) > 0 else "Estimated",
        axis=1,
    )

    return merged


def combine_salary_sources_v87(uploaded_file=None, salary_url="", platform="DraftKings", sport="MLB", use_auto=False, draft_group_id=None):
    """
    Priority changed:
    1. Uploaded CSV, because user likely uploaded exact slate salary file.
    2. Pasted URL
    3. Selected DK slate auto
    4. Auto loader fallback
    5. Estimated
    """
    csv_df = read_dfs_salary_file_v87(uploaded_file, platform) if uploaded_file is not None else pd.DataFrame()
    if not csv_df.empty:
        return csv_df, "Uploaded CSV", f"Loaded {len(csv_df)} salaries from uploaded CSV."

    if salary_url and str(salary_url).strip():
        url_df, url_msg = read_dfs_salary_url_cached_v87(salary_url, platform)
        if not url_df.empty:
            return url_df, f"{platform} URL", url_msg

    if platform == "DraftKings" and draft_group_id:
        slate_df, slate_msg = load_dk_salary_by_draft_group_v87(draft_group_id, sport=sport)
        if not slate_df.empty:
            return slate_df, "DraftKings Slate", slate_msg

    if use_auto:
        auto_df, auto_msg = auto_load_dfs_salaries_v87(platform=platform, sport=sport)
        if not auto_df.empty:
            return auto_df, f"{platform} Auto", auto_msg

    return pd.DataFrame(), "Estimated", "Using estimated salaries."


@st.cache_data(ttl=900, show_spinner=False)
def load_dk_salary_by_draft_group_v87(draft_group_id, sport="MLB"):
    if not draft_group_id:
        return pd.DataFrame(), "No draft group selected."

    url = dk_salary_url_for_draft_group(str(draft_group_id))
    df, msg = try_read_salary_csv_url_v87(url, platform="DraftKings")

    if not df.empty:
        df["Draft Group ID"] = str(draft_group_id)
        df["Salary Source Label"] = "DraftKings Slate"
        return df, f"Loaded {len(df)} exact DK salaries for draft group {draft_group_id}."

    return pd.DataFrame(), f"Could not load DK salary CSV for draft group {draft_group_id}: {msg}"


@st.cache_data(ttl=900, show_spinner=False)
def auto_load_dfs_salaries_v87(platform="DraftKings", sport="MLB"):
    if platform == "DraftKings":
        slates, msg = discover_dk_slates_v86(sport)
        if not slates.empty:
            # Try biggest slates first.
            for _, row in slates.sort_values("Games", ascending=False).iterrows():
                dg = row.get("Draft Group ID")
                df, load_msg = load_dk_salary_by_draft_group_v87(dg, sport)
                if not df.empty and len(df) >= 100:
                    return df, f"Auto-loaded DraftKings slate {dg}. {load_msg}"

            # Return largest available even if small, but message will show low coverage later.
            first = slates.sort_values("Games", ascending=False).iloc[0]
            df, load_msg = load_dk_salary_by_draft_group_v87(first.get("Draft Group ID"), sport)
            if not df.empty:
                return df, f"Auto-loaded partial DraftKings salaries. {load_msg}"

        return pd.DataFrame(), "Auto-loader could not access a full DraftKings salary slate. Upload CSV as backup."

    if platform == "FanDuel":
        return pd.DataFrame(), "FanDuel automatic salary feed is not public/reliable yet. Upload FanDuel salary CSV as backup."

    return pd.DataFrame(), "Unsupported platform."



# =========================================================
# DFS V88 PLAYER NAME CLEANING + MATCH DEBUG
# =========================================================

def clean_prop_player_name(name):
    """
    Converts betting prop text into a clean DFS player name.

    Examples:
    - "Nick Gonzales Over +0.5 Hits (+120)" -> "Nick Gonzales"
    - "Mookie Betts Under 1.5 Total Bases" -> "Mookie Betts"
    - "J.J. Bleday - Hits" -> "J.J. Bleday"
    """
    txt = str(name or "").strip()

    if not txt:
        return ""

    # Remove odds.
    txt = re.sub(r"\([+-]?\d+\)", "", txt).strip()

    # Remove common prop side/text suffixes.
    txt = re.split(
        r"\s+(Over|Under|Yes|No)\s+[-+]?\d*\.?\d*",
        txt,
        flags=re.I,
    )[0].strip()

    txt = re.split(
        r"\s+(Over|Under|Yes|No)\s+",
        txt,
        flags=re.I,
    )[0].strip()

    # Remove dash suffixes that contain market names.
    txt = re.split(
        r"\s+-\s+(Hits|Total Bases|Runs|RBI|Walks|Strikeouts|Singles|Doubles|Home Runs|Bases|Assists|Points|Rebounds)",
        txt,
        flags=re.I,
    )[0].strip()

    # Remove market words if they are still attached.
    txt = re.sub(
        r"\b(Hits|Total Bases|Runs|RBI|Walks|Strikeouts|Singles|Doubles|Triples|Home Runs|Pitching|Earned Runs|Outs Recorded)\b.*$",
        "",
        txt,
        flags=re.I,
    ).strip()

    # Remove team separators if accidentally present.
    txt = re.split(r"\s+@\s+|\s+vs\.?\s+", txt, flags=re.I)[0].strip()

    # Clean whitespace.
    txt = re.sub(r"\s+", " ", txt).strip()

    return txt


def player_match_keys(name):
    """
    Multiple normalized keys for better DFS salary matching.
    """
    clean = clean_prop_player_name(name)
    raw = str(name or "").strip()

    keys = set()
    for n in [clean, raw]:
        if not n:
            continue

        base = normalize_player_name_for_join(n)
        if base:
            keys.add(base)

        # Remove common suffixes.
        no_suffix = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b$", "", n, flags=re.I).strip()
        ns = normalize_player_name_for_join(no_suffix)
        if ns:
            keys.add(ns)

        # Remove periods for initials.
        no_periods = n.replace(".", "")
        np = normalize_player_name_for_join(no_periods)
        if np:
            keys.add(np)

        # First initial + last name fallback.
        parts = re.findall(r"[A-Za-zÀ-ÿ']+", n)
        if len(parts) >= 2:
            fi_last = parts[0][0] + parts[-1]
            keys.add(normalize_player_name_for_join(fi_last))

    return [k for k in keys if k]


def salary_match_score(pool_name, dfs_name):
    """
    Stronger score for DFS salary matching.
    """
    import difflib

    pool_clean = clean_prop_player_name(pool_name)
    dfs_clean = clean_prop_player_name(dfs_name)

    p_keys = player_match_keys(pool_clean)
    d_keys = player_match_keys(dfs_clean)

    if not p_keys or not d_keys:
        return 0

    if set(p_keys) & set(d_keys):
        return 100

    best = 0
    for pk in p_keys:
        for dk in d_keys:
            if pk == dk:
                return 100
            if pk in dk or dk in pk:
                best = max(best, 94)
            best = max(best, int(difflib.SequenceMatcher(None, pk, dk).ratio() * 100))

    return best


def attach_salary_to_pool_v88(pool, salary_df, platform="DraftKings"):
    """
    V88 salary attach:
    - Clean prop-player names first
    - Exact multi-key match
    - Fuzzy fallback
    """
    pool = pool.copy()

    if salary_df is None or salary_df.empty:
        return pool

    sal = salary_df.copy()

    if "DFS Name" not in sal.columns:
        return pool

    sal["DFS Clean Name"] = sal["DFS Name"].apply(clean_prop_player_name)
    sal["Salary Keys"] = sal["DFS Clean Name"].apply(player_match_keys)

    # Build lookup map from every possible salary key.
    salary_lookup = {}
    for _, srow in sal.iterrows():
        for key in srow.get("Salary Keys", []):
            if key and key not in salary_lookup:
                salary_lookup[key] = srow.to_dict()

    pool["DFS Match Name"] = pool["Player"].apply(clean_prop_player_name)
    pool["Salary Match Score"] = 0
    pool["Matched DFS Name"] = ""

    salaries = []
    positions = []
    teams = []
    games = []
    sources = []
    matched_names = []
    scores = []

    sal_records = sal.to_dict("records")

    for _, prow in pool.iterrows():
        pname = prow.get("DFS Match Name", prow.get("Player", ""))
        keys = player_match_keys(pname)

        match = None
        score = 0

        # Exact multi-key match first.
        for key in keys:
            if key in salary_lookup:
                match = salary_lookup[key]
                score = 100
                break

        # Fuzzy fallback.
        if match is None:
            best_score = 0
            best_match = None
            for srow in sal_records:
                s = salary_match_score(pname, srow.get("DFS Name", ""))
                if s > best_score:
                    best_score = s
                    best_match = srow

            if best_match is not None and best_score >= 86:
                match = best_match
                score = best_score

        if match is not None:
            salaries.append(match.get("DFS Salary", None))
            positions.append(normalize_dk_position(match.get("DFS Position", "")))
            teams.append(match.get("DFS Team", ""))
            games.append(match.get("DFS Game Info", ""))
            sources.append(match.get("Salary Source Label", "Salary CSV"))
            matched_names.append(match.get("DFS Name", ""))
            scores.append(score)
        else:
            salaries.append(None)
            positions.append(prow.get("Inferred Position", "UTIL"))
            teams.append("")
            games.append("")
            sources.append("Estimated")
            matched_names.append("")
            scores.append(score)

    pool["DFS Salary"] = salaries
    pool["DFS Position"] = positions
    pool["DFS Team"] = teams
    pool["DFS Game Info"] = games
    pool["Matched DFS Name"] = matched_names
    pool["Salary Match Score"] = scores

    pool["Salary"] = pd.to_numeric(pool["DFS Salary"], errors="coerce")
    pool["Position"] = pool["DFS Position"].fillna(pool.get("Inferred Position", "UTIL")).apply(normalize_dk_position)
    pool["Salary Source"] = [
        src if pd.notna(salv) and float(salv or 0) > 0 else "Estimated"
        for src, salv in zip(sources, salaries)
    ]

    return pool


def salary_match_debug_table(pool, salary_df, max_rows=25):
    """
    Build debug tables for Streamlit display.
    """
    debug = {}

    if salary_df is None or salary_df.empty:
        debug["salary_sample"] = pd.DataFrame()
    else:
        s = salary_df.copy()
        for col in ["DFS Name", "Join Name", "DFS Position", "DFS Salary", "DFS Team", "DFS Game Info"]:
            if col not in s.columns:
                s[col] = ""
        s["Clean Name"] = s["DFS Name"].apply(clean_prop_player_name)
        s["Match Keys"] = s["Clean Name"].apply(lambda x: ", ".join(player_match_keys(x)[:3]))
        debug["salary_sample"] = s[["DFS Name", "Clean Name", "Match Keys", "DFS Position", "DFS Salary", "DFS Team", "DFS Game Info"]].head(max_rows)

    if pool is None or pool.empty:
        debug["pool_sample"] = pd.DataFrame()
        debug["unmatched"] = pd.DataFrame()
        debug["best_guesses"] = pd.DataFrame()
        return debug

    p = pool.copy()
    for col in ["Player", "DFS Match Name", "Matched DFS Name", "Salary", "Position", "Salary Source", "Salary Match Score"]:
        if col not in p.columns:
            p[col] = ""

    p["Clean Player"] = p["Player"].apply(clean_prop_player_name)
    p["Match Keys"] = p["Clean Player"].apply(lambda x: ", ".join(player_match_keys(x)[:3]))
    debug["pool_sample"] = p[["Player", "Clean Player", "Match Keys", "Matched DFS Name", "Salary", "Position", "Salary Source", "Salary Match Score"]].head(max_rows)

    unmatched = p[p["Salary Source"].astype(str).str.lower().eq("estimated")].copy()
    debug["unmatched"] = unmatched[["Player", "Clean Player", "Match Keys", "Position", "Salary Match Score"]].head(max_rows)

    guesses = []
    if salary_df is not None and not salary_df.empty and not unmatched.empty:
        sal_records = salary_df.to_dict("records")
        for _, row in unmatched.head(15).iterrows():
            best_name = ""
            best_score = 0
            for srow in sal_records:
                sc = salary_match_score(row.get("Clean Player", row.get("Player", "")), srow.get("DFS Name", ""))
                if sc > best_score:
                    best_score = sc
                    best_name = srow.get("DFS Name", "")
            guesses.append({
                "Pool Player": row.get("Player", ""),
                "Clean Player": row.get("Clean Player", ""),
                "Best DK Guess": best_name,
                "Score": best_score,
            })

    debug["best_guesses"] = pd.DataFrame(guesses)
    return debug


def render_salary_match_debug(pool, salary_df):
    with st.expander("Salary Match Debug"):
        dbg = salary_match_debug_table(pool, salary_df)

        st.markdown("##### DK/FanDuel Salary CSV sample")
        if dbg["salary_sample"].empty:
            st.info("No salary rows loaded.")
        else:
            st.dataframe(dbg["salary_sample"], use_container_width=True, hide_index=True)

        st.markdown("##### Betting player pool sample")
        if dbg["pool_sample"].empty:
            st.info("No player pool rows.")
        else:
            st.dataframe(dbg["pool_sample"], use_container_width=True, hide_index=True)

        st.markdown("##### Unmatched examples")
        if dbg["unmatched"].empty:
            st.success("No unmatched examples in sample.")
        else:
            st.dataframe(dbg["unmatched"], use_container_width=True, hide_index=True)

        st.markdown("##### Best fuzzy guesses")
        if dbg["best_guesses"].empty:
            st.info("No fuzzy guesses to show.")
        else:
            st.dataframe(dbg["best_guesses"], use_container_width=True, hide_index=True)



# =========================================================
# DFS V89 SLATE FILTER HELPERS
# =========================================================

DK_TEAM_ALIASES = {
    "ARI": ["Arizona Diamondbacks", "Diamondbacks"],
    "ATL": ["Atlanta Braves", "Braves"],
    "BAL": ["Baltimore Orioles", "Orioles"],
    "BOS": ["Boston Red Sox", "Red Sox"],
    "CHC": ["Chicago Cubs", "Cubs"],
    "CWS": ["Chicago White Sox", "White Sox"],
    "CHW": ["Chicago White Sox", "White Sox"],
    "CIN": ["Cincinnati Reds", "Reds"],
    "CLE": ["Cleveland Guardians", "Guardians"],
    "COL": ["Colorado Rockies", "Rockies"],
    "DET": ["Detroit Tigers", "Tigers"],
    "HOU": ["Houston Astros", "Astros"],
    "KC": ["Kansas City Royals", "Royals"],
    "KCR": ["Kansas City Royals", "Royals"],
    "LAA": ["Los Angeles Angels", "Angels"],
    "LAD": ["Los Angeles Dodgers", "Dodgers"],
    "MIA": ["Miami Marlins", "Marlins"],
    "MIL": ["Milwaukee Brewers", "Brewers"],
    "MIN": ["Minnesota Twins", "Twins"],
    "NYM": ["New York Mets", "Mets"],
    "NYY": ["New York Yankees", "Yankees"],
    "ATH": ["Athletics"],
    "OAK": ["Athletics", "Oakland Athletics"],
    "PHI": ["Philadelphia Phillies", "Phillies"],
    "PIT": ["Pittsburgh Pirates", "Pirates"],
    "SD": ["San Diego Padres", "Padres"],
    "SDP": ["San Diego Padres", "Padres"],
    "SEA": ["Seattle Mariners", "Mariners"],
    "SF": ["San Francisco Giants", "Giants"],
    "SFG": ["San Francisco Giants", "Giants"],
    "STL": ["St. Louis Cardinals", "Saint Louis Cardinals", "Cardinals"],
    "TB": ["Tampa Bay Rays", "Rays"],
    "TBR": ["Tampa Bay Rays", "Rays"],
    "TEX": ["Texas Rangers", "Rangers"],
    "TOR": ["Toronto Blue Jays", "Blue Jays"],
    "WSH": ["Washington Nationals", "Nationals"],
    "WAS": ["Washington Nationals", "Nationals"],
}


def extract_dk_game_codes(game_info):
    """
    DraftKings Game Info often looks like:
    "NYY@TOR 06/14/2026 01:10PM ET"
    Returns ["NYY", "TOR"].
    """
    txt = str(game_info or "").upper()
    m = re.search(r"\b([A-Z]{2,3})@([A-Z]{2,3})\b", txt)
    if not m:
        return []

    return [m.group(1), m.group(2)]


def dk_codes_to_team_terms(codes):
    terms = []
    for code in codes:
        code = str(code).upper().strip()
        terms.extend(DK_TEAM_ALIASES.get(code, [code]))
    return sorted(set([t for t in terms if t]))


def salary_df_slate_terms(salary_df):
    """
    Build a list of team-name terms that represent the exact DK salary slate.
    """
    if salary_df is None or salary_df.empty or "DFS Game Info" not in salary_df.columns:
        return []

    codes = []
    for g in salary_df["DFS Game Info"].dropna().astype(str).unique():
        codes.extend(extract_dk_game_codes(g))

    return dk_codes_to_team_terms(codes)


def salary_df_slate_games(salary_df):
    if salary_df is None or salary_df.empty or "DFS Game Info" not in salary_df.columns:
        return pd.DataFrame()

    rows = []
    seen = set()

    for g in salary_df["DFS Game Info"].dropna().astype(str).unique():
        codes = extract_dk_game_codes(g)
        if len(codes) != 2:
            continue

        terms = dk_codes_to_team_terms(codes)
        key = tuple(codes)
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "DK Game Info": g,
            "Away Code": codes[0],
            "Home Code": codes[1],
            "Matched Team Terms": " / ".join(terms),
        })

    return pd.DataFrame(rows)


def matchup_matches_slate_terms(matchup, terms):
    txt = str(matchup or "").lower()
    if not txt or not terms:
        return True

    return any(str(term).lower() in txt for term in terms)


def filter_betting_pool_to_salary_slate(df, salary_df, sport="MLB"):
    """
    If exact salary slate has game info, restrict betting board to those games.
    This prevents a Turbo/Main slate salary file from trying to match all MLB props.
    """
    board = ensure_schema(df)
    if board.empty:
        return board, {
            "Applied": False,
            "Terms": [],
            "Before": 0,
            "After": 0,
            "Reason": "empty board",
        }

    terms = salary_df_slate_terms(salary_df)
    before = len(board)

    if not terms:
        return board, {
            "Applied": False,
            "Terms": [],
            "Before": before,
            "After": before,
            "Reason": "no DK Game Info/team terms found",
        }

    if "Matchup" not in board.columns:
        return board, {
            "Applied": False,
            "Terms": terms,
            "Before": before,
            "After": before,
            "Reason": "no Matchup column",
        }

    filtered = board[board["Matchup"].apply(lambda m: matchup_matches_slate_terms(m, terms))].copy()

    # If the filter is too aggressive, return original so app remains usable.
    if filtered.empty:
        return board, {
            "Applied": False,
            "Terms": terms,
            "Before": before,
            "After": before,
            "Reason": "filter produced zero rows",
        }

    return filtered, {
        "Applied": True,
        "Terms": terms,
        "Before": before,
        "After": len(filtered),
        "Reason": "filtered by DK salary CSV Game Info",
    }


def render_slate_filter_report(salary_df, slate_filter_report):
    with st.expander("Slate Match Info"):
        st.write(
            f"Slate filter: {'ON' if slate_filter_report.get('Applied') else 'OFF'} "
            f"({slate_filter_report.get('Before')} → {slate_filter_report.get('After')} rows)"
        )
        st.caption(slate_filter_report.get("Reason", ""))

        terms = slate_filter_report.get("Terms", [])
        if terms:
            st.write("Detected slate teams:")
            st.write(", ".join(terms[:40]))

        games = salary_df_slate_games(salary_df)
        if games.empty:
            st.info("No DK Game Info found in salary CSV.")
        else:
            st.dataframe(games, use_container_width=True, hide_index=True)



# =========================================================
# DFS V90 CSV-ONLY LINEUP BUILDER
# =========================================================

def projection_from_salary_and_position(row, sport="MLB"):
    salary = float(row.get("DFS Salary", row.get("Salary", 0)) or 0)
    pos = str(row.get("DFS Position", row.get("Position", "UTIL"))).upper()

    if salary <= 0:
        salary = 3000

    if sport == "MLB":
        if pos == "P":
            base = 7.0 + (salary / 1000) * 1.15
        else:
            base = 4.0 + (salary / 1000) * 0.75
    elif sport in ["NBA", "WNBA"]:
        base = 8.0 + (salary / 1000) * 2.6
    elif sport == "NFL":
        base = 5.0 + (salary / 1000) * 1.8
    elif sport == "NHL":
        base = 3.0 + (salary / 1000) * 0.9
    else:
        base = 5.0 + (salary / 1000) * 1.0

    return round(base, 2)


def build_dfs_pool_from_salary_csv(salary_df, betting_df=None, platform="DraftKings", sport="MLB", style="Classic"):
    """
    CSV-first DFS pool.
    Every CSV row becomes a DFS player. Betting/AI props only enrich if names match.
    """
    if salary_df is None or salary_df.empty:
        return pd.DataFrame()

    sal = salary_df.copy()

    if "DFS Name" not in sal.columns or "DFS Salary" not in sal.columns:
        sal = normalize_dfs_salary_dataframe_v87(sal, platform=platform)

    if sal.empty:
        return pd.DataFrame()

    for col in ["DFS Name", "DFS Salary", "DFS Position", "DFS Team", "DFS Game Info"]:
        if col not in sal.columns:
            sal[col] = ""

    pool = pd.DataFrame()
    pool["Player"] = sal["DFS Name"].astype(str)
    pool["DFS Match Name"] = pool["Player"].apply(clean_prop_player_name)
    pool["Position"] = sal["DFS Position"].apply(normalize_dk_position)
    pool["Salary"] = pd.to_numeric(sal["DFS Salary"], errors="coerce").fillna(0).astype(int)
    pool["Salary Source"] = "Uploaded CSV"
    pool["League"] = sport
    pool["Matchup"] = sal["DFS Game Info"].astype(str)
    pool["Team"] = sal["DFS Team"].astype(str)
    pool["Market"] = "DFS Salary CSV"
    pool["Pick"] = pool["Player"]
    pool["Best Book"] = platform
    pool["Best MN App"] = platform
    pool["Best Odds"] = 0
    pool["Line"] = ""
    pool["Is Prop"] = True
    pool["Salary Match Score"] = 100
    pool["Matched DFS Name"] = pool["Player"]

    pool["DFS Projection"] = pool.apply(lambda r: projection_from_salary_and_position(r, sport), axis=1)
    pool["Floor"] = (pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0) * 0.55).round(2)
    pool["Ceiling"] = (pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0) * 1.55).round(2)
    pool["Leverage"] = (10000 / pool["Salary"].replace(0, 3000)).clip(0, 8).round(2)
    pool["DFS Confidence"] = 62.0
    pool["Edge %"] = 0.0
    pool["Model Probability %"] = 50.0
    pool["AI Confidence"] = 62.0
    pool["Priority Score"] = pool["DFS Projection"]

    board = ensure_schema(betting_df) if betting_df is not None else pd.DataFrame()
    if not board.empty:
        try:
            board = board[board["League"] == sport].copy()
            if "AI Confidence" not in board.columns:
                board = add_ai_columns(board)

            board["Clean Player"] = board["Player"].apply(clean_prop_player_name)
            board["Join Key"] = board["Clean Player"].apply(normalize_player_name_for_join)
            board["DFS Projection Num"] = pd.to_numeric(board.get("DFS Projection", 0), errors="coerce").fillna(0)
            board["AI Confidence Num"] = pd.to_numeric(board.get("AI Confidence", 0), errors="coerce").fillna(0)
            board["Edge Num"] = pd.to_numeric(board.get("Edge %", 0), errors="coerce").fillna(0)

            best = (
                board.sort_values(["AI Confidence Num", "Edge Num", "DFS Projection Num"], ascending=False)
                .drop_duplicates(subset=["Join Key"], keep="first")
            )

            enrich = {}
            for _, r in best.iterrows():
                key = normalize_player_name_for_join(r.get("Clean Player", ""))
                if key:
                    enrich[key] = r.to_dict()

            for idx, row in pool.iterrows():
                pkey = normalize_player_name_for_join(row.get("Player", ""))
                hit = enrich.get(pkey)

                if hit is None:
                    best_hit = None
                    best_score = 0
                    for _, v in best.iterrows():
                        sc = salary_match_score(row.get("Player", ""), v.get("Clean Player", ""))
                        if sc > best_score:
                            best_score = sc
                            best_hit = v.to_dict()
                    if best_score >= 88:
                        hit = best_hit

                if hit is not None:
                    if float(hit.get("DFS Projection", 0) or 0) > 0:
                        pool.at[idx, "DFS Projection"] = float(hit.get("DFS Projection", pool.at[idx, "DFS Projection"]))
                    pool.at[idx, "DFS Confidence"] = float(hit.get("DFS Confidence", pool.at[idx, "DFS Confidence"]) or pool.at[idx, "DFS Confidence"])
                    pool.at[idx, "AI Confidence"] = float(hit.get("AI Confidence", pool.at[idx, "AI Confidence"]) or pool.at[idx, "AI Confidence"])
                    pool.at[idx, "Edge %"] = float(hit.get("Edge %", 0) or 0)
                    pool.at[idx, "Model Probability %"] = float(hit.get("Model Probability %", 50) or 50)
                    pool.at[idx, "Market"] = hit.get("Market", pool.at[idx, "Market"])
                    pool.at[idx, "Pick"] = hit.get("Pick", pool.at[idx, "Pick"])
                    pool.at[idx, "Best Book"] = hit.get("Best Book", pool.at[idx, "Best Book"])
                    pool.at[idx, "Best MN App"] = hit.get("Best MN App", pool.at[idx, "Best MN App"])
                    pool.at[idx, "Best Odds"] = hit.get("Best Odds", pool.at[idx, "Best Odds"])
        except Exception:
            pass

    pool["DFS Projection"] = pd.to_numeric(pool["DFS Projection"], errors="coerce").fillna(0)
    pool["Floor"] = (pool["DFS Projection"] * 0.55).round(2)
    pool["Ceiling"] = (pool["DFS Projection"] * 1.55).round(2)
    pool["Base Score"] = (
        pool["DFS Projection"] * 1.0
        + pd.to_numeric(pool["DFS Confidence"], errors="coerce").fillna(50) * 0.05
        + pd.to_numeric(pool["Edge %"], errors="coerce").fillna(0) * 0.25
    )

    return pool.sort_values(["Base Score", "DFS Projection", "Salary"], ascending=False).reset_index(drop=True)


def salary_csv_summary(salary_df):
    if salary_df is None or salary_df.empty:
        return {"Rows": 0, "Positions": "", "Games": 0}

    s = salary_df.copy()
    pos = ""

    if "DFS Position" in s.columns:
        pos_counts = s["DFS Position"].apply(normalize_dk_position).value_counts().to_dict()
        pos = " · ".join([f"{k}: {v}" for k, v in pos_counts.items()])

    games = 0
    if "DFS Game Info" in s.columns:
        games = len([x for x in s["DFS Game Info"].dropna().astype(str).unique() if x.strip()])

    return {"Rows": len(s), "Positions": pos, "Games": games}


def render_csv_only_notice():
    st.info("CSV-only mode: lineups are built strictly from the uploaded salary CSV. Betting/AI data is only used as an optional projection boost when names match.")



# =========================================================
# DFS V91 CSV STYLE AUTO-DETECT + SHOWDOWN OPTIMIZER
# =========================================================

def csv_game_count(salary_df):
    if salary_df is None or salary_df.empty or "DFS Game Info" not in salary_df.columns:
        return 0
    return len([x for x in salary_df["DFS Game Info"].dropna().astype(str).unique() if x.strip()])


def auto_style_from_csv(platform, sport, selected_style, salary_df):
    games = csv_game_count(salary_df)

    # If the salary file is one game, it is usually DK Showdown or FD Single Game.
    if games == 1:
        if platform == "DraftKings" and (platform, sport, "Showdown Captain") in DFS_ROSTER_RULES:
            return "Showdown Captain"
        if platform == "FanDuel" and (platform, sport, "Single Game MVP") in DFS_ROSTER_RULES:
            return "Single Game MVP"

    return selected_style


def slot_adjusted_player(row, slot):
    """
    Applies captain/MVP rules in a simple usable way.
    DK CPT usually costs 1.5x and scores 1.5x.
    FD MVP usually scores boosted but salary is not multiplied.
    """
    r = dict(row)
    slot_u = str(slot).upper()

    if slot_u == "CPT":
        r["Salary"] = int(round(float(r.get("Salary", 0) or 0) * 1.5))
        r["DFS Projection"] = round(float(r.get("DFS Projection", 0) or 0) * 1.5, 2)
        r["Ceiling"] = round(float(r.get("Ceiling", 0) or 0) * 1.5, 2)
        r["Floor"] = round(float(r.get("Floor", 0) or 0) * 1.5, 2)
        r["Roster Slot"] = "CPT"
        return r

    if slot_u == "MVP":
        r["DFS Projection"] = round(float(r.get("DFS Projection", 0) or 0) * 2.0, 2)
        r["Ceiling"] = round(float(r.get("Ceiling", 0) or 0) * 2.0, 2)
        r["Floor"] = round(float(r.get("Floor", 0) or 0) * 2.0, 2)
        r["Roster Slot"] = "MVP"
        return r

    r["Roster Slot"] = slot
    return r


def optimize_roster_by_slots_csv_v91(pool, platform, sport, style, salary_cap, build_type="Cash", max_lineups=5):
    """
    CSV-only optimizer that:
    - Handles DK Showdown CPT salary multiplier
    - Does not require salary coverage
    - Uses uploaded CSV player pool directly
    """
    rules = dfs_get_rules(platform, sport, style)
    slots = list(rules["slots"])

    if pool is None or pool.empty:
        return []

    p = pool.copy()
    p["Build Score"] = p.apply(lambda r: score_player_for_build(r, build_type), axis=1)
    p["Value"] = p["Build Score"] / (pd.to_numeric(p["Salary"], errors="coerce").fillna(9999) / 1000)
    p = p.sort_values(["Build Score", "Value", "DFS Projection"], ascending=False)

    rows = p.to_dict("records")
    lineups = []

    # Restrictive slots first; captain first for showdown.
    def slot_rank(s):
        su = str(s).upper()
        if su in ["CPT", "MVP"]:
            return 0
        if su in ["P", "QB", "G", "DST", "DEF"]:
            return 1
        if su in ["UTIL", "FLEX"]:
            return 99
        return 2

    ordered_slots = sorted(slots, key=slot_rank)

    for start_idx in range(min(len(rows), max_lineups * 80)):
        used = set()
        salary = 0
        lineup_rows = []

        ordered_rows = rows[start_idx:] + rows[:start_idx]

        for slot in ordered_slots:
            best = None
            best_score = -999999

            for cand in ordered_rows:
                player = str(cand.get("Player", "")).strip()
                if not player or player in used:
                    continue

                if not eligible_for_slot_v82(cand.get("Position", "UTIL"), slot, cand.get("Salary Source", "Uploaded CSV")):
                    # For showdown utility/captain, every player is eligible.
                    if str(slot).upper() not in ["CPT", "MVP", "UTIL"]:
                        continue

                adj = slot_adjusted_player(cand, slot)
                cand_salary = int(adj.get("Salary", 0) or 0)

                if salary + cand_salary > int(salary_cap):
                    continue

                raw_score = float(adj.get("DFS Projection", 0) or 0)
                ceil_score = float(adj.get("Ceiling", 0) or 0)
                val_score = raw_score / max(cand_salary / 1000, 1)

                if str(build_type).lower() == "cash":
                    score = raw_score * 1.2 + val_score * 0.6
                elif str(build_type).lower() == "gpp":
                    score = ceil_score * 1.1 + val_score * 0.3
                else:
                    score = ceil_score * 0.8 + val_score * 0.8

                if score > best_score:
                    best = adj
                    best_score = score

            if best is None:
                break

            lineup_rows.append(best)
            used.add(str(best.get("Player", "")).strip())
            salary += int(best.get("Salary", 0) or 0)

        if len(lineup_rows) == len(slots):
            key = tuple(sorted([f"{x.get('Roster Slot')}:{x.get('Player')}" for x in lineup_rows]))
            if key in [l["Key"] for l in lineups]:
                continue

            lineups.append({
                "Key": key,
                "Build Type": build_type,
                "Platform": platform,
                "Sport": sport,
                "Style": style,
                "Salary Cap": int(salary_cap),
                "Salary Used": int(salary),
                "Salary Left": int(salary_cap) - int(salary),
                "Players": lineup_rows,
                "Projected": round(sum(float(x.get("DFS Projection", 0) or 0) for x in lineup_rows), 2),
                "Ceiling": round(sum(float(x.get("Ceiling", 0) or 0) for x in lineup_rows), 2),
                "Floor": round(sum(float(x.get("Floor", 0) or 0) for x in lineup_rows), 2),
                "Avg Confidence": round(sum(float(x.get("DFS Confidence", 50) or 50) for x in lineup_rows) / len(lineup_rows), 1),
            })

        if len(lineups) >= max_lineups:
            break

    return sorted(lineups, key=lambda x: (x["Projected"], x["Salary Used"]), reverse=True)[:max_lineups]



# =========================================================
# DFS V92 DRAFTKINGS LOBBY AUTO MODE
# =========================================================

def dk_lobby_link_for_sport(sport="MLB"):
    sport_code = dk_sport_code(sport)
    return f"https://www.draftkings.com/lobby#/{sport_code}"


def classify_dk_slate_from_salary_df(platform, sport, salary_df, selected_style="Classic"):
    games = csv_game_count(salary_df)
    if games == 1:
        if platform == "DraftKings" and (platform, sport, "Showdown Captain") in DFS_ROSTER_RULES:
            return "Showdown Captain"
        if platform == "FanDuel" and (platform, sport, "Single Game MVP") in DFS_ROSTER_RULES:
            return "Single Game MVP"
    return selected_style


def load_dk_lobby_slate_salaries(draft_group_id, sport="MLB"):
    """
    Loads the actual DK salary CSV from a draftGroupId.
    """
    if not draft_group_id:
        return pd.DataFrame(), "", "No DraftKings draft group selected."

    salary_url = dk_salary_url_for_draft_group(str(draft_group_id))
    salary_df, msg = load_dk_salary_by_draft_group_v87(str(draft_group_id), sport=sport)

    if not salary_df.empty:
        salary_df["Salary Source Label"] = "DraftKings Lobby CSV"
        return salary_df, salary_url, msg

    return pd.DataFrame(), salary_url, msg


def render_dk_slate_cards(slates, selected_id=None):
    """
    Compact slate preview table/cards for mobile.
    """
    if slates is None or slates.empty:
        st.warning("No DraftKings slates found for this sport right now.")
        return

    show = slates.copy()
    for col in ["Slate Name", "Games", "Start Time", "Draft Group ID"]:
        if col not in show.columns:
            show[col] = ""
    safe_dataframe(
        show[["Slate Name", "Games", "Start Time", "Draft Group ID"]].head(25),
        use_container_width=True,
        hide_index=True,
    )


def render_dk_links(draft_group_id, salary_url, sport="MLB"):
    lobby_url = dk_lobby_link_for_sport(sport)
    if draft_group_id:
        st.markdown(f"[Open DraftKings Lobby]({lobby_url})")
        st.markdown(f"[Open DraftKings salary CSV]({salary_url})")


def render_dfs_dk_auto_builder(df):
    st.header("DFS Builder")

    platform = "DraftKings"

    top1, top2 = st.columns(2)
    with top1:
        st.selectbox("Platform", ["DraftKings"], index=0, key="dfs_v92_platform_locked", disabled=True)
    with top2:
        sport = st.selectbox(
            "Sport",
            list(LEAGUES.keys()),
            index=list(LEAGUES.keys()).index(st.session_state.get("dfs_mobile_sport", "MLB")) if st.session_state.get("dfs_mobile_sport", "MLB") in list(LEAGUES.keys()) else 0,
            key="dfs_v92_sport",
        )

    st.session_state["dfs_mobile_sport"] = sport

    st.info("Auto mode: the DFS Builder searches DraftKings slates, pulls the salary CSV itself, then builds lineups from that slate.")

    dk_slates, dk_msg = discover_dk_slates_v86(sport)
    if dk_slates.empty:
        st.warning(dk_msg)
        st.markdown(f"[Open DraftKings Lobby]({dk_lobby_link_for_sport(sport)})")
        return

    dk_slates = dk_slates.copy()
    dk_slates["Games"] = pd.to_numeric(dk_slates["Games"], errors="coerce").fillna(0).astype(int)
    dk_slates = dk_slates.sort_values(["Games", "Start Time"], ascending=[False, True]).reset_index(drop=True)

    labels = dk_slates["Slate Label"].tolist()
    selected_label = st.selectbox(
        "DraftKings Slate",
        labels,
        index=0,
        key=f"dfs_v92_dk_slate_{sport}",
    )

    selected_row = dk_slates[dk_slates["Slate Label"].eq(selected_label)].iloc[0]
    draft_group_id = str(selected_row["Draft Group ID"])

    salary_df, salary_url, salary_msg = load_dk_lobby_slate_salaries(draft_group_id, sport=sport)

    with st.expander("DraftKings slate links"):
        st.write(f"Draft Group ID: {draft_group_id}")
        render_dk_links(draft_group_id, salary_url, sport=sport)
        render_dk_slate_cards(dk_slates, selected_id=draft_group_id)

    if salary_df.empty:
        st.error("DraftKings slate found, but the salary CSV could not be loaded automatically. DraftKings may be blocking the salary endpoint for this slate.")
        with st.expander("Advanced manual salary URL"):
            manual_url = st.text_input("Manual salary CSV URL", value=salary_url, key=f"dfs_v92_manual_url_{sport}_{draft_group_id}")
            if manual_url:
                manual_df, manual_msg = read_dfs_salary_url_cached_v87(manual_url, platform="DraftKings")
                if not manual_df.empty:
                    st.success(manual_msg)
                    salary_df = manual_df
                    salary_url = manual_url
                else:
                    st.warning(manual_msg)
        if salary_df.empty:
            return
    else:
        st.success(salary_msg)

    selected_style = classify_dk_slate_from_salary_df(platform, sport, salary_df, selected_style="Classic")
    rules = dfs_get_rules(platform, sport, selected_style)

    st.markdown(f"### {platform} {sport} {selected_style}")
    st.caption(rules.get("description", ""))
    st.write(f"**Roster:** {' · '.join(rules['slots'])}")

    c1, c2 = st.columns(2)
    with c1:
        salary_cap = st.number_input(
            "Salary Cap",
            min_value=10000,
            max_value=100000,
            value=int(rules.get("cap", 50000)),
            step=500,
            key=f"dfs_v92_cap_{sport}_{draft_group_id}_{selected_style}",
        )
    with c2:
        max_lineups = st.selectbox(
            "Lineups",
            [1, 3, 5, 10, 20],
            index=2,
            key=f"dfs_v92_count_{sport}_{draft_group_id}_{selected_style}",
        )

    pool = build_dfs_pool_from_salary_csv(
        salary_df,
        betting_df=df,
        platform=platform,
        sport=sport,
        style=selected_style,
    )

    csv_summary = salary_csv_summary(salary_df)

    c_pool1, c_pool2, c_pool3, c_pool4 = st.columns(4)
    c_pool1.metric("DK Players", csv_summary["Rows"])
    c_pool2.metric("Pool Used", len(pool) if pool is not None else 0)
    c_pool3.metric("Games", csv_summary["Games"])
    c_pool4.metric("Slots", len(rules["slots"]))

    if csv_summary["Positions"]:
        st.caption(f"Position coverage: {csv_summary['Positions']}")

    build = st.radio(
        "Build Type",
        ["Cash", "GPP", "Contrarian"],
        horizontal=True,
        key=f"dfs_v92_build_type_{sport}_{draft_group_id}_{selected_style}",
    )

    if pool is None or pool.empty:
        st.warning("No DFS pool could be built from this DraftKings salary CSV.")
        return

    lineups = optimize_roster_by_slots_csv_v91(
        pool,
        platform,
        sport,
        selected_style,
        salary_cap,
        build_type=build,
        max_lineups=max_lineups,
    )

    render_dfs_pro_lineups(lineups)

    with st.expander("Player Pool"):
        safe_dataframe(
            pool.sort_values(["Base Score", "DFS Projection", "Salary"], ascending=False),
            cols=[
                "Player", "Position", "Salary", "Team", "Matchup",
                "DFS Projection", "Ceiling", "Floor", "Leverage",
                "DFS Confidence", "Market", "Pick"
            ],
            use_container_width=True,
            hide_index=True,
        )



# =========================================================
# DFS V93 DRAFTKINGS-NATIVE HELPERS
# =========================================================

def dk_sport_code_v93(sport):
    mapping = {
        "MLB": "MLB",
        "NBA": "NBA",
        "WNBA": "WNBA",
        "NFL": "NFL",
        "NHL": "NHL",
        "UFC/MMA": "MMA",
        "MLS Soccer": "SOC",
        "Soccer": "SOC",
    }
    return mapping.get(str(sport), str(sport).upper())


def dk_lobby_url_v93(sport="MLB", draft_group_id=None):
    sport_code = dk_sport_code_v93(sport)
    if draft_group_id:
        return f"https://www.draftkings.com/lobby#/{sport_code}?draftGroupId={draft_group_id}"
    return f"https://www.draftkings.com/lobby#/{sport_code}"


def find_first_key(obj, names):
    if not isinstance(obj, dict):
        return None
    lower = {str(k).lower(): k for k in obj.keys()}
    for name in names:
        if str(name).lower() in lower:
            return obj.get(lower[str(name).lower()])
    return None


def normalize_dk_draftable_position(raw):
    txt = str(raw or "").upper().strip()
    if not txt or txt in ["NAN", "NONE"]:
        return "UTIL"
    txt = txt.replace("UTIL/BN", "UTIL").replace("BN", "UTIL")
    txt = txt.replace("SP", "P").replace("RP", "P")
    parts = [p.strip() for p in re.split(r"[/,|]", txt) if p.strip()]
    if "C" in parts and "1B" in parts:
        return "C/1B"
    priority = ["CPT", "MVP", "P", "C/1B", "C", "1B", "2B", "3B", "SS", "OF", "QB", "RB", "WR", "TE", "DST", "PG", "SG", "SF", "PF", "G", "F", "D", "UTIL"]
    for p in priority:
        if p in parts or p == txt:
            if p in ["C", "1B"]:
                return "C/1B"
            return p
    return parts[0] if parts else "UTIL"


def extract_dk_player_name(d):
    return (
        find_first_key(d, ["displayName", "displayNameShort", "name", "fullName", "playerName", "firstLastName", "draftableName"])
        or ""
    )


def extract_dk_salary(d):
    val = find_first_key(d, ["salary", "Salary", "draftStatSalary"])
    try:
        return int(float(val))
    except Exception:
        return 0


def extract_dk_position(d):
    pos = find_first_key(d, ["position", "rosterSlot", "rosterPosition", "positionName", "playerPosition"])
    if isinstance(pos, dict):
        pos = find_first_key(pos, ["name", "displayName", "position"])
    if isinstance(pos, list) and pos:
        pos = pos[0]
    return normalize_dk_draftable_position(pos)


def extract_dk_team(d):
    team = find_first_key(d, ["teamAbbreviation", "teamAbbrev", "team", "teamName"])
    if isinstance(team, dict):
        team = find_first_key(team, ["abbreviation", "name", "teamAbbrev"])
    return str(team or "")


def extract_dk_game_info(d):
    gi = find_first_key(d, ["gameInfo", "game", "competition", "eventDescription", "gameDescription"])
    if isinstance(gi, dict):
        away = find_first_key(gi, ["awayTeam", "awayTeamAbbreviation", "awayTeamName"])
        home = find_first_key(gi, ["homeTeam", "homeTeamAbbreviation", "homeTeamName"])
        start = find_first_key(gi, ["startTime", "startDate", "startDateTime"])
        if isinstance(away, dict):
            away = find_first_key(away, ["abbreviation", "name"])
        if isinstance(home, dict):
            home = find_first_key(home, ["abbreviation", "name"])
        if away and home:
            return f"{away}@{home} {start or ''}".strip()
    return str(gi or "")


def extract_dk_status(d):
    status = find_first_key(d, ["status", "playerStatus", "statusDisplay", "injuryStatus"])
    if isinstance(status, dict):
        status = find_first_key(status, ["status", "displayValue", "description"])
    return str(status or "")


def normalize_dk_draftables_payload(payload, platform="DraftKings", sport="MLB"):
    """
    Converts DraftKings draftables JSON into a salary/player pool dataframe.
    Searches nested JSON for dicts that contain name + salary.
    """
    candidates = []
    for item in flatten_json_items(payload):
        if not isinstance(item, dict):
            continue
        name = extract_dk_player_name(item)
        salary = extract_dk_salary(item)
        if name and salary > 0:
            candidates.append(item)

    rows = []
    seen = set()
    for d in candidates:
        name = extract_dk_player_name(d)
        salary = extract_dk_salary(d)
        pos = extract_dk_position(d)
        team = extract_dk_team(d)
        game_info = extract_dk_game_info(d)
        status = extract_dk_status(d)
        key = (normalize_player_name_for_join(name), salary, pos)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "DFS Name": name,
            "Join Name": normalize_player_name_for_join(name),
            "DFS Salary": salary,
            "DFS Position": pos,
            "DFS Team": team,
            "DFS Game Info": game_info,
            "DFS Status": status,
            "Platform": platform,
            "Salary Source Label": "DraftKings Draftables",
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=900, show_spinner=False)
def get_dk_json_cached(url):
    try:
        r = requests.get(
            url,
            timeout=(7, 25),
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.draftkings.com/",
                "Origin": "https://www.draftkings.com",
            },
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}"
        try:
            return r.json(), "OK"
        except Exception:
            return None, "Non-JSON response"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


@st.cache_data(ttl=900, show_spinner=False)
def load_dk_draftables_v93(draft_group_id, sport="MLB"):
    """
    Try multiple DraftKings draftables endpoint patterns.
    If JSON endpoints fail, fallback internally to CSV endpoint.
    """
    if not draft_group_id:
        return pd.DataFrame(), "", "No DraftKings draft group selected."

    dg = str(draft_group_id)
    endpoints = [
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg}/draftables",
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg}/draftables?format=json",
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg}/players",
        f"https://api.draftkings.com/lineups/v1/draftgroups/{dg}/draftables",
        f"https://www.draftkings.com/lineup/getavailableplayers?draftGroupId={dg}",
        f"https://www.draftkings.com/lineup/getavailableplayersjson?draftGroupId={dg}",
    ]

    errors = []
    for url in endpoints:
        payload, msg = get_dk_json_cached(url)
        if payload is None:
            errors.append(f"{url} -> {msg}")
            continue
        df = normalize_dk_draftables_payload(payload, platform="DraftKings", sport=sport)
        if not df.empty:
            return df, url, f"Loaded {len(df)} DraftKings draftables."

        errors.append(f"{url} -> JSON found but no draftable salary rows recognized")

    # Internal fallback: DK salary CSV endpoint.
    salary_url = dk_salary_url_for_draft_group(dg)
    csv_df, csv_msg = load_dk_salary_by_draft_group_v87(dg, sport=sport)
    if not csv_df.empty:
        csv_df["Salary Source Label"] = "DraftKings Salary CSV"
        return csv_df, salary_url, f"Draftables JSON unavailable. Loaded {len(csv_df)} rows from DK salary CSV fallback."

    return pd.DataFrame(), salary_url, "Could not load DraftKings draftables or salary CSV. DK may be blocking the endpoint for this slate."


def classify_dk_style_v93(platform, sport, salary_df):
    games = csv_game_count(salary_df)
    if games == 1:
        if (platform, sport, "Showdown Captain") in DFS_ROSTER_RULES:
            return "Showdown Captain"
    if (platform, sport, "Classic") in DFS_ROSTER_RULES:
        return "Classic"
    styles = dfs_available_styles(platform, sport)
    return styles[0] if styles else "Classic"


def slate_type_label_v93(row, salary_df=None):
    name = str(row.get("Slate Name", "DraftKings Slate"))
    games = row.get("Games", "")
    start = row.get("Start Time", "")
    dg = row.get("Draft Group ID", "")
    return f"{name} • {games} games • {start} • ID {dg}"


def render_dfs_dk_native_v93(df):
    st.header("DFS Builder")

    platform = "DraftKings"
    top1, top2 = st.columns(2)
    with top1:
        st.selectbox("Platform", ["DraftKings"], index=0, key="dfs_v93_platform", disabled=True)
    with top2:
        sport = st.selectbox(
            "Sport",
            list(LEAGUES.keys()),
            index=list(LEAGUES.keys()).index(st.session_state.get("dfs_v93_sport", "MLB")) if st.session_state.get("dfs_v93_sport", "MLB") in list(LEAGUES.keys()) else 0,
            key="dfs_v93_sport",
        )

    st.info("DraftKings-native mode: select a slate, the app pulls DK draftable players/salaries directly, then builds lineups. No CSV upload.")

    dk_slates, msg = discover_dk_slates_v86(sport)
    if dk_slates.empty:
        st.warning(msg)
        st.markdown(f"[Open DraftKings Lobby]({dk_lobby_url_v93(sport)})")
        return

    dk_slates = dk_slates.copy()
    dk_slates["Games"] = pd.to_numeric(dk_slates["Games"], errors="coerce").fillna(0).astype(int)
    dk_slates = dk_slates.sort_values(["Games", "Start Time"], ascending=[False, True]).reset_index(drop=True)
    dk_slates["V93 Label"] = dk_slates.apply(lambda r: slate_type_label_v93(r), axis=1)

    selected_label = st.selectbox(
        "DraftKings Slate",
        dk_slates["V93 Label"].tolist(),
        index=0,
        key=f"dfs_v93_slate_{sport}",
    )
    selected_row = dk_slates[dk_slates["V93 Label"].eq(selected_label)].iloc[0]
    draft_group_id = str(selected_row["Draft Group ID"])

    salary_df, source_url, source_msg = load_dk_draftables_v93(draft_group_id, sport=sport)

    with st.expander("DraftKings board links"):
        st.write(f"Draft Group ID: {draft_group_id}")
        st.markdown(f"[Open DraftKings Lobby]({dk_lobby_url_v93(sport, draft_group_id)})")
        if source_url:
            st.markdown(f"[Open DK data source]({source_url})")
        render_dk_slate_cards(dk_slates, selected_id=draft_group_id)

    if salary_df.empty:
        st.error(source_msg)
        st.caption("This means DraftKings is blocking or changing the public draftables feed for this slate.")
        return

    st.success(source_msg)

    style = classify_dk_style_v93(platform, sport, salary_df)
    rules = dfs_get_rules(platform, sport, style)

    st.markdown(f"### {platform} {sport} {style}")
    st.write(f"**Roster:** {' · '.join(rules['slots'])}")

    c1, c2 = st.columns(2)
    with c1:
        salary_cap = st.number_input(
            "Salary Cap",
            min_value=10000,
            max_value=100000,
            value=int(rules.get("cap", 50000)),
            step=500,
            key=f"dfs_v93_cap_{sport}_{draft_group_id}_{style}",
        )
    with c2:
        max_lineups = st.selectbox(
            "Lineups",
            [1, 3, 5, 10, 20],
            index=2,
            key=f"dfs_v93_count_{sport}_{draft_group_id}_{style}",
        )

    pool = build_dfs_pool_from_salary_csv(
        salary_df,
        betting_df=df,
        platform=platform,
        sport=sport,
        style=style,
    )

    csv_summary = salary_csv_summary(salary_df)
    c_pool1, c_pool2, c_pool3, c_pool4 = st.columns(4)
    c_pool1.metric("DK Players", csv_summary["Rows"])
    c_pool2.metric("Pool Used", len(pool))
    c_pool3.metric("Games", csv_summary["Games"])
    c_pool4.metric("Slots", len(rules["slots"]))

    if csv_summary["Positions"]:
        st.caption(f"Position coverage: {csv_summary['Positions']}")

    build = st.radio(
        "Build Type",
        ["Cash", "GPP", "Contrarian"],
        horizontal=True,
        key=f"dfs_v93_build_{sport}_{draft_group_id}_{style}",
    )

    lineups = optimize_roster_by_slots_csv_v91(
        pool,
        platform,
        sport,
        style,
        salary_cap,
        build_type=build,
        max_lineups=max_lineups,
    )

    render_dfs_pro_lineups(lineups)

    with st.expander("Player Pool"):
        safe_dataframe(
            pool.sort_values(["Base Score", "DFS Projection", "Salary"], ascending=False),
            cols=[
                "Player", "Position", "Salary", "Team", "Matchup",
                "DFS Projection", "Ceiling", "Floor", "Leverage",
                "DFS Confidence", "Market", "Pick"
            ],
            use_container_width=True,
            hide_index=True,
        )



# =========================================================
# DFS V94 SOURCE ROUTER + ENDPOINT DEBUG
# =========================================================

def get_with_debug(url, expect_json=True):
    info = {
        "URL": url,
        "Status": "",
        "Content Type": "",
        "Bytes": 0,
        "OK": False,
        "Reason": "",
    }

    try:
        r = requests.get(
            url,
            timeout=(8, 30),
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/125 Safari/537.36",
                "Accept": "application/json,text/csv,text/plain,*/*",
                "Referer": "https://www.draftkings.com/",
                "Origin": "https://www.draftkings.com",
                "Cache-Control": "no-cache",
            },
        )
        info["Status"] = r.status_code
        info["Content Type"] = r.headers.get("content-type", "")
        info["Bytes"] = len(r.content or b"")

        if r.status_code != 200:
            info["Reason"] = f"HTTP {r.status_code}"
            return None, info

        if expect_json:
            try:
                payload = r.json()
                info["OK"] = True
                info["Reason"] = "JSON loaded"
                return payload, info
            except Exception:
                info["Reason"] = "Non-JSON response"
                return None, info

        text = r.text or ""
        if "," in text and len(text) > 100:
            info["OK"] = True
            info["Reason"] = "CSV/text loaded"
            return text, info

        info["Reason"] = "Empty or non-CSV response"
        return None, info

    except Exception as e:
        info["Reason"] = f"{type(e).__name__}: {e}"
        return None, info


def normalize_any_salary_payload_v94(payload, platform="DraftKings", sport="MLB"):
    """
    Accepts JSON payload, CSV text, or list/dict and returns normalized salary dataframe.
    """
    if payload is None:
        return pd.DataFrame()

    if isinstance(payload, str):
        try:
            from io import StringIO
            raw = pd.read_csv(StringIO(payload))
            return normalize_dfs_salary_dataframe_v87(raw, platform=platform)
        except Exception:
            return pd.DataFrame()

    df = normalize_dk_draftables_payload(payload, platform=platform, sport=sport)
    if not df.empty:
        return df

    # Some APIs return a top-level players list with slightly different names.
    rows = []
    for item in flatten_json_items(payload):
        if not isinstance(item, dict):
            continue
        name = extract_dk_player_name(item)
        salary = extract_dk_salary(item)
        if name and salary:
            rows.append(item)

    if rows:
        return normalize_dk_draftables_payload({"draftables": rows}, platform=platform, sport=sport)

    return pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def load_custom_dfs_source_v94(draft_group_id, sport="MLB"):
    """
    Optional custom source owned by user.
    Set DK_DFS_SALARY_API_URL in Streamlit secrets/env:
      https://your-api.com/dk?sport={sport}&draft_group_id={draft_group_id}
    """
    template = os.environ.get("DK_DFS_SALARY_API_URL", "") or safe_get_secret("DK_DFS_SALARY_API_URL", "")
    if not template:
        return pd.DataFrame(), "", {"Reason": "No DK_DFS_SALARY_API_URL configured"}

    url = template.format(sport=sport, draft_group_id=draft_group_id)
    payload, info = get_with_debug(url, expect_json=not url.lower().endswith(".csv"))
    df = normalize_any_salary_payload_v94(payload, platform="DraftKings", sport=sport)
    if not df.empty:
        df["Salary Source Label"] = "Custom DFS Source"
    return df, url, info


@st.cache_data(ttl=900, show_spinner=False)
def load_dk_dfs_sources_v94(draft_group_id, sport="MLB"):
    """
    Central source router.
    Returns: df, source_url, message, debug_rows
    """
    dg = str(draft_group_id)
    debug_rows = []

    # 1) Public DraftKings draftables endpoints.
    json_urls = [
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg}/draftables",
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg}/draftables?format=json",
        f"https://www.draftkings.com/lineup/getavailableplayers?draftGroupId={dg}",
        f"https://www.draftkings.com/lineup/getavailableplayersjson?draftGroupId={dg}",
    ]

    for url in json_urls:
        payload, info = get_with_debug(url, expect_json=True)
        debug_rows.append(info)
        df = normalize_any_salary_payload_v94(payload, platform="DraftKings", sport=sport)
        if not df.empty:
            df["Salary Source Label"] = "DraftKings Public JSON"
            return df, url, f"Loaded {len(df)} DraftKings players from public JSON.", debug_rows

    # 2) Public salary CSV fallback.
    csv_urls = [
        f"https://www.draftkings.com/lineup/getavailableplayerscsv?draftGroupId={dg}",
        f"https://www.draftkings.com/lineup/getavailableplayerscsv?contestTypeId=0&draftGroupId={dg}",
    ]

    for url in csv_urls:
        text, info = get_with_debug(url, expect_json=False)
        debug_rows.append(info)
        df = normalize_any_salary_payload_v94(text, platform="DraftKings", sport=sport)
        if not df.empty:
            df["Salary Source Label"] = "DraftKings Public CSV"
            return df, url, f"Loaded {len(df)} DraftKings players from salary CSV.", debug_rows

    # 3) User-owned custom API source.
    custom_df, custom_url, custom_info = load_custom_dfs_source_v94(dg, sport)
    if custom_url:
        debug_rows.append(custom_info)
    if not custom_df.empty:
        return custom_df, custom_url, f"Loaded {len(custom_df)} players from custom DFS source.", debug_rows

    return pd.DataFrame(), "", "DraftKings slate was found, but player/salary endpoints are blocked or unavailable from this app session.", debug_rows


def render_dk_endpoint_debug_v94(debug_rows):
    with st.expander("DK endpoint debug"):
        if not debug_rows:
            st.info("No endpoints tested yet.")
            return
        dbg = pd.DataFrame(debug_rows)
        safe_dataframe(dbg, use_container_width=True, hide_index=True)
        st.caption("If the lobby works but draftables/CSV endpoints fail, DraftKings is blocking or changing the player/salary feed. Use a custom authorized source/API for full automation.")


def render_dk_blocked_next_steps_v94(sport, draft_group_id):
    st.error("DraftKings found the slate, but blocked or did not return the player salary feed.")
    st.markdown(
        """
**What this means:** the app can see the DK lobby, but DK is not allowing this Streamlit/Python session to read the salary/player feed.

**Best practical no-hand-entry path:** generate lineups in the app, download the DK Lineups CSV, then use DraftKings' bulk upload page. That avoids typing players one by one.

For fully automatic lineup generation, connect a legit salary feed source:
- Your own backend/proxy that can access DK salary data
- A paid DFS/salary data provider
- An external scraper service you control

Plug-in point: set `DK_DFS_SALARY_API_URL` and the app will use that automatically.
"""
    )
    st.markdown(f"[Open DraftKings Lobby]({dk_lobby_url_v93(sport, draft_group_id)})")


def render_dfs_dk_native_v94(df):
    st.header("DFS Builder")

    platform = "DraftKings"
    c1, c2 = st.columns(2)
    with c1:
        st.selectbox("Platform", ["DraftKings"], index=0, disabled=True, key="dfs_v94_platform")
    with c2:
        sport = st.selectbox(
            "Sport",
            list(LEAGUES.keys()),
            index=list(LEAGUES.keys()).index(st.session_state.get("dfs_v94_sport", "MLB")) if st.session_state.get("dfs_v94_sport", "MLB") in list(LEAGUES.keys()) else 0,
            key="dfs_v94_sport",
        )

    st.info("V94: DraftKings lobby scan + source router. No CSV upload. If DK blocks salary feeds, endpoint debug shows exactly where it failed.")

    dk_slates, msg = discover_dk_slates_v86(sport)
    if dk_slates.empty:
        st.warning(msg)
        st.markdown(f"[Open DraftKings Lobby]({dk_lobby_url_v93(sport)})")
        return

    dk_slates = dk_slates.copy()
    dk_slates["Games"] = pd.to_numeric(dk_slates["Games"], errors="coerce").fillna(0).astype(int)
    dk_slates = dk_slates.sort_values(["Games", "Start Time"], ascending=[False, True]).reset_index(drop=True)
    dk_slates["V94 Label"] = dk_slates.apply(lambda r: slate_type_label_v93(r), axis=1)

    selected_label = st.selectbox("DraftKings Slate", dk_slates["V94 Label"].tolist(), index=0, key=f"dfs_v94_slate_{sport}")
    selected_row = dk_slates[dk_slates["V94 Label"].eq(selected_label)].iloc[0]
    draft_group_id = str(selected_row["Draft Group ID"])

    salary_df, source_url, source_msg, debug_rows = load_dk_dfs_sources_v94(draft_group_id, sport=sport)

    with st.expander("DraftKings board links"):
        st.write(f"Draft Group ID: {draft_group_id}")
        st.markdown(f"[Open DraftKings Lobby]({dk_lobby_url_v93(sport, draft_group_id)})")
        if source_url:
            st.markdown(f"[Open data source]({source_url})")
        render_dk_slate_cards(dk_slates, selected_id=draft_group_id)

    render_dk_endpoint_debug_v94(debug_rows)

    if salary_df.empty:
        render_dk_blocked_next_steps_v94(sport, draft_group_id)
        return

    st.success(source_msg)

    style = classify_dk_style_v93(platform, sport, salary_df)
    rules = dfs_get_rules(platform, sport, style)

    st.markdown(f"### {platform} {sport} {style}")
    st.write(f"**Roster:** {' · '.join(rules['slots'])}")

    cap_col, cnt_col = st.columns(2)
    with cap_col:
        salary_cap = st.number_input(
            "Salary Cap",
            min_value=10000,
            max_value=100000,
            value=int(rules.get("cap", 50000)),
            step=500,
            key=f"dfs_v94_cap_{sport}_{draft_group_id}_{style}",
        )
    with cnt_col:
        max_lineups = st.selectbox(
            "Lineups",
            [1, 3, 5, 10, 20],
            index=2,
            key=f"dfs_v94_count_{sport}_{draft_group_id}_{style}",
        )

    pool = build_dfs_pool_from_salary_csv(salary_df, betting_df=df, platform=platform, sport=sport, style=style)
    csv_summary = salary_csv_summary(salary_df)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("DK Players", csv_summary["Rows"])
    m2.metric("Pool Used", len(pool))
    m3.metric("Games", csv_summary["Games"])
    m4.metric("Slots", len(rules["slots"]))

    if csv_summary["Positions"]:
        st.caption(f"Position coverage: {csv_summary['Positions']}")

    build = st.radio("Build Type", ["Cash", "GPP", "Contrarian"], horizontal=True, key=f"dfs_v94_build_{sport}_{draft_group_id}_{style}")

    lineups = optimize_roster_by_slots_csv_v91(
        pool,
        platform,
        sport,
        style,
        salary_cap,
        build_type=build,
        max_lineups=max_lineups,
    )

    render_dfs_pro_lineups(lineups)

    with st.expander("Player Pool"):
        safe_dataframe(
            pool.sort_values(["Base Score", "DFS Projection", "Salary"], ascending=False),
            cols=[
                "Player", "Position", "Salary", "Team", "Matchup",
                "DFS Projection", "Ceiling", "Floor", "Leverage",
                "DFS Confidence", "Market", "Pick"
            ],
            use_container_width=True,
            hide_index=True,
        )



# =========================================================
# V95 SAFE SECRETS HELPER
# =========================================================

def safe_get_secret(name, default=""):
    """
    Streamlit raises StreamlitSecretNotFoundError if no secrets.toml exists.
    This helper makes secrets optional.
    """
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default



# =========================================================
# DFS V96 DRAFTKINGS BULK UPLOAD EXPORT
# =========================================================

def dk_lineup_upload_url():
    return "https://www.draftkings.com/lineup"


def lineup_to_dk_upload_rows(lineups):
    """
    Create a simple DraftKings bulk-upload style CSV.
    DraftKings upload templates can vary by sport/style, so V96 outputs:
    - Lineup #
    - roster slot columns in order
    - optional metadata columns
    The player values use names as displayed in the optimizer.

    For best DK compatibility, use the same slate/style that DK's upload page expects.
    """
    if not lineups:
        return pd.DataFrame()

    rows = []
    for i, lu in enumerate(lineups, start=1):
        row = {
            "Lineup": i,
            "Build Type": lu.get("Build Type", ""),
            "Platform": lu.get("Platform", "DraftKings"),
            "Sport": lu.get("Sport", ""),
            "Style": lu.get("Style", ""),
            "Salary Used": lu.get("Salary Used", ""),
            "Salary Left": lu.get("Salary Left", ""),
            "Projected": lu.get("Projected", ""),
            "Ceiling": lu.get("Ceiling", ""),
        }

        players = lu.get("Players", [])
        slot_counts = {}

        for p in players:
            slot = str(p.get("Roster Slot", p.get("Position", "UTIL")) or "UTIL").upper()
            slot_counts[slot] = slot_counts.get(slot, 0) + 1
            col = slot if slot_counts[slot] == 1 else f"{slot}{slot_counts[slot]}"
            row[col] = p.get("Player", "")

        rows.append(row)

    return pd.DataFrame(rows)


def render_dk_bulk_upload_tools(lineups, key_prefix="dk_bulk"):
    if not lineups:
        return

    export_df = lineup_to_dk_upload_rows(lineups)
    if export_df.empty:
        return

    csv_bytes = export_df.to_csv(index=False).encode("utf-8")

    st.markdown("### DraftKings Bulk Upload")
    st.caption("Download this CSV, then upload it on DraftKings Lineups. This avoids hand-entering every player.")

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download DK Lineups CSV",
            data=csv_bytes,
            file_name="cd_betting_dk_lineups.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"{key_prefix}_download_csv",
        )
    with c2:
        st.link_button(
            "Open DraftKings Lineups",
            dk_lineup_upload_url(),
            use_container_width=True,
        )

    with st.expander("Export Preview"):
        safe_dataframe(export_df, use_container_width=True, hide_index=True)



# =========================================================
# DFS V97 SIMPLE CSV RUNNER
# =========================================================

def render_dfs_simple_csv_v97(df):
    st.header("DFS Builder")

    c1, c2 = st.columns(2)
    with c1:
        platform = st.selectbox(
            "Platform",
            ["DraftKings", "FanDuel"],
            index=0,
            key="dfs_v97_platform",
        )
    with c2:
        sport = st.selectbox(
            "Sport",
            list(LEAGUES.keys()),
            index=list(LEAGUES.keys()).index(st.session_state.get("dfs_v97_sport", "MLB")) if st.session_state.get("dfs_v97_sport", "MLB") in list(LEAGUES.keys()) else 0,
            key="dfs_v97_sport",
        )

    st.info("Upload the DraftKings/FanDuel salary CSV and run it. No slate selector, no DK endpoint scan, no salary matching gate.")

    uploaded_salary = st.file_uploader(
        "Upload salary CSV",
        type=["csv"],
        key=f"dfs_v97_salary_csv_{platform}_{sport}",
    )

    if uploaded_salary is None:
        st.warning("Upload a salary CSV to build lineups.")
        return

    salary_df = read_dfs_salary_file_v87(uploaded_salary, platform)

    if salary_df.empty:
        st.error("CSV uploaded, but I could not read player name, position, and salary columns.")
        return

    style_options = dfs_available_styles(platform, sport)
    default_style = "Classic" if "Classic" in style_options else (style_options[0] if style_options else "Classic")

    detected_style = auto_style_from_csv(platform, sport, default_style, salary_df)
    if detected_style not in style_options and style_options:
        detected_style = default_style

    st.success(f"Loaded {len(salary_df)} players from uploaded CSV.")

    style = st.selectbox(
        "DFS Style",
        style_options if style_options else [detected_style],
        index=(style_options.index(detected_style) if detected_style in style_options else 0),
        key=f"dfs_v97_style_{platform}_{sport}",
    )

    rules = dfs_get_rules(platform, sport, style)

    st.markdown(f"### {platform} {sport} {style}")
    st.caption(rules.get("description", ""))
    st.write(f"**Roster:** {' · '.join(rules['slots'])}")

    c3, c4 = st.columns(2)
    with c3:
        salary_cap = st.number_input(
            "Salary Cap",
            min_value=10000,
            max_value=100000,
            value=int(rules.get("cap", 50000)),
            step=500,
            key=f"dfs_v97_cap_{platform}_{sport}_{style}",
        )
    with c4:
        max_lineups = st.selectbox(
            "Lineups",
            [1, 3, 5, 10, 20],
            index=2,
            key=f"dfs_v97_count_{platform}_{sport}_{style}",
        )

    min_salary_pct = st.slider(
        "Minimum salary spend target",
        min_value=0.70,
        max_value=1.00,
        value=0.95,
        step=0.01,
        key=f"dfs_v102_min_spend_{platform}_{sport}_{style}",
    )

    pool = build_dfs_pool_from_salary_csv(
        salary_df,
        betting_df=df,
        platform=platform,
        sport=sport,
        style=style,
    )

    csv_summary = salary_csv_summary(salary_df)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("CSV Players", csv_summary["Rows"])
    m2.metric("Pool Used", len(pool))
    m3.metric("Games", csv_summary["Games"])
    m4.metric("Slots", len(rules["slots"]))

    if csv_summary["Positions"]:
        st.caption(f"Position coverage: {csv_summary['Positions']}")

    build = st.radio(
        "Build Type",
        ["Cash", "GPP", "Contrarian"],
        horizontal=True,
        key=f"dfs_v97_build_{platform}_{sport}_{style}",
    )

    if pool is None or pool.empty:
        st.warning("No usable DFS pool was created from this CSV.")
        return

    render_optimizer_debug_v102(pool, platform, sport, style, salary_cap)

    run_build = st.button(
        "Build Best Lineups",
        type="primary",
        use_container_width=True,
        key=f"dfs_v102_build_button_{platform}_{sport}_{style}_{build}",
    )

    if not run_build:
        st.info("Choose your settings, then click Build Best Lineups.")
        lineups = []
    else:
        with st.spinner("Building best lineups..."):
            lineups = optimize_best_lineups_v103(
                pool,
                platform,
                sport,
                style,
                salary_cap,
                build_type=build,
                max_lineups=max_lineups,
                min_salary_pct=min_salary_pct,
            )

        if not lineups:
            st.warning("No valid lineup fit. Open Optimizer Debug - troubleshooting only to see the exact reason.")
        else:
            render_best_outcome_summary_v102(lineups)
            render_lineup_quality_note_v102(lineups, salary_cap, min_salary_pct)
            render_dfs_pro_lineups(lineups)

    with st.expander("Player Pool"):
        safe_dataframe(
            pool.sort_values(["Base Score", "DFS Projection", "Salary"], ascending=False),
            cols=[
                "Player", "Position", "Salary", "Team", "Matchup",
                "DFS Projection", "Ceiling", "Floor", "Leverage",
                "DFS Confidence", "Market", "Pick"
            ],
            use_container_width=True,
            hide_index=True,
        )



# =========================================================
# DFS V98 OPTIMIZER DEBUG + RELAXED CSV OPTIMIZER
# =========================================================

def pos_tokens_v98(pos):
    txt = str(pos or "UTIL").upper().strip()
    if not txt:
        return {"UTIL"}
    parts = set([p.strip() for p in re.split(r"[/,|]", txt) if p.strip()])
    if txt == "C/1B" or ("C" in parts and "1B" in parts):
        parts.update(["C", "1B", "C/1B"])
    if not parts:
        parts.add(txt)
    return parts


def eligible_for_slot_v98(pos, slot):
    slot = str(slot or "UTIL").upper().strip()
    toks = pos_tokens_v98(pos)

    if slot in ["UTIL", "FLEX"]:
        # MLB UTIL can be any hitter, not pitcher.
        return "P" not in toks

    if slot == "C/1B":
        return bool(toks & {"C", "1B", "C/1B"})

    if slot == "P":
        return "P" in toks

    if slot == "OF":
        return "OF" in toks

    return slot in toks


def dfs_optimizer_diagnostics_v98(pool, platform, sport, style, salary_cap):
    rules = dfs_get_rules(platform, sport, style)
    slots = list(rules.get("slots", []))

    diag = {
        "Players entering optimizer": 0,
        "Salary Cap": salary_cap,
        "Slots": " · ".join(slots),
        "Position Counts": "",
        "Salary Min": 0,
        "Salary Median": 0,
        "Salary Max": 0,
        "Cheapest Slot Fill Estimate": 0,
        "Likely Fail Reason": "",
    }

    if pool is None or pool.empty:
        diag["Likely Fail Reason"] = "Player pool is empty."
        return diag, pd.DataFrame()

    p = pool.copy()
    p["Salary"] = pd.to_numeric(p.get("Salary", 0), errors="coerce").fillna(0).astype(int)
    p = p[p["Salary"] > 0].copy()

    diag["Players entering optimizer"] = len(p)

    if p.empty:
        diag["Likely Fail Reason"] = "All salaries are zero or missing."
        return diag, pd.DataFrame()

    pos_counts = p["Position"].astype(str).apply(normalize_dk_position).value_counts().to_dict()
    diag["Position Counts"] = " · ".join([f"{k}: {v}" for k, v in pos_counts.items()])
    diag["Salary Min"] = int(p["Salary"].min())
    diag["Salary Median"] = int(p["Salary"].median())
    diag["Salary Max"] = int(p["Salary"].max())

    used = set()
    cheapest_rows = []
    total = 0

    # Fill hardest slots first.
    ordered_slots = sorted(slots, key=lambda s: 99 if str(s).upper() in ["UTIL", "FLEX"] else 0)

    for slot in ordered_slots:
        elig = p[p.apply(lambda r: eligible_for_slot_v98(r.get("Position", "UTIL"), slot), axis=1)].copy()
        elig = elig[~elig["Player"].astype(str).isin(used)]
        if elig.empty:
            diag["Likely Fail Reason"] = f"No eligible players found for slot {slot}."
            return diag, pd.DataFrame(cheapest_rows)

        row = elig.sort_values("Salary", ascending=True).iloc[0]
        used.add(str(row["Player"]))
        total += int(row["Salary"])
        cheapest_rows.append({
            "Slot": slot,
            "Player": row.get("Player", ""),
            "Position": row.get("Position", ""),
            "Salary": int(row.get("Salary", 0)),
        })

    diag["Cheapest Slot Fill Estimate"] = int(total)

    if total > int(salary_cap):
        diag["Likely Fail Reason"] = f"Cheapest legal lineup costs ${total:,}, above the ${int(salary_cap):,} cap."
    else:
        diag["Likely Fail Reason"] = "A legal lineup appears possible. If no lineup built, old optimizer slot logic was rejecting valid combinations."

    return diag, pd.DataFrame(cheapest_rows)


def render_optimizer_debug_v102(pool, platform, sport, style, salary_cap):
    diag, cheapest = dfs_optimizer_diagnostics_v98(pool, platform, sport, style, salary_cap)

    with st.expander("Optimizer Debug", expanded=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("Players In", diag["Players entering optimizer"])
        c2.metric("Cheapest Legal", f"${int(diag['Cheapest Slot Fill Estimate']):,}")
        c3.metric("Cap", f"${int(salary_cap):,}")

        st.write(f"**Slots:** {diag['Slots']}")
        st.write(f"**Position counts:** {diag['Position Counts']}")
        st.write(
            f"**Salary range:** ${int(diag['Salary Min']):,} / "
            f"${int(diag['Salary Median']):,} median / ${int(diag['Salary Max']):,}"
        )
        st.write(f"**Likely fail reason:** {diag['Likely Fail Reason']}")

        if not cheapest.empty:
            st.markdown("##### Cheapest possible slot fill")
            safe_dataframe(cheapest, use_container_width=True, hide_index=True)

    return diag


def optimize_roster_by_slots_csv_v98(pool, platform, sport, style, salary_cap, build_type="Cash", max_lineups=5):
    """
    Relaxed optimizer for uploaded CSVs.
    It is intentionally simple and robust:
    - no salary coverage gate
    - correct C/1B and UTIL eligibility
    - fills hard slots first
    - produces multiple lineups by rotating starting candidates
    """
    rules = dfs_get_rules(platform, sport, style)
    slots = list(rules.get("slots", []))

    if pool is None or pool.empty or not slots:
        return []

    p = pool.copy()
    p["Salary"] = pd.to_numeric(p.get("Salary", 0), errors="coerce").fillna(0).astype(int)
    p = p[p["Salary"] > 0].copy()
    if p.empty:
        return []

    for col in ["DFS Projection", "Ceiling", "Floor", "DFS Confidence", "Leverage"]:
        if col not in p.columns:
            p[col] = 0
        p[col] = pd.to_numeric(p[col], errors="coerce").fillna(0)

    p["Build Score"] = p.apply(lambda r: score_player_for_build(r, build_type), axis=1)
    p["Value Score"] = p["Build Score"] / (p["Salary"].replace(0, 9999) / 1000)

    if str(build_type).lower() == "cash":
        p = p.sort_values(["Value Score", "DFS Projection", "Build Score"], ascending=False)
    elif str(build_type).lower() == "gpp":
        p = p.sort_values(["Ceiling", "Build Score", "Value Score"], ascending=False)
    else:
        p = p.sort_values(["Leverage", "Ceiling", "Value Score"], ascending=False)

    rows = p.to_dict("records")
    lineups = []
    seen_keys = set()

    def slot_hardness(slot):
        slot_u = str(slot).upper()
        if slot_u in ["UTIL", "FLEX"]:
            return 99
        return len([r for r in rows if eligible_for_slot_v98(r.get("Position", "UTIL"), slot)])

    ordered_slots = sorted(slots, key=slot_hardness)

    # Rotate pool to create different lineups.
    max_attempts = min(len(rows), max(250, max_lineups * 80))

    for start in range(max_attempts):
        rotated = rows[start:] + rows[:start]
        selected = []
        used_players = set()
        salary_used = 0

        for slot in ordered_slots:
            best = None
            best_rank = -10**18

            for cand in rotated:
                player = str(cand.get("Player", "")).strip()
                if not player or player in used_players:
                    continue

                if not eligible_for_slot_v98(cand.get("Position", "UTIL"), slot):
                    continue

                adj = slot_adjusted_player(cand, slot) if "slot_adjusted_player" in globals() else dict(cand)
                adj["Roster Slot"] = slot

                cand_salary = int(adj.get("Salary", 0) or 0)
                if salary_used + cand_salary > int(salary_cap):
                    continue

                # Prefer high value while also getting close to cap.
                proj = float(adj.get("DFS Projection", 0) or 0)
                ceil = float(adj.get("Ceiling", 0) or 0)
                build_score = float(cand.get("Build Score", 0) or 0)
                value = build_score / max(cand_salary / 1000, 1)

                if str(build_type).lower() == "cash":
                    rank = value * 2.0 + proj * 0.7
                elif str(build_type).lower() == "gpp":
                    rank = ceil * 1.2 + value * 0.5
                else:
                    rank = float(cand.get("Leverage", 0) or 0) * 2.0 + ceil * 0.8 + value * 0.4

                # Minor penalty for leaving too much salary when near final slots.
                rank -= max((salary_used + cand_salary) - int(salary_cap), 0) * 1000

                if rank > best_rank:
                    best_rank = rank
                    best = adj

            if best is None:
                break

            selected.append(best)
            used_players.add(str(best.get("Player", "")).strip())
            salary_used += int(best.get("Salary", 0) or 0)

        if len(selected) != len(slots):
            continue

        key = tuple(sorted([str(x.get("Player", "")) for x in selected]))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        lineups.append({
            "Key": key,
            "Build Type": build_type,
            "Platform": platform,
            "Sport": sport,
            "Style": style,
            "Salary Cap": int(salary_cap),
            "Salary Used": int(salary_used),
            "Salary Left": int(salary_cap) - int(salary_used),
            "Players": selected,
            "Projected": round(sum(float(x.get("DFS Projection", 0) or 0) for x in selected), 2),
            "Ceiling": round(sum(float(x.get("Ceiling", 0) or 0) for x in selected), 2),
            "Floor": round(sum(float(x.get("Floor", 0) or 0) for x in selected), 2),
            "Avg Confidence": round(sum(float(x.get("DFS Confidence", 50) or 50) for x in selected) / len(selected), 1),
        })

        if len(lineups) >= int(max_lineups):
            break

    return sorted(lineups, key=lambda x: (x["Projected"], -x["Salary Left"]), reverse=True)[:int(max_lineups)]



# =========================================================
# DFS V102 FAST BEST-LINEUP OPTIMIZER
# =========================================================

def render_optimizer_debug_v102(pool, platform, sport, style, salary_cap):
    diag, cheapest = dfs_optimizer_diagnostics_v98(pool, platform, sport, style, salary_cap)

    with st.expander("Optimizer Debug - troubleshooting only", expanded=False):
        c1, c2, c3 = st.columns(3)
        c1.metric("Players In", diag["Players entering optimizer"])
        c2.metric("Cheapest Legal", f"${int(diag['Cheapest Slot Fill Estimate']):,}")
        c3.metric("Cap", f"${int(salary_cap):,}")

        st.write(f"**Slots:** {diag['Slots']}")
        st.write(f"**Position counts:** {diag['Position Counts']}")
        st.write(
            f"**Salary range:** ${int(diag['Salary Min']):,} / "
            f"${int(diag['Salary Median']):,} median / ${int(diag['Salary Max']):,}"
        )
        st.write(f"**Fail check:** {diag['Likely Fail Reason']}")

        if not cheapest.empty:
            st.caption("Diagnostic only. This is NOT the recommended lineup.")
            safe_dataframe(cheapest, use_container_width=True, hide_index=True)

    return diag


def optimize_fast_best_lineups_v102(pool, platform, sport, style, salary_cap, build_type="Cash", max_lineups=5, min_salary_pct=0.95):
    """
    Fast optimizer for Streamlit:
    - Projection-first
    - Tries to spend at least min_salary_pct of cap
    - Capped attempts so app does not freeze
    """
    rules = dfs_get_rules(platform, sport, style)
    slots = list(rules.get("slots", []))

    if pool is None or pool.empty or not slots:
        return []

    p = pool.copy()
    p["Salary"] = pd.to_numeric(p.get("Salary", 0), errors="coerce").fillna(0).astype(int)
    p = p[p["Salary"] > 0].copy()
    if p.empty:
        return []

    for col in ["DFS Projection", "Ceiling", "Floor", "DFS Confidence", "Leverage"]:
        if col not in p.columns:
            p[col] = 0
        p[col] = pd.to_numeric(p[col], errors="coerce").fillna(0)

    p["Value"] = p["DFS Projection"] / (p["Salary"].replace(0, 9999) / 1000)

    if str(build_type).lower() == "cash":
        p["Rank"] = p["DFS Projection"] * 100 + p["DFS Confidence"] * 0.25 + p["Value"] * 0.5
    elif str(build_type).lower() == "gpp":
        p["Rank"] = p["DFS Projection"] * 70 + p["Ceiling"] * 35 + p["Leverage"] * 1.0
    else:
        p["Rank"] = p["DFS Projection"] * 65 + p["Ceiling"] * 25 + p["Leverage"] * 8

    # Keep top players per position group so optimizer is fast.
    keep_frames = []
    for slot in set(slots + ["UTIL"]):
        elig = p[p.apply(lambda r: eligible_for_slot_v98(r.get("Position", "UTIL"), slot), axis=1)].copy()
        if not elig.empty:
            keep_frames.append(elig.sort_values("Rank", ascending=False).head(80))
    if keep_frames:
        p = pd.concat(keep_frames, ignore_index=True).drop_duplicates(subset=["Player", "Salary", "Position"])

    rows = p.sort_values(["Rank", "DFS Projection", "Salary"], ascending=False).to_dict("records")
    min_spend = int(float(salary_cap) * float(min_salary_pct))

    def slot_hardness(slot):
        if str(slot).upper() in ["UTIL", "FLEX"]:
            return 99999
        return len([r for r in rows if eligible_for_slot_v98(r.get("Position", "UTIL"), slot)])

    ordered_slots = sorted(slots, key=slot_hardness)

    def build_one(offset):
        rotated = rows[offset:] + rows[:offset]
        selected = []
        used = set()
        salary_used = 0

        for slot in ordered_slots:
            best = None
            best_score = -10**18
            remaining_slots = ordered_slots[ordered_slots.index(slot)+1:]

            for cand in rotated:
                player = str(cand.get("Player", "")).strip()
                if not player or player in used:
                    continue
                if not eligible_for_slot_v98(cand.get("Position", "UTIL"), slot):
                    continue

                adj = slot_adjusted_player(cand, slot) if "slot_adjusted_player" in globals() else dict(cand)
                adj["Roster Slot"] = slot
                sal = int(adj.get("Salary", 0) or 0)

                if salary_used + sal > int(salary_cap):
                    continue

                # quick remaining-slot feasibility
                temp_used = used | {player}
                temp_salary = salary_used + sal
                min_remaining = 0
                feasible = True
                for rem in remaining_slots:
                    rem_elig = [
                        r for r in rows
                        if str(r.get("Player", "")).strip() not in temp_used
                        and eligible_for_slot_v98(r.get("Position", "UTIL"), rem)
                    ]
                    if not rem_elig:
                        feasible = False
                        break
                    min_remaining += min(int(r.get("Salary", 0) or 0) for r in rem_elig)
                if not feasible or temp_salary + min_remaining > int(salary_cap):
                    continue

                proj = float(adj.get("DFS Projection", 0) or 0)
                ceil = float(adj.get("Ceiling", 0) or 0)
                lev = float(adj.get("Leverage", 0) or 0)
                val = float(cand.get("Value", 0) or 0)

                if str(build_type).lower() == "cash":
                    score = proj * 1000 + val * 2
                elif str(build_type).lower() == "gpp":
                    score = proj * 700 + ceil * 350 + lev * 10
                else:
                    score = proj * 650 + ceil * 250 + lev * 100

                # spend-up pressure
                if temp_salary + min_remaining < min_spend:
                    score += sal * 0.6
                else:
                    score += sal * 0.05

                if score > best_score:
                    best_score = score
                    best = adj

            if best is None:
                return None

            selected.append(best)
            used.add(str(best.get("Player", "")).strip())
            salary_used += int(best.get("Salary", 0) or 0)

        return selected if len(selected) == len(slots) else None

    lineups = []
    seen = set()
    max_attempts = min(len(rows), 240)

    for offset in range(max_attempts):
        selected = build_one(offset)
        if not selected:
            continue

        salary_used = sum(int(x.get("Salary", 0) or 0) for x in selected)
        key = tuple(sorted([str(x.get("Player", "")) for x in selected]))
        if key in seen:
            continue
        seen.add(key)

        projected = sum(float(x.get("DFS Projection", 0) or 0) for x in selected)
        ceiling = sum(float(x.get("Ceiling", 0) or 0) for x in selected)
        floor = sum(float(x.get("Floor", 0) or 0) for x in selected)
        avg_conf = sum(float(x.get("DFS Confidence", 50) or 50) for x in selected) / len(selected)

        rank = projected * 10000 + ceiling * 100
        if salary_used < min_spend:
            rank -= (min_spend - salary_used) * 20
        else:
            rank += salary_used

        lineups.append({
            "Key": key,
            "Build Type": build_type,
            "Platform": platform,
            "Sport": sport,
            "Style": style,
            "Salary Cap": int(salary_cap),
            "Salary Used": int(salary_used),
            "Salary Left": int(salary_cap) - int(salary_used),
            "Players": selected,
            "Projected": round(projected, 2),
            "Ceiling": round(ceiling, 2),
            "Floor": round(floor, 2),
            "Avg Confidence": round(avg_conf, 1),
            "_Rank": rank,
        })

        if len(lineups) >= int(max_lineups) * 5:
            break

    good_spend = [x for x in lineups if int(x["Salary Used"]) >= min_spend]
    rank_pool = good_spend if good_spend else lineups

    return sorted(rank_pool, key=lambda x: (x["_Rank"], x["Projected"], x["Salary Used"]), reverse=True)[:int(max_lineups)]


def render_best_outcome_summary_v102(lineups):
    if not lineups:
        return
    best = lineups[0]
    st.markdown("### Best Possible Outcomes")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Best Projection", best.get("Projected", 0))
    c2.metric("Ceiling", best.get("Ceiling", 0))
    c3.metric("Salary Used", f"${int(best.get('Salary Used', 0)):,}")
    c4.metric("Salary Left", f"${int(best.get('Salary Left', 0)):,}")


def render_lineup_quality_note_v102(lineups, salary_cap, min_salary_pct):
    if not lineups:
        return
    min_spend = int(float(salary_cap) * float(min_salary_pct))
    low = [lu for lu in lineups if int(lu.get("Salary Used", 0)) < min_spend]
    if low:
        st.warning(f"{len(low)} lineup(s) are below your spend target of ${min_spend:,}.")
    else:
        st.success(f"Lineups meet your spend target of ${min_spend:,}.")



# =========================================================
# DFS V103 ROBUST BEST-LINEUP OPTIMIZER
# =========================================================

import random
import itertools


def player_key_v103(row):
    return str(row.get("Player", "")).strip().lower()


def build_lineup_from_order_v103(rows, slots, salary_cap):
    selected = []
    used = set()
    salary_used = 0

    # Hardest slots first, UTIL last.
    ordered_slots = sorted(
        list(slots),
        key=lambda s: 999 if str(s).upper() in ["UTIL", "FLEX"] else 0
    )

    for slot in ordered_slots:
        chosen = None

        for cand in rows:
            pk = player_key_v103(cand)
            if not pk or pk in used:
                continue

            if not eligible_for_slot_v98(cand.get("Position", "UTIL"), slot):
                continue

            adj = slot_adjusted_player(cand, slot) if "slot_adjusted_player" in globals() else dict(cand)
            adj["Roster Slot"] = slot

            sal = int(adj.get("Salary", 0) or 0)
            if sal <= 0:
                continue

            if salary_used + sal > int(salary_cap):
                continue

            chosen = adj
            break

        if chosen is None:
            return None

        selected.append(chosen)
        used.add(player_key_v103(chosen))
        salary_used += int(chosen.get("Salary", 0) or 0)

    return selected


def lineup_score_v103(lineup, salary_cap, min_spend, build_type):
    if not lineup:
        return -10**18

    salary_used = sum(int(x.get("Salary", 0) or 0) for x in lineup)
    if salary_used > int(salary_cap):
        return -10**18

    proj = sum(float(x.get("DFS Projection", 0) or 0) for x in lineup)
    ceil = sum(float(x.get("Ceiling", 0) or 0) for x in lineup)
    floor = sum(float(x.get("Floor", 0) or 0) for x in lineup)
    lev = sum(float(x.get("Leverage", 0) or 0) for x in lineup)

    bt = str(build_type).lower()

    if bt == "cash":
        score = proj * 10000 + floor * 250
    elif bt == "gpp":
        score = proj * 7000 + ceil * 3500 + lev * 100
    else:
        score = proj * 6500 + ceil * 2500 + lev * 700

    # Spend target is a preference, not a hard rejection.
    if salary_used < int(min_spend):
        score -= (int(min_spend) - salary_used) * 8
    else:
        score += salary_used * 3

    return score


def optimize_best_lineups_v103(
    pool,
    platform,
    sport,
    style,
    salary_cap,
    build_type="Cash",
    max_lineups=5,
    min_salary_pct=0.95,
):
    rules = dfs_get_rules(platform, sport, style)
    slots = list(rules.get("slots", []))

    if pool is None or pool.empty or not slots:
        return []

    p = pool.copy()
    p["Salary"] = pd.to_numeric(p.get("Salary", 0), errors="coerce").fillna(0).astype(int)
    p = p[p["Salary"] > 0].copy()

    if p.empty:
        return []

    for col in ["DFS Projection", "Ceiling", "Floor", "DFS Confidence", "Leverage"]:
        if col not in p.columns:
            p[col] = 0
        p[col] = pd.to_numeric(p[col], errors="coerce").fillna(0)

    p["Value"] = p["DFS Projection"] / (p["Salary"].replace(0, 9999) / 1000)

    bt = str(build_type).lower()
    if bt == "cash":
        p["Rank"] = p["DFS Projection"] * 1000 + p["Floor"] * 100 + p["DFS Confidence"] * 2 + p["Salary"] * 0.01
    elif bt == "gpp":
        p["Rank"] = p["DFS Projection"] * 800 + p["Ceiling"] * 500 + p["Leverage"] * 20 + p["Salary"] * 0.01
    else:
        p["Rank"] = p["DFS Projection"] * 700 + p["Ceiling"] * 300 + p["Leverage"] * 120 + p["Salary"] * 0.01

    # Build candidate pool per slot. Keep enough players so we can spend up.
    keep = []
    for slot in set(slots + ["UTIL"]):
        elig = p[p.apply(lambda r: eligible_for_slot_v98(r.get("Position", "UTIL"), slot), axis=1)].copy()
        if not elig.empty:
            keep.append(elig.sort_values(["Rank", "Salary"], ascending=False).head(160))

    if keep:
        p = pd.concat(keep, ignore_index=True).drop_duplicates(subset=["Player", "Salary", "Position"])

    base_rows = p.sort_values(["Rank", "DFS Projection", "Salary"], ascending=False).to_dict("records")
    salary_cap = int(salary_cap)
    min_spend = int(float(salary_cap) * float(min_salary_pct))

    lineups = []
    seen = set()

    def add_lineup(selected):
        if not selected or len(selected) != len(slots):
            return

        salary_used = sum(int(x.get("Salary", 0) or 0) for x in selected)
        if salary_used > salary_cap:
            return

        key = tuple(sorted([player_key_v103(x) for x in selected]))
        if key in seen:
            return

        seen.add(key)

        projected = sum(float(x.get("DFS Projection", 0) or 0) for x in selected)
        ceiling = sum(float(x.get("Ceiling", 0) or 0) for x in selected)
        floor = sum(float(x.get("Floor", 0) or 0) for x in selected)
        avg_conf = sum(float(x.get("DFS Confidence", 50) or 50) for x in selected) / len(selected)
        score = lineup_score_v103(selected, salary_cap, min_spend, build_type)

        lineups.append({
            "Key": key,
            "Build Type": build_type,
            "Platform": platform,
            "Sport": sport,
            "Style": style,
            "Salary Cap": salary_cap,
            "Salary Used": int(salary_used),
            "Salary Left": salary_cap - int(salary_used),
            "Players": selected,
            "Projected": round(projected, 2),
            "Ceiling": round(ceiling, 2),
            "Floor": round(floor, 2),
            "Avg Confidence": round(avg_conf, 1),
            "_Rank": score,
        })

    # 1) deterministic rotations of projection-ranked pool
    for offset in range(min(len(base_rows), 300)):
        rows = base_rows[offset:] + base_rows[:offset]
        add_lineup(build_lineup_from_order_v103(rows, slots, salary_cap))

    # 2) salary-heavy order to use cap
    salary_rows = sorted(base_rows, key=lambda r: (float(r.get("DFS Projection", 0)), int(r.get("Salary", 0))), reverse=True)
    for offset in range(min(len(salary_rows), 200)):
        rows = salary_rows[offset:] + salary_rows[:offset]
        add_lineup(build_lineup_from_order_v103(rows, slots, salary_cap))

    # 3) randomized weighted search
    rng = random.Random(103)
    weighted_rows = sorted(base_rows, key=lambda r: float(r.get("Rank", 0)), reverse=True)

    for _ in range(2500):
        rows = weighted_rows.copy()

        # Shuffle but preserve some bias toward top players by shuffling chunks.
        top = rows[:80]
        mid = rows[80:220]
        rest = rows[220:]

        rng.shuffle(top)
        rng.shuffle(mid)
        rng.shuffle(rest)

        # Different builds bias differently.
        if bt == "cash":
            order = sorted(top[:35] + mid[:80] + rest[:60], key=lambda r: (float(r.get("DFS Projection", 0)), int(r.get("Salary", 0))), reverse=True)
        elif bt == "gpp":
            order = sorted(top[:45] + mid[:100] + rest[:80], key=lambda r: (float(r.get("Ceiling", 0)), float(r.get("DFS Projection", 0))), reverse=True)
        else:
            order = sorted(top[:45] + mid[:120] + rest[:100], key=lambda r: (float(r.get("Leverage", 0)), float(r.get("Ceiling", 0))), reverse=True)

        # Randomly rotate the order so different slot fits happen.
        if order:
            cut = rng.randrange(0, len(order))
            order = order[cut:] + order[:cut]

        add_lineup(build_lineup_from_order_v103(order, slots, salary_cap))

        if len(lineups) >= max(60, int(max_lineups) * 12):
            break

    if not lineups:
        return []

    good_spend = [x for x in lineups if int(x["Salary Used"]) >= min_spend]
    rank_pool = good_spend if good_spend else lineups

    return sorted(
        rank_pool,
        key=lambda x: (float(x.get("_Rank", 0)), float(x.get("Projected", 0)), int(x.get("Salary Used", 0))),
        reverse=True
    )[:int(max_lineups)]


# =========================================================
# APP
# =========================================================

auto_load_once()
load_default_dashboard_sport()
header()

# Global search bar between Dashboard and Sportsbook nav/content
if "global_search" not in st.session_state:
    st.session_state["global_search"] = ""

global_search = st.text_input(
    "Search",
    value=st.session_state["global_search"],
    placeholder="🔍 Search player, team, matchup, market...",
    label_visibility="collapsed",
    key="top_global_search_input",
)
st.session_state["global_search"] = global_search


def apply_global_search(df):
    df = ensure_schema(df)
    q = str(st.session_state.get("global_search", "")).strip().lower()

    if not q:
        return df

    search_cols = [
        "League", "Matchup", "Market", "Player", "Pick", "Best Book",
        "Best MN App", "Game Time", "Live Score"
    ]

    mask = pd.Series(False, index=df.index)
    for col in search_cols:
        if col in df.columns:
            mask = mask | df[col].astype(str).str.lower().str.contains(q, na=False)

    return df[mask].copy()



tabs = st.tabs([
    "🏠 Dashboard",
    "📚 Sportsbook",
    "🤖 AI Predictions",
    "⚖️ Arbitrage",
    "🧾 Parlays",
    "🏗️ DFS Builder",
    "📍 Minnesota Apps",
    "⚙️ Settings",
])

st.caption(f"Last updated: {datetime.now(ZoneInfo('America/Chicago')).strftime('%b %d • %I:%M %p CT')}")


with tabs[0]:
    st.header("Dashboard")

    df = apply_global_search(ensure_schema(st.session_state["all_df"]))

    if df.empty:
        if not st.session_state.get("dashboard_retry_loaded", False):
            st.session_state["dashboard_retry_loaded"] = True
            with st.spinner("Loading main board..."):
                load_one_sport_to_state("MLB")
            st.rerun()

        st.warning("Main board did not load yet.")
        reports_df = st.session_state.get("reports", pd.DataFrame())
        if isinstance(reports_df, pd.DataFrame) and not reports_df.empty:
            with st.expander("Load report"):
                safe_dataframe(reports_df, use_container_width=True, hide_index=True)
        st.caption("Go to Settings → Force Scan All Sports if MLB returned no rows.")
    else:
        board = cached_clean_board_for_ui(df).head(MAX_DASHBOARD_ROWS)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Games", board["Matchup"].nunique())
        c2.metric("Markets", len(board))
        c3.metric("Best Edge", f"{pd.to_numeric(board['Edge %'], errors='coerce').fillna(0).max()}%")
        c4.metric("Sports", board["League"].nunique())

        st.subheader("Top 20 Edges")
        top = (
            board
            .drop_duplicates(subset=["Matchup", "Pick Key", "Market", "Line"], keep="first")
            .sort_values(["Priority Score", "High Rate Score", "Edge %"], ascending=False)
            .head(20)
        )

        dashboard_cols = [
            "League", "Game Time", "Matchup", "Market", "Player", "Bet Side",
            "Prop Line", "Pick", "Best Odds", "Best Book", "Best MN App",
            "Edge %", "Model Probability %", "Rating", "Units", "Books Compared"
        ]
        safe_dataframe(top, cols=dashboard_cols, use_container_width=True, hide_index=True)

        st.subheader("Top 5 AI Picks of the Day")
        ai = cached_ai_board(df)
        ai = (
            ai
            .drop_duplicates(subset=["Matchup", "Pick Key", "Market", "Line"], keep="first")
            .sort_values(["AI Confidence", "Priority Score", "Edge %"], ascending=False)
            .head(5)
        )
        render_top_ai_cards(ai, count=5)
        save_today_top5_ai_picks_v2(ai)


with tabs[1]:
    st.header("Sportsbook")

    if st.session_state["all_df"].empty:
        st.info("Dashboard is loading all sports. If nothing appears, use Refresh All Sports.")
    else:
        df = apply_global_search(ensure_schema(st.session_state["all_df"]))
        left, main = st.columns([1.05, 4.9])

        with left:
            selected_sport = st.radio(
                "Sport",
                list(LEAGUES.keys()),
                format_func=lambda x: f"{SPORT_EMOJI.get(x, '')} {x}",
                key="sportsbook_selected_sport",
            )
            render_sports_rail(df, selected_sport)

        with main:
            sport_df = df[df["League"] == selected_sport].copy()
            if sport_df.empty:
                load_one_sport_to_state(selected_sport)
                df = apply_global_search(ensure_schema(st.session_state["all_df"]))
                sport_df = df[df["League"] == selected_sport].copy()
            sport_df = trim_for_speed_safe(sport_df, MAX_SPORTBOOK_ROWS)
            st.subheader(f"{SPORT_EMOJI.get(selected_sport, '')} {selected_sport} Matchups")

            if sport_df.empty:
                st.warning("No matchups loaded for this sport.")
                if st.button(f"Load {selected_sport}", use_container_width=True, key=f"load_sportsbook_{selected_sport}"):
                    with st.spinner(f"Loading {selected_sport}..."):
                        load_one_sport_to_state(selected_sport)
                    st.rerun()
            else:
                matchup_scores = cached_matchup_scores(sport_df)

                matchup_list = matchup_scores["Matchup"].tolist()

                if "open_matchup" not in st.session_state or st.session_state["open_matchup"] not in matchup_list:
                    st.session_state["open_matchup"] = matchup_list[0]

                if "sportsbook_view" not in st.session_state:
                    st.session_state["sportsbook_view"] = "list"

                if st.session_state["sportsbook_view"] == "detail":
                    back_col, title_col = st.columns([1, 4])
                    with back_col:
                        if st.button("← Back", use_container_width=True):
                            st.session_state["sportsbook_view"] = "list"
                            st.rerun()

                    with title_col:
                        st.markdown("#### Matchup Detail")

                    render_matchup_detail(sport_df, st.session_state["open_matchup"])

                else:
                    st.markdown("#### Games")
                    st.caption("Click any matchup card to open the full betting board.")
                    for matchup in matchup_scores["Matchup"].head(50):
                        render_game_summary_card(sport_df, matchup, state_key="open_matchup")


with tabs[2]:
    st.header("AI Predictions")
    st.caption("Top 5 AI picks are tracked automatically once per day.")

    df = apply_global_search(ensure_schema(st.session_state["all_df"]))

    if df.empty:
        st.info("Load all sports from the Dashboard first.")
    else:
        props_only = st.checkbox("Only player props", value=False, key="ai_props_only")

        ai = cached_ai_board(df)

        if props_only:
            ai = ai[ai["Is Prop"] == True]

        ai = (
            ai.sort_values(["AI Confidence", "Edge %"], ascending=False)
            .drop_duplicates(subset=["Matchup", "Pick Key", "Market", "Line"], keep="first")
            .head(100)
        )

        st.subheader("Best AI Picks")
        render_top_ai_cards(ai.head(20), count=20)

        st.divider()
        save_today_top5_ai_picks_v2(ai)
        render_ai_tracker_v2()

        with st.expander("AI Picks Table"):
            safe_dataframe(
                ai,
                cols=[
                    "AI Grade", "AI Confidence", "League", "Game Time", "Matchup",
                    "Bucket", "Market", "Player", "Pick", "Best Odds", "Best Book",
                    "Best MN App", "Edge %", "Model Probability %",
                    "Books Compared", "Rating"
                ],
                use_container_width=True,
                hide_index=True,
            )


with tabs[3]:
    st.header("Arbitrage")

    df = apply_global_search(ensure_schema(st.session_state["all_df"]))
    if df.empty:
        st.info("Load all sports from the Dashboard first.")
    else:
        arbs = find_arbitrage(df)
        if arbs.empty:
            st.info("No clean two-sided arbitrage found in this scan.")
        else:
            st.metric("Arbs Found", len(arbs))
            arb_cols = [
                "Profit %", "League", "Matchup", "Market", "Line",
                "Side A", "Book A", "Side B", "Book B",
                "Best MN App", "Available MN Apps",
            ]
            safe_dataframe(arbs, cols=arb_cols, use_container_width=True, hide_index=True)


with tabs[4]:
    st.header("Parlays")

    df = apply_global_search(ensure_schema(st.session_state["all_df"]))
    if df.empty:
        st.info("Load all sports from the Dashboard first.")
    else:
        st.info(
            "Parlays now avoid far-future NFL clutter, show matchup context on every leg, "
            "prefer the best alternate line when edge improves, and show which Minnesota app to check."
        )

        legs = st.selectbox("Legs", [2, 3, 4], index=1)
        parlays = build_parlays(df, legs=legs)

        render_parlay_cards(parlays, legs)

        with st.expander("Show raw parlay table"):
            if parlays.empty:
                st.warning("No raw parlay rows.")
            else:
                safe_dataframe(parlays, use_container_width=True, hide_index=True)


with tabs[5]:
    df = ensure_schema(st.session_state["all_df"])
    render_dfs_simple_csv_v97(df)


with tabs[6]:
    st.header("Minnesota Betting App Guide")
    st.warning(
        "Minnesota does not currently have normal statewide online sportsbook apps. "
        "This app routes bets toward fantasy/pick'em/DFS-style apps to check first. "
        "Always confirm eligibility inside the app before depositing."
    )

    guide_rows = [
        {"Bet Type": "Player Props", "Best First Check": "Underdog", "Also Check": "PrizePicks, Sleeper, Chalkboard, DraftKings Pick6 / DFS, Dabble", "Example": "Olivia Miles Over 2.5 3PT Made"},
        {"Bet Type": "Pick'em / Multi-Leg Props", "Best First Check": "Underdog", "Also Check": "PrizePicks, Sleeper, Chalkboard, Dabble", "Example": "2-6 player prop entries"},
        {"Bet Type": "Team Pick / Winner", "Best First Check": "Underdog", "Also Check": "Sleeper, PrizePicks, Chalkboard", "Example": "Fever Moneyline-style pick"},
        {"Bet Type": "Spread / Total Style Picks", "Best First Check": "Underdog", "Also Check": "PrizePicks, Sleeper, Chalkboard", "Example": "Team +1.5 or Over 8.5"},
        {"Bet Type": "DFS Lineups", "Best First Check": "DraftKings Pick6 / DFS", "Also Check": "FanDuel DFS, Sleeper", "Example": "Salary-cap contests / fantasy entries"},
    ]

    st.dataframe(pd.DataFrame(guide_rows), use_container_width=True, hide_index=True)

    st.subheader("Links")
    for app, url in MN_APP_LINKS.items():
        st.link_button(app, url, use_container_width=True)



with tabs[7]:
    st.header("Settings")

    st.subheader("V86 DK Slate Discovery")
    st.write("DFS Builder now attempts to list DraftKings draft groups/slates and load the selected slate salary CSV instead of grabbing the first available feed.")


    st.subheader("DFS Auto Salary Loader")
    st.write("V85 attempts to auto-load DraftKings salary CSVs when public slate endpoints are available. If the site blocks the feed, upload the salary CSV as backup.")


    st.subheader("AI Tracker")
    if st.button("Clean AI Tracker Duplicates", use_container_width=True, key="settings_clean_ai_tracker_duplicates_1"):
        tracker = dedupe_ai_tracker(load_ai_tracker())
        save_ai_tracker(tracker)
        st.success("AI tracker duplicates cleaned.")

    if st.button("Clear AI Tracker History", use_container_width=True, key="settings_clear_ai_tracker_history_main"):
        empty_tracker = load_ai_tracker().head(0)
        save_ai_tracker(empty_tracker)
        st.success("AI tracker history cleared.")


    st.subheader("AI Tracker Maintenance")
    if st.button("Clean AI Tracker Duplicates", use_container_width=True, key="settings_clean_ai_tracker_duplicates_2"):
        tracker = load_ai_tracker()
        if not tracker.empty and "Pick ID" in tracker.columns:
            tracker = tracker.drop_duplicates(subset=["Pick ID"], keep="last")
            save_ai_tracker(tracker)
            st.success("AI tracker duplicates cleaned.")
        else:
            st.info("No tracker rows to clean.")


    if st.button("Reset Loaded Data", use_container_width=True, key="settings_reset_loaded_data_main"):
        st.session_state["all_df"] = pd.DataFrame()
        st.session_state["reports"] = pd.DataFrame()
        st.session_state["loaded_default_sport"] = False
        st.session_state["dashboard_retry_loaded"] = False
        st.success("Reset loaded data. Refresh the app.")


    st.subheader("Performance")
    st.write("The app now opens with a lightweight main board and loads heavy sports/pages only when needed.")

    if st.button("Force Scan All Sports", use_container_width=True, key="settings_force_scan_all_sports_main"):
        with st.spinner("Scanning all sports..."):
            df_all, reports = fetch_all_sports()
            st.session_state["all_df"] = ensure_schema(df_all)
            st.session_state["reports"] = reports
            st.success("All sports scanned.")

    st.write("Structure: Sport → Matchup → Betting Lines → AI Evidence / Arbitrage / Player History.")
    st.write("Parlays now show matchup context, book, MN app routing, and alternate lines with edge.")
    st.write("Sport-specific prop filters remove bad props like MLB player Points.")
    st.write("Dashboard rankings prioritize high-quality player props and remove walk/base-on-balls props.")
    st.write("V56 Speed Mode loads selected sports first instead of scanning every sport on startup.")
    st.write("DFS Builder V2 includes estimated salary, ownership, ceiling, floor, value, and leverage placeholders.")
    st.write("AI Confidence is capped from 0 to 100.")
    st.write("Markets are limited to common sportsbook lines and common player props.")
    st.write("Player history links are included, but exact all-time batter-vs-pitcher logs require a stats database/API.")
    st.warning("Research tool only. No pick is guaranteed. Bet responsibly.")
