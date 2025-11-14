import requests
import time
import schedule
from telegram import Bot

# ================== CONFIG ==================
TELEGRAM_BOT_TOKEN = "8306653164:AAHGMf5XnLD1ysld1KFCoAy1twcdt-vmcRg"
CHAT_ID = "-1003318925434"

ODDS_API_KEY = "77936dd856ff66f5d4bfe318884e0ab2"

# Sports to track (add/remove as you want)
SPORTS = [
    "basketball_nba",
    "americanfootball_nfl",
    "icehockey_nhl",
    "baseball_mlb",
    "soccer_epl"
]

REGIONS = "us"          # us = US books
MARKETS = "h2h,spreads,totals"  # moneyline, spread, total
ODDS_FORMAT = "american"

# Thresholds for “movement” alerts
MIN_ODDS_MOVE = 10          # e.g. -120 → -130 or +100 → +110
MIN_PROB_MOVE = 0.03        # 3% change in implied probability
# ============================================

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Store previous odds to detect changes
# key: (sport_key, game_id, bookmaker, market, outcome_name)
# value: {"price": int, "implied_prob": float}
last_odds_state = {}


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability (0–1)."""
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return -odds / (-odds + 100)


def fetch_odds_for_sport(sport_key: str):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": ODDS_FORMAT
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def build_alert_message(sport_key, game, bookmaker, market, outcome, old, new):
    home = game.get("home_team")
    away = game.get("away_team")
    commences = game.get("commence_time", "N/A")

    line_change = new["price"] - old["price"]
    prob_change = (new["implied_prob"] - old["implied_prob"]) * 100

    direction = "⬆️" if line_change > 0 else "⬇️"
    prob_dir = "↑" if prob_change > 0 else "↓"

    msg = (
        f"🎯 *Odds Movement Alert*\n"
        f"🏟️ *Sport:* `{sport_key}`\n"
        f"🆚 *Game:* {away} @ {home}\n"
        f"⏰ *Start:* `{commences}`\n\n"
        f"🏛️ *Book:* {bookmaker['title']}\n"
        f"📈 *Market:* {market['key']}\n"
        f"🎰 *Outcome:* {outcome['name']}\n\n"
        f"💵 Odds: {old['price']} → {new['price']}  {direction}\n"
        f"📊 Implied prob: {old['implied_prob']*100:.1f}% → {new['implied_prob']*100:.1f}% {prob_dir} ({prob_change:+.1f}%)\n"
    )
    return msg


def check_for_movers():
    global last_odds_state
    messages = []

    for sport_key in SPORTS:
        try:
            games = fetch_odds_for_sport(sport_key)
        except Exception as e:
            print(f"[ERROR] Fetching odds for {sport_key}: {e}")
            continue

        for game in games:
            game_id = game.get("id")

            for bookmaker in game.get("bookmakers", []):
                book_key = bookmaker.get("key")

                for market in bookmaker.get("markets", []):
                    market_key = market.get("key")

                    for outcome in market.get("outcomes", []):
                        outcome_name = outcome.get("name")
                        price = outcome.get("price")

                        if price is None:
                            continue

                        implied_prob = american_to_implied_prob(int(price))

                        state_key = (sport_key, game_id, book_key, market_key, outcome_name)
                        new_state = {
                            "price": int(price),
                            "implied_prob": implied_prob
                        }

                        if state_key in last_odds_state:
                            old_state = last_odds_state[state_key]
                            price_diff = new_state["price"] - old_state["price"]
                            prob_diff = abs(new_state["implied_prob"] - old_state["implied_prob"])

                            if abs(price_diff) >= MIN_ODDS_MOVE or prob_diff >= MIN_PROB_MOVE:
                                # significant movement → alert
                                msg = build_alert_message(
                                    sport_key, game, bookmaker, market,
                                    outcome, old_state, new_state
                                )
                                messages.append(msg)

                        # update state
                        last_odds_state[state_key] = new_state

    # send alerts (if any)
    if not messages:
        print("No significant movements this run.")
        return

    for m in messages:
        try:
            bot.send_message(chat_id=CHAT_ID, text=m, parse_mode="Markdown")
        except Exception as e:
            print(f"[ERROR] Sending message: {e}")

    print(f"Sent {len(messages)} movement alerts.")


def send_heartbeat():
    """Optional: ping to confirm bot is alive."""
    try:
        bot.send_message(chat_id=CHAT_ID, text="🤖 Monsta Bets bot heartbeat – still watching the lines.")
    except Exception as e:
        print(f"[ERROR] Heartbeat failed: {e}")


# ==================== MAIN LOOP =====================

def main():
    send_message("✅ MonstaTrades Sports Bot is now ONLINE.")
    send_message("🔥 TEST ALERT – SPORTS BOT IS WORKING")

    print("Sports bot running...")

    while True:
        try:
            check_games()
        except Exception as e:
            print("Error:", e)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
