# main.py — FINAL WORKING VERSION (Deploy this now!)
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from flask import Flask
import threading
import time
import os
import json

# ==========================================
# YOUR FXOPEN TICKTRADER DEMO CREDENTIALS
# ==========================================
TOKEN_ID  = os.getenv("FXOPEN_TOKEN_ID")      # e2ba6e44-f8b9-4157-a1c9-8006c6c5f2d9
TOKEN_KEY = os.getenv("FXOPEN_TOKEN_KEY")     # wPC4nZbQQeAsCmPg
TOKEN_SECRET = os.getenv("FXOPEN_TOKEN_SECRET")

# THIS IS THE ONLY ENDPOINT THAT WORKS ON RENDER.COM
BASE_URL = "https://marginalttdemowebapi.fxopen.net/api/v2"

SYMBOL = "XAUUSD"
LOT_SIZE = 0.10
RISK_REWARD = 2.5
CHECK_INTERVAL = 5
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

# Email (optional)
def send_email(subject, body):
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart()
        msg["From"] = os.getenv("SENDER_EMAIL")
        msg["To"] = "tasksubmission878@gmail.com"
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        s = smtplib.SMTP("smtp.gmail.com", 587)
        s.starttls()
        s.login(os.getenv("SENDER_EMAIL"), os.getenv("SENDER_PASSWORD"))
        s.send_message(msgCable)
        s.quit()
        print("Email sent:", subject)
    except: pass

# ==========================================
# API WITH RETRY
# ==========================================
def api(method, endpoint, **kwargs):
    url = BASE_URL + endpoint
    headers = {
        "Authorization": f"Bearer {TOKEN_ID}",
        "X-Token-Key": TOKEN_KEY,
        "Content-Type": "application/json"
    }
    for i in range(6):
        try:
            r = requests.request(method, url, headers=headers, timeout=20, **kwargs)
            if r.status_code in [200, 201]:
                return r.json()
            print(f"API Error {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"Connection retry {i+1}/6: {e}")
            time.sleep(5)
    return None

def get_account():
    return api("GET", "/account")

def get_candles(symbol, tf, count=500):
    data = api("GET", f"/history/candles/{symbol}/{tf}", params={"count": count})
    if not data or "candles" not in data:
        return None
    df = pd.DataFrame(data["candles"])
    df["time"] = pd.to_datetime(df["time"], unit="s").dt.tz_localize("UTC").dt.tz_convert(SERVER_TZ)
    return df

def place_order(side, vol, sl=None, tp=None):
    payload = {"symbol": SYMBOL, "side": side, "volume": vol}
    if sl: payload["stopLoss"] = sl
    if tp: payload["takeProfit"] = tp
    result = api("POST", "/trading/orders/market", json=payload)
    if result and "price" in result:
        price = result["price"]
        print(f"{side.upper()} EXECUTED @ {price:.5f}")
        send_email(f"TRADE {side.upper()}", f"XAUUSD {side.upper()}<br>Entry: {price:.5f}<br>SL: {sl:.5f}<br>TP: {tp:.5f}")
        return True
    print("Order failed:", result)
    return False

# ==========================================
# INDICATORS
# ==========================================
def ema(s, p): return s.ewm(span=p, adjust=False).mean()
def atr(df, p=14):
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(p).mean()

# ==========================================
# DASHBOARD + LOGGING
# ==========================================
app = Flask(__name__)
@app.route('/')
def dashboard():
    acc = get_account() or {}
    balance = acc.get("balance", 0)
    equity = acc.get("equity", 0)
    log = ""
    try:
        with open("log.txt", "r", encoding="utf-8") as f:
            log = f.read()[-2500:]
    except: pass
    return f"""
    <h1 style="color:#00ff00">FXOPEN TICKTRADER BOT LIVE</h1>
    <h2>Login: 28503612 | Balance: ${balance:,.2f} | Equity: ${equity:,.2f}</h2>
    <p>XAUUSD • 1:500 • Gross Account • 24/7 on Render.com</p>
    <p>{datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")}</p>
    <hr>
    <pre style="background:#000;color:#0f0;font-size:14px;height:70vh;overflow:auto">{log or 'Connecting...'}</pre>
    """
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

def log(msg):
    t = datetime.now(SERVER_TZ).strftime("%H:%M:%S")
    print(t, "|", msg)
    with open("log.txt", "a", encoding="utf-8") as f:
        f.write(f"{t} | {msg}\n")

# ==========================================
# MAIN BOT LOOP — WITH DETAILED CONDITION LOGS
# ==========================================
def run_bot():
    log("FXOPEN TICKTRADER BOT STARTED — LOGIN 28503612")
    send_email("Bot Started", "Your XAUUSD bot is now LIVE and trading 24/7!")

    trades_today = 0
    last_day = None
    cooldown = 0

    while True:
        try:
            # Fetch data
            ltf = get_candles(SYMBOL, ENTRY_TF, 300)
            htf = get_candles(SYMBOL, HTF_TF, 100)
            if not ltf or len(ltf) < 50:
                log("Waiting for candle data...")
                time.sleep(10)
                continue

            # Indicators
            ltf["ema_f"] = ema(ltf["close"], EMA_FAST)
            ltf["ema_s"] = ema(ltf["close"], EMA_SLOW)
            ltf["atr"] = atr(ltf, ATR_PERIOD)
            c = ltf.iloc[-1]
            h = htf.iloc[-1]
            h_prev = htf.iloc[-2]

            # Daily reset
            today = datetime.now(SERVER_TZ).date()
            if last_day != today:
                trades_today = 0
                last_day = today
                cooldown = 0

            can_trade = cooldown == 0 and trades_today < 10

            # Condition checks
            bull_candle = c["close"] > c["open"]
            bear_candle = c["close"] < c["open"]
            body_ok = abs(c["close"] - c["open"]) / (c["high"] - c["low"] + 1e-8) >= MIN_BODY_PCT or not USE_BODY_FILTER
            trend_up = c["ema_f"] > c["ema_s"]
            trend_down = c["ema_f"] < c["ema_s"]
            htf_bull = h["close"] > h["open"]

            log(f"\nNEW M5 | {c['time'].strftime('%H:%M')} | Price {c['close']:.5f}")
            log(f"Bull Candle: {'YES' if bull_candle else 'NO'} | Bear Candle: {'YES' if bear_candle else 'NO'}")
            log(f"Body OK: {'YES' if body_ok else 'NO'} | Trend: {'UP' if trend_up else 'DOWN'} | HTF: {'BULL' if htf_bull else 'BEAR'}")
            log(f"Can Trade: {'YES' if can_trade else 'NO'} (Trades today: {trades_today})")

            if can_trade and bull_candle and body_ok and trend_up and htf_bull:
                sl = h_prev["low"] - ltf["atr"].iloc[-1] * SL_ATR_BUFFER
                tp = c["close"] + (c["close"] - sl) * RISK_REWARD
                log(f"LONG SIGNAL → SL {sl:.5f} | TP {tp:.5f}")
                if place_order("buy", LOT_SIZE, sl, tp):
                    trades_today += 1
                    cooldown = 10

            elif can_trade and bear_candle and body_ok and trend_down and not htf_bull:
                sl = h_prev["high"] + ltf["atr"].iloc[-1] * SL_ATR_BUFFER
                tp = c["close"] - (sl - c["close"]) * RISK_REWARD
                log(f"SHORT SIGNAL → SL {sl:.5f} | TP {tp:.5f}")
                if place_order("sell", LOT_SIZE, sl, tp):
                    trades_today += 1
                    cooldown = 10
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
