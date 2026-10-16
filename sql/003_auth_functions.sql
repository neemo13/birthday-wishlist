-- =====================================================================
-- 003_auth_functions.sql  -  login, sessions, credentials, rate limiting
-- All functions are callable ONLY by service_role (see 999_*.sql).
-- Functions return jsonb {ok, code, ...} instead of raising, so that a
-- failed-attempt counter commits even when the attempt fails.
-- =====================================================================

-- ---------- internal helpers -----------------------------------------
create or replace function public._setting_int(p_key text, p_field text, p_default int)
returns int language sql stable set search_path = public, pg_temp as $$
  select coalesce((select (value ->> p_field)::int from public.app_settings where key = p_key), p_default)
$$;

create or replace function public._audit(p_actor text, p_action text, p_target text, p_details jsonb)
returns void language sql set search_path = public, pg_temp as $$
  insert into public.audit_log (actor, action, target, details)
  values (p_actor, p_action, p_target, coalesce(p_details, '{}'::jsonb))
$$;

-- seconds left on a lockout (0 = not locked)
create or replace function public._rl_locked(p_scope text) returns int
language sql stable set search_path = public, pg_temp as $$
  select coalesce((
    select ceil(extract(epoch from (locked_until - now())))::int
    from public.rate_limits where scope = p_scope and locked_until > now()
  ), 0)
$$;

create or replace function public._rl_fail(p_scope text, p_max int, p_window interval, p_lock interval)
returns void language plpgsql set search_path = public, pg_temp as $$
begin
  insert into public.rate_limits (scope, fail_count, window_start) values (p_scope, 1, now())
  on conflict (scope) do update set
    fail_count   = case when public.rate_limits.window_start < now() - p_window
                        then 1 else public.rate_limits.fail_count + 1 end,
    window_start = case when public.rate_limits.window_start < now() - p_window
                        then now() else public.rate_limits.window_start end;
  update public.rate_limits
     set locked_until = now() + p_lock, fail_count = 0, window_start = now()
   where scope = p_scope and fail_count >= p_max;
end $$;

create or replace function public._rl_reset(p_scope text) returns void
language sql set search_path = public, pg_temp as $$
  delete from public.rate_limits where scope = p_scope
$$;

-- Returns the session row if the token is known, unexpired and not idle; else an all-null row.
create or replace function public._session_check(p_token_hash text) returns public.sessions
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  if p_token_hash is null then return null; end if;
  select * into r from public.sessions where token_hash = p_token_hash;
  if not found then return null; end if;
  if r.expires_at <= now()
     or r.last_seen < now() - make_interval(mins => public._setting_int('security', 'idle_minutes', 60)) then
    delete from public.sessions where token_hash = p_token_hash;
    return null;
  end if;
  return r;
end $$;

-- ---------- login -----------------------------------------------------
create or replace function public.auth_login(p_role text, p_secret text, p_token_hash text)
returns jsonb language plpgsql set search_path = public, extensions, pg_temp as $$
declare
  v_hash text; v_enabled boolean; v_wait int; v_scope text; v_ok boolean;
begin
  if p_role not in ('admin', 'family') or p_secret is null
     or char_length(p_secret) = 0 or char_length(p_secret) > 200
     or p_token_hash is null or char_length(p_token_hash) < 32 then
    return jsonb_build_object('ok', false, 'code', 'invalid');
  end if;

  v_scope := 'login:' || p_role;
  v_wait := public._rl_locked(v_scope);
  if v_wait > 0 then
    return jsonb_build_object('ok', false, 'code', 'locked', 'retry_after', v_wait);
  end if;

  select secret_hash, enabled into v_hash, v_enabled from public.app_credentials where kind = p_role;
  v_ok := coalesce(v_enabled, false) and v_hash is not null and crypt(p_secret, v_hash) = v_hash;

  if not v_ok then
    if v_hash is null then perform crypt(p_secret, gen_salt('bf', 10)); end if;  -- keep timing similar
    perform public._rl_fail(v_scope, 8, interval '15 minutes', interval '15 minutes');
    return jsonb_build_object('ok', false, 'code', 'invalid');
  end if;

  perform public._rl_reset(v_scope);
  delete from public.sessions where expires_at < now();
  insert into public.sessions (token_hash, role, expires_at)
  values (p_token_hash, p_role, now() + make_interval(hours => public._setting_int('security', 'session_hours', 8)));
  return jsonb_build_object('ok', true, 'role', p_role);
