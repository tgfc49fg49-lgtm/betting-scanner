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
    "MMA": {"key": "mma_mixed_martial_arts", "markets": ["h2h"]},
    "Boxing": {"key": "boxing_boxing", "markets": ["h2h"]},
    "Golf PGA": {"key": "golf_pga", "markets": ["h2h"]},
    "NASCAR": {"key": "motorsport_nascar", "markets": ["h2h"]},
    "Soccer MLS": {"key": "soccer_usa_mls", "markets": ["h2h", "spreads", "totals"]},
}

BOOKS_TO_IGNORE = ["Bovada", "BetOnline.ag", "LowVig.ag"]


def american_to_decimal(odds):
    if odds > 0:
        return 1 + odds / 100
    return 1 + 100 / abs(odds)


def american_to_prob(odds):
    return 1 / american_to_decimal(odds)


def format_time(commence_time):
    utc_time = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    ct_time = utc_time.astimezone(ZoneInfo("America/Chicago"))
    return ct_time.strftime("%B %d, %Y • %I:%M %p CT")


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
    q_news = quote_plus(f"{matchup} preview odds injury report")
    q_injury = quote_plus(f"{matchup} injuries lineup news")
    q_preview = quote_plus(f"{matchup} betting preview prediction")

    return {
        "News": f"https://www.google.com/search?q={q_news}&tbm=nws",
        "Injuries": f"https://www.google.com/search?q={q_injury}",
        "Preview": f"https://www.google.com/search?q={q_preview}",
    }


