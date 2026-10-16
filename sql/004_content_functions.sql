-- =====================================================================
-- 004_content_functions.sql  -  read paths for the homepage and wishlist
-- Every function verifies the session itself. Re-run 999_* afterwards.
-- =====================================================================

-- Non-secret website content. Explicit allow-list: 'dad_page' and 'security' can never leak from here.
create or replace function public.settings_get(p_token_hash text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null or (r.role = 'family' and r.family_slug is null) then
    return jsonb_build_object('ok', false, 'code', 'forbidden');
  end if;
  return jsonb_build_object('ok', true, 'settings', coalesce((
    select jsonb_object_agg(key, value) from public.app_settings
    where key in ('homepage', 'wishlist', 'sections')), '{}'::jsonb));
end $$;

-- Everything the wishlist needs in ONE round trip: visible categories + non-archived products
-- with their links and claim status. Visibility rules are decided here, in the database:
--   * archived products never appear;  hidden categories (and their products) never appear;
--   * the Dad Only category row is returned only to the admin, or to a Dad-named session while the page is enabled
--     (it never holds products - a trigger guarantees that);
--   * claim PIN hashes are never selected.
create or replace function public.catalog_list(p_token_hash text) returns jsonb
language plpgsql set search_path = public, pg_temp as $$
declare r public.sessions; v_see_dad boolean;
begin
  r := public._session_check(p_token_hash);
  if r.token_hash is null or (r.role = 'family' and r.family_slug is null) then
    return jsonb_build_object('ok', false, 'code', 'forbidden');
  end if;
  -- Dad sees the Dad Only category row only while the page is switched on AND has a PIN; the admin always does.
  v_see_dad := r.role = 'admin' or (r.family_slug = 'dad' and exists (
      select 1 from public.app_credentials where kind = 'dad_only' and enabled and secret_hash is not null));

  return jsonb_build_object(
    'ok', true,
    'categories', coalesce((
      select jsonb_agg(jsonb_build_object('id', c.id, 'name', c.name, 'description', c.description, 'kind', c.kind)
                       order by c.sort_order, lower(c.name))
      from public.categories c
      where not c.is_hidden and (c.kind = 'regular' or v_see_dad)), '[]'::jsonb),
    'products', coalesce((
      select jsonb_agg(jsonb_build_object(
        'id', p.id, 'name', p.name, 'category_id', p.category_id,
        'short_description', p.short_description,
        'price_min', p.price_min, 'price_max', p.price_max,
        'preferences', p.preferences, 'notes', p.notes, 'image_path', p.image_path,
        'created_at', p.created_at,
        'links', coalesce((select jsonb_agg(jsonb_build_object(
                    'source_name', l.source_name, 'url', l.url, 'note', l.note) order by l.sort_order, l.created_at)
                  from public.product_links l where l.product_id = p.id), '[]'::jsonb),
        'claimed', cl.id is not null,
        'claimed_by', f.display_name) order by p.created_at desc)
      from public.products p
      left join public.categories c on c.id = p.category_id
      left join public.claims cl on cl.product_id = p.id and cl.status = 'active'
      left join public.family_members f on f.slug = cl.family_slug
      where not p.is_archived and (c.id is null or not c.is_hidden)), '[]'::jsonb));
end $$;
