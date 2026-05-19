"""Dashboard Streamlit — andamento paniere + storico alert.

Deploy: https://share.streamlit.io
Secrets richiesti (Advanced settings → Secrets):
    SUPABASE_URL = "https://xxxxx.supabase.co"
    SUPABASE_KEY = "anon-key-qui"
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yaml
from supabase import create_client

st.set_page_config(page_title="tick", page_icon="📈", layout="wide")


# ---- accesso a config/secrets -------------------------------------------

def _secret(key: str) -> str:
    """Legge da st.secrets se disponibile, altrimenti da env (utile per dev locale)."""
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        v = os.environ.get(key)
        if not v:
            st.error(f"Secret/env mancante: {key}")
            st.stop()
        return v


@st.cache_resource
def get_client():
    return create_client(_secret("SUPABASE_URL"), _secret("SUPABASE_KEY"))


@st.cache_data(ttl=60)
def load_config() -> dict:
    p = Path(__file__).resolve().parent.parent / "config" / "paniere.yaml"
    return yaml.safe_load(p.read_text())


@st.cache_data(ttl=60)
def load_prices(symbol: str, hours: int) -> pd.DataFrame:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    client = get_client()
    resp = (
        client.table("prices").select("*")
        .eq("symbol", symbol).gte("fetched_at", since)
        .order("fetched_at").execute()
    )
    df = pd.DataFrame(resp.data)
    if not df.empty:
        df["fetched_at"] = pd.to_datetime(df["fetched_at"])
    return df


@st.cache_data(ttl=60)
def load_alerts(hours: int = 168) -> pd.DataFrame:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    client = get_client()
    resp = (
        client.table("alerts").select("*")
        .gte("fired_at", since).order("fired_at", desc=True).execute()
    )
    df = pd.DataFrame(resp.data)
    if not df.empty:
        df["fired_at"] = pd.to_datetime(df["fired_at"])
    return df


@st.cache_data(ttl=60)
def latest_quote(symbol: str) -> dict | None:
    client = get_client()
    resp = (
        client.table("prices").select("*")
        .eq("symbol", symbol).order("fetched_at", desc=True)
        .limit(1).execute()
    )
    return resp.data[0] if resp.data else None


# ---- UI -----------------------------------------------------------------

cfg = load_config()
tickers = cfg["tickers"]
ticker_map = {t["symbol"]: t for t in tickers}

st.title("📈 tick — andamento e alert")

# Refresh manuale (Streamlit Cloud non auto-refresha)
if st.button("🔄 Aggiorna", help="Ricarica dati da Supabase"):
    st.cache_data.clear()
    st.rerun()

# Panoramica metric cards
n_cols = min(len(tickers), 4)
cols = st.columns(n_cols)
for i, t in enumerate(tickers):
    q = latest_quote(t["symbol"])
    with cols[i % n_cols]:
        if q:
            delta = q.get("pct_change")
            delta_str = f"{delta:+.2f}%" if delta is not None else None
            st.metric(
                label=t.get("name", t["symbol"]),
                value=f"{q['price']:.4f}",
                delta=delta_str,
            )
        else:
            st.metric(label=t.get("name", t["symbol"]), value="—")

st.divider()

left, right = st.columns([3, 2])

with left:
    st.subheader("Grafico")
    sel = st.selectbox(
        "Ticker",
        [t["symbol"] for t in tickers],
        format_func=lambda s: f"{ticker_map[s].get('name', s)}  ({s})",
    )
    hours = st.slider("Finestra (ore)", 1, 168, 24)

    df = load_prices(sel, hours)
    if df.empty:
        st.info("Nessun dato nel periodo.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df["fetched_at"], y=df["price"],
            mode="lines", name="Prezzo",
            line=dict(width=2),
        ))

        # linee di riferimento se configurate
        cfg_t = ticker_map[sel]
        entry = cfg_t.get("entry_price")
        if entry:
            fig.add_hline(y=entry, line_dash="dot", line_color="gray",
                          annotation_text=f"Entry {entry}", annotation_position="right")
            sl = cfg_t.get("stop_loss_pct")
            tp = cfg_t.get("take_profit_pct")
            if sl is not None:
                fig.add_hline(y=entry * (1 + sl / 100), line_dash="dash", line_color="red",
                              annotation_text=f"SL {sl}%", annotation_position="right")
            if tp is not None:
                fig.add_hline(y=entry * (1 + tp / 100), line_dash="dash", line_color="green",
                              annotation_text=f"TP {tp:+}%", annotation_position="right")

        fig.update_layout(
            height=420,
            margin=dict(l=0, r=80, t=20, b=0),
            xaxis_title=None,
            yaxis_title="Prezzo (EUR)",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

        # stats compatte
        latest = df.iloc[-1]
        first = df.iloc[0]
        change = (latest["price"] - first["price"]) / first["price"] * 100
        c1, c2, c3 = st.columns(3)
        c1.metric("Ultimo", f"{latest['price']:.4f}")
        c2.metric(f"Δ ultime {hours}h", f"{change:+.2f}%")
        c3.metric("Punti", len(df))

with right:
    st.subheader("Ultimi alert")
    al = load_alerts()
    if al.empty:
        st.info("Nessun alert nell'ultima settimana.")
    else:
        for _, row in al.head(30).iterrows():
            arrow = "🟢 ▲" if row["direction"] == "up" else "🔴 ▼"
            ts = row["fired_at"].strftime("%d/%m %H:%M")
            pct = row.get("pct_change")
            pct_str = f" ({pct:+.2f}%)" if pct is not None else ""
            cond_label = {
                "intraday": "intraday",
                "stop_loss": "STOP LOSS",
                "take_profit": "TAKE PROFIT",
            }.get(row["condition"], row["condition"])
            name = ticker_map.get(row["symbol"], {}).get("name", row["symbol"])
            st.markdown(
                f"{arrow} **{name}** — {cond_label}{pct_str}  \n"
                f"<small>{ts} · `{row['symbol']}` · {row['price']:.4f}</small>",
                unsafe_allow_html=True,
            )
            st.divider()
