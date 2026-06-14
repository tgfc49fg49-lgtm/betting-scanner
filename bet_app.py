
import itertools
import math
import re
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
        save_today_top5_ai_picks(ai)

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
    V57:
    Auto-load all sports again so Dashboard is clean.
    Stable schema stays on, but no visible load buttons on Dashboard.
    """
    ensure_loaded()

    if st.session_state["all_df"].empty and not st.session_state.get("auto_loading_done", False):
        with st.spinner("Loading today's board..."):
            df, reports = fetch_all_sports()
            st.session_state["all_df"] = ensure_schema(df)
            st.session_state["reports"] = reports
            st.session_state["auto_loading_done"] = True



def header():
    st.markdown(
        """
        <div class="hero">
            <div class="hero-title">CD BETTING</div>
            <div class="hero-sub">Sportsbook edge scanner • AI pick tracker • DFS Builder</div>
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
    return pool.sort_values(["DFS Value", "Leverage", "DFS Projection", "Edge %"], ascending=False)


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


def render_ai_tracker():
    st.subheader("Top 5 AI Pick Tracker")

    tracker = load_ai_tracker()

    if tracker.empty:
        st.info("No AI picks saved yet. Load the board and save today's Top 5 AI picks.")
        return

    summary = ai_tracker_summary(tracker)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Record", f"{summary['Wins']}-{summary['Losses']}-{summary['Pushes']}")
    c2.metric("Win %", summary["Win %"])
    c3.metric("Units", summary["Units"])
    c4.metric("ROI", summary["ROI"])
    c5.metric("Pending", summary["Pending"])

    with st.expander("Grade pending picks"):
        pending = tracker[tracker["Result"].astype(str).str.lower().eq("pending")].copy()

        if pending.empty:
            st.success("No pending picks to grade.")
        else:
            for idx, row in pending.iterrows():
                with st.container(border=True):
                    st.write(f"**{row.get('Pick', '')}**")
                    st.caption(f"{row.get('League', '')} • {row.get('Matchup', '')} • {row.get('Date', '')}")

                    c_res, c_save = st.columns([2, 1])
                    with c_res:
                        result = st.selectbox(
                            "Result",
                            ["Pending", "Win", "Loss", "Push"],
                            key=f"grade_result_{safe_key(row.get('Pick ID', idx))}",
                        )
                    with c_save:
                        if st.button("Save", key=f"grade_save_{safe_key(row.get('Pick ID', idx))}", use_container_width=True):
                            tracker.loc[tracker["Pick ID"] == row["Pick ID"], "Result"] = result
                            tracker.loc[tracker["Pick ID"] == row["Pick ID"], "Units Won"] = units_profit_from_result(
                                result,
                                row.get("Best Odds", 0),
                                row.get("Units Risked", 1.0),
                            )
                            tracker.loc[tracker["Pick ID"] == row["Pick ID"], "Graded At"] = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %I:%M %p CT")
                            save_ai_tracker(tracker)
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


# =========================================================
# APP
# =========================================================

auto_load_once()
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
    "🔍 Search",
    "⚙️ Settings",
])

st.caption(f"Last updated: {datetime.now(ZoneInfo('America/Chicago')).strftime('%b %d • %I:%M %p CT')}")


with tabs[0]:
    st.header("Dashboard")

    df = apply_global_search(ensure_schema(st.session_state["all_df"]))

    if df.empty:
        st.info("Loading today's betting board...")
        reports_df = st.session_state.get("reports", pd.DataFrame())
        if isinstance(reports_df, pd.DataFrame) and not reports_df.empty:
            with st.expander("Load report"):
                safe_dataframe(reports_df, use_container_width=True, hide_index=True)
    else:
        board = clean_user_facing_board(df, hide_low_interest=True)

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
        ai = add_ai_columns(board)
        ai = (
            ai
            .drop_duplicates(subset=["Matchup", "Pick Key", "Market", "Line"], keep="first")
            .sort_values(["AI Confidence", "Priority Score", "Edge %"], ascending=False)
            .head(5)
        )
        render_top_ai_cards(ai, count=5)


