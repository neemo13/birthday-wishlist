-- =====================================================================
-- 001_schema.sql  -  tables, constraints, indexes, triggers
-- Run in the Supabase SQL Editor. Safe to re-run (idempotent).
--
-- SECURITY MODEL (read this once):
--   * The Streamlit server talks to Supabase with the *service_role* key.
--   * Every table has Row Level Security ENABLED and NO policies, and all
--     grants to anon/authenticated are revoked (see 999_*.sql). So even if
--     the public anon key leaks, it can read and write nothing.
--   * Secrets (family PIN, admin password, Dad Only PIN, gift PINs) are
--     stored only as bcrypt hashes (pgcrypto) and verified inside Postgres.
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;

create or replace function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ---------- settings (editable website content) ----------------------
create table if not exists public.app_settings (
  key         text primary key,
  value       jsonb not null,
  updated_at  timestamptz not null default now()
);

-- ---------- credentials (hashes only) --------------------------------
create table if not exists public.app_credentials (
  kind         text primary key check (kind in ('family', 'admin', 'dad_only')),
  secret_hash  text,
  enabled      boolean not null default true,
  updated_at   timestamptz not null default now()
);

-- ---------- brute-force protection -----------------------------------
create table if not exists public.rate_limits (
  scope         text primary key,
  fail_count    int not null default 0,
  window_start  timestamptz not null default now(),
  locked_until  timestamptz
);

-- ---------- family display names (4 fixed roles, editable labels) ----
create table if not exists public.family_members (
  slug          text primary key check (slug in ('grandmother', 'brother', 'mom', 'dad')),
  display_name  text not null check (char_length(btrim(display_name)) between 1 and 40),
  sort_order    int not null default 0
);
create unique index if not exists family_members_name_uq
  on public.family_members (lower(btrim(display_name)));

-- ---------- categories ------------------------------------------------
create table if not exists public.categories (
  id           uuid primary key default gen_random_uuid(),
  name         text not null check (char_length(btrim(name)) between 1 and 60),
  description  text not null default '' check (char_length(description) <= 300),
  sort_order   int not null default 0,
  is_hidden    boolean not null default false,
  kind         text not null default 'regular' check (kind in ('regular', 'dad_only')),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
create unique index if not exists categories_name_uq on public.categories (lower(btrim(name)));
create unique index if not exists categories_one_dad_only on public.categories (kind) where kind = 'dad_only';

drop trigger if exists categories_updated on public.categories;
create trigger categories_updated before update on public.categories
  for each row execute function public.set_updated_at();

-- The Dad Only category can never be deleted or turned into a regular category.
create or replace function public.protect_dad_only_category() returns trigger
language plpgsql as $$
begin
  if tg_op = 'DELETE' and old.kind = 'dad_only' then
    raise exception 'The Dad Only category cannot be deleted';
  end if;
  if tg_op = 'UPDATE' and old.kind <> new.kind then
    raise exception 'A category cannot change its kind';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end $$;
drop trigger if exists categories_protect on public.categories;
create trigger categories_protect before update or delete on public.categories
  for each row execute function public.protect_dad_only_category();

-- ---------- products --------------------------------------------------
create table if not exists public.products (
  id                 uuid primary key default gen_random_uuid(),
  name               text not null check (char_length(btrim(name)) between 1 and 120),
  category_id        uuid references public.categories (id) on delete restrict,  -- null = uncategorized
  short_description  text not null default '' check (char_length(short_description) <= 300),
  price_min          numeric(10, 2) check (price_min is null or price_min >= 0),
  price_max          numeric(10, 2) check (price_max is null or price_max >= 0),
  preferences        text not null default '' check (char_length(preferences) <= 2000),
  notes              text not null default '' check (char_length(notes) <= 2000),
  image_path         text check (image_path is null or char_length(image_path) <= 300),
  is_archived        boolean not null default false,
  archived_at        timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint products_price_range_ok check (price_min is null or price_max is null or price_min <= price_max)
);
create index if not exists products_category_idx on public.products (category_id);
create index if not exists products_created_idx on public.products (created_at desc);
create index if not exists products_archived_idx on public.products (is_archived);

drop trigger if exists products_updated on public.products;
create trigger products_updated before update on public.products
  for each row execute function public.set_updated_at();

-- Dad Only is a message page, not a catalogue: products may never live in it.
create or replace function public.forbid_dad_only_products() returns trigger
language plpgsql as $$
begin
  if new.category_id is not null
     and exists (select 1 from public.categories c where c.id = new.category_id and c.kind = 'dad_only') then
    raise exception 'Products cannot be placed in the Dad Only category';
  end if;
  return new;
end $$;
drop trigger if exists products_no_dad_only on public.products;
create trigger products_no_dad_only before insert or update of category_id on public.products
  for each row execute function public.forbid_dad_only_products();

-- ---------- shopping-source links (0..n per product) ------------------
create table if not exists public.product_links (
  id           uuid primary key default gen_random_uuid(),
  product_id   uuid not null references public.products (id) on delete cascade,
  source_name  text not null check (char_length(btrim(source_name)) between 1 and 60),
  url          text not null check (url ~* '^https?://[^[:space:]]+$' and char_length(url) <= 2000),
  note         text not null default '' check (char_length(note) <= 200),
  sort_order   int not null default 0,
  created_at   timestamptz not null default now()
);
create index if not exists product_links_product_idx on public.product_links (product_id, sort_order);

-- ---------- claims ----------------------------------------------------
-- A product is "Claimed" iff it has a row here with status = 'active'.
-- The partial unique index is the database-level guarantee of at most one
-- active claim per product, no matter what the app does.
create table if not exists public.claims (
  id           uuid primary key default gen_random_uuid(),
  product_id   uuid not null references public.products (id) on delete restrict,
  family_slug  text not null references public.family_members (slug),
  pin_hash     text,                       -- bcrypt; NULLed on release
  status       text not null default 'active' check (status in ('active', 'released')),
  created_at   timestamptz not null default now(),
  released_at  timestamptz,
  released_by  text check (released_by in ('claimant', 'admin')),
  constraint claims_state_ok check (
    (status = 'active'   and pin_hash is not null and released_at is null) or
    (status = 'released' and pin_hash is null     and released_at is not null)
  )
);
create unique index if not exists claims_one_active_per_product
  on public.claims (product_id) where status = 'active';
create index if not exists claims_product_idx on public.claims (product_id);

-- ---------- server-side login sessions -------------------------------
-- The browser never holds a role; it holds (in Streamlit's server memory)
-- a random token whose SHA-256 hash is the key here.
create table if not exists public.sessions (
  token_hash    text primary key,
  role          text not null check (role in ('admin', 'family')),
  family_slug   text references public.family_members (slug),
  dad_unlocked  boolean not null default false,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null,
  last_seen     timestamptz not null default now()
);
create index if not exists sessions_expires_idx on public.sessions (expires_at);

-- ---------- audit log -------------------------------------------------
create table if not exists public.audit_log (
  id          bigint generated always as identity primary key,
  actor       text not null,
  action      text not null,
  target      text,
  details     jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now()
);
create index if not exists audit_log_created_idx on public.audit_log (created_at desc);

-- ---------- Row Level Security: enabled, deliberately no policies -----
alter table public.app_settings    enable row level security;
alter table public.app_credentials enable row level security;
alter table public.rate_limits     enable row level security;
alter table public.family_members  enable row level security;
alter table public.categories      enable row level security;
alter table public.products        enable row level security;
alter table public.product_links   enable row level security;
alter table public.claims          enable row level security;
alter table public.sessions        enable row level security;
alter table public.audit_log       enable row level security;
