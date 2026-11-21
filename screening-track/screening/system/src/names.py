"""Name normalisation and agreement, following POLICY.md principle 8.

PROVISIONAL: this file belongs to the decision half. It implements the SOP
wording exactly so the data half can resolve customers by name; replace it
with the teammate's version at join-up if theirs differs.

Rule 8 in short:
- compare parts ignoring case, accents, punctuation and anything in brackets;
- single letters are initials, not parts; each distinct part counts once;
- placeholders (NA, N/A, TEST, UNKNOWN, XXX, NONE, digits...) are not parts;
- for companies the legal forms in name_variants.json are not parts;
- two parts match when identical, in the same variant group, written together
  or apart (Abdulsalam ~ Abdul Salam, counting as one part), or within an edit
  budget set by the SHORTER part's length: <4 letters identical only,
  4-6 letters 1 edit, 7+ letters 2 edits;
- names agree when at least two parts match, or every part of the shorter
  name matches.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Optional

# Thresholds from POLICY.md principle 8. Keep them here so they are easy to see.
EXACT_ONLY_BELOW = 4      # parts shorter than this must be identical
ONE_EDIT_BELOW = 7        # parts of 4..6 letters: 1 edit; 7+: 2 edits
MIN_MATCHED_PARTS = 2     # ...or every part of the shorter name matches

PLACEHOLDERS = {
    "na", "n/a", "n.a", "test", "unknown", "none", "null", "xxx", "xx", "x",
    "nil", "tbd", "tba", "unk", "placeholder", "anonymous", "noname", "nn",
}

_BRACKETS_RE = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_PUNCT_RE = re.compile(r"[^\w\s]|_", re.UNICODE)


class Variants:
    """name_variants.json, loaded once: part -> group id, plus legal forms."""

    def __init__(self, data: Optional[dict] = None):
        data = data or {}
        self.group_of: dict[str, int] = {}
        groups = data.get("groups") or data.get("given_name_groups") or []
        for i, group in enumerate(groups):
            for part in group:
                self.group_of[strip_accents(part.lower())] = i
        self.legal_forms = {strip_accents(x.lower()) for x in data.get("company_legal_forms", [])}

    def same_group(self, a: str, b: str) -> bool:
        ga, gb = self.group_of.get(a), self.group_of.get(b)
        return ga is not None and ga == gb


EMPTY_VARIANTS = Variants()


def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def normalize_name(name: Optional[str], company: bool = False,
                   variants: Variants = EMPTY_VARIANTS) -> list[str]:
    """'Mohámed (Mo) Al-Hassan' -> ['mohamed', 'al', 'hassan'].

    Initials, placeholders and digit tokens are dropped; for companies the
    legal forms are dropped too. Each distinct part is kept once.
    """
    if not name:
        return []
    s = strip_accents(str(name)).lower()
    s = _BRACKETS_RE.sub(" ", s)
    s = s.replace("'", "").replace("’", "")
    s = _PUNCT_RE.sub(" ", s)
    parts = []
    for p in s.split():
        if p in PLACEHOLDERS or p.isdigit() or not p.isalnum():
            continue
        if len(p) == 1:          # an initial, not a part
            continue
        if company and p in variants.legal_forms:
            continue
        if p not in parts:
            parts.append(p)
    return parts


def real_part_count(name: Optional[str], company: bool = False,
                    variants: Variants = EMPTY_VARIANTS) -> int:
    return len(normalize_name(name, company, variants))


@lru_cache(maxsize=200_000)
def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def edit_budget(shorter_len: int) -> int:
    if shorter_len < EXACT_ONLY_BELOW:
        return 0
    if shorter_len < ONE_EDIT_BELOW:
        return 1
    return 2


def parts_match(a: str, b: str, variants: Variants = EMPTY_VARIANTS) -> bool:
    if a == b:
        return True
    if variants.same_group(a, b):
        return True
    budget = edit_budget(min(len(a), len(b)))
    if budget and abs(len(a) - len(b)) <= budget and levenshtein(a, b) <= budget:
        return True
    return False


def _units(parts: list[str]) -> list[tuple[str, frozenset]]:
    """Single parts plus adjacent pairs written together ('abdul'+'salam' ->
    'abdulsalam'). Each unit remembers which part indexes it covers so a part
    is never counted twice."""
    units = [(p, frozenset([i])) for i, p in enumerate(parts)]
    for i in range(len(parts) - 1):
        units.append((parts[i] + parts[i + 1], frozenset([i, i + 1])))
    return units


def matched_part_count(parts_a: list[str], parts_b: list[str],
                       variants: Variants = EMPTY_VARIANTS) -> tuple[int, int]:
    """Maximum number of distinct A-parts that can be matched to distinct
    B-parts (a joined pair counts as one match covering both parts).
    Returns (matches, parts_of_shorter_name_covered)."""
    ua, ub = _units(parts_a), _units(parts_b)
    # A joined pair may only be compared with a single part of the other name.
    pairs = [(i, j) for i, (ta, ca) in enumerate(ua) for j, (tb, cb) in enumerate(ub)
             if not (len(ca) > 1 and len(cb) > 1) and parts_match(ta, tb, variants)]
    best = (0, 0)

    def search(idx, used_a, used_b, count):
        nonlocal best
        covered_a, covered_b = len(used_a), len(used_b)
        shorter_cov = covered_a if len(parts_a) <= len(parts_b) else covered_b
        if (count, shorter_cov) > best:
            best = (count, shorter_cov)
        for k in range(idx, len(pairs)):
            i, j = pairs[k]
            ca, cb = ua[i][1], ub[j][1]
            if ca & used_a or cb & used_b:
                continue
            search(k + 1, used_a | ca, used_b | cb, count + 1)

    search(0, frozenset(), frozenset(), 0)
    return best


def names_agree(a: Optional[str], b: Optional[str], variants: Variants = EMPTY_VARIANTS,
                company: bool = False) -> bool:
    """True when the two names plausibly refer to the same name (rule 8)."""
    pa = normalize_name(a, company, variants)
    pb = normalize_name(b, company, variants)
    if not pa or not pb:
        return False
    matches, shorter_covered = matched_part_count(pa, pb, variants)
    shorter_len = min(len(pa), len(pb))
    return matches >= MIN_MATCHED_PARTS or shorter_covered == shorter_len


def any_name_agrees(name: Optional[str], others: Iterable[Optional[str]],
                    variants: Variants = EMPTY_VARIANTS, company: bool = False) -> Optional[str]:
    """The first of ``others`` that agrees with ``name``, else None."""
    for o in others:
        if o and names_agree(name, o, variants, company):
            return o
    return None


def query_key(name: str) -> str:
    """search_results.query is the name's lowercase words in alphabetical order."""
    words = re.findall(r"[a-z]+", strip_accents(name or "").lower())
    return " ".join(sorted(words))
