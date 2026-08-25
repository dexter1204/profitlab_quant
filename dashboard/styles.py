"""Global CSS + palette constants for the dashboard.

Palette matches the reference layout: near-black background, muted grid,
color-coded exposure labels (call = green, put = red, gamma flip = purple,
delta = cyan/amber). Injected once at app boot via `inject()`.
"""

from __future__ import annotations

import streamlit as st


# ── palette ────────────────────────────────────────────────────────────────
BG          = "#05070b"
BG_PANEL    = "#0b1220"
BG_ELEVATED = "#111827"
BORDER      = "#1f2937"
GRID        = "#111a2b"
MUTED       = "#64748b"
TEXT        = "#e2e8f0"
TEXT_STRONG = "#f8fafc"

GREEN       = "#22c55e"
GREEN_SOFT  = "#4ade80"
RED         = "#ef4444"
RED_SOFT    = "#f87171"
AMBER       = "#f59e0b"
YELLOW      = "#facc15"
PURPLE      = "#a855f7"
CYAN        = "#06b6d4"

# color-code by metric family
COLOR_CALL      = GREEN
COLOR_PUT       = RED
COLOR_GAMMA     = PURPLE
COLOR_DELTA     = CYAN
COLOR_MAX_PAIN  = AMBER
COLOR_VANNA     = "#eab308"
COLOR_CHARM     = "#f97316"


