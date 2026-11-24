# Κύρβεις (Kyrbeis)

> *In ancient Athens, laws were written on wooden tablets called **kyrbeis** and set up in public for everyone to read. Kyrbeis does the same for today's Greek public announcements.*

**Tax deadlines, subsidies and funding programs from 15 Greek government sources, collected every morning into one searchable, bilingual website.**

[![Tests](https://github.com/ThanosTheodorakis/kyrbeis/actions/workflows/ci.yml/badge.svg)](https://github.com/ThanosTheodorakis/kyrbeis/actions/workflows/ci.yml)
[![Deploy](https://github.com/ThanosTheodorakis/kyrbeis/actions/workflows/update.yml/badge.svg)](https://github.com/ThanosTheodorakis/kyrbeis/actions/workflows/update.yml)

**Live site:** https://thanostheodorakis.github.io/kyrbeis/

[![Kyrbeis: the 60-day deadline timeline and today's announcements](docs/screenshot.png)](https://thanostheodorakis.github.io/kyrbeis/)

## The problem

What Greek citizens and small businesses need to act on is spread across many sites. Tax deadlines are on AADE, new benefits on OPEKA, payment dates on e-EFKA, and funding calls with ministries and the Development Bank. Each site has its own layout, and none of them answers the simple question *what's due soon, and what's open to me?* Missing a deadline can mean a fine; missing a call can mean missing funding.

## What it does

- **Collects** announcements every morning from AADE, e-EFKA, DYPA, OPEKA, six ministries (Finance, Development, Labour, Environment & Energy, Social Cohesion, Rural Development), the Hellenic Development Bank, IKY (state scholarships), HFRI/ΕΛΙΔΕΚ (research grants), the Prime Minister's office and the Diavgeia open-data API. It reads RSS feeds and the API where they exist, and web pages otherwise.
- **Understands Greek announcements.** It tags each one by topic (taxes, subsidies, programs) and by audience (households, businesses, employees, pensioners, farmers). It also pulls the deadline out of free text like «αιτήσεις έως 30 Νοεμβρίου» and tells real opportunities apart from news (see *How the classifier works*).
- **Publishes a static website** with:
  - a 60-day deadline timeline, the next seven days highlighted
  - search and filters by topic, audience, deadline status, publication date and agency, kept in the URL so a filtered view can be shared
  - Greek and English, dark mode, a phone layout
  - an RSS feed
  - a source-health panel showing which sites answered on the last run

## How it works

```mermaid
flowchart LR
    subgraph PC[Computer in Greece · Docker]
      A[runner, every morning] --> B[Python scraper]
      B --> D[classify + extract deadlines]
      D --> E[merge into data/items.json<br/>rolling 1-year history]
    end
    B -->|RSS / HTML / JSON API| C[(15 government sources)]
    E -->|git push| G[GitHub repository]
    G -->|push triggers deploy| H[GitHub Pages<br/>static site]
    H --> V[visitors]
```

Collecting and publishing are split on purpose:

- **A computer in Greece collects.** A self-scheduling Docker container keeps a clone of the repository. Every morning it pulls the latest code, scrapes from a Greek connection, and commits and pushes the new data. Government sites see an ordinary Greek visitor, not a data centre abroad. If the computer was off or asleep at the scheduled time, it catches up when it's back.
- **GitHub publishes.** Each push of `data/` deploys the static site to GitHub Pages. Hosting is free, and if the computer is off, the site stays up with the last data. The git history doubles as a day-by-day archive.

## How the classifier works

Government headlines are short, formulaic Greek, so classification is rule-based rather than an LLM: free, fast, the same answer every run, and every decision traceable to a specific rule. The hard part is that the same words mean different things:

> «Αιτήσεις για το **πρόγραμμα** κατάρτισης **έως 30/11**» → a program, deadline 30 Nov
> «Το **πρόγραμμα** του Προέδρου της Δημοκρατίας από 22/11 **έως 25/11**» → news: a schedule, no deadline

Each announcement goes through four steps:

1. **Normalise.** Lower-case it and strip accents, so «Πρόγραμμα», «ΠΡΟΓΡΑΜΜΑ» and «προγραμμα» match alike. Words match at their start, so «δόση» never matches «έκδοση».
2. **Rewrite phrases whose meaning depends on context:**
   - «το πρόγραμμα του Πρωθυπουργού» becomes an agenda marker
   - «δηλώσεις του Υπουργού» means statements, not tax returns
   - «εκδήλωση ενδιαφέροντος» means applying, not an event
3. **Weigh the signals:**
   - unambiguous topic words (επίδομα, ΕΝΦΙΑ, αιτήσεις)
   - ambiguous ones (πρόγραμμα, ενίσχυση, επιστροφή)
   - action words (υποβολή, πληρωμή, δικαιούχοι, or a euro amount)
   - event words (visits, meetings, statements, conferences, court notices, outages)

   Ambiguous words only count in announcements that offer or ask for something and aren't events.
4. **Find the deadline:**
   - a date after «έως/μέχρι» or «προθεσμία», but only when the reader has to act: «πληρωμές 23 έως 27/11» is when the state pays, not a deadline
   - on a παράταση (extension), the new date
   - dates without a year resolve forward from publication, unless the text is in the past tense («ολοκληρώθηκε… έως 25 Σεπτεμβρίου»)

Every misclassification found on the live site becomes a regression test built from the real headline, so it can't come back.

## Design decisions

| Decision | Why |
|---|---|
| Static site, no backend | Free hosting, nothing to keep alive, data versioned in git |
| Collect in Greece, publish on GitHub | Requests come from a Greek connection; the public site never depends on that computer being on |
| Self-scheduling Docker collector | Runs on any machine with one command, catches up after downtime, restarts after a reboot, and only makes outgoing connections |
| Fine-grained token for pushes | The container can write to this one repository and nothing else |
| One failing source doesn't fail the run | Government sites are often slow or down. The run only fails if *every* source fails |
| Byte-stable output files | Unchanged announcements produce identical files, so quiet days make tiny commits |
| Polite fetching | Honours robots.txt and Crawl-delay, rate-limits per host, retries only errors that can clear, and identifies itself with a contact link. It never pretends to be a browser to get past a block |
| All dates in Europe/Athens | Dates near midnight stay correct whatever time zone the machine or GitHub's servers use |
| Vanilla JS, no build step | Loads fast; the whole front end is three readable files |
| Cross-platform | Tests run on Windows, macOS and Linux in CI, and every file is read and written as UTF-8 |

## Tech stack

**Scraper:** Python 3.11+, requests, BeautifulSoup, lxml  
**Front end:** HTML, CSS, vanilla JavaScript  
**Collection:** Docker, git  
**CI/CD:** GitHub Actions: pytest on Windows, macOS and Linux, ruff, Docker build checks, and deploy to GitHub Pages  
**Output formats:** JSON, RSS 2.0

## Development

```bash
git clone https://github.com/ThanosTheodorakis/kyrbeis.git && cd kyrbeis
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest                                              # offline test suite, ~200 tests
python -m scraper.gov_scraper --site-data data      # scrape into data/
python -m scraper.gov_scraper --only aade -v        # one source, verbose
python scripts/serve.py                             # preview at http://localhost:8000
```

Sources are configured in [`scraper/sources.json`](scraper/sources.json) without code changes. A source can be an RSS feed, an HTML page (CSS selectors or a headline-detection fallback), a feed with HTML fallback, or a Diavgeia API search. The classifier's word lists (`CATEGORIES`, `CATEGORY_HINTS`, `ACTION`, `EVENT`) are in [`scraper/gov_scraper.py`](scraper/gov_scraper.py).

## Operations

The collector runs in Docker on my computer. It reads `REPO_URL`, `GITHUB_TOKEN` and `RUN_AT` from a local `.env`, which is never committed (see `.env.example`).

| To | Run |
|---|---|
| Start, or apply changes to the collector | `docker compose up -d --build` |
| Watch it | `docker compose logs -f` |
| Collect right now | `docker compose run --rm kyrbeis once` |
| Stop it | `docker compose down` |

Scraper and site changes need no rebuild: the container pulls the latest code before each run, and a push redeploys the site. The *Deploy site* workflow can also scrape from GitHub when run by hand ("Also run the scraper here"), as a fallback if the computer is away for a while.

## Limitations

- **Rules miss things.** Classification is rule-based, so an unusual phrasing can still be misfiled; each fix adds a rule and a regression test.
- **Redesigns break HTML sources.** A site redesign breaks its HTML scraping. The source-health panel shows it, and the fix is usually one CSS selector.
- **Some sources are switched off.** ESPA resets automated connections, the Recovery Fund site doesn't finish loading, and ELGA's TLS certificate fails verification. The scraper doesn't disguise itself or turn off certificate checks to get around problems like these. The site lists these sources as unavailable, with the reason.
- **Collection needs the computer.** It depends on the collecting computer being on with internet. Missed days are caught up and the site stays online meanwhile.

## Roadmap

- Email or Telegram alerts for new items matching a saved search
- An LLM second opinion for the few announcements the rules can't decide
- Per-item pages with the full text and attachments

## Disclaimer

This is an unofficial project. Information is collected automatically and may be incomplete or wrong. Always check the official announcement before acting on it.

## License

[MIT](LICENSE)
