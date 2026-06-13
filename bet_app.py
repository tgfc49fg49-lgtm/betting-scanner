import itertools
import requests
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote_plus

API_KEY = "2f7afd7c33504715784ab006af05b58c"

SPORTS = {
    "MLB": {"key": "baseball_mlb", "markets": ["h2h", "spreads", "totals"]},
    "WNBA": {"key": "basketball_wnba", "markets": ["h2h", "spreads", "totals"]},
    "NBA": {"key": "basketball_nba", "markets": ["h2h", "spreads", "totals"]},
    "NHL": {"key": "icehockey_nhl", "markets": ["h2h", "spreads", "totals"]},
    "NFL": {"key": "americanfootball_nfl", "markets": ["h2h", "spreads", "totals"]},
    "MMA": {"key": "mma_mixed_martial_arts", "markets": ["h2h", "method_of_victory", "fight_goes_distance", "round_totals"]},
    "Boxing": {"key": "boxing_boxing", "markets": ["h2h", "method_of_victory", "fight_goes_distance", "round_totals"]},
    "Golf PGA": {"key": "golf_pga", "markets": ["h2h"]},
    "NASCAR": {"key": "motorsport_nascar", "markets": ["h2h"]},
    "Soccer MLS": {"key": "soccer_usa_mls", "markets": ["h2h", "spreads", "totals"]},
}

BOOKS_TO_IGNORE = ["Bovada", "BetOnline.ag", "LowVig.ag"]

