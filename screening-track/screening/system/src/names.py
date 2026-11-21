"""Name normalisation and agreement: POLICY.md principle 8.

Decision half. Pure functions: no file reading. The data half loads
name_variants.json from the run's data folder and passes it in as `Variants`.

Rule 8 in short:
- compare parts ignoring case, accents, punctuation and anything in brackets;
- single letters are initials, not parts; each distinct part counts once;
- placeholders (NA, N/A, TEST, UNKNOWN, XXX, NONE, digits...) are not parts;
- for companies the legal forms in name_variants.json are not parts;
- two parts match when identical, listed together in name_variants.json,
  written together or apart (Abdulsalam ~ Abdul Salam, one match covering
  both), or within an edit budget set by the SHORTER part's length;
- names agree when at least two parts match, or every part of the shorter
  name matches.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable, Optional

# --- thresholds (POLICY.md principle 8); tune here only -----------------------
EXACT_BELOW = 4           # parts shorter than this must be identical
ONE_EDIT_BELOW = 7        # 4..6 letters: 1 edit; 7+ letters: 2 edits
MIN_MATCHED_PARTS = 2     # names agree on >= 2 matched parts...
                          # ...or when every part of the shorter name matches

PLACEHOLDERS = {"na", "n/a", "test", "unknown", "none", "null", "nil", "xxx", "xx", "tbd", "tba", "unk", "noname"}

_BRACKETS_RE = re.compile(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}")
_APOSTROPHE_RE = re.compile(r"['’`´]")
_PUNCT_RE = re.compile(r"[^\w\s]|_")


def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


class Variants:
    """name_variants.json as lookups. A part can sit in several groups
    (joseph and joe are in both the Yusuf and the Joseph group), so matching
    uses the set of groups; `group_of` keeps one id per part for indexing."""

    def __init__(self, data: Optional[dict] = None):
        data = data or {}
        self.groups_of: dict[str, set[int]] = {}
        for i, group in enumerate(data.get("groups") or []):
            for part in group:
                self.groups_of.setdefault(strip_accents(part.lower()), set()).add(i)
        self.group_of: dict[str, int] = {p: min(g) for p, g in self.groups_of.items()}
        self.legal_forms = {strip_accents(x.lower()) for x in data.get("company_legal_forms") or []}

    def same_group(self, a: str, b: str) -> bool:
        return bool(self.groups_of.get(a, set()) & self.groups_of.get(b, set()))


EMPTY_VARIANTS = Variants()


def _as_variants(variants) -> Variants:
    return variants if isinstance(variants, Variants) else Variants(variants)


def normalize_name(name: Optional[str], company: bool = False, variants=EMPTY_VARIANTS) -> list[str]:
    """'Mohámed  (Mo) Al-Hassan' -> ['mohamed', 'al', 'hassan'].

    Drops bracketed text, initials, placeholders and digit tokens, and for a
    company its legal forms. Each distinct part is kept once, in order.
    """
    if not name:
        return []
    variants = _as_variants(variants)
    s = strip_accents(str(name)).lower()
    s = _BRACKETS_RE.sub(" ", s)
    s = _APOSTROPHE_RE.sub("", s)          # O'Brien -> obrien, not o + brien
    s = _PUNCT_RE.sub(" ", s)              # hyphens, dots, commas -> spaces
    parts: list[str] = []
    for p in s.split():
        if len(p) == 1 or p in PLACEHOLDERS or p.isdigit():
            continue
        if company and p in variants.legal_forms:
            continue
        if p not in parts:
            parts.append(p)
    return parts


@lru_cache(maxsize=200_000)
def levenshtein(a: str, b: str) -> int:
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
    if shorter_len < EXACT_BELOW:
        return 0
    return 1 if shorter_len < ONE_EDIT_BELOW else 2


def parts_match(a: str, b: str, variants=EMPTY_VARIANTS) -> bool:
    if a == b or _as_variants(variants).same_group(a, b):
        return True
    budget = edit_budget(min(len(a), len(b)))
    return budget > 0 and abs(len(a) - len(b)) <= budget and levenshtein(a, b) <= budget


def _units(parts: list[str]) -> list[tuple[str, frozenset]]:
    """Each part, plus each adjacent pair written together ('abdul'+'salam')."""
    units = [(p, frozenset([i])) for i, p in enumerate(parts)]
    units += [(parts[i] + parts[i + 1], frozenset([i, i + 1])) for i in range(len(parts) - 1)]
    return units


def _best_matching(pa: list[str], pb: list[str], variants: Variants) -> tuple[int, int, int]:
    """Over every one-to-one matching of units: the most matches, and the most
    parts of A and of B covered. A joined pair is only compared with a single
    part, and counts as one match covering both its parts."""
    ua, ub = _units(pa), _units(pb)
    edges = [(ua[i][1], ub[j][1]) for i in range(len(ua)) for j in range(len(ub))
             if not (len(ua[i][1]) > 1 and len(ub[j][1]) > 1) and parts_match(ua[i][0], ub[j][0], variants)]
    best = [0, 0, 0]

    # ponytail: exhaustive search; names have a handful of parts so it is tiny.
    def search(k: int, used_a: frozenset, used_b: frozenset, count: int):
        best[0] = max(best[0], count)
        best[1] = max(best[1], len(used_a))
        best[2] = max(best[2], len(used_b))
        for n in range(k, len(edges)):
            ca, cb = edges[n]
            if not (ca & used_a or cb & used_b):
                search(n + 1, used_a | ca, used_b | cb, count + 1)

    search(0, frozenset(), frozenset(), 0)
    return best[0], best[1], best[2]


def parts_agree(pa: list[str], pb: list[str], variants=EMPTY_VARIANTS) -> bool:
    """Rule 8 on already-normalised parts."""
    if not pa or not pb:
        return False
    matches, covered_a, covered_b = _best_matching(pa, pb, _as_variants(variants))
    if matches >= MIN_MATCHED_PARTS:
        return True
    shorter = min(len(pa), len(pb))
    return (len(pa) == shorter and covered_a == shorter) or (len(pb) == shorter and covered_b == shorter)


def names_agree(a: Optional[str], b: Optional[str], variants=EMPTY_VARIANTS, company: bool = False) -> bool:
    """True when the two names plausibly refer to the same name (rule 8)."""
    variants = _as_variants(variants)
    return parts_agree(normalize_name(a, company, variants), normalize_name(b, company, variants), variants)


def any_name_agrees(name: Optional[str], others: Iterable[Optional[str]], variants=EMPTY_VARIANTS,
                    company: bool = False) -> Optional[str]:
    """The first of `others` that agrees with `name`, else None."""
    return next((o for o in others if o and names_agree(name, o, variants, company)), None)


def query_key(name: str) -> str:
    """search_results.query: the name's lower-case words in alphabetical order."""
    return " ".join(sorted(re.findall(r"[a-z]+", strip_accents(name or "").lower())))
