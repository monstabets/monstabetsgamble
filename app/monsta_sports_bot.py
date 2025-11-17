import time
import threading
import requests
from datetime import datetime, timezone
from flask import Flask

# ================== FLASK APP (Render health check) ==================

app = Flask(__name__)

@app.route("/")
def home():
    return "MonstaSports Bot Running"

@app.route("/test")
def test():
    # Hit https://YOUR-APP.onrender.com/test to verify Telegram send works
    send_message("🧪 Test signal from MonstaSports server")
    return "Test message sent"

# =========================== CONFIG =================================

# FILL THESE IN WITH YOUR REAL VALUES
TOKEN = "8306653164:AAHGMf5XnLD1ysld1KFCoAy1twcdt-vmcRg"  # from BotFather
CHAT_ID = -1003318925434                # your channel id (must start with -100)
ODDS_API_KEY = "77936dd856ff66f5d4bfe318884e0ab2" # from the-odds-api

# Sports keys supported by the-odds-api v4 (adjust if needed)
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
PROB_CHANGE_THRESHOLD = 0.05          # 5% probability change
ODDS_MOVE_THRESHOLD = 0.15            # 0.15 decimal odds move
GAME_START_ALERT_MINUTES = 15         # minutes before start

# ====================================================================

previous_probs = {}
previous_prices = {}
start_alert_sent = set()


# ========================= TELEGRAM HELPERS =========================

