# Updated main entrypoint: auto-manage Telegram webhook if TELEGRAM_WEBHOOK_URL is set,
# added simple /health endpoint.
import os
import argparse
import logging
import asyncio
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from .db import init_db, get_session
from .models import Chat, Subscription, Alert
from .services import (
    fetch_market_info,
    fetch_price_simple,
    list_top_coins,
    send_message,
    format_price_line,
)
from .worker import subscription_and_alert_worker
import httpx

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("telegram-crypto-bot")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DEFAULT_INTERVAL = int(os.getenv("DEFAULT_UPDATE_INTERVAL", "300"))
WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook").rstrip("/")

app = FastAPI()


class UpdateModel(BaseModel):
    update_id: int
    message: Optional[Dict[str, Any]] = None
    edited_message: Optional[Dict[str, Any]] = None


@app.get("/health")
async def health():
    return {"status": "ok"}


# Startup: init DB and start worker, manage Telegram webhook if configured
@app.on_event("startup")
async def on_startup():
    logger.info("Initializing database...")
    init_db()

    # start background worker
    app.state.stop_event = asyncio.Event()
    app.state.worker_task = asyncio.create_task(subscription_and_alert_worker(app.state.stop_event))
    logger.info("Worker started")

    # Manage webhook if WEBHOOK_URL is set (automatically set webhook on startup)
    if WEBHOOK_URL:
        if not TELEGRAM_TOKEN:
            logger.error("TELEGRAM_WEBHOOK_URL set but TELEGRAM_TOKEN is not set. Cannot register webhook.")
        else:
            try:
                await set_telegram_webhook(WEBHOOK_URL)
                logger.info("Webhook registered at %s", WEBHOOK_URL)
            except Exception as e:
                logger.exception("Failed to set webhook: %s", e)


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Shutting down worker...")
    # remove webhook if we set it earlier (try best-effort)
    if WEBHOOK_URL and TELEGRAM_TOKEN:
        try:
            await delete_telegram_webhook()
            logger.info("Webhook removed")
        except Exception:
            logger.exception("Failed to remove webhook during shutdown")
    app.state.stop_event.set()
    await app.state.worker_task
    logger.info("Shutdown complete")


# Helper to parse commands from message text
def parse_command(text: str):
    if not text:
        return None, []
    parts = text.strip().split()
    cmd = parts[0].lstrip("/").split("@")[0].lower()
    args = parts[1:]
    return cmd, args


