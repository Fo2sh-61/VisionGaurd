"""
Egyptian licence plate text handling.

Egyptian plates (2008 system onward) are:
    [ up to 3 Arabic letters ]  [ up to 4 Arabic-Indic digits ]
with a coloured strip on top carrying "مصر / EGYPT".

Two facts about the character set matter for recognition, and public sources
disagree on the details, so BOTH are configurable in config/plate_charset.yaml:

  1. Only a restricted subset of Arabic letters is issued (the excluded ones
     look too much like digits or like each other). Sources differ on the exact
     list, so `LETTERS` below is a superset that is safe to *recognise*.
     `STRICT_LETTERS` is the narrower set most sources agree on and is used
     only for the plausibility score, never to reject a read outright.
  2. Digit zero is reportedly not issued in the number part. We therefore
     down-weight (but do not forbid) a leading/likely-zero read.

Never hard-fail a plate because it breaks a rule — real plates include old
formats, damaged plates and foreign vehicles. Rules only adjust confidence.
"""

from __future__ import annotations

import re
import unicodedata

# --- character sets ----------------------------------------------------------

# Arabic-Indic digits ٠١٢٣٤٥٦٧٨٩  <->  ASCII 0-9
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
EASTERN_AR_DIGITS = "۰۱۲۳۴۵۶۷۸۹"  # Persian variants, sometimes produced by OCR
_DIGIT_MAP = {c: str(i) for i, c in enumerate(AR_DIGITS)}
_DIGIT_MAP.update({c: str(i) for i, c in enumerate(EASTERN_AR_DIGITS)})

# Broad recognition set (what the OCR is allowed to output).
LETTERS = "ابجدرسصطعفقلمنهوىيكحزتثشخذضظغئءؤ"

# Narrow set most sources list as actually issued on Egyptian plates.
# Used for scoring only. Verify against your own site data and edit freely.
STRICT_LETTERS = "ابجدرسصطعفقلمنهوىي"

# Arabic letter -> conventional Latin transliteration used on the newer plates.
# Handy for search boxes, exports and for staff who type on a Latin keyboard.
TRANSLIT = {
    "ا": "A", "ب": "B", "ج": "G", "د": "D", "ر": "R", "س": "S",
    "ص": "C", "ط": "T", "ع": "E", "ف": "F", "ق": "K", "ل": "L",
    "م": "M", "ن": "N", "ه": "H", "و": "W", "ى": "Y", "ي": "Y",
    "ك": "K", "ح": "H", "ز": "Z", "ت": "T", "ث": "S", "ش": "S",
    "خ": "KH", "ذ": "Z", "ض": "D", "ظ": "Z", "غ": "GH",
}

# Glyphs an OCR commonly confuses. Used to generate alternative candidates
# when a plate *almost* matches something already in the database.
#
# Digits are written in ASCII because that is what a *canonical* plate contains
# — normalize() converts ٠-٩ to 0-9 before anything compares strings. The
# Arabic-Indic forms that used to be listed here could never match a canonical
# plate, so every letter/digit pair in this table was silently dead.
#
# The letter/digit pairs are not theoretical: ٤ and ع are the same shape, and
# the character detector genuinely returns both for one glyph (measured on the
# saved crops from this site).
CONFUSIONS = [
    ("ع", "4"), ("ه", "5"), ("و", "6"), ("ا", "1"), ("ل", "1"),
    ("2", "7"), ("3", "2"), ("6", "5"), ("9", "8"),
    ("ب", "ت"), ("ب", "ث"), ("ج", "ح"), ("ج", "خ"),
    ("د", "ذ"), ("ر", "ز"), ("س", "ش"), ("ص", "ض"),
    ("ط", "ظ"), ("ع", "غ"), ("ف", "ق"), ("ى", "ي"),
]

# Letters whose glyph is shared with a digit, and the digit they double as.
# Used by the reader to settle a character by *where it sits on the plate*
# rather than by confidence alone, which is what a plate's fixed layout makes
# possible: on an Egyptian plate the number and the letters occupy separate
# halves, so a "ع" standing among the digits is a ٤.
LETTER_AS_DIGIT = {"ع": "4", "ه": "5", "و": "6", "ا": "1", "ل": "1"}
DIGIT_AS_LETTER = {"4": "ع", "5": "ه", "6": "و", "1": "ا"}

# Letters that may legitimately appear in the *canonical* form.
_ALL_LETTERS = set(LETTERS)

# Arabic diacritics / tatweel / zero-width marks that OCR sometimes emits.
_STRIP_RE = re.compile(r"[ؐ-ًؚ-ٟـٰ​-‏‪-‮]")


# --- normalisation -----------------------------------------------------------

def to_ascii_digits(text: str) -> str:
    """Convert Arabic-Indic and Persian digits to ASCII 0-9."""
    return "".join(_DIGIT_MAP.get(c, c) for c in text)


def to_arabic_digits(text: str) -> str:
    """Convert ASCII digits to Arabic-Indic, for display on an Arabic UI."""
    return "".join(AR_DIGITS[int(c)] if c.isdigit() else c for c in text)


