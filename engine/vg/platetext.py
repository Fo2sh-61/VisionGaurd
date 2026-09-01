"""Egyptian number plates as text: one canonical form, however they arrive.

Ported from `vendor/gate-anpr/anpr/plate_text.py`. Pure functions, no
model, no camera, no database — which is why it lives beside `clock.py` rather
than under `infer/`, and why its tests run in milliseconds.

**The problem this solves.** An Egyptian plate is Arabic letters plus
Indic digits. The same car can reach this system three ways:

    a camera         ب ج د ١٢٣٤      Indic digits, whatever the model emitted
    a typed form     ب ج د 1234      whichever keyboard the office had
    a spreadsheet    ب ج د ١٢٣٤      whatever the previous system exported

Those must be **one** row. `normalize` is what makes that true, and the
`UNIQUE` constraint on `vehicle.plate` is what makes it a guarantee rather
than an intention. Get this wrong and a school ends up with three records per
car and an attendance-style mess in the gate log.

**Two letter sets, on purpose.** `LETTERS` is broad — anything the reader is
allowed to output, because refusing a reading is worse than recording an odd
one. `STRICT_LETTERS` is the narrower set public sources agree is actually
issued, and is used **only for confidence weighting**. Published sources
disagree about the exact list, so this is deliberately a nudge and never a
rejection. Widen either after seeing real plates from the site.

**The confusion table is measured, not theoretical.** `ع` and `٤` are the same
shape; the character model genuinely returns both for one glyph. Letting those
readings split a vote is how a correct plate loses to two wrong ones, so
`same_plate` merges them instead.

Digits are stored as ASCII throughout, because `normalize` converts before
anything compares. Arabic digits appear only in `display`, on the way out.
"""

from __future__ import annotations

import re
import unicodedata

# --- character sets --------------------------------------------------------

#: Arabic-Indic digits, and the Persian variants an OCR sometimes emits.
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
EASTERN_AR_DIGITS = "۰۱۲۳۴۵۶۷۸۹"

_DIGIT_MAP = {c: str(i) for i, c in enumerate(AR_DIGITS)}
_DIGIT_MAP.update({c: str(i) for i, c in enumerate(EASTERN_AR_DIGITS)})

#: What the reader is allowed to output. Broad: never reject a reading.
LETTERS = "ابجدرسصطعفقلمنهوىيكحزتثشخذضظغئءؤ"

#: The narrower set most sources list as actually issued. **Scoring only.**
STRICT_LETTERS = "ابجدرسصطعفقلمنهوىي"

#: Latin transliteration, as printed on the newer plates. For exports and for
#: staff searching from a Latin keyboard.
TRANSLIT = {
    "ا": "A", "ب": "B", "ج": "G", "د": "D", "ر": "R", "س": "S",
    "ص": "C", "ط": "T", "ع": "E", "ف": "F", "ق": "K", "ل": "L",
    "م": "M", "ن": "N", "ه": "H", "و": "W", "ى": "Y", "ي": "Y",
    "ك": "K", "ح": "H", "ز": "Z", "ت": "T", "ث": "S", "ش": "S",
    "خ": "KH", "ذ": "Z", "ض": "D", "ظ": "Z", "غ": "GH",
}

#: Glyph pairs the reader actually confuses, measured on saved crops.
#: Digits are ASCII because a canonical plate contains no Indic digits.
CONFUSIONS = [
    ("ع", "4"), ("ه", "5"), ("و", "6"), ("ا", "1"), ("ل", "1"),
    ("2", "7"), ("3", "2"), ("6", "5"), ("9", "8"),
    ("ب", "ت"), ("ب", "ث"), ("ج", "ح"), ("ج", "خ"),
    ("د", "ذ"), ("ر", "ز"), ("س", "ش"), ("ص", "ض"),
    ("ط", "ظ"), ("ع", "غ"), ("ف", "ق"), ("ى", "ي"),
]

#: Letters whose glyph doubles as a digit, and which digit.
#:
#: An Egyptian plate puts letters and numbers in separate halves, so **where a
#: glyph sits settles what it is** far more reliably than confidence does. A
#: `ع` standing among the digits is a ٤.
LETTER_AS_DIGIT = {"ع": "4", "ه": "5", "و": "6", "ا": "1", "ل": "1"}
DIGIT_AS_LETTER = {"4": "ع", "5": "ه", "6": "و", "1": "ا"}

_ALL_LETTERS = set(LETTERS)

#: Diacritics, tatweel and zero-width marks an OCR sometimes emits.
_STRIP_RE = re.compile(r"[ؐ-ًؚ-ٟـٰ​-‏‪-‮]")


# --- normalisation ---------------------------------------------------------

def to_ascii_digits(text: str) -> str:
    """Arabic-Indic and Persian digits to ASCII 0-9."""
    return "".join(_DIGIT_MAP.get(c, c) for c in text)


