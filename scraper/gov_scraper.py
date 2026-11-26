#!/usr/bin/env python3
"""
gov_scraper.py — collect announcements from Greek government sites
(AADE, ESPA, ministries, e-EFKA, Diavgeia) and flag the ones about
subsidies / programs / tax deadlines.

Usage:
    python -m scraper.gov_scraper                 # scrape all enabled sources
    python -m scraper.gov_scraper --new-only      # only items not seen before
    python -m scraper.gov_scraper --only aade     # one source
    python -m scraper.gov_scraper --all-items     # keep items that match no category

    python -m scraper.gov_scraper --site-data data   # update the website's data

Outputs (in <repo>/output/, or --out DIR):
    items.json, items.csv, digest.html
State (seen items) is kept in output/seen.sqlite3

With --site-data DIR the scraper instead merges results into DIR/items.json
(a rolling history) and writes DIR/meta.json and DIR/feed.xml
for the static website.

Requires: requests, beautifulsoup4, lxml
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import html
import json
import logging
import os
import re
import sqlite3
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from lxml import etree

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "output"  # <repo>/output, next to scraper/
log = logging.getLogger("gov_scraper")
TZ = ZoneInfo("Europe/Athens")  # the GitHub runner is in UTC; dates are Greek


def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def today_local() -> date:
    return now_local().date()


# A URL or e-mail where site owners can reach you. Set with --contact or KYRBEIS_CONTACT.
CONTACT_ENV = "KYRBEIS_CONTACT"
OLD_CONTACT_ENV = "GOV_TRACKER_CONTACT"  # the project's earlier name; still read so old setups keep working

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def norm(text: str) -> str:
    """Lower-case and strip Greek accents/diaeresis so 'Προθεσμία' == 'προθεσμια'."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.lower().replace("ς", "σ")


def _month_forms() -> dict[str, int]:
    """Exact (normalized) month words: nominative, genitive and abbreviations."""
    greek = [
        ("ιανουαριοσ ιανουαριου ιαν", 1),
        ("φεβρουαριοσ φεβρουαριου φεβ", 2),
        ("μαρτιοσ μαρτιου μαρ", 3),
        ("απριλιοσ απριλιου απρ", 4),
        ("μαιοσ μαιου μαι", 5),
        ("ιουνιοσ ιουνιου ιουν", 6),
        ("ιουλιοσ ιουλιου ιουλ", 7),
        ("αυγουστοσ αυγουστου αυγ", 8),
        ("σεπτεμβριοσ σεπτεμβριου σεπ σεπτ", 9),
        ("οκτωβριοσ οκτωβριου οκτ", 10),
        ("νοεμβριοσ νοεμβριου νοε νοεμ", 11),
        ("δεκεμβριοσ δεκεμβριου δεκ", 12),
    ]
    english = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
    forms: dict[str, int] = {}
    for words, num in greek:
        for w in words.split():
            forms[w] = num
    for num, w in enumerate(english, 1):
        forms[w] = num
        forms[w[:3]] = num
    forms["sept"] = 9
    return forms


MONTHS = _month_forms()

_W = r"[a-zα-ω]"  # a letter, after norm()
ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
NUM_DATE = re.compile(r"(?<![\d/.])(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)")
WORD_DATE = re.compile(rf"(?<!\d)(\d{{1,2}})\s+({_W}{{3,12}})(?!{_W})\.?\s+(\d{{4}})(?!\d)")
# Year-less forms, only used when a reference date is known (see find_dates):
NUM_DM = re.compile(r"(?<![\d/.,-])(\d{1,2})[./](\d{1,2})(?![\d]|[./-]\d)")
WORD_DM = re.compile(rf"(?<!\d)(\d{{1,2}})\s+({_W}{{3,12}})(?!{_W})")


