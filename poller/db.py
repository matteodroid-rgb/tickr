"""Wrapper Supabase per persistenza prezzi, alert e state."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from supabase import Client, create_client


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


# ---- prices --------------------------------------------------------------

def insert_price(
    client: Client,
    symbol: str,
    price: float,
    open_price: float | None,
    pct_change: float | None,
    volume: int | None,
) -> None:
    client.table("prices").insert({
        "symbol": symbol,
        "price": price,
        "open_price": open_price,
        "pct_change": pct_change,
        "volume": volume,
    }).execute()


# ---- alerts log ----------------------------------------------------------

def insert_alert(
    client: Client,
    symbol: str,
    condition: str,
    direction: str,
    price: float,
    pct_change: float | None,
    threshold: float | None,
    message: str,
) -> None:
    client.table("alerts").insert({
        "symbol": symbol,
        "condition": condition,
        "direction": direction,
        "price": price,
        "pct_change": pct_change,
        "threshold": threshold,
        "message": message,
    }).execute()


# ---- state (dedup) -------------------------------------------------------

def get_alert_state(client: Client, symbol: str, condition: str) -> dict | None:
    resp = (
        client.table("alert_state")
        .select("*")
        .eq("symbol", symbol)
        .eq("condition", condition)
        .execute()
    )
    return resp.data[0] if resp.data else None


def upsert_alert_state(
    client: Client,
    symbol: str,
    condition: str,
    state: str,
    price: float,
    mark_alerted: bool = False,
) -> None:
    record = {
        "symbol": symbol,
        "condition": condition,
        "state": state,
        "last_price": price,
    }
    if mark_alerted:
        record["last_alerted_at"] = datetime.now(timezone.utc).isoformat()
    client.table("alert_state").upsert(record).execute()


# ---- query per dashboard (usata anche da Streamlit via anon key) ---------

def recent_prices(client: Client, symbol: str, hours: int = 24) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    resp = (
        client.table("prices")
        .select("*")
        .eq("symbol", symbol)
        .gte("fetched_at", since)
        .order("fetched_at")
        .execute()
    )
    return resp.data