def to_arabic_digits(text: str) -> str:
    """ASCII digits to Arabic-Indic, for display."""
    return "".join(AR_DIGITS[int(c)] if c.isdigit() else c for c in text)


def normalize(raw: str) -> str:
    """Any raw string to the one canonical key: ``"<letters> <digits>"``.

    Letters stay Arabic, digits become ASCII — `"ب ج د 1234"`. This is what is
    stored and compared, so a plate typed by a person and one read by a camera
    land on the same key or the register grows a duplicate per car.

    Alef variants and a few equivalents are unified (`أإآ`→`ا`, `ة`→`ه`,
    `ي`→`ى`) because a human and a model will not agree on which they meant,
    and a search that distinguishes them finds nothing.
    """
    if not raw:
        return ""
    s = unicodedata.normalize("NFKC", raw)
    s = _STRIP_RE.sub("", s)
    s = to_ascii_digits(s)

    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ي", "ى")):
        s = s.replace(a, b)

    letters = [c for c in s if c in _ALL_LETTERS]
    digits = [c for c in s if c.isdigit()]
    if not letters and not digits:
        return ""
    return f"{''.join(letters)} {''.join(digits)}".strip()


def display(canonical: str, arabic_digits: bool = True) -> str:
    """The canonical key as it should be shown — spaced letters, Indic digits.

    The console renders this right-to-left, as it appears on the car.
    """
    if not canonical:
        return ""
    parts = canonical.split(" ", 1)
    letters = " ".join(parts[0]) if parts[0] else ""
    digits = parts[1] if len(parts) > 1 else ""
    if arabic_digits:
        digits = to_arabic_digits(digits)
    return f"{letters}  {digits}".strip()


def transliterate(canonical: str) -> str:
    """Latin form: `"ب ج د 1234"` → `"B G D 1234"`. Exports and search."""
    if not canonical:
        return ""
    letters, _, digits = canonical.partition(" ")
    latin = " ".join(TRANSLIT.get(c, c) for c in letters)
    return f"{latin} {digits}".strip()


# --- plausibility ----------------------------------------------------------

def plausibility(canonical: str) -> float:
    """0..1 — does this look like a real Egyptian plate?

    Multiplied into the reading confidence when frames vote, so an implausible
    reading has to be very clean before the system will act on it. **Never
    rejects.** A weird plate that is really on a car must still be recordable;
    it just needs more agreement first.
    """
    if not canonical:
        return 0.0
    letters, _, digits = canonical.partition(" ")
    score = 1.0

    n_letters, n_digits = len(letters), len(digits)
    if not 1 <= n_letters <= 3:
        score *= 0.45 if n_letters else 0.25
    if not 1 <= n_digits <= 4:
        score *= 0.45 if n_digits else 0.25

    if letters:
        odd = sum(1 for c in letters if c not in STRICT_LETTERS)
        score *= 0.75 ** odd

    # Zero is reportedly not issued in the numeric part.
    if "0" in digits:
        score *= 0.8

    return round(max(score, 0.0), 4)


def is_wellformed(canonical: str) -> bool:
    """Strict shape check. Used by the importer to flag a suspect row."""
    letters, _, digits = canonical.partition(" ")
    return 1 <= len(letters) <= 3 and 1 <= len(digits) <= 4


# --- comparison ------------------------------------------------------------

def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Levenshtein, abandoned once it passes `cap`.

    Full Levenshtein rather than substitutions-only because the dominant
    reader errors here are a **dropped** glyph and a **duplicated** one, not a
    swap. A comparison that only understands substitution cannot tell that
    `"مب 451"` and `"مجب 451"` are the same car.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def same_plate(a: str, b: str, max_edits: int = 1) -> bool:
    """Two readings of one car, allowing for a misread?

    **The two halves are compared separately**, so a plate never matches
    another because its letter error and its digit error happen to cancel.

    A reading missing letters *or* digits entirely is too thin to match on and
    is only equal to itself — otherwise `"م 4"` would claim to be every car on
    the site, which is how one bad frame poisons a whole register.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    letters_a, _, digits_a = a.partition(" ")
    letters_b, _, digits_b = b.partition(" ")
    if not (letters_a and digits_a and letters_b and digits_b):
        return False
    distance = (edit_distance(letters_a, letters_b, max_edits)
                + edit_distance(digits_a, digits_b, max_edits))
    return distance <= max_edits


def richer(a: str, b: str) -> str:
    """Of two readings of the same plate, the one more likely to be complete.

    A dropped character is far more common than an invented one, so the longer
    reading is the better bet — but only while it still looks like a plate,
    which is what plausibility decides. Used when merging votes so the winning
    text is the fullest of the readings that agreed.
    """
    if not a:
        return b
    if not b:
        return a
    plaus_a, plaus_b = plausibility(a), plausibility(b)
    if abs(plaus_a - plaus_b) > 0.05:
        return a if plaus_a > plaus_b else b
    return a if len(a) >= len(b) else b
