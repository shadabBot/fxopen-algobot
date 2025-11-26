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
import hmac
import hashlib
import base64
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# YOUR FXOPEN TICKTRADER DEMO CREDENTIALS
# ==========================================
TOKEN_ID = os.getenv("FXOPEN_TOKEN_ID")
TOKEN_KEY = os.getenv("FXOPEN_TOKEN_KEY")
TOKEN_SECRET = os.getenv("FXOPEN_TOKEN_SECRET")

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

# Email
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
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())
        print("Email sent:", subject)
    except Exception as e:
        print("Email failed:", e)

# ==========================================
# HMAC SIGNATURE GENERATION (FROM YOUR WEBSOCKET LOGS)
# ==========================================
def generate_hmac_signature(payload, timestamp):
    # Sort keys for consistent signature
    sorted_payload = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    message = str(timestamp) + sorted_payload
    signature = hmac.new(TOKEN_SECRET.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(signature).decode()

# ==========================================
# API WITH HMAC AUTH
# ==========================================
def api_request(method, endpoint, payload=None, params=None):
    url = BASE_URL + endpoint
    timestamp = int(time.time() * 1000)
    headers = {
        "Authorization": f"Bearer {TOKEN_ID}",
        "X-Token-Key": TOKEN_KEY,
        "X-Timestamp": str(timestamp),
        "Content-Type": "application/json"
    }
    if payload:
        headers["X-Signature"] = generate_hmac_signature(payload, timestamp)
    for i in range(6):
        try:
            r = requests.request(method, url, headers=headers, json=payload, params=params, timeout=20)
            if r.status_code in [200, 201]:
                return r.json()
            print(f"API {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"Retry {i+1}/6: {e}")
            time.sleep(5)
    return None

def get_account():
    data = api_request("GET", "/account")
    if data:
        print(f"Account OK | Balance: ${data.get('balance', 0):,.2f}")
    return data

def get_candles(symbol, tf, count=500):
    data = api_request("GET", f"/history/candles/{symbol}/{tf}", params={"count": count})
    if not data or "candles" not in data:
        return None
    df = pd.DataFrame(data["candles"])
    df["time"] = pd.to_datetime(df["time"], unit="s").dt.tz_localize("UTC").dt.tz_convert(SERVER_TZ)
    return df

def place_order(side, vol, sl=None, tp=None):
    payload = {
        "symbol": SYMBOL,
        "side": side,
        "volume": vol,
        "comment": "VWAP+EMA Bot"
    }
    if sl: payload["stopLoss"] = sl
    if tp: payload["takeProfit"] = tp
    result = api_request("POST", "/trading/orders/market", payload)
    if result and result.get("price"):
        price = result["price"]
        print(f"{side.upper()} ORDER @ {price:.5f}")
        send_email(f"TRADE {side.upper()}", f"XAUUSD {side.upper()}<br>Entry: {price:.5f}<br>SL: {sl:.5f}<br>TP: {tp:.5f}")
        return True
    print("Order failed:", result)
    return False

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

# ==========================================
# DASHBOARD
# ==========================================
app = Flask(__name__)
@app.route('/')
def dashboard():
    acc = get_account() or {}
    log = ""
    try:
        with open("log.txt", "r", encoding="utf-8") as f:
            log = f.read()[-3000:]
    except: pass
    return f"""
    <h1 style="color:#00ff00">FXOPEN BOT LIVE — 28503612</h1>
    <h2>Balance: ${acc.get('balance',0):,.2f} | Equity: ${acc.get('equity',0):,.2f}</h2>
    <p>XAUUSD • 1:500 • Gross • 24/7 Free</p>
    <p>{datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")}</p>
    <hr>
    <pre style="background:#000;color:#0f0;height:70vh;overflow:auto">{log or 'Connecting...'}</pre>
    """
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

def log(msg):
    t = datetime.now(SERVER_TZ).strftime("%H:%M:%S")
    print(t, "|", msg)
    with open("log.txt", "a", encoding="utf-8") as f:
        f.write(f"{t} | {msg}\n")

# ==========================================
# MAIN BOT LOOP
# ==========================================
def run_bot():
    log("FXOPEN TICKTRADER BOT STARTED — LOGIN 28503612")
    send_email("Bot Started", "Your XAUUSD bot is LIVE on Render.com!")

    trades_today = 0
    last_day = None
    cooldown = 0

    while True:
        try:
            acc = get_account()
            if not acc:
                log("Account not connected — retrying...")
                time.sleep(20)
                continue

            log(f"CONNECTED! Balance: ${acc['balance']:,.2f}")
            send_email("BOT LIVE", f"Balance: ${acc['balance']:,.2f} | Login: 28503612")

            trades_today = 0
            last_day = datetime.now(SERVER_TZ).date()
            cooldown = 0

            while True:
                ltf = get_candles(SYMBOL, ENTRY_TF, 300)
                htf = get_candles(SYMBOL, HTF_TF, 100)
                if not ltf or len(ltf) < 50:
                    log("Waiting for data...")
                    time.sleep(10)
                    continue

                ltf["ema_f"] = ema(ltf["close"], EMA_FAST)
                ltf["ema_s"] = ema(ltf["close"], EMA_SLOW)
                ltf["atr"] = atr(ltf, ATR_PERIOD)
                c = ltf.iloc[-1]
                h = htf.iloc[-1]
                h_prev = htf.iloc[-2]

                today = datetime.now(SERVER_TZ).date()
                if last_day != today:
                    trades_today = 0
                    last_day = today

                can_trade = cooldown == 0 and trades_today < 10

                log(f"\nNEW M5 | {c['time'].strftime('%H:%M')} | Price {c['close']:.5f}")
                log(f"EMA: {'UP' if c['ema_f'] > c['ema_s'] else 'DOWN'} | HTF: {'BULL' if h['close'] > h['open'] else 'BEAR'}")
                log(f"Candle: {'BULL' if c['close'] > c['open'] else 'BEAR'} | Body %: {abs(c['close'] - c['open']) / (c['high'] - c['low'] + 1e-8):.1%}")

                if can_trade and c['close'] > c['open'] and c['ema_f'] > c['ema_s'] and h['close'] > h['open']:
                    sl = h_prev['low'] - ltf['atr'].iloc[-1] * SL_ATR_BUFFER
                    tp = c['close'] + (c['close'] - sl) * RISK_REWARD
                    log(f"LONG → Entry ~{c['close']:.5f} | SL {sl:.5f} | TP {tp:.5f}")
                    if place_order("buy", LOT_SIZE, sl, tp):
                        trades_today += 1
                        cooldown = 10

                elif can_trade and c['close'] < c['open'] and c['ema_f'] < c['ema_s'] and h['close'] < h['open']:
                    sl = h_prev['high'] + ltf['atr'].iloc[-1] * SL_ATR_BUFFER
                    tp = c['close'] - (sl - c['close']) * RISK_REWARD
                    log(f"SHORT → Entry ~{c['close']:.5f} | SL {sl:.5f} | TP {tp:.5f}")
                    if place_order("sell", LOT_SIZE, sl, tp):
                        trades_today += 1
                        cooldown = 10
                else:
                    log("No signal")

                if cooldown > 0:
                    cooldown -= 1
                    log(f"Cooldown: {cooldown}")

                time.sleep(CHECK_INTERVAL)

        except Exception as e:
            log(f"Error: {e}")
            time.sleep(20)

run_bot()
