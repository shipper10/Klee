-- Group support: per-account sharing consent and per-group on/off switch.
-- Safe to run more than once.

alter table public.game_accounts
    add column if not exists shared_in_groups boolean not null default false;

create table if not exists public.group_settings (
    chat_id         bigint primary key,
    reports_enabled boolean not null default true,
    updated_by      bigint,
    updated_at      timestamptz not null default now()
);

alter table public.group_settings enable row level security;
revoke all on public.group_settings from anon, authenticated;