def send_message(text: str):
    """Send a plain text message to the configured Telegram chat."""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    params = {
        "chat_id": CHAT_ID,
        "text": text
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        if not r.ok:
            print("Telegram error:", r.text)
    except Exception as e:
        print("Send error:", e)


# ========================= ODDS API HELPERS =========================

def decimal_to_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability."""
    return (1.0 / decimal_odds) if decimal_odds > 0 else 0.0


def parse_time(iso_string: str) -> datetime:
    """Parse the-odds-api ISO time into UTC datetime."""
    if iso_string.endswith("Z"):
        iso_string = iso_string[:-1] + "+00:00"
    return datetime.fromisoformat(iso_string).astimezone(timezone.utc)


def fetch_odds(sport_key: str):
    """Fetch odds for a single sport from the-odds-api."""
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }
    try:
        r = requests.get(url, params=params, timeout=10)
    except Exception as e:
        print(f"Request error for {sport_key}:", e)
        return []

    if not r.ok:
        print(f"Odds API error for {sport_key} :", r.text)
        return []

    try:
        return r.json()
    except Exception as e:
        print(f"JSON parse error for {sport_key}:", e, "raw:", r.text)
        return []


# ======================= AI "CERTAINTY" MODEL =======================

def compute_certainty(new_p: float, old_p: float) -> float:
    """
    Turn implied probability + recent change into a 0–100 'certainty' score.
    This is NOT real AI, just simple math using:
      - current implied probability
      - recent change in that probability
    """
    base = new_p * 100.0               # current implied probability %
    change = (new_p - old_p) * 400.0   # boost recent moves (5% = +20)
    score = base + change

    if score < 0:
        score = 0
    if score > 99:
        score = 99
    return score


def risk_label(certainty: float) -> str:
    """Map certainty 0–100 to a text risk band."""
    if certainty >= 80:
        return "HIGH"
    if certainty >= 65:
        return "MEDIUM"
    return "LOW"


# ======================= CORE GAME CHECKING LOOP ====================

def check_games():
    """Fetch odds, compare to last run, and send alerts if something moved."""
    global previous_probs, previous_prices, start_alert_sent

    now = datetime.now(timezone.utc)

    for sport in SPORTS:
        games = fetch_odds(sport)
        if not games:
            continue

        for game in games:
            game_id = game.get("id")
            home = game.get("home_team")
            away = game.get("away_team")
            commence = game.get("commence_time")

            if not game_id or not home or not away:
                continue

            if not game.get("bookmakers"):
                continue

            # Take first bookmaker's h2h market
            bookmaker = game["bookmakers"][0]
            bookname = bookmaker.get("title", "Unknown")
            markets = bookmaker.get("markets", [])
            if not markets:
                continue

            outcomes = markets[0].get("outcomes", [])
            if not outcomes:
                continue

            current_prices = {}
            current_probs = {}

            for outcome in outcomes:
                team = outcome.get("name")
                price = outcome.get("price")
                if team is None or price is None:
                    continue
                price = float(price)
                current_prices[team] = price
                current_probs[team] = decimal_to_prob(price)

            # ---------------- GAME START ALERT ----------------
            if commence:
                try:
                    start_time = parse_time(commence)
                    mins_left = (start_time - now).total_seconds() / 60
                except Exception as e:
                    print("Time parse error:", e, commence)
                    mins_left = None

                if (
                    mins_left is not None and
                    0 < mins_left <= GAME_START_ALERT_MINUTES and
                    game_id not in start_alert_sent
                ):
                    send_message(
                        f"🏟 GAME STARTING SOON\n\n"
                        f"{home} vs {away}\n"
                        f"Starts in ~{int(mins_left)} minutes\n"
                        f"Sport: {sport}\n"
                        f"Book: {bookname}"
                    )
                    start_alert_sent.add(game_id)

            # First time we see this game → just store baseline
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
                diff_p = new_p - old_p

                # -------- probability move --------
                if abs(diff_p) >= PROB_CHANGE_THRESHOLD:
                    prob_alerts.append(
                        f"{team}: {old_p * 100:.1f}% → {new_p * 100:.1f}% ({diff_p * 100:+.1f}%)"
                    )

                # -------- odds move --------
                new_price = current_prices.get(team, 0.0)
                old_price = old_prices.get(team, new_price)
                diff_price = new_price - old_price

                if abs(diff_price) >= ODDS_MOVE_THRESHOLD:
                    odds_alerts.append(
                        f"{team}: {old_price:.2f} → {new_price:.2f} ({diff_price:+.2f})"
                    )

                # -------- certainty & best side --------
                if diff_p > 0:  # only consider sides whose win chance increased
                    cert = compute_certainty(new_p, old_p)
                    if cert > best_cert:
                        best_cert = cert
                        best_team = team

            # Nothing interesting happened → skip
MIN_CERTAINTY = 75  # only send quality signals

if (
    not prob_alerts
    or not odds_alerts
    or best_team is None
    or best_cert < MIN_CERTAINTY
):
    # skip weak signals
    previous_probs[game_id] = current_probs
    previous_prices[game_id] = current_prices
    
  continue

# Build clean alert message
sport_tag = sport.split("_")[0].upper()  # e.g. BASKETBALL_NBA → BASKETBALL
msg_lines = [
    f"🏟 <b>{sport_tag}</b> | LINE MOVE\n",
    f"{home} vs {away}",
    f"Book: {bookname}",
    "",
]


            if prob_alerts:
                msg_lines.append("🎯 Probability moves:")
                msg_lines.extend(prob_alerts)
                msg_lines.append("")

            if odds_alerts:
                msg_lines.append("📉 Odds moves:")
                msg_lines.extend(odds_alerts)
                msg_lines.append("")

            # Suggested bet section
            if best_team is not None and best_cert >= 0:
                label = risk_label(best_cert)
                msg_lines.append("💡 Suggested bet:")
                msg_lines.append(f"➡️ {best_team} moneyline")
                msg_lines.append(f"AI Certainty: {best_cert:.0f}/100")
                msg_lines.append(f"Risk Level: {label}")
                msg_lines.append("")
                msg_lines.append("⚠️ Not financial advice. Gamble responsibly.")

            # Send final message
            send_message("\n".join(msg_lines))

            # Update memory for next loop
            previous_probs[game_id] = current_probs
            previous_prices[game_id] = current_prices


# ======================= BOT LOOP / THREAD ==========================

def bot_loop():
    """Run the betting bot forever in a background thread."""
    print("Bot loop starting...")
    send_message("✅ MonstaSports AI Sports Bot is now ONLINE.")
    send_message("🔥 TEST ALERT – SPORTS BOT IS WORKING")
    print("Sports bot running...")

    while True:
        try:
            check_games()
        except Exception as e:
            print("Error in bot loop:", e)
        time.sleep(POLL_INTERVAL)


# Start the bot thread as soon as the module is imported (for gunicorn)
print("Starting bot thread from module import...")
threading.Thread(target=bot_loop, daemon=True).start()
print("Bot thread started.")


# If you run this file directly with: python monsta_sports_bot.py
if __name__ == "__main__":
    # Keep process alive locally (Flask isn't used in this mode)
    while True:
        time.sleep(3600)


