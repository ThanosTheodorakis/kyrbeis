"""Regression tests for issues found in code review. Offline: HTTP is faked."""

import dataclasses
import json
from datetime import date, datetime
from pathlib import Path

import pytest
import requests

from scraper import gov_scraper as g

PUB = date(2026, 11, 10)


# --- deadlines ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Παράταση προθεσμίας από 30/11/2026 έως 31/12/2026",
        "Παράταση της προθεσμίας υποβολής, που έληγε 30/11/2026, έως 31/12/2026",
        "Παρατείνεται έως 31 Δεκεμβρίου 2026 η προθεσμία που έληγε στις 30 Νοεμβρίου 2026",
    ],
)
def test_extension_takes_the_new_deadline(text):
    assert g.find_deadline(text, PUB) == date(2026, 12, 31)


def test_start_date_after_apo_is_not_the_deadline():
    assert g.find_deadline("Αιτήσεις από 1/12/2026 έως 31/12/2026", PUB) == date(2026, 12, 31)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Υποβολή αιτήσεων έως 30 Νοεμβρίου", date(2026, 11, 30)),
        ("μέχρι 15/12 οι δηλώσεις", date(2026, 12, 15)),
        ("Αιτήσεις έως 10 Ιαν.", date(2027, 1, 10)),  # already past this year -> next year
        ("προθεσμία έως 5.1", date(2027, 1, 5)),
    ],
)
def test_dates_without_a_year(text, expected):
    assert g.find_deadline(text, PUB) == expected


def test_year_less_dates_dont_double_count_dated_ones():
    assert [d for _, d in g.find_dates("έως 30 Νοε. 2026", PUB)] == [date(2026, 11, 30)]


def test_amounts_are_not_dates():
    assert g.find_deadline("Ενίσχυση έως 1.000 ευρώ και έως 25% της δαπάνης", PUB) is None


def test_cue_inside_another_word_is_ignored():
    # «ανανέωσης» contains «εωσ»
    assert g.find_deadline("Ανανέωσης αδειών 20/12/2026", PUB) is None


# --- keywords ----------------------------------------------------------------


@pytest.mark.parametrize("text", ["Έκδοση νέου διαβατηρίου", "Απόδοση του έργου", "Αλλαγή password στο Taxisnet"])
def test_keywords_dont_match_inside_words(text):
    assert g.categorize(text) == []


def test_keywords_still_match_inflected_forms():
    assert "tax_deadline" in g.categorize("Πληρωμή της 4ης δόσης")
    assert "subsidy" in g.categorize("Νέες επιδοτήσεις για αγρότες")
    assert "subsidy" in g.categorize("Ξεκινά το Fuel Pass")


# --- HTML fallback -----------------------------------------------------------

LIST = """<html><body><main><ul>
<li><span>10/11/2026</span> <a href="/a/1">Πρώτη ανακοίνωση με αρκετά μεγάλο τίτλο εδώ</a></li>
<li><a href="/a/2">Δεύτερη ανακοίνωση χωρίς δική της ημερομηνία</a></li>
<li><a href="/a/3">Παράταση προθεσμίας υποβολής ΦΠΑ έως 30/11/2026</a></li>
<li><a href="javascript:void(0)">Εκτύπωση αυτής της σελίδας με μεγάλο κείμενο</a></li>
<li><a href="#top">Επιστροφή στην αρχή της σελίδας παρακαλώ πολύ</a></li>
<li><a href="/news#comments">Σχόλια σε αυτή τη σελίδα, πατήστε εδώ για όλα</a></li>
<li><a href="mailto:info@example.gr">Επικοινωνήστε μαζί μας μέσω ηλεκτρονικού ταχυδρομείου</a></li>
</ul></main></body></html>"""


def _parsed():
    return {i.url: i for i in g.parse_html(LIST, "aade", "https://www.aade.gr/news", {})}


def test_undated_item_does_not_borrow_neighbours_date():
    assert _parsed()["https://www.aade.gr/a/2"].published is None


def test_deadline_in_title_is_not_the_published_date():
    item = _parsed()["https://www.aade.gr/a/3"]
    assert item.published is None
    assert g.enrich(item).deadline == "2026-11-30"


def test_non_announcement_links_are_dropped():
    assert set(_parsed()) == {f"https://www.aade.gr/a/{n}" for n in (1, 2, 3)}


def test_future_published_date_is_discarded(monkeypatch):
    monkeypatch.setattr(g, "today_local", lambda: PUB)
    item = g.enrich(g.Item("x", "Ανακοίνωση", "https://e.gr/1", published="2026-12-01"))
    assert item.published is None


def test_feed_rejects_unsafe_links():
    rss = b"""<rss><channel>
    <item><title>Bad</title><link>javascript:alert(1)</link></item>
    <item><title>Good</title><link>https://e.gr/ok#x</link></item></channel></rss>"""
    assert [i.url for i in g.parse_feed(rss, "s", "https://e.gr/")] == ["https://e.gr/ok"]


@pytest.mark.parametrize("href", ["javascript:alert(1)", "mailto:a@b.gr", "data:text/html,x", "#top", " JAVASCRIPT:x"])
def test_safe_url_rejects(href):
    assert g.safe_url(href, "https://e.gr/page") in (None, "https://e.gr/page")


