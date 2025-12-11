
import os
import httpx
import logging
from typing import Optional, Dict, List

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

logger = logging.getLogger(__name__)


async def fetch_price_simple(coin_id: str, vs_currency: str = "usd") -> Optional[float]:
    url = f"{COINGECKO_BASE}/simple/price"
    params = {"ids": coin_id, "vs_currencies": vs_currency, "include_24hr_change": "true"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            logger.warning("Coingecko simple/price failed %s: %s", r.status_code, r.text)
            return None
        data = r.json()
        if coin_id in data and vs_currency in data[coin_id]:
            return data[coin_id][vs_currency]
        return None


async def fetch_market_info(coin_id: str, vs_currency: str = "usd") -> Optional[Dict]:
    """Return market info (price, 24h change, market cap) using /coins/markets"""
    url = f"{COINGECKO_BASE}/coins/markets"
    params = {"vs_currency": vs_currency, "ids": coin_id, "order": "market_cap_desc", "per_page": 1, "page": 1, "price_change_percentage": "24h"}
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            logger.warning("Coingecko coins/markets failed %s: %s", r.status_code, r.text)
            return None
        arr = r.json()
        if not arr:
            return None
        return arr[0]


async def fetch_multiple_prices(coins: List[str], vs_currency: str = "usd") -> Dict[str, Optional[float]]:
    if not coins:
        return {}
    ids = ",".join(coins)
    url = f"{COINGECKO_BASE}/simple/price"
    params = {"ids": ids, "vs_currencies": vs_currency, "include_24hr_change": "true"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            logger.warning("Coingecko multi simple/price failed %s: %s", r.status_code, r.text)
            return {c: None for c in coins}
        data = r.json()
        out = {}
        for c in coins:
            out[c] = data.get(c, {}).get(vs_currency)
        return out


async def list_top_coins(n: int = 10, vs_currency: str = "usd"):
    url = f"{COINGECKO_BASE}/coins/markets"
    params = {"vs_currency": vs_currency, "order": "market_cap_desc", "per_page": n, "page": 1, "price_change_percentage": "24h"}
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            logger.warning("Coingecko top coins failed %s: %s", r.status_code, r.text)
            return []
        return r.json()


async def send_message(chat_id: int, text: str, parse_mode: str = "Markdown"):
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not set, cannot send messages")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=payload)
        if r.status_code != 200:
            logger.warning("Telegram sendMessage failed %s: %s", r.status_code, r.text)
            return None
        return r.json()


def format_price_line(coin_id: str, price: float, info: Optional[dict] = None, currency: str = "usd") -> str:
    cur = currency.upper()
    price_str = f"{price:,.6g}"
    if info:
        change = info.get("price_change_percentage_24h") or info.get("price_change_percentage_24h_in_currency")
        market_cap = info.get("market_cap")
        change_str = f"{change:+.2f}%" if change is not None else "N/A"
        market_str = f"${market_cap:,.0f}" if market_cap else "N/A"
        return f"*{coin_id}* — {price_str} {cur}\n24h: {change_str} • Mkt cap: {market_str}"
    return f"*{coin_id}* — {price_str} {cur}"
