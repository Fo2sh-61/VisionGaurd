"""The enrolled face gallery.

SQLite plus a NumPy matrix held in memory. A linear scan over a few thousand
people is well under a millisecond, so an ANN index would be complexity without
benefit until the roll is very much larger.

Three rules here exist because getting them wrong misidentifies a child.

**Several embeddings per person.** One photo is a single lighting condition and
a single angle. Matching takes the best score across all of a person's vectors,
so enrolling four or five varied captures is worth far more than one good one.

**A margin, not just a threshold.** If the best match and the runner-up are
close together, the system does not know which it is and must say so. A
confident wrong name on an attendance register is worse than an absence — one
gets corrected, the other gets believed.

**The margin does nothing while only one person is enrolled**, and that is
worth knowing rather than discovering. `match()` guards it with
`len(ranked) > 1`, because with a gallery of one there is no runner-up to be
close to. A one-person gallery therefore runs on the threshold alone — which
is exactly how a stranger came to be named at the old 0.45 bar. The gate
switches itself back on at the second enrolment; nothing needs changing for
that to happen. Until then, the threshold is carrying both jobs, and
`config.py` explains what it was measured against.

**Model is recorded with every vector.** SFace and ArcFace embeddings are not
comparable. Comparing them silently produces plausible-looking nonsense, so a
mismatch is refused outright.

Biometric data of minors is regulated separately from ordinary personal data in
most jurisdictions. This file stores vectors and never images, which limits the
blast radius but does not by itself settle the legal position.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from vg import db

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS person (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    type         TEXT NOT NULL DEFAULT 'Student',
    grp          TEXT,
    detail       TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS face_embedding (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id    TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
    model        TEXT NOT NULL,
    dimensions   INTEGER NOT NULL,
    vector       BLOB NOT NULL,
    quality      REAL,
    source       TEXT,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_embedding_person ON face_embedding(person_id);
CREATE INDEX IF NOT EXISTS idx_embedding_model  ON face_embedding(model);
"""