# --- time zones --------------------------------------------------------------


@pytest.mark.parametrize("raw", ["2026-11-09T23:30:00Z", "Mon, 09 Nov 2026 23:30:00 +0000"])
def test_feed_dates_are_athens_dates(raw):
    assert g._parse_any_date(raw) == date(2026, 11, 10)


def _site(tmp_path, items):
    srcs = [{"name": "aade", "label": "ΑΑΔΕ", "url": "https://www.aade.gr"}]
    return g.write_site_data(items, tmp_path, srcs, {"aade": {"ok": True, "found": 1, "kept": 1}}, 365, "https://x")


def _items():
    return [g.enrich(g.Item("aade", "Παράταση προθεσμίας ΕΝΦΙΑ έως 30/11/2026", "https://a/1", "2026-11-10"))]


def test_meta_updated_has_a_timezone(tmp_path):
    _site(tmp_path, _items())
    updated = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["updated"]
    assert datetime.fromisoformat(updated).utcoffset() is not None


def test_unchanged_items_give_identical_files(tmp_path):
    _site(tmp_path, _items())
    before = {f: (tmp_path / f).read_bytes() for f in ("items.json", "feed.xml")}
    _site(tmp_path, _items())  # a later run finding the same announcement
    after = {f: (tmp_path / f).read_bytes() for f in before}
    assert before == after
    assert "scraped_at" not in before["items.json"].decode()


# --- fetcher -----------------------------------------------------------------


class FakeSession:
    """Stands in for requests.Session: replies from a {url: [status, ...]} script."""

    def __init__(self, script, robots="User-agent: *\nAllow: /\n"):
        self.script = {k: list(v) for k, v in script.items()}
        self.robots = robots
        self.calls: list[str] = []
        self.headers: dict = {}

    def get(self, url, **kw):
        self.calls.append(url)
        r = requests.Response()
        r.url = url
        r.encoding = "utf-8"
        if url.endswith("/robots.txt"):
            r.status_code, r._content = (200, self.robots.encode()) if self.robots else (404, b"")
            return r
        step = self.script[url].pop(0)
        if isinstance(step, Exception):
            raise step
        r.status_code, r._content = step, b"<html></html>"
        return r


@pytest.fixture
def fetcher(monkeypatch):
    monkeypatch.setattr(g.time, "sleep", lambda s: None)

    def make(script, **kw):
        f = g.Fetcher(contact="https://github.com/me/repo/issues", delay=0)
        f.s = FakeSession(script, **kw)
        return f

    return make


def test_404_is_not_retried(fetcher):
    f = fetcher({"https://e.gr/x": [404, 200]})
    with pytest.raises(requests.HTTPError):
        f.get("https://e.gr/x")
    assert f.s.calls.count("https://e.gr/x") == 1


@pytest.mark.parametrize("first", [503, 429, requests.ConnectionError("reset")])
def test_temporary_errors_are_retried(fetcher, first):
    f = fetcher({"https://e.gr/x": [first, 200]})
    assert f.get("https://e.gr/x").status_code == 200


def test_robots_disallow_is_respected(fetcher):
    f = fetcher({"https://e.gr/private/x": [200]}, robots="User-agent: *\nDisallow: /private/\n")
    with pytest.raises(g.BlockedByRobots):
        f.get("https://e.gr/private/x")
    assert "https://e.gr/private/x" not in f.s.calls


def test_missing_robots_allows_everything(fetcher):
    f = fetcher({"https://e.gr/x": [200]}, robots="")
    assert f.get("https://e.gr/x").ok


def test_user_agent_has_contact():
    assert "github.com/me/repo" in g.Fetcher(contact="https://github.com/me/repo/issues").agent


def test_one_failing_page_keeps_the_others(fetcher):
    page1 = (
        '<main><div><span>10/11/2026</span><a href="/a/1">Νέα επιδότηση για όλες τις μικρές επιχειρήσεις</a></div>'
        "</main>"
    )
    f = fetcher({"https://e.gr/list": [200], "https://e.gr/list?page=1": [404]})
    f.s.get_orig = f.s.get

    def get(url, **kw):
        r = f.s.get_orig(url, **kw)
        if url == "https://e.gr/list":
            r._content = page1.encode()
        return r

    f.s.get = get
    src = {"name": "s", "type": "html", "url": "https://e.gr/list", "extra_pages": ["https://e.gr/list?page=1"]}
    items, errors = g.scrape_source(f, src, PUB)
    assert [i.url for i in items] == ["https://e.gr/a/1"]
    assert len(errors) == 1


def test_all_pages_failing_raises(fetcher):
    f = fetcher({"https://e.gr/list": [404]})
    with pytest.raises(RuntimeError):
        g.scrape_source(f, {"name": "s", "type": "html", "url": "https://e.gr/list"}, PUB)


# --- local preview server ----------------------------------------------------


def test_serve_refuses_paths_outside_data():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("serve", Path(__file__).parent.parent / "scripts" / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)
    h = serve.Handler.__new__(serve.Handler)
    h.directory = str(serve.SITE)
    assert h.translate_path("/data/items.json") == str((serve.DATA / "items.json").resolve())
    for bad in ("/data/../README.md", "/data/%2e%2e/%2e%2e/etc/passwd"):
        assert h.translate_path(bad).endswith("__not_found__")


