"""Hardcoded, deterministic leave-entitlement facts for the GOAL-ORIENTED
ADVISORY section of the system prompt (see retrieval/prompt.py) -- computed
here in code, once, rather than asked of the generation model on every call.

Sourced verbatim from Calfus India Employee Handbook v4, section 5.3 "Leave
Policy", p.13.

This module exists because the model was unreliable at deriving the
guaranteed general-purpose ceiling itself: several rounds of increasingly
explicit prompt instructions asking it to classify each bucket
purpose-matched/unconditional and sum the passing ones still intermittently
misclassified Birthday Leave (purpose-matched -- its policy text states only
a day count, no required circumstance) as purpose-gated, purely because of
its name, landing on 21 days instead of the correct 22 -- see git history for
several rounds of prompt wording that tried and failed to fix this reliably
through instructions alone. Moving the one number that matters most out of
the model's own arithmetic and into code removes that failure mode entirely.

NOT config_store-editable, unlike SYSTEM_PROMPT -- these are hardcoded facts
about a specific, named policy document, not a generation-behavior knob. If
the underlying policy changes, this file changes with it (and so does the
PDF it's sourced from).
"""

import re
from dataclasses import dataclass
from typing import NamedTuple

_SOURCE_FILE = "Calfus India Employee Handbook v4.pdf"
_SOURCE_PAGE = 13
_CITATION = f"{_SOURCE_FILE}, Section 5.3 Leave Policy, p.{_SOURCE_PAGE}"


@dataclass(frozen=True)
class LeaveBucket:
    key: str  # canonical snake_case id, matching eval/golden_questions.yaml's bucket-name convention
    name: str
    entitlement_text: str  # human-readable, verbatim-style, e.g. "21 days"
    days: int | None  # None where there's no fixed numeric cap (Maternity, LOP/LWP)
    purpose: str | None  # None = unconditional/general-purpose; else the required stated circumstance
    conditional: bool  # True = discretionary/available-but-conditional (LOP/LWP) -- never summed, never "purpose-matched" for ceiling purposes regardless of `purpose`
    citation: str


# Every leave bucket in section 5.3's table, plus the LOP/LWP fallback
# described in prose immediately after it (not part of the table itself, see
# retrieval/prompt.py's docstring history for the earlier read-through of
# this page). Order matches the source table.
LEAVE_BUCKETS: tuple[LeaveBucket, ...] = (
    LeaveBucket("earned_leave", "Earned Leave", "21 days", 21, None, False, _CITATION),
    LeaveBucket("sick_leave", "Sick Leave", "7 days", 7, "illness", False, _CITATION),
    LeaveBucket("marriage_leave", "Marriage Leave", "2 days", 2, "the employee's own marriage", False, _CITATION),
    LeaveBucket("bereavement_leave", "Bereavement Leave", "2 days", 2, "a death/bereavement", False, _CITATION),
    LeaveBucket("paternity_leave", "Paternity Leave", "10 days", 10, "the birth of the employee's child", False, _CITATION),
    LeaveBucket("birthday_leave", "Birthday Leave", "1 day", 1, None, False, _CITATION),
    LeaveBucket(
        "maternity_leave",
        "Maternity Leave",
        "up to 180 days (as per act)",
        None,
        "the employee's own childbirth",
        False,
        _CITATION,
    ),
    LeaveBucket("lop_lwp", "LOP/LWP", "no fixed limit", None, None, True, _CITATION),
)

LEAVE_BUCKETS_BY_KEY: dict[str, LeaveBucket] = {b.key: b for b in LEAVE_BUCKETS}


def is_ceiling_bucket(bucket_key: str) -> bool:
    """True if `bucket_key` is one of the buckets compute_leave_ceiling()
    sums (purpose-unrestricted, not conditional) -- e.g. earned_leave,
    birthday_leave. Used by retrieval/qa.answer_question to decide whether a
    detect_stated_balance() match should replace the generic ceiling fact
    (bucket contributes to it) or leave it untouched (bucket is irrelevant to
    the general-purpose ceiling, e.g. a stated Sick Leave balance).
    """
    bucket = LEAVE_BUCKETS_BY_KEY.get(bucket_key)
    return bucket is not None and bucket.purpose is None and not bucket.conditional


class LeaveCeiling(NamedTuple):
    days: int
    contributing_buckets: tuple[LeaveBucket, ...]
    fact_string: str


