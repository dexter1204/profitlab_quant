"""Global CSS + palette for the dashboard — Apple-style, light + dark.

A single design language shared with the web app (`web/theme.css`): SF-style
system typography, translucent materials, soft depth, lime accent. The active
theme is chosen at runtime by `set_theme()` (default dark); the module-level
colour names below are rebound to the active palette so `components.py`, which
reads them as `styles.TEXT` etc. at draw time, recolors automatically.
"""

from __future__ import annotations

import streamlit as st


# ── Brand accent (lime) ──────────────────────────────────────────────────────
ACCENT       = "#C7F94C"     # fill — black text on top
ACCENT_PRESS = "#AEE235"
ON_ACCENT    = "#0A0B0E"

# ── Palettes ─────────────────────────────────────────────────────────────────
DARK = dict(
    BG="#0a0a0c", BG_PANEL="#1c1c1e", BG_ELEVATED="#2c2c30",
    BORDER="rgba(255,255,255,0.12)", BORDER_2="rgba(255,255,255,0.07)",
    GRID="rgba(255,255,255,0.10)",
    MUTED="#a1a1a6", TEXT="#f5f5f7", TEXT_STRONG="#ffffff", TEXT_3="#86868b",
    GREEN="#30d073", GREEN_SOFT="#5be093", RED="#ff5247", RED_SOFT="#ff7b72",
    AMBER="#ffa418", YELLOW="#ffd60a", PURPLE="#b483ff", CYAN="#40c8ef",
    ACCENT_TEXT="#C7F94C",
    BG_GRAD="radial-gradient(1200px 760px at 16% -14%, #17181d 0%, #0d0d10 55%, #08080a 100%)",
    MATERIAL="rgba(28,28,32,0.62)", SHADOW="0 16px 40px rgba(0,0,0,.5)",
    PLOTLY_TEMPLATE="plotly_dark",
)

LIGHT = dict(
    BG="#f5f5f7", BG_PANEL="#ffffff", BG_ELEVATED="#f0f0f3",
    BORDER="rgba(0,0,0,0.10)", BORDER_2="rgba(0,0,0,0.06)",
    GRID="rgba(0,0,0,0.08)",
    MUTED="#6e6e73", TEXT="#1d1d1f", TEXT_STRONG="#000000", TEXT_3="#8e8e93",
    GREEN="#1f9d57", GREEN_SOFT="#34c27a", RED="#e0463b", RED_SOFT="#ff6a5e",
    AMBER="#e08c10", YELLOW="#d6a908", PURPLE="#8a4be0", CYAN="#0a94c4",
    ACCENT_TEXT="#6f9c00",
    BG_GRAD="radial-gradient(1200px 760px at 18% -16%, #ffffff 0%, #f1f1f4 55%, #ececf0 100%)",
    MATERIAL="rgba(255,255,255,0.72)", SHADOW="0 12px 32px rgba(0,0,0,.10)",
    PLOTLY_TEMPLATE="plotly_white",
)

# ── Active palette (module globals; rebound by set_theme) ────────────────────
# Defaults to dark so the module is importable without a Streamlit session.
BG = BG_PANEL = BG_ELEVATED = BORDER = BORDER_2 = GRID = ""
MUTED = TEXT = TEXT_STRONG = TEXT_3 = ""
GREEN = GREEN_SOFT = RED = RED_SOFT = AMBER = YELLOW = PURPLE = CYAN = ""
ACCENT_TEXT = BG_GRAD = MATERIAL = SHADOW = PLOTLY_TEMPLATE = ""

# color-code by metric family (rebound in set_theme)
COLOR_CALL = COLOR_PUT = COLOR_GAMMA = COLOR_DELTA = COLOR_MAX_PAIN = ""
COLOR_VANNA = COLOR_CHARM = ""

_THEME = "dark"


def set_theme(mode: str = "dark") -> None:
    """Rebind the module-level colour names to the chosen palette.

    Call BEFORE `inject()` and before rendering any Plotly chart.
    """
    global _THEME
    mode = "light" if str(mode).lower().startswith("l") else "dark"
    _THEME = mode
    pal = LIGHT if mode == "light" else DARK
    g = globals()
    g.update(pal)
    # derived metric-family colors
    g["COLOR_CALL"] = pal["GREEN"]
    g["COLOR_PUT"] = pal["RED"]
    g["COLOR_GAMMA"] = pal["PURPLE"]
    g["COLOR_DELTA"] = pal["CYAN"]
    g["COLOR_MAX_PAIN"] = pal["AMBER"]
    g["COLOR_VANNA"] = "#eab308" if mode == "dark" else "#b8860b"
    g["COLOR_CHARM"] = "#f97316" if mode == "dark" else "#d2691e"