# --- found in the first live run (11 Nov 2026) --------------------------------


def test_past_yearless_date_is_not_pushed_to_next_year():
    text = "Πληρώθηκε η προκαταβολή… για όσους υπέβαλαν αίτηση έως τις 25 Σεπτεμβρίου"
    assert g.find_dates(text, date(2026, 11, 1))[0][1] == date(2026, 9, 25)
    assert g.find_deadline(text, date(2026, 11, 1)) is None  # before publication -> dropped


def test_until_cue_followed_by_a_number_is_not_a_deadline():
    item = g.Item(
        "aade",
        "Ρύθμιση οφειλών με δυνατότητα εξόφλησης σε έως 72 δόσεις",
        "https://www.aade.gr/1",
        "2026-10-16",
        summary="16 Οκτ 2026 Ρύθμιση οφειλών με δυνατότητα εξόφλησης σε έως 72 δόσεις",
    )
    assert g.enrich(item).deadline is None


def test_deadline_is_not_taken_across_title_and_summary():
    item = g.Item("x", "Νέο πρόγραμμα, αιτήσεις έως", "https://e.gr/1", "2026-11-01", summary="20/11/2026 ανακοίνωση")
    assert g.enrich(item).deadline is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Αιτήσεις έως και την Παρασκευή 20 Νοεμβρίου", date(2026, 11, 20)),
        ("Η προθεσμία λήγει στις 30/11/2026", date(2026, 11, 30)),
        ("Καταληκτική ημερομηνία υποβολής: 15/12/2026", date(2026, 12, 15)),
        ("έως 72 δόσεις, με πρώτη δόση 30/11/2026", None),
    ],
)
def test_date_must_follow_the_cue_closely(text, expected):
    assert g.find_deadline(text, date(2026, 11, 1)) == expected


@pytest.mark.parametrize(
    "summary,title,expected",
    [
        ("16 Οκτ 2026 Ρύθμιση οφειλών σε 72 δόσεις", "Ρύθμιση οφειλών σε 72 δόσεις", ""),
        ("10/11/2026", "Οτιδήποτε", ""),
        ("16 Οκτ 2026 Νέα πλατφόρμα για τους δικαιούχους", "Τίτλος", "Νέα πλατφόρμα για τους δικαιούχους"),
        ("50 εργαζόμενοι παίρνουν ενίσχυση", "Τίτλος", "50 εργαζόμενοι παίρνουν ενίσχυση"),
    ],
)
def test_summary_without_repeated_title_or_date(summary, title, expected):
    assert g.clean_summary(summary, title) == expected


def _run(tmp_path, monkeypatch, sources, results):
    """Run main() in --site-data mode with scrape_source faked per source name."""
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    monkeypatch.setattr(g, "scrape_source", lambda f, src, since: (results[src["name"]], []))
    code = g.main(["--config", str(cfg), "--site-data", str(tmp_path / "data"), "--contact", "x@example.com"])
    meta = json.loads((tmp_path / "data" / "meta.json").read_text(encoding="utf-8"))
    items = json.loads((tmp_path / "data" / "items.json").read_text(encoding="utf-8"))
    return code, {s["name"]: s for s in meta["sources"]}, items


def _post(source, title, published=None):
    return g.Item(source, title, f"https://e.gr/{abs(hash(title))}", published)


def test_zero_items_is_reported_as_a_failure(tmp_path, monkeypatch):
    today = g.today_local().isoformat()
    code, status, _ = _run(
        tmp_path,
        monkeypatch,
        [{"name": "efka", "type": "html", "url": "u"}, {"name": "aade", "type": "html", "url": "u", "keep_all": True}],
        {"efka": [], "aade": [_post("aade", "Νέα επιδότηση για όλους", today)]},
    )
    assert status["efka"]["ok"] is False and "0 items" in status["efka"]["error"]
    assert status["aade"]["ok"] is True
    assert code == 0  # one source failing doesn't fail the run


def test_zero_items_is_fine_when_not_expected(tmp_path, monkeypatch):
    _, status, _ = _run(
        tmp_path, monkeypatch, [{"name": "diavgeia", "type": "diavgeia", "expect_items": False}], {"diavgeia": []}
    )
    assert status["diavgeia"]["ok"] is True


def test_require_date_drops_menu_links(tmp_path, monkeypatch):
    today = g.today_local().isoformat()
    posts = [_post("dypa", "Εγγραφή στο μητρώο ανέργων"), _post("dypa", "Νέο πρόγραμμα απασχόλησης νέων", today)]
    _, _, items = _run(
        tmp_path, monkeypatch, [{"name": "dypa", "type": "html", "url": "u", "require_date": True}], {"dypa": posts}
    )
    assert [i["title"] for i in items] == ["Νέο πρόγραμμα απασχόλησης νέων"]


