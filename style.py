# style.py
# Single source of visual styling for the whole app.
#
# Theme system: light mode by default, user-toggleable dark mode via
# st.session_state.theme. Rather than CSS custom properties (fiddlier to
# toggle reliably across Streamlit's own re-injected DOM), each rerun just
# builds the full stylesheet from the active token dict and re-injects it.
from typing import Optional
import streamlit as st
import streamlit.components.v1 as components

LIGHT = {
    "paper": "#FBFAF6",
    "paper_raised": "#FFFFFF",
    "ink": "#1C1B18",
    "muted": "#726F66",
    "muted_soft": "#8C8A80",
    "hairline": "#E7E3D8",
    "hairline_strong": "#D8D3C4",
    "accent": "#3F4A3D",
    "accent_soft": "#EDEFE9",
    "card_fill": "#F4F2EA",
    "button_bg": "#1C1B18",
    "button_text": "#FBFAF6",
    "button_hover": "#3A3934",
}

DARK = {
    "paper": "#15140F",
    "paper_raised": "#1B1A14",
    "ink": "#F2EFE6",
    "muted": "#9C988C",
    "muted_soft": "#8A8779",
    "hairline": "#34322B",
    "hairline_strong": "#403D33",
    "accent": "#8FA888",
    "accent_soft": "#20241E",
    "card_fill": "#1E1D17",
    "button_bg": "#F2EFE6",
    "button_text": "#15140F",
    "button_hover": "#D8D5C9",
}


def _inject_dom_fixups(t: dict):
    """Runs real JS against the live page DOM to fix two things CSS alone
    couldn't reliably reach:

    1. Text input / textarea borders. Multiple rounds of CSS selectors
       guessing the exact wrapper depth ([data-testid=...] > div, :has(),
       etc) either produced a double border or no border at all -- the
       exact DOM nesting Streamlit uses here wasn't matching what any of
       those selectors assumed. This walks up from the actual <input>/
       <textarea> element itself, borders exactly ONE ancestor level (so
       there's never a double border by construction), and explicitly
       strips border/background from a few levels above that in case any
       of them carry a stray default border -- rather than guessing which
       level is "the" box, it fixes the box regardless of which level it
       turns out to be.
    2. Calendar filler-day cells. Previous attempts were plain CSS
       (:not([aria-roledescription]), :empty, etc) that kept losing to a
       Streamlit rule we couldn't identify. This finds any calendar
       gridcell with no visible text and paints it directly.

    Uses streamlit.components.v1.html rather than a <script> tag inside
    st.markdown(unsafe_allow_html=True) -- script tags inserted via
    unsafe_allow_html/innerHTML are never executed by the browser (a
    standard browser behavior, not a Streamlit bug), which is why an
    earlier version of this fix silently did nothing. components.html runs
    in an iframe but is same-origin, so window.parent.document reaches the
    real page.
    """
    paper = t["paper_raised"]
    hairline = t["hairline_strong"]
    ink = t["ink"]
    js = f"""
    <script>
    (function() {{
        const doc = window.parent.document;
        const PAPER = "{paper}";
        const HAIRLINE = "{hairline}";
        const INK = "{ink}";

        function fixTextBoxes() {{
            doc.querySelectorAll('[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea')
              .forEach(function(el) {{
                el.style.setProperty('background', 'transparent', 'important');
                el.style.setProperty('color', INK, 'important');
                el.style.setProperty('border', 'none', 'important');
                el.style.setProperty('outline', 'none', 'important');
                el.style.setProperty('box-shadow', 'none', 'important');

                let node = el.parentElement;
                for (let level = 0; node && level < 4; level++, node = node.parentElement) {{
                    if (level === 0) {{
                        // exactly one ancestor gets the visible box -- this
                        // is what stops a double border from appearing
                        node.style.setProperty('background', PAPER, 'important');
                        node.style.setProperty('border', '1px solid ' + HAIRLINE, 'important');
                        node.style.setProperty('border-radius', '8px', 'important');
                    }} else {{
                        // strip any border/background further up so nothing
                        // else can paint a second box behind the first
                        node.style.setProperty('border', 'none', 'important');
                        node.style.setProperty('background', 'transparent', 'important');
                        node.style.setProperty('box-shadow', 'none', 'important');
                    }}
                    node.style.setProperty('outline', 'none', 'important');
                }}
            }});
        }}

        function fixCalendarFillerCells() {{
            const cal = doc.querySelector('div[data-baseweb="calendar"]');
            if (!cal) return;
            // Don't assume role="gridcell" -- that selector matched nothing
            // for the filler cells in this Streamlit version, meaning they
            // don't carry that attribute at all. Instead match the one
            // property actually visible in the screenshots: a leaf element
            // (no element children) with no text. Real day cells always
            // have a number inside, so they're excluded automatically.
            // Nav arrows are excluded by tag (SVG/PATH).
            cal.querySelectorAll('*').forEach(function(el) {{
                const tag = el.tagName;
                if (tag === 'SVG' || tag === 'PATH' || tag === 'BUTTON') return;
                if (el.children.length === 0 && el.textContent.trim() === '') {{
                    el.style.setProperty('background', PAPER, 'important');
                    el.style.setProperty('background-color', PAPER, 'important');
                    el.style.setProperty('border', 'none', 'important');
                    if (el.parentElement) {{
                        el.parentElement.style.setProperty('background', PAPER, 'important');
                        el.parentElement.style.setProperty('background-color', PAPER, 'important');
                        el.parentElement.style.setProperty('border', 'none', 'important');
                    }}
                }}
            }});
        }}

        function fixFileUploaderText() {{
            doc.querySelectorAll('[data-testid="stFileUploaderDropzone"], [data-testid="stFileUploaderFile"]')
              .forEach(function(container) {{
                container.querySelectorAll('div, span, small, p').forEach(function(el) {{
                    if (el.children.length === 0 && el.textContent.trim() !== '') {{
                        el.style.setProperty('color', INK, 'important');
                    }}
                }});
            }});
        }}

        function runAll() {{
            fixTextBoxes();
            fixCalendarFillerCells();
            fixFileUploaderText();
        }}

        runAll();
        // form fields and the calendar popover render after this script's
        // first pass (and the calendar doesn't exist until clicked), so
        // watch for DOM changes and re-run
        new MutationObserver(runAll).observe(doc.body, {{ childList: true, subtree: true }});
        // Belt-and-suspenders fallback: st.dialog's input wasn't picking up
        // this fix even though the observer should cover it -- native
        // browser <dialog> "top layer" rendering is a plausible reason a
        // childList/subtree observer on doc.body could miss it. A cheap
        // interval catches that case without betting the whole fix on
        // diagnosing the exact mechanism.
        setInterval(runAll, 400);
    }})();
    </script>
    """
    components.html(js, height=0)


