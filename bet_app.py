
import itertools
import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

import pandas as pd
import requests
import streamlit as st

# =========================================================
# CD BETTING V43 — CLEAN SPORTSBOOK BUILD
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
    "MLS Soccer": "MLS",
}

SPORT_EMOJI = {
    "MLB": "⚾",
    "WNBA": "🏀",
    "NBA": "🏀",
    "NFL": "🏈",
    "NHL": "🏒",
    "UFC/MMA": "🥊",
    "MLS Soccer": "⚽",
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
# STYLE
# =========================================================

st.set_page_config(page_title="CD Betting V43", page_icon="🏆", layout="wide")

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


def parse_game_date(game_time_text):
    """
    Parses app display dates like 'Jun 14 • 12:40 PM CT'.
    Uses current year. Good enough for filtering far-future futures.
    """
    if not game_time_text:
        return None
    try:
        clean = str(game_time_text).replace("•", "").replace("CT", "").strip()
        # Example: Jun 14 12:40 PM
        dt = datetime.strptime(clean, "%b %d %I:%M %p")
        return dt.replace(year=datetime.now(ZoneInfo("America/Chicago")).year)
    except Exception:
        return None


def is_far_future_nfl(row, days=45):
    if str(row.get("League", "")) != "NFL":
        return False
    dt = parse_game_date(row.get("Game Time", ""))
    if dt is None:
        return False
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


def is_common_market(market_raw, stat, is_prop):
    raw = str(market_raw).lower()
    stat_s = str(stat)

    if any(bad in raw for bad in BAD_MARKET_PHRASES):
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

    if not is_common_market(market_raw, stat, is_prop):
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
        "Market": clean_market,
        "Bucket": "",
        "Player": player,
        "Bet Side": side_clean,
        "Prop Line": line,
        "Pick": pick,
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
    if df.empty:
        return df

    work = df[df.apply(is_realistic_bet_row, axis=1)].copy()

    # Hide far-future NFL from user-facing AI/parlays/arbs.
    # It can still exist in the raw API, but it should not dominate June boards.
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
    return clean_board(board)


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
    headers = {
        "Accept": "application/json",
        "x-api-key": SGO_API_KEY,
        "Authorization": f"Bearer {SGO_API_KEY}",
    }

    rows = []
    events_seen = 0
    cursor = None
    statuses = []
    last_url = ""

    page_size = 5
    max_pages = 60

    for _ in range(max_pages):
        params = {
            "apiKey": SGO_API_KEY,
            "leagueID": LEAGUES[league],
            "oddsAvailable": "true",
            "limit": page_size,
        }

        if cursor:
            params["cursor"] = cursor

        r = requests.get(SGO_EVENTS_URL, params=params, headers=headers, timeout=(2, 10))
        last_url = r.url
        statuses.append(r.status_code)
        payload = safe_json(r)

        if r.status_code != 200:
            return rows, {
                "ok": False,
                "status": r.status_code,
                "text": r.text[:1500],
                "json": payload,
                "url": r.url,
                "events_seen": events_seen,
            }

        events = extract_events(payload)
        events_seen += len(events)

        for event in events:
            for odd in get_odds_rows(event):
                row = normalize_odd(league, event, odd)
                if row:
                    rows.append(row)

        cursor = None
        if isinstance(payload, dict):
            cursor = payload.get("nextCursor") or payload.get("cursor")
            data = payload.get("data")
            if not cursor and isinstance(data, dict):
                cursor = data.get("nextCursor") or data.get("cursor")

        if not cursor:
            break

    return rows, {
        "ok": True,
        "status": statuses[-1] if statuses else "NO_REQUEST",
        "text": f"events_seen={events_seen}, rows={len(rows)}, pages={len(statuses)}",
        "json": None,
        "url": last_url,
        "events_seen": events_seen,
        "pages": len(statuses),
    }


def fetch_league(league):
    try:
        rows, report = fetch_league_cached(league)
        return score_board(rows), report
    except Exception as e:
        return pd.DataFrame(), {"ok": False, "status": "ERROR", "text": str(e), "json": None, "url": SGO_EVENTS_URL}


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
            "Rows": 0 if df.empty else len(df),
            "Games": 0 if df.empty else df["Matchup"].nunique(),
        })
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame(), pd.DataFrame(reports)

    full = pd.concat(frames, ignore_index=True)
    full = full.sort_values(["High Rate Score", "Edge %"], ascending=False)
    return full, pd.DataFrame(reports)


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
    edge = float(row.get("Edge %", 0))
    model = float(row.get("Model Probability %", 0))
    books = int(row.get("Books Compared", 0))

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

    if row.get("Best MN App"):
        reasons.append(f"best Minnesota app route: {row.get('Best MN App')}")

    if not reasons:
        reasons.append("best clean price on the current board")

    return "; ".join(reasons).capitalize() + "."