def test_disabled_source_is_shown_as_unavailable(tmp_path, monkeypatch):
    today = g.today_local().isoformat()
    _, status, _ = _run(
        tmp_path,
        monkeypatch,
        [
            {"name": "aade", "type": "html", "url": "u", "keep_all": True},
            {"name": "espa_calls", "type": "html", "url": "u", "enabled": False, "note": "connection reset"},
        ],
        {"aade": [_post("aade", "Νέα επιδότηση για όλους", today)]},
    )
    assert status["espa_calls"] == {**status["espa_calls"], "ok": False, "disabled": True, "error": "connection reset"}


def test_history_is_corrected_by_new_rules():
    """A wrong deadline saved by an older version must not survive the next run."""
    old = g.Item(
        "aade", "Ρύθμιση οφειλών σε έως 72 δόσεις", "https://www.aade.gr/1", "2026-10-16", deadline="2026-10-16"
    )
    old.first_seen = "2026-10-16T08:00:00"
    fresh = g.enrich(g.Item("aade", "Ρύθμιση οφειλών σε έως 72 δόσεις", "https://www.aade.gr/1", "2026-10-16"))
    for run in ([], [fresh]):  # item gone from the page, or still there
        merged = g.merge_history([dataclasses.asdict(old)], run, 365, "2026-11-11T08:00:00")
        assert merged[0].deadline is None
        assert merged[0].first_seen == "2026-10-16T08:00:00"


# --- found in the second live run (23 Nov 2026) ------------------------------


def test_links_on_a_redirected_site_are_kept(fetcher):
    """efka.gov.gr redirects to e-efka.gov.gr; links there are the site's own, not external."""
    page = (
        "<main><div><span>20/11/2026</span>"
        '<a href="https://www.e-efka.gov.gr/el/anakoinoseis/1">Καταβολή εισφορών μη μισθωτών έως 30/11/2026</a></div>'
        "</main>"
    )
    f = fetcher({"https://www.efka.gov.gr/": [200]})
    orig = f.s.get

    def get(url, **kw):
        r = orig(url, **kw)
        if url == "https://www.efka.gov.gr/":
            r._content, r.url = page.encode(), "https://www.e-efka.gov.gr/el"
        return r

    f.s.get = get
    items, _ = g.scrape_source(f, {"name": "efka", "type": "html", "url": "https://www.efka.gov.gr/"}, PUB)
    assert [i.url for i in items] == ["https://www.e-efka.gov.gr/el/anakoinoseis/1"]


def test_robots_redirect_to_html_page_means_no_robots(fetcher):
    f = fetcher({"https://e.gr/x": [200]}, robots="<html><body>Αρχική σελίδα</body></html>")
    orig = f.s.get

    def get(url, **kw):
        r = orig(url, **kw)
        if url.endswith("/robots.txt"):
            r.url = "https://e.gr/el"  # robots.txt redirected to the home page
        return r

    f.s.get = get
    assert f._robots_for("https://e.gr/x") is None
    assert f.get("https://e.gr/x").ok


EFKA_HOME = (Path(__file__).parent / "fixtures" / "efka_home.html").read_text(encoding="utf-8")


def _efka_config():
    cfg = json.loads((Path(__file__).parent.parent / "scraper" / "sources.json").read_text(encoding="utf-8"))
    return next(s for s in cfg["sources"] if s["name"] == "efka")


def test_efka_selectors_read_the_news_block():
    src = _efka_config()
    items = g.parse_html(EFKA_HOME, "efka", src["url"], src)
    assert [(i.title, i.published) for i in items] == [
        (
            "Νέες δυνατότητες αναλυτικής ενημέρωσης για τις ρυθμισμένες οφειλές "
            "στο Dashboard του Πολίτη από τον e-ΕΦΚΑ",
            "2026-11-11",
        ),
        ("Ημερομηνίες πληρωμής των συντάξεων μηνός Δεκεμβρίου 2026", "2026-11-10"),
        ("Επικοινωνία του κοινού με την Τοπική Διεύθυνση Λακωνίας", "2026-11-23"),
    ]
    assert items[0].url == "https://www.e-efka.gov.gr/el/deltia-typoy/deltio-typoy-430"


def test_fallback_searches_the_page_when_main_is_empty():
    items = g.parse_html(EFKA_HOME, "efka", "https://www.e-efka.gov.gr/el", {})
    urls = [i.url for i in items]
    assert "https://www.e-efka.gov.gr/el/deltia-typoy/deltio-typoy-430" in urls
    assert "https://www.e-efka.gov.gr/el/epikoinonia" not in urls  # footer/menu links are stripped


# --- found in the third live run (23 Nov 2026): mindev.gov.gr was down ---------


def test_unreachable_site_is_not_tried_again(fetcher):
    """mindev.gov.gr timed out: after the feed failed, the page fallback waited all over again."""
    down = requests.ConnectTimeout("timed out")
    f = fetcher({"https://e.gr/feed": [down, down, down], "https://e.gr/": [200]})
    with pytest.raises(RuntimeError):
        f.get("https://e.gr/feed")
    calls = len(f.s.calls)
    with pytest.raises(g.HostUnreachable):
        f.get("https://e.gr/")
    assert len(f.s.calls) == calls  # no new request to the dead host