with tabs[1]:
    st.header("Sportsbook")

    if st.session_state["all_df"].empty:
        st.info("Dashboard is loading all sports. If nothing appears, use Refresh All Sports.")
    else:
        df = apply_global_search(st.session_state["all_df"])
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
            st.subheader(f"{SPORT_EMOJI.get(selected_sport, '')} {selected_sport} Matchups")

            if sport_df.empty:
                st.warning("No matchups loaded for this sport.")
                if st.button(f"Load {selected_sport}", use_container_width=True, key=f"load_sportsbook_{selected_sport}"):
                    with st.spinner(f"Loading {selected_sport}..."):
                        load_one_sport_to_state(selected_sport)
                    st.rerun()
            else:
                matchup_scores = (
                    sport_df.groupby("Matchup")
                    .agg(
                        BestEdge=("Edge %", "max"),
                        BestScore=("High Rate Score", "max"),
                        Markets=("Pick", "count"),
                        Props=("Is Prop", "sum"),
                        GameScore=("Game Score", "first"),
                    )
                    .reset_index()
                    .sort_values(["BestScore", "BestEdge"], ascending=False)
                )

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
    st.caption("Top 5 AI pick tracking is available after picks load.")

    df = apply_global_search(st.session_state["all_df"])

    if df.empty:
        st.info("Load all sports from the Dashboard first.")
    else:
        props_only = st.checkbox("Only player props", value=False, key="ai_props_only")

        ai = add_ai_columns(clean_user_facing_board(df, hide_low_interest=True))

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

        c_save_ai, c_info_ai = st.columns([1, 3])
        with c_save_ai:
            if st.button("Save Today's Top 5", use_container_width=True):
                save_today_top5_ai_picks(ai)
                st.success("Saved today's Top 5 AI picks.")
        with c_info_ai:
            st.caption("Grade results later to track win/loss rate, units, and ROI.")

        render_ai_tracker()

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

    df = apply_global_search(st.session_state["all_df"])
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

    df = apply_global_search(st.session_state["all_df"])
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
    st.header("DFS Builder")

    df = apply_global_search(ensure_schema(st.session_state["all_df"]))
    if df.empty:
        st.info("Loading today's DFS player pool...")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            platform = st.selectbox("Platform", ["DraftKings", "FanDuel"], index=0, key="dfs_platform")
        with c2:
            league_choice = st.selectbox("Sport", ["All"] + list(LEAGUES.keys()), index=0, key="dfs_league")
        with c3:
            lineup_size = st.selectbox("Lineup size", [4, 5, 6, 7, 8, 9], index=2, key="dfs_size")
        with c4:
            default_budget = dfs_default_budget(platform)
            budget = st.number_input(
                "Budget / Salary Cap",
                min_value=10000,
                max_value=100000,
                value=default_budget,
                step=500,
                key=f"dfs_budget_{platform}",
            )

        max_lineups = st.selectbox("Lineups to build", [3, 5, 8, 10, 15], index=2, key="dfs_count")

        pool = build_dfs_pool(df, league_choice)
        pool = ensure_schema(pool)

        if not pool.empty:
            pool["Platform"] = platform
            pool["Salary"] = pool.apply(lambda r: dfs_platform_salary(r, platform), axis=1)
            pool["Position"] = pool.apply(lambda r: dfs_platform_positions(r, platform), axis=1)
            pool["Value Per $1K"] = (
                pd.to_numeric(pool["DFS Value"], errors="coerce").fillna(0)
                / (pd.to_numeric(pool["Salary"], errors="coerce").fillna(9999) / 1000)
            ).round(3)

        st.metric("Player Pool", 0 if pool.empty else len(pool))

        st.subheader("Best AI Lineups")
        lineups = optimize_dfs_lineups(
            df,
            platform=platform,
            budget=budget,
            league_filter=league_choice,
            lineup_size=lineup_size,
            max_lineups=max_lineups,
        )
        render_budget_dfs_lineups(lineups)

        with st.expander("View player pool"):
            if pool.empty:
                st.warning("No DFS players available from current board.")
            else:
                safe_dataframe(
                    pool,
                    cols=[
                        "Position", "Player", "League", "Matchup", "Market", "Line", "Pick",
                        "Salary", "DFS Projection", "DFS Value", "Value Per $1K",
                        "Ceiling", "Floor", "Leverage", "DFS Confidence",
                        "Edge %", "Model Probability %", "Best MN App", "Best Book"
                    ],
                    use_container_width=True,
                    hide_index=True,
                )


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
    st.header("Search")

    df = apply_global_search(st.session_state["all_df"])
    if df.empty:
        st.info("Load all sports from the Dashboard first.")
    else:
        query = st.text_input("Search player, team, matchup, market...", placeholder="Buxton, Twins, Total Bases...")
        if query:
            q = query.lower()
            mask = (
                df["Matchup"].astype(str).str.lower().str.contains(q, na=False)
                | df["Player"].astype(str).str.lower().str.contains(q, na=False)
                | df["Pick"].astype(str).str.lower().str.contains(q, na=False)
                | df["Market"].astype(str).str.lower().str.contains(q, na=False)
                | df["League"].astype(str).str.lower().str.contains(q, na=False)
            )
            results = df[mask].sort_values(["High Rate Score", "Edge %"], ascending=False)
            st.metric("Results", len(results))
            st.dataframe(view_cols(results.head(200)), use_container_width=True, hide_index=True)
        else:
            st.info("Type a search term.")


with tabs[8]:
    st.header("Settings")
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
