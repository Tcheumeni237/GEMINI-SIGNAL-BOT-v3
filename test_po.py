# -*- coding: utf-8 -*-
"""
test_po.py — Vérifie votre SSID Pocket Option avant de déployer le bot.

Usage :
    pip install -r requirements.txt
    pip install -r requirements-poo.txt
    python test_po.py

Ce script est NON destructif : il ne fait que LIRE (aucun trade, aucune
modification). Il n'affiche JAMAIS votre SSID — uniquement le résultat.

Bibliothèque : pocketoptionapi_async (dépôt ChipaDevTeam).
"""
import asyncio
import os
import re
import sys

from dotenv import load_dotenv

load_dotenv()

PO_SSID = os.getenv("PO_SSID", "").strip()


def check_ssid_format(ssid):
    """Accepte le format complet 42["auth",{...}] OU un SSID brut (cookie v2.0...)."""
    if not ssid:
        print("❌ PO_SSID est vide dans le fichier .env")
        return False
    if ssid.startswith('42["auth"'):
        if '"session"' not in ssid and '"sessionToken"' not in ssid:
            print("❌ Aucun champ 'session' / 'sessionToken' trouvé dans le SSID")
            return False
        return True
    # SSID brut (ex: cookie ssid de type v2.0.1785...)
    if len(ssid) < 10:
        print("❌ Ce SSID semble trop court pour être valide.")
        return False
    print("ℹ️  Format détecté : SSID brut (ex: v2.0...). La bibliothèque le")
    print("    traite comme une session brute et reconstruit le message d'auth.")
    print("    Si la connexion échoue, utilisez le format complet :")
    print('    42["auth",{"session":"...","isDemo":1,"uid":...,"platform":1}]')
    return True


def normalize_ssid(ssid):
    """La bibliothèque attend le champ 'session'; les navigateurs récents
    l'appellent 'sessionToken'. On convertit avant connexion."""
    if ssid and '"sessionToken"' in ssid and '"session"' not in ssid:
        return ssid.replace('"sessionToken"', '"session"')
    return ssid


def is_demo():
    m = re.search(r'"isDemo"\s*:\s*(\d)', PO_SSID)
    if m:
        return m.group(1) == "1"
    if re.search(r'"currentUrl"\s*:\s*"[^"]*demo', PO_SSID, re.IGNORECASE):
        return True
    return os.getenv("PO_DEMO", "1") == "1"


async def main():
    print("🔎 Vérification du SSID Pocket Option (lecture seule)\n")

    if not check_ssid_format(PO_SSID):
        print("\n➡️  Comment l'obtenir :")
        print("   1. Connectez-vous sur pocketoption.com (compte démo recommandé)")
        print("   2. F12 -> onglet Network -> filtre WS")
        print("   3. Cliquez sur le WebSocket, cherchez le message 42[\"auth\",{...}]")
        print("   4. Copiez-le EN ENTIER dans .env -> PO_SSID=...")
        sys.exit(1)

    try:
        from pocketoptionapi_async import AsyncPocketOptionClient
        print("✅ Bibliothèque pocketoptionapi_async trouvée")
    except Exception as exc:
        print(f"❌ Bibliothèque absente : {exc}")
        print("   Installez d'abord :  pip install -r requirements-poo.txt")
        sys.exit(1)

    demo = is_demo()
    print(f"ℹ️  Compte ciblé : {'DÉMO' if demo else 'RÉEL'}")

    ssid_use = normalize_ssid(PO_SSID)
    if ssid_use != PO_SSID:
        print("ℹ️  'sessionToken' détecté → converti en 'session' pour la bibliothèque.")

    try:
        client = AsyncPocketOptionClient(ssid_use, is_demo=demo, enable_logging=False)
        ok = await client.connect()
    except Exception as exc:
        print(f"❌ Échec de connexion : {exc}")
        print("   → Vérifiez que le SSID est COMPLET et à jour.")
        print("   → Reconnectez-vous sur Pocket Option pour le régénérer.")
        sys.exit(1)

    if not ok:
        print("❌ Connexion refusée (SSID invalide ou expiré).")
        sys.exit(1)
    print("✅ Connecté à Pocket Option avec votre SSID")

    # Lecture de chandelles (lecture seule)
    symbol = "EURUSD"
    try:
        candles = await client.get_candles(symbol, 60, 30)
        n = len(candles or [])
        if n:
            print(f"✅ {n} chandelles reçues pour {symbol} (1 min) — SSID opérationnel !")
        else:
            print("⚠️  Connexion OK mais 0 chandelle retournée — réessayez plus tard.")
    except Exception as exc:
        print(f"⚠️  Connexion OK mais lecture des chandelles impossible : {exc}")

    try:
        await client.disconnect()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())