def test_rss_or_html_fails_fast_when_the_site_is_down(fetcher):
    down = requests.ConnectTimeout("timed out")
    f = fetcher({"https://e.gr/feed/": [down, down, down], "https://e.gr/": [200]})
    src = {"name": "s", "type": "rss_or_html", "feed_url": "https://e.gr/feed/", "url": "https://e.gr/"}
    with pytest.raises(RuntimeError, match="unreachable earlier"):
        g.scrape_source(f, src, PUB)
    assert "https://e.gr/" not in f.s.calls


def test_slow_download_does_not_mark_the_site_down(fetcher):
    slow = requests.ReadTimeout("read timed out")
    f = fetcher({"https://e.gr/big": [slow, slow, slow], "https://e.gr/small": [200]})
    with pytest.raises(RuntimeError):
        f.get("https://e.gr/big")
    assert f.get("https://e.gr/small").ok


def test_connect_timeout_is_shorter_than_read_timeout():
    f = g.Fetcher()
    connect, read = f.timeout
    assert connect == 10 and read == 25


def test_sources_config_is_consistent():
    cfg = json.loads((Path(__file__).parent.parent / "scraper" / "sources.json").read_text(encoding="utf-8"))
    names = [s["name"] for s in cfg["sources"]]
    assert len(names) == len(set(names)), "source names must be unique"
    for s in cfg["sources"]:
        assert s["type"] in {"rss", "html", "rss_or_html", "diavgeia"}, s["name"]
        for key in ("url", "feed_url", "api"):
            if key in s:
                assert s[key].startswith("https://"), f"{s['name']}.{key}"
        if not s.get("enabled", True):
            assert s.get("note"), f"{s['name']} is switched off: say why in 'note'"


# --- audience tags (titles from the live runs) --------------------------------


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Ημερομηνίες πληρωμής των συντάξεων μηνός Δεκεμβρίου 2026", ["pensioners"]),
        ("Ηλεκτρονική Αίτηση Χορήγησης Επιδόματος Μητρότητας για εργαζόμενες", ["workers"]),
        ("Νέο πρόγραμμα επιδότησης για μικρομεσαίες επιχειρήσεις", ["businesses"]),
        ("ΑΑΔΕ: πληρωμή ενισχύσεων σε αγρότες και κτηνοτρόφους", ["farmers"]),
        ("Επίδομα παιδιού: πληρωμή της Α' δόσης", ["households"]),
        ("Εισφορές μη μισθωτών για ελεύθερους επαγγελματίες", ["businesses"]),
        ("Εισφορές μη μισθωτών – Υποχρεώσεις Ασφάλισης", ["businesses"]),  # self-employed, not workers
        ("Βεβαίωση προϋπηρεσίας μισθωτών", ["workers"]),
        ("1ο Βραβείο για τον e-ΕΦΚΑ στα Digital Gov Awards!", []),
    ],
)
def test_audiences(title, expected):
    assert g.audiences_for(title) == expected


def test_audience_keywords_respect_word_starts():
    assert "pensioners" not in g.audiences_for("Νέα σύνθεση της επιτροπής")
    assert "businesses" not in g.audiences_for("Ανακοίνωση για τα ΜΜΕ και τον Τύπο")


def test_enrich_sets_audiences_and_meta_counts(tmp_path):
    item = g.enrich(g.Item("efka", "Καταβολή συντάξεων Δεκεμβρίου", "https://e.gr/1", "2026-11-10"))
    assert item.audiences == ["pensioners"]
    srcs = [{"name": "efka", "label": "e-ΕΦΚΑ", "url": "https://e.gr"}]
    g.write_site_data([item], tmp_path, srcs, {"efka": {"ok": True, "found": 1, "kept": 1}}, 365, "https://x")
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["audience_counts"]["pensioners"] == 1
    saved = json.loads((tmp_path / "items.json").read_text(encoding="utf-8"))
    assert saved[0]["audiences"] == ["pensioners"]


# --- rename to Κύρβεις (23 Nov 2026) -------------------------------------------


def test_user_agent_and_outputs_use_the_new_name(tmp_path):
    assert g.Fetcher(contact="x@example.com").agent == "Kyrbeis/1.0 (+x@example.com)"
    items = [g.enrich(g.Item("aade", "Προθεσμία ΕΝΦΙΑ έως 30/11/2026", "https://a/1", "2026-11-10"))]
    srcs = [{"name": "aade", "label": "ΑΑΔΕ", "url": "https://www.aade.gr"}]
    g.write_site_data(items, tmp_path, srcs, {"aade": {"ok": True, "found": 1, "kept": 1}}, 365, "https://x")
    assert "<title>Κύρβεις</title>" in (tmp_path / "feed.xml").read_text(encoding="utf-8")


@pytest.mark.parametrize("var", ["KYRBEIS_CONTACT", "GOV_TRACKER_CONTACT"])
def test_contact_is_read_from_new_and_old_env_var(monkeypatch, tmp_path, var):
    monkeypatch.delenv("KYRBEIS_CONTACT", raising=False)
    monkeypatch.delenv("GOV_TRACKER_CONTACT", raising=False)
    monkeypatch.setenv(var, "me@example.com")
    seen = {}

    class FakeFetcher:
        def __init__(self, contact="", **kw):
            seen["contact"] = contact

    monkeypatch.setattr(g, "Fetcher", FakeFetcher)
    monkeypatch.setattr(g, "scrape_source", lambda f, src, since: ([], []))
    cfg = tmp_path / "sources.json"
    cfg.write_text(
        json.dumps({"sources": [{"name": "s", "type": "rss", "url": "u", "expect_items": False}]}), encoding="utf-8"
    )
    g.main(["--config", str(cfg), "--site-data", str(tmp_path / "data")])
    assert seen["contact"] == "me@example.com"


