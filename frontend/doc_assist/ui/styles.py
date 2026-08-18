"""All custom CSS in one place, injected once at startup."""

import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

:root {
    --doc-width: 680px;
    --doc-pad: 28px;
    --header-h: 3.75rem;   /* Streamlit's fixed header overlays the page */

    /* Horizontal nudge applied ONLY when the sidebar is collapsed.
       The scrollbar eats width on the right edge only, so a centred
       column sits half a scrollbar-width to the left. 8px ≈ half a
       standard 16px scrollbar. Raise or lower this single number
       until it looks dead centre on your display. */
    --collapsed-nudge: 8px;
}

.stApp { font-family: 'IBM Plex Sans', sans-serif; }

[data-testid="stIconMaterial"] {
    font-family: 'Material Symbols Rounded', 'Material Icons' !important;
}

/* ------------------------------------------------------------------
   Content column. Streamlit renamed this node across versions, so all
   three names are listed; only the matching one applies.
   ------------------------------------------------------------------ */
[data-testid="stMainBlockContainer"],
[data-testid="stAppViewBlockContainer"],
.block-container {
    max-width: var(--doc-width) !important;
    /* must clear the fixed header, or the first bubble sits under it */
    padding-top: calc(var(--header-h) + 1.25rem) !important;
    padding-left: var(--doc-pad) !important;
    padding-right: var(--doc-pad) !important;
    padding-bottom: 4.5rem !important;
    margin-left: auto !important;
    margin-right: auto !important;
}

/* ------------------------------------------------------------------
   True centring.
   Two things pull the column off-centre, both to the left:
   1. the vertical scrollbar eats width on the right only
   2. a collapsed sidebar can keep a residual min-width
   ------------------------------------------------------------------ */
html, body, .stApp,
[data-testid="stMain"],
[data-testid="stMain"] > div,
[data-testid="stAppViewContainer"] {
    scrollbar-gutter: stable both-edges;
}

/* When the sidebar is collapsed (or absent from the DOM entirely),
   shift the column and the composer right by the same amount so they
   stay locked together. :not(:has(expanded)) catches both states. */
.stApp:not(:has([data-testid="stSidebar"][aria-expanded="true"])) [data-testid="stMainBlockContainer"],
.stApp:not(:has([data-testid="stSidebar"][aria-expanded="true"])) [data-testid="stAppViewBlockContainer"],
.stApp:not(:has([data-testid="stSidebar"][aria-expanded="true"])) .block-container,
.stApp:not(:has([data-testid="stSidebar"][aria-expanded="true"])) [data-testid="stBottomBlockContainer"] {
    transform: translateX(var(--collapsed-nudge));
}
[data-testid="stSidebar"][aria-expanded="false"] {
    width: 0 !important;
    min-width: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
}
[data-testid="stBottomBlockContainer"] {
    margin-left: auto !important;
    margin-right: auto !important;
}

/* ------------------------------------------------------------------
   Header: make it opaque so messages scrolling underneath are masked
   instead of showing through, and keep it above the message stack.
   ------------------------------------------------------------------ */
[data-testid="stHeader"] {
    background: #FFFFFF;
    height: var(--header-h);
    z-index: 100;
    border-bottom: 1px solid transparent;
    backdrop-filter: saturate(180%) blur(8px);
}
/* the thin rainbow/progress strip at the very top */
[data-testid="stDecoration"] { display: none; }
[data-testid="stToolbar"] { background: transparent; }

/* Anchored scrolling should stop below the header, not under it */
[data-testid="stMain"],
[data-testid="stAppViewContainer"] {
    scroll-padding-top: calc(var(--header-h) + 1rem);
}

/* The native bottom container that holds st.chat_input. Streamlit
   already aligns this to the main column and reserves space above it —
   we only match the width/padding so the two share one axis. */
[data-testid="stBottomBlockContainer"] {
    max-width: var(--doc-width) !important;
    padding-left: var(--doc-pad) !important;
    padding-right: var(--doc-pad) !important;
    padding-bottom: 1.75rem !important;
    padding-top: 0.75rem !important;
}
[data-testid="stBottom"] > div { background: transparent; }

/* ---- Hide "Press Enter to submit" hints ---- */
[data-testid="InputInstructions"],
[data-testid="stInputInstructions"],
.stTextInput small {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
}

