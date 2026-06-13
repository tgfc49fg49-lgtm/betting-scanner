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

st.set_page_config(page_title="CD Betting", layout="wide")

st.markdown("""
<style>
.stApp { background:#090909; color:#e8e8e8; }
[data-testid="stSidebar"] { display:none; }
[data-testid="collapsedControl"] { display:none; }
.block-container { max-width:1250px; padding-top:1.2rem; }
.cd-header {
    background:linear-gradient(135deg,#111,#1b1b1b);
    border:1px solid #444;
    border-radius:18px;
    padding:24px;
    margin-bottom:16px;
}
.cd-logo { color:#ff1f2d; font-size:46px; font-weight:900; }
.cd-subtitle { color:#c0c0c0; font-size:15px; }
.nav-bar {
    display:flex; gap:10px; flex-wrap:wrap;
    background:#111; border:1px solid #333;
    padding:12px; border-radius:16px; margin-bottom:20px;
}
.metric-card, .bet-card {
    background:#121212; border:1px solid #333;
    border-radius:16px; padding:16px; margin-bottom:14px;
}
.bet-card { border-left:6px solid #c1121f; }
.metric-label { color:#c0c0c0; font-size:12px; text-transform:uppercase; }
.metric-value { font-size:30px; font-weight:900; color:white; }
.tag-red {
    background:#c1121f; color:white; padding:4px 10px;
    border-radius:999px; font-weight:800; font-size:12px;
}
.tag-silver {
    background:#c0c0c0; color:#080808; padding:4px 10px;
    border-radius:999px; font-weight:800; font-size:12px;
}
div.stButton > button {
    background:#c1121f; color:white; border-radius:12px;
    border:1px solid #c1121f; font-weight:800;
}
div.stButton > button:hover {
    background:#8f0d17; color:white; border:1px solid #c0c0c0;
}
a { color:#ff4b5c !important; }
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
    return utc_time.astimezone(ZoneInfo("America/Chicago")).strftime("%B %d, %Y • %I:%M %p CT")

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
        "Google News": f"https://www.google.com/search?q={q}+local+team+news&tbm=nws",
        "Local News": f"https://www.google.com/search?q={q}+local+sports+news",
        "Injuries": f"https://www.google.com/search?q={q}+injury+report+lineups",
        "Preview": f"https://www.google.com/search?q={q}+betting+preview+prediction",
        "ESPN": f"https://www.google.com/search?q=ESPN+{q}",
        "CBS": f"https://www.google.com/search?q=CBS+Sports+{q}",
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
        score_text = "Scheduled / no score yet"
        if game.get("scores"):
            parts = [f'{s["name"]}: {s["score"]}' for s in game["scores"]]
            score_text = " | ".join(parts)
            score_text += " | Final" if game.get("completed") else " | Live / recent"
        scores[matchup] = score_text
    return scores

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

def parse_games(sport_name, sport_key, games):
    scores = get_scores(sport_key)
    results = []

    for game in games:
        matchup = f'{game["away_team"]} @ {game["home_team"]}'
        game_time = format_time(game["commence_time"])
        live_score = scores.get(matchup, "Not live / no score available")
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
                            "sport": sport_name,
                            "game_time": game_time,
                            "matchup": matchup,
                            "live_score": live_score,
                            "market": market_key,
                            "pick": pick_label,
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
                "Sport": data["sport"],
                "Game Time": data["game_time"],
                "Matchup": data["matchup"],
                "Live Score": data["live_score"],
                "Market": data["market"],
                "Pick": data["pick"],
                "Best Odds": best_line["odds"],
                "Best Book": best_line["book"],
                "Book Implied %": round(best_line["prob"] * 100, 2),
                "Market Avg %": round(market_prob * 100, 2),
                "Edge %": edge,
                "Rating": rating_from_edge(edge),
                "Suggested Units": suggested_units(edge),
                "Google News": data["links"]["Google News"],
                "Local News": data["links"]["Local News"],
                "Injuries": data["links"]["Injuries"],
                "Preview": data["links"]["Preview"],
                "ESPN": data["links"]["ESPN"],
                "CBS": data["links"]["CBS"],
            })

    return results, None

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
                    "News": links["Google News"],
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
    candidates = df[
        (df["Rating"] != "PASS") &
        (df["Book Implied %"] >= 45)
    ].copy()

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

        parlays.append({
            "Legs": legs,
            "Combined Odds": decimal_to_american(decimal_total),
            "Estimated Hit %": round(probability_total * 100, 2),
            "Total Edge": round(edge_total, 2),
            "Leg 1": f"{combo[0]['Pick']} ({combo[0]['Best Odds']})",
            "Leg 2": f"{combo[1]['Pick']} ({combo[1]['Best Odds']})",
            "Leg 3": f"{combo[2]['Pick']} ({combo[2]['Best Odds']})" if legs >= 3 else "",
            "Leg 4": f"{combo[3]['Pick']} ({combo[3]['Best Odds']})" if legs >= 4 else "",
        })

    return sorted(parlays, key=lambda x: (x["Estimated Hit %"], x["Total Edge"]), reverse=True)[:max_results]

def render_header():
    st.markdown("""
    <div class="cd-header">
        <div class="cd-logo">CD BETTING</div>
        <div class="cd-subtitle">Sharp betting dashboard • Edge scanner • Arbitrage • Parlays</div>
    </div>
    """, unsafe_allow_html=True)

def render_nav():
    page = st.radio(
        "Navigation",
        ["Dashboard", "Value Scanner", "Fight Hub", "Arbitrage", "Parlay Builder", "Summary"],
        horizontal=True,
        label_visibility="collapsed",
    )
    return page

def metric_card(label, value):
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value">{value}</div>
    </div>
    """, unsafe_allow_html=True)

