"""
Parsers for dirty CSV values. Each returns (parsed_or_None, error_or_None) so
the importer can store the row regardless and record *why* a field is NULL.
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

_REF_RE = re.compile(r"(?:REC)?-?(\d+)")
_MONEY_RE = re.compile(r"-?\d+(?:\.\d+)?")
_LABEL_CATEGORY_RE = re.compile(r"Entry for (CAT-\d+)", re.I)


def normalize_ref(raw):
    """Canonicalise a System B record_ref to System A's "REC-<digits>" form.

    Seen in the data: "REC-1034", "rec1034", " REC - 1070 ", "1112".
    Anything else (e.g. "INV-9", "abc", "") returns None and is treated as an
    unresolvable reference, never guessed at.
    """
    if raw is None:
        return None
    compact = re.sub(r"\s+", "", raw).upper()
    m = _REF_RE.fullmatch(compact)
    return f"REC-{m.group(1)}" if m else None


def parse_money(raw):
    """Parse a monetary amount into a Decimal.

    Commas are treated as digit-group separators wherever they fall, so both
    western ("125,400.00") and Indian lakh grouping ("1,25,400.00") parse to
    125400.00. "." is the only decimal separator accepted: a European
    "1.234,56" is rejected as unparseable rather than silently misread.
    Decimal, never float, so a 0.01 difference is a real difference.
    """
    if raw is None or raw.strip() == "":
        return None, "blank"
    cleaned = raw.strip().replace(",", "")
    if not _MONEY_RE.fullmatch(cleaned):
        return None, f"not a number: {raw!r}"
    try:
        return Decimal(cleaned), None
    except InvalidOperation:  # pragma: no cover - the regex already guards this
        return None, f"not a number: {raw!r}"


def parse_date(raw):
    """ISO dates only (every date in both files is ISO). Others -> None + error."""
    if raw is None or raw.strip() == "":
        return None, "blank"
    try:
        return date.fromisoformat(raw.strip()), None
    except ValueError:
        return None, f"not an ISO date: {raw!r}"


def category_from_label(label):
    """System B has no category column; its label sometimes embeds one
    ("Entry for CAT-02"). Returns None when the label doesn't say (e.g.
    "Entry part 2 of 2"), in which case no category claim is made."""
    m = _LABEL_CATEGORY_RE.fullmatch((label or "").strip())
    return m.group(1).upper() if m else None
