import websocket
import json
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
import hmac
import hashlib
import base64

# ==========================================
# YOUR FXOPEN WEBSOCKET CREDENTIALS
# ==========================================
WEB_SOCKET_URL = "wss://marginalttdemowebapi.fxopen.net/trade"
TOKEN_ID = os.getenv("FXOPEN_TOKEN_ID")
TOKEN_KEY = os.getenv("FXOPEN_TOKEN_KEY")
TOKEN_SECRET = os.getenv("FXOPEN_TOKEN_SECRET")

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
# HMAC SIGNATURE (FROM YOUR WEBSOCKET LOGS)
# ==========================================
def generate_signature(params):
    timestamp = int(time.time() * 1000)
    params["Timestamp"] = timestamp
    message = json.dumps(params, separators=(',', ':'), sort_keys=True)
    signature = hmac.new(TOKEN_SECRET.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(signature).decode(), timestamp

# ==========================================
# WEBSOCKET CLASS (REALTIME BALANCE + CANDLES)
# ==========================================
class FxOpenWebSocket:
    def __init__(self):
        self.ws = None
        self.connected = False
        self.account_info = {}
        self.candles = {}
        self.balance = 0

    def connect(self):
        self.ws = websocket.WebSocketApp(WEB_SOCKET_URL,
                                         on_message=self.on_message,
                                         on_error=self.on_error,
                                         on_close=self.on_close,
                                         on_open=self.on_open)
        self.ws.run_forever()

    def on_open(self, ws):
        print("WebSocket connected!")
        self.connected = True
        # Login (exact from your console logs)
        params = {
            "AuthType": "HMAC",
            "WebApiId": TOKEN_ID,
            "WebApiKey": TOKEN_KEY,
            "DeviceId": "RenderBot",
            "AppSessionId": "123"
        }
        sig, ts = generate_signature(params)
        params["Signature"] = sig
        params["Timestamp"] = ts
        ws.send(json.dumps({"Id": "login1", "Request": "Login", "Params": params}))

    def on_message(self, ws, message):
        data = json.loads(message)
        print("WS Message:", data)
        if "Response" in data:
            if data["Response"] == "Login" and data["Result"]["Info"] == "ok":
                print("LOGIN SUCCESS — Account 28503612 connected!")
                self.get_account_info()
                self.get_candles(SYMBOL, ENTRY_TF, 300)
                self.get_candles(SYMBOL, HTF_TF, 100)
            elif data["Response"] == "TradeSessionInfo":
                print("Session opened — Ready to trade!")
            elif data["Response"] == "AccountInfo":
                self.account_info = data["Result"]
                self.balance = data["Result"]["balance"]
                print(f"Balance updated: ${self.balance:,.2f}")
            elif data["Response"] == "Candles":
                self.candles[data["Params"]["symbol"]] = data["Result"]["candles"]
        with open("ws_log.txt", "a") as f:
            f.write(f"{datetime.now()}: {message}\n")

    def on_error(self, ws, error):
        print(f"WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print("WebSocket closed — Reconnecting...")
        self.connected = False
        time.sleep(5)
        self.connect()

    def get_account_info(self):
        self.ws.send(json.dumps({"Id": "acc1", "Request": "AccountInfo"}))

    def get_candles(self, symbol, tf, count):
        self.ws.send(json.dumps({"Id": f"c{time.time()}", "Request": "Candles", "Params": {"symbol": symbol, "timeframe": tf, "count": count}}))

    def send_order(self, side, vol, sl=None, tp=None):
        if not self.connected:
            return False
        payload = {
            "Id": f"o{time.time()}",
            "Request": "PlaceOrder",
            "Params": {
                "symbol": SYMBOL,
                "side": side,
                "volume": vol,
                "type": "market",
                "comment": "VWAP+EMA Bot"
            }
        }
        if sl: payload["Params"]["stopLoss"] = sl
        if tp: payload["Params"]["takeProfit"] = tp
        self.ws.send(json.dumps(payload))
        return True

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
    ws = FxOpenWebSocket()
    ws.connect()
    time.sleep(2)
    balance = ws.account_info.get("balance", 0)
    equity = ws.account_info.get("equity", 0)
    log = ""
    try:
        with open("log.txt", "r") as f:
            log = f.read()[-3000:]
    except: pass
    return f"""
    <h1 style="color:lime">FXOPEN WEBSOCKET BOT LIVE</h1>
    <h2>Login: 28503612 | Balance: ${balance:,.2f} | Equity: ${equity:,.2f}</h2>
    <p>XAUUSD • 1:500 • Gross • 24/7 Free</p>
    <p>{datetime.now(SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")}</p>
    <hr>
    <pre style="background:black;color:lime;height:70vh;overflow:auto">{log or 'Connecting...'}</pre>
    """
threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()

def log(msg):
    t = datetime.now(SERVER_TZ).strftime("%H:%M:%S")
    print(t, "|", msg)
    with open("log.txt", "a") as f:
        f.write(f"{t} | {msg}\n")

# ==========================================
# MAIN BOT LOOP
# ==========================================
def run_bot():
    log("FXOPEN WEBSOCKET BOT STARTED — LOGIN 28503612")
    send_email("Bot Started", "Your XAUUSD bot is LIVE via WebSocket!")

    ws = FxOpenWebSocket()
    ws.connect()

    trades_today = 0
    last_day = None
    cooldown = 0

    while True:
        try:
            if not ws.connected:
                log("WebSocket disconnected — reconnecting...")
                ws.connect()
                time.sleep(5)
                continue

            # Get candles (from WebSocket cache)
            ltf_candles = ws.candles.get(SYMBOL, [])
            if len(ltf_candles) < 50:
                ws.get_candles(SYMBOL, ENTRY_TF, 300)
                time.sleep(2)
                continue

            htf_candles = ws.candles.get(SYMBOL, [])
            if len(htf_candles) < 10:
                ws.get_candles(SYMBOL, HTF_TF, 100)
                time.sleep(2)
                continue

            # Convert to DataFrame
            ltf = pd.DataFrame(ltf_candles[-LOOKBACK:])
            ltf["time"] = pd.to_datetime(ltf["time"])
            htf = pd.DataFrame(htf_candles[-LOOKBACK//6:])

            ltf["ema_f"] = ema(ltf["close"], EMA_FAST)
            ltf["ema_s"] = ema(ltf["close"], EMA_SLOW)
            ltf["atr"] = atr(ltf, ATR_PERIOD)

            c = ltf.iloc[-1]
            p = ltf.iloc[-2]
            h = htf.iloc[-1]
            h_prev = htf.iloc[-2]

            today = datetime.now(SERVER_TZ).date()
            if last_day != today:
                trades_today = 0
                last_day = today
                cooldown = 0

            can_trade = cooldown == 0 and trades_today < 10

            log(f"\nNEW M5 | {c['time'].strftime('%H:%M')} | Price {c['close']:.5f}")
            log(f"EMA: {'UP' if c['ema_f'] > c['ema_s'] else 'DOWN'} | HTF: {'BULL' if h['close'] > h['open'] else 'BEAR'}")
            log(f"Candle: {'BULL' if c['close'] > c['open'] else 'BEAR'} | Body %: {abs(c['close'] - c['open']) / (c['high'] - c['low'] + 1e-8):.1%}")

            if can_trade and c['close'] > c['open'] and c['ema_f'] > c['ema_s'] and h['close'] > h['open']:
                sl = h_prev['low'] - c['atr'] * SL_ATR_BUFFER
                tp = c['close'] + (c['close'] - sl) * RISK_REWARD
                log(f"LONG SIGNAL → SL {sl:.5f} | TP {tp:.5f}")
                if ws.send_order("buy", LOT_SIZE, sl, tp):
                    trades_today += 1
                    cooldown = 10

            elif can_trade and c['close'] < c['open'] and c['ema_f'] < c['ema_s'] and h['close'] < h['open']:
                sl = h_prev['high'] + c['atr'] * SL_ATR_BUFFER
                tp = c['close'] - (sl - c['close']) * RISK_REWARD
                log(f"SHORT SIGNAL → SL {sl:.5f} | TP {tp:.5f}")
                if ws.send_order("sell", LOT_SIZE, sl, tp):
                    trades_today += 1
                    cooldown = 10
            else:
                log("No signal")

            if cooldown > 0:
                cooldown -= 1
                log(f"Cooldown: {cooldown}")

            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            log(f"ERROR: {e}")
            time.sleep(10)

run_bot()