def test_status_links_go_to_websites_not_feeds(tmp_path):
    # the footer links people to each agency; a raw RSS feed or JSON API is useless to them
    srcs = [
        {"name": "dypa", "type": "rss", "url": "https://www.dypa.gov.gr/feed", "website": "https://www.dypa.gov.gr/"},
        {"name": "aade", "type": "html", "url": "https://www.aade.gr/deltia-typoy-anakoinoseis"},
    ]
    g.write_site_data([], tmp_path, srcs, {}, 365, "https://x")
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert [s["url"] for s in meta["sources"]] == [
        "https://www.dypa.gov.gr/",
        "https://www.aade.gr/deltia-typoy-anakoinoseis",
    ]


def test_every_feed_or_api_source_has_a_website():
    cfg = json.loads((Path(g.__file__).parent / "sources.json").read_text(encoding="utf-8"))
    for s in cfg["sources"]:
        link = s.get("url") or s.get("api")
        if s["type"] in ("rss", "diavgeia") or link.rstrip("/").endswith(("feed", ".json", ".xml")):
            assert s.get("website", "").startswith("https://"), s["name"]


# --- context: news and agendas are not programs or deadlines (24 Nov 2026) -----


@pytest.mark.parametrize(
    "title",
    [
        "Το πρόγραμμα του Προέδρου της Δημοκρατίας από 22/11 έως 25/11",
        "Δημόσιο πρόγραμμα του Πρωθυπουργού για την Τρίτη 25 Νοεμβρίου",
        "Το πρόγραμμα επισκέψεων του Υπουργού έως 28/11",
        "Επίσκεψη του Υπουργού στη Θεσσαλονίκη έως 25/11",
        "Συνέδριο για την ψηφιακή μετάβαση, 22 έως 25 Νοεμβρίου",
        "Ενίσχυση της συνεργασίας Ελλάδας – Κύπρου",
        "Επιστροφή του Πρωθυπουργού από τις Βρυξέλλες",
        "Δηλώσεις του Υπουργού Οικονομικών μετά τη συνάντηση έως 25/11",
        "Η πλατφόρμα θα είναι εκτός λειτουργίας έως 25/11",
    ],
)
def test_news_and_agendas_are_not_programs_or_deadlines(title):
    item = g.enrich(g.Item("x", title, "https://e.gr/1", "2026-11-20"))
    assert item.categories == []
    assert item.deadline is None


@pytest.mark.parametrize(
    "title,cat,deadline",
    [
        ("Εξοικονομώ: υποβολή αιτήσεων έως 15/12/2026", "program", "2026-12-15"),
        ("Πρόγραμμα απασχόλησης 5.000 ανέργων: αιτήσεις έως 10/12", "program", "2026-12-10"),
        ("Υποβολή αιτήσεων από 1/12 έως 15/12", "program", "2026-12-15"),
        ("Παράταση προθεσμίας υποβολής δηλώσεων ΦΠΑ έως 17/1/2027", "tax_deadline", "2027-01-17"),
        ("Ενίσχυση 250 ευρώ σε συνταξιούχους: πότε πληρώνεται", "subsidy", None),
        ("Δράση ενίσχυσης μικρομεσαίων με προϋπολογισμό 100 εκατ. ευρώ", "program", None),
        ("Εκδήλωση ενδιαφέροντος για το πρόγραμμα κατάρτισης έως 30/11", "program", "2026-11-30"),
        ("Ομιλία του Υπουργού για το νέο επίδομα θέρμανσης", "subsidy", None),
    ],
)
def test_real_opportunities_still_count(title, cat, deadline):
    item = g.enrich(g.Item("x", title, "https://e.gr/1", "2026-11-20"))
    assert cat in item.categories
    assert item.deadline == deadline


def test_summary_can_make_a_title_actionable():
    # the title alone ("Νέα δράση έως 15/12") is fine; a bare "Ψηφιακός μετασχηματισμός έως 15/12" needs the summary
    item = g.Item(
        "x",
        "Ψηφιακός μετασχηματισμός έως 15/12/2026",
        "https://e.gr/1",
        "2026-11-20",
        summary="Οι επιχειρήσεις υποβάλλουν αίτηση ηλεκτρονικά.",
    )
    item = g.enrich(item)
    assert item.deadline == "2026-12-15"
    assert "program" in item.categories


# real headlines from primeminister.gr, 21-23 Nov 2026: schedules, visits and statements
@pytest.mark.parametrize(
    "title",
    [
        "Πρόγραμμα του Πρωθυπουργού για αύριο, Δευτέρα 23 Νοεμβρίου 2026",
        "Ενημερωτικό σημείωμα για την επίσκεψη του Πρωθυπουργού στην έκθεση XENIA 2026",
        "Κοινό Ανακοινωθέν 4ης Διακυβερνητικής Συνόδου Ελλάδας-Κύπρου",
        "Δηλώσεις του Πρωθυπουργού μετά την ολοκλήρωση των εργασιών της 4ης Διακυβερνητικής Συνόδου",
    ],
)
def test_real_prime_minister_news_is_just_news(title):
    item = g.enrich(g.Item("primeminister", title, "https://e.gr/1", "2026-11-21"))
    assert (item.categories, item.deadline) == ([], None)


