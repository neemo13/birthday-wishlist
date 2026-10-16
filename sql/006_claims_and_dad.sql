-- =====================================================================
-- 006_claims_and_dad.sql  -  family claims/releases and the Dad Only gate
-- Everything returns jsonb {ok, code}; failures RETURN (not raise) so that attempt counters commit.
-- Run 999_storage_and_lockdown.sql again afterwards.
-- =====================================================================

-- ---------- claim a gift ------------------------------------------------
-- Concurrency: the product row is locked FOR UPDATE, so simultaneous claims queue up one by one; the partial
-- unique index claims_one_active_per_product is the independent backstop (even if this function had a bug).
create or replace function public.claim_create(p_token_hash text, p_product_id uuid, p_family_slug text, p_pin text)
returns jsonb language plpgsql set search_path = public, extensions, pg_temp as $$
declare r public.sessions; v_archived boolean; v_hidden boolean; v_id uuid;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null or r.role <> 'family' or r.family_slug is null then
    return jsonb_build_object('ok', false, 'code', 'forbidden');          -- admins don't claim; no anonymous claims
  end if;
  if p_family_slug is distinct from r.family_slug then                       -- the confirmed name must be the signed-in name
    return jsonb_build_object('ok', false, 'code', 'name_mismatch');
  end if;
  if p_pin is null or p_pin !~ '^[0-9]{4,8}$' then
    return jsonb_build_object('ok', false, 'code', 'invalid_pin');
  end if;

  select p.is_archived, coalesce(c.is_hidden, false) into v_archived, v_hidden
    from public.products p left join public.categories c on c.id = p.category_id
   where p.id = p_product_id for update of p;
  if not found or v_archived or v_hidden then
    return jsonb_build_object('ok', false, 'code', 'unavailable');
  end if;
  if exists (select 1 from public.claims where product_id = p_product_id and status = 'active') then
    return jsonb_build_object('ok', false, 'code', 'already_claimed');
  end if;
  begin
    insert into public.claims (product_id, family_slug, pin_hash)
    values (p_product_id, r.family_slug, crypt(p_pin, gen_salt('bf', 10))) returning id into v_id;
  exception when unique_violation then
    return jsonb_build_object('ok', false, 'code', 'already_claimed');
  end;
  perform public._audit('family:' || r.family_slug, 'claim_create', v_id::text, jsonb_build_object('product_id', p_product_id));
  return jsonb_build_object('ok', true, 'claim_id', v_id);
end $$;

-- ---------- release a claim (claimant name + gift PIN) ------------------
-- Name AND PIN are both checked server-side against the ACTIVE claim; a wrong name and a wrong PIN produce the
-- identical generic answer. Verification and release happen in ONE transaction (no verify-then-act gap).
create or replace function public.claim_release(p_token_hash text, p_product_id uuid, p_name text, p_pin text)
returns jsonb language plpgsql set search_path = public, extensions, pg_temp as $$
declare
  r public.sessions; c public.claims; v_name text; v_sess text; v_claim text; v_wait int; v_name_ok boolean; v_pin_ok boolean;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null or r.role <> 'family' or r.family_slug is null then
    return jsonb_build_object('ok', false, 'code', 'forbidden');
  end if;
  select * into c from public.claims where product_id = p_product_id and status = 'active' for update;   -- serialises releases
  if not found then return jsonb_build_object('ok', false, 'code', 'not_claimed'); end if;

  v_sess := 'release_sess:' || p_token_hash;
  v_claim := 'release:' || p_product_id::text;
  v_wait := greatest(public._rl_locked(v_sess), public._rl_locked(v_claim));
  if v_wait > 0 then return jsonb_build_object('ok', false, 'code', 'locked', 'retry_after', v_wait); end if;

  select display_name into v_name from public.family_members where slug = c.family_slug;
  v_name_ok := p_name is not null and char_length(p_name) <= 80 and lower(btrim(p_name)) = lower(btrim(v_name));
  v_pin_ok := p_pin is not null and char_length(p_pin) <= 20 and crypt(p_pin, c.pin_hash) = c.pin_hash;   -- always computed

  if not (v_name_ok and v_pin_ok) then
    perform public._rl_fail(v_sess, 5, interval '15 minutes', interval '15 minutes');
    perform public._rl_fail(v_claim, 5, interval '15 minutes', interval '15 minutes');
    return jsonb_build_object('ok', false, 'code', 'failed');
  end if;

  update public.claims set status = 'released', pin_hash = null, released_at = now(), released_by = 'claimant' where id = c.id;
  perform public._rl_reset(v_claim);
  perform public._rl_reset(v_sess);
  perform public._audit('family:' || r.family_slug, 'claim_release', c.id::text,
                        jsonb_build_object('product_id', p_product_id, 'claimant_slug', c.family_slug));
  return jsonb_build_object('ok', true);
end $$;

-- ---------- Dad Only ----------------------------------------------------
-- Unlock needs: a live FAMILY session whose chosen name is Dad + the separate Dad Only PIN + page enabled.
create or replace function public.dad_unlock(p_token_hash text, p_pin text) returns jsonb
language plpgsql set search_path = public, extensions, pg_temp as $$
declare r public.sessions; v_hash text; v_enabled boolean; v_wait int; v_sess text;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null or r.role <> 'family' or r.family_slug is distinct from 'dad' then
    return jsonb_build_object('ok', false, 'code', 'forbidden');
  end if;
  select secret_hash, enabled into v_hash, v_enabled from public.app_credentials where kind = 'dad_only';
  if not coalesce(v_enabled, false) or v_hash is null then
    return jsonb_build_object('ok', false, 'code', 'unavailable');
  end if;
  v_sess := 'dad_pin_sess:' || p_token_hash;
  v_wait := greatest(public._rl_locked('dad_pin'), public._rl_locked(v_sess));
  if v_wait > 0 then return jsonb_build_object('ok', false, 'code', 'locked', 'retry_after', v_wait); end if;
  if p_pin is null or char_length(p_pin) > 128 or crypt(p_pin, v_hash) <> v_hash then
    perform public._rl_fail('dad_pin', 5, interval '15 minutes', interval '15 minutes');
    perform public._rl_fail(v_sess, 5, interval '15 minutes', interval '15 minutes');
    return jsonb_build_object('ok', false, 'code', 'failed');
  end if;
  perform public._rl_reset('dad_pin');
  perform public._rl_reset(v_sess);
  update public.sessions set dad_unlocked = true where token_hash = p_token_hash;
  perform public._audit('family:dad', 'dad_unlock', null, '{}'::jsonb);
  return jsonb_build_object('ok', true);
end $$;

-- The ONLY function that returns the Dad Only text to a non-admin. Every call re-checks everything, so switching the
-- page off, changing the PIN, or changing the session's name takes effect on the very next request.
create or replace function public.dad_page_get(p_token_hash text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions; v_allowed boolean;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  v_allowed := r.role = 'admin'
    or (r.role = 'family' and r.family_slug = 'dad' and r.dad_unlocked and exists (
          select 1 from public.app_credentials where kind = 'dad_only' and enabled and secret_hash is not null));
  if not v_allowed then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  return jsonb_build_object('ok', true, 'page', (select value from public.app_settings where key = 'dad_page'));
end $$;
