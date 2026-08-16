# -*- coding: utf-8 -*-
"""
analysis.py — Moteur d'analyse de marché nouvelle génération.
Signaux BUY / SELL / NEUTRAL basés sur la confluence de plusieurs
indicateurs (EMA, MACD, RSI, Stochastic, ADX, ATR, Bollinger, S/R).
⚠️ Analyse éducative — pas un conseil en investissement.
"""
from __future__ import annotations


# ================== Indicateurs de base ==================

def _ema_series(values, period):
    """Série complète d'EMA sur les valeurs (nécessaire pour le MACD)."""
    n = len(values)
    if n < period:
        return []
    k = 2.0 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema(values, period):
    if not values or len(values) < period:
        return None
    return _ema_series(values, period)[-1]


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(values, period=14):
    """RSI de Wilder."""
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(values, fast=12, slow=26, signal=9):
    """Renvoie (ligne MACD, ligne de signal, histogramme)."""
    n = len(values)
    if n < slow + signal:
        return None, None, None
    ef = _ema_series(values, fast)
    es = _ema_series(values, slow)
    # longueurs différentes -> on aligne sur la plus courte
    offset = len(ef) - len(es)
    macd_series = [f - s for f, s in zip(ef[offset:], es)]
    sig_series = _ema_series(macd_series, signal)
    if not macd_series or not sig_series:
        return None, None, None
    line = macd_series[-1]
    sig = sig_series[-1]
    return line, sig, line - sig


def stochastic(closes, kp=14, dp=3):
    """Renvoie (%K, %D) de l'oscillateur stochastique."""
    n = len(closes)
    if n < kp + dp:
        return None, None
    kvals = []
    for i in range(kp - 1, n):
        window = closes[i - kp + 1:i + 1]
        hh, ll = max(window), min(window)
        if hh == ll:
            kvals.append(50.0)
        else:
            kvals.append((closes[i] - ll) / (hh - ll) * 100.0)
    k = kvals[-1]
    d = sum(kvals[-dp:]) / dp if len(kvals) >= dp else None
    return k, d


def atr(highs, lows, closes, period=14):
    """Average True Range — volatilité moyenne."""
    n = len(closes)
    if n < period + 1:
        return None
    trs = []
    for i in range(1, n):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    return sum(trs[-period:]) / period


def bollinger(closes, period=20, k=2.0):
    """Renvoie (bande haute, bande médiane, bande basse)."""
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    sd = var ** 0.5
    return mid + k * sd, mid, mid - k * sd


def adx(highs, lows, closes, period=14):
    """Average Directional Index — force de la tendance (Wilder)."""
    n = len(closes)
    if n < period + 1:
        return None
    tr, pdi_src, mdi_src = [], [], []
    for i in range(1, n):
        tr.append(max(highs[i] - lows[i],
                      abs(highs[i] - closes[i - 1]),
                      abs(lows[i] - closes[i - 1])))
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdi_src.append(up if (up > dn and up > 0) else 0.0)
        mdi_src.append(dn if (dn > up and dn > 0) else 0.0)

    def _wilder(series):
        if len(series) < period:
            return []
        out = [sum(series[:period])]
        for v in series[period:]:
            out.append(out[-1] - out[-1] / period + v)
        return out

    atr_s = _wilder(tr)
    pdi_s = _wilder(pdi_src)
    mdi_s = _wilder(mdi_src)
    dxs = []
    for a, p, m in zip(atr_s, pdi_s, mdi_s):
        if a <= 0:
            continue
        pdi = 100.0 * p / a
        mdi = 100.0 * m / a
        s = pdi + mdi
        dxs.append(100.0 * abs(pdi - mdi) / s if s else 0.0)
    if not dxs:
        return None
    return sum(dxs[-period:]) / min(period, len(dxs))


def sr_levels(highs, lows, lookback=25):
    """Supports / résistances récents (hauts et bas locaux)."""
    if len(highs) < lookback + 2 or len(lows) < lookback + 2:
        return None, None
    resistance = max(highs[-lookback:])
    support = min(lows[-lookback:])
    return support, resistance


def trend_side(closes, fast=20, slow=50):
    """
    Direction de la tendance d'un graphique : -1 baissier, 0 neutre, +1 haussier.
    Utilisé pour la confirmation multi-timeframe (ex : M5 confirmé par M15 et H1).
    """
    if len(closes) < slow:
        return 0
    ef = ema(closes, fast)
    es = ema(closes, slow)
    if ef is None or es is None:
        return 0
    if ef > es:
        return 1
    if ef < es:
        return -1
    return 0


# ================== Signal final ==================

