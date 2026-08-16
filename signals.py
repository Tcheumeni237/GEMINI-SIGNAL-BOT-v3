# -*- coding: utf-8 -*-
"""
signals.py — Compatibilité avec la v1.
L'analyse avancée est désormais dans analysis.py.
"""
from analysis import (
    compute_signal,
    ema,
    sma,
    rsi,
    macd,
    stochastic,
    atr,
    bollinger,
    adx,
    sr_levels,
)

__all__ = [
    "compute_signal",
    "ema",
    "sma",
    "rsi",
    "macd",
    "stochastic",
    "atr",
    "bollinger",
    "adx",
    "sr_levels",
]