_CSS = f"""
<style>
:root {{
    --bg: {BG};
    --panel: {BG_PANEL};
    --border: {BORDER};
    --muted: {MUTED};
    --text: {TEXT};
    --text-strong: {TEXT_STRONG};
}}

/* Kill Streamlit chrome we don't want */
#MainMenu, footer {{ visibility: hidden; }}
[data-testid="stDecoration"] {{ display: none; }}
/* Keep the top header transparent (no bar) but keep its buttons — the sidebar
   collapse/expand arrow lives there. Hiding `header` outright makes the
   sidebar impossible to reopen once it collapses. */
header[data-testid="stHeader"] {{
    background: transparent !important;
    height: auto !important;
}}
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"] {{
    visibility: visible !important;
    display: flex !important;
    z-index: 1000;
}}
[data-testid="collapsedControl"] button,
[data-testid="stSidebarCollapsedControl"] button {{
    background: {BG_ELEVATED} !important;
    border: 1px solid {BORDER} !important;
    color: {TEXT_STRONG} !important;
    border-radius: 6px;
}}

/* Full-bleed dark background */
.stApp {{
    background: radial-gradient(1200px 700px at 20% -20%, #0b1220 0%, {BG} 60%);
    color: var(--text);
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif;
    letter-spacing: 0.01em;
}}

section[data-testid="stSidebar"] {{
    background: {BG_PANEL};
    border-right: 1px solid {BORDER};
}}

.block-container {{
    padding-top: 0.75rem !important;
    padding-bottom: 3rem !important;
    max-width: 100% !important;
}}

/* Tabs → pill style */
.stTabs [data-baseweb="tab-list"] {{
    gap: 4px;
    border-bottom: 1px solid {BORDER};
    padding-bottom: 4px;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent;
    color: {MUTED};
    font-size: 11px;
    letter-spacing: 0.14em;
    font-weight: 600;
    padding: 6px 14px;
    border-radius: 6px;
    text-transform: uppercase;
}}
.stTabs [aria-selected="true"] {{
    background: {BG_ELEVATED} !important;
    color: {TEXT_STRONG} !important;
    box-shadow: inset 0 -2px 0 0 {GREEN};
}}

/* Metric ribbon */
.pl-ribbon {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 1px;
    background: {BORDER};
    border: 1px solid {BORDER};
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 14px;
}}
.pl-cell {{
    background: {BG_PANEL};
    padding: 10px 14px;
    display: flex;
    flex-direction: column;
    gap: 4px;
}}
.pl-cell .lbl {{
    color: {MUTED};
    font-size: 10px;
    letter-spacing: 0.16em;
    font-weight: 700;
    text-transform: uppercase;
}}
.pl-cell .val {{
    color: {TEXT_STRONG};
    font-size: 20px;
    font-weight: 600;
    line-height: 1.05;
    font-variant-numeric: tabular-nums;
}}
.pl-cell .sub {{
    font-size: 11px;
    font-weight: 500;
    color: {MUTED};
    letter-spacing: 0.02em;
}}
.pl-cell .dot {{
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    margin-right: 6px;
    box-shadow: 0 0 8px currentColor;
}}
.pl-cell.spot .val {{ color: {TEXT_STRONG}; }}
.pl-cell.call .val   {{ color: {COLOR_CALL}; }}
.pl-cell.put .val    {{ color: {COLOR_PUT}; }}
.pl-cell.gamma .val  {{ color: {COLOR_GAMMA}; }}
.pl-cell.delta .val  {{ color: {COLOR_DELTA}; }}
.pl-cell.pain .val   {{ color: {COLOR_MAX_PAIN}; }}

/* Regime pill */
.pl-regime {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 10px 16px;
    border-radius: 8px;
    font-weight: 700;
    letter-spacing: 0.12em;
    font-size: 12px;
    margin: 10px 0 6px;
}}
.pl-regime.long   {{ background: rgba(34,197,94,0.12); border: 1px solid {GREEN}; color: {GREEN_SOFT}; box-shadow: 0 0 16px rgba(34,197,94,0.22); }}
.pl-regime.short  {{ background: rgba(239,68,68,0.12); border: 1px solid {RED};   color: {RED_SOFT};   box-shadow: 0 0 16px rgba(239,68,68,0.22); }}
.pl-regime.trans  {{ background: rgba(250,204,21,0.10); border: 1px solid {YELLOW}; color: {YELLOW}; }}
.pl-regime .dot {{
    width: 8px; height: 8px; border-radius: 50%;
    background: currentColor; box-shadow: 0 0 10px currentColor;
}}

/* Right-column panels */
.pl-panel {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 12px;
}}
.pl-panel h3 {{
    color: {MUTED};
    font-size: 11px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin: 0 0 8px 0;
    font-weight: 700;
}}
.pl-panel .spot-line {{
    display: flex;
    align-items: baseline;
    gap: 10px;
}}
.pl-panel .spot-line .price {{
    color: {TEXT_STRONG};
    font-size: 30px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
}}
.pl-panel .spot-line .tk {{
    color: {MUTED};
    font-size: 12px;
    letter-spacing: 0.16em;
    font-weight: 600;
}}
.pl-panel .reading {{
    color: {MUTED};
    font-size: 12px;
    margin-top: 6px;
    text-align: center;
}}

/* Trigger rows inside regime panel */
.pl-triggers {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-top: 10px;
}}
.pl-trigger .lbl {{
    color: {MUTED}; font-size: 10px; letter-spacing: 0.14em; font-weight: 700;
}}
.pl-trigger .val {{
    color: {TEXT_STRONG}; font-size: 16px; font-weight: 600; font-variant-numeric: tabular-nums;
}}
.pl-trigger .delta {{
    font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums;
}}
.pl-trigger .delta.pos {{ color: {GREEN}; }}
.pl-trigger .delta.neg {{ color: {RED}; }}

/* IV premium hero */
.pl-iv-hero {{
    text-align: center;
    padding: 8px 0 12px;
}}
.pl-iv-hero .num {{
    font-size: 44px;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1;
}}
.pl-iv-hero.expensive .num {{ color: {RED_SOFT}; text-shadow: 0 0 24px rgba(239,68,68,0.28); }}
.pl-iv-hero.cheap     .num {{ color: {GREEN_SOFT}; text-shadow: 0 0 24px rgba(34,197,94,0.28); }}
.pl-iv-hero.neutral   .num {{ color: {YELLOW}; }}
.pl-iv-hero .lbl {{
    color: {MUTED}; font-size: 11px; letter-spacing: 0.14em; margin-top: 4px; font-weight: 700;
}}
.pl-iv-hero .ratio {{
    color: {MUTED}; font-size: 11px; margin-top: 4px;
}}
.pl-iv-hero .ratio b {{ color: {TEXT_STRONG}; }}

/* IV spectrum bar */
.pl-spectrum {{
    position: relative;
    height: 8px;
    border-radius: 4px;
    background: linear-gradient(90deg, {GREEN} 0%, {YELLOW} 50%, {RED} 100%);
    margin: 16px 4px 22px;
}}
.pl-spectrum .marker {{
    position: absolute;
    top: -6px;
    width: 2px;
    height: 20px;
    background: {TEXT_STRONG};
    transform: translateX(-1px);
}}
.pl-spectrum .marker::after {{
    content: attr(data-label) " " attr(data-val);
    position: absolute;
    top: -18px;
    left: 50%;
    transform: translateX(-50%);
    color: {TEXT};
    font-size: 9px;
    font-weight: 600;
    white-space: nowrap;
    letter-spacing: 0.05em;
}}
.pl-spectrum .marker.hv10 {{ background: #60a5fa; }}
.pl-spectrum .marker.hv30 {{ background: {AMBER}; }}
.pl-spectrum .marker.hv60 {{ background: {PURPLE}; }}
.pl-spectrum .marker.iv   {{ background: {TEXT_STRONG}; }}

/* Small stat rows at bottom of IV panel */
.pl-statrow {{
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    border-top: 1px solid {BORDER};
    font-size: 11px;
    letter-spacing: 0.08em;
}}
.pl-statrow .lbl {{ color: {MUTED}; text-transform: uppercase; font-weight: 700; }}
.pl-statrow .val {{ color: {TEXT_STRONG}; font-weight: 600; font-variant-numeric: tabular-nums; }}
.pl-statrow .val.pos {{ color: {GREEN}; }}
.pl-statrow .val.neg {{ color: {RED}; }}
.pl-statrow .val.warn {{ color: {AMBER}; }}

/* Section titles */
.pl-title {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 6px 0 10px;
}}
.pl-title .tk {{
    font-size: 22px;
    font-weight: 700;
    color: {TEXT_STRONG};
    letter-spacing: 0.03em;
}}
.pl-title .sub {{
    color: {MUTED};
    font-size: 11px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    font-weight: 600;
}}
.pl-title .badge {{
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 10px;
    letter-spacing: 0.16em;
    font-weight: 700;
    text-transform: uppercase;
}}
.pl-title .badge.demo {{ background: rgba(251,191,36,0.15); color: {AMBER}; border: 1px solid {AMBER}; }}
.pl-title .badge.live {{ background: rgba(34,197,94,0.15); color: {GREEN}; border: 1px solid {GREEN}; }}

/* Top-level pill radios (ticker row + view row) */
[data-testid="stRadio"] > label {{ display: none; }}
[data-testid="stRadio"] div[role="radiogroup"] {{
    gap: 4px;
    padding: 6px 0 10px;
    border-bottom: 1px solid {BORDER};
    margin-bottom: 6px;
    flex-wrap: wrap;
}}
[data-testid="stRadio"] div[role="radiogroup"] label {{
    background: transparent !important;
    border: 1px solid transparent;
    padding: 6px 14px;
    border-radius: 6px;
    cursor: pointer;
}}
[data-testid="stRadio"] div[role="radiogroup"] label p {{
    color: {MUTED} !important;
    font-size: 11px !important;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    font-weight: 700;
    margin: 0 !important;
}}
[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {{
    background: {BG_ELEVATED} !important;
    box-shadow: inset 0 -2px 0 0 {GREEN};
}}
[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) p {{
    color: {TEXT_STRONG} !important;
}}
/* Hide the radio circles */
[data-testid="stRadio"] div[role="radiogroup"] label > div:first-child {{ display: none; }}

/* DataFrame polish */
[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    overflow: hidden;
}}

/* Sidebar controls tighter */
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 {{
    color: {TEXT_STRONG};
    font-size: 13px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    font-weight: 700;
}}
</style>
"""


def inject() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
