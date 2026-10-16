"""Global pink-and-cream design system. One place for all CSS so every page matches."""
from __future__ import annotations

import streamlit as st

PALETTE = {
    "blush": "#F8E9EB", "rose": "#A44E70", "mauve": "#713B50",
    "cream": "#FFF9F7", "white": "#FFFFFF",
}

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

:root {
  --blush: #F8E9EB;  --blush-2: #F3D9DE;  --rose: #A44E70;  --rose-2: #B8668A;
  --mauve: #713B50;  --mauve-2: #8B5A6D;  --cream: #FFF9F7; --white: #FFFFFF;
  --line: #EBD3D9;   --muted: #8B6B77;    --ok-bg: #FCE4EC;
  --serif: 'Playfair Display', 'Cormorant Garamond', Georgia, 'Times New Roman', serif;
  --sans: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  --shadow: 0 10px 30px rgba(113, 59, 80, .09);
  --shadow-lg: 0 18px 44px rgba(113, 59, 80, .16);
}

/* ---------- page shell ---------- */
html, body, .stApp { font-family: var(--sans); color: var(--mauve); }
.stApp {
  background:
    radial-gradient(900px 480px at 8% -6%, var(--blush-2) 0%, transparent 60%),
    radial-gradient(800px 460px at 96% 4%, var(--blush) 0%, transparent 62%),
    radial-gradient(900px 520px at 50% 108%, var(--blush) 0%, transparent 65%),
    var(--cream);
  background-attachment: fixed;
}
[data-testid="stHeader"] { background: transparent; height: 0; }
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stAppDeployButton"],
#MainMenu, footer, [data-testid="stStatusWidget"] { display: none !important; visibility: hidden; }
[data-testid="stMainBlockContainer"], .block-container {
  max-width: 1180px; padding: 1.6rem 1.25rem 4rem;
}

[data-testid="stHeaderActionElements"], .stMarkdown a.anchor { display: none !important; }

/* ---------- type ---------- */
h1, h2, h3, .gw-serif { font-family: var(--serif) !important; color: var(--mauve) !important; letter-spacing: -.01em; }
h1 { font-weight: 700 !important; }
h2, h3 { font-weight: 600 !important; }
p, li, label, span, div { font-family: var(--sans); }
a { color: var(--rose); text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: var(--mauve); }
.gw-eyebrow { text-transform: uppercase; letter-spacing: .18em; font-size: .72rem; font-weight: 600; color: var(--rose); }
.gw-muted { color: var(--muted); }

/* ---------- buttons ---------- */
[data-testid^="stBaseButton-"], .stButton > button, .stFormSubmitButton > button {
  border-radius: 999px !important; min-height: 2.75rem; padding: .45rem 1.3rem;
  font-family: var(--sans); font-weight: 600; letter-spacing: .01em;
  transition: transform .15s ease, box-shadow .15s ease, background .15s ease, border-color .15s ease;
}
[data-testid^="stBaseButton-primary"] {
  background: linear-gradient(135deg, var(--rose) 0%, var(--mauve) 100%) !important;
  color: #fff !important; border: 0 !important; box-shadow: 0 8px 20px rgba(164, 78, 112, .32);
}
[data-testid^="stBaseButton-primary"]:hover { transform: translateY(-2px); box-shadow: 0 12px 26px rgba(164, 78, 112, .42); }
[data-testid^="stBaseButton-primary"]:active { transform: translateY(0); box-shadow: 0 4px 10px rgba(164, 78, 112, .3); }
[data-testid^="stBaseButton-secondary"] {
  background: var(--white) !important; color: var(--mauve) !important; border: 1.5px solid var(--line) !important;
}
[data-testid^="stBaseButton-secondary"]:hover { background: var(--blush) !important; border-color: var(--rose) !important; color: var(--rose) !important; }
[data-testid^="stBaseButton-secondary"]:active { transform: scale(.98); }
button:focus-visible { outline: 3px solid rgba(164, 78, 112, .35) !important; outline-offset: 2px; }