st.set_page_config(
    page_title="CD Betting",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
[data-testid="stSidebar"] {display:none;}
[data-testid="collapsedControl"] {display:none;}
.block-container {max-width: 1180px; padding-top: 1rem; padding-bottom: 4rem;}

.stApp {
    background: linear-gradient(180deg, #edf3fb 0%, #f7f9fc 100%);
    color: #111827;
}

.hero {
    background: linear-gradient(135deg, #143d73 0%, #0d2446 70%);
    color: white;
    border-radius: 28px;
    padding: 28px;
    box-shadow: 0 20px 40px rgba(13,36,70,.22);
    margin-bottom: 18px;
}

.logo {
    font-size: 42px;
    font-weight: 950;
    letter-spacing: -1px;
}

.subtitle {
    color: #dce8f7;
    font-size: 15px;
    margin-top: 4px;
}

.nav-wrap {
    background: white;
    border-radius: 22px;
    padding: 10px;
    box-shadow: 0 10px 30px rgba(20,61,115,.12);
    margin-bottom: 18px;
}

div[role="radiogroup"] {
    gap: 8px;
}

.metric {
    background: white;
    border-radius: 22px;
    padding: 18px;
    box-shadow: 0 10px 30px rgba(20,61,115,.10);
    border: 1px solid #e7edf5;
}

.metric-label {
    color: #6b7280;
    font-size: 12px;
    font-weight: 800;
    text-transform: uppercase;
}

.metric-value {
    color: #143d73;
    font-size: 30px;
    font-weight: 950;
}

.pick-card {
    background: white;
    border-radius: 26px;
    padding: 18px;
    margin-bottom: 16px;
    border: 1px solid #e7edf5;
    box-shadow: 0 12px 32px rgba(20,61,115,.12);
}

.pick-card-red {
    border-left: 7px solid #e11d48;
}

.pick-card-blue {
    border-left: 7px solid #2563eb;
}

.pick-card-gray {
    border-left: 7px solid #94a3b8;
}

.badge-red {
    background: #e11d48;
    color: white;
    padding: 5px 11px;
    border-radius: 999px;
    font-weight: 900;
    font-size: 12px;
}

.badge-blue {
    background: #143d73;
    color: white;
    padding: 5px 11px;
    border-radius: 999px;
    font-weight: 900;
    font-size: 12px;
}

.badge-gray {
    background: #e5e7eb;
    color: #111827;
    padding: 5px 11px;
    border-radius: 999px;
    font-weight: 900;
    font-size: 12px;
}

.card-title {
    font-size: 22px;
    font-weight: 950;
    color: #111827;
    margin-top: 10px;
}

.card-sub {
    color: #475569;
    font-size: 14px;
    margin-top: 4px;
}

.stat-line {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
}

.stat-pill {
    background: #f1f5f9;
    color: #0f172a;
    padding: 8px 11px;
    border-radius: 14px;
    font-weight: 800;
    font-size: 13px;
}

.link-row a {
    display: inline-block;
    margin-right: 8px;
    margin-top: 12px;
    background: #143d73;
    color: white !important;
    text-decoration: none;
    padding: 8px 12px;
    border-radius: 14px;
    font-weight: 900;
    font-size: 13px;
}

.link-row a:nth-child(2) {background:#e11d48;}
.link-row a:nth-child(3) {background:#334155;}

div.stButton > button {
    background: #e11d48;
    color: white;
    border-radius: 16px;
    border: 0;
    font-weight: 950;
    padding: .6rem 1rem;
}

div.stButton > button:hover {
    background: #be123c;
    color: white;
}

[data-testid="stDataFrame"] {
    border-radius: 22px;
    overflow: hidden;
    box-shadow: 0 10px 30px rgba(20,61,115,.10);
}

@media (max-width: 700px) {
    .logo {font-size: 34px;}
    .hero {padding: 22px;}
    .card-title {font-size: 19px;}
}
</style>
""", unsafe_allow_html=True)


def american_to_decimal(odds):
    return 1 + odds / 100 if odds > 0 else 1 + 100 / abs(odds)

def american_to_prob(odds):
    return 1 / american_to_decimal(odds)

def decimal_to_american(decimal_odds):
    if decimal_odds >= 2:
        return round((decimal_odds - 1) * 100)
    return round(-100 / (decimal_odds - 1))

def format_time(commence_time):
    utc_time = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    return utc_time.astimezone(ZoneInfo("America/Chicago")).strftime("%b %d • %I:%M %p CT")

def rating_from_edge(edge):
    if edge >= 5:
        return "🔥 BET NOW"
    if edge >= 3:
        return "👀 STRONG WATCH"
    if edge >= 2:
        return "🟡 WATCH"
    return "PASS"

def suggested_units(edge):
    if edge >= 5:
        return 1.0
    if edge >= 3:
        return 0.5
    if edge >= 2:
        return 0.25
    return 0

def make_links(matchup):
    q = quote_plus(matchup)
    return {
        "News": f"https://www.google.com/search?q={q}+local+team+news&tbm=nws",
        "Local": f"https://www.google.com/search?q={q}+local+sports+news",
        "Preview": f"https://www.google.com/search?q={q}+betting+preview+prediction",
        "Injuries": f"https://www.google.com/search?q={q}+injury+report+lineups",
    }

def fetch_odds(sport_key, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american",
    }
    return requests.get(url, params=params, timeout=30)

def get_scores(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores"
    params = {"apiKey": API_KEY, "daysFrom": 1}

    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return {}
        games = r.json()
    except Exception:
        return {}

    scores = {}
    for game in games:
        matchup = f'{game.get("away_team")} @ {game.get("home_team")}'
        score_text = "Scheduled"
        if game.get("scores"):
            parts = [f'{s["name"]}: {s["score"]}' for s in game["scores"]]
            score_text = " | ".join(parts)
            score_text += " | Final" if game.get("completed") else " | Live"
        scores[matchup] = score_text
    return scores

def parse_games(sport_name, sport_key, games):
    scores = get_scores(sport_key)
    results = []

    for game in games:
        matchup = f'{game["away_team"]} @ {game["home_team"]}'
        game_time = format_time(game["commence_time"])
        live_score = scores.get(matchup, "No live score")
        links = make_links(matchup)

        prices = {}

        for book in game.get("bookmakers", []):
            book_name = book["title"]
            if book_name in BOOKS_TO_IGNORE:
                continue

            for market in book.get("markets", []):
                market_key = market.get("key", "unknown")

                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    odds = outcome.get("price")
                    point = outcome.get("point", "")

                    if odds is None:
                        continue

                    pick_label = name if point == "" else f"{name} {point}"
                    pick_key = f"{matchup}|{market_key}|{pick_label}"

                    if pick_key not in prices:
                        prices[pick_key] = {
                            "Sport": sport_name,
                            "Game Time": game_time,
                            "Matchup": matchup,
                            "Live Score": live_score,
                            "Market": market_key,
                            "Pick": pick_label,
                            "links": links,
                            "lines": [],
                        }

                    prices[pick_key]["lines"].append({
                        "book": book_name,
                        "odds": odds,
                        "prob": american_to_prob(odds),
                    })

        for _, data in prices.items():
            lines = data["lines"]
            if len(lines) < 2:
                continue

            market_prob = sum(x["prob"] for x in lines) / len(lines)
            best_line = min(lines, key=lambda x: x["prob"])
            edge = round((market_prob - best_line["prob"]) * 100, 2)

            if edge <= 0:
                continue

            results.append({
                "Sport": data["Sport"],
                "Game Time": data["Game Time"],
                "Matchup": data["Matchup"],
                "Live Score": data["Live Score"],
                "Market": data["Market"],
                "Pick": data["Pick"],
                "Best Odds": best_line["odds"],
                "Best Book": best_line["book"],
                "Book Implied %": round(best_line["prob"] * 100, 2),
                "Market Avg %": round(market_prob * 100, 2),
                "Edge %": edge,
                "Rating": rating_from_edge(edge),
                "Suggested Units": suggested_units(edge),
                "News": data["links"]["News"],
                "Local": data["links"]["Local"],
                "Preview": data["links"]["Preview"],
                "Injuries": data["links"]["Injuries"],
            })

    return results, None

def scan_sport(sport_name, sport_key, markets):
    response = fetch_odds(sport_key, markets)

    if response.status_code != 200:
        results = []
        for market in markets:
            r = fetch_odds(sport_key, [market])
            if r.status_code == 200:
                parsed, _ = parse_games(sport_name, sport_key, r.json())
                results.extend(parsed)

        if results:
            return results, None

        return [], response.text

    return parse_games(sport_name, sport_key, response.json())

def scan_all_sports():
    all_results = []
    errors = []

    for sport_name, info in SPORTS.items():
        results, error = scan_sport(sport_name, info["key"], info["markets"])
        if error:
            errors.append(f"{sport_name}: {error}")
        else:
            all_results.extend(results)

    return all_results, errors

def find_arbitrage_for_sport(sport_name, sport_key, markets):
    r = fetch_odds(sport_key, markets)
    if r.status_code != 200:
        return [], r.text

    arbs = []

    for game in r.json():
        matchup = f'{game["away_team"]} @ {game["home_team"]}'
        game_time = format_time(game["commence_time"])
        links = make_links(matchup)
        markets_by_key = {}

        for book in game.get("bookmakers", []):
            book_name = book["title"]
            if book_name in BOOKS_TO_IGNORE:
                continue

            for market in book.get("markets", []):
                market_key = market.get("key", "unknown")
                markets_by_key.setdefault(market_key, {})

                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    odds = outcome.get("price")
                    point = outcome.get("point", "")

                    if odds is None:
                        continue

                    outcome_key = name if point == "" else f"{name} {point}"
                    markets_by_key[market_key].setdefault(outcome_key, [])
                    markets_by_key[market_key][outcome_key].append({
                        "book": book_name,
                        "odds": odds,
                        "prob": american_to_prob(odds),
                    })

        for market_key, outcomes in markets_by_key.items():
            if len(outcomes) < 2:
                continue

            best_outcomes = []
            for outcome_name, lines in outcomes.items():
                best = min(lines, key=lambda x: x["prob"])
                best_outcomes.append({
                    "outcome": outcome_name,
                    "book": best["book"],
                    "odds": best["odds"],
                    "prob": best["prob"],
                })

            best_outcomes = sorted(best_outcomes, key=lambda x: x["prob"])[:2]
            total_prob = sum(x["prob"] for x in best_outcomes)
            arb_profit = round((1 - total_prob) * 100, 2)

            if total_prob < 1:
                arbs.append({
                    "Sport": sport_name,
                    "Game Time": game_time,
                    "Matchup": matchup,
                    "Market": market_key,
                    "Leg 1": best_outcomes[0]["outcome"],
                    "Leg 1 Odds": best_outcomes[0]["odds"],
                    "Leg 1 Book": best_outcomes[0]["book"],
                    "Leg 2": best_outcomes[1]["outcome"],
                    "Leg 2 Odds": best_outcomes[1]["odds"],
                    "Leg 2 Book": best_outcomes[1]["book"],
                    "Total Implied %": round(total_prob * 100, 2),
                    "Arb Profit %": arb_profit,
                    "News": links["News"],
                    "Preview": links["Preview"],
                })

    return sorted(arbs, key=lambda x: x["Arb Profit %"], reverse=True), None

def find_all_arbitrage():
    all_arbs = []
    errors = []
    for sport_name, info in SPORTS.items():
        arbs, error = find_arbitrage_for_sport(sport_name, info["key"], info["markets"])
        if error:
            errors.append(f"{sport_name}: {error}")
        else:
            all_arbs.extend(arbs)
    return sorted(all_arbs, key=lambda x: x["Arb Profit %"], reverse=True), errors

def build_parlays(df, legs=3, max_results=10):
    candidates = df[(df["Rating"] != "PASS") & (df["Book Implied %"] >= 45)].copy()

    if candidates.empty:
        candidates = df[df["Book Implied %"] >= 50].copy()

    candidates = candidates.sort_values(["Edge %", "Book Implied %"], ascending=False).head(30)
    parlays = []

    for combo in itertools.combinations(candidates.to_dict("records"), legs):
        matchups = [x["Matchup"] for x in combo]
        if len(set(matchups)) < len(matchups):
            continue

        decimal_total = 1
        probability_total = 1
        edge_total = 0

        for leg in combo:
            decimal_total *= american_to_decimal(leg["Best Odds"])
            probability_total *= leg["Book Implied %"] / 100
            edge_total += leg["Edge %"]

        parlay = {
            "Legs": legs,
            "Combined Odds": decimal_to_american(decimal_total),
            "Estimated Hit %": round(probability_total * 100, 2),
            "Total Edge": round(edge_total, 2),
        }

        for i, leg in enumerate(combo, start=1):
            parlay[f"Leg {i}"] = f"{leg['Sport']} — {leg['Pick']} ({leg['Best Odds']})"

        parlays.append(parlay)

    return sorted(parlays, key=lambda x: (x["Estimated Hit %"], x["Total Edge"]), reverse=True)[:max_results]

def render_header():
    st.markdown("""
    <div class="hero">
        <div class="logo">CD BETTING</div>
        <div class="subtitle">Sharp picks • Live odds • Edge board • Parlays</div>
    </div>
    """, unsafe_allow_html=True)

def render_metric(label, value):
    st.markdown(f"""
    <div class="metric">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
    </div>
    """, unsafe_allow_html=True)

def render_bet_card(row):
    rating = row["Rating"]
    card_class = "pick-card-gray"
    badge = "badge-gray"

    if "BET NOW" in rating:
        card_class = "pick-card-red"
        badge = "badge-red"
    elif "WATCH" in rating:
        card_class = "pick-card-blue"
        badge = "badge-blue"

    st.markdown(f"""
    <div class="pick-card {card_class}">
        <span class="{badge}">{rating}</span>
        <div class="card-title">{row['Sport']} • {row['Pick']}</div>
        <div class="card-sub">{row['Matchup']}</div>
        <div class="stat-line">
            <span class="stat-pill">Edge {row['Edge %']}%</span>
            <span class="stat-pill">Odds {row['Best Odds']}</span>
            <span class="stat-pill">{row['Best Book']}</span>
            <span class="stat-pill">{row['Game Time']}</span>
            <span class="stat-pill">{row['Market']}</span>
        </div>
        <div class="card-sub" style="margin-top:10px;">{row['Live Score']}</div>
        <div class="link-row">
            <a href="{row['News']}" target="_blank">News</a>
            <a href="{row['Local']}" target="_blank">Local</a>
            <a href="{row['Preview']}" target="_blank">Preview</a>
            <a href="{row['Injuries']}" target="_blank">Injuries</a>
        </div>
    </div>
    """, unsafe_allow_html=True)

def show_matchup_breakdowns(df):
    for matchup in df["Matchup"].unique():
        matchup_df = df[df["Matchup"] == matchup].sort_values("Edge %", ascending=False)
        first = matchup_df.iloc[0]

        with st.expander(f"{first['Sport']} • {matchup} • {first['Game Time']}"):
            st.write(f"**Live status:** {first['Live Score']}")
            st.link_button("News", first["News"])
            st.link_button("Local Team News", first["Local"])
            st.link_button("Preview", first["Preview"])
            st.link_button("Injuries", first["Injuries"])

            st.dataframe(
                matchup_df[[
                    "Market", "Pick", "Best Odds", "Best Book",
                    "Book Implied %", "Market Avg %", "Edge %",
                    "Rating", "Suggested Units"
                ]],
                use_container_width=True,
            )

render_header()

st.markdown('<div class="nav-wrap">', unsafe_allow_html=True)
page = st.radio(
    "Navigation",
    ["Dashboard", "Value Scanner", "Fight Hub", "Arbitrage", "Parlay Builder", "Summary"],
    horizontal=True,
    label_visibility="collapsed"
)
st.markdown('</div>', unsafe_allow_html=True)

last_updated = datetime.now(ZoneInfo("America/Chicago")).strftime("%b %d • %I:%M %p CT")
st.caption(f"Last updated: {last_updated}")

if page == "Dashboard":
    st.header("Top 20 Edge Picks")

    with st.spinner("Loading top picks..."):
        results, errors = scan_all_sports()

    if errors:
        with st.expander("Skipped / unavailable"):
            for e in errors:
                st.warning(e)

    if not results:
        st.warning("No value spots found.")
    else:
        df = pd.DataFrame(results).sort_values("Edge %", ascending=False).head(20)

        c1, c2, c3, c4 = st.columns(4)
        with c1: render_metric("BET NOW", len(df[df["Rating"].str.contains("BET NOW")]))
        with c2: render_metric("WATCH", len(df[df["Rating"].str.contains("WATCH")]))
        with c3: render_metric("BEST EDGE", f"{df['Edge %'].max()}%")
        with c4: render_metric("PICKS", len(df))

        st.subheader("Best Picks")
        for _, row in df.iterrows():
            render_bet_card(row)

        st.subheader("Full Edge Board")
        st.dataframe(df, use_container_width=True)

        st.subheader("Matchup Breakdowns")
        show_matchup_breakdowns(df)

elif page == "Value Scanner":
    st.header("Value Scanner")

    sport_name = st.selectbox("Choose Sport", list(SPORTS.keys()))
    info = SPORTS[sport_name]
    selected_markets = st.multiselect("Markets", info["markets"], default=info["markets"])
    min_edge = st.slider("Minimum Edge %", 0.0, 10.0, 1.0, 0.25)
    top_n = st.slider("Picks to show", 5, 100, 20, 5)
    only_watch = st.checkbox("Only WATCH / BET NOW", value=False)

    if st.button("Scan Sport"):
        results, error = scan_sport(sport_name, info["key"], selected_markets)

        if error:
            st.error(error)
        elif not results:
            st.warning("No value spots found.")
        else:
            df = pd.DataFrame(results)
            df = df[df["Edge %"] >= min_edge]

            if only_watch:
                df = df[df["Rating"] != "PASS"]

            df = df.sort_values("Edge %", ascending=False).head(top_n)

            for _, row in df.iterrows():
                render_bet_card(row)

            show_matchup_breakdowns(df)

elif page == "Fight Hub":
    st.header("Fight Hub")

    fight_sport = st.selectbox("Fight Sport", ["MMA", "Boxing"])
    info = SPORTS[fight_sport]
    selected_markets = st.multiselect("Fight Markets", info["markets"], default=info["markets"])

    if st.button("Scan Fight Card"):
        results, error = scan_sport(fight_sport, info["key"], selected_markets)

        if error:
            st.error(error)
        elif not results:
            st.warning("No fight props found right now.")
        else:
            df = pd.DataFrame(results).sort_values("Edge %", ascending=False)
            for _, row in df.head(40).iterrows():
                render_bet_card(row)
            show_matchup_breakdowns(df)

elif page == "Arbitrage":
    st.header("Arbitrage Finder")

    scope = st.selectbox("Scan", ["All Sports", "Single Sport"])

    if scope == "Single Sport":
        sport_name = st.selectbox("Choose Sport", list(SPORTS.keys()))
        info = SPORTS[sport_name]

    if st.button("Scan Arbitrage"):
        if scope == "All Sports":
            arbs, errors = find_all_arbitrage()
        else:
            arbs, error = find_arbitrage_for_sport(sport_name, info["key"], info["markets"])
            errors = [error] if error else []

        if errors:
            with st.expander("Skipped"):
                for e in errors:
                    if e:
                        st.warning(e)

        if not arbs:
            st.warning("No arbitrage found.")
        else:
            st.dataframe(pd.DataFrame(arbs).head(25), use_container_width=True)

elif page == "Parlay Builder":
    st.header("Parlay Builder")

    legs = st.selectbox("Parlay Legs", [2, 3, 4], index=1)
    scope = st.selectbox("Scan", ["All Sports", "Single Sport"])

    if scope == "Single Sport":
        sport_name = st.selectbox("Choose Sport", list(SPORTS.keys()))
        info = SPORTS[sport_name]

    if st.button("Build Parlays"):
        if scope == "All Sports":
            results, errors = scan_all_sports()
        else:
            results, error = scan_sport(sport_name, info["key"], info["markets"])
            errors = [error] if error else []

        if not results:
            st.warning("No picks available.")
        else:
            df = pd.DataFrame(results)
            parlays = build_parlays(df, legs=legs, max_results=15)

            if not parlays:
                st.warning("No clean parlay combinations found.")
            else:
                st.dataframe(pd.DataFrame(parlays), use_container_width=True)

elif page == "Summary":
    st.header("How to Read CD Betting")

    st.subheader("Edge %")
    st.write("Edge % compares the best sportsbook price against the average market probability.")

    st.subheader("Ratings")
    st.markdown("""
    - 🔥 BET NOW = Edge is 5%+
    - 👀 STRONG WATCH = Edge is 3% to 4.99%
    - 🟡 WATCH = Edge is 2% to 2.99%
    - PASS = Under 2%
    """)

    st.subheader("Arbitrage")
    st.write("Arbitrage looks for markets where the best prices across books total under 100% implied probability.")

    st.subheader("Parlay Builder")
    st.write("The parlay page combines higher-edge picks while avoiding multiple legs from the same matchup.")

    st.subheader("Downloadable App")
    st.write("Open the Streamlit URL on your phone, tap Share, then Add to Home Screen. Name it CD Betting.")

    st.warning("Research tool only. No pick is guaranteed.")