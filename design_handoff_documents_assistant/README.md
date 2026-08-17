# Handoff: Internal Documents Assistant

## Overview
A minimal, single-page chat assistant for querying internal PDF documents (HR policies, SOPs, manuals, onboarding docs). Users upload PDFs, the assistant ingests them, and answers questions with grounded, cited responses.

## About the Design Files
The bundled HTML file is a **design reference** — an interactive prototype built to show intended look, layout, and behavior. It is not production code to copy directly. Recreate this design in the target codebase's existing environment (React, Vue, etc.) using its established patterns, component library, and state management — or, if no environment exists yet, choose the most appropriate framework and implement it there.

## Fidelity
**High-fidelity.** Colors, typography, spacing, and interaction states below should be treated as final and recreated pixel-accurately using the codebase's own component/styling system.

## Screens / Views

### Single view: Chat workspace
Two-column layout, full viewport height, no scroll on the outer shell.

**Layout**
- Root: `display:flex; height:100vh; width:100%; background:#fff;`
- Left: collapsible sidebar, `264px` wide when open, animates to `0px` width (0.18s ease) when collapsed.
- Right: main column (`flex:1`), containing a slim header and a scrollable content area.

#### Sidebar (`#FBFBFC` background, 1px right border `#EEEFF3`)
- Padding `22px 18px`, vertical stack, `gap:22px`.
- **Brand mark**: 26×26px dark rounded-square icon (`#171B2E` bg, white document glyph) + wordmark "Doc Assist" (Manrope 700, 14px).
- **Library** (collapsible section, default open):
  - Header row: uppercase label "Library" (11px, 600 weight, `#B4B8C4`, 0.05em tracking) + chevron icon that rotates -90deg when collapsed.
  - Body: shows an "Ingesting…" row with spinner while a PDF is processing; then a flat list of ingested documents (13px doc icon + 12.5px filename, truncated with ellipsis). Empty state: "No documents yet." (12px, `#B4B8C4`).
- **Chat History** (collapsible section, default open, same header style as Library):
  - Flat list of past chat titles (13px chat-bubble icon + 12.5px title text, truncated). Empty state: "No past chats yet."

#### Header (main column)
- Height auto, padding `16px 28px`, flex space-between.
- Left: sidebar-collapse toggle button (26×26px, chevron icon rotates 180deg on collapse).
- Right: overflow "…" (kebab) icon button, 28×28px.
- No page title, no status indicator, no Deploy button (all intentionally removed).

#### Main content column
- Scrollable container, centered column `max-width:640px`, `padding:0 28px 28px`.
- `padding-top` is `28vh` when no messages exist yet (centers the empty state vertically), collapses to `32px` once a conversation starts.
- **Empty state** (shown only when no messages):
  - H1 "Ask about your documents" — Manrope 700, 26px, `-0.01em` tracking, `#171B2E`.
  - Subtext "Upload a PDF, then ask a question to get a grounded, cited answer." — 13.5px, `#9297A6`.
- **Composer** (chat input bar) — sits directly below the empty-state heading/subtext, above the message list:
  - Pill container: `background:#F5F6FA; border-radius:14px; padding:6px 6px 6px 10px;` flex row, `align-items:flex-end`, `gap:8px`.
  - **"+" button** (left of textarea): 32×32px, transparent bg, `#6B7280` plus-icon. Opens a hidden native file picker (`accept="application/pdf"`, multiple). On file selection, auto-triggers ingestion (no separate "Ingest" button) — this is a change from an earlier iteration where the upload control lived in the sidebar.
  - Textarea: flex:1, no border, transparent bg, 14px text, placeholder "Message Doc Assist…", auto-behaves as single line growing to `max-height:120px`, Enter sends (Shift+Enter = newline).
  - Send button: 32×32px rounded square, dark (`#171B2E`) when input has text, light gray (`#D6DAE3`) + `not-allowed` cursor when empty/thinking; white up-arrow icon.
- **Suggestion chips** (only in empty state, appear below the composer): 3 pill buttons, 1px border `#EEEFF3`, white bg, `#6B7280` text, 12px — "Summarize the onboarding guide", "What's the PTO policy?", "List required SOP approvals". Clicking one sends that question immediately.
- **Message list** (appears below composer/chips once populated):
  - User messages: right-aligned, dark bubble (`#171B2E` bg, white text), rounded 14px, max-width 84%.
  - Assistant messages: left-aligned, light bubble (`#F5F6FA` bg, `#1A2036` text), same radius/max-width.
  - Citation line under assistant replies (when applicable): 11px, `#B4B8C4`, e.g. "policy.pdf · p. 4".
  - "Thinking…" indicator (12.5px, `#B4B8C4`) shown while awaiting a reply.
  - Messages fade/slide in (`fadeUp` keyframe: opacity 0→1, translateY 6px→0, 0.3–0.4s ease).

