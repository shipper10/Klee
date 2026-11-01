-- Klee bot: initial schema. Run once in the Supabase SQL editor.
-- All tables are reachable ONLY with the backend's service-role key:
-- row level security is on and there are deliberately no policies for anon/authenticated.

create table if not exists public.game_accounts (
    id                 uuid primary key default gen_random_uuid(),
    telegram_user_id   bigint not null,
    game_uid           text   not null unique,   -- one Telegram owner per game account (first release)
    region             text   not null,          -- genshin.py server code, e.g. os_asia
    nickname           text,
    is_default         boolean not null default false,
    status             text   not null default 'active'
                       check (status in ('active', 'reauth_required', 'unlinked', 'error')),
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    last_validated_at  timestamptz
);
create index if not exists game_accounts_owner_idx on public.game_accounts (telegram_user_id);
create unique index if not exists game_accounts_one_default_idx
    on public.game_accounts (telegram_user_id) where is_default;

create table if not exists public.account_credentials (
    game_account_id uuid primary key references public.game_accounts (id) on delete cascade,
    ciphertext      text not null,   -- base64 AES-256-GCM output
    nonce           text not null,   -- base64, fresh per encryption
    key_version     text not null,
    updated_at      timestamptz not null default now()
);

create table if not exists public.link_sessions (
    id                uuid primary key default gen_random_uuid(),
    telegram_user_id  bigint not null,
    token_hash        text   not null unique,   -- SHA-256 of the token, never the token itself
    attempts          integer not null default 0,
    expires_at        timestamptz not null,
    consumed_at       timestamptz,
    created_at        timestamptz not null default now()
);

create table if not exists public.activity_cache (
    game_account_id uuid not null references public.game_accounts (id) on delete cascade,
    cache_key       text not null,
    payload         jsonb not null,
    schema_version  integer not null,
    fetched_at      timestamptz not null,
    expires_at      timestamptz not null,
    primary key (game_account_id, cache_key)
);

create table if not exists public.audit_events (
    id                     uuid primary key default gen_random_uuid(),
    actor_telegram_user_id bigint,
    action                 text not null,
    target_type            text,
    target_id              text,
    created_at             timestamptz not null default now()
);

alter table public.game_accounts       enable row level security;
alter table public.account_credentials enable row level security;
alter table public.link_sessions       enable row level security;
alter table public.activity_cache      enable row level security;
alter table public.audit_events        enable row level security;

revoke all on public.game_accounts, public.account_credentials, public.link_sessions,
              public.activity_cache, public.audit_events from anon, authenticated;