/* ---- Sidebar ---- */
[data-testid="stSidebar"] {
    background: #FBFBFC;
    border-right: 1px solid #EEEFF3;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 0.25rem; }

.brand-row { display: flex; align-items: center; gap: 9px; margin: 0 0 1rem; }
.brand-icon {
    width: 26px; height: 26px; border-radius: 7px; background: #171B2E;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.brand-word {
    font-family: 'Manrope', sans-serif; font-weight: 700; font-size: 14px;
    letter-spacing: -0.01em; color: #171B2E;
}

[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] {
    justify-content: flex-start; color: #3C4258; font-size: 13px;
    padding: 6px 8px; border-radius: 8px;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] > div {
    justify-content: flex-start; width: 100%;
}
/* Chat History entries: force left-aligned, single-line + ellipsis (not
   Streamlit's default centered button label), matching the Library rows. */
[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] p {
    text-align: left; width: 100%;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"]:hover {
    background: #F0F1F5;
}

/* ---- LIBRARY / CHAT HISTORY: fully transparent, no card chrome ----
   Streamlit paints the expander background on several nested nodes
   (wrapper, <details>, <summary>, and the details body), so all of
   them have to be cleared or a grey card shows through. */
[data-testid="stSidebar"] [data-testid="stExpander"],
[data-testid="stSidebar"] [data-testid="stExpander"] > div,
[data-testid="stSidebar"] [data-testid="stExpander"] details,
[data-testid="stSidebar"] [data-testid="stExpander"] summary,
[data-testid="stSidebar"] [data-testid="stExpanderDetails"],
[data-testid="stSidebar"] [data-testid="stExpanderContent"] {
    background: transparent !important;
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    border-radius: 0 !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: transparent !important;
}
/* the label text still gets a subtle hover cue */
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover [data-testid="stMarkdownContainer"] p {
    color: #9297A6 !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary { padding: 8px 4px; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.05em; color: #B4B8C4;
}
[data-testid="stSidebar"] [data-testid="stExpanderDetails"] { padding-bottom: 6px; }

.doc-row { display: flex; align-items: center; gap: 9px; padding: 7px 8px; }
.doc-row span, .doc-row .doc-link {
    font-size: 12.5px; font-weight: 500; color: #3C4258;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.doc-row .doc-link { text-decoration: none; }
.doc-row .doc-link:hover { color: #171B2E; text-decoration: underline; }
.empty-row { font-size: 12px; color: #B4B8C4; padding: 4px 8px; line-height: 1.6; }

/* ---- Empty-state hero ---- */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
}
.hero {
    text-align: center; padding-top: 12vh; margin-bottom: 1.75rem;
    animation: fadeUp 0.4s ease both;
}
.hero h1 {
    font-family: 'Manrope', sans-serif; font-size: 26px; font-weight: 700;
    letter-spacing: -0.01em; margin: 0 0 8px; color: #171B2E;
}
.hero p { font-size: 13.5px; color: #9297A6; margin: 0; line-height: 1.6; }

/* ==================================================================
   Chat bubbles — alignment lives on the bubble itself, so it does not
   depend on Streamlit's chat DOM.
   ================================================================== */
[class*="st-key-msgrow-"] { margin-bottom: 1.4rem; }
/* NOTE: :first-of-type / :last-of-type are deliberately NOT used here.
   Those pseudo-classes match on element *type* (div) among siblings,
   not on the class — and these rows sit among many other sibling
   divs, so they never reliably match the first/last message. The
   spacers are rendered explicitly in Python instead. */

[class*="st-key-bubble-"] {
    width: fit-content;
    max-width: 84%;
    border-radius: 16px;
    padding: 14px 18px;
    box-sizing: border-box;
    animation: fadeUp 0.3s ease both;
}

/* ------------------------------------------------------------------
   Kill every inherited margin/gap inside the bubble.
   Streamlit stacks stVerticalBlock > stElementContainer > stMarkdown >
   stMarkdownContainer > p, and several of those carry their own
   margins and a flex `gap`. Those margins live INSIDE the bubble's
   padding box, which is why the text was sitting low — extra space
   above it, none below. Zero them all, then re-add paragraph spacing
   deliberately.
   ------------------------------------------------------------------ */
[class*="st-key-bubble-"] [data-testid="stVerticalBlock"],
[class*="st-key-bubble-"] [data-testid="stVerticalBlockBorderWrapper"] {
    gap: 0 !important;
    row-gap: 0 !important;
}
[class*="st-key-bubble-"] > div,
[class*="st-key-bubble-"] > div * {
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    min-height: 0 !important;
}
/* deliberate spacing between paragraphs / list items only */
[class*="st-key-bubble-"] [data-testid="stMarkdownContainer"] p + p,
[class*="st-key-bubble-"] [data-testid="stMarkdownContainer"] p + ul,
[class*="st-key-bubble-"] [data-testid="stMarkdownContainer"] ul + p {
    margin-top: 0.55rem !important;
}
[class*="st-key-bubble-"] [data-testid="stMarkdownContainer"] li + li {
    margin-top: 0.3rem !important;
}

[class*="st-key-bubble-user-"] {
    background: #171B2E;
    margin-left: auto;
    margin-right: 0;
    align-self: flex-end;
}
[class*="st-key-bubble-user-"] [data-testid="stMarkdownContainer"] p {
    color: #fff !important; font-size: 14px; line-height: 1.55;
}

[class*="st-key-bubble-assistant-"] {
    background: #F5F6FA;
    margin-left: 0;
    margin-right: auto;
    align-self: flex-start;
}
[class*="st-key-bubble-assistant-"] [data-testid="stMarkdownContainer"] p,
[class*="st-key-bubble-assistant-"] [data-testid="stMarkdownContainer"] li {
    color: #1A2036 !important; font-size: 14px; line-height: 1.55;
}

.citation-line {
    font-size: 11.5px; color: #9297A6; padding: 6px 4px 0;
    line-height: 1.6; text-align: left;
}

[class*="st-key-bubble-user-"] a,
[class*="st-key-bubble-assistant-"] a,
.citation-line a {
    color: inherit !important; text-decoration: none !important;
    pointer-events: none; cursor: default;
}

/* Explicit spacers — see the note above the msgrow rules */
.top-spacer { height: 0.75rem; }
.bottom-spacer { height: 3.25rem; }

/* ==================================================================
   Native chat input, restyled
   ================================================================== */
/* Fully rounded (pill) composer. Drop to ~24px if you'd rather it
   square off a little as the textarea grows to multiple lines. */
[data-testid="stChatInput"] {
    background: #F5F6FA;
    border: none !important;
    border-radius: 999px;
    box-shadow: none !important;
    overflow: hidden;             /* clip children to the rounded edge */
    padding-left: 6px;
    padding-right: 6px;
}
/* inner wrappers inherit the curve so nothing pokes past the corners */
[data-testid="stChatInput"] > div,
[data-testid="stChatInput"] [data-baseweb="textarea"],
[data-testid="stChatInput"] [data-baseweb="base-input"] {
    border-radius: inherit !important;
    background: transparent !important;
    border: none !important;
}
[data-testid="stChatInput"]:focus-within {
    border: none !important;
    box-shadow: none !important;
    outline: none !important;
}
[data-testid="stChatInput"] textarea {
    font-size: 14px;
    color: #1A2036;
    caret-color: #171B2E;
}
[data-testid="stChatInput"] textarea::placeholder { color: #9297A6; }

[data-testid="stChatInputSubmitButton"],
[data-testid="stChatInputSubmitButton"]:hover {
    background: #171B2E !important;
    border-radius: 50%;
    width: 34px;
    height: 34px;
    color: #fff !important;
}
[data-testid="stChatInputSubmitButton"] svg,
[data-testid="stChatInputSubmitButton"] span {
    fill: #fff !important;
    color: #fff !important;
}
[data-testid="stChatInputSubmitButton"]:disabled {
    background: #D8DAE2 !important;
}
[data-testid="stChatInputFileUploadButton"] {
    color: #6B7280 !important;
}
[data-testid="stChatInputFileUploadButton"]:hover {
    background: #EFF0F5 !important;
    border-radius: 50%;
}

/* ---- File uploader (sidebar fallback) ---- */
[data-testid="stFileUploader"] {
    border: 1.5px dashed #D1D5DB;
    border-radius: 10px;
    padding: 12px;
    background: #F9FAFB;
}
[data-testid="stFileUploader"]:hover {
    border-color: #9CA3AF; background: #F3F4F6;
}
[data-testid="stFileUploader"] section { padding: 0px !important; }
[data-testid="stFileUploader"] small {
    color: #9CA3AF !important; font-size: 11.5px;
}

/* ---- Suggestion chips ---- */
[class*="st-key-suggestion-row"] { margin-top: 0.25rem; }
[class*="st-key-suggestion-row"] button {
    border-radius: 999px !important;
    border: 1px solid #EEEFF3 !important;
    background: #fff !important;
    color: #6B7280 !important;
    font-size: 11.5px !important;
    min-height: 42px !important;
    height: 42px !important;
    padding: 4px 10px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    text-align: center !important;
    white-space: normal !important;
    line-height: 1.25 !important;
    outline: none !important;
}
[class*="st-key-suggestion-row"] button:focus {
    outline: none !important; box-shadow: none !important;
}

[data-testid="stSpinner"] > div { color: #B4B8C4; font-size: 12.5px; }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