/* ---------- inputs ---------- */
[data-testid="stWidgetLabel"] p { font-weight: 600; font-size: .88rem; color: var(--mauve); }
div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="textarea"],
div[data-baseweb="select"] > div {
  border-radius: 14px !important; background: var(--white) !important; border-color: var(--line) !important;
}
div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within,
div[data-baseweb="select"] > div:focus-within {
  border-color: var(--rose) !important; box-shadow: 0 0 0 3px rgba(164, 78, 112, .16) !important;
}
input, textarea { color: var(--mauve) !important; font-family: var(--sans) !important; }
[data-baseweb="popover"] ul { border-radius: 14px; }
[data-baseweb="popover"] li:hover { background: var(--blush) !important; }

/* ---------- alerts, tabs, expanders ---------- */
[data-testid="stAlert"] { border-radius: 16px; border: 1px solid var(--line); border-left: 5px solid var(--rose);
  background: var(--white) !important; box-shadow: 0 4px 14px rgba(113,59,80,.06); }
[data-testid="stAlert"] * { color: var(--mauve) !important; }
button[data-baseweb="tab"] { font-weight: 600; color: var(--muted); }
button[data-baseweb="tab"][aria-selected="true"] { color: var(--rose); }
[data-baseweb="tab-highlight"] { background-color: var(--rose) !important; }
[data-testid="stExpander"] { border: 1px solid var(--line); border-radius: 16px; background: var(--white); }
hr { border-color: var(--line); }