def normalize(raw: str) -> str:
    """
    Reduce any raw OCR string to a canonical comparable key.

    Canonical form is:  "<letters><SPACE><digits>"  with Arabic letters kept as
    Arabic and digits converted to ASCII.  Example: "ب ج د 1234".

    This is what gets stored in the database and compared against, so a plate
    typed by a human and a plate read by a camera always land on the same key.
    """
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", raw)
    s = _STRIP_RE.sub("", s)
    s = to_ascii_digits(s)

    # Unify alef variants and common equivalents so search always matches.
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ي", "ى")):
        s = s.replace(a, b)

    letters = [c for c in s if c in _ALL_LETTERS]
    digits = [c for c in s if c.isdigit()]
    if not letters and not digits:
        return ""
    return f"{''.join(letters)} {''.join(digits)}".strip()


def display(canonical: str, arabic_digits: bool = True) -> str:
    """Format a canonical key for the Arabic dashboard: letters spaced out."""
    if not canonical:
        return ""
    parts = canonical.split(" ", 1)
    letters = " ".join(parts[0]) if parts[0] else ""
    digits = parts[1] if len(parts) > 1 else ""
    if arabic_digits:
        digits = to_arabic_digits(digits)
    return f"{letters}  {digits}".strip()


def transliterate(canonical: str) -> str:
    """Latin form, e.g. 'ب ج د 1234' -> 'B G D 1234'. For exports and search."""
    if not canonical:
        return ""
    letters, _, digits = canonical.partition(" ")
    lat = " ".join(TRANSLIT.get(c, c) for c in letters)
    return f"{lat} {digits}".strip()


# --- plausibility scoring ----------------------------------------------------

def plausibility(canonical: str) -> float:
    """
    0.0-1.0 score for "does this look like a real Egyptian plate".

    Multiplied into the OCR confidence, so an implausible read needs to be
    *very* clean before the system will act on it. Never rejects outright.
    """
    if not canonical:
        return 0.0
    letters, _, digits = canonical.partition(" ")
    score = 1.0

    n_l, n_d = len(letters), len(digits)
    if not (1 <= n_l <= 3):
        score *= 0.45 if n_l else 0.25
    if not (1 <= n_d <= 4):
        score *= 0.45 if n_d else 0.25

    # Letters outside the commonly-issued set are suspicious but possible.
    if letters:
        odd = sum(1 for c in letters if c not in STRICT_LETTERS)
        score *= (0.75 ** odd)

    # Zero is reportedly not issued in the numeric part.
    if "0" in digits:
        score *= 0.8

    return round(max(score, 0.0), 4)


def is_wellformed(canonical: str) -> bool:
    """Strict check, used by the bulk importer to warn on bad rows."""
    letters, _, digits = canonical.partition(" ")
    return 1 <= len(letters) <= 3 and 1 <= len(digits) <= 4


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """
    Levenshtein distance, stopped once it exceeds `cap`.

    Used to decide whether two reads are "the same plate, read twice". The
    dominant OCR errors here are a dropped glyph and a duplicated one, not a
    substitution, so a comparison that only understands substitutions (as
    near_variants does) misses most of them: it cannot tell that "مب 451" and
    "مجب 451" are the same car.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def same_plate(a: str, b: str, max_edits: int = 1) -> bool:
    """
    Are these two canonical plates the same vehicle, allowing for misreads?

    Deliberately asymmetric about what it tolerates: the letter block and the
    digit block are compared separately, so a plate never matches another one
    just because the two halves happen to swap errors. A plate with no digits
    or no letters at all is too thin to match on and is only ever equal to
    itself — otherwise "م 4" would claim to be every plate on the site.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    la, _, da = a.partition(" ")
    lb, _, db = b.partition(" ")
    if not (la and da and lb and db):
        return False
    d = edit_distance(la, lb, max_edits) + edit_distance(da, db, max_edits)
    return d <= max_edits


def richer(a: str, b: str) -> str:
    """
    Of two reads of the same plate, the one more likely to be complete.

    A dropped character is far more common than an invented one, so between
    two otherwise equal candidates the longer read is the better bet — but
    only while it still looks like a plate, which is what plausibility scores.
    """
    if not a:
        return b
    if not b:
        return a
    pa, pb = plausibility(a), plausibility(b)
    if abs(pa - pb) > 0.05:
        return a if pa > pb else b
    return a if len(a) >= len(b) else b


def near_variants(canonical: str, max_out: int = 40) -> list[str]:
    """
    Plates one confusable-character swap away from this one.

    Used for the "did you mean" match: if a read is not in the database but a
    single-glyph neighbour is, the dashboard flags it for the guard to confirm
    instead of silently logging the car as unknown.
    """
    out: set[str] = set()
    chars = list(canonical)
    for i, c in enumerate(chars):
        if c == " ":
            continue
        for a, b in CONFUSIONS:
            other = None
            if c == a:
                other = b
            elif c == b:
                other = a
            if other is None:
                continue
            cand = chars.copy()
            cand[i] = other
            n = normalize("".join(cand))
            if n and n != canonical:
                out.add(n)
            if len(out) >= max_out:
                return sorted(out)
    return sorted(out)
