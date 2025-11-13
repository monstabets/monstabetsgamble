import time
import requests
from datetime import datetime, timezone

# ================== CONFIG ==================

# Telegram
TOKEN = "8306653164:AAHGMf5XnLD1ysld1KFCoAy1twcdt-vmcRg"          # <-- your Telegram bot token here
CHAT_ID = -1003318925434               # MonstaTrades channel ID

# Odds API
ODDS_API_KEY = "77936dd856ff66f5d4bfe318884e0ab2"   # <-- your API key

# What sports to track
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
    "tennis_atp",
]

# Check every X seconds
POLL_INTERVAL = 60

# Alert thresholds
PROB_CHANGE_THRESHOLD = 0.05     # 5% probability move = alert
ODDS_MOVE_THRESHOLD = 0.15       # 0.15 decimal odds move = alert
GAME_START_ALERT_MINUTES = 15    # alert 15 min before start

# ============================================

previous_probs = {}
previous_prices = {}
start_alert_sent = set()


def send_message(text: str):
    """Send text to Telegram channel."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.get(url, params=params)
        if not r.ok:
            print("Telegram error:", r.text)
    except Exception as e:
        print("Request error:", e)


def decimal_to_prob(decimal_odds: float) -> float:
    return 1.0 / decimal_odds if decimal_odds > 0 else 0.0


def parse_time(iso_string: str):
    """Convert OddsAPI times into UTC datetime."""
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
        print("Odds API error:", r.text)
        return []
    return r.json()


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
            market = bookmaker["markets"][0]
            outcomes = market["outcomes"]

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
                        f"Starts in ~{int(mins_left)} min\n"
                        f"Book: {bookname}"
                    )
                    start_alert_sent.add(game_id)

            # First time seeing this game
            if game_id not in previous_probs:
                previous_probs[game_id] = current_probs
                previous_prices[game_id] = current_prices
                continue

            # PROBABILITY ALERTS
            old_probs = previous_probs[game_id]
            prob_alerts = []

            for team, new_p in current_probs.items():
                old_p = old_probs.get(team, 0)
                diff = new_p - old_p
                if abs(diff) >= PROB_CHANGE_THRESHOLD:
                    prob_alerts.append(
                        f"{team}: {old_p*100:.1f}% → {new_p*100:.1f}% ({diff*100:+.1f}%)"
                    )

            if prob_alerts:
                send_message(
                    f"🎯 PROBABILITY MOVE ALERT\n\n"
                    f"{home} vs {away}\n"
                    f"Book: {bookname}\n\n" +
                    "\n".join(prob_alerts)
                )

            # ODDS MOVEMENT ALERTS
            old_prices = previous_prices[game_id]
            price_alerts = []

            for team, new_price in current_prices.items():
                old_price = old_prices.get(team, 0)
                diff = new_price - old_price
                if abs(diff) >= ODDS_MOVE_THRESHOLD:
                    price_alerts.append(
                        f"{team}: {old_price:.2f} → {new_price:.2f} ({diff:+.2f})"
                    )

            if price_alerts:
                send_message(
                    f"📉 ODDS MOVEMENT ALERT\n\n"
                    f"{home} vs {away}\n"
                    f"Book: {bookname}\n\n" +
                    "\n".join(price_alerts)
                )

            # Update stored values
            previous_probs[game_id] = current_probs
            previous_prices[game_id] = current_prices


# ===================== MAIN LOOP =====================

# Startup messages
send_message("✅ MonstaTrades Sports Bot is now ONLINE.")
send_message("🔥 TEST ALERT – SPORTS BOT IS WORKING")

print("Sports bot running...")

while True:
    try:
        check_games()
    except Exception as e:
        print("Error:", e)
    time.sleep(POLL_INTERVAL)
