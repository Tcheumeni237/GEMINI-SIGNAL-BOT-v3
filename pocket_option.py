# -*- coding: utf-8 -*-
"""
pocket_option.py — Flux de chandelles temps réel Pocket Option via votre SSID.
Lecture : PO_SSID depuis le fichier .env.

Bibliothèques supportées (par ordre de préférence) :
  1) pocketoptionapi_async       (AsyncPocketOptionClient) — maintenue, dépôt ChipaDevTeam
  2) pocketoptionapi.stable_api  (PocketOption)           — classique

Le SSID doit être la chaîne COMPLÈTE "42[\"auth\",{...}]" (pas seulement la session).
En cas d'échec, le module renvoie [] et le bot bascule sur Binance/Yahoo.
"""
import asyncio
import logging
import os
import re

log = logging.getLogger("pocketoption")

PO_SSID = os.getenv("PO_SSID", "").strip()

# ---- Détection des bibliothèques (aucun blocage si absentes) ----
try:
    from pocketoptionapi_async import AsyncPocketOptionClient
    _ASYNC_OK = True
except Exception:
    _ASYNC_OK = False

try:
    from pocketoptionapi.stable_api import PocketOption as _ClassicPO
    _CLASSIC_OK = True
except Exception:
    _CLASSIC_OK = False

_client = None  # client partagé (async ou classique)


def ssid_enabled() -> bool:
    return bool(PO_SSID)


def _is_demo() -> bool:
    """Compte démo si isDemo:1 dans le SSID, sinon si l'URL indique demo, sinon variable PO_DEMO."""
    m = re.search(r'"isDemo"\s*:\s*(\d)', PO_SSID)
    if m:
        return m.group(1) == "1"
    if re.search(r'"currentUrl"\s*:\s*"[^"]*demo', PO_SSID, re.IGNORECASE):
        return True
    return os.getenv("PO_DEMO", "1") == "1"


def _normalize_ssid(ssid: str) -> str:
    """La bibliothèque attend le champ 'session'; les navigateurs récents
    l'appellent 'sessionToken'. On convertit avant connexion."""
    if ssid and '"sessionToken"' in ssid and '"session"' not in ssid:
        return ssid.replace('"sessionToken"', '"session"')
    return ssid


def _row(c):
    """Extrait (open, high, low, close) depuis un objet Candle ou un dict."""
    if c is None:
        return None
    try:
        if isinstance(c, dict):
            o = c.get("open") or c.get("o")
            h = c.get("high") or c.get("h")
            l = c.get("low") or c.get("l")
            cl = c.get("close") or c.get("c")
        else:
            o, h, l, cl = c.open, c.high, c.low, c.close
        if None in (o, h, l, cl):
            return None
        return (float(o), float(h), float(l), float(cl))
    except Exception:
        return None


# ============ Mode async (pocketoptionapi_async) ============
async def _async_candles(po_symbol, period_sec, count):
    global _client
    try:
        if _client is None:
            _client = AsyncPocketOptionClient(_normalize_ssid(PO_SSID), is_demo=_is_demo(), enable_logging=False)
            await _client.connect()
            log.info("✅ Connecté à Pocket Option (async) avec votre SSID")
        candles = await _client.get_candles(po_symbol, period_sec, count)
    except Exception as exc:
        log.warning("Pocket Option async (%s, %ss) : %s", po_symbol, period_sec, exc)
        return []
    out = []
    for c in candles or []:
        r = _row(c)
        if r:
            out.append(r)
    return out


# ============ Mode classique (pocketoptionapi.stable_api) ============
def _make_classic_client():
    global _client
    if _client is not None:
        return _client
    client = None
    for factory in (
        lambda: _ClassicPO(ssid=PO_SSID),
        lambda: _ClassicPO(PO_SSID),
        lambda: _ClassicPO(set_ssid=PO_SSID),
    ):
        try:
            client = factory()
            break
        except Exception:
            continue
    if client is None:
        log.warning("Impossible d'instancier PocketOption classique — SSID invalide ?")
        return None
    try:
        res = client.connect()
        ok = res[0] if isinstance(res, tuple) else bool(res)
        if ok:
            _client = client
            log.info("✅ Connecté à Pocket Option (classique) avec votre SSID")
        else:
            log.warning("Connexion Pocket Option classique refusée : %s", res)
    except Exception as exc:
        log.warning("Erreur de connexion Pocket Option classique : %s", exc)
    return _client


def _classic_candles(po_symbol, period_sec, count):
    client = _make_classic_client()
    if client is None:
        return []
    try:
        raw = client.get_candles(po_symbol, period_sec, count)
    except Exception as exc:
        log.warning("get_candles Pocket Option classique (%s, %ss) : %s", po_symbol, period_sec, exc)
        return []
    out = []
    for c in raw or []:
        r = _row(c)
        if r:
            out.append(r)
    return out


# ============ API publique ============
async def get_candles(po_symbol, period_sec, count=160):
    """Chandelles OHLC (open, high, low, close) depuis Pocket Option, ou [] si indisponible."""
    if not PO_SSID:
        return []
    if _ASYNC_OK:
        return await _async_candles(po_symbol, period_sec, count)
    if _CLASSIC_OK:
        return await asyncio.to_thread(_classic_candles, po_symbol, period_sec, count)
    log.warning("Aucune bibliothèque Pocket Option installée — sources publiques utilisées.")
    return []
