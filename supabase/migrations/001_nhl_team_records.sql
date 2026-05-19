-- Run in Supabase SQL editor (or via supabase db push).
-- Stores NHL team records refreshed hourly by TeamGM-LLM-API.

create table if not exists public.nhl_team_records (
  season integer not null,
  team_id integer not null,
  team_name text not null,
  wins integer not null default 0,
  losses integer not null default 0,
  ot_losses integer not null default 0,
  record text not null,
  standing text,
  points integer,
  position integer,
  updated_at timestamptz not null default now(),
  primary key (season, team_id)
);

create index if not exists nhl_team_records_season_idx
  on public.nhl_team_records (season);

alter table public.nhl_team_records enable row level security;

alter table public.nhl_team_records
  add column if not exists standing text;

-- Service role bypasses RLS; block anonymous reads by default.
create policy "nhl_team_records_service_only"
  on public.nhl_team_records
  for all
  using (false);
