# tick

Monitoraggio paniere azioni con alert Telegram e dashboard web.
**Zero infrastruttura da gestire**: gira tutto su GitHub Actions + Supabase + Streamlit Cloud.

> Il nome è il tick di prezzo, il tick degli alert, il tick del cron che batte ogni 5 minuti.

## Architettura

```
GitHub Actions (cron */5 min, lun-ven)
    │
    ├─► yfinance         (fetch prezzi)
    ├─► Supabase         (storico + state + alert log)
    └─► Telegram         (push alert)

Streamlit Community Cloud
    └─► legge da Supabase → dashboard
```

## Setup (~30 min)

### 1. Bot Telegram

1. Apri Telegram, cerca `@BotFather`, comando `/newbot`, segui le istruzioni
2. Salva il **TOKEN** che ti viene mostrato (formato `123456:ABC-...`)
3. Apri una chat col tuo bot e mandagli un messaggio qualsiasi
4. Visita nel browser: `https://api.telegram.org/bot<TOKEN>/getUpdates`
5. Cerca `"chat":{"id":NUMERO,...}` → salva il **CHAT_ID** (può essere negativo per i gruppi)

> Se vuoi alert su un gruppo: aggiungi il bot al gruppo come admin e usa il `chat_id` del gruppo.

### 2. Supabase

1. Vai su https://supabase.com e crea un nuovo progetto (free tier)
2. Quando è pronto: **Settings → API**, annota:
   - **Project URL**
   - **service_role key** (sotto "Project API keys") — questa è la chiave server-side, NON committarla
   - **anon public key** — questa è ok per il frontend
3. **SQL Editor → New query**, incolla tutto `schema.sql` e premi Run

### 3. Repo GitHub

1. Fork di questo repo
2. Modifica `config/paniere.yaml` con i tuoi ticker (vedi sezione sotto)
3. Vai su **Settings → Secrets and variables → Actions → New repository secret** e aggiungi:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY` (la **service_role** key)
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. Tab **Actions** → abilita i workflow se richiesto
5. Test: **Actions → "Paniere Poller" → Run workflow** (manual trigger). Aggiungi `SKIP_MARKET_CHECK=1` per forzare il run fuori orario di mercato.

### 4. Dashboard Streamlit

1. Vai su https://share.streamlit.io e fai login con GitHub
2. **New app** → seleziona il tuo fork → main file: `dashboard/streamlit_app.py`
3. **Advanced settings → Secrets** → incolla:
   ```toml
   SUPABASE_URL = "https://xxxxx.supabase.co"
   SUPABASE_KEY = "eyJ...la-anon-key..."
   ```
   (usa la **anon** key qui, è safe — le tabelle hanno RLS con read-only pubblico)
4. Deploy. URL pubblico: `<nome>.streamlit.app`

## Configurazione paniere

Modifica `config/paniere.yaml` e committa. Il prossimo run userà il nuovo paniere.

```yaml
tickers:
  - symbol: ENI.MI                  # ticker yfinance
    name: "Eni"
    entry_price: 14.20              # opzionale: per stop loss / take profit
    stop_loss_pct: -7               # alert quando P&L vs entry <= -7%
    take_profit_pct: 15             # alert quando P&L vs entry >= +15%
    intraday_threshold_pct: 2.5     # alert quando |Δ% intraday| >= 2.5%
```

### Suffissi ticker yfinance

| Borsa | Suffisso | Esempio |
|---|---|---|
| Borsa Italiana | `.MI` | `ENI.MI`, `ISP.MI`, `STLAM.MI` |
| Xetra (DE) | `.DE` | `SAP.DE`, `VOW3.DE` |
| LSE | `.L` | `HSBA.L` |
| Parigi | `.PA` | `MC.PA` (LVMH) |
| NYSE/NASDAQ | — | `AAPL`, `TSLA`, `NVDA` |
| Indici | `^` | `^GSPC` (S&P 500), `^FTMIB` (FTSE MIB), `^STOXX50E` |
| Crypto | `-USD` | `BTC-USD`, `ETH-USD` |

## Logica alert

- **Intraday**: scatta su |Δ% vs apertura giornaliera| ≥ soglia. Direzioni up/down trattate separatamente (puoi avere alert solo down).
- **Stop loss**: scatta su P&L vs `entry_price` ≤ `stop_loss_pct`.
- **Take profit**: scatta su P&L vs `entry_price` ≥ `take_profit_pct`.
- **Dedup**: ogni condizione, una volta scattata, non si re-firea finché non passa `cooldown_hours` (default 4h) o la condizione non si "resetta" (prezzo torna in zona neutra).

## Costi e limiti free tier

| Servizio | Limite | Margine effettivo |
|---|---|---|
| GitHub Actions | 2000 min/mese privato (illimitato pubblico) | ~50 min/giorno → ~25% del budget se privato |
| Supabase | 500 MB DB, sospensione dopo 7gg inattività | Mesi/anni di storico; il poller mantiene attivo |
| Streamlit Cloud | 1 app, sleep dopo 12h | Auto-wake al primo accesso |
| Telegram Bot API | Nessun limite pratico | — |

## Manutenzione storico

Per evitare di saturare i 500 MB di Supabase, esegui periodicamente nel SQL Editor:

```sql
delete from prices where fetched_at < now() - interval '30 days';
delete from alerts where fired_at < now() - interval '180 days';
```

Oppure aggiungi un workflow GitHub Actions schedulato (es. 1 volta/settimana) che chiama una RPC Supabase di pulizia.

## Limiti noti

- **Delay dati**: yfinance scrape Yahoo Finance, che ha delay di ~15 min per Borsa Italiana e quasi tutte le borse non-USA. Real-time vero gratis non esiste per BIT.
- **Granularità cron**: GitHub Actions minimo 5 min, e sotto carico può ritardare di qualche minuto. Non aspettarti precisione al secondo.
- **Streamlit free**: l'app va in sleep dopo 12h senza visite; primo accesso può richiedere ~30s di cold start.
- **Supabase free**: progetto sospeso dopo 7gg di inattività totale. Il poller fa scritture ogni 5 min in orario di mercato, quindi non capita mai in pratica.

## Test in locale

```bash
pip install -r requirements.txt
export SUPABASE_URL=...
export SUPABASE_SERVICE_KEY=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
export SKIP_MARKET_CHECK=1
python -m poller.main
```
