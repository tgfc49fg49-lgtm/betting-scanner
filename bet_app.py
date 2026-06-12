import requests
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

API_KEY = "2f7afd7c33504715784ab006af05b58c"

SPORTS = {
    "MLB": "baseball_mlb",
    "WNBA": "basketball_wnba",
    "MMA": "mma_mixed_martial_arts",
    "NBA": "basketball_nba",
    "NHL": "icehockey_nhl",
    "NFL": "americanfootball_nfl",
    "Soccer MLS": "soccer_usa_mls",
}

BOOKS_TO_IGNORE = [
    "Bovada",
    "BetOnline.ag",
    "LowVig.ag",
]

def american_to_decimal(odds):
    if odds > 0:
        return 1 + odds / 100
    return 1 + 100 / abs(odds)

def american_to_prob(odds):
    decimal = american_to_decimal(odds)
    return 1 / decimal

def suggested_units(edge_percent):
    if edge_percent >= 5:
        return 1.0
    if edge_percent >= 3:
        return 0.5
    if edge_percent >= 2:
        return 0.25
    return 0

def rating_from_edge(edge_percent):
    if edge_percent >= 5:
        return "🔥 BET NOW"
    if edge_percent >= 3:
        return "👀 STRONG WATCH"
    if edge_percent >= 2:
        return "🟡 WATCH"
    return "PASS"

def format_time(commence_time):
    utc_time = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    ct_time = utc_time.astimezone(ZoneInfo("America/Chicago"))
    return ct_time.strftime("%B %d, %Y • %I:%M %p CT")

def scan_sport(sport, markets):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": ",".join(markets),
        "oddsFormat": "american"
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        st.error(response.text)
        return []

    games = response.json()
    results = []

    for game in games:
        matchup = f'{game["away_team"]} @ {game["home_team"]}'
        game_time = format_time(game["commence_time"])

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

                    pick_label = name
                    if point != "":
                        pick_label = f"{name} {point}"

                    pick_key = f"{market_key}|{pick_label}"

                    if pick_key not in prices:
                        prices[pick_key] = {
                            "market": market_key,
                            "pick": pick_label,
                            "lines": []
                        }

                    prices[pick_key]["lines"].append({
                        "book": book_name,
                        "odds": odds,
                        "prob": american_to_prob(odds)
                    })

        for _, data in prices.items():
            lines = data["lines"]

            if len(lines) < 2:
                continue

            market_prob = sum(x["prob"] for x in lines) / len(lines)
            best_line = min(lines, key=lambda x: x["prob"])

            edge = market_prob - best_line["prob"]
            edge_percent = round(edge * 100, 2)

            if edge_percent <= 0:
                continue

            results.append({
                "Game Time": game_time,
                "Matchup": matchup,
                "Market": data["market"],
                "Pick": data["pick"],
                "Best Odds": best_line["odds"],
                "Best Book": best_line["book"],
                "Book Implied %": round(best_line["prob"] * 100, 2),
                "Market Avg %": round(market_prob * 100, 2),
                "Edge %": edge_percent,
                "Suggested Units": suggested_units(edge_percent),
                "Rating": rating_from_edge(edge_percent)
            })

    return sorted(results, key=lambda x: x["Edge %"], reverse=True)

st.set_page_config(page_title="Sports Betting Value Scanner", layout="wide")

st.title("Sports Betting Value Scanner")
st.caption("Version 3 — WNBA added, spreads/totals added, ratings added, unit sizing added.")

sport_name = st.selectbox("Choose Sport", list(SPORTS.keys()))
sport = SPORTS[sport_name]

market_options = {
    "Moneyline": "h2h",
    "Spreads": "spreads",
    "Totals": "totals",
}

selected_market_names = st.multiselect(
    "Markets to scan",
    list(market_options.keys()),
    default=["Moneyline", "Spreads", "Totals"]
)

markets = [market_options[name] for name in selected_market_names]

min_edge = st.slider("Minimum Edge %", 0.0, 10.0, 1.0, 0.25)
top_n = st.slider("Number of bets to show", 5, 50, 10, 5)
show_only_watch = st.checkbox("Only show WATCH / BET NOW picks", value=False)

if st.button("Scan Value Board"):
    with st.spinner("Scanning odds..."):
        results = scan_sport(sport, markets)

    if not results:
        st.warning("No matchups or value spots found right now.")
    else:
        df = pd.DataFrame(results)

        df = df[df["Edge %"] >= min_edge]

        if show_only_watch:
            df = df[df["Rating"] != "PASS"]

        df = df.head(top_n)

        if df.empty:
            st.warning("No bets matched your filters.")
        else:
            st.subheader(f"Top {len(df)} Value Spots")
            st.dataframe(df, use_container_width=True)

            st.subheader("Best Alerts")

            for _, row in df.iterrows():
                message = (
                    f"**{row['Rating']}**  \n"
                    f"**{row['Pick']}** | {row['Best Odds']} at **{row['Best Book']}**  \n"
                    f"Market: **{row['Market']}**  \n"
                    f"📅 {row['Game Time']}  \n"
                    f"🏟 {row['Matchup']}  \n"
                    f"Edge: **{row['Edge %']}%**  \n"
                    f"Suggested Bet: **{row['Suggested Units']} units**"
                )

                if "BET NOW" in row["Rating"]:
                    st.success(message)
                elif "WATCH" in row["Rating"]:
                    st.warning(message)
                else:
                    st.info(message)