def render_links(row):
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: st.link_button("📰 News", row["Google News"])
    with c2: st.link_button("🏙 Local", row["Local News"])
    with c3: st.link_button("🚑 Injuries", row["Injuries"])
    with c4: st.link_button("📊 Preview", row["Preview"])
    with c5: st.link_button("ESPN", row["ESPN"])
    with c6: st.link_button("CBS", row["CBS"])

def render_bet_card(row):
    tag = "tag-red" if "BET NOW" in row["Rating"] else "tag-silver"
    st.markdown(f"""
    <div class="bet-card">
        <span class="{tag}">{row['Rating']}</span>
        <h3>{row['Sport']} — {row['Pick']}</h3>
        <p><b>Market:</b> {row['Market']} | <b>Edge:</b> {row['Edge %']}% | <b>Suggested:</b> {row['Suggested Units']} units</p>
        <p><b>Best Odds:</b> {row['Best Odds']} at <b>{row['Best Book']}</b></p>
        <p><b>Matchup:</b> {row['Matchup']}</p>
        <p><b>Time:</b> {row['Game Time']}</p>
        <p><b>Status:</b> {row['Live Score']}</p>
    </div>
    """, unsafe_allow_html=True)
    render_links(row)

def show_matchup_breakdowns(df):
    for matchup in df["Matchup"].unique():
        matchup_df = df[df["Matchup"] == matchup].sort_values("Edge %", ascending=False)
        first = matchup_df.iloc[0]

        with st.expander(f"{first['Sport']} — {matchup} | {first['Game Time']}"):
            st.write(f"**Live score/status:** {first['Live Score']}")
            render_links(first)

            st.subheader("All Betting Categories")
            st.dataframe(
                matchup_df[[
                    "Market", "Pick", "Best Odds", "Best Book",
                    "Book Implied %", "Market Avg %", "Edge %",
                    "Rating", "Suggested Units"
                ]],
                use_container_width=True,
            )

            st.subheader("Best Plays")
            for _, row in matchup_df.head(5).iterrows():
                render_bet_card(row)


render_header()
page = render_nav()

last_updated = datetime.now(ZoneInfo("America/Chicago")).strftime("%B %d, %Y • %I:%M %p CT")
st.caption(f"Last updated: {last_updated}")