@pytest.mark.parametrize(
    "title,cat",
    [
        ("Κοινωφελής εργασία: τα οριστικά αποτελέσματα", "program"),
        ("Επιταγή ακρίβειας: πότε καταβάλλεται", "subsidy"),
        ("Αποτελέσματα του προγράμματος Ψηφιακός Μετασχηματισμός ΜμΕ", "program"),
        ("Πληρωμή επιδομάτων ΟΠΕΚΑ στις 27 Νοεμβρίου", "subsidy"),
        ("Οδηγός για τη φορολογική δήλωση 2026", "tax_deadline"),
    ],
)
def test_typical_opportunities_are_kept(title, cat):
    assert cat in g.categorize(title)


# --- from the live site, 24 Nov 2026 ------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        # statements by people
        "Βασιλική Παντελοπούλου: Ενίσχυση των πόρων της Πολιτικής Συνοχής για την πρόσβαση των δικαιούχων "
        "στην επόμενη Προγραμματική Περίοδο 2028-2034",
        "Δ. Μαρκόπουλος από τη Λάρισα: Αγώνας δρόμου για την πληρωμή των αγροτών – "
        "Καμία φορολογική υπηρεσία δεν κλείνει",
        # an event abroad
        "Το Σάββατο η νέα δράση Rebrain Greece στο Μόναχο",
        # a court notice about expropriation compensation
        "Ειδοποίηση για την συζήτηση αίτησης που προσδιορίστηκε να συζητηθεί την 01-03-2027 στο ακροατήριο "
        "του Μονομελούς Εφετείου Θεσσαλονίκης: Να καθοριστεί η αποζημίωση για τα ακίνητα που απαλλοτριώνονται",
        # a minister's appeal, not a call for applications
        "Ανοιχτή πρόσκληση Στ. Καλαφάτη στις επιχειρήσεις να γίνουν «πρώτοι πελάτες» των startups, "
        "παράλληλα με φορολογική υπερέκπτωση έως 315%",
    ],
)
def test_live_news_is_just_news(title):
    item = g.enrich(g.Item("x", title, "https://e.gr/1", "2026-11-20"))
    assert (item.categories, item.deadline) == ([], None)


def test_payment_calendar_is_not_a_deadline():
    # the state pays between 23 and 27/11; nobody has to do anything by the 27th
    item = g.enrich(
        g.Item(
            "x",
            "Ο «χάρτης» των πληρωμών από e-ΕΦΚΑ, ΔΥΠΑ για την περίοδο 23 έως 27 Νοεμβρίου",
            "https://e.gr/1",
            "2026-11-20",
        )
    )
    assert item.deadline is None


@pytest.mark.parametrize(
    "title,cats,deadline",
    [
        ("Πληρωμή ΕΝΦΙΑ: η τελευταία δόση έως 31/12", ["tax_deadline"], "2026-12-31"),
        ("Κοινωνικός Τουρισμός: αιτήσεις έως 15/12", ["program"], "2026-12-15"),
        ("ΥΚΟΙΣΟ: Στα 400 ευρώ, από 250, η ετήσια ενίσχυση για άτομα με αναπηρία", ["subsidy"], None),
        ("Προσωρινοί πίνακες δικαιούχων του προγράμματος «Νταντάδες της γειτονιάς»", ["program"], None),
    ],
)
def test_live_opportunities_are_kept(title, cats, deadline):
    item = g.enrich(g.Item("x", title, "https://e.gr/1", "2026-11-20"))
    assert (item.categories, item.deadline) == (cats, deadline)


def test_words_starting_with_a_keyword_dont_count():
    assert g.categorize("Ενίσχυση στην επόμενη Προγραμματική Περίοδο") == []  # not «πρόγραμμα»
    assert g.read_context("η αποτελεσματική αντιμετώπιση της βίας") == (False, False)  # not «αποτελέσματα»


def test_same_headline_twice_from_one_source_is_kept_once():
    t = "ΑΝΑΡΤΗΣΗ ΑΝΑΣΥΝΤΑΓΜΕΝΩΝ ΠΙΝΑΚΩΝ ΠΡΟΚΗΡΥΞΗΣ ΣΟΧ 1/2026"
    a = g.Item("efka", t, "https://e-efka.gov.gr/a", "2026-11-18")
    b = g.Item("efka", t, "https://e-efka.gov.gr/b", "2026-11-18")
    other_source = g.Item("aade", t, "https://aade.gr/c", "2026-11-18")
    kept = g.merge_history([], [a, b, other_source], 365, "2026-11-24T06:17:00+02:00")
    assert sorted(i.url for i in kept) == ["https://aade.gr/c", "https://e-efka.gov.gr/a"]


# --- year-less deadlines far ahead (24 Nov 2026) ------------------------------