def alt_group_key(row):
    """
    Groups similar alternate lines together.
    Example:
    Aaron Judge Over 0.5 Total Bases
    Aaron Judge Over 1.5 Total Bases
    Aaron Judge Over 2.5 Total Bases
    """
    player = str(row.get("Player", "")).strip()
    matchup = str(row.get("Matchup", "")).strip()
    market = str(row.get("Market", "")).strip()
    side = str(row.get("Side", "")).strip()

    if player:
        return f"{matchup}|{player}|{market}|{side}"

    # For game lines keep team/side identity, but not the line number.
    pick_key = str(row.get("Pick Key", "")).split("|")[0]
    pick_key = re.sub(r"[-+]?\\d+(\\.\\d+)?", "", pick_key).strip()
    return f"{matchup}|{market}|{side}|{pick_key}"


def pick_best_alt_lines(df):
    """
    If alternate lines exist, keep the best edge/highest score version
    and store the alternatives for display.
    """
    if df.empty:
        return df

    work = choose_display_rows(clean_board(df.copy()))
    if work.empty:
        return work

    work["Alt Group"] = work.apply(alt_group_key, axis=1)
    output = []

    for _, group in work.groupby("Alt Group"):
        best = group.sort_values(["Edge %", "High Rate Score"], ascending=False).iloc[0].copy()
        alternates = group.sort_values(["Edge %", "High Rate Score"], ascending=False).head(4)

        alt_lines = []
        for _, alt in alternates.iterrows():
            if alt["Pick"] != best["Pick"]:
                alt_lines.append(f"{alt['Pick']} | Edge {alt['Edge %']}% | {format_odds(alt['Best Odds'])}")

        best["Alternative Lines"] = " || ".join(alt_lines)
        output.append(best)

    return pd.DataFrame(output).sort_values(["High Rate Score", "Edge %"], ascending=False)


def parlay_leg_label(row):
    return (
        f"{row['League']} — {row['Matchup']}\\n"
        f"{row['Pick']}\\n"
        f"Book: {format_book_name(row['Best Book'])} | MN App: {row.get('Best MN App', '')} | "
        f"Edge: {row['Edge %']}% | Odds: {format_odds(row['Best Odds'])}"
    )


def build_parlays(df, legs=3):
    if df.empty:
        return pd.DataFrame()

    work = pick_best_alt_lines(df)
    if work.empty:
        return pd.DataFrame()

    # Only use actual playable ratings and avoid same matchup duplication.
    work = work[
        (work["Rating"] != "PASS")
        & (pd.to_numeric(work["Edge %"], errors="coerce").fillna(0) >= 2.0)
        & (pd.to_numeric(work["Books Compared"], errors="coerce").fillna(0) >= 2)
    ].head(80)

    parlays = []

    for combo in itertools.combinations(work.to_dict("records"), legs):
        if len(set(x["Matchup"] for x in combo)) < len(combo):
            continue

        # Avoid using the same player twice.
        players = [str(x.get("Player", "")) for x in combo if str(x.get("Player", ""))]
        if len(players) != len(set(players)):
            continue

        dec_total = 1
        hit = 1
        edge = 0

        for leg in combo:
            dec_total *= american_to_decimal(leg["Best Odds"])
            # Slightly conservative hit estimate.
            hit *= max(0.05, min(0.88, float(leg["Model Probability %"]) / 100))
            edge += float(leg["Edge %"])

        row = {
            "Legs": legs,
            "Combined Odds": decimal_to_american(dec_total),
            "Estimated Hit %": round(hit * 100, 2),
            "Total Edge": round(edge, 2),
            "Avg Edge": round(edge / legs, 2),
        }

        for i, leg in enumerate(combo, 1):
            row[f"Leg {i}"] = parlay_leg_label(leg)
            row[f"Leg {i} Pick"] = leg["Pick"]
            row[f"Leg {i} Matchup"] = leg["Matchup"]
            row[f"Leg {i} Book"] = leg["Best Book"]
            row[f"Leg {i} MN App"] = leg.get("Best MN App", "")
            row[f"Leg {i} Edge"] = leg["Edge %"]
            row[f"Leg {i} Alternates"] = leg.get("Alternative Lines", "")

        parlays.append(row)

    if not parlays:
        return pd.DataFrame()

    return pd.DataFrame(parlays).sort_values(["Estimated Hit %", "Avg Edge", "Total Edge"], ascending=False)


