# -*- coding: utf-8 -*-
"""
risk.py — Gestion du risque professionnelle.
Règles : risque fixe %, taille de position calculée, R:R, limite quotidienne.
"""
from __future__ import annotations

import json
import os
from datetime import date

RISK_FILE = os.getenv("RISK_FILE", "risk_state.json")


# ---------- Taille de position ----------
def position_size(balance, risk_pct, entry, stop):
    """
    Taille de position à NE PAS dépasser.
    Ex : 1000 $, risque 2 % (20 $), écart entrée->stop = 10 pips
    -> taille = 2 unités (20 / 10).
    """
    risk_per_trade = balance * (risk_pct / 100.0)
    distance = abs(entry - stop)
    if distance <= 0:
        return 0.0
    return risk_per_trade / distance


# ---------- Ratio gain / perte ----------
def rr(entry, stop, target):
    """Ratio gain / perte (R:R). 1.5 : 1 = on risque 1 pour gagner 1.5."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    return abs(target - entry) / risk


# ---------- Limite de perte quotidienne ----------
class DailyRisk:
    """Suivi des pertes de la journée avec arrêt automatique recommandé."""

    def __init__(self, balance, daily_limit_pct):
        self.balance = balance
        self.daily_limit_pct = daily_limit_pct
        self._data = self._load()

    def _load(self):
        try:
            with open(RISK_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") != str(date.today()):
                return {"date": str(date.today()), "loss": 0.0, "trades": 0}
            return data
        except Exception:
            return {"date": str(date.today()), "loss": 0.0, "trades": 0}

    def _save(self):
        try:
            with open(RISK_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @property
    def daily_loss_limit(self):
        return self.balance * (self.daily_limit_pct / 100.0)

    def remaining_budget(self):
        return self.daily_loss_limit - self._data["loss"]

    def record_result(self, r_multiple, risk_per_trade):
        """Enregistre un résultat : r_multiple = +1 (gain 1R) ou -1 (perte 1R)."""
        pnl = r_multiple * risk_per_trade
        if pnl < 0:
            self._data["loss"] += abs(pnl)
        self._data["trades"] += 1
        self._save()
        return self._data["loss"]

    def stop_today(self):
        """True si la limite de perte quotidienne est atteinte."""
        return self._data["loss"] >= self.daily_loss_limit
