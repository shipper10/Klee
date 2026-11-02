-- Image style preferences. user_id 0 = the owner's default for everyone. service '*' = all services.
-- Safe to run more than once.

create table if not exists public.style_prefs (
    user_id    bigint not null,
    service    text   not null,
    style      text   not null,
    updated_at timestamptz not null default now(),
    primary key (user_id, service)
);

alter table public.style_prefs enable row level security;
revoke all on public.style_prefs from anon, authenticated;
