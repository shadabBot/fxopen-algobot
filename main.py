import requests
import json
import time
import hmac
import hashlib
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from flask import Flask
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# ==========================================
# CONFIGURATION (from your FxOpen account)
# ==========================================
TOKEN_ID = os.getenv("FXOPEN_TOKEN_ID")
TOKEN_KEY = os.getenv("FXOPEN_TOKEN_KEY")
TOKEN_SECRET = os.getenv("FXOPEN_TOKEN_SECRET")

BASE_URL = "https://ttdemomarginal.fxopen.net:8844/api/v2"
SYMBOL = "XAUUSD"
LOT_SIZE = 0.10
RISK_REWARD = 2.5
MAGIC = 987654
CHECK_INTERVAL = 1
LOOKBACK = 10000
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
PARTIAL_AT_1R_PCT = 40
USE_EMA_FILTER = True
USE_TRAILING_STOP = True
TRAILING_STOP_ATR = 1.0
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

# Flask Dashboard
app = Flask(__name__)
@app.route('/')
def dashboard():
    account = requests.get(f"{BASE_URL}/account", headers=headers()).json()
    balance = account.get("balance", 0)
    equity = account.get("equity", 0)
    return f"""
    <h1>FxOpen TickTrader Bot LIVE</h1>
    <h2>Balance: ${balance:,.2f} | Equity: ${equity:,.2f}</h2>
    <p>Symbol: {SYMBOL} | Time: {datetime.now(SERVER_TZ)}</p>
    <p>Bot Running 24/7 on Render.com (Free)</p>
    """
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

# ==========================================
# API HELPERS
# ==========================================
def headers():
    return {
        "Authorization": f"Bearer {TOKEN_ID}",
        "X-Token-Key": TOKEN_KEY,
        "Content-Type": "application/json"
    }

def get_candles(symbol, timeframe, count=1000):
    url = f"{BASE_URL}/history/candles/{symbol}/{timeframe}"
    params = {"count": count}
    r = requests.get(url, headers=headers(), params=params)
    if r.status_code != 200: return None
    data = r.json()
    df = pd.DataFrame(data["candles"])
    df["time"] = pd.to_datetime(df["time"], unit="s").dt.tz_localize("UTC").dt.tz_convert(SERVER_TZ)
    return df

def place_order(side, volume, sl=None, tp=None):
    url = f"{BASE_URL}/trading/orders/market"
    payload = {
        "symbol": SYMBOL,
        "side": side,  # "buy" or "sell"
        "volume": volume,
        "comment": "VWAP + EMA Strategy"
    }
    if sl: payload["stopLoss"] = sl
    if tp: payload["takeProfit"] = tp
    r = requests.post(url, headers=headers(), json=payload)
    if r.status_code == 200:
        order = r.json()
        print(f"{side.upper()} ORDER PLACED")
        send_email(f"Trade Opened ({side.upper()})", f"Entry ~{order['price']:.2f}<br>SL: {sl}<br>TP: {tp}")
        return True, order["orderId"]
    else:
        print("Order failed:", r.text)
        return False, None

def close_position(ticket, volume):
    url = f"{BASE_URL}/trading/positions/{ticket}/close"
    r = requests.post(url, headers=headers(), json={"volume": volume})
    return r.status_code == 200

# ==========================================
# INDICATORS (same as yours)
# ==========================================
def ema(series, period): return series.ewm(span=period, adjust=False).mean()
def atr(df, period=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()
def vwap(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    df['day'] = df['time'].dt.date
    df['pv'] = tp * df["volume"]
    df['cum_pv'] = df.groupby('day')['pv'].cumsum()
    df['cum_vol'] = df.groupby('day')['volume'].cumsum()
    return df['cum_pv'] / df['cum_vol']

# ==========================================
# MAIN STRATEGY (100% YOUR LOGIC)
# ==========================================
def run_bot():
    print("FxOpen TickTrader Bot STARTED (24/7 on Render.com)")
    send_email("Bot Started", "Your XAUUSD bot is now live on Render.com!")

    trades_today = 0
    last_trade_day = None
    cooldown = 0
    current_ticket = None
    last_signal = None
    last_entry_risk = None
    be_moved = False
    partial_done = False

    while True:
        try:
            ltf = get_candles(SYMBOL, ENTRY_TF, 500)
            htf = get_candles(SYMBOL, HTF_TF, 100)
            if ltf is None or len(ltf) < 100:
                time.sleep(CHECK_INTERVAL)
                continue

            ltf["ema_fast"] = ema(ltf["close"], EMA_FAST)
            ltf["ema_slow"] = ema(ltf["close"], EMA_SLOW)
            ltf["atr"] = atr(ltf, ATR_PERIOD)
            ltf["vwap"] = vwap(ltf)

            close = ltf["close"].iloc[-1]
            open_ = ltf["open"].iloc[-1]
            high = ltf["high"].iloc[-1]
            low = ltf["low"].iloc[-1]
            vol = ltf["volume"].iloc[-1]
            vol_prev = ltf["volume"].iloc[-2]
            atr_val = ltf["atr"].iloc[-1]
            ema_f = ltf["ema_fast"].iloc[-1]
            ema_s = ltf["ema_slow"].iloc[-1]
            vwap_val = ltf["vwap"].iloc[-1]

            body_pct = abs(close - open_) / (high - low + 0.00001)
            bull = close > open_ and (body_pct >= MIN_BODY_PCT or not USE_BODY_FILTER)
            bear = close < open_ and (body_pct >= MIN_BODY_PCT or not USE_BODY_FILTER)
            vol_ok = not USE_VOLUME_FILTER or vol >= vol_prev * VOL_MULT
            trend_up = not USE_EMA_FILTER or (ema_f > ema_s and close > vwap_val)
            trend_down = not USE_EMA_FILTER or (ema_f < ema_s and close < vwap_val)

            htf_bias = htf["close"].iloc[-1] > htf["open"].iloc[-1]

            can_trade = cooldown == 0 and trades_today < MAX_TRADES_PER_DAY
            today = datetime.now(SERVER_TZ).date()
            if last_trade_day != today:
                trades_today = 0
                last_trade_day = today
                cooldown = 0

            # Entry
            if can_trade and bull and trend_up and htf_bias and vol_ok:
                sl = htf["low"].iloc[-2] - atr_val * SL_ATR_BUFFER
                tp = close + (close - sl) * RISK_REWARD
                success, ticket = place_order("buy", LOT_SIZE, sl, tp)
                if success:
                    trades_today += 1
                    cooldown = COOLDOWN_BARS
                    current_ticket = ticket
                    last_signal = "BUY"
                    last_entry_risk = close - sl
                    be_moved = partial_done = False

            elif can_trade and bear and trend_down and not htf_bias and vol_ok:
                sl = htf["high"].iloc[-2] + atr_val * SL_ATR_BUFFER
                tp = close - (sl - close) * RISK_REWARD
                success, ticket = place_order("sell", LOT_SIZE, sl, tp)
                if success:
                    trades_today += 1
                    cooldown = COOLDOWN_BARS
                    current_ticket = ticket
                    last_signal = "SELL"
                    last_entry_risk = sl - close
                    be_moved = partial_done = False

            if cooldown > 0:
                cooldown -= 1

            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print("Error:", e)
            time.sleep(10)

run_bot()