def compute_leave_ceiling() -> LeaveCeiling:
    """The guaranteed general-purpose leave ceiling: the sum of every bucket
    that is both purpose-unrestricted (purpose is None) and not conditional/
    discretionary (conditional is False). Today that's Earned Leave (21) +
    Birthday Leave (1) = 22 -- see this module's docstring for why that
    specific total is hardcoded here instead of left to the model.
    """
    contributing = tuple(
        b for b in LEAVE_BUCKETS if b.purpose is None and not b.conditional and b.days is not None
    )
    total = sum(b.days for b in contributing)

    ceiling_parts = " + ".join(
        f"{b.name} ({b.entitlement_text}) [cite p.{_SOURCE_PAGE}]" for b in contributing
    )
    gated = [b for b in LEAVE_BUCKETS if b.purpose is not None]
    gated_names = ", ".join(b.name.replace(" Leave", "") for b in gated)
    conditional_buckets = [b for b in LEAVE_BUCKETS if b.conditional]

    conditional_sentences = " ".join(
        f"{b.name} has no fixed limit and is granted only if leave balance is exhausted and "
        "'the situation warrants it' -- this is discretionary, not automatic, and has no "
        "named approver in policy."
        for b in conditional_buckets
    )

    fact_string = (
        f"SYSTEM-VERIFIED FACT (do not recompute, use exactly): the guaranteed general-purpose "
        f"leave ceiling -- usable for any reason, no eligibility condition -- is {total} days, "
        f"composed of {ceiling_parts}. All other leave types "
        f"({gated_names}) require a specific stated circumstance and must NOT be included in a "
        f"general days-off total. {conditional_sentences}"
    )

    return LeaveCeiling(days=total, contributing_buckets=contributing, fact_string=fact_string)


def context_has_leave_policy(docs) -> bool:
    """True if any retrieved chunk in `docs` is from this policy's page --
    NOT sufficient on its own to inject the ceiling fact; see
    is_leave_planning_question below for the other half of that check.
    Deliberately simple (source + page match, no query classification) --
    there's no goal-oriented-advisory query detector in this codebase yet;
    this is the simplest thing that works, per the task that introduced it.
    """
    return any(
        doc.metadata.get("source") == _SOURCE_FILE and doc.metadata.get("page") == _SOURCE_PAGE
        for doc in docs
    )


# A bare day-count ("12 days", "40 days", "15 earned leave days") is what
# distinguishes an actual leave-day-planning/advisory question (see
# prompt.py's <goal_oriented_advisory>) from one that merely happens to
# retrieve a Leave Policy chunk because it's topically adjacent -- e.g. a
# Work From Home policy question retrieving the same handbook page's
# neighboring Leave Policy section (5.3) too, purely because the two
# sections share a page (5.4 WFH, same page as 5.3 Leave). Calibrated
# against this codebase's three real advisory eval questions -- "take 12
# days off", "take 40 days off", "20 days off, ... 15 earned leave days
# left" -- all three state an explicit day count; a plain policy-lookup
# question, even one that's topically near leave (like the WFH case),
# doesn't.
_DAY_COUNT_RE = re.compile(r"\b\d+\s*days?\b", re.IGNORECASE)


def is_leave_planning_question(question: str) -> bool:
    """True if `question` itself states a day count -- the other half of
    the ceiling-fact injection trigger (see context_has_leave_policy).
    Deliberately narrow, same reasoning as detect_stated_balance below --
    the failure mode is NOT injecting the fact (falls through to a plain
    grounded answer, which is what a non-planning question needs anyway),
    never a false positive that hijacks an unrelated answer into advisory
    mode and away from citing what was actually asked about.
    """
    return bool(_DAY_COUNT_RE.search(question or ""))


# Phrase -> canonical bucket key, for detect_stated_balance() below. Deliberately
# only the phrasings an employee would actually type, not every LeaveBucket.name
# variant -- e.g. no "LOP/LWP" (the slash form is this module's internal display
# name, not how someone writes a sentence).
_BUCKET_ALIASES: dict[str, str] = {
    "earned leave": "earned_leave",
    "sick leave": "sick_leave",
    "marriage leave": "marriage_leave",
    "bereavement leave": "bereavement_leave",
    "paternity leave": "paternity_leave",
    "birthday leave": "birthday_leave",
    "maternity leave": "maternity_leave",
    "loss of pay": "lop_lwp",
    "leave without pay": "lop_lwp",
    "lop": "lop_lwp",
    "lwp": "lop_lwp",
}

# Longest alias first so "leave without pay" matches before a hypothetical
# shorter substring alias would -- alternation is first-match, not longest-match.
_ALIAS_PATTERN = "|".join(re.escape(a) for a in sorted(_BUCKET_ALIASES, key=len, reverse=True))

# "15 earned leave days left", "20 sick leave days remaining"
_AMOUNT_THEN_BUCKET_RE = re.compile(
    rf"(\d+)\s+\b({_ALIAS_PATTERN})\b\s+days?\s+(?:left|remaining)\b", re.IGNORECASE
)

