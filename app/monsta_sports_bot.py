import time
import threading
import requests
from datetime import datetime, timezone
from flask import Flask

# =============== FLASK APP (for Render / health check) ===============
app = Flask(__name__)

@app.route("/")
def home():
    return "MonstaTrades Sports Bot Running"
# ====================================================================


# ========================= CONFIG ==============================

TOKEN = "8306653164:AAHGMf5XnLD1ysld1KFCoAy1twcdt-vmcRg"   # <-- put your Telegram bot token here
CHAT_ID = -1003318925434           # your channel ID

ODDS_API_KEY = "77936dd856ff66f5d4bfe318884e0ab2"  # <-- put your odds API key here

SPORTS = [
    "americanfootball_nfl",
    "americanfootball_ncaaf",
    "basketball_nba",
    "basketball_ncaab",
    "baseball_mlb",
    "icehockey_nhl",
    "mma_mixed_martial_arts",
    "soccer_epl",
    "soccer_uefa_champs_league",
]

POLL_INTERVAL = 60                    # seconds between checks
PROB_CHANGE_THRESHOLD = 0.05
ODDS_MOVE_THRESHOLD = 0.15
GAME_START_ALERT_MINUTES = 15

# ===============================================================

previous_probs = {}
previous_prices = {}
start_alert_sent = set()


def send_message(text: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.get(url, params=params)
        if not r.ok:
            print("Telegram error:", r.text)
    except Exception as e:
        print("Send error:", e)


def decimal_to_prob(decimal_odds: float):
    return (1.0 / decimal_odds) if decimal_odds > 0 else 0.0


def parse_time(iso_string: str):
    if iso_string.endswith("Z"):
        iso_string = iso_string[:-1] + "+00:00"
    return datetime.fromisoformat(iso_string).astimezone(timezone.utc)


def fetch_odds(sport_key: str):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }
    r = requests.get(url, params=params)
    if not r.ok:
        print("Odds API error for", sport_key, ":", r.text)
        return []
    return r.json()


def compute_certainty(new_p, old_p):
    """
    Turn implied probability + recent change into a 0–100 'certainty' score.
    """
    base = new_p * 100.0
    change = (new_p - old_p) * 400.0
    score = base + change

    if score < 0:
        score = 0
    if score > 99:
        score = 99
    return score


def check_games():
    global previous_probs, previous_prices, start_alert_sent

    now = datetime.now(timezone.utc)

    for sport in SPORTS:
        games = fetch_odds(sport)

        for game in games:
            game_id = game.get("id")
            home = game.get("home_team")
            away = game.get("away_team")
            commence = game.get("commence_time")

            if not game.get("bookmakers"):
                continue

            bookmaker = game["bookmakers"][0]
            bookname = bookmaker.get("title", "Unknown")
            outcomes = bookmaker["markets"][0]["outcomes"]

            current_prices = {}
            current_probs = {}

            for outcome in outcomes:
                team = outcome["name"]
                price = float(outcome["price"])
                current_prices[team] = price
                current_probs[team] = decimal_to_prob(price)

            # GAME START ALERT
            if commence:
                start_time = parse_time(commence)
                mins_left = (start_time - now).total_seconds() / 60

                if 0 < mins_left <= GAME_START_ALERT_MINUTES and game_id not in start_alert_sent:
                    send_message(
                        f"🏟 GAME STARTING SOON\n\n"
                        f"{home} vs {away}\n"
                        f"Starts in ~{int(mins_left)} minutes\n"
                        f"Sport: {sport}\n"
                        f"Book: {bookname}"
                    )
                    start_alert_sent.add(game_id)

            # first time we see this game
            if game_id not in previous_probs:
                previous_probs[game_id] = current_probs
                previous_prices[game_id] = current_prices
                continue

            old_probs = previous_probs[game_id]
            old_prices = previous_prices[game_id]

            prob_alerts = []
            odds_alerts = []

            best_team = None
            best_cert = -1.0

            for team, new_p in current_probs.items():
                old_p = old_probs.get(team, new_p)
                diff_p = new