end $$;

-- ---------- session read / name selection / logout -------------------
create or replace function public.session_get(p_token_hash text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions; v_name text;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('valid', false); end if;
  update public.sessions set last_seen = now() where token_hash = p_token_hash;
  select display_name into v_name from public.family_members where slug = r.family_slug;
  return jsonb_build_object(
    'valid', true, 'role', r.role, 'family_slug', r.family_slug, 'display_name', v_name,
    'is_dad', coalesce(r.family_slug = 'dad', false), 'dad_unlocked', r.dad_unlocked,
    'expires_at', r.expires_at);
end $$;

-- Choosing a name only labels the session. It is NOT identity verification
-- (the Dad Only PIN is the real gate), and it always re-locks Dad Only.
create or replace function public.session_set_family(p_token_hash text, p_slug text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null or r.role <> 'family' then
    return jsonb_build_object('ok', false, 'code', 'forbidden');
  end if;
  if not exists (select 1 from public.family_members where slug = p_slug) then
    return jsonb_build_object('ok', false, 'code', 'invalid');
  end if;
  update public.sessions set family_slug = p_slug, dad_unlocked = false where token_hash = p_token_hash;
  return jsonb_build_object('ok', true);
end $$;

create or replace function public.session_destroy(p_token_hash text) returns void
language sql set search_path = public, pg_temp as $$
  delete from public.sessions where token_hash = p_token_hash
$$;

-- ---------- credential management ------------------------------------
create or replace function public.credential_status(p_token_hash text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null or r.role <> 'admin' then
    return jsonb_build_object('ok', false, 'code', 'forbidden');
  end if;
  return jsonb_build_object('ok', true, 'items', (
    select jsonb_agg(jsonb_build_object('kind', kind, 'configured', secret_hash is not null, 'enabled', enabled)
                     order by kind)
    from public.app_credentials));
end $$;

-- Admin changes a credential. Requires a live admin session AND the current
-- admin password again (step-up), with its own attempt limiter.
create or replace function public.credential_change(
  p_token_hash text, p_admin_password text, p_kind text,
  p_new_secret text default null, p_enabled boolean default null) returns jsonb
language plpgsql set search_path = public, extensions, pg_temp as $$
declare
  s public.sessions; v_wait int; v_admin_hash text; v_min int; v_has_secret boolean;
begin
  s := public._session_check(p_token_hash);
  if s.token_hash is null or s.role <> 'admin' then
    return jsonb_build_object('ok', false, 'code', 'forbidden');
  end if;
  if p_kind not in ('family', 'admin', 'dad_only') then
    return jsonb_build_object('ok', false, 'code', 'invalid');
  end if;

  v_wait := public._rl_locked('reauth:admin');
  if v_wait > 0 then
    return jsonb_build_object('ok', false, 'code', 'locked', 'retry_after', v_wait);
  end if;
  select secret_hash into v_admin_hash from public.app_credentials where kind = 'admin';
  if p_admin_password is null or v_admin_hash is null or crypt(p_admin_password, v_admin_hash) <> v_admin_hash then
    perform public._rl_fail('reauth:admin', 5, interval '15 minutes', interval '15 minutes');
    return jsonb_build_object('ok', false, 'code', 'wrong_password');
  end if;
  perform public._rl_reset('reauth:admin');

  v_min := case p_kind when 'admin' then 12 else 6 end;
  if p_new_secret is not null and (char_length(p_new_secret) < v_min or char_length(p_new_secret) > 128) then
    return jsonb_build_object('ok', false, 'code', 'weak_secret', 'min_length', v_min);
  end if;
  if p_kind = 'admin' and p_enabled is false then
    return jsonb_build_object('ok', false, 'code', 'cannot_disable_admin');
  end if;
  select (secret_hash is not null) into v_has_secret from public.app_credentials where kind = p_kind;
  if p_enabled is true and not (coalesce(v_has_secret, false) or p_new_secret is not null) then
    return jsonb_build_object('ok', false, 'code', 'no_secret');
  end if;

  if p_new_secret is not null then
    update public.app_credentials
       set secret_hash = crypt(p_new_secret, gen_salt('bf', 10)), updated_at = now()
     where kind = p_kind;
  end if;
  if p_enabled is not null then
    update public.app_credentials set enabled = p_enabled, updated_at = now() where kind = p_kind;
  end if;

  -- Invalidate sessions that relied on the old credential.
  if p_kind = 'family' and (p_new_secret is not null or p_enabled is false) then
    delete from public.sessions where role = 'family';
  elsif p_kind = 'admin' and p_new_secret is not null then
    delete from public.sessions where role = 'admin' and token_hash <> p_token_hash;
  elsif p_kind = 'dad_only' and (p_new_secret is not null or p_enabled is false) then
    update public.sessions set dad_unlocked = false;
  end if;

  perform public._audit('admin', 'credential_change', p_kind,
    jsonb_build_object('secret_changed', p_new_secret is not null, 'enabled', p_enabled));
  return jsonb_build_object('ok', true);
end $$;

-- First-time setup (and emergency rotation) from the command line:
--   python scripts/set_credential.py admin
-- No session needed; only service_role can execute it. Refuses to overwrite
-- an existing secret unless p_force is true.
create or replace function public.credential_bootstrap(p_kind text, p_secret text, p_force boolean default false)
returns jsonb language plpgsql set search_path = public, extensions, pg_temp as $$
declare v_min int; v_existing text;
begin
  if p_kind not in ('family', 'admin', 'dad_only') then
    return jsonb_build_object('ok', false, 'code', 'invalid');
  end if;
  v_min := case p_kind when 'admin' then 12 else 6 end;
  if p_secret is null or char_length(p_secret) < v_min or char_length(p_secret) > 128 then
    return jsonb_build_object('ok', false, 'code', 'weak_secret', 'min_length', v_min);
  end if;
  select secret_hash into v_existing from public.app_credentials where kind = p_kind;
  if v_existing is not null and not p_force then
    return jsonb_build_object('ok', false, 'code', 'already_set');
  end if;
  update public.app_credentials
     set secret_hash = crypt(p_secret, gen_salt('bf', 10)), enabled = true, updated_at = now()
   where kind = p_kind;
  if p_kind = 'dad_only' then
    update public.sessions set dad_unlocked = false;
  else
    delete from public.sessions where role = case p_kind when 'admin' then 'admin' else 'family' end;
  end if;
  perform public._rl_reset('login:' || p_kind);
  perform public._audit('system', 'credential_bootstrap', p_kind, jsonb_build_object('forced', p_force));
  return jsonb_build_object('ok', true);
end $$;

-- ---------- family display names (admin only, atomic) ----------------
-- p_names: {"grandmother": "...", "brother": "...", "mom": "...", "dad": "..."}
create or replace function public.family_rename(p_token_hash text, p_names jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  s public.sessions; v_slug text; v_name text; v_seen text[] := '{}';
begin
  s := public._session_check(p_token_hash);
  if s.token_hash is null or s.role <> 'admin' then
    return jsonb_build_object('ok', false, 'code', 'forbidden');
  end if;
  for v_slug in select slug from public.family_members loop
    v_name := btrim(coalesce(p_names ->> v_slug, ''));
    if char_length(v_name) not between 1 and 40 then
      return jsonb_build_object('ok', false, 'code', 'invalid_name');
    end if;
    if lower(v_name) = any (v_seen) then
      return jsonb_build_object('ok', false, 'code', 'duplicate_name');
    end if;
    v_seen := v_seen || lower(v_name);
  end loop;
  -- Two passes so swapping names never trips the unique index; one transaction = all or nothing.
  update public.family_members set display_name = '~tmp-' || slug;
  for v_slug in select slug from public.family_members loop
    update public.family_members set display_name = btrim(p_names ->> v_slug) where slug = v_slug;
  end loop;
  perform public._audit('admin', 'family_rename', null, p_names);
  return jsonb_build_object('ok', true);
end $$;

-- Any live session may read the four display names (needed for the name picker and claim forms).
create or replace function public.family_list(p_token_hash text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null then
    return jsonb_build_object('ok', false, 'code', 'forbidden');
  end if;
  return jsonb_build_object('ok', true, 'items', (
    select jsonb_agg(jsonb_build_object('slug', slug, 'display_name', display_name) order by sort_order)
    from public.family_members));
end $$;
