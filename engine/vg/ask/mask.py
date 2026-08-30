"""Names and plates out, before anything leaves the site.

**This module is the one that can hurt somebody if it is wrong.** Everything
else in Ask fails visibly — a bad route shows the wrong answer, a dead provider
shows an error. A miss here is silent, and it is a child's name arriving at a
company that may keep it.

So it imports nothing from the engine. It is pure functions over strings and a
dictionary handed in, which means the Arabic corpus can be a data file and the
test can be a loop rather than a fixture.

**What normalisation has to survive.** The same person is written five ways in
one school:

    سارة   ساره   سارا   Sara   Sarah

and a plate is written in two digit systems that mean the same number. So
matching is done on a folded form — alef and hamza collapsed, taa marbuta and
haa collapsed, both digit systems collapsed onto Western, diacritics and
tatweel stripped, case folded. The **original** text is what gets replaced, so
the question keeps its shape; only the comparison is folded.

**The known limit, and it is deliberate** (spec clarification 2, 30 Aug 2026).
A word the site does not recognise — a visitor, a misspelling, somebody never
enrolled — is sent as typed. The alternative was masking every proper noun,
which leaves the model guessing at a sentence of placeholders and routing
badly. `unrecognised()` is what lets Ask say which words those were, so the
limit is visible on screen rather than buried in a document.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: Arabic-Indic and Eastern Arabic-Indic digits onto Western. The vehicle
#: register already collapses both onto one row; a plate must fold the same
#: way here or "ص ب د ٢٣٤" and "ص ب د 234" mask as two different cars.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

#: Letter forms that are the same letter for our purposes.
#:
#: alef with any hamza -> bare alef, because nobody types the hamza reliably.
#: taa marbuta -> haa, because سارة and ساره are one person.
#: alef maqsura -> yaa, same reason.
_LETTERS = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ة": "ه",
    "ى": "ي",
    "ؤ": "و",
    "ئ": "ي",
})

#: Harakat, tanwin, shadda, sukun — and tatweel, which is decoration only.
_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")

#: What counts as a word when looking for unrecognised ones. Arabic block,
#: Latin, and digits; anything else is punctuation.
_WORD = re.compile(r"[\w؀-ۿ]+", re.UNICODE)


def normalise(text: str) -> str:
    """The form two spellings of the same name are compared in.

    Never shown to anybody and never sent anywhere — it exists only so that
    `سارة`, `ساره` and `Sara` can be recognised as the same entry. The text
    that gets substituted is always the original.
    """
    folded = unicodedata.normalize("NFKC", text)
    folded = _MARKS.sub("", folded)
    folded = folded.translate(_LETTERS).translate(_DIGITS)
    # Arabic has no case, but Franco-Arabic and English names do, and
    # casefold beats lower() for the Latin side.
    return " ".join(folded.casefold().split())


#: Arabic letters to their nearest Latin consonant. Long vowels (alef, waw,
#: yaa) and the two letters with no English sound (ain, hamza) become nothing,
#: because that is exactly what a transliteration drops.
_ROMAN = {
    "ا": "", "ب": "b", "ت": "t", "ث": "t", "ج": "g", "ح": "h", "خ": "k",
    "د": "d", "ذ": "z", "ر": "r", "ز": "z", "س": "s", "ش": "s", "ص": "s",
    "ض": "d", "ط": "t", "ظ": "z", "ع": "", "غ": "g", "ف": "f", "ق": "k",
    "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "", "ي": "",
    "ء": "",
}
#: Dropped from the Latin side. `y` and `w` are in here because Arabic treats
#: yaa and waw as long vowels and drops them — keeping them on one side only
#: means "Layla" and "ليلى" never meet, and "Nour" and "نور" never meet.
_VOWELS = frozenset("aeiouyw")

#: Prefix for a placeholder that masks a name but names nobody. Distinct from
#: PERSON_ on purpose: the caller must be able to tell "this is Sara Ahmed"
#: from "this is one of the two people called Sara".
AMBIGUOUS = "PERSON_UNCLEAR_"


def skeleton(text: str) -> str:
    """The consonants of a name, in either script — `سارة` and `Sara` alike.

    This is what makes P12-FR-008's transliteration requirement work: the two
    scripts never agree on vowels, so the comparison drops them entirely.

        سارة  ->  s r h  ->  sr
        ساره  ->  s r h  ->  sr
        Sara  ->  s r    ->  sr
        Sarah ->  s r h  ->  sr

    A trailing `h` goes too, because taa marbuta is written `-a`, `-ah` or
    `-eh` depending on who is typing.

    **Lossy on purpose, and therefore never trusted on its own.** Two
    different names can share a skeleton, and putting the wrong person's name
    back would answer confidently about somebody else — worse than not
    answering. `Dictionary.build` only indexes a skeleton that belongs to
    exactly one enrolled person; a collision means neither is indexed and the
    word is reported as unrecognised instead.
    """
    folded = normalise(text)

    # Latin digraphs are one Arabic letter. "Khaled" is خ-ا-ل-د — four
    # letters, one of which English spells with two. Without this, "khaled"
    # reduced to "khld" and "خالد" to "kld", and Omar Khaled's surname left
    # the site every time somebody typed it in Arabic.
    for pair, single in (("kh", "k"), ("sh", "s"), ("th", "t"),
                         ("gh", "g"), ("ph", "f"), ("ch", "s"),
                         ("dh", "z"), ("aa", "a"), ("ee", "i"), ("oo", "u")):
        folded = folded.replace(pair, single)

    # Collapse doubles FIRST, while the vowels are still there. Order matters
    # and getting it wrong breaks half the school either way:
    #
    #   Hassan  needs the collapse — Arabic writes a doubled consonant once
    #           (حسن), Latin writes it twice, so "hassan" -> "hasan" -> "hsn".
    #   Layla   must NOT be collapsed after vowel removal — its two l's are
    #           separated by a vowel, and collapsing "ll" would leave "l",
    #           one consonant, which is below the floor and would leave the
    #           name unmasked.
    squashed: list[str] = []
    for ch in folded:
        if not squashed or squashed[-1] != ch:
            squashed.append(ch)

    out: list[str] = []
    for ch in squashed:
        if ch in _ROMAN:
            out.append(_ROMAN[ch])
        elif ch.isspace():
            out.append(" ")
        elif ch.isalpha() and ch not in _VOWELS:
            out.append(ch)

    # A trailing h goes too: taa marbuta is written -a, -ah or -eh depending
    # on who is typing, and none of them is more correct than the others.
    return " ".join(w[:-1] if len(w) > 1 and w.endswith("h") else w
                    for w in "".join(out).split())


@dataclass
class Dictionary:
    """Every identifier the site knows, keyed by its folded form.

    Built per question from the store, so somebody enrolled this morning is
    masked this afternoon. It is never cached: a stale dictionary is a name
    that leaves the site.
    """

    #: folded form -> the placeholder it becomes
    entries: dict[str, str] = field(default_factory=dict)
    #: placeholder -> the real value, for putting back locally
    values: dict[str, str] = field(default_factory=dict)
    #: consonant skeleton -> placeholder, for the other script. Only ever
    #: holds skeletons owned by exactly one person.
    skeletons: dict[str, str] = field(default_factory=dict)
    #: Placeholders that stand for a name two or more people share. The name IS
    #: masked — privacy first — but it resolves to nobody, and the caller asks
    #: which person was meant rather than picking one.
    ambiguous: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, people: list[str], plates: list[str]) -> "Dictionary":
        """From names and plate strings. Longest first — see `mask`."""
        d = cls()
        for kind, items in (("PERSON", people), ("PLATE", plates)):
            seen: dict[str, str] = {}
            for raw in items:
                folded = normalise(raw)
                if not folded or folded in d.entries:
                    continue
                # One placeholder per distinct real value, so two questions
                # about the same person send the same token and the model is
                # not told they might differ.
                token = seen.get(folded)
                if token is None:
                    token = f"{kind}_{sum(1 for t in d.values if t.startswith(kind)) + 1}"
                    seen[folded] = token
                    d.values[token] = raw
                d.entries[folded] = token
        # Both, always. A caller who has to remember to add first names is a
        # caller who one day forgets, and the thing they forget is the form
        # guards actually type.
        d.add_person_parts()
        d.add_transliterations()
        return d

    def add_person_parts(self) -> None:
        """Also match a first name on its own.

        A guard types "track Ali", not "track Ali Hassan". Without this the
        full name is masked and the bare first name is not, so the one thing
        people actually type is the one thing that leaks.

        **A shared first name is still masked**, just not to anybody. Two
        children called Sara means "Sara" cannot be resolved to one of them —
        but leaving it unmasked would send a real child's name off-site, which
        is the worse of the two mistakes. It becomes an ambiguous placeholder
        instead: the question is safe to send, and the caller sees the token
        and asks which Sara rather than guessing.
        """
        parts: dict[str, list[str]] = {}
        for folded, token in list(self.entries.items()):
            if not token.startswith("PERSON"):
                continue
            for part in folded.split():
                if len(part) >= 2:
                    parts.setdefault(part, []).append(token)
        for part, tokens in parts.items():
            if part in self.entries:
                continue
            if len(set(tokens)) == 1:
                self.entries[part] = tokens[0]
            else:
                self.entries[part] = self._ambiguous_token(part)

    def _ambiguous_token(self, folded: str) -> str:
        """A placeholder that masks a name but resolves to nobody.

        `values` deliberately maps it to the empty string: `unmask` then puts
        nothing back, and the caller can see the parameter is unresolved. The
        alternative — picking one of the people who share the name — would
        answer confidently about the wrong child.
        """
        token = f"{AMBIGUOUS}{len(self.ambiguous) + 1}"
        self.values[token] = ""
        self.ambiguous.add(token)
        return token

    def add_transliterations(self) -> None:
        """Match the other script, where it is safe to.

        `سارة` and `Sara` share a consonant skeleton, so a school that enrolled
        in one script still masks questions typed in the other — which is most
        questions, because guards type Franco-Arabic on a Latin keyboard and
        Arabic on a phone.

        **Only where exactly one person owns the skeleton.** Two people whose
        names collapse to the same consonants would otherwise be masked to
        whichever was added first, and unmasked to the wrong one — Ask would
        then answer confidently about somebody else. A collision is left
        unmatched, and `unrecognised` reports the word instead.

        Kept in `skeletons`, not `entries`: an entry is matched by a regex
        built from its own characters, and a skeleton is not a spelling — a
        regex for "sr" would match the letters s and r in any word.
        """
        owners: dict[str, set[str]] = {}
        for folded, token in list(self.entries.items()):
            # Plates only ever match exactly. A plate is letters and digits
            # with no vowels to drop, so a skeleton adds nothing — and it
            # takes away a great deal: the single Arabic letters in
            # "ص ب د ٢٣٤" each reduce to one consonant, and "d" then matched
            # the English word "did". A car is not a name.
            if not token.startswith("PERSON"):
                continue
            for word in folded.split():
                key = skeleton(word)
                # A single consonant is not evidence. "علي" and "ليلى" both
                # reduce to "l", and masking Layla as Ali would put one
                # child's name on another child's movements — the exact bug
                # this feature exists to avoid.
                #
                # Two is the floor rather than three, because Arabic first
                # names are frequently two consonants — Sara, Nour, Mona — and
                # a floor that excluded them would exclude most of the school.
                #
                # **Two consonants can still collide**, and no threshold
                # removes that: a question about an unenrolled "Isra" could
                # mask to an enrolled "Sara". Two things contain it. The
                # ambiguity rule below drops any skeleton two enrolled people
                # share, so the common case is caught. And the answer always
                # carries its "understood as" line naming the person it
                # resolved to, so a wrong match is visible on screen rather
                # than silent — which is the whole reason that line is
                # mandatory.
                if len(key.replace(" ", "")) >= 2:
                    owners.setdefault(key, set()).add(token)
        for key, tokens in owners.items():
            if len(tokens) == 1:
                self.skeletons[key] = next(iter(tokens))
            else:
                # Shared by two people. Mask it — to nobody — rather than
                # letting a real name through, and never fall back to a coin
                # toss between two children.
                self.skeletons[key] = self._ambiguous_token(key)


def mask(question: str, dictionary: Dictionary) -> tuple[str, dict[str, str]]:
    """Replace every identifier the site knows with its placeholder.

    Returns the text to send and the tokens used, which is all `unmask` needs.

    **Longest first.** "Ali Hassan" must be replaced before "Ali", or the
    surname is left behind as a bare word and leaves the site on its own.
    """
    used: dict[str, str] = {}
    out = question
    for folded in sorted(dictionary.entries, key=len, reverse=True):
        token = dictionary.entries[folded]
        pattern = _pattern_for(folded)
        if pattern is None:
            continue
        replaced, count = pattern.subn(token, out)
        if count:
            out = replaced
            used[token] = dictionary.values[token]

    # Second pass: the other script. A skeleton is not a spelling, so it
    # cannot be a regex — each remaining word is folded to its consonants and
    # looked up. Word by word, because a skeleton match is weaker evidence and
    # must not be allowed to span a phrase.
    if dictionary.skeletons:
        def _swap(m: re.Match[str]) -> str:
            word = m.group(0)
            if word in used or word.startswith(("PERSON_", "PLATE_")):
                return word
            token = dictionary.skeletons.get(skeleton(word))
            if token is None:
                return word
            used[token] = dictionary.values[token]
            return token

        out = _WORD.sub(_swap, out)

    return out, used


def _pattern_for(folded: str) -> re.Pattern[str] | None:
    """A regex matching any spelling that folds to `folded`.

    Built by folding the *candidate* rather than by listing spellings: each
    character becomes the class of characters that fold to it, so a spelling
    nobody thought of still matches.
    """
    if not folded:
        return None
    pieces: list[str] = []
    for ch in folded:
        variants = sorted(_UNFOLD.get(ch, {ch}))
        escaped = "".join(re.escape(v) for v in variants)
        pieces.append(f"[{escaped}]" if len(variants) > 1 else re.escape(ch))
    # Spaces in a name may be any run of whitespace in the question.
    body = "".join(pieces).replace(re.escape(" "), r"\s+")
    # Whole words only. Without this, "Sara" matched inside "Sarah" and the
    # question went out as "was PERSON_1h here" — a corrupted sentence AND a
    # half-masked name, which is the worst of both. A different spelling is
    # now left alone and reported by `unrecognised` instead, which is the
    # honest behaviour: Ask says the word went, rather than mangling it.
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE | re.UNICODE)


def _build_unfold() -> dict[str, set[str]]:
    """folded character -> every character that folds to it."""
    out: dict[str, set[str]] = {}
    for table in (_LETTERS, _DIGITS):
        for src, dst in table.items():
            # `str.maketrans(a, b)` with two strings yields int -> int, while
            # `str.maketrans({...})` yields int -> str. Handling only the
            # second silently dropped every digit: the plate pattern was built
            # with a literal "234" and never matched "٢٣٤", so a plate written
            # in Arabic-Indic digits left the site untouched. The test caught
            # it; nothing about the code looked wrong.
            char = chr(dst) if isinstance(dst, int) else dst
            if char:
                out.setdefault(char, {char}).add(chr(src))
    return out


_UNFOLD = _build_unfold()


def unmask(params: dict[str, str], used: dict[str, str]) -> dict[str, str]:
    """Put the real values back, locally, after the model has answered.

    A placeholder the model invented is left exactly as it is rather than
    guessed at — the caller sees it is not a real value and refuses.
    """
    out: dict[str, str] = {}
    for key, value in params.items():
        for token, real in used.items():
            value = value.replace(token, real)
        out[key] = value
    return out


def unrecognised(question: str, dictionary: Dictionary) -> list[str]:
    """Words that look like names and that the site does not know.

    These are what will be sent as typed. Naming them is how the accepted
    limit stays visible: the operator is told which words left, rather than
    being left to assume none did.

    Deliberately crude, and deliberately biased towards over-reporting: an
    extra word on screen is a harmless nuisance, a missed one is the whole
    problem. Ordinary question words are filtered out because a list that
    includes "today" and "when" is a list nobody reads, and an unread warning
    protects nobody.
    """
    known = set(dictionary.entries)
    out: list[str] = []
    for word in _WORD.findall(question):
        folded = normalise(word)
        if len(folded) < 3 or folded.isdigit() or folded in known:
            continue
        if folded in _COMMON:
            continue
        # Matched in the other script, so it did not leave.
        if skeleton(word) in dictionary.skeletons:
            continue
        if folded not in {normalise(w) for w in out}:
            out.append(word)
    return out


#: Question words, not names. English, Modern Standard Arabic, Egyptian
#: dialect and the Franco-Arabic spellings of the same, because a guard types
#: "meen" as often as "مين".
#:
#: This list only decides what is *reported*, never what is *masked* — a name
#: that happened to appear here would still be masked normally. Getting an
#: entry wrong costs a missing line on screen, never a leak.
_COMMON_WORDS = """
who what when where which why how many much did was were is are has have had
the and for from with about into over today yesterday now still yet any all
some none person people camera cameras car cars gate gates zone zones day days
week weeks month time times name late early present absent inside outside
come came go went enter entered exit exited leave left seen see show tell find
search look track count check open close last first next this that there here
مين ما ماذا متى فين اين أين ليه لماذا كام كم ازاي كيف هل في من الى إلى على عن
مع بعد قبل النهارده النهاردة اليوم امبارح أمس دلوقتي الان الآن كل اي أي بعض
حد حاجه حاجة شخص ناس واحد واحده واحدة اتنين تلاته الفناء فناء الحوش حوش ملعب صف فصل مدرسه مدرسة كاميرا كاميرات عربية عربيه عربيات بوابة بوابه منطقة
يوم ايام أيام اسبوع أسبوع شهر وقت اسم متاخر متأخر بدري موجود غايب غائب
جه جت راح راحت دخل دخلت خرج خرجت شوف اعرض قولي ابحث دور تتبع عد شيك
امتى إمتى فين ازاي إزاي ايه إيه انهي أنهي عايز عاوز
meen fen ezay leh kam emta enta ana howa heya el al ely elli
"""

#: Normalised at build time, because that is what they are compared against.
#: Comparing a folded word to an unfolded list silently matches nothing — the
#: list looks right, the filter does nothing, and every Arabic question
#: reports its own question words as names.
_COMMON: frozenset[str] = frozenset(
    normalise(w) for w in _COMMON_WORDS.split()
)
