"""Static configuration: env-driven settings, page metadata, icon assets."""

import os

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

# What the USER'S BROWSER can reach, as opposed to API_BASE_URL (what this
# server-side process reaches). Under docker-compose these differ: API_BASE_URL
# is the Docker-internal "http://api:8000" (only resolvable inside the compose
# network), while a browser link (e.g. the Library's "view PDF") needs the
# host-published port instead. Defaults to API_BASE_URL, which is already
# correct for local (non-docker) dev where both are "http://localhost:8000".
PUBLIC_API_BASE_URL = os.environ.get("PUBLIC_API_BASE_URL", API_BASE_URL)

PAGE_TITLE = "Doc Assist"

BRAND_ICON_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none">'
    '<path d="M6 2h9l5 5v15a1 1 0 01-1 1H6a1 1 0 01-1-1V3a1 1 0 011-1z" '
    'stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>'
)

DOC_ICON_SVG = (
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" style="flex-shrink:0;">'
    '<path d="M6 2h9l5 5v15a1 1 0 01-1 1H6a1 1 0 01-1-1V3a1 1 0 011-1z" '
    'stroke="#B4B8C4" stroke-width="2"/></svg>'
)

SUGGESTIONS = [
    "Summarize the onboarding guide",
    "What's the PTO policy?",
    "List required SOP approvals",
]
