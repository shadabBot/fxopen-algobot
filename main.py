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
# YOUR EXACT FXOPEN TICKTRADER DEMO CREDENTIALS
# ==========================================
TOKEN_ID     = "e2ba6e44-f8b9-4157-a1c9-8006c6c5f2d9"
TOKEN_KEY    = "wPC4nZbQQeAsCmPg"
TOKEN_SECRET = "9yYkYHsBK4Pr4W3kf6R4ry2aX2w3dp8txZDQfzxxFXKaHB2zDME8Sg4KGYz8mByx"

BASE_URL = "https://ticktrader-api.fxopen.com/api/v2"   # THIS WORKS ON RENDER.COM

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
def send_email(subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = os.getenv("SENDER_EMAIL", "sayedshadabali8421@gmail.com")
        msg["To"] = ", ".join(["tasksubmission878@gmail.com", "eventshadab@gmail.com"])
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(msg["From"], os.getenv("SENDER_PASSWORD", "eynj eiip itff nbga"))
        server.send_message(msg)
        server.quit()
        print("Email sent:", subject)
    except Exception as e:
        print("Email failed:", e)

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
    for i in range(5):
        try:
            r = requests.request(method, url, headers=headers, timeout=15, **kwargs)
            if r.status_code in [200, 201]:
                return r.json()
            print(f"API {r.status_code}: {r.text}")
        except Exception as e:
            print(f"Retry {i+1}: {e}")
            time.sleep(3)
    return None

def account_info():
    return api("GET", "/account")

def candles(symbol, tf, count=500):
    data = api("GET", f"/history/candles/{symbol}/{tf}", params={"count": count})
    if not data or "candles" not in data: return None
    df = pd.DataFrame(data["candles"])
    df["time"] = pd.to_datetime(df["time"], unit="s").dt.tz_localize("UTC").dt.tz_convert(SERVER_TZ)
    return df

def trade(side, vol, sl=None, tp=None):
    payload = {"symbol": SYMBOL, "side": side, "volume": vol}
    if sl: payload["stopLoss"] = sl
    if tp: payload["takeProfit"] = tp
    r = api("POST", "/trading/orders/market", json=payload)
    if r and r.get("price"):
        price = r["price"]
        print(f"{side.upper()} EXECUTED @ {price}")
        send_email(f"TRADE {side.upper()}", f"XAUUSD {side.upper()}<br>Entry: {price}<br>SL: {sl}<br>TP: {tp}")
        return True
    return False

# ==========================================
# DASHBOARD + LIVE LOG
# ==========================================
app = Flask(__name__)
@app.route('/')
def dashboard():
    info = account_info() or {}
    log = ""
    try:
        with open("log.txt", "r", encoding="utf-8") as f:
            log = f.read()[-3000:]
    except: pass
    return f"""
    <h1 style="color:#00ff41">FXOPEN TICKTRADER BOT LIVE</h1>
    <h2>Login: 28503612 | Balance: ${info.get('balance',0):,.2f} | Equity: ${info.get('equity',0):,.2f}</h2>
    <p>XAUUSD • Leverage 1:500 • Gross Account</p>
    <p>{datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")}</p>
    <hr>
    <pre style="background:black;color:lime;height:70vh;overflow:auto">{log or 'Starting...'}</pre>
    """
threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": 10000}, daemon=True).start()

# ==========================================
# LOGGING & INDICATORS
# ==========================================
def log(msg):
    t = datetime.now(SERVER_TZ).strftime("%H:%M:%S")
    print(t, "|", msg)
    with open("log.txt", "a", encoding="utf-8") as f:
        f.write(f"{t} | {msg}\n")

def ema(s, p): return s.ewm(span=p, adjust=False).mean()
def atr(df): return (df["high"] - df["low"]).rolling(14).mean()

# ==========================================
# MAIN BOT LOOP
# ==========================================
log("FXOPEN TICKTRADER BOT STARTED — LOGIN 28503612")
send_email("Bot Started", "Your XAUUSD bot is LIVE on Render.com!<br>Login: 28503612<br>Server: ttdemomarginal.fxopen.net")

trades_today = 0
last_day = None
cooldown = 0

while True:
    try:
        ltf = candles(SYMBOL, ENTRY_TF, 300)
        htf = candles(SYMBOL, HTF_TF, 100)
        if not ltf or len(ltf) < 50:
            log("Waiting for candles...")
            time.sleep(10)
            continue

        ltf["ema_f"] = ema(ltf["close"], EMA_FAST)
        ltf["ema_s"] = ema(ltf["close"], EMA_SLOW)
        ltf["atr"] = atr(ltf)
        c = ltf.iloc[-1]
        h = htf.iloc[-1]
        h_prev = htf.iloc[-2]

        today = datetime.now(SERVER_TZ).date()
        if last_day != today:
            trades_today = 0
            last_day = today
            cooldown = 0

        can_trade = cooldown == 0 and trades_today < 10

        log(f"\nNEW M5 | {c['time'].strftime('%H:%M')} | Price {c['close']:.2f}")
        log(f"EMA: {'UP' if c['ema_f']>c['ema_s'] else 'DOWN'} | HTF: {'BULL' if h['close']>h['open'] else 'BEAR'}")

        if can_trade and c["close"] > c["open"] and c["ema_f"] > c["ema_s"] and h["close"] > h["open"]:
            sl = h_prev["low"] - ltf["atr"].iloc[-1] * SL_ATR_BUFFER
            tp = c["close"] + (c["close"] - sl) * RISK_REWARD
            log(f"LONG SIGNAL → SL {sl:.2f} | TP {tp:.2f}")
            if trade("buy", LOT_SIZE, sl, tp):
                trades_today += 1
                cooldown = 10

        elif can_trade and c["close"] < c["open"] and c["ema_f"] < c["ema_s"] and h["close"] < h["open"]:
            sl = h_prev["high"] + ltf["atr"].iloc[-1] * SL_ATR_BUFFER
            tp = c["close"] - (sl - c["close"]) * RISK_REWARD
            log(f"SHORT SIGNAL → SL {sl:.2f} | TP {tp:.2f}")
            if trade("sell", LOT_SIZE, sl, tp):
                trades_today += 1
                cooldown = 10
        else:
            log("No signal")

        if cooldown > 0: cooldown -= 1
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        log(f"ERROR: {e}")
        time.sleep(10)