# "earned leave balance is 15", "my LOP balance of 3"
_BUCKET_BALANCE_RE = re.compile(
    rf"\b({_ALIAS_PATTERN})\b\s+balance\s+(?:is|of)\s+(\d+)", re.IGNORECASE
)

# Bucket-less fallback: "I only have 15 days left", "I have 15 days remaining".
# Deliberately defaults to Earned Leave rather than returning no match --
# Earned Leave is the only truly general-purpose bucket in this policy (see
# LEAVE_BUCKETS), so a bare day count with no bucket named is, in every
# scenario this was built against, about Earned Leave specifically. This is
# the one place this function makes an assumption rather than a literal
# match; everything else here is pattern detection, not inference.
_BARE_AMOUNT_RE = re.compile(
    r"\bi\s+(?:only\s+)?have\s+(\d+)\s+days?\s+(?:left|remaining)\b", re.IGNORECASE
)


def detect_stated_balance(question: str) -> dict | None:
    """Simple, conservative pattern match for the employee explicitly
    stating their OWN remaining balance for a leave bucket, right in the
    question text -- e.g. "I only have 15 earned leave days left", "my
    earned leave balance is 15". Returns {"bucket": <canonical key>,
    "stated_amount": <int>} or None if nothing matched.

    Deliberately narrow: this is pattern detection, not general NLU. Unusual
    phrasing legitimately won't match, and that's the intended failure mode
    (falls back to the generic SYSTEM-VERIFIED FACT ceiling in
    retrieval/qa.answer_question) rather than guessing wrong from a maybe-
    balance-statement. See _BARE_AMOUNT_RE's comment for the one place this
    goes beyond a literal pattern match.
    """
    q = question or ""

    m = _AMOUNT_THEN_BUCKET_RE.search(q)
    if m:
        amount, alias = m.group(1), m.group(2)
        return {"bucket": _BUCKET_ALIASES[alias.lower()], "stated_amount": int(amount)}

    m = _BUCKET_BALANCE_RE.search(q)
    if m:
        alias, amount = m.group(1), m.group(2)
        return {"bucket": _BUCKET_ALIASES[alias.lower()], "stated_amount": int(amount)}

    m = _BARE_AMOUNT_RE.search(q)
    if m:
        return {"bucket": "earned_leave", "stated_amount": int(m.group(1))}

    return None


def build_stated_balance_fact(bucket_key: str, stated_amount: int) -> str | None:
    """The scenario-specific replacement for compute_leave_ceiling().fact_string
    when the employee has stated their own remaining balance for a bucket (see
    detect_stated_balance) -- the model then only ever sees ONE number for
    that bucket, never both the generic annual default and the stated
    balance side by side. Returns None if `bucket_key` isn't a recognized
    bucket (defensive; detect_stated_balance only ever returns known keys).

    Also carries the same LOP/LWP gating-condition sentence
    compute_leave_ceiling().fact_string includes -- an earlier version of
    this function omitted it entirely (it only overrode the stated bucket),
    so an answer that needed to name LOP/LWP as the shortfall option had no
    gating language available in context to draw from and fell back to
    vague, non-compliant phrasing ("if necessary") instead of the real
    condition. This sentence is conditional in the prose itself ("if this
    scenario's total leave need exceeds what's available") rather than only
    injected when the goal is known to exceed the bucket, since this
    function doesn't know the requested amount -- retrieval/qa.py only
    knows the employee's stated balance, not what they're asking for.

    No inline "[cite ...]" placeholder here (unlike an earlier version) --
    this block already gets a real numbered "[n]" citation label from
    format_context() when qa.answer_question() appends it to `docs`, the
    same as every other retrieved chunk. A second, non-numeric bracket
    marker inside the text itself doesn't match that convention and risked
    reading as competing/confusing guidance about how to cite this block.
    """
    bucket = LEAVE_BUCKETS_BY_KEY.get(bucket_key)
    if bucket is None:
        return None

    return (
        f"SYSTEM-VERIFIED FACT: the employee has stated a remaining {bucket.name} balance of "
        f"{stated_amount} days, which overrides the generic annual entitlement for this "
        f"conversation. Use {stated_amount}, not {bucket.entitlement_text}, as {bucket.name}'s "
        f"contribution to any total. Do not mention the generic annual ceiling or any bucket "
        f"the employee did not ask about. If this scenario's total leave need exceeds what's "
        f"available, note that Loss of Pay (LOP) or Leave Without Pay (LWP) may be granted at "
        f"the discretion of management when the leave balance is exhausted and the situation "
        f"warrants it -- this is discretionary, not automatic, not guaranteed."
    )
