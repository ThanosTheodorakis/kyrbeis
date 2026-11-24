"""Offline tests: no network needed. Run with `pytest`."""

from dataclasses import asdict
from datetime import date

import pytest

from scraper import gov_scraper as g

# --- dates & deadlines -------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Δημοσιεύθηκε 05/11/2026", date(2026, 11, 5)),
        ("12 Νοεμβρίου 2026", date(2026, 11, 12)),
        ("3 Ιουλ 2026", date(2026, 7, 3)),
        ("ΙΟΥΝΙΟΥ: 30 Ιουνίου 2026", date(2026, 6, 30)),
        ("2026-01-15T10:00", date(2026, 1, 15)),
        ("31/02/2026 is not a date", None),
    ],
)
def test_first_date(text, expected):
    assert g.first_date(text) == expected


def test_deadline_after_cue_word():
    t = "Παράταση προθεσμίας υποβολής δηλώσεων ΦΠΑ έως τις 30 Νοεμβρίου 2026. Ανακοίνωση 10/11/2026"
    assert g.find_deadline(t, date(2026, 11, 10)) == date(2026, 11, 30)


def test_deadline_numeric():
    assert g.find_deadline("Οι αιτήσεις υποβάλλονται μέχρι 15/12/2026") == date(2026, 12, 15)


def test_no_deadline_without_cue():
    assert g.find_deadline("Νέο πρόγραμμα 10/11/2026") is None


def test_deadline_ignores_dates_before_publication():
    t = "Έως 01/10/2026 υποβλήθηκαν 5.000 αιτήσεις. Νέα προθεσμία έως 20/11/2026"
    assert g.find_deadline(t, date(2026, 11, 5)) == date(2026, 11, 20)


# --- categories --------------------------------------------------------------


@pytest.mark.parametrize(
    "text,cat",
    [
        ("Παράταση προθεσμίας για τον ΕΝΦΙΑ", "tax_deadline"),
        ("Νέα επιδότηση για φωτοβολταϊκά στη στέγη", "subsidy"),
        ("Ξεκινούν οι αιτήσεις για το πρόγραμμα «Ανακαινίζω»", "program"),
    ],
)
def test_categorize(text, cat):
    assert cat in g.categorize(text)


def test_irrelevant_text_has_no_category():
    assert g.categorize("Συνάντηση του Υπουργού με τον Πρέσβη") == []


def test_accent_and_case_insensitive():
    assert g.norm("ΠΡΟΘΕΣΜΊΑ") == g.norm("προθεσμια")


# --- parsers -----------------------------------------------------------------

PAGE = """<html><body><nav><a href="/x">Πολύ μακρύς σύνδεσμος πλοήγησης που αγνοείται</a></nav>
<main><div class="views-row"><span>10 Νοε 2026</span>
<a href="/anakoinoseis/paratasi-fpa">Παράταση προθεσμίας υποβολής δηλώσεων ΦΠΑ έως 30/11/2026</a></div>
<div class="views-row"><span>09/11/2026</span>
<a href="/nea/synantisi">Συνάντηση του Διοικητή με αντιπροσωπεία επιμελητηρίου</a></div>
<a href="/short">Λίγα</a></main></body></html>"""


def test_html_heuristic():
    items = [g.enrich(i) for i in g.parse_html(PAGE, "aade", "https://www.aade.gr/deltia", {})]
    assert [i.url for i in items] == [
        "https://www.aade.gr/anakoinoseis/paratasi-fpa",
        "https://www.aade.gr/nea/synantisi",
    ]
    first = items[0]
    assert (first.published, first.deadline, first.categories) == ("2026-11-10", "2026-11-30", ["tax_deadline"])


def test_html_selectors():
    items = g.parse_html(
        PAGE, "aade", "https://www.aade.gr/", {"item_selector": "div.views-row", "date_selector": "span"}
    )
    assert len(items) == 2 and items[1].published == "2026-11-09"


def test_rss():
    rss = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
    <item><title>Νέο πρόγραμμα επιδότησης</title><link>https://www.mindev.gov.gr/neo/</link>
    <pubDate>Tue, 10 Nov 2026 09:00:00 +0200</pubDate><description>&lt;p&gt;x&lt;/p&gt;</description></item>
    </channel></rss>""".encode()
    it = g.enrich(g.parse_feed(rss, "mindev", "https://www.mindev.gov.gr/")[0])
    assert it.published == "2026-11-10"
    assert {"subsidy", "program"} <= set(it.categories)


def test_atom_relative_link():
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Title long enough</title>
    <link href="/a"/><updated>2026-11-09T10:00:00Z</updated></entry></feed>"""
    it = g.parse_feed(atom, "s", "https://e.gr/")[0]
    assert (it.url, it.published) == ("https://e.gr/a", "2026-11-09")


def test_diavgeia():
    data = {
        "decisions": [
            {
                "ada": "ΨΑΒΓ46ΜΤΛ6-123",
                "subject": "Προκήρυξη δράσης «Ψηφιακός Μετασχηματισμός»",
                "issueDate": 1762761600000,
                "documentUrl": "https://diavgeia.gov.gr/doc/x",
            }
        ]
    }
    it = g.enrich(g.parse_diavgeia(data, "diavgeia")[0])
    assert it.categories and it.published and it.url.endswith("/doc/x")


# --- website data ------------------------------------------------------------


def _item(title, url, published=None, deadline=None):
    return g.Item("aade", title, url, published, deadline=deadline, categories=["tax_deadline"])


def test_merge_keeps_first_seen_and_drops_old():
    old = _item("Παλιό", "https://a/1", "2026-11-01")
    old.first_seen = "2026-11-01T08:00:00"
    stale = _item("Πολύ παλιό", "https://a/0", "2024-01-01")
    stale.first_seen = "2024-01-01T08:00:00"
    alive = _item("Παλιό πρόγραμμα, αιτήσεις έως 01/01/2027", "https://a/9", "2024-01-01", deadline="2027-01-01")
    alive.first_seen = "2024-01-01T08:00:00"
    again = _item("Παλιό", "https://a/1", "2026-11-01")
    new = _item("Νέο", "https://a/2", "2026-11-10")

    merged = g.merge_history([asdict(old), asdict(stale), asdict(alive)], [again, new], 365, "2026-11-11T08:00:00")
    by_url = {i.url: i for i in merged}
    assert set(by_url) == {"https://a/1", "https://a/2", "https://a/9"}
    assert by_url["https://a/1"].first_seen == "2026-11-01T08:00:00"
    assert by_url["https://a/2"].first_seen == "2026-11-11T08:00:00"
    assert merged[0].url == "https://a/2"  # newest first


def test_write_site_data(tmp_path):
    items = [g.enrich(_item("Παράταση προθεσμίας ΕΝΦΙΑ έως 30/11/2026", "https://a/1", "2026-11-10"))]
    srcs = [{"name": "aade", "label": "ΑΑΔΕ", "url": "https://www.aade.gr"}]
    g.write_site_data(items, tmp_path, srcs, {"aade": {"ok": True, "found": 1, "kept": 1}}, 365, "https://x")
    for f in ["items.json", "meta.json", "feed.xml"]:
        assert (tmp_path / f).stat().st_size > 0


def test_old_calendar_file_is_removed(tmp_path):
    # the site no longer offers a calendar; the next collection deletes the stale file from data/
    (tmp_path / "deadlines.ics").write_text("BEGIN:VCALENDAR", encoding="utf-8")
    g.write_site_data([], tmp_path, [], {}, 365, "https://x")
    assert not (tmp_path / "deadlines.ics").exists()
