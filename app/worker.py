
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import List, Dict, Any

from .db import get_session
from .models import Subscription, Alert, Chat
from .services import fetch_multiple_prices, fetch_market_info, send_message

logger = logging.getLogger(__name__)
DEFAULT_INTERVAL = int(os.getenv("DEFAULT_UPDATE_INTERVAL", "300"))


async def subscription_and_alert_worker(app_stop_event: asyncio.Event):
    """
    Background worker to:
    - Send subscription updates when interval elapsed
    - Check alerts and trigger when conditions met
    """
    logger.info("Background worker started")
    while not app_stop_event.is_set():
        try:
            session = get_session()
            now = int(datetime.now(tz=timezone.utc).timestamp())

            # Load subscriptions
            subs: List[Subscription] = session.query(Subscription).all()
            # Group by (coin, currency)
            to_fetch: Dict[str, List[Subscription]] = {}
            for s in subs:
                last = s.last_sent or 0
                interval = s.interval_seconds or DEFAULT_INTERVAL
                if now - last >= interval:
                    key = f"{s.coin_id}|{s.currency}"
                    to_fetch.setdefault(key, []).append(s)

            # Fetch prices in batches
            for key, s_list in to_fetch.items():
                coin_id, currency = key.split("|")
                prices = await fetch_multiple_prices([coin_id], vs_currency=currency)
                price = prices.get(coin_id)
                if price is None:
                    continue
                info = await fetch_market_info(coin_id, vs_currency=currency)
                # send message to all chats
                for s in s_list:
                    text = f"Scheduled update:\n{send_price_text(coin_id, price, info, currency)}"
                    await send_message(s.chat_id, text)
                    # update last_sent
                    s.last_sent = now
                session.commit()

            # Alerts
            alerts: List[Alert] = session.query(Alert).filter(Alert.enabled == True).all()
            # Group alerts by (coin, currency)
            alerts_by_key: Dict[str, List[Alert]] = {}
            for a in alerts:
                key = f"{a.coin_id}|{a.currency}"
                alerts_by_key.setdefault(key, []).append(a)

            for key, a_list in alerts_by_key.items():
                coin_id, currency = key.split("|")
                prices = await fetch_multiple_prices([coin_id], vs_currency=currency)
                price = prices.get(coin_id)
                if price is None:
                    continue
                info = await fetch_market_info(coin_id, vs_currency=currency)
                for a in a_list:
                    should_trigger = False
                    if a.direction == "above" and price >= a.target_price:
                        should_trigger = True
                    if a.direction == "below" and price <= a.target_price:
                        should_trigger = True
                    # Optional: throttle triggers to not spam; here we check last_triggered_at
                    last = a.last_triggered_at or 0
                    if should_trigger and (int(datetime.now(tz=timezone.utc).timestamp()) - last > 60):
                        text = (
                            f"Alert triggered for *{a.coin_id}* ({currency.upper()}):\n"
                            f"Condition: {a.direction} {a.target_price}\n"
                            f"Current: {price}\n\n{send_price_text(coin_id, price, info, currency)}"
                        )
                        await send_message(a.chat_id, text)
                        a.last_triggered_at = int(datetime.now(tz=timezone.utc).timestamp())
                        session.commit()

            session.close()
        except Exception as e:
            logger.exception("Error in worker loop: %s", e)

        # Sleep a short time; keep responsiveness
        await asyncio.sleep(5)


def send_price_text(coin_id: str, price: float, info: Dict[str, Any], currency: str = "usd") -> str:
    # Reuse services.format_price_line-like formatting but inline to avoid import cycle
    cur = currency.upper()
    price_str = f"{price:,.6g}"
    if info:
        change = info.get("price_change_percentage_24h") or info.get("price_change_percentage_24h_in_currency")
        market_cap = info.get("market_cap")
        change_str = f"{change:+.2f}%" if change is not None else "N/A"
        market_str = f"${market_cap:,.0f}" if market_cap else "N/A"
        return f"*{coin_id}* — {price_str} {cur}\n24h: {change_str} • Mkt cap: {market_str}"
    return f"*{coin_id}* — {price_str} {cur}"