def get_theme() -> dict:
    return DARK if st.session_state.get("theme") == "dark" else LIGHT


def inject_base_css():
    t = get_theme()
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,600;0,9..144,700;1,9..144,500&family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"] {{
            font-family: 'Inter', sans-serif;
        }}

        #MainMenu, footer, header {{visibility: hidden;}}
        [data-testid="stDecoration"] {{display: none;}}

        .stApp {{
            background: {t['paper']};
        }}

        .block-container {{
            padding-top: 1.25rem;
            max-width: 1100px;
            margin-left: auto !important;
            margin-right: auto !important;
        }}

        /* generic text colors for Streamlit's own elements (tables, labels,
           form widgets in section pages) so the theme reaches beyond our
           custom markup blocks */
        .stApp, .stApp p, .stApp label, .stMarkdown, .stText {{
            color: {t['ink']};
        }}
        .stApp small, .stCaption {{
            color: {t['muted']};
        }}

        /* st.dialog had no rules at all -- it was falling back entirely to
           Streamlit's native default styling (dark bg regardless of our
           toggle), same gap as the expander/spinner before this. Covers
           both the modern testid and the raw <dialog> element as a
           fallback in case the testid name has drifted. */
        [data-testid="stDialog"], div[role="dialog"], dialog {{
            background: {t['paper_raised']} !important;
            border: 1px solid {t['hairline']} !important;
            color: {t['ink']} !important;
        }}
        [data-testid="stDialog"] p,
        [data-testid="stDialog"] li,
        [data-testid="stDialog"] label,
        [data-testid="stDialog"] h1,
        [data-testid="stDialog"] h2,
        [data-testid="stDialog"] h3,
        [data-testid="stDialog"] strong,
        div[role="dialog"] p,
        div[role="dialog"] li,
        div[role="dialog"] label {{
            color: {t['ink']} !important;
        }}
        /* the key-entry input itself: CSS-level backstop in case the JS
           pass (which handles this everywhere else on the page) doesn't
           reach inside the dialog's top-layer rendering */
        [data-testid="stDialog"] input,
        div[role="dialog"] input {{
            background: {t['paper']} !important;
            color: {t['ink']} !important;
            border: 1px solid {t['hairline']} !important;
        }}
        [data-testid="stDialog"] input::placeholder,
        div[role="dialog"] input::placeholder {{
            color: {t['muted']} !important;
        }}
        /* the password-reveal "eye" icon button was rendering white-on-white */
        [data-testid="stDialog"] button svg,
        div[role="dialog"] button svg {{
            fill: {t['ink']} !important;
            color: {t['ink']} !important;
        }}
        [data-testid="stDataFrame"], [data-testid="stTable"] {{
            border: 1px solid {t['hairline']};
            border-radius: 10px;
        }}
        /* st.dataframe / st.data_editor render their grid on a <canvas> via
           Glide Data Grid, so normal CSS selectors can't reach the cell
           colors -- it paints using Streamlit's own light/dark theme
           (config.toml), not our custom toggle-driven variables. Glide
           reads its palette from these CSS custom properties at paint
           time, so setting them on the grid's container lets it follow
           our theme instead. */
        [data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {{
            --gdg-bg-cell: {t['paper_raised']};
            --gdg-bg-cell-medium: {t['paper']};
            --gdg-bg-header: {t['paper']};
            --gdg-bg-header-has-focus: {t['hairline']};
            --gdg-bg-header-hovered: {t['hairline']};
            --gdg-text-dark: {t['ink']};
            --gdg-text-medium: {t['ink']};
            --gdg-text-light: {t['muted']};
            --gdg-text-header: {t['ink']};
            --gdg-text-header-selected: {t['ink']};
            --gdg-border-color: {t['hairline']};
            --gdg-horizontal-border-color: {t['hairline']};
            --gdg-bg-bubble: {t['paper_raised']};
            --gdg-bg-bubble-selected: {t['hairline']};
            --gdg-bg-search-result: {t['accent_soft']};
            --gdg-accent-color: {t['accent']};
            --gdg-accent-fg: {t['paper_raised']};
            --gdg-accent-light: {t['accent_soft']};
            --gdg-bg-icon-header: {t['muted']};
            --gdg-fg-icon-header: {t['paper_raised']};
        }}

        /* ── text inputs / textareas ──────────────────────────────────────
           IMPORTANT: the border/background live on whichever div directly
           WRAPS the raw <input>/<textarea> -- using :has() to select that
           div directly, rather than guessing a fixed nesting depth
           ([data-testid="stTextInput"] > div etc), because guessing the
           depth wrong is exactly what caused two earlier bugs: a double
           border (border applied to the wrong, non-visual div while some
           other div still drew its own) and the Notes box going solid
           black (the div we targeted wasn't the real box, so it never got
           a background, and the textarea above it was set to transparent --
           letting Streamlit's unstyled black default show through). :has()
           finds the actual immediate parent regardless of depth, so this
           can't drift out of sync with Streamlit's DOM again. */
        [data-testid="stTextInput"] div:has(> input),
        [data-testid="stTextArea"] div:has(> textarea) {{
            background: {t['paper_raised']} !important;
            border: 1px solid {t['hairline_strong']} !important;
            box-shadow: none !important;
            outline: none !important;
            border-radius: 8px !important;
        }}
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea {{
            background: transparent !important;
            color: {t['ink']} !important;
            border: none !important;
            box-shadow: none !important;
            outline: none !important;
        }}
        [data-testid="stTextInput"] input::placeholder,
        [data-testid="stTextArea"] textarea::placeholder {{
            color: {t['muted_soft']} !important;
        }}
        /* "Press Enter to submit/apply" hint text under inputs */
        [data-testid="InputInstructions"],
        [data-testid="InputInstructions"] * {{
            color: {t['muted_soft']} !important;
        }}
        /* visible focus state so clicking into a field still reads clearly,
           without swapping any text/background to BaseWeb's own default
           (which is what was causing the white-on-click text) */
        [data-testid="stTextInput"] div:has(> input):focus-within,
        [data-testid="stTextArea"] div:has(> textarea):focus-within,
        div[data-baseweb="input"]:focus-within,
        div[data-baseweb="select"]:focus-within {{
            border-color: {t['hairline_strong']} !important;
            outline: none !important;
        }}

        /* ── selects, date inputs ──────────────────────────────────────────
           Same wrapper-only-border principle as above. Additionally, the
           color rule now targets EVERY descendant (`*`), not just the
           direct child div -- BaseWeb renders the selected value into a
           nested span that carries its own color from BaseWeb's internal
           theme, which is what was showing up as white text the moment you
           clicked/selected a value. Coloring only the outer wrapper left
           that inner span untouched, same root cause as the dropdown-list
           bug fixed earlier. */
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div,
        div[data-baseweb="datepicker"] > div {{
            background: {t['paper_raised']} !important;
            border: 1px solid {t['hairline_strong']} !important;
            box-shadow: none !important;
            outline: none !important;
            border-radius: 8px !important;
        }}
        div[data-baseweb="select"] *,
        div[data-baseweb="datepicker"] * {{
            color: {t['ink']} !important;
        }}
        div[data-baseweb="input"] input,
        div[data-baseweb="datepicker"] input {{
            background: transparent !important;
            color: {t['ink']} !important;
            border: none !important;
            box-shadow: none !important;
        }}
        div[data-baseweb="select"] svg {{
            fill: {t['muted']} !important;
        }}

        /* the popover dropdown menu that opens on click. Needs to hit the
           <li> options AND everything inside them explicitly -- BaseWeb
           renders each option's label in a nested span with its own
           inherited color from BaseWeb's internal theme, so coloring only
           the outer ul/menu wrapper leaves the option text unaffected. */
        div[data-baseweb="popover"] ul,
        div[data-baseweb="menu"],
        div[data-baseweb="popover"] li,
        div[data-baseweb="menu"] li,
        div[data-baseweb="popover"] li *,
        div[data-baseweb="menu"] li * {{
            background: {t['paper_raised']} !important;
            color: {t['ink']} !important;
        }}
        div[data-baseweb="popover"] ul,
        div[data-baseweb="menu"] {{
            border: 1px solid {t['hairline']} !important;
        }}
        div[data-baseweb="popover"] li:hover,
        div[data-baseweb="popover"] li:hover * {{
            background: {t['accent_soft']} !important;
        }}

        /* date-picker calendar popup -- a separate BaseWeb component
           (data-baseweb="calendar") that the select/menu rules above never
           touch, so without this it falls back to BaseWeb's own default
           dark calendar theme regardless of our light/dark mode. */
        div[data-baseweb="calendar"],
        div[data-baseweb="calendar"] * {{
            background: {t['paper_raised']} !important;
            color: {t['ink']} !important;
            border-color: {t['hairline']} !important;
        }}
        div[data-baseweb="calendar"] button {{
            background: transparent !important;
            color: {t['ink']} !important;
        }}
        div[data-baseweb="calendar"] [aria-selected="true"],
        div[data-baseweb="calendar"] [aria-selected="true"] * {{
            background: {t['accent']} !important;
            color: {t['button_text']} !important;
        }}
        div[data-baseweb="calendar"] button:hover,
        div[data-baseweb="calendar"] button:hover * {{
            background: {t['accent_soft']} !important;
        }}
        /* empty filler-day cells at start/end of month grid -- CSS-only
           attempts (aria-roledescription, aria-disabled, :empty) all lost
           to a Streamlit rule I couldn't pin down. Moved to the script
           below instead, which sets an inline style directly on the
           element -- inline !important always wins the cascade regardless
           of any stylesheet's specificity, so this sidesteps the
           specificity war entirely rather than guessing again. */

        /* empty filler-day cells: confirmed via inspected HTML that the
           JS fix (_inject_dom_fixups below) is correctly setting the real
           element's own background to white/paper inline -- yet it still
           renders black. That means the black fill is coming from a
           ::before/::after pseudo-element layered on top, not the
           element's own background. Pseudo-elements aren't real DOM nodes,
           so JS (el.style.background = ...) structurally cannot reach them
           -- this has to be CSS. :empty is confirmed to match this exact
           element (the provided HTML has zero children), which real day
           cells never do since they always contain a number. */
        html body div[data-baseweb="calendar"] [role="gridcell"]:empty::before,
        html body div[data-baseweb="calendar"] [role="gridcell"]:empty::after {{
            display: none !important;
            content: none !important;
            background: transparent !important;
            border: none !important;
        }}

        /* ── header row: back link (left) + theme toggle (right) ──────── */
        .ah-header-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
        }}

        /* narrow, centered wrapper used on landing / choice screens.
           Flex + align-items:center is used instead of relying purely on
           margin:auto, because Streamlit's own markdown wrapper divs can
           shrink-wrap to content width, which would make margin:auto a
           no-op and leave text hugging the left edge while sibling
           st.columns-based content (like the CTA button) centers fine. */
        .ah-narrow {{
            width: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            margin-top: 8vh;
            text-align: center;
        }}
        .ah-narrow > * {{
            max-width: 640px;
        }}

        .ah-eyebrow {{
            font-family: 'Inter', sans-serif;
            font-size: 0.78rem;
            font-weight: 600;
            color: {t['muted']};
            margin-bottom: 2rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }}

        .ah-title {{
            font-family: 'Fraunces', serif;
            font-optical-sizing: auto;
            font-size: 4.4rem;
            font-weight: 600;
            color: {t['ink']};
            margin-bottom: 1.35rem;
            line-height: 1.03;
            letter-spacing: -0.01em;
        }}

        .ah-title-mid {{
            font-family: 'Fraunces', serif;
            font-optical-sizing: auto;
            font-size: 2.05rem;
            font-weight: 600;
            font-style: normal;
            color: {t['ink']};
            margin-bottom: 2rem;
            line-height: 1.35;
        }}

        .ah-body {{
            font-size: 1.08rem;
            color: {t['ink']};
            line-height: 1.7;
            margin-bottom: 0.5rem;
        }}

        .ah-body-muted {{
            font-size: 0.92rem;
            color: {t['muted']};
            line-height: 1.65;
            margin-bottom: 2.25rem;
        }}

        .ah-page-desc {{
            font-family: 'Fraunces', serif;
            font-style: normal;
            font-size: 1.15rem;
            font-weight: 500;
            color: {t['ink']};
            padding-bottom: 1rem;
            margin-bottom: 1.75rem;
            border-bottom: 1px solid {t['hairline']};
            text-align: left;
            line-height: 1.5;
        }}

        /* card visuals -- the actual click target is an invisible button
           layered on top, see .st-key-card_* rules below */
        .ah-card {{
            background: {t['card_fill']};
            border: 1px solid {t['hairline']};
            border-radius: 10px;
            padding: 2.75rem 1.5rem;
            text-align: center;
            pointer-events: none;
            transition: border-color 0.15s ease, transform 0.15s ease;
        }}

        .ah-card-title {{
            font-family: 'Fraunces', serif;
            font-weight: 600;
            font-size: 1.35rem;
            color: {t['ink']};
            margin: 0 0 0.4rem 0;
        }}

        .ah-card-sub {{
            font-size: 0.92rem;
            color: {t['muted']};
            margin: 0;
        }}

        div[class*="st-key-card_"]:hover:not([class*="_btn"]) .ah-card {{
            border-color: {t['accent']};
        }}

        /* primary CTA buttons -- bordered pill, letterspaced, ink-on-hover.
           High specificity + !important because Streamlit's own primary/
           form-submit button styles otherwise win the cascade and stay
           black-on-black regardless of our base .stButton rule. */
        .stButton > button,
        .stButton > button[kind="primary"],
        .stButton > button[kind="secondary"],
        [data-testid="stFormSubmitButton"] button,
        [data-testid="baseButton-primary"],
        [data-testid="baseButton-secondary"] {{
            background: transparent !important;
            color: {t['ink']} !important;
            border: 1px solid {t['hairline_strong']} !important;
            border-radius: 999px !important;
            padding: 0.7rem 1.9rem !important;
            font-weight: 600 !important;
            font-size: 0.82rem !important;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
        }}
        .stButton > button:hover,
        [data-testid="stFormSubmitButton"] button:hover,
        [data-testid="baseButton-primary"]:hover,
        [data-testid="baseButton-secondary"]:hover {{
            background: {t['button_bg']} !important;
            color: {t['button_text']} !important;
            border-color: {t['button_bg']} !important;
        }}
        .stButton > button p,
        [data-testid="stFormSubmitButton"] button p {{
            color: inherit !important;
        }}

        /* file uploader's "Browse files" button -- targeted structurally
           (any button inside the dropzone) rather than by a specific
           data-testid string, since the exact testid Streamlit uses here
           has drifted before (see stTextInput/stBaseButton naming changes
           elsewhere in this file) and matching by structure instead of a
           guessed attribute value is what actually holds up across
           versions. */
        [data-testid="stFileUploaderDropzone"] button {{
            background: transparent !important;
            color: {t['ink']} !important;
            border: 1px solid {t['hairline_strong']} !important;
            border-radius: 999px !important;
        }}
        [data-testid="stFileUploaderDropzone"] button:hover {{
            background: {t['button_bg']} !important;
            color: {t['button_text']} !important;
            border-color: {t['button_bg']} !important;
        }}
        [data-testid="stFileUploaderDropzone"] button p,
        [data-testid="stFileUploaderDropzone"] button span {{
            color: inherit !important;
        }}

        .st-key-theme_toggle {{
            display: flex;
            justify-content: flex-end;
        }}

        /* back link + theme toggle -- identical pill footprint for visual
           symmetry: same padding, font-size, height, no wrap, no oversized
           glyphs blowing up the box. */
        .st-key-back_nav button,
        .st-key-theme_toggle button {{
            background: transparent !important;
            color: {t['muted']} !important;
            border: 1px solid transparent !important;
            border-radius: 999px !important;
            padding: 0.45rem 1rem !important;
            font-size: 0.82rem !important;
            font-weight: 500 !important;
            text-transform: none !important;
            letter-spacing: 0 !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
            width: auto !important;
            min-width: 0 !important;
        }}
        .st-key-back_nav button:hover,
        .st-key-theme_toggle button:hover {{
            color: {t['ink']} !important;
            background: transparent !important;
        }}
        /* theme toggle additionally gets a visible hairline border so it
           reads as a control, matching its outlined-pill twin position */
        .st-key-theme_toggle button {{
            border-color: {t['hairline']} !important;
        }}
        .st-key-theme_toggle button:hover {{
            border-color: {t['hairline_strong']} !important;
        }}
        /* kill any emoji/glyph size inflation inside these buttons */
        .st-key-back_nav button p,
        .st-key-theme_toggle button p {{
            font-size: 0.82rem !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
        }}

        /* onboarding wizard nav row (Back / Skip / Next) -- same small pill
           footprint as back_nav/theme_toggle above, not the big uppercase
           CTA style .stButton gets by default. This block was previously
           MISSING from style.py entirely, which is why the wizard buttons
           were falling through to default .stButton styling. Each wrap
           also controls its own flex alignment so Back sits flush left,
           Skip is centered under the progress dots, and Next/Let's go
           sits flush right. */
        .st-key-onb_back_wrap {{
            width: 100% !important;
        }}
        .st-key-onb_skip_wrap {{
            width: 100% !important;
        }}
        .st-key-onb_next_wrap {{
            width: 100% !important;
        }}
        /* Streamlit nests the actual <button> a few div levels deep inside
           the container(key=...) wrapper (same issue the card overlay fix
           above has to work around), so a flex/justify-content rule on the
           outer wrap alone doesn't reach the button -- each intermediate
           level needs to be forced to full width too, or it just shrinks to
           the button's own content size and alignment has nothing to act on. */
        .st-key-onb_back_wrap > div,
        .st-key-onb_back_wrap .stButton,
        .st-key-onb_back_wrap .stButton > div,
        .st-key-onb_skip_wrap > div,
        .st-key-onb_skip_wrap .stButton,
        .st-key-onb_skip_wrap .stButton > div,
        .st-key-onb_next_wrap > div,
        .st-key-onb_next_wrap .stButton,
        .st-key-onb_next_wrap .stButton > div {{
            width: 100% !important;
        }}
        /* now that every level is guaranteed full-width, position the
           button itself via margin: auto -- more robust than justify-content
           since it doesn't depend on the button's own div being a flex item */
        .st-key-onb_back_wrap button {{
            display: block !important;
            margin-right: auto !important;
            margin-left: 0 !important;
        }}
        .st-key-onb_skip_wrap button {{
            display: block !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }}
        .st-key-onb_next_wrap button {{
            display: block !important;
            margin-left: auto !important;
            margin-right: 0 !important;
        }}
        .st-key-onb_back_wrap button,
        .st-key-onb_skip_wrap button,
        .st-key-onb_next_wrap button {{
            background: transparent !important;
            color: {t['muted']} !important;
            border: 1px solid transparent !important;
            border-radius: 999px !important;
            padding: 0.45rem 1rem !important;
            font-size: 0.82rem !important;
            font-weight: 500 !important;
            text-transform: none !important;
            letter-spacing: 0 !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
            width: auto !important;
            min-width: 0 !important;
        }}
        .st-key-onb_back_wrap button:hover,
        .st-key-onb_skip_wrap button:hover,
        .st-key-onb_next_wrap button:hover {{
            color: {t['ink']} !important;
            background: transparent !important;
        }}
        .st-key-onb_back_wrap button p,
        .st-key-onb_skip_wrap button p,
        .st-key-onb_next_wrap button p {{
            font-size: 0.82rem !important;
            line-height: 1.2 !important;
            white-space: nowrap !important;
        }}

        /* whole-card click targets: any container whose key starts with
           "card_" gets an invisible button stretched over the card markdown.
           Newer Streamlit wraps the button in its own height:auto element
           wrapper, so we have to force every level to fill its parent, not
           just the <button> itself, or the overlay collapses to 0 height. */
        div[class*="st-key-card_"]:not([class*="_btn"]) {{
            position: relative;
            height: 100%;
        }}
        div[class*="st-key-card_"][class*="_btn"] {{
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
        }}
        div[class*="st-key-card_"][class*="_btn"] > div,
        div[class*="st-key-card_"][class*="_btn"] .stButton,
        div[class*="st-key-card_"][class*="_btn"] .stButton > div {{
            width: 100%;
            height: 100%;
        }}
        div[class*="st-key-card_"][class*="_btn"] button {{
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            opacity: 0;
            cursor: pointer;
            border: none;
            padding: 0;
            margin: 0;
            z-index: 5;
        }}

        .ah-tag {{
            display: inline-block;
            padding: 0.22rem 0.7rem;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 500;
            margin: 0.15rem;
            background: {t['accent_soft']};
            color: {t['accent']};
            border: 1px solid {t['hairline']};
        }}

        /* score card (JD Match "overall match" tile) */
        .ah-score-card {{
            pointer-events: auto;
        }}
        .ah-score-label {{
            font-size: 0.92rem;
            color: {t['muted']};
        }}
        .ah-score-value {{
            font-family: 'Fraunces', serif;
            font-size: 3.2rem;
            font-weight: 600;
            color: {t['ink']};
            line-height: 1.15;
        }}
        .ah-score-caption {{
            font-size: 0.95rem;
            color: {t['muted']};
        }}

        /* tabs */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 1.75rem;
            border-bottom: 1px solid {t['hairline']};
        }}
        .stTabs [data-baseweb="tab"] {{
            background: transparent;
            color: {t['muted']};
            font-weight: 500;
            font-size: 0.92rem;
            padding: 0.4rem 0;
        }}
        .stTabs [aria-selected="true"] {{
            color: {t['ink']} !important;
            font-weight: 600;
        }}
        .stTabs [data-baseweb="tab-highlight"] {{
            background-color: {t['accent']};
        }}

        /* forms + expanders + file uploader */
        [data-testid="stForm"] {{
            background: {t['paper_raised']};
            border: 1px solid {t['hairline']};
            border-radius: 10px;
            padding: 1.5rem;
        }}
        [data-testid="stExpander"] {{
            background: {t['paper_raised']};
            border: 1px solid {t['hairline']};
            border-radius: 8px;
        }}
        /* expander header text was never given an explicit color, so it
           fell back to Streamlit's own default (light/white) -- invisible
           on our light-mode paper_raised background, though it happened
           to look fine in dark mode by coincidence. */
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary p,
        [data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] {{
            background: {t['paper_raised']} !important;
            color: {t['ink']} !important;
        }}
        [data-testid="stExpander"] summary svg {{
            fill: {t['ink']} !important;
        }}
        /* expander body text -- same missing-color issue */
        [data-testid="stExpanderDetails"] {{
            color: {t['ink']};
        }}
        /* spinner label ("Checking your resume against the job
           description...") had no color rule at all -- same
           inherit-from-default-theme issue as the expander header. */
        [data-testid="stSpinner"] {{
            background: {t['paper_raised']} !important;
            color: {t['ink']} !important;
        }}
        [data-testid="stSpinner"] p {{
            color: {t['ink']} !important;
        }}
        /* st.dialog modals (Groq/Tavily key prompts) -- never had any
           custom CSS at all, so they render on Streamlit's own default
           dark chrome with dark text on top, unreadable regardless of
           our light/dark toggle. Same fix pattern as the expander header
           and spinner above: force both background and text color. */
        [data-testid="stDialog"] {{
            background: {t['paper_raised']} !important;
        }}
        [data-testid="stDialog"] [data-testid="stDialogContent"],
        [data-testid="stDialog"] * {{
            color: {t['ink']};
        }}
        [data-testid="stDialog"] a {{
            color: {t['accent']} !important;
        }}
        [data-testid="stDialog"] code {{
            background: {t['paper']};
            color: {t['ink']};
        }}
        [data-testid="stDialog"] button {{
            border-color: {t['hairline']} !important;
        }}
        [data-testid="stDialog"] [data-testid="stBaseButton-headerNoPadding"] svg,
        [data-testid="stDialog"] button[aria-label="Close"] svg {{
            fill: {t['ink']} !important;
        }}
        [data-testid="stFileUploaderDropzone"] {{
            background: {t['card_fill']};
            border: 1px dashed {t['hairline_strong']};
        }}
        /* dropzone label text ("Drag and drop file here", size/type hint)
           had no explicit color before, so it fell back to a default that
           read as white-on-light. Target the text nodes directly. */
        [data-testid="stFileUploaderDropzone"] div,
        [data-testid="stFileUploaderDropzone"] span,
        [data-testid="stFileUploaderDropzone"] small,
        [data-testid="stFileUploaderDropzone"] p {{
            color: {t['muted']} !important;
        }}
        /* the uploaded-file-name row (filename + size + remove icon) is a
           separate component from the dropzone itself and was never
           targeted at all -- same white-text issue. */
        [data-testid="stFileUploaderFile"],
        [data-testid="stFileUploaderFile"] div,
        [data-testid="stFileUploaderFile"] span,
        [data-testid="stFileUploaderFile"] small {{
            color: {t['ink']} !important;
        }}
        [data-testid="stFileUploaderFileName"] {{
            color: {t['ink']} !important;
        }}
        /* file size caption reads better muted rather than full ink */
        [data-testid="stFileUploaderFile"] small {{
            color: {t['muted']} !important;
        }}

        /* alert boxes */
        [data-testid="stAlertContainer"] {{
            border-radius: 8px;
            border: 1px solid {t['hairline']};
        }}

        /* progress bar */
        .stProgress > div > div {{
            background: {t['accent']};
        }}

        @media (max-width: 640px) {{
            .ah-title {{ font-size: 2.8rem; }}
            .ah-title-mid {{ font-size: 1.5rem; }}
        }}
    </style>
    """, unsafe_allow_html=True)
    _inject_dom_fixups(t)


def clickable_card(key: str, title: str, subtitle: str) -> bool:
    """Renders a card whose entire surface is clickable (not a card plus a
    separate button below it). Returns True on the run where it was clicked."""
    with st.container(key=f"card_{key}"):
        st.markdown(
            f'<div class="ah-card"><div class="ah-card-title">{title}</div>'
            f'<div class="ah-card-sub">{subtitle}</div></div>',
            unsafe_allow_html=True,
        )
        return st.button(title, key=f"card_{key}_btn", use_container_width=True)


def render_header(back_target: Optional[str] = None, go_fn=None):
    """Top row shown on every page: back link on the left (if a target is
    given), theme toggle always on the right."""
    left, right = st.columns([8, 1], vertical_alignment="top")
    with left:
        if back_target and go_fn:
            with st.container(key="back_nav"):
                if st.button("← Back", key=f"back_to_{back_target}"):
                    go_fn(back_target)
    with right:
        with st.container(key="theme_toggle"):
            is_dark = st.session_state.get("theme") == "dark"
            label = "☀ Light" if is_dark else "☾ Dark"
            if st.button(label, key="theme_toggle_btn"):
                st.session_state.theme = "light" if is_dark else "dark"
                st.rerun()