@pytest.mark.parametrize(
    "published,text,expected",
    [
        # more than six months ahead: nearest-date resolution put these in the past and dropped them
        (date(2026, 2, 1), "Αιτήσεις έως 30 Σεπτεμβρίου", date(2026, 9, 30)),
        (date(2026, 1, 10), "Υποβολή αιτήσεων μέχρι 15/7", date(2026, 7, 15)),
        (date(2026, 3, 1), "Η προθεσμία λήγει στις 31 Δεκεμβρίου", date(2026, 12, 31)),
        # across the new year
        (date(2026, 11, 20), "Αιτήσεις έως 10 Ιανουαρίου", date(2027, 1, 10)),
        (date(2026, 12, 1), "Ρύθμιση οφειλών: αιτήσεις έως 31 Μαΐου", date(2027, 5, 31)),
    ],
)
def test_yearless_deadlines_resolve_forward(published, text, expected):
    assert g.find_deadline(text, published) == expected


@pytest.mark.parametrize(
    "published,text",
    [
        # a recent past reference stays in the past, so it is not a deadline
        (date(2026, 11, 1), "Πληρώθηκαν όσοι υπέβαλαν αίτηση έως τις 25 Σεπτεμβρίου"),
        (date(2027, 1, 2), "Πληρώθηκαν όσοι υπέβαλαν αίτηση έως τις 20 Δεκεμβρίου"),
    ],
)
def test_recent_past_reference_is_not_a_deadline(published, text):
    assert g.find_deadline(text, published) is None


def test_publication_dates_without_a_year_still_look_back():
    # a listing dated "20 Νοε" seen on 5 Jan is last November, not next
    assert [d for _, d in g.find_dates("20 Νοε", date(2027, 1, 5))] == [date(2026, 11, 20)]


# --- from the live site, 24 Nov 2026 (2) --------------------------------------


def test_past_tense_reference_is_not_a_deadline_next_year():
    # published 12 Nov; 25 Sep is 48 days back, and "Ολοκληρώθηκε" says it's over (was: "25 Σεπ, σε 305 ημέρες")
    item = g.enrich(
        g.Item(
            "aade",
            "Ολοκληρώθηκε η προκαταβολή στους κτηνοτρόφους με αίτηση έως τις 25 Σεπτεμβρίου",
            "https://e.gr/1",
            "2026-11-12",
        )
    )
    assert item.deadline is None


def test_was_extended_is_past_tense_but_the_new_date_is_ahead():
    assert g.find_deadline("Παρατάθηκε έως 30 Σεπτεμβρίου η προθεσμία υποβολής αιτήσεων", date(2026, 2, 1)) == date(
        2026, 9, 30
    )


@pytest.mark.parametrize(
    "title",
    [
        "Πρόγραμμα «Προσωπικός Βοηθός»: Παράταση υποβολής νέων αιτήσεων έως τις 12 Ιανουαρίου 2027",
        "Έως 19 Νοεμβρίου η προθεσμία υποβολής της ΕΑΕ 2026 για την χορήγηση προκαταβολής",
    ],
)
def test_extensions_and_deadlines_are_not_tax_by_themselves(title):
    item = g.enrich(g.Item("x", title, "https://e.gr/1", "2026-11-16"))
    assert "tax_deadline" not in item.categories
    assert item.categories  # but still a topic: program / subsidy
    assert item.deadline


def test_press_release_prefix_is_removed_from_titles():
    item = g.enrich(
        g.Item("aade", "Δελτίο Τύπου 20/11/2026 ΕΑΕ 2026: 500.000 οι αγρότες", "https://e.gr/1", "2026-11-20")
    )
    assert item.title == "ΕΑΕ 2026: 500.000 οι αγρότες"
    assert g.clean_title("Δελτίο Τύπου") == "Δελτίο Τύπου"  # nothing left: keep the original


# --- new sources: IKY, ELIDEK, ELGA, Ministry of Rural Development (24 Nov 2026) -------


@pytest.mark.parametrize(
    "title,cat,deadline",
    [
        ("Πρόγραμμα υποτροφιών ΙΚΥ για μεταπτυχιακές σπουδές: αιτήσεις έως 12/1/2027", "program", "2027-01-12"),
        ("Προκήρυξη υποτροφιών για υποψήφιους διδάκτορες", "program", None),
        ("Erasmus+: Πρόσκληση υποβολής προτάσεων για σχέδια κινητικότητας 2027", "program", None),
        ("ΕΛΓΑ: Πληρωμή αποζημιώσεων ύψους 18,3 εκατ. ευρώ σε 8.480 δικαιούχους", "subsidy", None),
    ],
)
def test_new_sources_headlines(title, cat, deadline):
    item = g.enrich(g.Item("iky", title, "https://e.gr/1", "2026-11-20"))
    assert cat in item.categories
    assert item.deadline == deadline


def test_new_sources_are_configured_with_a_fallback():
    cfg = json.loads((Path(g.__file__).parent / "sources.json").read_text(encoding="utf-8"))
    by_name = {s["name"]: s for s in cfg["sources"]}
    for name in ("iky", "elidek", "elga", "minagric"):
        s = by_name[name]
        assert s["type"] == "rss_or_html" and s["feed_url"].startswith("https://") and s["url"].startswith("https://")
        assert s.get("require_date")  # the HTML fallback must not pick up menu links
