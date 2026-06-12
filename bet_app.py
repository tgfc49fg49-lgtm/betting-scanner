import requests
import streamlit as st

API_KEY = "2f7afd7c33504715784ab006af05b58c"

SPORTS = {
    "MLB": "baseball_mlb",
    "NBA": "basketball_nba",
    "NHL": "icehockey_nhl",
    "NFL": "americanfootball_nfl",
    "MMA": "mma_mixed_martial_arts",
}

def american_to_decimal(odds):
    if odds > 0:
        return 1 + odds / 100
    return 1 + 100 / abs(odds)

def implied_probability(odds):
    decimal = american_to_decimal(odds)
    return 1 / decimal

def scan_sport(sport):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "american"
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        st.error(response.text)
        return

    games = response.json()

    for game in games:
        st.subheader(f'{game["away_team"]} @ {game["home_team"]}')

        prices = {}

        for book in game.get("bookmakers", []):
            book_name = book["title"]

            for market in book.get("markets", []):
                for outcome in market.get("outcomes", []):
                    team = outcome["name"]
                    odds = outcome["price"]

                    if team not in prices:
                        prices[team] = []

                    prices[team].append({
                        "book": book_name,
                        "odds": odds
                    })

        for team, lines in prices.items():
            if not lines:
                continue

            best = max(lines, key=lambda x: x["odds"])
            avg_odds = sum(x["odds"] for x in lines) / len(lines)

            edge = best["odds"] - avg_odds
            implied = implied_probability(best["odds"]) * 100

            st.write(f"**{team}**")
            st.write(f"Best odds: `{best['odds']}` at **{best['book']}**")
            st.write(f"Market average: `{round(avg_odds, 1)}`")
            st.write(f"Implied probability: `{round(implied, 2)}%`")

            if edge >= 15:
                st.success(f"🔥 VALUE ALERT — Best line is {round(edge, 1)} points better than market average")
            else:
                st.caption("Pass / normal line")

            st.divider()

st.title("Sports Betting Value Scanner")

sport_name = st.selectbox("Choose Sport", list(SPORTS.keys()))
sport = SPORTS[sport_name]

if st.button("Scan Odds"):
    scan_sport(sport)