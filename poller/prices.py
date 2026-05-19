"""Fetch quotazioni tramite yfinance, con conversione automatica in EUR.

Tutti i prezzi restituiti sono in EUR, indipendentemente dalla valuta nativa
del ticker. Questo permette di confrontare entry_price (inserito in EUR
nel paniere.yaml) con il prezzo corrente senza preoccuparsi del cambio.
"""
from __future__ import annotations

import yfinance as yf

# Cache module-level dei tassi di cambio per ridurre chiamate ridondanti
# (es. 13 ticker USD condividono lo stesso fetch di USDEUR=X per ogni run)
_fx_cache: dict[str, float] = {}


def _fx_rate(from_ccy: str, to_ccy: str = "EUR") -> float | None:
    """Tasso di cambio from_ccy → to_ccy. Cachato per il run corrente."""
    if from_ccy == to_ccy:
        return 1.0
    key = f"{from_ccy}{to_ccy}"
    if key in _fx_cache:
        return _fx_cache[key]
    try:
        t = yf.Ticker(f"{from_ccy}{to_ccy}=X")
        fi = t.fast_info
        rate = None
        for k in ("last_price", "lastPrice", "regular_market_price"):
            try:
                rate = fi[k]
                if rate:
                    break
            except (KeyError, AttributeError, TypeError):
                continue
        if rate:
            _fx_cache[key] = float(rate)
            return float(rate)
    except Exception as e:
        print(f"[WARN] FX fetch {from_ccy}->{to_ccy} failed: {e}")
    return None


def _fast_get(fi, *keys):
    """Accessor robusto su fast_info (varia tra versioni di yfinance)."""
    for k in keys:
        try:
            v = fi[k]
            if v is not None:
                return v
        except (KeyError, AttributeError, TypeError):
            pass
        if hasattr(fi, k):
            v = getattr(fi, k)
            if v is not None:
                return v
    return None


def fetch_quote(symbol: str, target_currency: str = "EUR") -> dict | None:
    """Restituisce dict con price/open/pct_change/volume convertiti in target_currency,
    o None se il fetch fallisce.

    Δ% intraday è calcolato vs open giornaliero (o previous_close in fallback)
    PRIMA della conversione FX, quindi è invariante al cambio.
    """
    try:
        t = yf.Ticker(symbol)
        fi = t.fast_info

        price = _fast_get(fi, "last_price", "lastPrice", "regular_market_price")
        open_price = _fast_get(fi, "open", "regular_market_open")
        prev_close = _fast_get(fi, "previous_close", "previousClose",
                               "regular_market_previous_close")
        volume = _fast_get(fi, "last_volume", "lastVolume", "regular_market_volume")
        native_ccy = _fast_get(fi, "currency") or "EUR"
        native_ccy = str(native_ccy).upper()

        if price is None:
            return None

        # LSE quotano spesso in pence (GBp/GBX): yfinance restituisce un numero
        # 100x troppo grande. Normalizziamo in GBP.
        if native_ccy in ("GBX", "GBP.", "PENCE", "GBP_PENCE") or native_ccy == "GBP" and price > 1000 and symbol.endswith(".L"):
            # Euristica: se native_ccy è già "GBP" ma il prezzo è >1000 su un .L
            # è quasi certamente un ETC/ETF quotato in pence
            price = float(price) / 100.0
            if open_price: open_price = float(open_price) / 100.0
            if prev_close: prev_close = float(prev_close) / 100.0
            native_ccy = "GBP"
            print(f"[INFO] {symbol}: detected GBX pricing, normalized to GBP")

        # Δ% intraday calcolato in valuta nativa (invariante al cambio FX intraday)
        ref = open_price or prev_close
        pct = ((float(price) - float(ref)) / float(ref) * 100.0) if ref else None

        # Conversione FX (1.0 se native_ccy == target_currency)
        fx = _fx_rate(native_ccy, target_currency)
        if fx is None:
            print(f"[WARN] {symbol}: no FX rate {native_ccy}->{target_currency}, "
                  f"price restituito in valuta nativa")
            fx = 1.0

        return {
            "symbol": symbol,
            "price": float(price) * fx,
            "open_price": float(open_price) * fx if open_price else None,
            "pct_change": float(pct) if pct is not None else None,
            "volume": int(volume) if volume else None,
            "currency": target_currency,
            "native_currency": native_ccy,
            "fx_rate": fx,
        }
    except Exception as e:
        print(f"[WARN] fetch_quote({symbol}) failed: {e}")
        return None