def active_theme() -> str:
    return _THEME


# apply default so imports have real values
set_theme("dark")


def _css() -> str:
    return f"""
<style>
:root {{
    --bg: {BG}; --panel: {BG_PANEL}; --elevated: {BG_ELEVATED};
    --border: {BORDER}; --border-2: {BORDER_2}; --grid: {GRID};
    --muted: {MUTED}; --text: {TEXT}; --text-strong: {TEXT_STRONG}; --text-3: {TEXT_3};
    --accent: {ACCENT}; --accent-text: {ACCENT_TEXT}; --on-accent: {ON_ACCENT};
    --green: {GREEN}; --red: {RED}; --material: {MATERIAL};
    --r: 14px; --r-sm: 10px; --r-pill: 999px;
    --font: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
            "Inter", "Segoe UI", system-ui, sans-serif;
}}

/* Kill Streamlit chrome we don't want */
#MainMenu, footer {{ visibility: hidden; }}
[data-testid="stDecoration"] {{ display: none; }}
header[data-testid="stHeader"] {{
    background: transparent !important; height: 0 !important; min-height: 0 !important;
    padding: 0 !important; pointer-events: none !important;
}}
header[data-testid="stHeader"] button,
header[data-testid="stHeader"] a,
header[data-testid="stHeader"] [role="button"] {{ pointer-events: auto !important; }}
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"] {{
    visibility: visible !important; display: inline-flex !important;
    width: fit-content !important; max-width: 48px; height: fit-content !important;
    pointer-events: none !important; z-index: 50; position: fixed; top: 8px; left: 8px;
}}
[data-testid="collapsedControl"] > *,
[data-testid="stSidebarCollapseButton"] > *,
[data-testid="stSidebarCollapsedControl"] > * {{ pointer-events: auto; }}
[data-testid="collapsedControl"] button,
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarCollapsedControl"] button {{
    background: {BG_ELEVATED} !important; border: 1px solid {BORDER} !important;
    color: {TEXT_STRONG} !important; border-radius: 10px; pointer-events: auto;
}}

/* Window background */
.stApp {{
    background: {BG_GRAD}; background-attachment: fixed; color: {TEXT};
    font-family: var(--font); letter-spacing: -0.01em;
    -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
}}
.stApp, .stApp p, .stApp span, .stApp label, .stApp div {{ font-variant-numeric: tabular-nums; }}

section[data-testid="stSidebar"] {{
    background: {MATERIAL};
    backdrop-filter: saturate(180%) blur(20px);
    -webkit-backdrop-filter: saturate(180%) blur(20px);
    border-right: 1px solid {BORDER};
}}

.block-container {{
    padding-top: 0.9rem !important; padding-bottom: 3rem !important; max-width: 100% !important;
}}

h1, h2, h3, h4 {{ color: {TEXT}; letter-spacing: -0.022em; }}

/* Tabs → Apple segmented/pill */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px; border-bottom: 1px solid {BORDER}; padding-bottom: 6px;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent; color: {MUTED}; font-size: 12px; letter-spacing: 0.02em;
    font-weight: 550; padding: 7px 14px; border-radius: 9px;
}}
.stTabs [data-baseweb="tab"]:hover {{ color: {TEXT}; }}
.stTabs [aria-selected="true"] {{
    background: {BG_ELEVATED} !important; color: {TEXT_STRONG} !important;
    box-shadow: 0 1px 2px rgba(0,0,0,.14);
}}

/* Buttons */
.stButton > button, .stDownloadButton > button {{
    background: {BG_PANEL}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: var(--r-sm); font-weight: 550;
    transition: transform .14s cubic-bezier(.32,.72,0,1), border-color .14s ease, background-color .14s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{ border-color: {TEXT_3}; background: {BG_ELEVATED}; }}
.stButton > button:active {{ transform: scale(.97); }}

/* Inputs / selects */
.stTextInput input, .stNumberInput input, .stDateInput input,
[data-baseweb="select"] > div, [data-baseweb="input"] > div {{
    background: {BG_ELEVATED} !important; border-color: {BORDER} !important; color: {TEXT} !important;
    border-radius: var(--r-sm) !important;
}}

/* Metric ribbon */
.pl-ribbon {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 1px; background: {BORDER}; border: 1px solid {BORDER};
    border-radius: var(--r); overflow: hidden; margin-bottom: 16px;
}}
.pl-cell {{ background: {BG_PANEL}; padding: 13px 16px; display: flex; flex-direction: column; gap: 5px; }}
.pl-cell .lbl {{ color: {TEXT_3}; font-size: 10px; letter-spacing: 0.1em; font-weight: 650; text-transform: uppercase; }}
.pl-cell .val {{ color: {TEXT_STRONG}; font-size: 22px; font-weight: 600; line-height: 1.04; letter-spacing: -0.02em; }}
.pl-cell .sub {{ font-size: 11px; font-weight: 500; color: {MUTED}; }}
.pl-cell .dot {{ display: inline-block; width: 6px; height: 6px; border-radius: 50%; margin-right: 6px; box-shadow: 0 0 8px currentColor; }}
.pl-cell.spot .val {{ color: {TEXT_STRONG}; }}
.pl-cell.call .val   {{ color: {COLOR_CALL}; }}
.pl-cell.put .val    {{ color: {COLOR_PUT}; }}
.pl-cell.gamma .val  {{ color: {COLOR_GAMMA}; }}
.pl-cell.delta .val  {{ color: {COLOR_DELTA}; }}
.pl-cell.pain .val   {{ color: {COLOR_MAX_PAIN}; }}

/* Regime pill */
.pl-regime {{
    display: flex; align-items: center; justify-content: center; gap: 8px;
    padding: 10px 16px; border-radius: var(--r-sm);
    font-weight: 650; letter-spacing: 0.1em; font-size: 12px; margin: 10px 0 6px;
}}
.pl-regime.long   {{ background: color-mix(in srgb, {GREEN} 14%, transparent); border: 1px solid {GREEN}; color: {GREEN_SOFT}; }}
.pl-regime.short  {{ background: color-mix(in srgb, {RED} 14%, transparent);   border: 1px solid {RED};   color: {RED_SOFT}; }}
.pl-regime.trans  {{ background: color-mix(in srgb, {YELLOW} 12%, transparent); border: 1px solid {YELLOW}; color: {YELLOW}; }}
.pl-regime .dot {{ width: 8px; height: 8px; border-radius: 50%; background: currentColor; box-shadow: 0 0 10px currentColor; }}

/* Panels */
.pl-panel {{
    background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: var(--r);
    padding: 18px; margin-bottom: 12px; box-shadow: 0 1px 2px rgba(0,0,0,.10);
}}
.pl-panel h3 {{ color: {TEXT_3}; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; margin: 0 0 8px; font-weight: 650; }}
.pl-panel .spot-line {{ display: flex; align-items: baseline; gap: 10px; }}
.pl-panel .spot-line .price {{ color: {TEXT_STRONG}; font-size: 30px; font-weight: 600; letter-spacing: -0.02em; }}
.pl-panel .spot-line .tk {{ color: {MUTED}; font-size: 12px; letter-spacing: 0.1em; font-weight: 600; }}
.pl-panel .reading {{ color: {MUTED}; font-size: 12px; margin-top: 6px; text-align: center; }}

.pl-triggers {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px; }}
.pl-trigger .lbl {{ color: {TEXT_3}; font-size: 10px; letter-spacing: 0.12em; font-weight: 650; }}
.pl-trigger .val {{ color: {TEXT_STRONG}; font-size: 16px; font-weight: 600; }}
.pl-trigger .delta {{ font-size: 11px; font-weight: 600; }}
.pl-trigger .delta.pos {{ color: {GREEN}; }}
.pl-trigger .delta.neg {{ color: {RED}; }}

/* IV premium hero */
.pl-iv-hero {{ text-align: center; padding: 8px 0 12px; }}
.pl-iv-hero .num {{ font-size: 44px; font-weight: 700; letter-spacing: -0.03em; line-height: 1; }}
.pl-iv-hero.expensive .num {{ color: {RED_SOFT}; }}
.pl-iv-hero.cheap     .num {{ color: {GREEN_SOFT}; }}
.pl-iv-hero.neutral   .num {{ color: {YELLOW}; }}
.pl-iv-hero .lbl {{ color: {TEXT_3}; font-size: 11px; letter-spacing: 0.12em; margin-top: 4px; font-weight: 650; }}
.pl-iv-hero .ratio {{ color: {MUTED}; font-size: 11px; margin-top: 4px; }}
.pl-iv-hero .ratio b {{ color: {TEXT_STRONG}; }}

/* IV spectrum bar */
.pl-spectrum {{ position: relative; height: 8px; border-radius: 4px;
    background: linear-gradient(90deg, {GREEN} 0%, {YELLOW} 50%, {RED} 100%); margin: 16px 4px 22px; }}
.pl-spectrum .marker {{ position: absolute; top: -6px; width: 2px; height: 20px; background: {TEXT_STRONG}; transform: translateX(-1px); }}
.pl-spectrum .marker::after {{
    content: attr(data-label) " " attr(data-val); position: absolute; top: -18px; left: 50%;
    transform: translateX(-50%); color: {TEXT}; font-size: 9px; font-weight: 600; white-space: nowrap; letter-spacing: 0.04em;
}}
.pl-spectrum .marker.hv10 {{ background: {CYAN}; }}
.pl-spectrum .marker.hv30 {{ background: {AMBER}; }}
.pl-spectrum .marker.hv60 {{ background: {PURPLE}; }}
.pl-spectrum .marker.iv   {{ background: {TEXT_STRONG}; }}

/* Small stat rows */
.pl-statrow {{ display: flex; justify-content: space-between; padding: 6px 0; border-top: 1px solid {BORDER_2}; font-size: 11px; letter-spacing: 0.04em; }}
.pl-statrow .lbl {{ color: {TEXT_3}; text-transform: uppercase; font-weight: 650; }}
.pl-statrow .val {{ color: {TEXT_STRONG}; font-weight: 600; }}
.pl-statrow .val.pos {{ color: {GREEN}; }}
.pl-statrow .val.neg {{ color: {RED}; }}
.pl-statrow .val.warn {{ color: {AMBER}; }}

/* Section titles */
.pl-title {{ display: flex; align-items: center; gap: 12px; margin: 6px 0 10px; }}
.pl-title .tk {{ font-size: 22px; font-weight: 650; color: {TEXT_STRONG}; letter-spacing: -0.02em; }}
.pl-title .sub {{ color: {TEXT_3}; font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; font-weight: 600; }}
.pl-title .badge {{ padding: 3px 9px; border-radius: var(--r-pill); font-size: 10px; letter-spacing: 0.12em; font-weight: 650; text-transform: uppercase; }}
.pl-title .badge.demo {{ background: color-mix(in srgb, {AMBER} 16%, transparent); color: {AMBER}; border: 1px solid {AMBER}; }}
.pl-title .badge.live {{ background: color-mix(in srgb, {GREEN} 16%, transparent); color: {GREEN}; border: 1px solid {GREEN}; }}

/* Top-level pill radios (ticker row + view row) */
[data-testid="stRadio"] > label {{ display: none; }}
[data-testid="stRadio"] div[role="radiogroup"] {{
    gap: 4px; padding: 4px; background: {BG_ELEVATED}; border: 1px solid {BORDER_2};
    border-radius: 12px; margin-bottom: 8px; flex-wrap: wrap; position: relative; z-index: 5;
    display: inline-flex;
}}
[data-testid="stRadio"] div[role="radiogroup"] label {{
    background: transparent !important; border: 1px solid transparent; padding: 6px 15px;
    border-radius: 9px; cursor: pointer; display: inline-flex !important; align-items: center;
    user-select: none; position: relative; z-index: 5;
}}
[data-testid="stRadio"] div[role="radiogroup"] label:hover {{ background: color-mix(in srgb, {TEXT} 6%, transparent) !important; }}
[data-testid="stRadio"] div[role="radiogroup"] label p {{
    color: {MUTED} !important; font-size: 12px !important; letter-spacing: 0.01em;
    font-weight: 550; margin: 0 !important; pointer-events: none;
}}
[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {{
    background: {BG_PANEL} !important; box-shadow: 0 1px 2px rgba(0,0,0,.14);
}}
[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) p {{ color: {TEXT_STRONG} !important; }}
[data-testid="stRadio"] div[role="radiogroup"] label > div:first-child {{
    width: 0 !important; height: 0 !important; overflow: hidden; opacity: 0; margin: 0 !important; padding: 0 !important; pointer-events: none;
}}

/* DataFrame polish */
[data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; border-radius: var(--r-sm); overflow: hidden; }}

/* Sidebar headings */
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{
    color: {TEXT_STRONG}; font-size: 13px; letter-spacing: 0.1em; text-transform: uppercase; font-weight: 650;
}}

/* Reference bar (Call/Put walls + key levels) under the buscador */
.pl-refbar {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 1px;
    background: {BORDER}; border: 1px solid {BORDER}; border-radius: var(--r-sm);
    overflow: hidden; margin: 2px 0 12px; box-shadow: 0 1px 2px rgba(0,0,0,.10);
}}
.pl-refcol {{ background: {BG_PANEL}; padding: 9px 13px; min-width: 0; }}
.pl-refcol .rx {{ display: flex; align-items: center; gap: 6px; font-size: 9px; font-weight: 650;
    letter-spacing: 0.1em; text-transform: uppercase; color: {TEXT_3}; margin-bottom: 5px; }}
.pl-refcol .rx .dot {{ width: 6px; height: 6px; border-radius: 50%; display: inline-block; }}
.pl-refcol .rx .dot.call {{ background: {GREEN}; }}
.pl-refcol .rx .dot.put {{ background: {RED}; }}
.pl-refcol .rx .dot.key {{ background: {ACCENT_TEXT}; }}
.pl-refrow {{ display: flex; align-items: baseline; justify-content: space-between; gap: 10px; padding: 2px 0; }}
.pl-refrow .rk {{ font-size: 12.5px; font-weight: 600; color: {TEXT}; }}
.pl-refrow .rlbl {{ font-size: 11.5px; font-weight: 550; color: {MUTED}; }}
.pl-refrow .rv {{ font-size: 11px; font-weight: 600; }}
.pl-refrow .rv.call {{ color: {GREEN}; }}
.pl-refrow .rv.put {{ color: {RED}; }}
.pl-refrow .rv.key {{ color: {TEXT}; }}
.pl-refrow .rtag {{ font-size: 10px; font-weight: 650; padding: 1px 6px; border-radius: var(--r-pill);
    background: {BG_ELEVATED}; color: {MUTED}; white-space: nowrap; }}
.pl-refrow .rtag.pos {{ color: {GREEN}; background: color-mix(in srgb, {GREEN} 14%, transparent); }}
.pl-refrow .rtag.neg {{ color: {RED}; background: color-mix(in srgb, {RED} 14%, transparent); }}
.pl-refrow .rvwrap {{ display: flex; align-items: baseline; gap: 8px; }}
/* Key Levels: 2-column grid of tiles */
.pl-refkeys {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px 14px; }}
.pl-refkey {{ display: flex; flex-direction: column; min-width: 0; }}
.pl-refkey .kk {{ font-size: 9.5px; font-weight: 600; letter-spacing: 0.04em; color: {TEXT_3}; white-space: nowrap; }}
.pl-refkey .kv {{ font-size: 12.5px; font-weight: 600; color: {TEXT}; display: flex; align-items: baseline; gap: 6px; }}

/* Métricas: cinta en movimiento (ticker tape) */
.pl-tape {{ overflow: hidden; border: 1px solid {BORDER}; border-radius: var(--r-sm);
    background: {BG_PANEL}; box-shadow: 0 1px 2px rgba(0,0,0,.10); margin: 2px 0 14px;
    -webkit-mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent);
    mask-image: linear-gradient(90deg, transparent, #000 3%, #000 97%, transparent); }}
.pl-tape-track {{ display: flex; width: max-content; animation: pl-marquee 46s linear infinite; }}
.pl-tape:hover .pl-tape-track {{ animation-play-state: paused; }}
@keyframes pl-marquee {{ from {{ transform: translateX(0); }} to {{ transform: translateX(-50%); }} }}
.pl-chip {{ display: inline-flex; align-items: baseline; gap: 8px; padding: 9px 18px;
    white-space: nowrap; border-right: 1px solid {BORDER_2}; }}
.pl-chip b {{ font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: {TEXT_3}; font-weight: 650; }}
.pl-chip .cv {{ font-size: 14px; font-weight: 600; color: {TEXT_STRONG}; }}
.pl-chip .cs {{ font-size: 11px; font-weight: 550; color: {MUTED}; }}
.pl-chip.call .cv {{ color: {GREEN}; }} .pl-chip.put .cv {{ color: {RED}; }}
.pl-chip.gamma .cv {{ color: {PURPLE}; }} .pl-chip.delta .cv {{ color: {CYAN}; }} .pl-chip.pain .cv {{ color: {AMBER}; }}
.pl-chip .cs .dot {{ display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: currentColor; margin-right: 5px; }}
@media (prefers-reduced-motion: reduce) {{
    .pl-tape-track {{ animation: none; }}
    .pl-tape {{ overflow-x: auto; -webkit-mask-image: none; mask-image: none; }}
}}
</style>
"""


def inject() -> None:
    st.markdown(_css(), unsafe_allow_html=True)