async def set_telegram_webhook(url: str):
    """Call Telegram setWebhook for this bot to the provided URL."""
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook"
    payload = {"url": url}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(api, json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Failed to set webhook: {data}")


async def delete_telegram_webhook():
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteWebhook"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(api)
        r.raise_for_status()


# Webhook endpoint
@app.post("/webhook/{token}")
async def webhook(token: str, update: UpdateModel):
    # simple token path validation
    if TELEGRAM_TOKEN and token != TELEGRAM_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token in URL")
    msg = update.message or update.edited_message
    if not msg:
        return {"ok": True}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = msg.get("text", "")
    if not chat_id or not text:
        return {"ok": True}
    # ensure chat exists
    session = get_session()
    c = session.query(Chat).filter(Chat.chat_id == chat_id).first()
    if not c:
        c = Chat(chat_id=chat_id)
        session.add(c)
        session.commit()
    # handle commands asynchronously
    asyncio.create_task(handle_command(chat_id, text))
    session.close()
    return {"ok": True}


async def handle_command(chat_id: int, text: str):
    cmd, args = parse_command(text)
    if not cmd:
        return
    try:
        if cmd == "start":
            await send_message(chat_id, HELP_TEXT())
        elif cmd == "price":
            if not args:
                await send_message(chat_id, "Usage: /price <coin_id> [currency]")
                return
            coin = args[0].lower()
            currency = args[1].lower() if len(args) > 1 else "usd"
            info = await fetch_market_info(coin, vs_currency=currency)
            if not info:
                await send_message(chat_id, f"Could not fetch data for '{coin}'. Make sure coin id is correct.")
                return
            text_msg = format_price_line(coin, info.get("current_price"), info, currency)
            await send_message(chat_id, text_msg)
        elif cmd == "coins":
            n = 10
            if args:
                try:
                    n = min(50, max(1, int(args[0])))
                except ValueError:
                    n = 10
            arr = await list_top_coins(n)
            if not arr:
                await send_message(chat_id, "Could not fetch coins list.")
                return
            lines = []
            for t in arr:
                lines.append(f"{t['id']} — {t['name']}: ${t.get('current_price', 'N/A')}")
            await send_message(chat_id, "\n".join(lines))
        elif cmd == "subscribe":
            if not args:
                await send_message(chat_id, "Usage: /subscribe <coin_id> [interval_seconds] [currency]")
                return
            coin = args[0].lower()
            interval = DEFAULT_INTERVAL
            currency = "usd"
            if len(args) > 1:
                try:
                    interval = max(10, int(args[1]))
                except ValueError:
                    interval = DEFAULT_INTERVAL
            if len(args) > 2:
                currency = args[2].lower()
            # verify coin
            info = await fetch_market_info(coin, vs_currency=currency)
            if not info:
                await send_message(chat_id, f"Could not find coin '{coin}' in {currency.upper()}.")
                return
            session = get_session()
            sub = session.query(Subscription).filter(Subscription.chat_id == chat_id, Subscription.coin_id == coin, Subscription.currency == currency).first()
            if not sub:
                sub = Subscription(chat_id=chat_id, coin_id=coin, interval_seconds=interval, currency=currency)
                session.add(sub)
            else:
                sub.interval_seconds = interval
            session.commit()
            session.close()
            await send_message(chat_id, f"Subscribed to {coin} updates every {interval}s ({currency.upper()}). Current: ${info.get('current_price')}")
        elif cmd == "unsubscribe":
            if not args:
                await send_message(chat_id, "Usage: /unsubscribe <coin_id>")
                return
            coin = args[0].lower()
            session = get_session()
            deleted = session.query(Subscription).filter(Subscription.chat_id == chat_id, Subscription.coin_id == coin).delete()
            session.commit()
            session.close()
            if deleted:
                await send_message(chat_id, f"Unsubscribed from {coin}.")
            else:
                await send_message(chat_id, f"You were not subscribed to {coin}.")
        elif cmd == "list":
            session = get_session()
            subs = session.query(Subscription).filter(Subscription.chat_id == chat_id).all()
            session.close()
            if not subs:
                await send_message(chat_id, "No subscriptions.")
                return
            lines = [f"{s.coin_id} — every {s.interval_seconds}s ({s.currency.upper()})" for s in subs]
            await send_message(chat_id, "Subscriptions:\n" + "\n".join(lines))
        elif cmd == "alert":
            # /alert <coin_id> <above|below> <price> [currency]
            if len(args) < 3:
                await send_message(chat_id, "Usage: /alert <coin_id> <above|below> <price> [currency]")
                return
            coin = args[0].lower()
            direction = args[1].lower()
            if direction not in ("above", "below"):
                await send_message(chat_id, "Direction must be 'above' or 'below'")
                return
            try:
                target = float(args[2])
            except ValueError:
                await send_message(chat_id, "Invalid price value")
                return
            currency = args[3].lower() if len(args) > 3 else "usd"
            # verify coin exists
            info = await fetch_market_info(coin, vs_currency=currency)
            if not info:
                await send_message(chat_id, f"Could not find coin '{coin}' in {currency.upper()}.")
                return
            session = get_session()
            alert = Alert(chat_id=chat_id, coin_id=coin, direction=direction, target_price=target, currency=currency)
            session.add(alert)
            session.commit()
            session.close()
            await send_message(chat_id, f"Alert created: {coin} {direction} {target} {currency.upper()}")
        elif cmd == "alerts":
            session = get_session()
            alerts = session.query(Alert).filter(Alert.chat_id == chat_id).all()
            session.close()
            if not alerts:
                await send_message(chat_id, "No alerts.")
                return
            lines = []
            for a in alerts:
                status = "enabled" if a.enabled else "disabled"
                lines.append(f"#{a.id} {a.coin_id} {a.direction} {a.target_price} {a.currency.upper()} ({status})")
            await send_message(chat_id, "Your alerts:\n" + "\n".join(lines))
        elif cmd == "delalert":
            if not args:
                await send_message(chat_id, "Usage: /delalert <alert_id>")
                return
            try:
                aid = int(args[0])
            except ValueError:
                await send_message(chat_id, "Invalid alert id")
                return
            session = get_session()
            deleted = session.query(Alert).filter(Alert.id == aid, Alert.chat_id == chat_id).delete()
            session.commit()
            session.close()
            if deleted:
                await send_message(chat_id, f"Alert #{aid} deleted.")
            else:
                await send_message(chat_id, f"Alert #{aid} not found.")
        else:
            await send_message(chat_id, "Unknown command. Send /start for help.")
    except Exception as e:
        logger.exception("Error handling command: %s", e)
        await send_message(chat_id, "Internal error while handling your command.")


def HELP_TEXT() -> str:
    return (
        "Welcome! I fetch crypto prices from CoinGecko.\n\n"
        "Commands:\n"
        "/price <coin_id> [currency] - Get current price (e.g. /price bitcoin usd)\n"
        "/coins [n] - List top N coins by market cap\n"
        "/subscribe <coin_id> [interval_seconds] [currency] - Subscribe to periodic updates\n"
        "/unsubscribe <coin_id> - Unsubscribe\n"
        "/list - Show your subscriptions\n"
        "/alert <coin_id> <above|below> <price> [currency] - Create price alert\n"
        "/alerts - List alerts\n"
        "/delalert <alert_id> - Delete an alert\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook", action="store_true", help="Run in webhook mode (requires TELEGRAM_WEBHOOK_URL env)")
    args = parser.parse_args()

    # If running as script, we can run Uvicorn (webhook) or a simple polling loop
    if args.webhook and WEBHOOK_URL:
        # Run FastAPI with uvicorn and ensure webhook is set at startup (the user must configure TELEGRAM_WEBHOOK_URL to point to /webhook/<token>)
        import uvicorn

        uvicorn.run("app.main:app", host=HOST, port=PORT, log_level=LOG_LEVEL.lower())
    else:
        # Polling mode: start worker and use getUpdates loop (simple naive polling)
        import time
        import httpx
        from .db import init_db

        init_db()
        logger.info("Starting in polling mode (getUpdates). Make sure TELEGRAM_TOKEN is set.")
        if not TELEGRAM_TOKEN:
            logger.error("TELEGRAM_TOKEN not set. Exiting.")
            raise SystemExit(1)

        OFFSET = 0

        async def polling_loop():
            # start background worker
            stop_event = asyncio.Event()
            worker_task = asyncio.create_task(subscription_and_alert_worker(stop_event))
            async with httpx.AsyncClient(timeout=45.0) as client:
                nonlocal OFFSET  # type: ignore
                while True:
                    try:
                        resp = await client.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", params={"timeout": 30, "offset": OFFSET + 1})
                        if resp.status_code != 200:
                            logger.warning("getUpdates failed: %s", resp.text)
                            await asyncio.sleep(2)
                            continue
                        data = resp.json()
                        for upd in data.get("result", []):
                            OFFSET = max(OFFSET, upd["update_id"])
                            msg = upd.get("message") or upd.get("edited_message")
                            if not msg:
                                continue
                            chat = msg.get("chat") or {}
                            chat_id = chat.get("id")
                            text = msg.get("text", "")
                            # ensure chat exists
                            session = get_session()
                            c = session.query(Chat).filter(Chat.chat_id == chat_id).first()
                            if not c:
                                c = Chat(chat_id=chat_id)
                                session.add(c)
                                session.commit()
                            session.close()
                            # handle command
                            asyncio.create_task(handle_command(chat_id, text))
                    except Exception as e:
                        logger.exception("Polling loop error: %s", e)
                        await asyncio.sleep(2)

        asyncio.run(polling_loop())