## Interactions & Behavior
- **Sidebar collapse**: toggle button flips a boolean; sidebar width animates 264px ↔ 0px.
- **Section collapse** (Library / Chat History): independent booleans, chevron rotates 0deg ↔ -90deg, default both open.
- **File upload**: "+" button opens native file picker → on change, sets an `isIngesting` flag (shows spinner row in Library for ~1.2s, simulating processing) → appends file(s) to the `docs` list and ensures the Library section is expanded so the user sees the result.
- **Sending a message**:
  1. Guard: ignore empty/whitespace input or if already thinking.
  2. Push user message (right-aligned, dark bubble) to `messages`, clear input, set `isThinking: true`.
  3. If this is the first message in the session, also prepend a new entry to `history` (title = first ~40 chars of the question).
  4. After a simulated delay (~1.1s), push an assistant reply: if documents exist, a grounded-sounding answer citing the first doc + a fabricated page number; if no documents exist, a prompt to upload one first. Clear `isThinking`.
- **Enter key** in composer sends; **Shift+Enter** inserts a newline.
- **Suggestion chip click** sends that chip's text as a full message (same flow as typing + Enter).
- No loading/error states beyond the above are designed — a real backend integration will need actual upload progress, ingestion failure states, and streaming/error handling for the chat reply, none of which are mocked here.

## State Management
Minimal local state is sufficient to reproduce the prototype; a real implementation should back this with actual API calls:
- `sidebarOpen: boolean`
- `librarySectionOpen: boolean`, `historySectionOpen: boolean`
- `docs: { name: string }[]` — ingested documents
- `isIngesting: boolean`
- `messages: { align, bg, color, text, hasCitation, citation? }[]`
- `history: { title: string }[]` — one entry per distinct chat session started
- `inputValue: string`
- `isThinking: boolean`

In production, `docs`/`history` should be fetched from and persisted to a backend (per-user document library + chat session history), and `sendQuestion` should call a real retrieval-augmented Q&A endpoint rather than a `setTimeout` mock.

## Design Tokens

**Colors**
- Background (page/main): `#FFFFFF`
- Sidebar background: `#FBFBFC`
- Borders/dividers: `#EEEFF3`, `#E7E9F0`, `#E0E2EA`
- Text — primary: `#1A2036`; headings: `#171B2E`; secondary: `#3C4258`; muted: `#6B7280`; faint: `#9297A6`; placeholder/disabled: `#B4B8C4`, `#D6DAE3`, `#C7CBD8`
- Accent (icons, links): `#4338CA`
- User bubble / brand-dark surfaces: `#171B2E`
- Assistant bubble / composer pill background: `#F5F6FA`
- Selection highlight: `#E4E7FF`

**Typography**
- Headings/wordmark: `Manrope`, weights 700–800
- Body/UI: `IBM Plex Sans`, weights 400–600
- Scale used: 26px (H1), 14–14.5px (body/messages), 12.5–13px (list items/labels), 11–12px (meta/captions), 11px uppercase section labels (0.05em letter-spacing)

**Spacing / Radius**
- Sidebar padding `22px 18px`; main content padding `0 28px 28px`; header padding `16px 28px`
- Border radius: 8–9px (buttons, list rows), 14px (message bubbles, composer pill), 999px (pill chips), 7px (small icon tiles)

**Motion**
- `fadeUp`: opacity 0→1 + translateY 6px→0, 0.3–0.4s ease — used on message entry and empty-state entry
- `spin`: 360deg rotation, 0.7s linear infinite — used on the ingesting spinner
- Sidebar width & chevron rotation both transition at 0.15–0.18s ease

## Assets
No external image assets. All icons are inline SVGs (stroke-based, 13–16px, using `currentColor` or explicit hex strokes) — document icon, chevron, chat bubble, upload arrow, plus, kebab/overflow, send arrow. Fonts loaded from Google Fonts (Manrope, IBM Plex Sans).

## Files
- `Internal Documents Assistant.dc.html` — the full interactive prototype (markup + behavior) referenced throughout this document.
