-- Resin reminders: one row per user. resin_threshold 0 = "when full". No row = reminders off.
-- armed = true means the next time resin reaches the threshold a message is sent (it is set to false after sending
-- and back to true once resin drops below the threshold). Safe to run more than once.

create table if not exists public.reminders (
    user_id        bigint primary key,
    resin_threshold int not null default 0,
    armed          boolean not null default true,
    session_warned boolean not null default false,
    updated_at     timestamptz not null default now()
);

alter table public.reminders enable row level security;
revoke all on public.reminders from anon, authenticated;
