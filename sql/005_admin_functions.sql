-- =====================================================================
-- 005_admin_functions.sql  -  Admin Studio. EVERY function re-verifies an ADMIN session itself.
-- Writes are atomic (one function call = one transaction) and audited.
-- Run 999_storage_and_lockdown.sql again afterwards.
-- =====================================================================

create or replace function public._admin_session(p_token_hash text) returns public.sessions
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null or r.role <> 'admin' then return null; end if;
  return r;
end $$;

-- Everything the studio shows, in one round trip (includes archived + hidden items).
create or replace function public.admin_snapshot(p_token_hash text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  return jsonb_build_object(
    'ok', true,
    'counts', jsonb_build_object(
      'active',   (select count(*) from public.products where not is_archived),
      'archived', (select count(*) from public.products where is_archived),
      'claimed',  (select count(*) from public.products p where not p.is_archived and exists
                    (select 1 from public.claims c where c.product_id = p.id and c.status = 'active')),
      'categories', (select count(*) from public.categories where kind = 'regular')),
    'categories', coalesce((select jsonb_agg(jsonb_build_object(
        'id', c.id, 'name', c.name, 'description', c.description, 'sort_order', c.sort_order,
        'is_hidden', c.is_hidden, 'kind', c.kind,
        'product_count', (select count(*) from public.products p where p.category_id = c.id))
        order by c.sort_order, lower(c.name)) from public.categories c), '[]'::jsonb),
    'products', coalesce((select jsonb_agg(jsonb_build_object(
        'id', p.id, 'name', p.name, 'category_id', p.category_id, 'short_description', p.short_description,
        'price_min', p.price_min, 'price_max', p.price_max, 'preferences', p.preferences, 'notes', p.notes,
        'image_path', p.image_path, 'created_at', p.created_at, 'is_archived', p.is_archived,
        'links', coalesce((select jsonb_agg(jsonb_build_object('source_name', l.source_name, 'url', l.url, 'note', l.note)
                           order by l.sort_order, l.created_at) from public.product_links l where l.product_id = p.id), '[]'::jsonb),
        'claimed', cl.id is not null, 'claimed_by', f.display_name) order by p.created_at desc)
      from public.products p
      left join public.claims cl on cl.product_id = p.id and cl.status = 'active'
      left join public.family_members f on f.slug = cl.family_slug), '[]'::jsonb),
    'claims', coalesce((select jsonb_agg(jsonb_build_object(
        'id', cl.id, 'product_id', cl.product_id, 'product_name', p.name, 'claimant', f.display_name,
        'created_at', cl.created_at) order by cl.created_at desc)
      from public.claims cl join public.products p on p.id = cl.product_id
      join public.family_members f on f.slug = cl.family_slug where cl.status = 'active'), '[]'::jsonb));
end $$;

-- ---------------------------------------------------------------- products
-- p_product: {id?, name, category_id?, short_description, price_min?, price_max?, preferences, notes,
--             image_path? (key present = set/clear), links: [{source_name, url, note}]}
create or replace function public.product_save(p_token_hash text, p_product jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  r public.sessions; v_id uuid; v_old text; v_new text; v_links jsonb; v_created boolean := false;
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  v_links := coalesce(p_product -> 'links', '[]'::jsonb);
  if jsonb_typeof(v_links) <> 'array' then return jsonb_build_object('ok', false, 'code', 'invalid'); end if;
  if jsonb_array_length(v_links) > 10 then return jsonb_build_object('ok', false, 'code', 'too_many_links'); end if;
  v_id := nullif(p_product ->> 'id', '')::uuid;

  begin   -- any constraint failure rolls back this whole block (product AND links)
    if v_id is null then
      insert into public.products (name, category_id, short_description, price_min, price_max, preferences, notes, image_path)
      values (btrim(coalesce(p_product ->> 'name', '')), nullif(p_product ->> 'category_id', '')::uuid,
              coalesce(p_product ->> 'short_description', ''), nullif(p_product ->> 'price_min', '')::numeric,
              nullif(p_product ->> 'price_max', '')::numeric, coalesce(p_product ->> 'preferences', ''),
              coalesce(p_product ->> 'notes', ''), p_product ->> 'image_path')
      returning id into v_id;
      v_created := true;
    else
      select image_path into v_old from public.products where id = v_id for update;
      if not found then return jsonb_build_object('ok', false, 'code', 'not_found'); end if;
      update public.products set
        name = btrim(coalesce(p_product ->> 'name', '')),
        category_id = nullif(p_product ->> 'category_id', '')::uuid,
        short_description = coalesce(p_product ->> 'short_description', ''),
        price_min = nullif(p_product ->> 'price_min', '')::numeric,
        price_max = nullif(p_product ->> 'price_max', '')::numeric,
        preferences = coalesce(p_product ->> 'preferences', ''), notes = coalesce(p_product ->> 'notes', ''),
        image_path = case when p_product ? 'image_path' then p_product ->> 'image_path' else image_path end
      where id = v_id returning image_path into v_new;
    end if;
    delete from public.product_links where product_id = v_id;
    insert into public.product_links (product_id, source_name, url, note, sort_order)
    select v_id, btrim(coalesce(e ->> 'source_name', '')), btrim(coalesce(e ->> 'url', '')), coalesce(e ->> 'note', ''), (ord - 1)::int
    from jsonb_array_elements(v_links) with ordinality as t(e, ord);
  exception
    when check_violation or invalid_text_representation or numeric_value_out_of_range or string_data_right_truncation then
      return jsonb_build_object('ok', false, 'code', 'invalid');
    when foreign_key_violation or raise_exception then
      return jsonb_build_object('ok', false, 'code', 'invalid_category');
  end;

  perform public._audit('admin', case when v_created then 'product_create' else 'product_update' end, v_id::text,
                        jsonb_build_object('name', p_product ->> 'name'));
  return jsonb_build_object('ok', true, 'id', v_id,
    'old_image_path', case when not v_created and v_old is distinct from v_new then v_old end);
end $$;

-- Archive keeps any active claim untouched (nothing is silently discarded); restore brings it back as it was.
create or replace function public.product_set_archived(p_token_hash text, p_id uuid, p_archived boolean) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions; v_claim boolean;
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  update public.products set is_archived = p_archived, archived_at = case when p_archived then now() end where id = p_id;
  if not found then return jsonb_build_object('ok', false, 'code', 'not_found'); end if;
  select exists (select 1 from public.claims where product_id = p_id and status = 'active') into v_claim;
  perform public._audit('admin', case when p_archived then 'product_archive' else 'product_restore' end, p_id::text,
                        jsonb_build_object('had_active_claim', v_claim));
  return jsonb_build_object('ok', true, 'had_active_claim', v_claim);
end $$;

-- ---------------------------------------------------------------- categories
create or replace function public.category_save(p_token_hash text, p_cat jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions; v_id uuid; v_kind text; v_next int;
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  v_id := nullif(p_cat ->> 'id', '')::uuid;
  begin
    if v_id is null then
      select coalesce(max(sort_order), 0) + 10 into v_next from public.categories where kind = 'regular';
      insert into public.categories (name, description, is_hidden, sort_order)
      values (btrim(coalesce(p_cat ->> 'name', '')), coalesce(p_cat ->> 'description', ''),
              coalesce((p_cat ->> 'is_hidden')::boolean, false), coalesce((p_cat ->> 'sort_order')::int, v_next))
      returning id into v_id;
    else
      select kind into v_kind from public.categories where id = v_id for update;
      if not found then return jsonb_build_object('ok', false, 'code', 'not_found'); end if;
      if v_kind = 'dad_only' then          -- the private category: label/description only, never hidden/reordered here
        update public.categories set name = btrim(coalesce(p_cat ->> 'name', '')),
               description = coalesce(p_cat ->> 'description', '') where id = v_id;
      else
        update public.categories set name = btrim(coalesce(p_cat ->> 'name', '')),
               description = coalesce(p_cat ->> 'description', ''),
               is_hidden = coalesce((p_cat ->> 'is_hidden')::boolean, is_hidden),
               sort_order = coalesce((p_cat ->> 'sort_order')::int, sort_order) where id = v_id;
      end if;
    end if;
  exception
    when unique_violation then return jsonb_build_object('ok', false, 'code', 'duplicate');
    when check_violation or invalid_text_representation or numeric_value_out_of_range then
      return jsonb_build_object('ok', false, 'code', 'invalid');
  end;
  perform public._audit('admin', 'category_save', v_id::text, jsonb_build_object('name', p_cat ->> 'name'));
  return jsonb_build_object('ok', true, 'id', v_id);
end $$;

-- Deleting never deletes products: they must be moved (or made uncategorised) first, in the same transaction.
create or replace function public.category_delete(p_token_hash text, p_id uuid,
    p_reassign_to uuid default null, p_uncategorize boolean default false) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions; v_kind text; v_count int;
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  select kind into v_kind from public.categories where id = p_id for update;
  if not found then return jsonb_build_object('ok', false, 'code', 'not_found'); end if;
  if v_kind = 'dad_only' then return jsonb_build_object('ok', false, 'code', 'protected'); end if;
  select count(*) into v_count from public.products where category_id = p_id;   -- includes archived
  if v_count > 0 then
    if p_reassign_to is not null then
      if p_reassign_to = p_id or not exists (select 1 from public.categories where id = p_reassign_to and kind = 'regular') then
        return jsonb_build_object('ok', false, 'code', 'invalid_target');
      end if;
      update public.products set category_id = p_reassign_to where category_id = p_id;
    elsif p_uncategorize then
      update public.products set category_id = null where category_id = p_id;
    else
      return jsonb_build_object('ok', false, 'code', 'has_products', 'count', v_count);
    end if;
  end if;
  delete from public.categories where id = p_id;
  perform public._audit('admin', 'category_delete', p_id::text,
    jsonb_build_object('moved_products', v_count, 'reassigned_to', p_reassign_to, 'uncategorized', p_uncategorize));
  return jsonb_build_object('ok', true, 'moved', v_count);
end $$;

-- ---------------------------------------------------------------- website content
create or replace function public.settings_update(p_token_hash text, p_key text, p_value jsonb) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare
  r public.sessions; v_allowed text[]; v_old text; v_page text; v_ids text[]; v_item jsonb; v_seen text[];
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  if p_key not in ('homepage', 'wishlist', 'sections') or jsonb_typeof(p_value) <> 'object'
     or char_length(p_value::text) > 20000 then
    return jsonb_build_object('ok', false, 'code', 'invalid');
  end if;

  if p_key = 'sections' then
    for v_page, v_ids in select * from (values ('homepage', array['portrait','message','cta']),
                                               ('wishlist', array['intro','search','filters','grid'])) as x(a, b) loop
      v_seen := '{}';
      if jsonb_typeof(p_value -> v_page) <> 'array' then return jsonb_build_object('ok', false, 'code', 'invalid'); end if;
      for v_item in select * from jsonb_array_elements(p_value -> v_page) loop
        if not (v_item ->> 'id') = any (v_ids) or (v_item ->> 'id') = any (v_seen)
           or jsonb_typeof(v_item -> 'visible') <> 'boolean' then
          return jsonb_build_object('ok', false, 'code', 'invalid');
        end if;
        v_seen := v_seen || (v_item ->> 'id');
      end loop;
    end loop;
    if (select count(*) from jsonb_object_keys(p_value)) <> 2 then return jsonb_build_object('ok', false, 'code', 'invalid'); end if;
    insert into public.app_settings (key, value) values ('sections', p_value)
      on conflict (key) do update set value = excluded.value, updated_at = now();
  else
    v_allowed := case p_key when 'homepage' then array['eyebrow','heading','subtitle','message','button_label','portrait_path']
                            else array['heading','intro','currency'] end;
    if exists (select 1 from jsonb_object_keys(p_value) k where not k = any (v_allowed))
       or exists (select 1 from jsonb_each(p_value) e where jsonb_typeof(e.value) not in ('string', 'null')
                  or char_length(e.value #>> '{}') > 2000) then
      return jsonb_build_object('ok', false, 'code', 'invalid');
    end if;
    if p_key = 'homepage' and p_value ? 'portrait_path' then
      select value ->> 'portrait_path' into v_old from public.app_settings where key = 'homepage';
    end if;
    insert into public.app_settings (key, value) values (p_key, p_value)
      on conflict (key) do update set value = public.app_settings.value || excluded.value, updated_at = now();
  end if;
  perform public._audit('admin', 'settings_update', p_key, jsonb_build_object('keys', (select jsonb_agg(k) from jsonb_object_keys(p_value) k)));
  return jsonb_build_object('ok', true, 'old_portrait_path',
    case when v_old is distinct from (p_value ->> 'portrait_path') then v_old end);
end $$;

-- The Dad Only page text. Read here for the editor (admin only); Phase 4 adds the Dad-session read.
create or replace function public.dad_page_get_admin(p_token_hash text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  return jsonb_build_object('ok', true, 'page', (select value from public.app_settings where key = 'dad_page'));
end $$;

create or replace function public.dad_page_set(p_token_hash text, p_title text, p_message text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  if char_length(btrim(coalesce(p_title, ''))) not between 1 and 80
     or char_length(btrim(coalesce(p_message, ''))) not between 1 and 1000 then
    return jsonb_build_object('ok', false, 'code', 'invalid');
  end if;
  insert into public.app_settings (key, value) values ('dad_page', jsonb_build_object('title', btrim(p_title), 'message', btrim(p_message)))
    on conflict (key) do update set value = excluded.value, updated_at = now();
  perform public._audit('admin', 'dad_page_update', null, '{}'::jsonb);   -- text itself is not copied into the log
  return jsonb_build_object('ok', true);
end $$;

-- ---------------------------------------------------------------- claims (admin override) + audit
create or replace function public.claim_admin_release(p_token_hash text, p_claim_id uuid) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions; v_product uuid; v_slug text;
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  update public.claims set status = 'released', pin_hash = null, released_at = now(), released_by = 'admin'
   where id = p_claim_id and status = 'active' returning product_id, family_slug into v_product, v_slug;
  if not found then return jsonb_build_object('ok', false, 'code', 'not_active'); end if;
  perform public._audit('admin', 'claim_release', p_claim_id::text, jsonb_build_object('product_id', v_product, 'claimant_slug', v_slug));
  return jsonb_build_object('ok', true);
end $$;

create or replace function public.audit_recent(p_token_hash text, p_limit int default 20) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  r := public._admin_session(p_token_hash);
  if r.token_hash is null then return jsonb_build_object('ok', false, 'code', 'forbidden'); end if;
  return jsonb_build_object('ok', true, 'items', coalesce((select jsonb_agg(x) from (
    select jsonb_build_object('actor', actor, 'action', action, 'target', target, 'created_at', created_at) x
    from public.audit_log order by id desc limit least(greatest(p_limit, 1), 100)) s), '[]'::jsonb));
end $$;
