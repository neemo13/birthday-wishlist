-- =====================================================================
-- 002_seed.sql  -  default content. Idempotent: never overwrites edits.
-- =====================================================================

insert into public.app_credentials (kind, enabled) values
  ('family', true), ('admin', true), ('dad_only', false)
on conflict (kind) do nothing;

insert into public.family_members (slug, display_name, sort_order) values
  ('grandmother', 'Grandmother', 1),
  ('brother',     'Brother',     2),
  ('mom',         'Mom',         3),
  ('dad',         'Dad',         4)
on conflict (slug) do nothing;

insert into public.categories (name, description, sort_order, kind) values
  ('Clothing',      'Pretty things to wear',            10, 'regular'),
  ('Makeup',        'Shades, finishes and glow',        20, 'regular'),
  ('Skincare',      'Self-care favourites',             30, 'regular'),
  ('Books',         'Stories to get lost in',           40, 'regular'),
  ('Electronics',   'Gadgets and gizmos',               50, 'regular'),
  ('Accessories',   'The finishing touches',            60, 'regular'),
  ('Food & Treats', 'Something sweet',                  70, 'regular'),
  ('My Dog',        'Spoil the real princess',          80, 'regular'),
  ('My Brother',    'Things he may enjoy too',          90, 'regular'),
  ('Dad Only',      'A private little note',          1000, 'dad_only')
on conflict do nothing;

-- Editable website content (non-secret). Python reads only an allow-list of keys.
insert into public.app_settings (key, value) values
  ('homepage', jsonb_build_object(
    'eyebrow',       '♡ a very special day ♡',
    'heading',       'Happy 21st Birthday!',
    'subtitle',      'A little list of things that would make me very happy.',
    'message',       E'Don''t be stingy, come on, celebrate the girl! 🎀',
    'button_label',  'Enter the World of Gifts ✨',
    'portrait_path', null
  )),
  ('wishlist', jsonb_build_object(
    'heading', 'The Wishlist',
    'intro',   'Browse, peek at the details, and claim something lovely. ♡'
  )),
  ('sections', jsonb_build_object(
    'homepage', jsonb_build_array(
      jsonb_build_object('id', 'portrait', 'visible', true),
      jsonb_build_object('id', 'message',  'visible', true),
      jsonb_build_object('id', 'cta',      'visible', true)
    ),
    'wishlist', jsonb_build_array(
      jsonb_build_object('id', 'intro',   'visible', true),
      jsonb_build_object('id', 'search',  'visible', true),
      jsonb_build_object('id', 'filters', 'visible', true),
      jsonb_build_object('id', 'grid',    'visible', true)
    )
  )),
  ('dad_page', jsonb_build_object(
    'title',   'A little note, just for you',
    'message', E'Dad, come on… it''s my 21st birthday! 🥹❤️\n\nYou know what to do. Make it a birthday to remember.'
  )),
  ('security', jsonb_build_object('idle_minutes', 60, 'session_hours', 8))
on conflict (key) do nothing;
