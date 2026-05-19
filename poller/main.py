"""Entry point del poller. Invocato da GitHub Actions ogni 5 minuti."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import alerts, db, prices, telegram_client

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "paniere.yaml"


def is_any_market_open(market_hours: list[dict], now: datetime | None = None) -> bool:
    """True se almeno una finestra di mercato è aperta a 'now' (UTC)."""
    now = now or datetime.now(timezone.utc)
    weekday = now.weekday()  # 0=lun, 6=dom
    hhmm = now.strftime("%H:%M")
    for m in market_hours:
        if weekday in m["days"] and m["start"] <= hhmm <= m["end"]:
            return True
    return False


def main() -> int:
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    defaults = cfg["defaults"]
    market_hours = cfg.get("market_hours_utc", [])

    # Skip se fuori orario (settare SKIP_MARKET_CHECK=1 per forzare in test)
    if market_hours and not os.environ.get("SKIP_MARKET_CHECK"):
        if not is_any_market_open(market_hours):
            print("Mercati chiusi, skip.")
            return 0

    client = db.get_client()
    cooldown = defaults["cooldown_hours"]

    fired = 0
    for tcfg in cfg["tickers"]:
        symbol = tcfg["symbol"]
        quote = prices.fetch_quote(symbol)
        if not quote:
            print(f"[SKIP] no quote for {symbol}")
            continue

        # storico prezzo
        try:
            db.insert_price(
                client, symbol, quote["price"],
                quote["open_price"], quote["pct_change"], quote["volume"],
            )
        except Exception as e:
            print(f"[ERR] insert_price({symbol}) failed: {e}")

        # valutazione alert
        try:
            events = alerts.evaluate_ticker(quote, tcfg, defaults, client, cooldown)
        except Exception as e:
            print(f"[ERR] evaluate_ticker({symbol}) failed: {e}")
            continue

        for ev in events:
            ok = telegram_client.send_message(ev.message)
            if ok:
                try:
                    db.insert_alert(
                        client, ev.symbol, ev.condition, ev.direction,
                        ev.price, ev.pct_change, ev.threshold, ev.message,
                    )
                except Exception as e:
                    print(f"[ERR] insert_alert({ev.symbol}) failed: {e}")
                fired += 1
                print(f"[ALERT] {ev.symbol} {ev.condition} {ev.direction} {ev.pct_change:+.2f}%")

    print(f"Done. Fired {fired} alert(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