def get_scores(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/scores"

    params = {
        "apiKey": API_KEY,
        "daysFrom": 1,
    }

    try:
        response = requests.get(url, params=params, timeout=20)
        if response.status_code != 200:
            return {}

        games = response.json()
    except Exception:
        return {}

    scores = {}

    for game in games:
        matchup = f'{game.get("away_team")} @ {game.get("home_team")}'
        completed = game.get("completed", False)

        score_text = "Scheduled / no score yet"

        if game.get("scores"):
            parts = []
            for score in game["scores"]:
                parts.append(f'{score["name"]}: {score["score"]}')

            score_text = " | ".join(parts)

            if completed:
                score_text += " | Final"
            else:
                score_text += " | Live / recent"

        scores[matchup] = score_text

    return scores


def scan_sport(sport_name, sport_key, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american",
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        return [], response.text

    games = response.json()
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
                "News Link": data["links"]["News"],
                "Injury Link": data["links"]["Injuries"],
                "Preview Link": data["links"]["Preview"],
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


def show_matchup_breakdowns(df):
    matchups = df["Matchup"].unique()

    for matchup in matchups:
        matchup_df = df[df["Matchup"] == matchup].sort_values("Edge %", ascending=False)
        first = matchup_df.iloc[0]

        with st.expander(f"{first['Sport']} — {matchup} | {first['Game Time']}"):
            st.write(f"**Live score/status:** {first['Live Score']}")

            col1, col2, col3 = st.columns(3)

            with col1:
                st.link_button("📰 News", first["News Link"])

            with col2:
                st.link_button("🚑 Injuries", first["Injury Link"])

            with col3:
                st.link_button("📊 Preview", first["Preview Link"])

            st.subheader("All Betting Categories Found")

            st.dataframe(
                matchup_df[[
                    "Market",
                    "Pick",
                    "Best Odds",
                    "Best Book",
                    "Book Implied %",
                    "Market Avg %",
                    "Edge %",
                    "Rating",
                    "Suggested Units",
                ]],
                use_container_width=True
            )

            st.subheader("Best Plays From This Matchup")

            for _, row in matchup_df.head(5).iterrows():
                msg = (
                    f"**{row['Rating']}**  \n"
                    f"**{row['Pick']}** | {row['Best Odds']} at **{row['Best Book']}**  \n"
                    f"Market: **{row['Market']}**  \n"
                    f"Edge: **{row['Edge %']}%**  \n"
                    f"Suggested Units: **{row['Suggested Units']}**"
                )

                if "BET NOW" in row["Rating"]:
                    st.success(msg)
                elif "WATCH" in row["Rating"]:
                    st.warning(msg)
                else:
                    st.info(msg)


st.set_page_config(page_title="Sports Betting Scanner", layout="wide")

st.title("Sports Betting Value Scanner")
st.caption("Version 4.3 — clickable articles, matchup breakdowns, all betting categories.")

last_updated = datetime.now(ZoneInfo("America/Chicago")).strftime("%B %d, %Y • %I:%M %p CT")
st.caption(f"Last updated: {last_updated}")

page = st.sidebar.radio(
    "Navigation",
    ["Home", "Value Scanner", "Summary"]
)

if page == "Home":
    st.header("Top 20 Best Edge Bets Across All Sports")

    if st.button("Scan Top 20 Best Edge Bets"):
        with st.spinner("Scanning all sports..."):
            results, errors = scan_all_sports()

        if errors:
            with st.expander("Skipped / unavailable sports"):
                for error in errors:
                    st.warning(error)

        if not results:
            st.warning("No value spots found right now.")
        else:
            df = pd.DataFrame(results)
            df = df.sort_values("Edge %", ascending=False).head(20)

            st.subheader("Top 20 Edge Board")

            display_df = df[[
                "Sport",
                "Game Time",
                "Matchup",
                "Live Score",
                "Market",
                "Pick",
                "Best Odds",
                "Best Book",
                "Edge %",
                "Rating",
                "Suggested Units",
            ]]

            st.dataframe(display_df, use_container_width=True)

            st.subheader("Clickable Matchup Breakdowns")
            show_matchup_breakdowns(df)

elif page == "Value Scanner":
    st.header("Single Sport Value Scanner")

    sport_name = st.selectbox("Choose Sport", list(SPORTS.keys()))
    info = SPORTS[sport_name]

    selected_markets = st.multiselect(
        "Markets to scan",
        info["markets"],
        default=info["markets"]
    )

    min_edge = st.slider("Minimum Edge %", 0.0, 10.0, 1.0, 0.25)
    top_n = st.slider("Number of picks to show", 5, 100, 20, 5)
    show_only_watch = st.checkbox("Only show WATCH / BET NOW picks", value=False)

    if st.button("Scan Sport"):
        with st.spinner("Scanning odds..."):
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

            if df.empty:
                st.warning("No picks matched your filters.")
            else:
                st.subheader("Value Board")
                st.dataframe(df, use_container_width=True)

                st.subheader("Clickable Matchup Breakdowns")
                show_matchup_breakdowns(df)

elif page == "Summary":
    st.header("How to Read This Scanner")

    st.subheader("Edge %")
    st.write(
        "Edge % compares the best available sportsbook price against the average market probability. "
        "Higher edge means one book may be offering a better price than the others."
    )

    st.subheader("Rating")
    st.markdown("""
    - `🔥 BET NOW` = Edge is 5% or higher
    - `👀 STRONG WATCH` = Edge is 3% to 4.99%
    - `🟡 WATCH` = Edge is 2% to 2.99%
    - `PASS` = Edge is under 2%
    """)

    st.subheader("Book Implied %")
    st.write("The probability implied by the sportsbook odds.")

    st.subheader("Market Avg %")
    st.write("Average implied probability across the sportsbooks being scanned.")

    st.subheader("All Betting Categories")
    st.write(
        "Inside each matchup breakdown, the app shows all available categories pulled for that sport, "
        "such as moneyline, spreads, totals, and head-to-head markets."
    )

    st.subheader("Articles / News")
    st.write(
        "Each matchup has clickable buttons for News, Injuries, and Preview links."
    )

    st.warning(
        "This is a research tool, not a guarantee. Bet small and never risk money you cannot afford to lose."
    )