if page == "Dashboard":
    st.header("Top 20 Best Edge Bets Across All Sports")

    with st.spinner("Loading top 20 edge board..."):
        results, errors = scan_all_sports()

    if errors:
        with st.expander("Skipped / unavailable sports or markets"):
            for e in errors:
                st.warning(e)

    if not results:
        st.warning("No value spots found.")
    else:
        df = pd.DataFrame(results).sort_values("Edge %", ascending=False).head(20)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            metric_card("🔥 BET NOW", len(df[df["Rating"].str.contains("BET NOW")]))
        with c2:
            metric_card("👀 WATCH", len(df[df["Rating"].str.contains("WATCH")]))
        with c3:
            metric_card("🎯 BEST EDGE", f"{df['Edge %'].max()}%")
        with c4:
            metric_card("📋 PICKS", len(df))

        st.subheader("Edge Board")
        st.dataframe(df, use_container_width=True)

        st.subheader("Cards")
        for _, row in df.iterrows():
            render_bet_card(row)

        st.subheader("Matchup Breakdowns")
        show_matchup_breakdowns(df)
        if errors:
            with st.expander("Skipped / unavailable sports or markets"):
                for e in errors:
                    st.warning(e)

        if not results:
            st.warning("No value spots found.")
        else:
            df = pd.DataFrame(results).sort_values("Edge %", ascending=False).head(20)

            c1, c2, c3, c4 = st.columns(4)
            with c1: metric_card("🔥 BET NOW", len(df[df["Rating"].str.contains("BET NOW")]))
            with c2: metric_card("👀 WATCH", len(df[df["Rating"].str.contains("WATCH")]))
            with c3: metric_card("🎯 BEST EDGE", f"{df['Edge %'].max()}%")
            with c4: metric_card("📋 PICKS", len(df))

            st.subheader("Edge Board")
            st.dataframe(df, use_container_width=True)

            st.subheader("Cards")
            for _, row in df.iterrows():
                render_bet_card(row)

            st.subheader("Matchup Breakdowns")
            show_matchup_breakdowns(df)

elif page == "Value Scanner":
    st.header("Single Sport Value Scanner")

    sport_name = st.selectbox("Choose Sport", list(SPORTS.keys()))
    info = SPORTS[sport_name]

    selected_markets = st.multiselect("Markets", info["markets"], default=info["markets"])
    min_edge = st.slider("Minimum Edge %", 0.0, 10.0, 1.0, 0.25)
    top_n = st.slider("Picks to show", 5, 100, 20, 5)
    show_only_watch = st.checkbox("Only WATCH / BET NOW", value=False)

    if st.button("Scan Sport"):
        with st.spinner("Scanning..."):
            results, error = scan_sport(sport_name, info["key"], selected_markets)

        if error:
            st.error(error)
        elif not results:
            st.warning("No value spots found.")
        else:
            df = pd.DataFrame(results)
            df = df[df["Edge %"] >= min_edge]

            if show_only_watch:
                df = df[df["Rating"] != "PASS"]

            df = df.sort_values("Edge %", ascending=False).head(top_n)

            st.dataframe(df, use_container_width=True)
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
            st.dataframe(df, use_container_width=True)
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
            with st.expander("Skipped / unavailable"):
                for e in errors:
                    if e:
                        st.warning(e)

        if not arbs:
            st.warning("No arbitrage found.")
        else:
            df = pd.DataFrame(arbs).head(25)
            st.dataframe(df, use_container_width=True)

elif page == "Parlay Builder":
    st.header("Parlay Builder")
    st.caption("Builds possible parlays from higher edge picks. This is not a guarantee.")

    legs = st.selectbox("Parlay Legs", [2, 3, 4], index=1)
    scan_scope = st.selectbox("Scan", ["All Sports", "Single Sport"])

    if scan_scope == "Single Sport":
        sport_name = st.selectbox("Choose Sport", list(SPORTS.keys()))
        info = SPORTS[sport_name]

    if st.button("Build Parlays"):
        with st.spinner("Finding parlay combinations..."):
            if scan_scope == "All Sports":
                results, errors = scan_all_sports()
            else:
                results, error = scan_sport(sport_name, info["key"], info["markets"])
                errors = [error] if error else []

        if not results:
            st.warning("No picks available for parlays.")
        else:
            df = pd.DataFrame(results)
            parlays = build_parlays(df, legs=legs, max_results=15)

            if not parlays:
                st.warning("No clean parlay combinations found.")
            else:
                parlay_df = pd.DataFrame(parlays)
                st.dataframe(parlay_df, use_container_width=True)

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
    st.write("Arbitrage looks for markets where best prices across books total under 100% implied probability.")

    st.subheader("Parlay Builder")
    st.write("The parlay page combines higher-edge picks while avoiding multiple legs from the same matchup.")

    st.warning("Research tool only. No pick is guaranteed.")