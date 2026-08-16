# -*- coding: utf-8 -*-
"""
backtest.py — Backtest de la stratégie : winrate réel et rentabilité.
Principe : forward-test barre par barre, sans biais (pas de fuite de données).
"""
from __future__ import annotations

from analysis import compute_signal


def _resolve_outcome(ohlc, i, entry, stop, tp, side, horizon=12):
    """Simule un trade : +1R (objectif touché), -1R (stop touché), sinon
    résultat au dernier prix de l'horizon (borné à ±1R)."""
    n = len(ohlc)
    end = min(i + 1 + horizon, n)
    for j in range(i + 1, end):
        hi = ohlc[j][1]
        lo = ohlc[j][2]
        if side == "BUY":
            hit_tp = hi >= tp
            hit_sl = lo <= stop
        else:
            hit_tp = lo <= tp
            hit_sl = hi >= stop
        if hit_tp and hit_sl:
            return 0.0  # cas ambigu -> compté neutre (prudent)
        if hit_tp:
            return 1.0
        if hit_sl:
            return -1.0
    # l'horizon s'écoule sans objectif ni stop : on clôture au dernier prix
    last = ohlc[end - 1][3]
    risk = abs(entry - stop)
    if risk <= 0:
        return 0.0
    if side == "BUY":
        r = (last - entry) / risk
    else:
        r = (entry - last) / risk
    return max(-1.0, min(1.0, r))


def run_backtest(ohlc, warmup=80, min_trades=5, tf_sec=300):
    """
    ohlc : liste de tuples (open, high, low, close) chronologiques.
    tf_sec : durée d'une chandelle en secondes (ajuste l'horizon de sortie).
    Renvoie un dict de statistiques, ou None si données insuffisantes.
    """
    n = len(ohlc)
    horizon = max(6, min(48, round(3600 / tf_sec) if tf_sec else 12))
    if n < warmup + horizon:
        return None

    results = []
    wins = losses = scratches = 0

    for i in range(warmup, n - horizon):
        sig = compute_signal(ohlc[: i + 1])
        if not sig or sig["side"] == "NEUTRAL":
            continue
        r = _resolve_outcome(ohlc, i, sig["entry"], sig["stop"],
                             sig["tp1"], sig["side"], horizon)
        results.append(r)
        if r > 0:
            wins += 1
        elif r < 0:
            losses += 1
        else:
            scratches += 1

    total = len(results)
    if total < min_trades:
        return None

    gross_win = sum(r for r in results if r > 0)
    gross_loss = abs(sum(r for r in results if r < 0))
    net_r = sum(results)
    winrate = wins / total * 100.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")
    expectancy = net_r / total

    if profit_factor >= 1.5 and winrate >= 45:
        verdict = "✅ Stratégie rentable sur cette période (edge positif)"
    elif profit_factor >= 1.0:
        verdict = "➖ Résultats équilibrés — à surveiller"
    else:
        verdict = "⚠️ Stratégie perdante ici — réduisez la taille des positions"

    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "scratches": scratches,
        "winrate": round(winrate, 1),
        "gross_win_r": round(gross_win, 2),
        "gross_loss_r": round(gross_loss, 2),
        "net_r": round(net_r, 2),
        "profit_factor": profit_factor,
        "expectancy": round(expectancy, 3),
        "verdict": verdict,
    }
