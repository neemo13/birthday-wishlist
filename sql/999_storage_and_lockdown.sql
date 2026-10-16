-- =====================================================================
-- 999_storage_and_lockdown.sql  -  RUN LAST, and re-run after any other migration.
-- Idempotent. (1) private image bucket  (2) lock everything to service_role.
-- =====================================================================

-- ---------- private Storage bucket for portrait + product photos -----
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('wishlist-images', 'wishlist-images', false, 5242880,
        array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update
  set public = false, file_size_limit = 5242880,
      allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp'];
-- No storage.objects policies are created on purpose: anon/authenticated
-- users get NO access. The Streamlit server (service_role) uploads files and
-- hands out short-lived signed URLs only to logged-in sessions.

-- ---------- lock the public schema down to service_role ---------------
revoke all on all tables    in schema public from anon, authenticated;
revoke all on all sequences in schema public from anon, authenticated;
revoke all on all functions in schema public from public, anon, authenticated;

grant usage on schema public to service_role;
grant all on all tables    in schema public to service_role;
grant all on all sequences in schema public to service_role;
grant execute on all functions in schema public to service_role;

-- Future objects created by the migration role get the same treatment.
alter default privileges in schema public revoke all on tables    from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke all on functions from public, anon, authenticated;
alter default privileges in schema public grant all on tables    to service_role;
alter default privileges in schema public grant all on sequences to service_role;
alter default privileges in schema public grant execute on functions to service_role;

-- ---------- make sure RLS is on for every table (no policies) ---------
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
  end loop;
end $$;
