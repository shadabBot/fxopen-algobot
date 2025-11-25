import requests
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from flask import Flask
import threading
import time
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# CONFIGURATION (UPDATED & WORKING)
# ==========================================
TOKEN_ID = os.getenv("FXOPEN_TOKEN_ID")
TOKEN_KEY = os.getenv("FXOPEN_TOKEN_KEY")
TOKEN_SECRET = os.getenv("FXOPEN_TOKEN_SECRET")

# CORRECT DEMO API URL (WORKS ON RENDER.COM)
BASE_URL = "https://api-demo.fxopen.com/api/v2"

SYMBOL = "XAUUSD"
LOT_SIZE = 0.10
RISK_REWARD = 2.5
CHECK_INTERVAL = 5
LOOKBACK = 500
MAX_TRADES_PER_DAY = 10
COOLDOWN_BARS = 10
EMA_FAST = 9
EMA_SLOW = 21
ATR_PERIOD = 14
SL_ATR_BUFFER = 0.1
MIN_BODY_PCT = 0.20
USE_BODY_FILTER = False
VOL_MULT = 1.05
USE_VOLUME_FILTER = False
USE_EMA_FILTER = True
ENTRY_TF = "M5"
HTF_TF = "M30"
SERVER_TZ = pytz.timezone("Europe/Moscow")

# Email
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
RECIPIENTS = ["tasksubmission878@gmail.com", "eventshadab@gmail.com"]

def send_email(subject: str, message: str):
    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["Subject"] = subject
        msg["To"] = ", ".join(RECIPIENTS)
        msg.attach(MIMEText(message, "html"))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Email failed: {e}")

# ==========================================
# API WITH RETRY
# ==========================================
def api_request(method, endpoint, **kwargs):
    url = f"{BASE_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {TOKEN_ID}",
        "X-Token-Key": TOKEN_KEY,
        "Content-Type": "application/json"
    }
    for i in range(5):
        try:
            r = requests.request(method, url, headers=headers, timeout=10, **kwargs)
            if r.status_code in [200, 201]:
                return r.json()
            else:
                print(f"API Error {r.status_code}: {r.text}")
        except Exception as e:
            print(f"Connection attempt {i+1} failed: {e}")
            time.sleep(5)
    return None

def get_account():
    return api_request("GET", "/account")

def get_candles(symbol, timeframe, count=500):
    data = api_request("GET", f"/history/candles/{symbol}/{timeframe}", params={"count": count})
    if not data or "candles" not in data:
        return None
    df = pd.DataFrame(data["candles"])
    df["time"] = pd.to_datetime(df["time"], unit="s").dt.tz_localize("UTC").dt.tz_convert(SERVER_TZ)
    return df

def place_order(side, volume, sl=None, tp=None):
    payload = {
        "symbol": SYMBOL,
        "side": side,
        "volume": volume,
        "comment": "VWAP+EMA Strategy"
    }
    if sl: payload["stopLoss"] = sl
    if tp: payload["takeProfit"] = tp
    result = api_request("POST", "/trading/orders/market", json=payload)
    if result:
        price = result.get("price", 0)
        print(f"{side.upper()} ORDER EXECUTED at ~{price:.2f}")
        send_email(f"TRADE OPENED - {side.upper()}", f"XAUUSD {side.upper()}<br>Entry: ~{price:.2f}<br>SL: {sl:.2f}<br>TP: {tp:.2f}")
        return True, result.get("orderId")
    return False, None

# ==========================================
# INDICATORS
# ==========================================
def ema(s, p): return s.ewm(span=p, adjust=False).mean()
def atr(df, p=14):
    h = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([h, hc, lc], axis=1).max(axis=1)
    return tr.rolling(p).mean()
