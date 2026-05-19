-- Eseguire una volta nel SQL Editor di Supabase

-- ====== TABELLE ======

-- Storico prezzi (append-only)
create table if not exists prices (
    id          bigserial primary key,
    symbol      text not null,
    price       numeric not null,
    open_price  numeric,
    pct_change  numeric,
    volume      bigint,
    fetched_at  timestamptz not null default now()
);
create index if not exists idx_prices_symbol_time on prices (symbol, fetched_at desc);

-- Log degli alert firati (append-only, per cronologia in dashboard)
create table if not exists alerts (
    id          bigserial primary key,
    symbol      text not null,
    condition   text not null,    -- 'intraday' | 'stop_loss' | 'take_profit'
    direction   text not null,    -- 'up' | 'down'
    price       numeric not null,
    pct_change  numeric,
    threshold   numeric,
    message     text,
    fired_at    timestamptz not null default now()
);
create index if not exists idx_alerts_time on alerts (fired_at desc);

-- State per dedup (upsert)
create table if not exists alert_state (
    symbol            text not null,
    condition         text not null,   -- es. 'intraday_up', 'intraday_down', 'stop_loss', 'take_profit'
    state             text not null,   -- 'normal' | 'triggered'
    last_alerted_at   timestamptz,
    last_price        numeric,
    primary key (symbol, condition)
);

-- ====== ROW LEVEL SECURITY ======
-- La service_role key bypassa RLS (usata dal poller GitHub Actions).
-- La anon key rispetta RLS (usata dalla dashboard Streamlit per sola lettura).

alter table prices       enable row level security;
alter table alerts       enable row level security;
alter table alert_state  enable row level security;

-- Lettura pubblica di prices e alerts (per la dashboard)
drop policy if exists "Public read prices" on prices;
create policy "Public read prices" on prices for select using (true);

drop policy if exists "Public read alerts" on alerts;
create policy "Public read alerts" on alerts for select using (true);

-- alert_state non esposto in lettura pubblica (solo service_role può leggerlo/scriverlo)
