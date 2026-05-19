"""Valutazione condizioni di alert con dedup e cooldown."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from supabase import Client

from . import db


@dataclass
class AlertEvent:
    symbol: str
    condition: str            # 'intraday' | 'stop_loss' | 'take_profit'
    direction: str            # 'up' | 'down'
    price: float
    pct_change: float | None
    threshold: float
    message: str


def evaluate_ticker(
    quote: dict,
    cfg: dict,
    defaults: dict,
    client: Client,
    cooldown_hours: int,
) -> list[AlertEvent]:
    """Valuta tutte le condizioni per un ticker e ritorna gli alert da firare
    (già filtrati per cooldown). Aggiorna lo state in DB.
    """
    events: list[AlertEvent] = []
    sym = quote["symbol"]
    price = quote["price"]
    pct = quote["pct_change"]

    # ---- 1) Variazione intraday (up/down trattati come condizioni distinte) ----
    threshold = cfg.get("intraday_threshold_pct", defaults["intraday_threshold_pct"])
    if pct is not None and abs(pct) >= threshold:
        direction = "up" if pct > 0 else "down"
        opposite = "down" if direction == "up" else "up"
        cond_key = f"intraday_{direction}"
        if _should_fire(client, sym, cond_key, cooldown_hours):
            events.append(AlertEvent(
                symbol=sym, condition="intraday", direction=direction,
                price=price, pct_change=pct, threshold=threshold,
                message=_fmt_intraday(cfg, sym, price, pct, threshold),
            ))
            db.upsert_alert_state(client, sym, cond_key, "triggered", price, mark_alerted=True)
        # reset della direzione opposta (il prezzo si è mosso lontano da quella zona)
        db.upsert_alert_state(client, sym, f"intraday_{opposite}", "normal", price)
    else:
        # zona neutra: reset entrambe le direzioni
        db.upsert_alert_state(client, sym, "intraday_up", "normal", price)
        db.upsert_alert_state(client, sym, "intraday_down", "normal", price)

    # ---- 2) Stop loss / Take profit (vs entry_price) ----
    entry = cfg.get("entry_price")
    if entry and not cfg.get("notify_only"):
        pnl = (price - entry) / entry * 100.0

        sl = cfg.get("stop_loss_pct")
        if sl is not None:
            if pnl <= sl:
                if _should_fire(client, sym, "stop_loss", cooldown_hours):
                    events.append(AlertEvent(
                        symbol=sym, condition="stop_loss", direction="down",
                        price=price, pct_change=pnl, threshold=sl,
                        message=_fmt_pnl(cfg, sym, price, entry, pnl, sl, "STOP LOSS"),
                    ))
                    db.upsert_alert_state(client, sym, "stop_loss", "triggered", price, mark_alerted=True)
            else:
                db.upsert_alert_state(client, sym, "stop_loss", "normal", price)

        tp = cfg.get("take_profit_pct")
        if tp is not None:
            if pnl >= tp:
                if _should_fire(client, sym, "take_profit", cooldown_hours):
                    events.append(AlertEvent(
                        symbol=sym, condition="take_profit", direction="up",
                        price=price, pct_change=pnl, threshold=tp,
                        message=_fmt_pnl(cfg, sym, price, entry, pnl, tp, "TAKE PROFIT"),
                    ))
                    db.upsert_alert_state(client, sym, "take_profit", "triggered", price, mark_alerted=True)
            else:
                db.upsert_alert_state(client, sym, "take_profit", "normal", price)

    return events


# ---- helpers ------------------------------------------------------------

def _should_fire(client: Client, symbol: str, cond_key: str, cooldown_hours: int) -> bool:
    """Fira se:
    - state == 'normal' (transizione fresca da zona neutra), oppure
    - state == 'triggered' MA è passato il cooldown (condizione ancora violata).
    """
    state = db.get_alert_state(client, symbol, cond_key)
    if state is None or state.get("state") == "normal":
        return True
    last = state.get("last_alerted_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last_dt >= timedelta(hours=cooldown_hours)


def _fmt_intraday(cfg: dict, sym: str, price: float, pct: float, thr: float) -> str:
    arrow = "🟢 ▲" if pct > 0 else "🔴 ▼"
    name = cfg.get("name", sym)
    return (
        f"{arrow} *{name}* (`{sym}`)\n"
        f"Variazione intraday: *{pct:+.2f}%*  _(soglia ±{thr}%)_\n"
        f"Prezzo: `{price:.4f}` EUR"
    )


def _fmt_pnl(cfg: dict, sym: str, price: float, entry: float,
             pnl: float, thr: float, label: str) -> str:
    arrow = "🟢 ▲" if pnl > 0 else "🔴 ▼"
    name = cfg.get("name", sym)
    return (
        f"{arrow} *{label}* — {name} (`{sym}`)\n"
        f"P&L vs ingresso ({entry:.4f} EUR): *{pnl:+.2f}%*  _(soglia {thr:+}%)_\n"
        f"Prezzo: `{price:.4f}` EUR"
    )