def vwap(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    df['day'] = df['time'].dt.date
    df['pv'] = tp * df["volume"]
    df['cum_pv'] = df.groupby('day')['pv'].cumsum()
    df['cum_vol'] = df.groupby('day')['volume'].cumsum()
    return df['cum_pv'] / df['cum_vol']

# ==========================================
# DASHBOARD
# ==========================================
app = Flask(__name__)
@app.route('/')
def dashboard():
    acc = get_account()
    if not acc:
        return "<h1>Connecting to FxOpen API...</h1><p>Bot is running, waiting for connection...</p>"
    return f"""
    <h1 style="color:green">FXOPEN BOT LIVE</h1>
    <h2>Balance: ${acc.get('balance',0):,.2f} | Equity: ${acc.get('equity',0):,.2f}</h2>
    <p>Symbol: {SYMBOL} | Time: {datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")}</p>
    <p>Bot Running 24/7 on Render.com (Free)</p>
    <hr>
    <pre>{open('latest_log.txt').read() if os.path.exists('latest_log.txt') else 'No logs yet...'}</pre>
    """
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

# ==========================================
# MAIN STRATEGY WITH DETAILED LOGS
# ==========================================
def log(msg):
    print(msg)
    with open("latest_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(SERVER_TZ).strftime('%H:%M:%S')} | {msg}\n")

def run_bot():
    log("FXOPEN XAUUSD BOT STARTED SUCCESSFULLY!")
    send_email("Bot Started", "Your XAUUSD bot is now LIVE on Render.com!")

    trades_today = 0
    last_trade_day = None
    cooldown = 0

    while True:
        try:
            ltf = get_candles(SYMBOL, ENTRY_TF, 500)
            htf = get_candles(SYMBOL, HTF_TF, 100)
            if not ltf or len(ltf) < 100:
                log("Not enough data, retrying...")
                time.sleep(CHECK_INTERVAL)
                continue

            # Indicators
            ltf["ema_fast"] = ema(ltf["close"], EMA_FAST)
            ltf["ema_slow"] = ema(ltf["close"], EMA_SLOW)
            ltf["atr"] = atr(ltf, ATR_PERIOD)
            ltf["vwap"] = vwap(ltf)

            c = ltf.iloc[-1]
            p = ltf.iloc[-2]
            htf_c = htf.iloc[-1]
            htf_p = htf.iloc[-2]

            # Conditions
            body_pct = abs(c["close"] - c["open"]) / (c["high"] - c["low"] + 1e-8)
            bull_candle = c["close"] > c["open"] and (body_pct >= MIN_BODY_PCT or not USE_BODY_FILTER)
            bear_candle = c["close"] < c["open"] and (body_pct >= MIN_BODY_PCT or not USE_BODY_FILTER)
            vol_ok = not USE_VOLUME_FILTER or c["volume"] >= p["volume"] * VOL_MULT
            trend_up = not USE_EMA_FILTER or (c["ema_fast"] > c["ema_slow"] and c["close"] > c["vwap"])
            trend_down = not USE_EMA_FILTER or (c["ema_fast"] < c["ema_slow"] and c["close"] < c["vwap"])
            htf_bull = htf_c["close"] > htf_c["open"]
            htf_bear = htf_c["close"] < htf_c["open"]

            today = datetime.now(SERVER_TZ).date()
            if last_trade_day != today:
                trades_today = 0
                last_trade_day = today
                cooldown = 0

            can_trade = cooldown == 0 and trades_today < MAX_TRADES_PER_DAY

            log(f"\n{'='*50}")
            log(f"NEW M5 CANDLE | {c['time'].strftime('%H:%M')} | Price: {c['close']:.2f}")
            log(f"Bull Candle: {'YES' if bull_candle else 'NO'} | Bear Candle: {'YES' if bear_candle else 'NO'}")
            log(f"Volume OK: {'YES' if vol_ok else 'NO'}")
            log(f"Trend Up: {'YES' if trend_up else 'NO'} | Trend Down: {'YES' if trend_down else 'NO'}")
            log(f"HTF Bias: {'BULLISH' if htf_bull else 'BEARISH'}")
            log(f"Can Trade: {'YES' if can_trade else 'NO'} (Trades: {trades_today}/{MAX_TRADES_PER_DAY})")

            if can_trade and bull_candle and trend_up and htf_bull and vol_ok:
                sl = htf_p["low"] - ltf["atr"].iloc[-1] * SL_ATR_BUFFER
                tp = c["close"] + (c["close"] - sl) * RISK_REWARD
                log(f"LONG SIGNAL! | SL: {sl:.2f} | TP: {tp:.2f}")
                success, _ = place_order("buy", LOT_SIZE, sl, tp)
                if success:
                    trades_today += 1
                    cooldown = COOLDOWN_BARS

            elif can_trade and bear_candle and trend_down and htf_bear and vol_ok:
                sl = htf_p["high"] + ltf["atr"].iloc[-1] * SL_ATR_BUFFER
                tp = c["close"] - (sl - c["close"]) * RISK_REWARD
                log(f"SHORT SIGNAL! | SL: {sl:.2f} | TP: {tp:.2f}")
                success, _ = place_order("sell", LOT_SIZE, sl, tp)
                if success:
                    trades_today += 1
                    cooldown = COOLDOWN_BARS
            else:
                log("No valid signal")

            if cooldown > 0:
                cooldown -= 1
                log(f"Cooldown: {cooldown} bars")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            log(f"ERROR: {e}")
            time.sleep(10)

run_bot()
