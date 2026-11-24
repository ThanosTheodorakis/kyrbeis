/* Κύρβεις (Kyrbeis) — static front end. Reads data/items.json + data/meta.json. */
(() => {
  "use strict";

  const DATA = "data/";
  const DAY = 864e5;
  const HORIZON = 60;
  const MAX_STACK = 5; // dots per day on the timeline; the rest collapse into "+N"
  const PAGE = 20; // announcements per "show more", so the footer stays within reach

  const T = {
    el: {
      skip: "Μετάβαση στα αποτελέσματα",
      title: "Τι λήγει, τι ανοίγει",
      lede: "Προθεσμίες, επιδοτήσεις και προγράμματα από ΑΑΔΕ, e-ΕΦΚΑ, ΟΠΕΚΑ, ΔΥΠΑ, υπουργεία και Διαύγεια, συγκεντρωμένα και ενημερωμένα κάθε πρωί.",
      horizon: "Οι επόμενες 60 ημέρες",
      today: "Σήμερα",
      week7: "Επόμενες 7 ημέρες",
      inMonth: n => n === 1 ? "1 προθεσμία" : `${n} προθεσμίες`,
      trackHint: "Κάθε κουκκίδα είναι μία προθεσμία. Πατήστε τη για να δείτε την ανακοίνωση.",
      trackHintScroll: "Σύρετε οριζόντια για τις επόμενες εβδομάδες.",
      search: "Αναζήτηση", searchPh: "Αναζήτηση, π.χ. ΕΝΦΙΑ, Εξοικονομώ",
      topic: "Θέμα", show: "Εμφάνιση", source: "Φορέας",
      audience: "Για ποιον",
      aud: { households: "Ιδιώτες & οικογένειες", businesses: "Επιχειρήσεις & ελ. επαγγελματίες",
        workers: "Εργαζόμενοι & άνεργοι", pensioners: "Συνταξιούχοι", farmers: "Αγρότες" },
      dueFilter: "Προθεσμία", dueAny: "Όλες οι ανακοινώσεις", dueOpen: "Με ανοιχτή προθεσμία",
      due7: "Λήγει σε 7 ημέρες", due30: "Λήγει σε 30 ημέρες",
      period: "Δημοσίευση", periodAny: "Οποτεδήποτε", period7: "Τελευταίες 7 ημέρες", period30: "Τελευταίες 30 ημέρες",
      sort: "Ταξινόμηση", sortPub: "Πιο πρόσφατα", sortDl: "Πλησιέστερη προθεσμία",
      reset: "Καθαρισμός φίλτρων", filters: "Φίλτρα",
      cat: { tax_deadline: "Φορολογικά & προθεσμίες", subsidy: "Επιδοτήσεις & ενισχύσεις", program: "Προγράμματα & προσκλήσεις", other: "Λοιπές ανακοινώσεις" },
      catShort: { tax_deadline: "Φορολογικά", subsidy: "Επιδότηση", program: "Πρόγραμμα", other: "Ανακοίνωση" },
      count: (n, t) => n === t ? `${n} ανακοινώσεις` : `${n} από ${t} ανακοινώσεις`,
      showN: n => n === 0 ? "Καμία ανακοίνωση" : n === 1 ? "Εμφάνιση 1 ανακοίνωσης" : `Εμφάνιση ${n} ανακοινώσεων`,
      activeFilters: n => n === 1 ? "1 ενεργό φίλτρο" : `${n} ενεργά φίλτρα`,
      updated: d => `Ενημερώθηκε ${d}`,
      neverUpdated: "Δεν έχει γίνει ακόμη ενημέρωση",
      published: "Δημοσίευση", noDate: "χωρίς ημερομηνία",
      due: "Λήξη", dueToday: "σήμερα", dueTomorrow: "αύριο", dueIn: n => `σε ${n} ημέρες`, duePast: "έληξε",
      isNew: "Νέο",
      nextUp: (t, n) => `Επόμενη προθεσμία: <strong>${t}</strong>, ${n}`,
      noneUpcoming: "Καμία γνωστή προθεσμία στις επόμενες 60 ημέρες.",
      emptyTrack: "Καμία προθεσμία σε αυτό το διάστημα με τα τρέχοντα φίλτρα.",
      moreOnDay: (n, d) => `Άλλες ${n} προθεσμίες στις ${d}`,
      timeline: "Χρονολόγιο προθεσμιών",
      emptyTitle: "Δεν βρέθηκαν ανακοινώσεις",
      emptyText: "Δοκιμάστε άλλη λέξη ή καθαρίστε τα φίλτρα.",
      noDataTitle: "Δεν υπάρχουν ακόμη δεδομένα",
      noDataText: "Η πρώτη συλλογή γίνεται με την επόμενη αυτόματη ενημέρωση. Ξαναδείτε σε λίγο.",
      loadError: "Τα δεδομένα δεν φορτώθηκαν. Ανανεώστε τη σελίδα.",
      more: n => `Εμφάνιση ${n} ακόμη`,
      jumpFoot: "Συνδρομή στο ημερολόγιο & κατάσταση πηγών",
      groupToday: "Σήμερα", groupYesterday: "Χθες", groupUndated: "Χωρίς ημερομηνία",
      groupDue: "Με προθεσμία", groupNoDue: "Χωρίς γνωστή προθεσμία",
      subscribe: "Πάρτε τις ενημερώσεις αλλού",
      subscribeText: "Προσθέστε όλες τις προθεσμίες στο ημερολόγιό σας ή ακολουθήστε τα νέα με RSS.",
      ics: "Συνδρομή στο ημερολόγιο", icsFile: "Λήψη αρχείου .ics", rss: "Ροή RSS",
      status: "Κατάσταση πηγών",
      stOk: n => `${n} βρέθηκαν`, stFail: "δεν απάντησε", stDisabled: "μη διαθέσιμη", stEmpty: "0 αποτελέσματα, πιθανή αλλαγή σελίδας", stPartial: n => `${n} βρέθηκαν, κάποιες σελίδες απέτυχαν`,
      disclaimer: "Ανεπίσημη υπηρεσία. Οι πληροφορίες συλλέγονται αυτόματα και μπορεί να περιέχουν λάθη. Ελέγχετε πάντα την επίσημη ανακοίνωση πριν από κάθε ενέργεια.",
      made: "Ο κώδικας στο GitHub",
      docTitle: "Κύρβεις — Προθεσμίες, επιδόματα και επιδοτήσεις του Δημοσίου",
      nameStory: "Στην αρχαία Αθήνα οι νόμοι γράφονταν σε ξύλινες πινακίδες, τις κύρβεις, και στήνονταν δημόσια για να τους διαβάζουν όλοι. Οι Κύρβεις κάνουν το ίδιο για τις σημερινές ανακοινώσεις του Δημοσίου.",
    },
    en: {
      skip: "Skip to results",
      title: "What's due, what's open",
      lede: "Deadlines, subsidies and programs from Greece's tax authority, social security and benefits agencies, ministries and the Diavgeia register, collected in one place every morning.",
      horizon: "The next 60 days",
      today: "Today",
      week7: "Next 7 days",
      inMonth: n => n === 1 ? "1 deadline" : `${n} deadlines`,
      trackHint: "Each dot is one deadline. Tap or click it to see the announcement.",
      trackHintScroll: "Swipe sideways for the weeks ahead.",
      search: "Search", searchPh: "Search, e.g. ENFIA, Exoikonomo",
      topic: "Topic", show: "Show", source: "Agency",
      audience: "Who it's for",
      aud: { households: "Individuals & families", businesses: "Businesses & self-employed",
        workers: "Employees & unemployed", pensioners: "Pensioners", farmers: "Farmers" },
      dueFilter: "Deadline", dueAny: "All announcements", dueOpen: "Open deadline",
      due7: "Due within 7 days", due30: "Due within 30 days",
      period: "Published", periodAny: "Any time", period7: "Last 7 days", period30: "Last 30 days",
      sort: "Sort by", sortPub: "Most recent", sortDl: "Nearest deadline",
      reset: "Clear filters", filters: "Filters",
      cat: { tax_deadline: "Tax & deadlines", subsidy: "Subsidies & grants", program: "Programs & calls", other: "Other notices" },
      catShort: { tax_deadline: "Tax", subsidy: "Subsidy", program: "Program", other: "Notice" },
      count: (n, t) => n === t ? `${n} announcements` : `${n} of ${t} announcements`,
      showN: n => n === 0 ? "No announcements" : n === 1 ? "Show 1 announcement" : `Show ${n} announcements`,
      activeFilters: n => n === 1 ? "1 active filter" : `${n} active filters`,
      updated: d => `Updated ${d}`,
      neverUpdated: "Not updated yet",
      published: "Published", noDate: "no date",
      due: "Due", dueToday: "today", dueTomorrow: "tomorrow", dueIn: n => `in ${n} days`, duePast: "closed",
      isNew: "New",
      nextUp: (t, n) => `Next deadline: <strong>${t}</strong>, ${n}`,
      noneUpcoming: "No known deadlines in the next 60 days.",
      emptyTrack: "No deadlines in this period with the current filters.",
      moreOnDay: (n, d) => `${n} more deadlines on ${d}`,
      timeline: "Deadline timeline",
      emptyTitle: "No announcements found",
      emptyText: "Try another word or clear the filters.",
      noDataTitle: "No data yet",
      noDataText: "The first collection happens with the next automatic update. Check back soon.",
      loadError: "The data didn't load. Refresh the page.",
      more: n => `Show ${n} more`,
      jumpFoot: "Calendar subscription & source status",
      groupToday: "Today", groupYesterday: "Yesterday", groupUndated: "Undated",
      groupDue: "With a deadline", groupNoDue: "No known deadline",
      subscribe: "Get updates elsewhere",
      subscribeText: "Add every deadline to your calendar, or follow new announcements by RSS.",
      ics: "Subscribe in your calendar", icsFile: "Download .ics file", rss: "RSS feed",
      status: "Source status",
      stOk: n => `${n} found`, stFail: "not responding", stDisabled: "unavailable", stEmpty: "0 results, page may have changed", stPartial: n => `${n} found, some pages failed`,
      disclaimer: "Unofficial service. Information is collected automatically and may contain mistakes. Always check the official announcement before acting on it.",
      made: "Source code on GitHub",
      docTitle: "Kyrbeis — Greek public deadlines, benefits and subsidies",
      nameStory: "In ancient Athens, laws were written on wooden tablets called kyrbeis and set up in public for everyone to read. Kyrbeis does the same for today's public announcements.",
    },
  };

  const SOURCE_EL = {
    aade: "ΑΑΔΕ", espa_calls: "ΕΣΠΑ, προσκλήσεις", espa_news: "ΕΣΠΑ, νέα",
    minfin: "Υπ. Οικονομικών", mindev: "Υπ. Ανάπτυξης", efka: "e-ΕΦΚΑ",
    dypa: "ΔΥΠΑ", primeminister: "Πρωθυπουργός", diavgeia: "Διαύγεια",
    opeka: "ΟΠΕΚΑ", ypergasias: "Υπ. Εργασίας", ypen: "Υπ. Περιβάλλοντος & Ενέργειας",
    hdb: "Αναπτυξιακή Τράπεζα", minscfa: "Υπ. Κοινωνικής Συνοχής", greece20: "Ταμείο Ανάκαμψης",
  };
  // nominative month names: toLocaleDateString gives the genitive ("Δεκεμβρίου") for el
  const MONTHS_EL = ["Ιανουάριος", "Φεβρουάριος", "Μάρτιος", "Απρίλιος", "Μάιος", "Ιούνιος",
    "Ιούλιος", "Αύγουστος", "Σεπτέμβριος", "Οκτώβριος", "Νοέμβριος", "Δεκέμβριος"];
  const SOURCE_EN = {
    aade: "AADE (tax authority)", espa_calls: "ESPA calls", espa_news: "ESPA news",
    minfin: "Ministry of Finance", mindev: "Ministry of Development", efka: "e-EFKA (social security)",
    dypa: "DYPA (employment)", primeminister: "Prime Minister", diavgeia: "Diavgeia",
    opeka: "OPEKA (benefits)", ypergasias: "Ministry of Labour", ypen: "Ministry of Environment & Energy",
    hdb: "Hellenic Development Bank", minscfa: "Ministry of Social Cohesion & Family", greece20: "Recovery Fund",
  };
  const CATS = ["tax_deadline", "subsidy", "program", "other"];
  const AUDS = ["households", "businesses", "workers", "pensioners", "farmers"];

  // ---------- state ----------
  const params = new URLSearchParams(location.search);
  const state = {
    lang: params.get("lang") === "en" ? "en" : "el",   // the site opens in Greek; ?lang=en opens it in English
    q: params.get("q") || "",
    cats: new Set((params.get("cat") || "").split(",").filter(Boolean)),
    srcs: new Set((params.get("src") || "").split(",").filter(Boolean)),
    aud: new Set((params.get("for") || "").split(",").filter(Boolean)),
    // older links used ?dl=1 ("only with a deadline") and ?new=1 ("only new")
    due: ["open", "7", "30"].includes(params.get("due")) ? params.get("due") : params.get("dl") === "1" ? "open" : "",
    period: ["7", "30"].includes(params.get("p")) ? params.get("p") : params.get("new") === "1" ? "7" : "",
    sort: params.get("sort") === "deadline" ? "deadline" : "published",
    shown: PAGE,
  };
  if (!T[state.lang]) state.lang = "el";

  let items = [], meta = null;
  const $ = s => document.querySelector(s);
  const t = k => T[state.lang][k];
  const today = startOfDay(new Date());

  function startOfDay(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
  function parseDay(iso) { if (!iso) return null; const [y, m, d] = iso.slice(0, 10).split("-").map(Number); return new Date(y, m - 1, d); }
  function daysUntil(iso) { return Math.round((parseDay(iso) - today) / DAY); }
  function primaryCat(it) { return it.categories && it.categories.length ? it.categories[0] : "other"; }
  function fmtDate(iso, opts = { day: "numeric", month: "long", year: "numeric" }) {
    return parseDay(iso).toLocaleDateString(state.lang === "el" ? "el-GR" : "en-GB", opts);
  }
  function relDue(n) {
    if (n < 0) return t("duePast");
    if (n === 0) return t("dueToday");
    if (n === 1) return t("dueTomorrow");
    return t("dueIn")(n);
  }
  function sourceLabel(name) {
    const short = (state.lang === "en" ? SOURCE_EN : SOURCE_EL)[name];
    if (short) return short;
    const s = meta && meta.sources.find(x => x.name === name);
    return (s && s.label) || name;
  }
  // only ever put http(s) URLs into href, whatever ends up in the data files
  const safeHref = u => (/^https?:\/\//i.test(u || "") ? u : null);
  const filtersActive = () => !!(state.q || state.cats.size || state.aud.size || state.srcs.size || state.due || state.period);
  const norm = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/ς/g, "σ");
  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids) if (c != null) n.append(c);
    return n;
  }

  // ---------- filtering ----------
  function matches(it) {
    if (state.cats.size) {
      const cs = it.categories && it.categories.length ? it.categories : ["other"];
      if (!cs.some(c => state.cats.has(c))) return false;
    }
    if (state.aud.size && !(it.audiences || []).some(a => state.aud.has(a))) return false;
    if (state.srcs.size && !state.srcs.has(it.source)) return false;
    if (state.due) {
      if (!it.deadline) return false;
      const n = daysUntil(it.deadline);
      if (n < 0 || (state.due !== "open" && n > Number(state.due))) return false;
    }
    if (state.period) {
      const d = parseDay(it.published || it.first_seen);
      if (!d || (today - d) / DAY > Number(state.period)) return false;
    }
    if (state.q) {
      const hay = it._hay || (it._hay = norm(`${it.title} ${it.summary} ${sourceLabel(it.source)}`));
      if (!norm(state.q).split(/\s+/).every(w => hay.includes(w))) return false;
    }
    return true;
  }

  function syncUrl() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.cats.size) p.set("cat", [...state.cats].join(","));
    if (state.srcs.size) p.set("src", [...state.srcs].join(","));
    if (state.aud.size) p.set("for", [...state.aud].join(","));
    if (state.due) p.set("due", state.due);
    if (state.period) p.set("p", state.period);
    if (state.sort !== "published") p.set("sort", state.sort);
    if (params.get("lang") || state.lang !== "el") p.set("lang", state.lang);
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  // ---------- rendering ----------
  function renderStatic() {
    document.documentElement.lang = state.lang;
    document.title = t("docTitle");
    document.querySelectorAll("[data-i18n]").forEach(n => { const v = t(n.dataset.i18n); if (typeof v === "string") n.textContent = v; });
    document.querySelectorAll("[data-i18n-ph]").forEach(n => { n.placeholder = t(n.dataset.i18nPh); });
    document.querySelectorAll("[data-i18n-label]").forEach(n => n.setAttribute("aria-label", t(n.dataset.i18nLabel)));
    document.querySelectorAll(".lang button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang)));
    $("#updated").textContent = meta && meta.updated
      ? t("updated")(new Date(meta.updated).toLocaleString(state.lang === "el" ? "el-GR" : "en-GB",
          { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }))
      : t("neverUpdated");
  }

  function renderFilters() {
    const cats = $("#cats"); cats.replaceChildren();
    for (const c of CATS) {
      const n = items.filter(it => (it.categories && it.categories.length ? it.categories : ["other"]).includes(c)).length;
      if (!n && c === "other") continue;
      const box = el("input", { type: "checkbox", value: c, checked: state.cats.has(c),
        onchange: e => { e.target.checked ? state.cats.add(c) : state.cats.delete(c); update(); } });
      cats.append(el("label", { class: "check" }, box,
        el("span", { class: "swatch", style: `--c: var(--${c === "tax_deadline" ? "tax" : c})` }),
        el("span", { text: t("cat")[c] }), el("span", { class: "n", text: String(n) })));
    }
    const auds = $("#auds"); auds.replaceChildren();
    for (const a of AUDS) {
      const n = items.filter(it => (it.audiences || []).includes(a)).length;
      if (!n) continue; // don't offer a choice that can only give an empty list
      const box = el("input", { type: "checkbox", value: a, checked: state.aud.has(a),
        onchange: e => { e.target.checked ? state.aud.add(a) : state.aud.delete(a); update(); } });
      auds.append(el("label", { class: "check" }, box, el("span", { text: t("aud")[a] }), el("span", { class: "n", text: String(n) })));
    }
    const srcs = $("#sources"); srcs.replaceChildren();
    const names = [...new Set(items.map(i => i.source))].sort((a, b) => sourceLabel(a).localeCompare(sourceLabel(b)));
    for (const s of names) {
      const n = items.filter(i => i.source === s).length;
      const box = el("input", { type: "checkbox", value: s, checked: state.srcs.has(s),
        onchange: e => { e.target.checked ? state.srcs.add(s) : state.srcs.delete(s); update(); } });
      srcs.append(el("label", { class: "check" }, box, el("span", { text: sourceLabel(s) }), el("span", { class: "n", text: String(n) })));
    }
    $("#q").value = state.q;
    $("#due").value = state.due;
    $("#period").value = state.period;
    $("#sort").value = state.sort;
  }

  // The 60-day timeline: one slot per day, months as shaded bands, a dated tick every Monday,
  // one dot per deadline stacked on its day. Narrow screens scroll it sideways rather than
  // squeezing 60 days into a few centimetres.
  const MIN_DAY_PX = 14;
  const tip = el("div", { class: "tip", hidden: true });
  document.body.append(tip);
  const hideTip = () => { tip.hidden = true; };
  addEventListener("scroll", hideTip, { passive: true });

  function renderHorizon() {
    const track = $("#track"); track.replaceChildren();
    const scroller = $("#track-scroll");
    const slots = HORIZON + 1;                      // today plus the next 60 days
    const cs = getComputedStyle(scroller);
    const room = (scroller.clientWidth || 800) - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const W = Math.max(room, slots * MIN_DAY_PX);
    track.style.width = `${W}px`;
    const slot = W / slots;
    const x = d => (d + .5) * slot;                 // centre of a day's slot
    const dayAt = d => new Date(today.getTime() + d * DAY);
    const short = d => dayAt(d).toLocaleDateString(state.lang === "el" ? "el-GR" : "en-GB", { day: "numeric", month: "short" });

    const upcoming = items
      .filter(it => it.deadline && matches(it))
      .map(it => ({ it, d: daysUntil(it.deadline) }))
      .filter(u => u.d >= 0 && u.d <= HORIZON)
      .sort((a, b) => a.d - b.d);

    // months as alternating bands, each with its name and how many deadlines fall in it
    let start = 0, band = 0;
    for (let d = 1; d <= slots; d++) {
      if (d === slots || dayAt(d).getDate() === 1) {
        const m = dayAt(start), w = (d - start) * slot;
        const n = upcoming.filter(u => u.d >= start && u.d < d).length;
        const name = state.lang === "el" ? MONTHS_EL[m.getMonth()] : m.toLocaleDateString("en-GB", { month: "long" });
        track.append(el("div", { class: `mband${band % 2 ? " alt" : ""}`, style: `left:${start * slot}px; width:${w}px` },
          w > 56 ? el("span", { class: "mname" }, el("b", { text: name }), el("span", { text: n ? t("inMonth")(n) : "" })) : ""));
        start = d; band++;
      }
    }
    // the next seven days
    track.append(el("div", { class: "urgent-zone", style: `width:${7 * slot}px` },
      7 * slot > 80 ? el("span", { text: t("week7") }) : ""));

    // the date scale: a tick per day, a labelled tick per Monday, "today" at the start
    track.append(el("div", { class: "axis" }));
    for (let d = 0; d <= HORIZON; d++) {
      const monday = dayAt(d).getDay() === 1;
      track.append(el("div", { class: `dtick${monday ? " wk" : ""}`, style: `left:${x(d)}px` }));
      // Monday dates, but not where they would collide with the wider "Today, 24 Nov" label
      if (monday && x(d) - x(0) > 118 && W - x(d) > 24) {
        track.append(el("div", { class: "dlabel", style: `left:${x(d)}px`, text: short(d) }));
      }
    }
    track.append(el("div", { class: "today", style: `left:${x(0) - 1}px` }));
    track.append(el("div", { class: "dlabel now", style: `left:${x(0)}px`, text: `${t("today")}, ${short(0)}` }));

    if (!upcoming.length) {
      // "with the current filters" only makes sense when filters are actually set
      const anyUpcoming = items.some(it => it.deadline && daysUntil(it.deadline) >= 0 && daysUntil(it.deadline) <= HORIZON);
      track.append(el("p", { class: "track-empty", style: `left:${7 * slot + 16}px`,
        text: anyUpcoming && filtersActive() ? t("emptyTrack") : t("noneUpcoming") }));
    }

    const showTip = (node, head, body) => {
      const open = () => {
        tip.replaceChildren(el("b", { text: head }), document.createTextNode(body));
        tip.hidden = false;
        const r = node.getBoundingClientRect(), tw = tip.offsetWidth, th = tip.offsetHeight;
        tip.style.left = `${Math.min(Math.max(8, r.left + r.width / 2 - 24), innerWidth - tw - 8)}px`;
        tip.style.top = `${r.top - th - 8 < 8 ? r.bottom + 8 : r.top - th - 8}px`;
      };
      node.addEventListener("mouseenter", open); node.addEventListener("focus", open);
      node.addEventListener("mouseleave", hideTip); node.addEventListener("blur", hideTip);
    };
    const AXIS = 34, STEP = 15;
    const bottom = level => `${AXIS - 6 + (level - 1) * STEP}px`;

    const byDay = new Map();
    for (const u of upcoming) byDay.set(u.d, [...(byDay.get(u.d) || []), u]);
    for (const [d, group] of byDay) {
      const left = `${x(d)}px`;
      const dayLabel = fmtDate(group[0].it.deadline, { day: "numeric", month: "long" });
      const visible = group.length > MAX_STACK ? group.slice(0, MAX_STACK - 1) : group;
      visible.forEach(({ it }, i) => {
        const dot = el("button", {
          type: "button", class: "tick", "data-cat": primaryCat(it),
          "aria-label": `${it.title}. ${t("due")}: ${fmtDate(it.deadline)} (${relDue(d)})`,
          style: `left:${left}; bottom:${bottom(i + 1)}`,
          onclick: () => { hideTip(); reveal(it); },
        });
        showTip(dot, `${dayLabel}, ${relDue(d)}`, it.title.length > 120 ? it.title.slice(0, 118) + "…" : it.title);
        track.append(dot);
      });
      const hidden = group.slice(visible.length);
      if (hidden.length) {
        const label = t("moreOnDay")(hidden.length, dayLabel);
        const more = el("button", {
          type: "button", class: "tick tick-more", "aria-label": label, text: `+${hidden.length}`,
          style: `left:${left}; bottom:${bottom(visible.length + 1)}`,
          onclick: () => { hideTip(); reveal(hidden[0].it); },
        });
        showTip(more, label, hidden.map(h => h.it.title).slice(0, 3).join(" · ") + (hidden.length > 3 ? " …" : ""));
        track.append(more);
      }
    }

    // colour key (only the colours on screen) and how to use it
    const legend = $("#track-legend"); legend.replaceChildren();
    const key = el("ul", { class: "key" });
    for (const c of CATS) {
      const n = upcoming.filter(u => primaryCat(u.it) === c).length;
      if (n) key.append(el("li", {}, el("span", { class: "swatch", style: `--c:var(--dot-${c})` }), `${t("catShort")[c]} (${n})`));
    }
    const scrolls = W > room + 2;
    legend.append(key, el("p", { class: "hint", text: scrolls ? `${t("trackHint")} ${t("trackHintScroll")}` : t("trackHint") }));
    if (!upcoming.length) key.remove();

    const next = upcoming[0];
    $("#next-up").innerHTML = next
      ? t("nextUp")(escapeHtml(next.it.title.length > 70 ? next.it.title.slice(0, 68) + "…" : next.it.title), relDue(next.d))
      : "";
  }

  function escapeHtml(s) { return s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  function itemNode(it) {
    const cat = primaryCat(it);
    const metaRow = el("div", { class: "meta" });
    for (const c of (it.categories && it.categories.length ? it.categories : ["other"])) {
      metaRow.append(el("span", { class: "tag", style: `--c: var(--${c === "tax_deadline" ? "tax" : c})`, text: t("catShort")[c] }));
    }
    metaRow.append(el("span", { text: sourceLabel(it.source) }));
    metaRow.append(el("span", { text: it.published ? fmtDate(it.published) : t("noDate") }));
    const seen = parseDay(it.first_seen);
    if (seen && (today - seen) / DAY <= 3) metaRow.append(el("span", { class: "new", text: t("isNew") }));

    let due = el("div");
    if (it.deadline) {
      const n = daysUntil(it.deadline);
      due = el("div", { class: `due${n < 0 ? " past" : n <= 7 ? " soon" : ""}` },
        el("b", { text: fmtDate(it.deadline, { day: "numeric", month: "short" }) }),
        el("span", { text: relDue(n) }));
    }
    return el("article", { class: "item", "data-cat": cat, id: `i-${it.uid}` },
      el("div", { class: "bar" }),
      el("div", {}, el("h4", {}, el("a", { href: safeHref(it.url), target: "_blank", rel: "noopener", text: it.title,
        title: it.title.length > 180 ? it.title : null })), metaRow),
      due);
  }

  function groupKey(it) {
    if (state.sort === "deadline") return it.deadline && daysUntil(it.deadline) >= 0 ? "due" : "nodue";
    if (!it.published) return "undated";
    return it.published.slice(0, 10);
  }
  function groupLabel(k) {
    if (k === "due") return t("groupDue");
    if (k === "nodue") return t("groupNoDue");
    if (k === "undated") return t("groupUndated");
    const n = -daysUntil(k);
    if (n === 0) return t("groupToday");
    if (n === 1) return t("groupYesterday");
    return fmtDate(k, { weekday: "long", day: "numeric", month: "long" });
  }

  // phones: the filter button shows how many filters are on, the panel's button how many results
  function renderPanelInfo(n) {
    const on = state.cats.size + state.aud.size + state.srcs.size + (state.due ? 1 : 0) + (state.period ? 1 : 0);
    const badge = $("#fcount");
    badge.hidden = !on; badge.textContent = on; badge.setAttribute("aria-label", t("activeFilters")(on));
    $("#apply").textContent = t("showN")(n);
  }

  function renderList() {
    const res = $("#results"); res.replaceChildren();
    if (!items.length) {
      res.append(el("div", { class: "empty" }, el("h3", { text: t("noDataTitle") }), el("p", { text: t("noDataText") })));
      $("#count").textContent = "";
      renderPanelInfo(0);
      return;
    }
    let list = items.filter(it => matches(it));
    if (state.sort === "deadline") {
      const key = it => { if (!it.deadline) return 1e9; const n = daysUntil(it.deadline); return n < 0 ? 1e8 - n : n; };
      list.sort((a, b) => key(a) - key(b));
    } else {
      list.sort((a, b) => (b.published || "").localeCompare(a.published || "") || (b.first_seen || "").localeCompare(a.first_seen || ""));
    }
    $("#count").textContent = t("count")(list.length, items.length);
    renderPanelInfo(list.length);
    if (!list.length) {
      res.append(el("div", { class: "empty" }, el("h3", { text: t("emptyTitle") }), el("p", { text: t("emptyText") })));
      return;
    }
    let current = null, box = null;
    for (const it of list.slice(0, state.shown)) {
      const k = groupKey(it);
      if (k !== current) {
        current = k;
        box = el("section", { class: "group" }, el("h3", { text: groupLabel(k) }));
        res.append(box);
      }
      box.append(itemNode(it));
    }
    if (list.length > state.shown) {
      const rest = Math.min(PAGE, list.length - state.shown);
      res.append(el("button", { type: "button", class: "more", text: t("more")(rest),
        onclick: () => { state.shown += PAGE; renderList(); } }));
    }
  }

  // feeds and APIs are for machines; link people to the site's home page instead
  function websiteOf(u) {
    try {
      const url = new URL(u);
      return /\/feed\/?$|\/opendata\/|\.(xml|json|rss)$/i.test(url.pathname) ? `${url.origin}/` : u;
    } catch { return u; }
  }

  function renderStatus() {
    const ul = $("#status"); ul.replaceChildren();
    if (!meta) return;
    for (const s of meta.sources) {
      const ok = s.ok !== false;
      ul.append(el("li", { class: s.disabled ? "off" : !ok ? "bad" : s.partial ? "warn" : "" }, el("span", { class: "dot" }),
        el("a", { href: safeHref(websiteOf(s.url)), target: "_blank", rel: "noopener", text: sourceLabel(s.name) }),
        el("span", { class: "st-n", title: (s.partial || [s.error || ""]).join("\n") || null,
          text: s.disabled ? t("stDisabled") : !ok && s.found === 0 && /^0 items/.test(s.error || "") ? t("stEmpty") : !ok ? t("stFail") : s.partial ? t("stPartial")(s.found ?? 0) : t("stOk")(s.found ?? 0) })));
    }
  }

  function reveal(it) {
    // timeline items already pass the filters, except "only with a deadline", which they
    // also pass, so the item is in the list; just make sure it isn't behind "show more"
    state.shown = Math.max(state.shown, items.length);
    renderList();
    const node = document.getElementById(`i-${it.uid}`);
    if (!node) return;
    node.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    node.classList.remove("flash"); void node.offsetWidth; node.classList.add("flash");
    node.querySelector("a").focus({ preventScroll: true });
  }

  function update() {
    state.shown = PAGE;
    renderHorizon(); renderList(); syncUrl();
    keepPanelInPlace();
  }

  function renderAll() { renderStatic(); renderFilters(); renderHorizon(); renderList(); renderStatus(); }

  // ---------- events ----------
  document.querySelectorAll(".lang button").forEach(b => b.addEventListener("click", () => {
    state.lang = b.dataset.lang; renderAll(); syncUrl();
  }));
  let qTimer;
  $("#q").addEventListener("input", e => { clearTimeout(qTimer); qTimer = setTimeout(() => { state.q = e.target.value.trim(); update(); }, 150); });
  $("#due").addEventListener("change", e => { state.due = e.target.value; update(); });
  $("#period").addEventListener("change", e => { state.period = e.target.value; update(); });
  $("#sort").addEventListener("change", e => { state.sort = e.target.value; update(); });
  $("#reset").addEventListener("click", () => {
    Object.assign(state, { q: "", due: "", period: "", sort: "published" });
    state.cats.clear(); state.aud.clear(); state.srcs.clear(); renderFilters(); update();
  });
  let rTimer;
  addEventListener("resize", () => { clearTimeout(rTimer); rTimer = setTimeout(renderHorizon, 120); });

  // calendar: webcal:// makes calendar apps subscribe (and keep updating) instead of downloading
  (() => {
    const ics = new URL("data/deadlines.ics", location.href);
    if (ics.protocol === "https:") $("#ics").href = `webcal://${ics.host}${ics.pathname}`;
  })();

  // repo link from the GitHub Pages URL
  (() => {
    const m = location.hostname.match(/^([^.]+)\.github\.io$/);
    const repo = location.pathname.split("/").filter(Boolean)[0];
    if (m && repo) $("#repo").href = `https://github.com/${m[1]}/${repo}`;
  })();

  // phones: filters live in a panel under the sticky search bar, closed until asked for;
  // wider screens always show them in the side column
  const phone = matchMedia("(max-width: 860px)");
  const panel = $("#filters");
  const fitPanel = () => { panel.open = !phone.matches; };
  fitPanel(); phone.addEventListener("change", fitPanel);
  const closePanel = () => { if (phone.matches) panel.open = false; };
  // if the bar was stuck to the top, keep it there after the list above the footer changes length
  function keepPanelInPlace() {
    if (!phone.matches || !panel.open) return;
    const top = $(".layout").getBoundingClientRect().top + scrollY;
    if (scrollY > top) scrollTo(0, top);
  }
  $("#apply").addEventListener("click", () => {
    closePanel();
    $("#list").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  });
  document.addEventListener("click", e => { if (panel.open && !e.target.closest(".rail")) closePanel(); });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && phone.matches && panel.open) { closePanel(); panel.querySelector("summary").focus(); }
  });

  // ---------- load ----------
  renderStatic();
  Promise.all([
    fetch(DATA + "items.json", { cache: "no-cache" }).then(r => r.ok ? r.json() : []),
    fetch(DATA + "meta.json", { cache: "no-cache" }).then(r => r.ok ? r.json() : null),
  ]).then(([rows, m]) => {
    meta = m;
    items = (rows || []).map(r => ({ ...r, uid: r.uid || hash(`${r.url}|${r.title}`) }));
    renderAll();
  }).catch(() => {
    renderAll();
    $("#results").replaceChildren(el("div", { class: "empty" }, el("h3", { text: t("loadError") })));
  });

  function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return (h >>> 0).toString(36); }
})();