def compute_signal(ohlc):
    """
    ohlc : liste de tuples (open, high, low, close) dans l'ordre chronologique.
    Renvoie un dictionnaire complet ou None si données insuffisantes.
    """
    if not ohlc or len(ohlc) < 60:
        return None

    highs = [x[1] for x in ohlc]
    lows = [x[2] for x in ohlc]
    closes = [x[3] for x in ohlc]
    last = closes[-1]

    score = 0.0
    notes = []  # (emoji, texte) pour le rapport

    # --- 1) Tendance EMA 10/20/50
    e10, e20, e50 = ema(closes, 10), ema(closes, 20), ema(closes, 50)
    if all(v is not None for v in (e10, e20, e50)):
        if e10 > e20 > e50:
            score += 20
            notes.append(("📈", "Tendance haussière (EMA 10 > 20 > 50)"))
        elif e10 < e20 < e50:
            score -= 20
            notes.append(("📉", "Tendance baissière (EMA 10 < 20 < 50)"))
        else:
            notes.append(("↔️", "Tendance mixte (EMA enchevêtrées)"))

    # --- 2) MACD
    macd_line, sig_line, hist = macd(closes)
    if hist is not None and macd_line is not None and sig_line is not None:
        if macd_line > sig_line and hist > 0:
            score += 15
            notes.append(("🟩", "MACD positif, croisement haussier"))
        elif macd_line < sig_line and hist < 0:
            score -= 15
            notes.append(("🟥", "MACD négatif, croisement baissier"))
        else:
            notes.append(("⬜", "MACD neutre / en transition"))

    # --- 3) RSI 14
    r = rsi(closes)
    if r is not None:
        if r < 30:
            score += 12
            notes.append(("💚", f"RSI surventé ({r:.0f}) — rebond potentiel"))
        elif r > 70:
            score -= 12
            notes.append(("💔", f"RSI surachat ({r:.0f}) — repli potentiel"))
        elif 40 <= r <= 60:
            notes.append(("😐", f"RSI neutre ({r:.0f})"))
        else:
            score += 6 if r < 50 else -6
            notes.append((f"📊", f"RSI légèrement {'baissier' if r < 50 else 'haussier'} ({r:.0f})"))

    # --- 4) Stochastique
    k, d = stochastic(closes)
    if k is not None and d is not None:
        if k > d and k < 80:
            score += 10
            notes.append(("🟢", f"Stochastique haussier (K {k:.0f} > D {d:.0f})"))
        elif k < d and k > 20:
            score -= 10
            notes.append(("🔴", f"Stochastique baissier (K {k:.0f} < D {d:.0f})"))
        else:
            notes.append(("⚪", f"Stochastique extrême (K {k:.0f})"))

    # --- 5) Bollinger
    upper, mid, lower = bollinger(closes)
    if all(v is not None for v in (upper, mid, lower)):
        if last > mid:
            score += 6
            notes.append(("🔝", "Prix au-dessus de la bande médiane"))
        else:
            score -= 6
            notes.append(("🔻", "Prix sous la bande médiane"))

    # --- 6) Force de tendance (ADX) — pondère le tout
    a = adx(highs, lows, closes)
    multiplier = 1.0
    if a is not None:
        if a >= 25:
            multiplier = 1.5
            notes.append(("💪", f"Tendance forte (ADX {a:.0f}) — signal amplifié"))
        elif a < 20:
            multiplier = 0.7
            notes.append(("🪶", f"Tendance faible (ADX {a:.0f}) — prudence"))
        else:
            notes.append(("✨", f"Tendance modérée (ADX {a:.0f})"))
    score *= multiplier

    # --- Décision
    if score >= 35:
        side, emoji = "BUY", "🟢"
    elif score <= -35:
        side, emoji = "SELL", "🔴"
    else:
        side, emoji = "NEUTRAL", "🟡"

    if abs(score) >= 65 and (a is None or a >= 25):
        strength = "FORT"
    elif abs(score) >= 45:
        strength = "MOYEN"
    else:
        strength = "FAIBLE"

    # --- Niveaux de sortie basés sur l'ATR (volatilité réelle)
    at = atr(highs, lows, closes)
    at_val = at if at else last * 0.005
    if side == "BUY":
        stop = last - 1.2 * at_val
        tp1 = last + 1.8 * at_val
        tp2 = last + 3.0 * at_val
    elif side == "SELL":
        stop = last + 1.2 * at_val
        tp1 = last - 1.8 * at_val
        tp2 = last - 3.0 * at_val
    else:
        stop = last - at_val
        tp1 = last + 1.5 * at_val
        tp2 = last + 2.5 * at_val

    support, resistance = sr_levels(highs, lows)

    return {
        "side": side,
        "emoji": emoji,
        "strength": strength,
        "score": round(score, 1),
        "notes": notes,
        "rsi": r,
        "adx": a,
        "macd_hist": hist,
        "entry": last,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "support": support,
        "resistance": resistance,
    }