def _mk(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _nearest_occurrence(day: int, month: int, ref: date) -> date | None:
    """The date with this day/month closest to `ref`, in the year before, of, or after it.
    "25 Σεπτεμβρίου" in a post from 1 November is last September, not next."""
    options = [d for y in (ref.year - 1, ref.year, ref.year + 1) if (d := _mk(y, month, day))]
    return min(options, key=lambda d: abs((d - ref).days)) if options else None


# A deadline without a year may lie up to this far in the past (a recent reference, like
# "υπέβαλαν αίτηση έως τις 25 Σεπτεμβρίου" in a 1 November post, 37 days back); anything
# earlier means the next time that day comes round ("έως 31 Δεκεμβρίου" in March is this December).
YEARLESS_GRACE = timedelta(days=45)
# When the text is in the past tense ("Ολοκληρώθηκε η προκαταβολή … με αίτηση έως 25 Σεπτεμβρίου"),
# a date up to this far back is a reference to the past, not a deadline next year.
YEARLESS_GRACE_PAST = timedelta(days=200)

# Past-tense markers: aorist passives ("ολοκληρώθηκε", "πληρώθηκαν", "καταβλήθηκε") and a few
# active forms. "παρατάθηκε" (was extended) is past tense but announces a new, future deadline.
PAST_TENSE = re.compile(
    r"(?<!\w)(?!παραταθ)\w{3,}θηκ(?:ε|αν|ανε)(?!\w)"
    r"|(?<!\w)(?:υπεβαλ\w*|ειχαν|ειχε|εληξε|εληγε|ολοκληρωσαν|οριστικοποιησαν|πληρωσε|κατεβαλ\w*)(?!\w)"
)


def _resolve_yearless(day: int, month: int, ref: date, grace: timedelta = YEARLESS_GRACE) -> date | None:
    """The year for a deadline written without one, e.g. "έως 30 Σεπτεμβρίου".

    Deadlines usually lie ahead of the announcement, often many months ahead, so take
    the earliest occurrence no more than YEARLESS_GRACE before `ref`:
    - 1 Feb + "30 Σεπτεμβρίου" -> 30 Sep this year (nearest-date would pick last September)
    - 20 Nov + "10 Ιανουαρίου" -> next January
    - 1 Nov + "25 Σεπτεμβρίου" -> this September, a recent past reference (then dropped as past)
    find_dates widens `grace` for text in the past tense (see PAST_TENSE)."""
    options = [d for y in (ref.year - 1, ref.year, ref.year + 1) if (d := _mk(y, month, day))]
    return next((d for d in sorted(options) if d >= ref - grace), None)


def find_dates(text: str, ref: date | None = None, forward: bool = False) -> list[tuple[int, date]]:
    """Return (position, date) for every date-looking string in text.

    Dates need a year, unless `ref` is given: then "30 Νοεμβρίου" or "15/12"
    count too, in whichever year puts them closest to `ref`, or, with `forward`
    (for deadlines), in the year given by _resolve_yearless."""
    found: dict[int, date] = {}
    n = norm(text)
    if forward:
        grace = YEARLESS_GRACE_PAST if PAST_TENSE.search(n) else YEARLESS_GRACE

        def pick(day, month, ref):
            return _resolve_yearless(day, month, ref, grace)
    else:
        pick = _nearest_occurrence
    for m in ISO_DATE.finditer(n):
        if d := _mk(int(m[1]), int(m[2]), int(m[3])):
            found[m.start()] = d
    for m in NUM_DATE.finditer(n):
        if d := _mk(int(m[3]), int(m[2]), int(m[1])):  # Greek order: day/month/year
            found.setdefault(m.start(), d)
    for m in WORD_DATE.finditer(n):
        if (mon := MONTHS.get(m[2])) and (d := _mk(int(m[3]), mon, int(m[1]))):
            found.setdefault(m.start(), d)
    if ref is not None:
        for m in NUM_DM.finditer(n):
            if m.start() not in found and (d := pick(int(m[1]), int(m[2]), ref)):
                found[m.start()] = d
        for m in WORD_DM.finditer(n):
            if m.start() not in found and (mon := MONTHS.get(m[2])) and (d := pick(int(m[1]), mon, ref)):
                found[m.start()] = d
    return sorted(found.items())


def first_date(text: str) -> date | None:
    ds = find_dates(text)
    return ds[0][1] if ds else None


def _word_re(words: list[str]) -> re.Pattern[str]:
    """Match any of `words` at the start of a word. A trailing '!' means the
    whole word must match ("pass!" matches "pass" but not "password")."""
    parts = []
    for w in words:
        whole = w.endswith("!")
        w = norm(w.rstrip("!"))
        parts.append(rf"(?<!\w){re.escape(w)}" + (r"(?!\w)" if whole else ""))
    return re.compile("|".join(parts))


# "until" cues: the date right after them is the deadline.
UNTIL_CUES = _word_re(["έως!", "μέχρι!", "το αργότερο", "until!"])
# weaker cues: a date after them is probably a deadline.
DEADLINE_CUES = _word_re(["προθεσμί", "λήξη", "λήγει", "λήγουν", "καταληκτική", "deadline"])
EXTENSION = _word_re(["παράταση", "παράτασης", "παρατείνεται", "παρατείνονται", "extension", "extended"])
_FROM_BEFORE = re.compile(r"(?<!\w)(?:απο|from)(?:\s+(?:την|τη|τισ|the))?\s*$")

# What may sit between a cue and its date. After έως/μέχρι only small words
# ("έως και τις", "μέχρι την Παρασκευή"); "έως 72 δόσεις" has no date, so no deadline.
_FILLERS = [
    "και",
    "τισ",
    "την",
    "τη",
    "το",
    "του",
    "τησ",
    "των",
    "στισ",
    "στην",
    "στη",
    "στο",
    "στον",
    "ωσ",
    "δευτερα",
    "τριτη",
    "τεταρτη",
    "πεμπτη",
    "παρασκευη",
    "σαββατο",
    "κυριακη",
    "the",
    "on",
    "of",
    "and",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
_P = r"[\s,:;.·()\-–]*"
GAP_AFTER_UNTIL = re.compile(rf"^{_P}(?:(?:{'|'.join(_FILLERS)}){_P})*$")
# After weaker cues allow up to four words ("καταληκτική ημερομηνία υποβολής: 15/12"), but no numbers.
GAP_AFTER_CUE = re.compile(rf"^{_P}(?:[^\W\d_]+{_P}){{0,4}}$")


def find_deadline(text: str, published: date | None = None, context: str | None = None) -> date | None:
    """Pick the date most likely to be the deadline.

    - Only in actionable announcements (see read_context; `context` is the whole item,
      default `text`): "επίσκεψη έως 25/11" or "συνέδριο 22-25/11" has no deadline.
    - ...that ask the reader to act (owes_action): a payment calendar "23 έως 27/11" has none.
    - Year-less dates are resolved forward from `published` (or today); see _resolve_yearless.
    - The date must follow its cue closely; see GAP_AFTER_UNTIL / GAP_AFTER_CUE.
    - A date right after "από"/"from" is a start date, never a deadline.
    - Prefer a date right after έως/μέχρι over one after weaker cues.
    - If the text announces an extension (παράταση), the latest candidate wins,
      because the earlier one is the deadline being replaced."""
    n = norm(text)
    ref = published or today_local()
    dates = [
        (pos, d) for pos, d in find_dates(text, ref, forward=True) if not _FROM_BEFORE.search(n[max(0, pos - 14) : pos])
    ]

    def after(cue_re: re.Pattern[str], gap: re.Pattern[str]) -> list[date]:
        out = []
        for cue in cue_re.finditer(n):
            nxt = next(((pos, d) for pos, d in dates if pos >= cue.end()), None)
            if nxt and gap.match(n[cue.end() : nxt[0]]):
                out.append(nxt[1])
        return [d for d in out if not published or d >= published]

    whole = text if context is None else context
    actionable, _ = read_context(whole)
    if not actionable or not owes_action(whole):
        return None
    until, other = after(UNTIL_CUES, GAP_AFTER_UNTIL), after(DEADLINE_CUES, GAP_AFTER_CUE)
    if EXTENSION.search(n) and (until or other):
        return max(until + other)
    if until:
        return min(until)
    return min(other) if other else None


# ---------------------------------------------------------------------------
# Categorisation
# ---------------------------------------------------------------------------

# Keywords match at the start of a word, accents and case ignored, so
# "επιδοτηση" also matches "επιδοτήσεις". End a keyword with "!" to require
# the whole word ("pass!" won't match "password").
#
# Two strengths of keyword:
# - CATEGORIES: unambiguous; one is enough ("επίδομα", "ΕΝΦΙΑ", "αιτήσεις").
# - CATEGORY_HINTS: ambiguous words that also appear in ordinary news ("πρόγραμμα" is
#   also a schedule, "ενίσχυση" also "strengthening", "επιστροφή" also "return"). They
#   count only when the announcement is actionable (see ACTION) and isn't an event.
CATEGORIES: dict[str, list[str]] = {
    # Taxes only. Deadlines of any kind have their own filter ("Προθεσμία"), so «παράταση» or
    # «προθεσμία» no longer make a disability program or a farm payment "tax".
    "tax_deadline": [
        "φορολογικη δηλωση",
        "φορολογικεσ δηλωσεισ",
        "δηλωση φορολογιασ",
        "ενφια",
        "φπα!",
        "εκκαθαριστικ",
        "ρυθμιση οφειλων",
        "τελη κυκλοφοριασ",
        "e9!",
        "ε9!",
        "mydata!",
        "υποβολη δηλωσ",
        "πληρωμη φορου",
    ],
    "subsidy": [
        "επιδοτηση",
        "επιδοτησεισ",
        "επιδοτησεων",
        "επιδομα",
        "χρηματοδοτηση",
        "επιχορηγηση",
        "voucher",
        "κουπονι",
        "pass!",
        "εσπα!",
        "ταμειο ανακαμψησ",
        "εγγυοδοσια",
        "de minimis",
        "επιταγη",
        "εαε!",  # Ενιαία Αίτηση Ενίσχυσης, the farmers' annual subsidy application
        "ενιαια αιτηση ενισχυσ",
    ],
    "program": [
        "αιτησεισ",
        "αιτησεων",
        "προσκληση υποβολ",
        "αιτηση ενδιαφεροντοσ",
        "υποτροφι",  # υποτροφία, υποτροφίες, υποτροφιών (ΙΚΥ, ΕΛΙΔΕΚ)
        "εξοικονομω",
        "ανακαινιζω",
        "σπιτι μου",
        "προκηρυξ",
        # "πρόγραμμα" alone is ambiguous, these phrases are not
        "νεο προγραμμα",
        "προγραμμα απασχολησ",
        "προγραμμα καταρτισ",
        "κοινωφελ",
        "προγραμμα στεγασ",
        "προγραμμα επιδοτ",
        "προγραμμα ενισχυσ",
        "προγραμμα χρηματοδοτ",
        "επιδοτουμενο προγραμμα",
    ],
}
CATEGORY_HINTS: dict[str, list[str]] = {
    "tax_deadline": [
        "δοση",
        "δοσεισ",
        "εισφορεσ",
        "εισφορων",
        "καταβολη",
        "αποδειξεισ",
    ],
    "subsidy": [
        "ενισχυση",
        "ενισχυσεισ",
        "ενισχυσεων",
        "επιστροφη",
        "δανεια",
        "πιστωση",
        "αποζημιωσ",
    ],
    "program": [
        "προγραμμα!",
        "προγραμματοσ!",
        "προγραμματα!",
        "προγραμματων!",
        "δραση",
        "δρασεισ",
        "δρασεων",
        "προσκληση",
        "προσκλησεισ",
        "πλατφορμα",
        "ψηφιακ",
        "καταρτιση",
        "νεοι!",
        "νεουσ!",
        "νεεσ θεσεισ",
        "μητρωο",
        "ενταξη",
        "erasmus",
        "κινητικοτητα",  # Erasmus+ mobility calls
    ],
}

# Something a citizen or business does, gets or must meet. Without one of these (or a
# euro amount, or a CATEGORIES word), an announcement is news, not an opportunity.
ACTION = _word_re(
    [
        "αιτησ",
        "αιτηση!",
        "υποβολ",
        "υποβαλ",
        "δικαιουχ",
        "ωφελουμεν",
        "επιλεξιμ",
        "προυποθεσ",
        "πληρωμ",
        "πληρων",
        "πληρωθ",
        "καταβολ",
        "καταβαλ",
        "εξοφλ",
        "προθεσμ",
        "παρατασ",
        "παρατειν",
        "εγγραφ",
        "ρυθμισ",
        "δηλωσ",
        "ανοιγει",
        "ανοιξε",
        "αποτελεσματα!",  # results of a call matter to everyone who applied
        "αποτελεσματων!",
        "applications",
        "apply",
    ]
)
# Narrower: things a citizen must *do* by a date. "Πληρωμή … 23 έως 27/11" is when the state
# pays, not a deadline; "αιτήσεις έως 27/11" is.
CITIZEN_ACTION = _word_re(
    [
        "αιτησ",
        "αιτηση!",
        "υποβολ",
        "υποβαλ",
        "προθεσμ",
        "παρατασ",
        "παρατειν",
        "εγγραφ",
        "ρυθμισ",
        "δηλωσ",
        "εξοφλ",
        "applications",
        "apply",
    ]
)
MONEY = re.compile(r"\d[\d.,]*\s*(?:€|ευρω|εκατ|δισ)|€\s*\d")

# Events and agendas: visits, meetings, speeches, ceremonies. Their dates are when
# something happens, not deadlines, and their "programme" is a schedule.
EVENT = _word_re(
    [
        "_agenda_",
        "_statement_",
        "επισκεψ",
        "επισκεπτ",
        "περιοδει",
        "συναντηση",
        "συναντησεισ",
        "συναντηθηκ",
        "συνομιλ",
        "ομιλια",
        "ομιλιασ",
        "συνεντευξ",
        "εκδηλωση!",
        "εκδηλωσησ!",
        "εκδηλωσεισ!",
        "εκδηλωσεων!",
        "συνεδριο",
        "συνεδριου",
        "συνεδριασ",
        "τελετ",
        "ορκωμοσι",
        "χαιρετισμ",
        "υποδεχ",
        "ταξιδ",
        "συλλυπητηρι",
        "συγχαρητηρι",
        "εγκαινι",
        "βραβευσ",
        "εορτασμ",
        "επετει",
        "μνημοσυν",
        "κηδει",
        "συνοδο",
        "συνοδου",
        "συζητηση",
        # court notices (expropriations, hearings)
        "ακροατηριο",
        "εφετει",
        "πρωτοδικει",
        "απαλλοτρι",
        "δικασιμ",
        # outages and maintenance: "εκτός λειτουργίας έως 25/11" is not a deadline
        "εκτοσ λειτουργιασ",
        "διακοπη λειτουργιασ",
        "μη διαθεσιμ",
        "προγραμματισμενη συντηρηση",
        "εργασιεσ συντηρησησ",
    ]
)

_OFFICIALS = r"(?:προεδρ|αντιπροεδρ|πρωθυπουργ|υπουργ|υφυπουργ|αναπληρωτ|γενικ\w* γραμματ|κυβερνητικ|εκπροσωπ)"
# Phrases rewritten before matching, so one word can't be read in the wrong sense.
_REWRITES = [
    # "εκδήλωση ενδιαφέροντος" is applying, not an event
    (re.compile(r"(?<!\w)εκδηλωσ\w* ενδιαφεροντοσ"), "αιτηση ενδιαφεροντοσ"),
    # "το πρόγραμμα του Προέδρου", "δημόσιο πρόγραμμα", "πρόγραμμα επισκέψεων" are schedules
    (
        re.compile(
            rf"(?<!\w)(?:(?:δημοσιο|ημερησιο|εβδομαδιαιο|επισημο)\s+)?προγραμμα\w*\s+(?:του|τησ|των)\s+{_OFFICIALS}\w*"
        ),
        "_agenda_",
    ),
    (re.compile(r"(?<!\w)(?:δημοσιο|ημερησιο|εβδομαδιαιο|επισημο)\s+προγραμμα\w*"), "_agenda_"),
    (
        re.compile(
            r"(?<!\w)προγραμμα\w*\s+(?:επισκεψ|εκδηλωσ|ομιλ|μεταδοσ|εργασιων|συνεδρ|περιοδει|ταξιδ|εορτασμ|τελετ)\w*"
        ),
        "_agenda_",
    ),
    # "δηλώσεις του Υπουργού" are statements, not tax returns
    (re.compile(rf"(?<!\w)δηλωσ\w*\s+(?:του|τησ|των)\s+{_OFFICIALS}\w*"), "_statement_"),
]


# "Βασιλική Παντελοπούλου: …", "Δ. Μαρκόπουλος από τη Λάρισα: …": a person's statement.
# Two capitalised words (or an initial and a surname), optionally "για/από/σε … ", then a colon.
_PERSON_SAYS = re.compile(
    r"^\s*(?:[Α-ΩΆ-Ώ]\.\s*|[Α-ΩΆ-Ώ][α-ωά-ώϊϋΐΰ]+\s+)[Α-ΩΆ-Ώ][α-ωά-ώϊϋΐΰ]+(?:-[Α-ΩΆ-Ώ][α-ωά-ώϊϋΐΰ]+)?"
    r"(?:\s+(?:για|από|στ[οηα]ν?|σε|με)\s[^:]{0,160})?\s*:"
)
# ...unless the "name" is really a noun phrase that often opens a headline
_NOT_A_NAME = {
    "δελτιο",
    "ανακοινωση",
    "ενημερωση",
    "προγραμμα",
    "προσκληση",
    "παραταση",
    "πληρωμη",
    "νεο",
    "νεα",
    "νεεσ",
    "νεοι",
    "ανοιχτη",
    "δημοσια",
    "δημοσιο",
    "κοινο",
    "κοινη",
    "επιδομα",
    "ειδοποιηση",
    "οδηγοσ",
    "αποτελεσματα",
    "τροποποιηση",
    "προθεσμια",
    "επιταγη",
    "επιστροφη",
    "ρυθμιση",
    "ψηφιακη",
    "ψηφιακο",
    "εθνικη",
    "εθνικο",
    "ελληνικη",
    "ελληνικο",
    "ευρωπαικη",
    "ευρωπαικο",
    "κοινωνικοσ",
    "κοινωνικη",
    "κοινωνικο",
    "ενιαια",
    "ενιαιο",
    "ειδικη",
    "ειδικο",
    "εκτακτη",
    "εκτακτο",
    "μηνιαια",
    "ετησια",
}


def _person_says(text: str) -> bool:
    m = _PERSON_SAYS.match(text or "")
    return bool(m) and norm(m.group().split()[0]).rstrip(".") not in _NOT_A_NAME


def _prepare(text: str) -> str:
    n = ("_statement_ " if _person_says(text) else "") + norm(text)
    for rx, repl in _REWRITES:
        n = rx.sub(f" {repl} ", n)
    return n


_cat_re = {cat: _word_re(words) for cat, words in CATEGORIES.items()}
_hint_re = {cat: _word_re(words) for cat, words in CATEGORY_HINTS.items()}


def owes_action(text: str) -> bool:
    """Does the text ask the reader to do something (apply, submit, declare, pay a tax)?"""
    n = _prepare(text)
    return bool(CITIZEN_ACTION.search(n) or _cat_re["tax_deadline"].search(n) or _cat_re["program"].search(n))


def read_context(text: str) -> tuple[bool, bool]:
    """(actionable, event): does the text offer or require something, and is it an event/agenda?
    An announcement with an unambiguous keyword is always actionable, even if it is also an event
    ("Ομιλία για το νέο επίδομα" is news about a benefit)."""
    n = _prepare(text)
    strong = any(rx.search(n) for rx in _cat_re.values())
    event = bool(EVENT.search(n))
    actionable = strong or (not event and bool(ACTION.search(n) or MONEY.search(n)))
    return actionable, event


def categorize(text: str) -> list[str]:
    n = _prepare(text)
    strong = {cat for cat, rx in _cat_re.items() if rx.search(n)}
    actionable, _ = read_context(text)
    hinted = {cat for cat, rx in _hint_re.items() if rx.search(n)} if actionable else set()
    return [cat for cat in CATEGORIES if cat in strong | hinted]


# Who an announcement is for. Same matching rules as CATEGORIES. An item can be
# for several groups, or for none (general news), which the site shows under "all".
AUDIENCES: dict[str, list[str]] = {
    "households": [
        "νοικοκυρ",
        "οικογεν",
        "παιδι",
        "τεκν",
        "πολυτεκν",
        "μονογονε",
        "μαθητ",  # school pupils concern their families too (also in "students")
        "ενοικ",
        "κατοικι",
        "σπιτι",
        "στεγ",
    ],
    "businesses": [
        "επιχειρησ",
        "επιχειρηματ",
        "μικρομεσαι",
        "εταιρ",
        "εργοδοτ",
        "επαγγελματιεσ",  # ελεύθεροι επαγγελματίες, in any case ending
        "επαγγελματιασ",
        "επαγγελματιων",
        "επαγγελματιου",
        "αυτοαπασχολουμεν",
        "νεοφυ",
        "startup",
        "εξαγωγ",
    ],
    "farmers": [
        "αγροτ",
        "κτηνοτροφ",
        "οσδε!",
        "καλλιεργ",
        "αλιε",
        "μελισσοκομ",
        "γεωργ",
        "ελγα!",
    ],
    "pensioners": ["συνταξ", "εφαπαξ"],
    "workers": [
        "ανεργ",
        "εργαζομεν",
        "μισθωτ",
        "απασχολησ",
        "θεσεισ εργασιασ",
        "καταρτισ",
    ],
    "students": [
        "μαθητ",
        "φοιτητ",
        "σπουδαστ",
        "σπουδεσ!",
        "σπουδων!",
        "προπτυχιακ",
        "μεταπτυχιακ",
        "υποτροφι",
        "erasmus",
        "πανελλαδικ",
        "τελειοφοιτ",
    ],
    "researchers": [
        "ερευνητ",  # ερευνητές, ερευνητικός
        "ερευνα!",
        "ερευνασ!",
        "διδακτορ",  # υποψήφιοι διδάκτορες, διδακτορικό
        "μεταδιδακτορ",
        "ακαδημαικ",
        "πανεπιστημ",
        "αει!",
        "ελιδεκ",
        "ελκε!",
    ],
    "disability": [
        "αναπηρ",  # αναπηρία, ΑμεΑ written out, αναπηρικό
        "αμεα!",
        "προσωπικοσ βοηθοσ",
        "κωφ",
        "τυφλ",
    ],
}
_aud_re = {aud: _word_re(words) for aud, words in AUDIENCES.items()}


def audiences_for(text: str) -> list[str]:
    n = norm(text)
    # «μη μισθωτοί» are the self-employed, not employees: read it as such before matching «μισθωτ»
    n = re.sub(r"(?<!\w)μη μισθωτ\w*", "αυτοαπασχολουμενοι", n)
    return [aud for aud, rx in _aud_re.items() if rx.search(n)]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Item:
    source: str
    title: str
    url: str
    published: str | None = None  # ISO date
    summary: str = ""
    categories: list[str] = field(default_factory=list)
    deadline: str | None = None  # ISO date
    scraped_at: str = field(default_factory=lambda: now_local().isoformat(timespec="seconds"))
    first_seen: str | None = None  # set when merged into the site history
    audiences: list[str] = field(default_factory=list)  # who it's for, see AUDIENCES

    @property
    def uid(self) -> str:
        return hashlib.sha1(f"{self.url}|{self.title}".encode(), usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class BlockedByRobots(Exception):
    pass


class HostUnreachable(Exception):
    """A site that could not be reached earlier in this run: fail at once instead of waiting again."""


RETRY_STATUS = {429, 500, 502, 503, 504}


class Fetcher:
    """Polite HTTP client: identifies itself, honours robots.txt (incl. Crawl-delay),
    waits between requests to the same host and retries only errors that may go away."""

    def __init__(
        self,
        contact: str = "",
        delay: float = 1.5,
        timeout: int = 25,
        retries: int = 3,
        connect_timeout: int = 10,
    ):
        self.s = requests.Session()
        self.agent = f"Kyrbeis/1.0 (+{contact})" if contact else "Kyrbeis/1.0"
        self.s.headers.update({"User-Agent": self.agent, "Accept-Language": "el-GR,el;q=0.9,en;q=0.6"})
        self.delay = delay
        # (connect, read): a dead site is noticed after 10 s, a slow download still gets 25 s
        self.timeout = (connect_timeout, timeout)
        self.retries = retries
        self._down: dict[str, str] = {}  # host -> why it was unreachable
        self._last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    def _wait(self, host: str, delay: float) -> None:
        wait = delay - (time.time() - self._last.get(host, 0))
        if wait > 0:
            time.sleep(wait)

    def _robots_for(self, url: str) -> RobotFileParser | None:
        p = urlparse(url)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self._robots:
            rp: RobotFileParser | None = None
            try:
                self._wait(p.netloc, self.delay)
                r = self.s.get(f"{key}/robots.txt", timeout=self.timeout)
                self._last[p.netloc] = time.time()
                ended_at = urlparse(r.url or "").path
                is_robots = ended_at.endswith("/robots.txt") and not r.text.lstrip().startswith("<")
                if r.ok and is_robots:
                    rp = RobotFileParser()
                    rp.parse(r.text.splitlines())
                # 4xx, or a redirect to an HTML page, means there is no robots.txt: all allowed (RFC 9309)
            except requests.RequestException as e:
                log.debug("robots.txt for %s unavailable: %s", key, e)
            self._robots[key] = rp
        return self._robots[key]

    def get(self, url: str, **kw) -> requests.Response:
        host = urlparse(url).netloc
        if host in self._down:
            raise HostUnreachable(f"{url}: skipped, {host} was unreachable earlier in this run ({self._down[host]})")
        rp = self._robots_for(url)
        if rp is not None and not rp.can_fetch(self.agent, url):
            raise BlockedByRobots(f"{url}: disallowed by robots.txt")
        crawl_delay = (rp.crawl_delay(self.agent) if rp else None) or 0
        delay = max(self.delay, float(crawl_delay))

        for attempt in range(1, self.retries + 1):
            self._wait(host, delay)
            last = attempt == self.retries
            try:
                r = self.s.get(url, timeout=self.timeout, **kw)
            except (requests.ConnectionError, requests.Timeout) as e:
                self._last[host] = time.time()
                if last:
                    if isinstance(e, requests.ConnectionError):  # includes connect timeouts, not slow reads
                        self._down[host] = type(e).__name__
                    raise RuntimeError(f"{url}: {e}") from e
                time.sleep(2 * attempt)
                continue
            self._last[host] = time.time()
            if r.status_code in RETRY_STATUS and not last:
                retry_after = r.headers.get("Retry-After", "")
                time.sleep(min(int(retry_after), 60) if retry_after.isdigit() else 2 * attempt)
                continue
            r.raise_for_status()  # 404, 403 … fail straight away: retrying won't help
            if not r.encoding or r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding  # Greek sites often mislabel charset
            return r
        raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def safe_url(href: str | None, base: str) -> str | None:
    """Absolute http(s) URL without its #fragment, or None for javascript:, mailto:, etc."""
    if not href:
        return None
    url = urljoin(base, href.strip())
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return parts._replace(fragment="").geturl()


def _same_page(a: str, b: str) -> bool:
    return urldefrag(a).url.rstrip("/") == urldefrag(b).url.rstrip("/")


def parse_feed(xml_bytes: bytes, source: str, base_url: str) -> list[Item]:
    """RSS 2.0 or Atom, without needing feedparser."""
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(xml_bytes, parser=parser)
    if root is None:
        return []
    items: list[Item] = []

    def text(el, *names):
        for nm in names:
            found = el.find(nm)
            if found is not None and (found.text or "").strip():
                return found.text.strip()
        return ""

    atom = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(".//item") or root.findall(f".//{atom}entry")
    for e in entries:
        title = text(e, "title", f"{atom}title")
        link = text(e, "link")
        if not link:
            le = e.find(f"{atom}link")
            link = le.get("href", "") if le is not None else ""
        url = safe_url(link, base_url)
        summary = text(e, "description", f"{atom}summary", f"{atom}content")
        summary = BeautifulSoup(summary, "lxml").get_text(" ", strip=True) if summary else ""
        pub_raw = text(e, "pubDate", f"{atom}published", f"{atom}updated", "{http://purl.org/dc/elements/1.1/}date")
        pub = _parse_any_date(pub_raw)
        if title and url:
            items.append(Item(source, title, url, pub.isoformat() if pub else None, summary[:600]))
    return items


def _parse_any_date(raw: str) -> date | None:
    """Feed dates -> the calendar date in Athens (23:30Z on the 9th is the 10th in Greece)."""
    if not raw:
        return None
    from email.utils import parsedate_to_datetime

    dt: datetime | None = None
    with contextlib.suppress(Exception):
        dt = parsedate_to_datetime(raw)
    if dt is None:
        with contextlib.suppress(ValueError):
            dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    if dt is None:
        return first_date(raw)
    return dt.astimezone(TZ).date() if dt.tzinfo else dt.date()


def _text_without(node, exclude: str) -> str:
    """Text of `node` with one occurrence of `exclude` (the headline) removed,
    so a deadline inside the title isn't taken for the publication date."""
    txt = node.get_text(" ", strip=True)
    return txt.replace(exclude, " ", 1) if exclude else txt


def parse_html(page: str, source: str, base_url: str, cfg: dict) -> list[Item]:
    """Two modes:
    1. cfg['item_selector'] given -> each match is one item; title/link/date
       from optional sub-selectors.
    2. otherwise a heuristic: every link inside cfg['container'] (or <main>)
       whose text looks like a headline, dated from its own block only.
    """
    soup = BeautifulSoup(page, "lxml")
    for bad in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        bad.decompose()
    items: list[Item] = []
    host = urlparse(base_url).netloc

    if cfg.get("item_selector"):
        for node in soup.select(cfg["item_selector"]):
            a = node.select_one(cfg.get("link_selector", "a[href]"))
            url = safe_url(a.get("href") if a else None, base_url)
            if not url:
                continue
            t_el = node.select_one(cfg["title_selector"]) if cfg.get("title_selector") else a
            title = (t_el or a).get_text(" ", strip=True)
            if cfg.get("date_selector"):
                d_el = node.select_one(cfg["date_selector"])
                pub = first_date(d_el.get_text(" ", strip=True)) if d_el else None
            else:
                pub = first_date(_text_without(node, title))
            summ = node.get_text(" ", strip=True)
            items.append(Item(source, title, url, pub.isoformat() if pub else None, summ[:600]))
        return items

    scope = soup.select_one(cfg.get("container", "")) if cfg.get("container") else None
    candidates = [scope] if scope else []
    candidates += [soup.find("main"), soup.find(id=re.compile("content|main", re.IGNORECASE))]
    candidates += [soup.body or soup]  # last resort: the whole page
    min_len = cfg.get("min_title_len", 25)
    url_must = cfg.get("link_contains")

    def headlines(area) -> list[tuple[object, str, str]]:
        found: list[tuple[object, str, str]] = []  # (anchor, title, url)
        seen: set[str] = set()
        for a in area.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            url = safe_url(a["href"], base_url)
            if not url or len(title) < min_len or url in seen or _same_page(url, base_url):
                continue
            if urlparse(url).netloc != host and not cfg.get("allow_external"):
                continue
            if url_must and url_must not in url:
                continue
            seen.add(url)
            found.append((a, title, url))
        return found

    # 1. pick the headline links from the first area that has any. Some sites (e-EFKA)
    #    leave <main> empty and put their news in a block elsewhere on the page.
    picked: list[tuple[object, str, str]] = []
    for area in candidates:
        if area is not None and (picked := headlines(area)):
            scope = area
            break

    # 2. date each one from its own block: climb while the block holds no other headline
    anchors = {id(a) for a, _, _ in picked}
    for a, title, url in picked:
        block = a
        for _ in range(4):
            parent = block.parent
            if parent is None or parent is scope:
                break
            if any(id(x) in anchors and x is not a for x in parent.find_all("a", href=True)):
                break
            block = parent
        pub = first_date(_text_without(block, title)[:400]) if block is not a else None
        summ = block.get_text(" ", strip=True)[:600] if block is not a else ""
        items.append(Item(source, title, url, pub.isoformat() if pub else None, summ))
    return items


def parse_diavgeia(data: dict, source: str) -> list[Item]:
    items = []
    for d in data.get("decisions", []):
        ada = d.get("ada", "")
        ts = d.get("issueDate") or d.get("publishTimestamp")
        pub = datetime.fromtimestamp(ts / 1000, tz=TZ).date().isoformat() if isinstance(ts, (int, float)) else None
        fallback = f"https://diavgeia.gov.gr/decision/view/{quote(ada)}"
        url = safe_url(d.get("documentUrl"), "https://diavgeia.gov.gr/") or fallback
        items.append(Item(source, d.get("subject", "").strip(), url, pub, f"ΑΔΑ {ada} · {d.get('organizationId', '')}"))
    return items


# ---------------------------------------------------------------------------
# Source runner
# ---------------------------------------------------------------------------


def scrape_source(f: Fetcher, src: dict, since: date) -> tuple[list[Item], list[str]]:
    """Return (items, errors). A source with several pages or search terms keeps
    what it got from the ones that worked; it only raises if every one failed."""
    kind, name = src["type"], src["name"]
    items: list[Item] = []
    errors: list[str] = []

    def attempt(label: str, fn) -> None:
        try:
            items.extend(fn())
        except Exception as e:  # noqa: BLE001 - one bad page shouldn't sink the source
            log.warning("%s: %s failed: %s", name, label, e)
            errors.append(f"{label}: {e}"[:200])

    def html_from(url: str) -> list[Item]:
        r = f.get(url)
        # parse against the address we ended up at: efka.gov.gr redirects to e-efka.gov.gr,
        # and links on that page must count as the site's own, not as external
        return parse_html(r.text, name, r.url or url, src)

    def feed_from(url: str) -> list[Item]:
        r = f.get(url)
        return parse_feed(r.content, name, r.url or url)

    if kind == "rss":
        attempt(src["url"], lambda: feed_from(src["url"]))
        tries = 1
    elif kind == "html":
        pages = [src["url"], *src.get("extra_pages", [])]
        for url in pages:
            attempt(url, lambda url=url: html_from(url))
        tries = len(pages)
    elif kind == "rss_or_html":
        attempt(src["feed_url"], lambda: feed_from(src["feed_url"]))
        if not items:
            log.info("%s: no feed items, falling back to HTML", name)
            errors.clear()
            attempt(src["url"], lambda: html_from(src["url"]))
        tries = 1
    elif kind == "diavgeia":
        api = src.get("api", "https://diavgeia.gov.gr/opendata/search.json")
        terms = src.get("terms", [])
        for term in terms:
            params = {
                "subject": term,
                "from_issue_date": since.isoformat(),
                "size": src.get("size", 50),
                "sort": "recent",
            }
            if src.get("org"):
                params["org"] = src["org"]
            attempt(term, lambda params=params: parse_diavgeia(f.get(api, params=params).json(), name))
        tries = len(terms)
    else:
        raise ValueError(f"unknown source type {kind!r}")

    if errors and len(errors) >= tries:
        raise RuntimeError("; ".join(errors))
    return items, errors


def clean_summary(summary: str, title: str) -> str:
    """Drop the parts of a summary that only repeat the title or the date.
    ("16 Οκτ 2026 Ρύθμιση οφειλών…" under the title "Ρύθμιση οφειλών…" -> "")"""
    s = (summary or "").replace(title, " ") if title else (summary or "")
    s = re.sub(r"\s+", " ", s).strip(" ·|-–—:")
    if not s:
        return ""
    rest = norm(s)
    # strip every date form; if (almost) nothing is left, the summary was just a date
    no_dates = ISO_DATE.sub("", rest)
    no_dates = NUM_DATE.sub("", no_dates)
    no_dates = WORD_DATE.sub(lambda m: "" if m[2] in MONTHS else m[0], no_dates)
    no_dates = WORD_DM.sub(lambda m: "" if m[2] in MONTHS else m[0], no_dates)
    leftover = re.sub(r"[\d\W_]+", "", no_dates)
    if len(leftover) < 3 or rest in norm(title):
        return ""
    return _LEADING_DATE.sub(lambda m: "" if _is_date(m[0]) else m[0], s, count=1)


_LEADING_DATE = re.compile(r"^\s*\d{1,2}(?:[./-]\d{1,2}(?:[./-]\d{2,4})?|\s+\w+\.?(?:\s+\d{4})?)[\s,·|:–-]*")


def _is_date(token: str) -> bool:
    return bool(find_dates(token, today_local()))


# "Δελτίο Τύπου 20/11/2026 ΕΑΕ 2026: …" (AADE): the label and date are shown under the title anyway
_PRESS_RELEASE = re.compile(r"^\s*Δελτίο\s+Τύπου\s*(?:\d{1,2}[./]\d{1,2}[./]\d{2,4})?\s*[:–-]?\s*", re.IGNORECASE)


def clean_title(title: str) -> str:
    cleaned = _PRESS_RELEASE.sub("", title or "")
    return cleaned[:1].upper() + cleaned[1:] if cleaned else title


def enrich(item: Item) -> Item:
    today = today_local()
    item.title = clean_title(item.title)
    # a "published" date in the future is a misread deadline, not a publication date
    if item.published and item.published > today.isoformat():
        item.published = None
    item.summary = clean_summary(item.summary, item.title)
    item.categories = categorize(f"{item.title} {item.summary}")  # also judged on the whole text
    item.audiences = audiences_for(f"{item.title} {item.summary}")
    pub = date.fromisoformat(item.published) if item.published else None
    # title and summary separately, so a cue at the end of one can't grab a date from the other
    # ...but whether it's actionable at all is judged on the whole announcement
    whole = f"{item.title} {item.summary}"
    dl = find_deadline(item.title, pub, whole) or find_deadline(item.summary, pub, whole)
    item.deadline = dl.isoformat() if dl else None
    return item


# ---------------------------------------------------------------------------
# State + output
# ---------------------------------------------------------------------------


def open_db(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE IF NOT EXISTS seen (uid TEXT PRIMARY KEY, first_seen TEXT, json TEXT)")
    return db


def write_outputs(items: list[Item], outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(i) for i in items]
    (outdir / "items.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(outdir / "items.csv", "w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel shows Greek
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["source"])
        w.writeheader()
        for r in rows:
            r = dict(r, categories=";".join(r["categories"]))
            w.writerow(r)
    (outdir / "digest.html").write_text(render_digest(items), encoding="utf-8")


CAT_LABEL = {
    "tax_deadline": "Φορολογικά / Προθεσμίες",
    "subsidy": "Επιδοτήσεις / Ενισχύσεις",
    "program": "Προγράμματα / Προσκλήσεις",
    "other": "Λοιπά",
}


def render_digest(items: list[Item]) -> str:
    today = today_local()
    upcoming = sorted((i for i in items if i.deadline and i.deadline >= today.isoformat()), key=lambda i: i.deadline)

    def row(i: Item) -> str:
        dl = ""
        if i.deadline:
            days = (date.fromisoformat(i.deadline) - today).days
            cls = "soon" if 0 <= days <= 14 else ""
            dl = f'<span class="dl {cls}">λήξη {i.deadline}' + (f" · σε {days} ημ." if days >= 0 else "") + "</span>"
        return (
            f'<li><a href="{html.escape(i.url)}">{html.escape(i.title)}</a>'
            f'<div class="meta">{html.escape(i.source)} · {i.published or "—"} {dl}</div></li>'
        )

    sections = []
    if upcoming:
        sections.append("<h2>Επερχόμενες προθεσμίες</h2><ul>" + "".join(row(i) for i in upcoming) + "</ul>")
    for cat in ["tax_deadline", "subsidy", "program", "other"]:
        group = [i for i in items if (cat in i.categories) or (cat == "other" and not i.categories)]
        group.sort(key=lambda i: i.published or "", reverse=True)
        if group:
            sections.append(f"<h2>{CAT_LABEL[cat]} ({len(group)})</h2><ul>" + "".join(row(i) for i in group) + "</ul>")
    body = "".join(sections) or "<p>Δεν βρέθηκαν νέα.</p>"
    return f"""<!doctype html><html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Gov digest {today}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 16px;color:#222}}
h1{{font-size:1.4rem}}h2{{margin-top:2rem;border-bottom:1px solid #ddd;font-size:1.1rem}}
ul{{list-style:none;padding:0}}li{{margin:.7rem 0}}a{{color:#0b57d0;text-decoration:none}}
.meta{{color:#666;font-size:.85rem}}.dl{{background:#eef;padding:1px 6px;border-radius:4px;margin-left:6px}}
.dl.soon{{background:#fde2e1;color:#a50e0e}}</style></head><body>
<h1>Ενημέρωση από κρατικούς φορείς — {today.strftime("%d/%m/%Y")}</h1>{body}</body></html>"""


# ---------------------------------------------------------------------------
# Website data (used by the GitHub Actions workflow)
# ---------------------------------------------------------------------------


def merge_history(existing: list[dict], fresh: list[Item], keep_days: int, now: str) -> list[Item]:
    """Combine previous items.json rows with this run's items.
    Existing items keep their first_seen; fresh ones get `now`.
    Items older than keep_days (by published, or first_seen) are dropped,
    unless their deadline is still ahead.

    Stored items are re-classified with the current rules, so a fix to
    deadline or keyword detection also corrects the history."""
    by_uid: dict[str, Item] = {}
    known = set(Item.__dataclass_fields__)
    for row in existing:
        it = enrich(Item(**{k: v for k, v in row.items() if k in known}))
        by_uid[it.uid] = it
    for it in fresh:
        if it.uid in by_uid:
            it.first_seen = by_uid[it.uid].first_seen
        else:
            it.first_seen = now
        by_uid[it.uid] = it
    # the same headline posted twice by one source (two links, same day) is one announcement
    seen: dict[tuple, str] = {}
    for uid, it in list(by_uid.items()):
        key = (it.source, norm(it.title).strip(), it.published)
        if key in seen:
            del by_uid[uid]
        else:
            seen[key] = uid
    cutoff = (date.fromisoformat(now[:10]) - timedelta(days=keep_days)).isoformat()
    today = now[:10]
    kept = [
        i
        for i in by_uid.values()
        if (i.published or (i.first_seen or now)[:10]) >= cutoff or (i.deadline and i.deadline >= today)
    ]
    kept.sort(key=lambda i: (i.published or (i.first_seen or "")[:10], i.first_seen or ""), reverse=True)
    return kept


def render_rss(items: list[Item], site_url: str) -> str:
    from email.utils import format_datetime

    def pub(i: Item) -> str:
        d = datetime.fromisoformat(i.published or i.first_seen or "2000-01-01")
        return format_datetime(d.replace(tzinfo=TZ))

    entries = "".join(
        f"<item><title>{html.escape(i.title)}</title><link>{html.escape(i.url)}</link>"
        f'<guid isPermaLink="false">{i.uid}</guid><pubDate>{pub(i)}</pubDate>'
        f"<category>{html.escape(','.join(i.categories))}</category>"
        f"<description>{html.escape((i.summary or '')[:400])}</description></item>"
        for i in items[:100]
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>Κύρβεις</title><link>{html.escape(site_url)}</link>"
        "<description>Προθεσμίες, επιδοτήσεις και προγράμματα από κρατικούς φορείς</description>"
        f"<language>el</language>{entries}</channel></rss>"
    )


def write_site_data(
    fresh: list[Item], outdir: Path, sources: list[dict], status: dict, keep_days: int, site_url: str
) -> list[Item]:
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "items.json"
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    now = now_local().isoformat(timespec="seconds")
    items = merge_history(existing, fresh, keep_days, now)
    # scraped_at changes every run; leaving it out means items.json only changes when the items do
    rows = [{**{k: v for k, v in asdict(i).items() if k != "scraped_at"}, "uid": i.uid} for i in items]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    meta = {
        "updated": datetime.now(TZ).isoformat(timespec="seconds"),  # with +02:00/+03:00 offset
        "sources": [
            {
                "name": s["name"],
                "label": s.get("label", s["name"]),
                # people should land on the agency's website, not on its RSS feed or API
                "url": s.get("website") or s.get("url") or s.get("api"),
                **status.get(s["name"], {}),
            }
            for s in sources
        ],
        "counts": {c: sum(c in i.categories for i in items) for c in CATEGORIES},
        "audience_counts": {a: sum(a in i.audiences for i in items) for a in AUDIENCES},
        "total": len(items),
    }
    (outdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    (outdir / "deadlines.ics").unlink(missing_ok=True)  # the calendar file was dropped (24 Nov 2026)
    (outdir / "feed.xml").write_text(render_rss(items, site_url), encoding="utf-8")
    return items


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(HERE / "sources.json"))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--only", nargs="*", help="source names to run")
    ap.add_argument("--days", type=int, default=30, help="ignore items older than N days (default 30)")
    ap.add_argument("--new-only", action="store_true", help="output only items not seen in earlier runs")
    ap.add_argument("--all-items", action="store_true", help="keep items matching no category")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between requests to the same host")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument(
        "--site-data",
        metavar="DIR",
        help="merge into DIR/items.json and write meta.json and feed.xml for the website",
    )
    ap.add_argument("--keep-days", type=int, default=365, help="history kept in --site-data mode")
    ap.add_argument("--site-url", default="", help="public URL of the site (used in feed.xml)")
    ap.add_argument(
        "--contact",
        default=os.environ.get(CONTACT_ENV) or os.environ.get(OLD_CONTACT_ENV, ""),
        help=f"URL or e-mail sent in the User-Agent so site owners can reach you (or set {CONTACT_ENV})",
    )
    a = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    configured = [
        s
        for s in json.loads(Path(a.config).read_text(encoding="utf-8"))["sources"]
        if not a.only or s["name"] in a.only
    ]
    sources = [s for s in configured if s.get("enabled", True)]
    disabled = [s for s in configured if not s.get("enabled", True)]
    since = today_local() - timedelta(days=a.days)
    if not a.contact:
        log.warning("no --contact given: set a URL or e-mail so site owners can reach you")
    f = Fetcher(contact=a.contact, delay=a.delay)

    collected: dict[str, Item] = {}
    status: dict[str, dict] = {}
    for src in sources:
        try:
            got, page_errors = scrape_source(f, src, since)
            log.info("%-14s %3d items", src["name"], len(got))
        except Exception as e:  # noqa: BLE001
            log.warning("%-14s FAILED: %s", src["name"], e)
            status[src["name"]] = {"ok": False, "found": 0, "error": str(e)[:200]}
            continue
        kept = 0
        for it in got:
            enrich(it)
            if it.published and it.published < since.isoformat():
                continue
            # keep anything with a topic, and anything with a deadline even without one
            if not it.categories and not it.deadline and not (a.all_items or src.get("keep_all")):
                continue
            # for pages where menu links slip in: real posts carry a date
            if src.get("require_date") and not it.published:
                continue
            if it.uid not in collected:
                collected[it.uid] = it
                kept += 1
        if not got and src.get("expect_items", True):
            # a page that normally lists posts returning nothing usually means the layout changed
            msg = "0 items found: the page layout may have changed (check the selectors)"
            log.warning("%-14s FAILED: %s", src["name"], msg)
            status[src["name"]] = {"ok": False, "found": 0, "error": msg}
            continue
        status[src["name"]] = {"ok": True, "found": len(got), "kept": kept}
        if page_errors:
            status[src["name"]]["partial"] = page_errors

    if a.site_data:
        # disabled sources still appear on the site, marked unavailable, with the reason
        shown = {**status, **{s["name"]: {"ok": False, "disabled": True, "error": s.get("note", "")} for s in disabled}}
        items = write_site_data(
            list(collected.values()), Path(a.site_data), sources + disabled, shown, a.keep_days, a.site_url
        )
        failed = [n for n, s in status.items() if not s["ok"]]
        log.info(
            "site data: %d items in history, %d this run, failed sources: %s",
            len(items),
            len(collected),
            ", ".join(failed) or "none",
        )
        # fail the CI job only when *every* source failed, so one flaky site doesn't block updates
        return 1 if sources and len(failed) == len(sources) else 0

    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    db = open_db(outdir / "seen.sqlite3")
    items = list(collected.values())
    new = []
    now = now_local().isoformat(timespec="seconds")
    for it in items:
        cur = db.execute(
            "INSERT OR IGNORE INTO seen VALUES (?,?,?)", (it.uid, now, json.dumps(asdict(it), ensure_ascii=False))
        )
        if cur.rowcount:
            new.append(it)
    db.commit()

    result = new if a.new_only else items
    write_outputs(result, outdir)
    log.info("done: %d relevant items (%d new) -> %s", len(items), len(new), outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
