# -*- coding: utf-8 -*-
"""
prices.py — Catégories, timeframes et données temps réel.
Sources : Pocket Option (SSID + public), Binance, Yahoo Finance.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx
import yfinance as yf

import pocket_option

log = logging.getLogger("prices")

# ---------------- Configuration ----------------
PO_ENABLED = os.getenv("PO_ENABLED", "0") == "1"
PO_QUOTES_URL = "https://api-tv.po.market/api/quotes/market/getRealTimeQuotes"
PO_CHART_URL = "https://api-tv.po.market/api/chart/history"
PO_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Origin": "https://pocketoption.com",
    "Referer": "https://pocketoption.com/",
}
BINANCE_API = "https://api.binance.com/api/v3"

# ---------------- Timeframes ----------------
TIMEFRAMES = ["S3", "S5", "S10", "S15", "S30", "M1", "M3", "M5", "M15", "M30", "H1"]


def tf_seconds(tf: str) -> int:
    """Convertit un timeframe en secondes (S5->5, M5->300, H1->3600)."""
    tf = tf.strip().upper()
    unit, val = tf[0], int(tf[1:])
    if unit == "S":
        return val
    if unit == "H":
        return val * 3600
    return val * 60


# ---------------- Catégories de paires ----------------
CATEGORIES = {
    "forex_major": {
        "label": "🏦 Forex Majeures",
        "symbols": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"],
    },
    "forex_minor": {
        "label": "💱 Forex Mineures / Croisées",
        "symbols": ["EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF", "GBPAUD",
                    "NZDJPY", "CADJPY", "EURNZD", "GBPCAD", "CHFJPY", "AUDNZD",
                    "EURAUD", "EURCAD", "EURSGD", "EURNOK", "EURSEK", "EURTRY",
                    "GBPCHF", "GBPNZD", "GBPSGD", "AUDCHF", "AUDCAD", "AUDSGD",
                    "CADCHF", "CADSGD", "NZDCHF", "NZDCAD", "USDSGD", "USDNOK",
                    "USDSEK", "USDDKK", "USDZAR", "USDMXN", "USDTRY", "USDPLN",
                    "USDHKD", "USDCNH"],
    },
    "crypto": {
        "label": "🪙 Cryptomonnaies",
        "symbols": ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LTC",
                    "DOT", "LINK", "AVAX", "MATIC", "SHIB", "UNI", "ATOM", "XLM",
                    "TRX", "PEPE", "NEAR", "SUI", "TON", "ARB", "OP", "APT", "INJ",
                    "FIL", "BCH", "XMR", "ZEC", "DASH", "EOS", "ALGO", "VET", "ICP",
                    "HBAR", "AAVE", "SAND", "MANA", "GALA", "AXS", "CHZ", "GRT",
                    "MKR", "LDO", "RUNE", "CRV", "STX", "SEI", "WLD", "JUP", "RNDR",
                    "FET", "ONDO", "IMX", "BONK", "FLOKI", "WIF", "CRO"],
    },
    "commodity": {
        "label": "🛢 Matières Premières",
        "symbols": ["XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD", "USOIL", "BRENT",
                    "XNGUSD", "XCUUSD", "XALUSD", "XNIUSD", "XZNUSD", "XPBUSD",
                    "COFFEE", "SUGAR", "COCOA"],
    },
}

# Correspondance matières premières -> symboles Yahoo (futures, secours)
COMMODITY_YAHOO = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "XPTUSD": "PL=F", "XPDUSD": "PA=F",
    "USOIL": "CL=F", "BRENT": "BZ=F", "XNGUSD": "NG=F", "XCUUSD": "HG=F",
    "XALUSD": "ALI=F", "COFFEE": "KC=F", "SUGAR": "SB=F", "COCOA": "CC=F",
}

MARKET_EMOJI = {"crypto": "🪙", "forex": "💱", "commodity": "🛢", "stock": "📈"}


def category_market(cat: str) -> str:
    """Déduit le marché depuis la catégorie."""
    if cat in ("forex_major", "forex_minor"):
        return "forex"
    if cat == "crypto":
        return "crypto"
    return "commodity"


def po_symbol(symbol: str, market: str) -> str:
    """Nom du symbole côté Pocket Option."""
    if market == "crypto":
        return symbol + "USD"
    return symbol  # forex (EURUSD) et matières premières (XAUUSD, USOIL…)


def po_ssid_enabled() -> bool:
    return pocket_option.ssid_enabled()


# ---------------- Utilitaires ----------------
def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).replace(",", ".").replace("%", "").replace("+", "").replace("$", "").strip()
        return float(s)
    except Exception:
        return None


def _pick(d, *keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def _extract_quote(payload):
    if isinstance(payload, list):
        return payload[0] if payload else None
    if isinstance(payload, dict):
        for key in ("data", "quotes", "result", "quote"):
            v = payload.get(key)
            if isinstance(v, list) and v:
                return v[0]
            if isinstance(v, dict):
                return v
        return payload
    return None


# ---------------- Normalisation (commandes rapides) ----------------
def normalize(raw):
    s = (raw or "").strip().upper().replace("$", "").replace("/", "").replace(" ", "")
    if s.endswith("USDT") and len(s) > 4:
        s = s[:-4]
    elif s.endswith("USDC") and len(s) > 4:
        s = s[:-4]
    if s in CATEGORIES["crypto"]["symbols"]:
        return s, "crypto"
    if s in CATEGORIES["forex_major"]["symbols"] or s in CATEGORIES["forex_minor"]["symbols"]:
        return s, "forex"
    if s in CATEGORIES["commodity"]["symbols"]:
        return s, "commodity"
    if len(s) == 6 and s[:3] in _CURRENCIES and s[3:] in _CURRENCIES:
        return s, "forex"
    if 1 < len(s) <= 6:
        return s, "stock"
    return s, "stock"


_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "CNY",
               "MXN", "SGD", "HKD", "ZAR", "SEK", "NOK", "TRY", "PLN", "INR"}


# ---------------- Pocket Option : cotation publique ----------------
async def _po_quote(sym, market):
    po = po_symbol(sym, market)
    try:
        async with httpx.AsyncClient(timeout=8, headers=PO_HEADERS) as client:
            r = await client.get(PO_QUOTES_URL, params={"symbol": po})
            r.raise_for_status()
            q = _extract_quote(r.json())
        price = _num(_pick(q, "price", "last", "close", "last_price", "value"))
        if price is None:
            return None
        return {
            "symbol": sym, "market": market, "price": price,
            "change": _num(_pick(q, "change", "change_24h")),
            "change_pct": _num(_pick(q, "percent", "change_percent", "changePercent")),
            "high": _num(_pick(q, "high", "high_price", "day_high")),
            "low": _num(_pick(q, "low", "low_price", "day_low")),
            "volume": _num(_pick(q, "volume", "quote_volume", "volume_24h")),
            "source": "Pocket Option",
        }
    except Exception as exc:
        log.warning("Pocket Option cotation échec (%s) : %s", po, exc)
        return None


async def _po_public_ohlc(po_symbol_name, tf_label):
    tf_map = {"M1": "M1", "M3": "M3", "M5": "M5", "M15": "M15",
              "M30": "M30", "H1": "H1"}
    po_tf = tf_map.get(tf_label.upper())
    if not po_tf:
        return []
    try:
        async with httpx.AsyncClient(timeout=10, headers=PO_HEADERS) as client:
            r = await client.get(PO_CHART_URL, params={
                "symbol": po_symbol_name, "timeframe": po_tf, "limit": 160,
            })
            r.raise_for_status()
            payload = r.json()
        rows = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(rows, list) and rows:
            if isinstance(rows[0], dict):
                return [(float(x["open"]), float(x["high"]),
                         float(x["low"]), float(x["close"]))
                        for x in rows
                        if all(k in x for k in ("open", "high", "low", "close"))]
            if isinstance(rows[0], list):
                return [(float(x[1]), float(x[2]), float(x[3]), float(x[4]))
                        for x in rows if len(x) >= 5]
        return []
    except Exception as exc:
        log.warning("Pocket Option graphique échec : %s", exc)
        return []


# ---------------- Binance (crypto, secours) ----------------
_BINANCE_TF = {60: "1m", 180: "3m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h"}


async def _binance_ohlc(symbol, tf_sec, limit=160):
    iv = _BINANCE_TF.get(tf_sec)
    if not iv:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{BINANCE_API}/klines", params={
                "symbol": symbol, "interval": iv, "limit": limit,
            })
            r.raise_for_status()
            rows = r.json()
        return [(float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in rows]
    except Exception as exc:
        log.warning("Binance klines échec (%s) : %s", symbol, exc)
        return []


# ---------------- Yahoo Finance (forex / matières premières, secours) ----------------
_YAHOO_TF = {60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "60m"}


def _yahoo_name(symbol, market):
    if market == "commodity":
        return COMMODITY_YAHOO.get(symbol, symbol)
    if market == "stock":
        return symbol
    if market == "forex":
        return symbol + "=X"
    return symbol + "-USD"


async def _yahoo_ohlc(symbol, market, tf_sec):
    iv = _YAHOO_TF.get(tf_sec)
    if not iv:
        return []
    name = _yahoo_name(symbol, market)

    def _work():
        try:
            tk = yf.Ticker(name)
            hist = tk.history(period="5d", interval=iv)
            if hist is None or hist.empty:
                return []
            out = []
            for _, row in hist.iterrows():
                try:
                    out.append((float(row["Open"]), float(row["High"]),
                                float(row["Low"]), float(row["Close"])))
                except Exception:
                    continue
            return out
        except Exception as exc:
            log.warning("Yahoo klines échec (%s) : %s", name, exc)
            return []

    return await asyncio.to_thread(_work)


# ---------------- API publique du module ----------------
async def get_ohlc(symbol, category, tf_sec, tf_label, limit=160):
    """Chandelles OHLC : Pocket Option SSID -> PO public -> Binance/Yahoo."""
    market = category_market(category)
    po_sym = po_symbol(symbol, market)

    # 1) Pocket Option via votre SSID (temps réel, tous timeframes)
    if pocket_option.ssid_enabled():
        ohlc = await pocket_option.get_candles(po_sym, tf_sec, limit)
        if len(ohlc) >= 50:
            return ohlc

    # 2) Pocket Option endpoint public (timeframes M/H)
    if PO_ENABLED:
        ohlc = await _po_public_ohlc(po_sym, tf_label)
        if len(ohlc) >= 50:
            return ohlc

    # 3) Binance (crypto)
    if market == "crypto":
        ohlc = await _binance_ohlc(symbol + "USDT", tf_sec, limit)
        if len(ohlc) >= 50:
            return ohlc

    # 4) Yahoo (forex / matières premières)
    return await _yahoo_ohlc(symbol, market, tf_sec)


async def get_price(symbol, market):
    """Prix temps réel pour les commandes rapides /prix et le texte libre."""
    if PO_ENABLED or pocket_option.ssid_enabled():
        data = await _po_quote(symbol, market)
        if data:
            return data
    if market == "crypto":
        return await _binance_price(symbol + "USDT")
    return await _yahoo_price(symbol, market)


# ---- prix de secours (commandes rapides) ----
async def _binance_price(symbol):
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{BINANCE_API}/ticker/24hr", params={"symbol": symbol})
            r.raise_for_status()
            d = r.json()
        return {
            "symbol": symbol.replace("USDT", ""), "market": "crypto",
            "price": float(d["lastPrice"]),
            "change": _num(d["priceChange"]), "change_pct": _num(d["priceChangePercent"]),
            "high": _num(d["highPrice"]), "low": _num(d["lowPrice"]),
            "volume": _num(d["quoteVolume"]), "source": "Binance",
        }
    except Exception as exc:
        log.warning("Binance prix échec (%s) : %s", symbol, exc)
        return None


async def _yahoo_price(symbol, market):
    name = _yahoo_name(symbol, market)

    def _work():
        try:
            tk = yf.Ticker(name)
            fi = tk.fast_info
            price = fi.last_price
            if price is None:
                return None
            change = change_pct = None
            hist = tk.history(period="2d", interval="1d")
            if hist is not None and not hist.empty and len(hist) >= 2:
                prev = float(hist["Close"].iloc[-2])
                last = float(hist["Close"].iloc[-1])
                change = last - prev
                change_pct = (change / prev * 100) if prev else None
            return {
                "symbol": symbol, "market": market, "price": float(price),
                "change": change, "change_pct": change_pct,
                "high": getattr(fi, "day_high", None) or getattr(fi, "high", None),
                "low": getattr(fi, "day_low", None) or getattr(fi, "low", None),
                "volume": None, "source": "Yahoo Finance",
            }
        except Exception as exc:
            log.warning("Yahoo prix échec (%s) : %s", name, exc)
            return None

    return await asyncio.to_thread(_work)
