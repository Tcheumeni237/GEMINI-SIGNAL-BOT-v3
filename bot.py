# -*- coding: utf-8 -*-
"""
bot.py — Bot Telegram « GEMINI SIGNAL BOT » v3.
Interface : Start -> Catégories -> Paires -> Timeframes -> Signal (+ confluence MTF).
Commandes : /prix, /signal, /backtest, /risk, /menu, /aide.
Lancement :  python bot.py
"""
import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import analysis
import backtest
import prices
import risk

# ---------------- Configuration ----------------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
ALLOWED_IDS = {
    int(x.strip()) for x in os.getenv("ALLOWED_IDS", "").split(",") if x.strip()
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("gemini_bot")

# ---------------- Sécurité ----------------
def is_allowed(user_id):
    return not ALLOWED_IDS or user_id in ALLOWED_IDS


# ---------------- Claviers interactifs ----------------
def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def main_menu_kb():
    rows = [
        [InlineKeyboardButton(info["label"], callback_data=f"cat:{cat_id}")]
        for cat_id, info in prices.CATEGORIES.items()
    ]
    return InlineKeyboardMarkup(rows)


def pairs_kb(cat_id):
    syms = prices.CATEGORIES[cat_id]["symbols"]
    rows = [
        [InlineKeyboardButton(s, callback_data=f"pair:{cat_id}:{s}") for s in row]
        for row in chunks(syms, 2)
    ]
    rows.append([InlineKeyboardButton("⬅️ Retour au menu", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def timeframe_kb(cat_id, symbol):
    rows = [
        [InlineKeyboardButton(t, callback_data=f"tf:{cat_id}:{symbol}:{t}") for t in row]
        for row in chunks(prices.TIMEFRAMES, 4)
    ]
    rows.append([InlineKeyboardButton("⬅️ Retour aux paires", callback_data=f"cat:{cat_id}")])
    return InlineKeyboardMarkup(rows)


def action_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Backtest", callback_data="backtest"),
         InlineKeyboardButton("🔄 Re-analyser", callback_data="reana")],
        [InlineKeyboardButton("🏠 Menu principal", callback_data="menu")],
    ])


# ---------------- Multi-timeframe ----------------
MTF_LADDER = ["M1", "M3", "M5", "M15", "M30", "H1"]


def higher_timeframes(tf):
    """Timeframes supérieurs pour la confirmation (max 2)."""
    tf = tf.upper()
    if tf in MTF_LADDER:
        idx = MTF_LADDER.index(tf)
        return MTF_LADDER[idx + 1: idx + 3]
    if tf.startswith("S"):
        return ["M1", "M5"]
    return []


def _market_to_cat(market):
    if market == "crypto":
        return "crypto"
    if market == "forex":
        return "forex_major"
    if market == "commodity":
        return "commodity"
    return None


# ---------------- Formatage ----------------
def _decimals(price):
    if price >= 1000:
        return 2
    if price >= 1:
        return 4
    return 6


def format_volume(v):
    if v is None:
        return None
    for unit in ("", "K", "M", "B", "T"):
        if abs(v) < 1000 or unit == "T":
            return f"{v:,.2f} {unit}$".replace("  $", "$")
        v /= 1000
    return f"{v:,.2f}$"


def format_price(d):
    p = d["price"]
    dec = _decimals(p)
    chg = d.get("change_pct")
    chg_txt = "—"
    if chg is not None:
        arrow = "📈" if chg >= 0 else "📉"
        chg_txt = f"{arrow} {chg:+.2f} %"
    lines = [
        f"{prices.MARKET_EMOJI.get(d['market'], '💠')} **{d['symbol']}** · {d['market'].upper()}",
        f"💰 Prix : **${p:,.{dec}f}**",
        f"Variation 24 h : {chg_txt}",
    ]
    if d.get("high") is not None:
        lines.append(f"🔺 Plus haut 24 h : ${d['high']:,.{dec}f}")
    if d.get("low") is not None:
        lines.append(f"🔻 Plus bas 24 h : ${d['low']:,.{dec}f}")
    vol = format_volume(d.get("volume"))
    if vol:
        lines.append(f"📦 Volume : {vol}")
    lines.append(f"🛰 Source : {d.get('source', '?')}")
    return "\n".join(lines)


def format_analysis(cat_label, symbol, tf, r, confluence=None):
    dec = _decimals(r["entry"])
    rsi_txt = f"{r['rsi']:.1f}" if r["rsi"] is not None else "—"
    adx_txt = f"{r['adx']:.1f}" if r["adx"] is not None else "—"
    dist = abs(r["entry"] - r["stop"])
    rr_val = (abs(r["tp1"] - r["entry"]) / dist) if dist > 0 else None

    lines = [
        f"{r['emoji']} **SIGNAL {r['side']} — {r['strength']}**",
        f"{cat_label} · `{symbol}` · **timeframe {tf}**",
        f"🎯 Score : **{r['score']:+.0f} / 100**",
        "",
    ]
    for emo, txt in r["notes"][:7]:
        lines.append(f"{emo} {txt}")
    if confluence:
        lines.append("")
        lines.append("🧭 **Confluence multi-timeframe :**")
        for htf, t_txt, emo in confluence:
            lines.append(f"   {emo} {htf} : {t_txt}")
    lines += [
        "",
        f"🎯 Entrée : **${r['entry']:,.{dec}f}**",
        f"🛑 Stop-loss : ${r['stop']:,.{dec}f}",
        f"✅ Objectif 1 : ${r['tp1']:,.{dec}f}",
        f"🚀 Objectif 2 : ${r['tp2']:,.{dec}f}",
    ]
    if rr_val:
        lines.append(f"⚖️ Ratio gain/perte : {rr_val:.1f} : 1")
    if r.get("support") is not None and r.get("resistance") is not None:
        lines.append(f"📊 Support : ${r['support']:,.{dec}f} · Résistance : ${r['resistance']:,.{dec}f}")
    lines += [
        f"📈 RSI : {rsi_txt} · ADX : {adx_txt}",
        "",
        "⏱ Données en temps réel.",
        "⚠️ Outil éducatif — pas un conseil en investissement.",
    ]
    return "\n".join(lines)


def format_backtest(symbol, tf, s):
    pf = s["profit_factor"]
    pf_txt = "∞" if pf == float("inf") else f"{pf:.2f}"
    lines = [
        f"📊 **BACKTEST — {symbol} ({tf})**",
        f"Trades simulés : **{s['trades']}**",
        f"✅ Victoires : {s['wins']} · ❌ Pertes : {s['losses']} · ➖ Neutres : {s['scratches']}",
        f"🏆 **Winrate réel : {s['winrate']:.1f} %**",
        f"💵 Profit net : {s['net_r']:+.2f} R (en multiples de votre risque)",
        f"📈 Facteur de profit : {pf_txt}",
        f"🎯 Espérance par trade : {s['expectancy']:+.3f} R",
        "",
        s["verdict"],
        "",
        "ℹ️ Résultat sur données passées — ne garantit rien pour l'avenir.",
    ]
    return "\n".join(lines)


# ---------------- Handlers ----------------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return await update.message.reply_text("⛔ Accès non autorisé.")
    user = update.effective_user
    await update.message.reply_text(
        f"🚀 **Bienvenue, {user.first_name} !**\n\n"
        "Je suis **GEMINI SIGNAL**, votre analyste de marché en temps réel "
        "avec confirmation multi-timeframe et backtest honnête.\n\n"
        "👇 **Choisissez une catégorie pour commencer :**",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return await update.message.reply_text("⛔ Accès non autorisé.")
    await update.message.reply_text(
        "🏠 **Menu principal** — choisissez une catégorie :",
        parse_mode="Markdown",
        reply_markup=main_menu_kb(),
    )


async def cmd_aide(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return await update.message.reply_text("⛔ Accès non autorisé.")
    texte = (
        "📖 **AIDE — GEMINI SIGNAL BOT v3**\n\n"
        "**Interface :** `/start` → catégorie → paire → timeframe → signal.\n"
        "Timeframes : S3 S5 S10 S15 S30 M1 M3 M5 M15 M30 H1\n\n"
        "**Commandes :**\n"
        "`/menu` — menu des catégories\n"
        "`/prix SYMBOLE` — prix temps réel\n"
        "`/signal SYMBOLE` — signal immédiat (5 min) + confluence\n"
        "`/backtest SYMBOLE [TF]` — winrate réel sur l'historique\n"
        "`/risk` — gestion du risque (taille de position, R:R, budget)\n"
        "`/aide` — cette aide\n\n"
        "💡 Astuce : tapez simplement `btc`, `eurusd` ou `xauusd` pour un prix immédiat.\n\n"
        "🧠 **Analyse :** EMA 10/20/50, MACD, RSI 14, Stochastic, ADX, ATR, "
        "Bollinger, S/R + confirmation M15/H1.\n"
        "🛰 **Source :** Pocket Option (SSID) + Binance / Yahoo en secours.\n\n"
        "⚠️ **Avertissement :** signaux informatifs, pas un conseil en investissement."
    )
    await update.message.reply_text(texte, parse_mode="Markdown")


async def run_analysis(update: Update, ctx: ContextTypes.DEFAULT_TYPE, cat, symbol, tf):
    q = update.callback_query
    cat_label = prices.CATEGORIES[cat]["label"]
    ctx.user_data["cur"] = {"cat": cat, "symbol": symbol, "tf": tf}

    await q.edit_message_text(
        f"🔬 Analyse de **{symbol}** sur **{tf}**…\n"
        "EMA, MACD, RSI, Stochastic, ADX, ATR, Bollinger + confluence M15/H1…"
    )

    tf_sec = prices.tf_seconds(tf)
    ohlc = await prices.get_ohlc(symbol, cat, tf_sec, tf)

    if not ohlc or len(ohlc) < 60:
        hint = ""
        if tf.startswith("S") and not prices.po_ssid_enabled():
            hint = ("\n\n💡 Les timeframes **en secondes (S3–S30)** exigent la source "
                    "**Pocket Option** : renseignez `PO_SSID` dans le fichier `.env` "
                    "(voir le guide). Choisissez sinon un timeframe **M/H**.")
        return await q.edit_message_text(
            f"❌ Pas assez de données pour `{symbol}` en `{tf}`.\n"
            "Réessayez dans quelques instants ou changez de timeframe." + hint,
            reply_markup=action_kb(),
        )

    result = analysis.compute_signal(ohlc)
    if not result:
        return await q.edit_message_text(
            f"❌ Analyse impossible pour `{symbol}` en `{tf}`.",
            reply_markup=action_kb(),
        )

    # ---- Confirmation multi-timeframe ----
    confluence = []
    confluence_score = 0
    for htf in higher_timeframes(tf):
        h_ohlc = await prices.get_ohlc(symbol, cat, prices.tf_seconds(htf), htf)
        if not h_ohlc or len(h_ohlc) < 60:
            continue
        trend = analysis.trend_side([x[3] for x in h_ohlc])
        if trend > 0:
            t_txt, emo = "haussier", "🟢"
        elif trend < 0:
            t_txt, emo = "baissier", "🔴"
        else:
            t_txt, emo = "neutre", "⚪"
        confluence.append((htf, t_txt, emo))
        if result["side"] == "BUY" and trend > 0:
            confluence_score += 1
        elif result["side"] == "SELL" and trend < 0:
            confluence_score += 1
        elif trend != 0:
            confluence_score -= 1

    if result["side"] != "NEUTRAL":
        if confluence_score >= 2:
            result["strength"] = "FORT"
        elif confluence_score <= -1:
            result["strength"] = "FAIBLE"

    # mémoire du dernier signal (pour /risk et backtest)
    ctx.user_data["last_result"] = {**result, "symbol": symbol, "tf": tf}

    await q.edit_message_text(
        format_analysis(cat_label, symbol, tf, result, confluence),
        reply_markup=action_kb(),
    )


async def run_backtest_flow(update: Update, ctx: ContextTypes.DEFAULT_TYPE, symbol, cat, tf):
    q = update.callback_query
    await q.edit_message_text(
        f"⏳ Backtest de `{symbol}` ({tf})…\nSimulation de la stratégie sur l'historique…"
    )
    tf_sec = prices.tf_seconds(tf)
    ohlc = await prices.get_ohlc(symbol, cat, tf_sec, tf, limit=500)
    if not ohlc or len(ohlc) < 120:
        return await q.edit_message_text(
            f"❌ Pas assez de données pour le backtest de `{symbol}` ({tf}).",
            reply_markup=action_kb(),
        )
    stats = backtest.run_backtest(ohlc, tf_sec=tf_sec)
    if not stats:
        return await q.edit_message_text(
            f"❌ Pas assez de trades détectés pour `{symbol}` ({tf}) sur cette période.",
            reply_markup=action_kb(),
        )
    await q.edit_message_text(
        format_backtest(symbol, tf, stats),
        reply_markup=action_kb(),
    )


async def on_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "menu":
        await q.edit_message_text(
            "🏠 **Menu principal** — choisissez une catégorie :",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return

    if data.startswith("cat:"):
        cat = data.split(":", 1)[1]
        if cat not in prices.CATEGORIES:
            return
        label = prices.CATEGORIES[cat]["label"]
        await q.edit_message_text(
            f"📋 **{label}** — choisissez une paire :",
            parse_mode="Markdown",
            reply_markup=pairs_kb(cat),
        )
        return

    if data.startswith("pair:"):
        _, cat, symbol = data.split(":", 2)
        ctx.user_data["cur"] = {"cat": cat, "symbol": symbol}
        await q.edit_message_text(
            f"⏱ **`{symbol}`** — choisissez le timeframe :",
            parse_mode="Markdown",
            reply_markup=timeframe_kb(cat, symbol),
        )
        return

    if data.startswith("tf:"):
        _, cat, symbol, tf = data.split(":", 3)
        await run_analysis(update, ctx, cat, symbol, tf)
        return

    if data == "backtest":
        cur = ctx.user_data.get("cur")
        if not cur or "tf" not in cur:
            return await q.edit_message_text(
                "❌ Choisissez d'abord une paire via le menu pour pouvoir la backtester.",
                reply_markup=main_menu_kb(),
            )
        await run_backtest_flow(update, ctx, cur["symbol"], cur["cat"], cur["tf"])
        return

    if data == "reana":
        cur = ctx.user_data.get("cur")
        if not cur or "tf" not in cur:
            return await q.edit_message_text(
                "❌ Aucune analyse précédente. Revenez au menu.",
                reply_markup=main_menu_kb(),
            )
        await run_analysis(update, ctx, cur["cat"], cur["symbol"], cur["tf"])


# ---------------- Commandes rapides texte ----------------
async def cmd_prix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return await update.message.reply_text("⛔ Accès non autorisé.")
    raw = " ".join(ctx.args).strip() if ctx.args else ""
    symbol, market = prices.normalize(raw)
    if not symbol:
        return await update.message.reply_text("Exemple : `/prix BTC`", parse_mode="Markdown")
    msg = await update.message.reply_text(f"🔎 Recherche du prix de **{symbol}**…")
    data = await prices.get_price(symbol, market)
    if not data:
        return await msg.edit_text(
            f"❌ Impossible d'obtenir le prix de *{symbol}*. Vérifiez le symbole."
        )
    await msg.edit_text(format_price(data), parse_mode="Markdown")


async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return await update.message.reply_text("⛔ Accès non autorisé.")
    raw = " ".join(ctx.args).strip() if ctx.args else ""
    symbol, market = prices.normalize(raw)
    cat = _market_to_cat(market)
    if not symbol or not cat:
        return await update.message.reply_text(
            "Exemple : `/signal EURUSD`. Utilisez `/menu` pour les matières premières.",
            parse_mode="Markdown",
        )
    msg = await update.message.reply_text(
        f"📊 Analyse de **{symbol}** (5 min)…\nEMA, MACD, RSI, Stochastic, ADX + confluence…"
    )
    ohlc = await prices.get_ohlc(symbol, cat, 300, "M5")
    if not ohlc or len(ohlc) < 60:
        return await msg.edit_text(
            f"❌ Pas assez de données pour *{symbol}*. Réessayez plus tard."
        )
    result = analysis.compute_signal(ohlc)
    if not result:
        return await msg.edit_text(f"❌ Analyse impossible pour *{symbol}*.")
    ctx.user_data["cur"] = {"cat": cat, "symbol": symbol, "tf": "M5"}
    ctx.user_data["last_result"] = {**result, "symbol": symbol, "tf": "M5"}
    cat_label = prices.CATEGORIES[cat]["label"]
    await msg.edit_text(format_analysis(cat_label, symbol, "M5", result))


async def cmd_backtest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return await update.message.reply_text("⛔ Accès non autorisé.")
    args = [a for a in ctx.args] if ctx.args else []
    if not args:
        return await update.message.reply_text(
            "Exemple : `/backtest BTC` ou `/backtest EURUSD M15`",
            parse_mode="Markdown",
        )
    raw = args[0]
    tf = args[1].upper() if len(args) > 1 and args[1].upper() in prices.TIMEFRAMES else "M5"
    symbol, market = prices.normalize(raw)
    cat = _market_to_cat(market)
    if not symbol or not cat:
        return await update.message.reply_text(f"Symbole *{raw}* inconnu.", parse_mode="Markdown")
    msg = await update.message.reply_text(
        f"⏳ Backtest de **{symbol}** ({tf})…\nSimulation de la stratégie sur l'historique…"
    )
    ohlc = await prices.get_ohlc(symbol, cat, prices.tf_seconds(tf), tf, limit=500)
    if not ohlc or len(ohlc) < 120:
        return await msg.edit_text(
            f"❌ Pas assez de données pour le backtest de *{symbol}* ({tf})."
        )
    stats = backtest.run_backtest(ohlc, tf_sec=prices.tf_seconds(tf))
    if not stats:
        return await msg.edit_text(
            f"❌ Pas assez de trades détectés pour *{symbol}* ({tf}) sur cette période."
        )
    ctx.user_data["cur"] = {"cat": cat, "symbol": symbol, "tf": tf}
    await msg.edit_text(format_backtest(symbol, tf, stats))


async def cmd_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return await update.message.reply_text("⛔ Accès non autorisé.")
    balance = float(os.getenv("ACCOUNT_BALANCE", "1000"))
    risk_pct = float(os.getenv("RISK_PERCENT", "2"))
    daily_pct = float(os.getenv("DAILY_LIMIT_PCT", "6"))
    dr = risk.DailyRisk(balance, daily_pct)
    risk_per_trade = balance * risk_pct / 100.0

    lines = [
        "💼 **GESTION DU RISQUE**",
        f"💰 Capital : **${balance:,.0f}**",
        f"⚖️ Risque par trade : {risk_pct:.1f} % (${risk_per_trade:,.2f})",
        f"🛑 Limite de perte quotidienne : {daily_pct:.0f} % (${dr.daily_loss_limit:,.2f})",
        f"📉 Perte déjà enregistrée aujourd'hui : ${dr._data['loss']:,.2f}",
        f"✅ Budget de risque restant : **${dr.remaining_budget():,.2f}**",
    ]
    if dr.stop_today():
        lines.append("\n⛔ **Limite atteinte : STOP pour aujourd'hui.**")

    last = ctx.user_data.get("last_result")
    if last:
        size = risk.position_size(balance, risk_pct, last["entry"], last["stop"])
        rr_val = risk.rr(last["entry"], last["stop"], last["tp1"])
        lines.append(f"\n💡 Dernier signal `{last['symbol']}` ({last['tf']}) :")
        if rr_val:
            lines.append(f"   • Ratio gain/perte : {rr_val:.1f} : 1")
        lines.append(f"   • Taille de position conseillée : **{size:,.4f} unités**")
        lines.append(f"   • Risque engagé : ${risk_per_trade:,.2f}")

    lines.append(
        "\nRègle d'or : risquez 1-2 % par trade, stop-loss toujours, "
        "arrêtez-vous après 2-3 pertes consécutives."
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return await update.message.reply_text("⛔ Accès non autorisé.")
    text = (update.message.text or "").strip()
    if not text or text.startswith("/"):
        return
    symbol, market = prices.normalize(text)
    if not symbol:
        return await update.message.reply_text("Tapez `/aide` pour voir les commandes.")
    data = await prices.get_price(symbol, market)
    if data:
        await update.message.reply_text(format_price(data), parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"Symbole *{symbol}* introuvable. Tapez `/menu` ou `/aide`.",
            parse_mode="Markdown",
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Erreur : %s", context.error, exc_info=context.error)


# ---------------- Point d'entrée ----------------
def main():
    if not TELEGRAM_TOKEN:
        log.error("❌ TELEGRAM_TOKEN manquant — remplissez le fichier .env")
        return
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("aide", cmd_aide))
    app.add_handler(CommandHandler("help", cmd_aide))
    app.add_handler(CommandHandler("prix", cmd_prix))
    app.add_handler(CommandHandler("price", cmd_prix))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("backtest", cmd_backtest))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CallbackQueryHandler(on_menu_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    log.info("✅ Bot GEMINI SIGNAL v3 démarré — 24h/24 — Ctrl+C pour arrêter")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