def find_arbitrage(df):
    if df.empty:
        return pd.DataFrame()

    work = clean_board(df.copy())
    if work.empty:
        return pd.DataFrame()

    work["SideNorm"] = work["Side"].astype(str).str.lower().str.strip()
    work["MarketKey"] = work["Matchup"].astype(str) + "|" + work["Market"].astype(str) + "|" + work["Line"].astype(str)
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

            inv = (1 / american_to_decimal(best_a["Best Odds"])) + (1 / american_to_decimal(best_b["Best Odds"]))

            if inv < 1:
                profit_pct = round((1 - inv) * 100, 2)
                if profit_pct > 20:
                    continue

                bucket = str(best_a.get("Bucket", "Other"))
                mn_best, mn_apps = recommend_mn_apps(
                    bucket,
                    f"{best_a['Pick']} / {best_b['Pick']}",
                    best_a.get("Market", ""),
                    bool(best_a.get("Is Prop", False) or best_b.get("Is Prop", False)),
                )

                arbs.append({
                    "Profit %": profit_pct,
                    "League": best_a["League"],
                    "Matchup": best_a["Matchup"],
                    "Market": best_a["Market"],
                    "Line": best_a["Line"],
                    "Side A": best_a["Pick"],
                    "Book A": best_a["Best Book"],
                    "Side B": best_b["Pick"],
                    "Book B": best_b["Best Book"],
                    "Best MN App": mn_best,
                    "Available MN Apps": mn_apps,
                })

    if not arbs:
        return pd.DataFrame()

    return pd.DataFrame(arbs).sort_values("Profit %", ascending=False)


def player_history_links(row):
    player = str(row.get("Player", "")).strip()
    matchup = str(row.get("Matchup", "")).strip()
    market = str(row.get("Market", "")).strip()

    if not player:
        return {}

    return {
        "Game Logs vs Opponent": f"https://www.google.com/search?q={quote_plus(player + ' game log vs ' + matchup)}",
        "Batter vs Pitcher / Head-to-Head": f"https://www.google.com/search?q={quote_plus(player + ' batter vs pitcher history ' + matchup)}",
        "Splits": f"https://www.google.com/search?q={quote_plus(player + ' splits vs opponent ' + matchup + ' ' + market)}",
        "StatMuse Search": f"https://www.google.com/search?q={quote_plus(player + ' vs ' + matchup + ' ' + market)}",
        "Baseball Savant": f"https://baseballsavant.mlb.com/search?search={quote_plus(player)}",
    }



def render_parlay_cards(parlays, legs):
    if parlays.empty:
        st.warning("No clean parlays built with the current filters.")
        return

    for idx, row in parlays.head(12).iterrows():
        with st.container(border=True):
            st.markdown(f"### {legs}-Leg Suggested Parlay")
            c1, c2, c3 = st.columns(3)
            c1.metric("Combined Odds", format_odds(row["Combined Odds"]))
            c2.metric("Estimated Hit %", f"{row['Estimated Hit %']}%")
            c3.metric("Total Edge", f"{row['Total Edge']}%")

            for i in range(1, legs + 1):
                st.markdown(f"#### Leg {i}")
                st.write(f"**Pick:** {row.get(f'Leg {i} Pick', '')}")
                st.write(f"**Matchup:** {row.get(f'Leg {i} Matchup', '')}")
                st.write(f"**Book:** {format_book_name(row.get(f'Leg {i} Book', ''))}")
                st.write(f"**Best MN App:** {row.get(f'Leg {i} MN App', '')}")
                st.write(f"**Edge:** {row.get(f'Leg {i} Edge', '')}%")

                alts = row.get(f"Leg {i} Alternates", "")
                if alts:
                    st.caption(f"Alternate lines with edge: {alts}")

            st.divider()


# =========================================================
# UI
# =========================================================

