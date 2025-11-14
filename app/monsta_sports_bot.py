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
CHAT_ID = -1003318925434

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
    "tennis_atp",
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
   
    def compute_certainty(new_p, old_p):
    """
    Turn implied probability + recent change into a 0–100 'certainty' score.
    This is NOT real AI, just a simple model using odds movement.
    """
    base = new_p * 100.0              # current implied probability %
    change = (new_p - old_p) * 400.0   # reward recent moves (5% move = +20)
    score = base + change

    # clamp between 0 and 99 so it looks clean
    if score < 0:
        score = 0
    if score > 99:
        score = 99
    return score

    r = requests.get(url, params=params)
    if not r.ok:
        print("Odds API error for", sport_key, ":", r.text)
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

            # First time seeing this game
            if game_id not in previous_probs:
                previous_probs[game_id] = current_probs
                previous_prices[game_id] = current_prices
                continue

            old_probs = previous_probs[game_id]
            old_prices = previous_prices[game_id]

            # --- build probability + odds alerts ---
            prob_alerts = []
            odds_alerts = []

            # also track best side for "what to bet"
            best_team = None
            best_cert = -1.0

            for team, new_p in current_probs.items():
                old_p = old_probs.get(team, new_p)
                diff_p = new_p - old_p

                # probability move
                if abs(diff_p) >= PROB_CHANGE_THRESHOLD:
                    prob_alerts.append(
                        f"{team}: {old_p*100:.1f}% → {new_p*100:.1f}% ({diff_p*100:+.1f}%)"
                    )

                # odds move
                new_price = current_prices.get(team, 0.0)
                old_price = old_prices.get(team, new_price)
                diff_price = new_price - old_price
                if abs(diff_price) >= ODDS_MOVE_THRESHOLD:
                    odds_alerts.append(
                        f"{team}: {old_price:.2f} → {new_price:.2f} ({diff_price:+.2f})"
                    )

                # compute "certainty" / edge for this team
                # only consider sides whose probability went UP
                if diff_p > 0:
                    cert = compute_certainty(new_p, old_p)
                    if cert > best_cert:
                        best_cert = cert
                        best_team = team

            # if nothing moved, skip this game
            if not prob_alerts and not odds_alerts:
                previous_probs[game_id] = current_probs
                previous_prices[game_id] = current_prices
                continue

            # build one combined alert message
            msg_lines = [
                f"📊 {sport.upper()} LINE MOVE\n",
                f"{home} vs {away}",
                f"Book: {bookname}",
                ""
            ]

            if prob_alerts:
                msg_lines.append("🎯 Probability moves:")
                msg_lines.extend(prob_alerts)
                msg_lines.append("")

            if odds_alerts:
                msg_lines.append("📉 Odds moves:")
                msg_lines.extend(odds_alerts)
                msg_lines.append("")

            # add suggested bet if we have a best_team
            if best_team is not None:
                msg_lines.append("💡 Suggested bet (NOT financial advice):")
                msg_lines.append(f"Bet: {best_team} moneyline")
                msg_lines.append(f"AI-style certainty: {best_cert:.0f}/100")
                msg_lines.append("Use bankroll management. Gamble responsibly.")

            send_message("\n".join(msg_lines))

            # update memory
            previous_probs[game_id] = current_probs
            previous_prices[game_id] = current_prices

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

            # First time seeing this game
            if game_id not in previous_probs:
                previous_probs[game_id] = current_probs
                previous_prices[game_id] = current_prices
                continue

            old_probs = previous_probs[game_id]
            old_prices = previous_prices[game_id]

            # PROBABILITY ALERT
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

            # ODDS ALERT
            odds_alerts = []
            for team, new_price in current_prices.items():
                old_price = old_prices.get(team, 0)
                diff = new_price - old_price
                if abs(diff) >= ODDS_MOVE_THRESHOLD:
                    odds_alerts.append(
                        f"{team}: {old_price:.2f} → {new_price:.2f} ({diff:+.2f})"
                    )

            if odds_alerts:
                send_message(
                    f"📉 ODDS MOVEMENT ALERT\n\n"
                    f"{home} vs {away}\n"
                    f"Book: {bookname}\n\n" +
                    "\n".join(odds_alerts)
                )

            previous_probs[game_id] = current_probs
            previous_prices[game_id] = current_prices


def bot_loop():
    """Run the betting bot forever in a background thread."""
    send_message("✅ MonstaTrades Sports Bot is now ONLINE.")
    send_message("🔥 TEST ALERT – SPORTS BOT IS WORKING")
    print("Sports bot running...")

    while True:
        try:
            check_games()
        except Exception as e:
            print("Error in bot loop:", e)
        time.sleep(POLL_INTERVAL)


# start the bot thread as soon as the module is imported (for gunicorn)
threading.Thread(target=bot_loop, daemon=True).start()

# If you run this file locally: python monsta_sports_bot.py
if __name__ == "__main__":
    # keep main thread alive when running locally
    while True:
        time.sleep(3600)