/* ---------- reusable components ---------- */
.gw-card {
  background: var(--white); border: 1px solid var(--line); border-radius: 22px;
  box-shadow: var(--shadow); padding: 1rem; transition: transform .18s ease, box-shadow .18s ease;
}
.gw-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg); }
.gw-img { width: 100%; aspect-ratio: 1 / 1; object-fit: cover; border-radius: 18px; display: block; background: var(--blush); }
.gw-img--placeholder {
  display: flex; align-items: center; justify-content: center; font-size: 2.6rem;
  background: linear-gradient(135deg, var(--blush) 0%, var(--blush-2) 100%); color: var(--rose);
}
.gw-badge { display: inline-block; padding: .18rem .7rem; border-radius: 999px; font-size: .74rem; font-weight: 600; letter-spacing: .02em; }
.gw-badge--available { background: var(--ok-bg); color: var(--rose); border: 1px solid #F4C2D2; }
.gw-badge--claimed { background: var(--mauve); color: #fff; }
.gw-price { font-weight: 600; color: var(--rose); }

/* ---------- top bar ---------- */
.st-key-topbar { padding: .2rem 0 .9rem; border-bottom: 1px solid var(--line); margin-bottom: 1.4rem; }
.gw-brand { font-family: var(--serif); font-size: 1.35rem; font-weight: 600; color: var(--mauve); }
.gw-brand span { color: var(--rose); }

/* ---------- login ---------- */
.gw-motif { text-align: center; margin: 2.2rem 0 .4rem; font-size: 2.4rem; line-height: 1; filter: drop-shadow(0 6px 10px rgba(164,78,112,.25)); }
.gw-motif .gw-sparkle { font-size: 1.1rem; opacity: .7; vertical-align: super; margin: 0 .5rem; }
.st-key-login_card, .st-key-pick_card {
  max-width: 460px; margin: 0 auto; background: rgba(255,255,255,.92);
  border: 1px solid var(--line); border-radius: 28px; box-shadow: var(--shadow-lg); padding: 2rem 1.9rem 1.6rem;
}
.gw-login-title { font-family: var(--serif); font-size: clamp(1.55rem, 5.2vw, 2.1rem); font-weight: 700; text-align: center;
  margin: 0 0 .25rem; color: var(--mauve); text-wrap: balance; line-height: 1.2; }
.gw-login-sub { text-align: center; color: var(--muted); margin: 0 0 1.4rem; }
.gw-fineprint { text-align: center; font-size: .78rem; color: var(--muted); margin-top: .9rem; }
.st-key-login_card [data-testid="stForm"], .st-key-pick_card [data-testid="stForm"] { padding: 0; border: 0; }


/* ---------- nav + pills ---------- */
[data-testid="stSegmentedControl"] { margin-top: .5rem; }
[data-testid="stBaseButton-segmented_control"], [data-testid="stBaseButton-segmented_controlActive"],
[data-testid="stBaseButton-pills"], [data-testid="stBaseButton-pillsActive"] {
  min-height: 2.3rem !important; padding: .2rem 1.05rem !important; font-size: .9rem; border-radius: 999px !important;
  background: var(--white) !important; color: var(--mauve) !important; border: 1.5px solid var(--line) !important; box-shadow: none !important;
}
[data-testid="stBaseButton-segmented_control"]:hover, [data-testid="stBaseButton-pills"]:hover {
  background: var(--blush) !important; border-color: var(--rose) !important; transform: none; }
[data-testid="stBaseButton-segmented_controlActive"], [data-testid="stBaseButton-pillsActive"] {
  background: linear-gradient(135deg, var(--rose), var(--mauve)) !important; color: #fff !important; border-color: transparent !important; }
[data-testid="stBaseButton-segmented_controlActive"] p, [data-testid="stBaseButton-pillsActive"] p { color: #fff !important; }

/* ---------- homepage hero ---------- */
.st-key-hero { align-items: center; text-align: center; gap: 1.1rem; padding: .5rem 0 2rem; }
.st-key-hero > div { width: 100%; }
.gw-portrait-wrap { display: flex; justify-content: center; padding: .6rem 0 .2rem; }
.gw-portrait-frame { position: relative; width: min(300px, 72vw); }
.gw-portrait-frame::before { content: ""; position: absolute; inset: 14px -14px -14px 14px; border-radius: 999px 999px 32px 32px;
  background: linear-gradient(160deg, var(--blush-2), var(--blush)); z-index: 0; }
.gw-portrait { position: relative; z-index: 1; width: 100%; aspect-ratio: 4 / 5; object-fit: cover; display: block;
  border-radius: 999px 999px 32px 32px; border: 6px solid var(--white); box-shadow: var(--shadow-lg); background: var(--blush); }
.gw-portrait--placeholder { display: flex; align-items: center; justify-content: center; font-family: var(--serif);
  font-size: 6rem; font-weight: 700; color: var(--rose); background: linear-gradient(160deg, var(--blush), var(--blush-2)); }
.gw-hero-text { max-width: 760px; margin: 0 auto; text-align: center; }
.gw-hero-title { font-size: clamp(2.1rem, 6.5vw, 3.6rem) !important; line-height: 1.08; margin: .3rem 0 .6rem !important; text-wrap: balance; }
.gw-hero-sub { font-size: 1.15rem; color: var(--mauve-2); margin: 0 0 .5rem; text-wrap: balance; }
.gw-hero-msg { font-family: var(--serif); font-style: italic; font-size: 1.25rem; color: var(--rose); margin: 0; }
.st-key-hero_cta { align-items: center; padding-top: .4rem; }
.st-key-hero_cta [data-testid^="stBaseButton-"] { font-size: 1.05rem; padding: .6rem 2.2rem; min-height: 3.2rem; }

/* ---------- wishlist ---------- */
.gw-page-head { text-align: center; margin: .2rem 0 1rem; }
.gw-page-head h1 { font-size: clamp(2rem, 5vw, 2.8rem) !important; margin-bottom: .2rem !important; }
.st-key-filters_box { background: rgba(255,255,255,.7); border: 1px solid var(--line); border-radius: 20px; padding: .9rem 1.1rem .5rem; margin: .6rem 0 1rem; }
.gw-count { font-size: .85rem; margin: .2rem 0 .8rem; }
.st-key-grid { display: grid !important; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 1.3rem !important; }
.st-key-grid > div { min-width: 0; height: 100%; }
[class*="st-key-card_"] { height: 100%; justify-content: space-between; background: var(--white); border: 1px solid var(--line); border-radius: 22px; box-shadow: var(--shadow);
  padding: .8rem .8rem .9rem; gap: .5rem !important; transition: transform .18s ease, box-shadow .18s ease; }
[class*="st-key-card_"]:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg); }
.gw-card-body { padding: .35rem .2rem .45rem; }
.gw-card-top { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
.gw-cat { text-transform: uppercase; letter-spacing: .12em; font-size: .66rem; font-weight: 600; color: var(--muted); }
.gw-card-title { font-family: var(--serif); font-weight: 600; color: var(--mauve); font-size: 1.12rem; margin: .35rem 0 .15rem; line-height: 1.25; }
.gw-desc { font-size: .85rem; line-height: 1.4; color: var(--mauve-2); margin: .25rem 0 .2rem; max-height: 2.9em; overflow: hidden; }
.gw-claimed-by { font-size: .78rem; color: var(--muted); margin-top: .3rem; }
.gw-empty { text-align: center; background: rgba(255,255,255,.75); border: 1px dashed var(--line); border-radius: 24px; padding: 2.5rem 1rem; margin: 1rem 0; }
.gw-empty-icon { font-size: 2.4rem; }

/* ---------- product dialog ---------- */
[data-testid="stDialog"] [role="dialog"] { border-radius: 26px; background: var(--cream); }
.gw-dialog-img { max-height: 340px; }
.gw-dialog-title { font-size: 1.8rem !important; margin: .2rem 0 .4rem !important; }
.gw-price--lg { font-size: 1.3rem; margin-bottom: .4rem; }
.gw-dialog-desc { margin-top: .7rem; }
.gw-block { background: var(--white); border: 1px solid var(--line); border-radius: 16px; padding: .8rem 1rem; margin-top: .8rem; }
.gw-block p { margin: .3rem 0 0; }
.gw-link-row { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; margin-top: .45rem; }
.gw-link { display: inline-block; padding: .3rem .9rem; border-radius: 999px; background: var(--blush); border: 1px solid var(--line);
  font-weight: 600; text-decoration: none; }
.gw-link:hover { background: var(--rose); color: #fff; }
.gw-link-note { font-size: .82rem; color: var(--muted); }

/* ---------- admin studio ---------- */
.gw-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 1rem; margin-top: .6rem; }
.gw-metric { background: var(--white); border: 1px solid var(--line); border-radius: 20px; box-shadow: var(--shadow); padding: 1.1rem 1rem; text-align: center; }
.gw-metric-n { font-family: var(--serif); font-size: 2.2rem; font-weight: 700; color: var(--rose); line-height: 1.1; }
.gw-metric-l { font-size: .78rem; text-transform: uppercase; letter-spacing: .12em; color: var(--muted); margin-top: .2rem; }
.gw-activity { padding: .45rem .2rem; border-bottom: 1px dashed var(--line); font-size: .9rem; }
.gw-thumb { max-width: 180px; margin-bottom: .6rem; }
.gw-sec-label { padding-top: .45rem; font-weight: 600; }
[class*="st-key-claim_"] { background: var(--white); border: 1px solid var(--line); border-radius: 18px; padding: .8rem 1rem; margin-bottom: .6rem; }
[data-testid="stFileUploader"] section { border-radius: 16px; background: var(--white); border: 1.5px dashed var(--line); }

/* ---------- claim actions + private page ---------- */
[class*="st-key-actions_"] { background: var(--white); border: 1px solid var(--line); border-radius: 16px; padding: .9rem 1rem; margin-top: .8rem; }
.gw-dad-card { text-align: center; max-width: 640px; margin: 1.2rem auto; padding: 2.2rem 1.6rem; border-radius: 28px;
  background: linear-gradient(160deg, var(--white) 0%, var(--blush) 100%); border: 1px solid var(--line); box-shadow: var(--shadow-lg); }
.gw-dad-card--locked { padding: 1.6rem 1.4rem; }
.gw-dad-hearts { color: var(--rose); font-size: 1.5rem; letter-spacing: .6rem; }
.gw-dad-title { font-size: clamp(1.6rem, 5vw, 2.3rem) !important; margin: .5rem 0 .6rem !important; }
.gw-dad-msg { font-family: var(--serif); font-style: italic; font-size: 1.2rem; line-height: 1.6; color: var(--mauve); margin: .4rem 0 1rem; }
.st-key-dad_pin_box { max-width: 420px; margin: 0 auto; }

/* ---------- mobile ---------- */
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"], .block-container { padding: 1rem .85rem 3rem; }
  .st-key-login_card, .st-key-pick_card { padding: 1.5rem 1.15rem 1.2rem; border-radius: 22px; }
  input, textarea, [data-baseweb="select"] { font-size: 16px !important; } /* stops iOS zoom-on-focus */
  [data-testid^="stBaseButton-"], .stFormSubmitButton > button { min-height: 3rem; }
  h1 { font-size: 1.9rem !important; }
  .st-key-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .8rem !important; }
  [class*="st-key-card_"] { padding: .55rem .55rem .7rem; border-radius: 18px; }
  .gw-card-title { font-size: .98rem; }
  .gw-desc { display: none; }
  .gw-hero-msg { font-size: 1.1rem; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
"""


def inject() -> None:
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)