def header():
    st.markdown(
        """
        <div class="hero">
            <div class="hero-title">CD BETTING V43</div>
            <div class="hero-sub">Parlay cards • matchup context • MN apps • alternate-line edge</div>
            <span class="pill">Common markets only</span>
            <span class="pill">No fake odds</span>
            <span class="pill">AI confidence 0-100</span>
            <span class="pill">History links</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def view_cols(df):
    cols = [
        "League", "Game Time", "Matchup", "Live Score", "Game Score", "Bucket", "Market",
        "Player", "Bet Side", "Prop Line", "Pick", "Best Odds", "Best Book",
        "Best MN App", "Available MN Apps", "Book Implied %", "Market Avg %",
        "Edge %", "Model Probability %", "High Rate Score", "Rating", "Units", "Books Compared",
    ]
    return df[[c for c in cols if c in df.columns]]


def render_sports_rail(df, selected_sport):
    rows = []
    for league in LEAGUES.keys():
        games = 0 if df.empty else df[df["League"] == league]["Matchup"].nunique()
        hot = " hot" if league == selected_sport else ""
        label = f"{SPORT_EMOJI.get(league, '')} {league}"
        rows.append(f'<div class="rail-item{hot}"><span>{label}</span><span>{games} games</span></div>')

    st.markdown(
        '<div class="left-rail"><div class="rail-title">Sports</div>' + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )


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

    main_md = md[md["Bucket"].isin(["Moneyline", "Spread", "Totals"])]
    best_pool = main_md if not main_md.empty else md
    best = best_pool.sort_values(["High Rate Score", "Edge %"], ascending=False).iloc[0]

    with st.container(border=True):
        st.markdown(f"### {matchup}")
        st.caption(f"{best['League']} • {best['Game Time']} • {best['Live Score']}")
        st.write(f"**Score:** {best.get('Game Score', 'Score unavailable')}")
        st.write(f"**Best common line:** {best['Pick']}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Edge", f"{best['Edge %']}%")
        c2.metric("Lines", len(main_md))
        c3.metric("Props", int(md["Is Prop"].sum()))

        if st.button("Open matchup details", key=f"open_{safe_key(matchup)}", use_container_width=True):
            st.session_state[state_key] = matchup
            st.session_state["sportsbook_view"] = "detail"
            st.rerun()


def render_player_history_panel(md):
    props = md[(md["Bucket"] == "Player Props") & (md["Player"].astype(str) != "")]
    props = choose_display_rows(props).head(25)

    st.markdown('<div class="market-header">Player History / Matchup Research</div>', unsafe_allow_html=True)
    st.caption(
        "This section links to matchup-history research. The app does not make up historical results. "
        "For exact all-time batter-vs-pitcher or player-vs-team logs, connect MLB StatsAPI/Statcast in the next build."
    )

    if props.empty:
        st.info("No player props available for matchup research.")
        return

    selected_pick = st.selectbox("Choose player prop to research", props["Pick"].tolist(), key=f"history_{md['Matchup'].iloc[0]}")
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
            st.dataframe(arbs[[c for c in arb_cols if c in arbs.columns]], use_container_width=True, hide_index=True)

    with research_tabs[2]:
        render_player_history_panel(md)


def ensure_loaded():
    if "all_df" not in st.session_state:
        st.session_state["all_df"] = pd.DataFrame()
    if "reports" not in st.session_state:
        st.session_state["reports"] = pd.DataFrame()


def auto_load_once():
    ensure_loaded()
    if st.session_state["all_df"].empty and not st.session_state.get("auto_load_failed", False):
        with st.spinner("Auto-loading all sports from SportsGameOdds..."):
            df, reports = fetch_all_sports()
        st.session_state["all_df"] = df
        st.session_state["reports"] = reports
        if df.empty:
            st.session_state["auto_load_failed"] = True


# =========================================================
# APP
# =========================================================

auto_load_once()
header()

tabs = st.tabs([
    "🏠 Dashboard",
    "📚 Sportsbook",
    "🤖 AI Predictions",
    "⚖️ Arbitrage",
    "🧾 Parlays",
    "📍 Minnesota Apps",
    "🔍 Search",
    "⚙️ Settings",
])

st.caption(f"Last updated: {datetime.now(ZoneInfo('America/Chicago')).strftime('%b %d • %I:%M %p CT')}")


with tabs[0]:
    st.header("Dashboard")

    if st.button("Refresh All Sports"):
        with st.spinner("Loading all available paginated matchups from SportsGameOdds..."):
            df, reports = fetch_all_sports()
        st.session_state["all_df"] = df
        st.session_state["reports"] = reports

    df = st.session_state["all_df"]

    if df.empty:
        st.info("Auto-load is running. If nothing appears, click Refresh All Sports.")
    else:
        top = (
            df.sort_values(["High Rate Score", "Edge %"], ascending=False)
            .drop_duplicates(subset=["Matchup", "Pick Key", "Market", "Line"], keep="first")
            .head(20)
        )
        ai = add_ai_columns(df).sort_values(["AI Confidence", "Edge %"], ascending=False).head(5)
        arbs = find_arbitrage(df)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Games", df["Matchup"].nunique())
        c2.metric("Markets", len(df))
        c3.metric("Best Edge", f"{df['Edge %'].max()}%")
        c4.metric("Sports", df["League"].nunique())

        st.subheader("Top 20 Common Sportsbook Edges")
        st.dataframe(view_cols(top), use_container_width=True, hide_index=True)

        st.subheader("Top 5 Clean AI Picks Today")
        render_top_ai_cards(add_ai_columns(df).sort_values(["AI Confidence", "Edge %"], ascending=False).head(5), count=5)

        st.subheader("Best Arbitrage")
        if arbs.empty:
            st.info("No clean arbitrage found in this scan.")
        else:
            arb_cols = [
                "Profit %", "League", "Matchup", "Market", "Line",
                "Side A", "Book A", "Side B", "Book B",
                "Best MN App", "Available MN Apps",
            ]
            st.dataframe(arbs.head(10)[[c for c in arb_cols if c in arbs.columns]], use_container_width=True, hide_index=True)


with tabs[1]:
    st.header("Sportsbook")

    if st.session_state["all_df"].empty:
        st.info("Dashboard is loading all sports. If nothing appears, use Refresh All Sports.")
    else:
        df = st.session_state["all_df"]
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
                        if st.button("← Back to matchups", use_container_width=True):
                            st.session_state["sportsbook_view"] = "list"
                            st.rerun()

                    with title_col:
                        st.markdown("#### Matchup Detail")

                    render_matchup_detail(sport_df, st.session_state["open_matchup"])

                else:
                    selected_matchup = st.selectbox(
                        "Quick open matchup",
                        matchup_list,
                        index=matchup_list.index(st.session_state["open_matchup"]),
                        key="sportsbook_open_matchup_select",
                    )

                    if selected_matchup != st.session_state["open_matchup"]:
                        st.session_state["open_matchup"] = selected_matchup

                    if st.button("Open selected matchup", use_container_width=True):
                        st.session_state["sportsbook_view"] = "detail"
                        st.rerun()

                    st.markdown("#### Games")
                    for matchup in matchup_scores["Matchup"].head(50):
                        render_game_summary_card(sport_df, matchup, state_key="open_matchup")


with tabs[2]:
    st.header("AI Predictions")

    df = st.session_state["all_df"]
    if df.empty:
        st.info("Load all sports from the Dashboard first.")
    else:
        props_only = st.checkbox("Only player props", value=False, key="ai_props_only")
        ai = add_ai_columns(df)

        if props_only:
            ai = ai[ai["Is Prop"] == True]

        ai = (
            ai.sort_values(["AI Confidence", "Edge %"], ascending=False)
            .drop_duplicates(subset=["Matchup", "Pick Key", "Market", "Line"], keep="first")
            .head(100)
        )

        st.subheader("Top 5 AI Picks")
        render_top_ai_cards(ai.head(5), count=5)

        st.subheader("Full AI Board")
        st.dataframe(
            ai[[
                "AI Grade", "AI Confidence", "League", "Matchup", "Bucket", "Pick",
                "Best Odds", "Best Book", "Best MN App", "Edge %",
                "Model Probability %", "Books Compared", "Rating",
            ]],
            use_container_width=True,
            hide_index=True,
        )

        if not ai.empty:
            selected = st.selectbox("Open AI matchup", ai["Matchup"].drop_duplicates().tolist(), key="ai_matchup")
            render_matchup_detail(df, selected)


with tabs[3]:
    st.header("Arbitrage")

    df = st.session_state["all_df"]
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
            st.dataframe(arbs[[c for c in arb_cols if c in arbs.columns]], use_container_width=True, hide_index=True)


with tabs[4]:
    st.header("Parlays")

    df = st.session_state["all_df"]
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
                st.dataframe(parlays, use_container_width=True, hide_index=True)


with tabs[5]:
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


with tabs[6]:
    st.header("Search")

    df = st.session_state["all_df"]
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


with tabs[7]:
    st.header("Settings")
    st.write("Structure: Sport → Matchup → Betting Lines → AI Evidence / Arbitrage / Player History.")
    st.write("Parlays now show matchup context, book, MN app routing, and alternate lines with edge.")
    st.write("AI Confidence is capped from 0 to 100.")
    st.write("Markets are limited to common sportsbook lines and common player props.")
    st.write("Player history links are included, but exact all-time batter-vs-pitcher logs require a stats database/API.")
    st.warning("Research tool only. No pick is guaranteed. Bet responsibly.")