def _parse(value: str | None) -> datetime | None:
    """An ISO string from SQLite back to an aware datetime.

    Rows written before the column carried an offset are read as UTC, which is
    what they were: everything in this file stamps `datetime.now(timezone.utc)`.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    type: str = "Student"
    group: str | None = None
    detail: str | None = None
    photo_count: int = 0
    #: When this person was enrolled. Written on every enrolment since the
    #: table existed; it simply never travelled outward until the People page
    #: needed to say when somebody was added.
    created_at: datetime | None = None

    @property
    def photo_on_file(self) -> bool:
        """Drives the UI's honest line that someone with no photo cannot be
        recognised. It is a statement about capability, not paperwork."""
        return self.photo_count > 0


@dataclass(frozen=True)
class Match:
    """The result of asking "who is this?".

    `person` is None when the gallery declines to guess — either nothing scored
    above the threshold, or the top two were too close to separate.
    """

    person: Person | None
    score: float
    runner_up: float = 0.0
    reason: str = ""

    @property
    def matched(self) -> bool:
        return self.person is not None

    @property
    def margin(self) -> float:
        return self.score - self.runner_up


class FaceGallery:
    """Enrolled faces, and matching against them."""

    # Minimum gap between the best and second-best person. Below this the two
    # candidates are not separable and naming either one is a guess.
    DEFAULT_MARGIN = 0.06

    def __init__(
        self,
        database: Path | str,
        model: str,
        threshold: float,
        margin: float = DEFAULT_MARGIN,
    ) -> None:
        self.path = Path(database)
        self.model = model
        self.threshold = threshold
        self.margin = margin

        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

        # In-memory index, rebuilt on change.
        self._matrix: np.ndarray = np.zeros((0, 0), dtype=np.float32)
        self._owners: list[str] = []
        self._people: dict[str, Person] = {}
        self.reload()

    # -- enrolment ----------------------------------------------------------

    def add_person(
        self,
        person_id: str,
        name: str,
        type: str = "Student",
        group: str | None = None,
        detail: str | None = None,
        created_at: datetime | None = None,
    ) -> Person:
        """`created_at` is for tests and imports that must say when somebody
        was enrolled; a real enrolment leaves it out and gets now."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO person (id, name, type, grp, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, "
                "type=excluded.type, grp=excluded.grp, detail=excluded.detail",
                (person_id, name, type, group, detail,
                 (created_at or datetime.now(timezone.utc)).isoformat()),
            )
            self._conn.commit()
        self.reload()
        return self._people[person_id]

    def add_embedding(
        self,
        person_id: str,
        vector: np.ndarray,
        model: str,
        quality: float | None = None,
        source: str | None = None,
    ) -> None:
        """Store one face vector.

        Refuses a model mismatch rather than storing something that will later
        be compared against incomparable vectors and produce confident nonsense.
        """
        if model != self.model:
            raise ValueError(
                f"gallery holds {self.model!r} embeddings; refusing to store "
                f"{model!r}. Mixing face models produces plausible-looking "
                f"nonsense. Re-enrol the gallery to switch models."
            )

        vector = np.asarray(vector, dtype=np.float32).flatten()
        with self._lock:
            self._conn.execute(
                "INSERT INTO face_embedding "
                "(person_id, model, dimensions, vector, quality, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (person_id, model, len(vector), vector.tobytes(), quality, source,
                 datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()
        self.reload()

    def remove_person(self, person_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM person WHERE id = ?", (person_id,))
            self._conn.commit()
        self.reload()
        return cursor.rowcount > 0

    # -- matching -----------------------------------------------------------

    def match(self, embedding: np.ndarray, model: str | None = None) -> Match:
        """Who is this? Or an honest refusal to say.

        Scores every enrolled vector, takes each person's best, then applies
        threshold and margin. Both gates have to pass.
        """
        if model is not None and model != self.model:
            return Match(None, 0.0, reason=f"gallery holds {self.model}, got {model}")

        with self._lock:
            matrix, owners = self._matrix, list(self._owners)

        if matrix.size == 0:
            return Match(None, 0.0, reason="gallery is empty")

        query = np.asarray(embedding, dtype=np.float32).flatten()
        if query.shape[0] != matrix.shape[1]:
            return Match(None, 0.0, reason="embedding size does not match gallery")

        # Vectors are L2-normalised on the way in, so a dot product is cosine.
        scores = matrix @ query

        best_per_person: dict[str, float] = {}
        for owner, score in zip(owners, scores):
            value = float(score)
            if value > best_per_person.get(owner, -1.0):
                best_per_person[owner] = value

        ranked = sorted(best_per_person.items(), key=lambda kv: kv[1], reverse=True)
        top_id, top_score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

        if top_score < self.threshold:
            return Match(None, top_score, runner_up,
                         f"below threshold ({top_score:.3f} < {self.threshold:.3f})")

        if len(ranked) > 1 and (top_score - runner_up) < self.margin:
            # Two people scored almost the same. Naming either is a coin flip,
            # and a wrong name on a register gets believed.
            return Match(None, top_score, runner_up,
                         f"too close to call ({top_score:.3f} vs {runner_up:.3f})")

        return Match(self._people.get(top_id), top_score, runner_up, "matched")

    # -- reads --------------------------------------------------------------

    def people(self) -> list[Person]:
        with self._lock:
            return sorted(self._people.values(), key=lambda p: p.name)

    def person(self, person_id: str) -> Person | None:
        return self._people.get(person_id)

    def find_by_name(self, name: str) -> Person | None:
        lowered = name.strip().lower()
        return next(
            (p for p in self._people.values() if p.name.lower() == lowered), None
        )

    @property
    def size(self) -> int:
        """People with at least one enrolled face — i.e. recognisable people."""
        return sum(1 for p in self._people.values() if p.photo_on_file)

    @property
    def embedding_count(self) -> int:
        return len(self._owners)

    # -- index --------------------------------------------------------------

    def reload(self) -> None:
        """Rebuild the in-memory index from SQLite."""
        with self._lock:
            counts = {
                row["person_id"]: row["n"]
                for row in self._conn.execute(
                    "SELECT person_id, COUNT(*) AS n FROM face_embedding "
                    "WHERE model = ? GROUP BY person_id",
                    (self.model,),
                )
            }
            self._people = {
                row["id"]: Person(
                    id=row["id"], name=row["name"], type=row["type"],
                    group=row["grp"], detail=row["detail"],
                    photo_count=counts.get(row["id"], 0),
                    created_at=_parse(row["created_at"]),
                )
                for row in self._conn.execute("SELECT * FROM person")
            }

            rows = list(self._conn.execute(
                "SELECT person_id, vector, dimensions FROM face_embedding "
                "WHERE model = ?", (self.model,),
            ))
            if not rows:
                self._matrix = np.zeros((0, 0), dtype=np.float32)
                self._owners = []
                return

            dimensions = rows[0]["dimensions"]
            vectors, owners = [], []
            for row in rows:
                if row["dimensions"] != dimensions:
                    log.warning(
                        "skipping %s embedding of size %d, gallery is %d",
                        row["person_id"], row["dimensions"], dimensions,
                    )
                    continue
                vectors.append(np.frombuffer(row["vector"], dtype=np.float32))
                owners.append(row["person_id"])

            self._matrix = np.vstack(vectors).astype(np.float32)
            self._owners = owners

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "FaceGallery":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
