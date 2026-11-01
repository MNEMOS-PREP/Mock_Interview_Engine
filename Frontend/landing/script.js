(function () {
  var root = document.documentElement;
  root.classList.add("js");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(s, c) { return (c || document).querySelector(s); }
  function $$(s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  /* Reading progress and the section the reader is in. */
  var bar = $("#progress");
  var links = $$(".nav nav a");
  var sections = links.map(function (a) { return $(a.getAttribute("href")); });
  function onScroll() {
    var max = document.documentElement.scrollHeight - window.innerHeight;
    bar.style.transform = "scaleX(" + (max > 0 ? Math.min(1, window.scrollY / max) : 0) + ")";
    var cur = -1;
    sections.forEach(function (s, i) {
      if (s && s.getBoundingClientRect().top < window.innerHeight * 0.4) cur = i;
    });
    links.forEach(function (a, i) { a.classList.toggle("on", i === cur); });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* Entrances: once, as each part scrolls in. */
  var items = $$(".reveal");
  if ("IntersectionObserver" in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
    items.forEach(function (n) { io.observe(n); });
  } else {
    items.forEach(function (n) { n.classList.add("in"); });
  }

  /* Numbers count up once. */
  $$("[data-count]").forEach(function (n) {
    var to = +n.getAttribute("data-count");
    if (reduce) return;
    n.textContent = "0";
    var t0 = null;
    function tick(t) {
      if (t0 == null) t0 = t;
      var p = Math.min(1, (t - t0) / 1100);
      n.textContent = String(Math.round(to * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });

  /* ───────── Mini interview: three questions, then your notes ───────── */

  var STATUS = {
    good: { label: "Correct", dot: "ok" },
    vague: { label: "Too vague", dot: "mid" },
    wrong: { label: "Incorrect", dot: "bad" },
    unbacked: { label: "Not backed up", dot: "na" }
  };

  var QUESTIONS = [
    {
      who: "Meera", role: "Campus Recruiter",
      q: "Tell me about a time you had to learn something quickly.",
      keys: ["weekend", "built", "project", "because", "then", "result", "learned by"],
      answers: [
        { k: "good", t: "I picked up Docker in a weekend for our project, then fixed a failing build by reading the logs." },
        { k: "vague", t: "I am a fast learner." },
        { k: "unbacked", t: "I cut our load time by half." }
      ],
      reply: {
        good: ["Nice. What was the first thing you tried, and what did it teach you?", "You gave a real situation and what you did. The follow-up asks for the first step."],
        vague: ["Can you give me one specific time?", "The answer claimed a trait without a story. The panel asks for one concrete moment."],
        wrong: ["Walk me through one real example.", "No situation was described, so there is nothing to follow up on yet."],
        unbacked: ["How did you measure that?", "A number was claimed without saying how it was measured. It is kept in the notes, not scored."]
      }
    },
    {
      who: "Ananya", role: "Software Engineer",
      q: "What does binary search need from its input?",
      keys: ["sorted", "order", "half", "middle", "discard"],
      answers: [
        { k: "good", t: "It needs sorted data, so each comparison can discard half of what is left." },
        { k: "vague", t: "It needs a list." },
        { k: "wrong", t: "It works on any list, it just guesses the middle." }
      ],
      reply: {
        good: ["Right. What happens to the running time if the data is not sorted first?", "You named the requirement and why it matters. The follow-up goes one step wider."],
        vague: ["What property of the list, exactly?", "A list is not enough. The note records that the key property was not named."],
        wrong: ["If it guesses the middle of an unsorted list, what does a comparison tell you?", "Challenged in your own words, not corrected on the spot. The notes explain it afterwards."],
        unbacked: ["Say more about that.", "Nothing here to check yet."]
      }
    },
    {
      who: "Arjun", role: "Bar Raiser",
      q: "Why is a hash map lookup O(1) on average?",
      keys: ["hash", "bucket", "index", "load factor", "resiz"],
      answers: [
        { k: "good", t: "Keys are hashed to a bucket, so we jump straight to it." },
        { k: "vague", t: "It is just fast." },
        { k: "wrong", t: "Because the keys are kept sorted." }
      ],
      reply: {
        good: ["Good. What keeps the buckets short as the map grows?", "You named the mechanism. The follow-up goes deeper, to the load factor and resizing."],
        vague: ["Fast compared to what? Walk me through what happens to the key.", "No mechanism was named. The panel asks for the steps."],
        wrong: ["If the keys were sorted, which lookup would you use? Does a hash map keep keys sorted?", "Challenged in your own words. The notes explain it afterwards."],
        unbacked: ["What is the evidence for that?", "Nothing to check yet."]
      }
    }
  ];

  var stage = $("#sim-stage");
  var fill = $("#sim-fill");
  var count = $("#sim-count");
  var idx = 0;
  var results = [];

  function classify(text, qd) {
    var s = text.toLowerCase();
    if (qd.keys.some(function (k) { return s.indexOf(k) !== -1; }) && s.length > 22) return "good";
    if (s.length < 24) return "vague";
    return "wrong";
  }

  function head(qd) {
    var who = el("div", "sim-who");
    who.appendChild(el("div", "avatar", qd.who.charAt(0)));
    var t = el("div");
    t.appendChild(el("b", null, qd.who));
    t.appendChild(el("span", null, qd.role + " asks"));
    who.appendChild(t);
    return who;
  }

  function ask() {
    var qd = QUESTIONS[idx];
    stage.textContent = "";
    count.textContent = "Question " + (idx + 1) + " of " + QUESTIONS.length;
    fill.style.width = (idx / QUESTIONS.length) * 100 + "%";
    var wrap = el("div", "fb");
    wrap.appendChild(head(qd));
    wrap.appendChild(el("p", "sim-q", qd.q));
    var opts = el("div", "opts");
    qd.answers.forEach(function (a) {
      var b = el("button", "opt", a.t);
      b.type = "button";
      b.addEventListener("click", function () { answer(a.t, a.k); });
      opts.appendChild(b);
    });
    wrap.appendChild(opts);
    var own = el("form", "sim-own");
    var inp = el("input");
    inp.type = "text";
    inp.placeholder = "Or answer in your own words";
    inp.setAttribute("aria-label", "Your own answer");
    inp.maxLength = 200;
    var go = el("button", null, "Send");
    go.type = "submit";
    own.appendChild(inp);
    own.appendChild(go);
    own.addEventListener("submit", function (e) {
      e.preventDefault();
      var v = inp.value.trim();
      if (!v) { inp.focus(); return; }
      answer(v, classify(v, qd));
    });
    wrap.appendChild(own);
    stage.appendChild(wrap);
  }

  function answer(text, kind) {
    var qd = QUESTIONS[idx];
    var r = qd.reply[kind];
    results.push({ q: qd.q, kind: kind });
    stage.textContent = "";
    fill.style.width = ((idx + 1) / QUESTIONS.length) * 100 + "%";
    var wrap = el("div", "fb");
    wrap.appendChild(head(qd));
    var you = el("p", "you");
    you.appendChild(el("b", null, "You: "));
    you.appendChild(document.createTextNode(text));
    wrap.appendChild(you);
    wrap.appendChild(el("p", "says", r[0]));
    var v = el("p", "verdict");
    v.appendChild(el("i", "dot " + STATUS[kind].dot));
    v.appendChild(document.createTextNode("Your note: " + STATUS[kind].label));
    wrap.appendChild(v);
    wrap.appendChild(el("p", "note-text", r[1]));
    var nx = el("div", "next");
    var b = el("button", "btn", idx < QUESTIONS.length - 1 ? "Next question" : "See my notes");
    b.type = "button";
    b.addEventListener("click", function () {
      idx++;
      if (idx < QUESTIONS.length) ask(); else done();
    });
    nx.appendChild(b);
    wrap.appendChild(nx);
    stage.appendChild(wrap);
    b.focus({ preventScroll: true });
  }

  function done() {
    stage.textContent = "";
    count.textContent = "Your notes";
    fill.style.width = "100%";
    var wrap = el("div", "fb");
    wrap.appendChild(el("p", "sim-q", "That is three questions. Here is how each went."));
    var ul = el("ul", "sum");
    results.forEach(function (r) {
      var li = el("li");
      li.appendChild(el("i", "dot " + STATUS[r.kind].dot));
      li.appendChild(el("span", null, r.q));
      li.appendChild(el("b", null, STATUS[r.kind].label));
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
    var nx = el("div", "next");
    var a = el("a", "btn", "Start a full interview");
    a.href = "/mock";
    var again = el("button", "btn ghost", "Try again");
    again.type = "button";
    again.addEventListener("click", function () { idx = 0; results = []; ask(); });
    nx.appendChild(a);
    nx.appendChild(again);
    wrap.appendChild(nx);
    stage.appendChild(wrap);
  }
  ask();

  /* ───────── Shape your slip ───────── */

  var TOPIC = {
    dsa: { name: "Data structures", who: "Ananya", role: "Software Engineer" },
    os: { name: "Operating systems", who: "Aditi", role: "Infrastructure Engineer" },
    ds: { name: "Data science", who: "Isha", role: "Data Scientist" },
    hr: { name: "People questions", who: "Nisha", role: "Campus Hiring Manager" }
  };
  var MODE = {
    practice: { name: "Practice", lead: "Meera", leadRole: "Campus Recruiter", hints: "hints on, retry allowed", open: false },
    mock: { name: "Mock", lead: "Lata", leadRole: "Director of Engineering", hints: "hints cost credit", open: true },
    drive: { name: "Real drive", lead: "Vikram", leadRole: "Staff Engineer", hints: "hints cost credit", open: true },
    boss: { name: "Final Boss", lead: "Arjun", leadRole: "Bar Raiser", hints: "no hints, hard clock", open: true }
  };
  var state = { topic: "dsa", len: "30", mode: "mock" };

  function renderPlan() {
    var len = +state.len;
    var m = MODE[state.mode];
    var t = TOPIC[state.topic];
    var parts = [];
    var open = m.open ? Math.max(2, Math.round(len * 0.08)) : 0;
    var close = m.open ? Math.max(2, Math.round(len * 0.08)) : 0;
    var people = state.topic === "hr" ? 0 : Math.round(len * 0.2);
    var main = len - open - close - people;
    if (open) parts.push({ n: "Opening", who: m.lead, role: m.leadRole, min: open, main: false });
    parts.push({ n: t.name, who: state.mode === "boss" ? "Arjun" : t.who, role: state.mode === "boss" ? "Bar Raiser" : t.role, min: main, main: true });
    if (people) parts.push({ n: "People questions", who: "Meera", role: "Campus Recruiter", min: people, main: false });
    if (close) parts.push({ n: "Closing", who: m.lead, role: m.leadRole, min: close, main: false });

    var bar = $("#plan-bar");
    var existing = $$("i", bar);
    if (existing.length !== parts.length) {
      bar.textContent = "";
      parts.forEach(function () { bar.appendChild(el("i")); });
      existing = $$("i", bar);
    }
    parts.forEach(function (p, i) {
      existing[i].style.flexGrow = p.min;
      existing[i].style.flexBasis = "0";
      existing[i].textContent = p.min >= 6 ? p.n : "";
      existing[i].className = p.main ? "main" : "";
    });
    bar.setAttribute("aria-label", parts.map(function (p) { return p.n + " " + p.min + " minutes"; }).join(", "));

    var list = $("#plan-list");
    list.textContent = "";
    parts.forEach(function (p) {
      var li = el("li");
      li.appendChild(el("div", "avatar", p.who.charAt(0)));
      var d = el("div");
      d.appendChild(el("b", null, p.n));
      d.appendChild(el("span", null, p.who + ", " + p.role));
      li.appendChild(d);
      li.appendChild(el("em", null, p.min + " min"));
      list.appendChild(li);
    });
    var pauses = Math.floor(len / 15);
    $("#plan-meta").textContent = m.name + ": " + m.hints + ". " + pauses + (pauses === 1 ? " pause" : " pauses") + " available.";
  }

  $$(".builder .chips").forEach(function (group) {
    var key = group.getAttribute("data-key");
    $$("button", group).forEach(function (b) {
      b.addEventListener("click", function () {
        $$("button", group).forEach(function (o) { o.setAttribute("aria-checked", o === b ? "true" : "false"); });
        state[key] = b.getAttribute("data-v");
        renderPlan();
      });
    });
  });
  renderPlan();

  /* ───────── Who is asking ───────── */

  var PEOPLE = {
    topics: [
      ["Ananya", "Software Engineer", "Likes to see a solution grow from the simplest version, and asks what the code does on a small example."],
      ["Rohit", "Senior Software Engineer", "Wants the complexity of every idea and the reason for it. Keeps asking about the worst input."],
      ["Aditi", "Infrastructure Engineer", "Starts from a laptop slowing down and asks what the operating system is doing about it."],
      ["Isha", "Data Scientist", "Asks how you would frame the problem, what you would measure, and what could fool you."]
    ],
    people: [
      ["Meera", "Campus Recruiter", "Puts people at ease. Short, plain questions; never pushes past the first sign of difficulty."],
      ["Nisha", "Campus Hiring Manager", "Asks why this role, and about a time you had to learn something fast."],
      ["Lata", "Director of Engineering", "Listens for judgement: how you decide with incomplete information, and how you explain it."]
    ],
    hard: [
      ["Arjun", "Bar Raiser", "Keeps asking until the reasoning runs out. Precise, economical, never rude."],
      ["Vikram", "Staff Engineer", "Wants the short version first. Terse and direct, interested in performance and scale."],
      ["Dr. Raghavan", "Professor", "Runs a viva: derive it, justify it, and follow the reasoning further than most would."],
      ["Kabir", "Founder", "Talks fast, cares about trade-offs and what you would actually ship."]
    ]
  };
  var plist = $("#people");
  function renderPeople(g) {
    plist.textContent = "";
    PEOPLE[g].forEach(function (p, i) {
      var li = el("li", "person");
      li.style.setProperty("--i", i);
      li.appendChild(el("div", "avatar", p[0].charAt(0)));
      li.appendChild(el("b", null, p[0]));
      li.appendChild(el("em", null, p[1]));
      li.appendChild(el("p", null, p[2]));
      plist.appendChild(li);
    });
  }
  function tabs(root, attr, onSel) {
    var bs = $$("button", root);
    bs.forEach(function (b, i) {
      b.addEventListener("click", function () { select(b); });
      b.addEventListener("keydown", function (e) {
        var j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : -1;
        if (j < 0) return;
        e.preventDefault();
        var n = bs[(j + bs.length) % bs.length];
        select(n);
        n.focus();
      });
    });
    function select(b) {
      bs.forEach(function (o) { o.setAttribute("aria-selected", o === b ? "true" : "false"); });
      onSel(b.getAttribute(attr));
    }
  }
  tabs($("#ptabs"), "data-g", renderPeople);
  renderPeople("topics");

  /* ───────── Four ways to sit it ───────── */

  var MODES = [
    { n: "Practice", img: "assets/ui-setup.jpg", alt: "The setup screen: what to practise, which topic, how long, and who you might meet",
      t: "A gentle interviewer, hints on, and a retry if you want another go. Each answer is checked once rather than three times: less precise, never more generous.",
      f: ["Hints on", "Retry allowed", "Checked once per answer"] },
    { n: "Mock", img: "assets/ui-plan.jpg", alt: "The plan screen: the panel, the time split across parts, and a Start button",
      t: "A realistic panel: a lead who opens and closes, someone who knows each part, HR for the people questions. The clock is enforced and a hint costs credit.",
      f: ["Full panel", "Clock enforced", "Hints cost credit"] },
    { n: "Real drive", img: "assets/ui-live.jpg", alt: "The live interview: the panel's tiles, the current question and the conversation",
      t: "As Mock, with a brisker technical interviewer. Start from a job description or a company's drive and the plan follows what it asks for.",
      f: ["Built from a job description", "Brisker technical round", "Hints cost credit"] },
    { n: "Final Boss", img: "assets/ui-notes.jpg", alt: "The notes screen: how your answers went, question by question",
      t: "No hints, a hard clock with no overrun, and an interviewer who keeps going until your reasoning runs out. Harder, never ruder.",
      f: ["No hints", "Hard clock, no overrun", "Keeps going until reasoning runs out"] }
  ];
  var mimg = $("#mode-img");
  var mcopy = $("#mode-copy");
  function renderMode(i) {
    var m = MODES[+i];
    mcopy.textContent = "";
    mcopy.appendChild(el("h3", null, m.n));
    mcopy.appendChild(el("p", null, m.t));
    var ul = el("ul");
    m.f.forEach(function (x) { ul.appendChild(el("li", null, x)); });
    mcopy.appendChild(ul);
    mimg.classList.add("swap");
    setTimeout(function () {
      mimg.src = m.img;
      mimg.alt = m.alt;
      mimg.classList.remove("swap");
    }, reduce ? 0 : 160);
  }
  tabs($("#mtabs"), "data-m", renderMode);
  mcopy.appendChild(el("h3", null, MODES[0].n));
  mcopy.appendChild(el("p", null, MODES[0].t));
  var ul0 = el("ul");
  MODES[0].f.forEach(function (x) { ul0.appendChild(el("li", null, x)); });
  mcopy.appendChild(ul0);
  mimg.alt = MODES[0].alt;

  /* The screenshot leans toward the pointer. */
  var shot = $("#shot");
  if (!reduce && window.matchMedia("(hover: hover)").matches) {
    shot.addEventListener("mousemove", function (e) {
      var r = shot.getBoundingClientRect();
      var x = (e.clientX - r.left) / r.width - 0.5;
      var y = (e.clientY - r.top) / r.height - 0.5;
      mimg.style.setProperty("--ry", (x * 6).toFixed(2) + "deg");
      mimg.style.setProperty("--rx", (-y * 6).toFixed(2) + "deg");
    });
    shot.addEventListener("mouseleave", function () {
      mimg.style.setProperty("--ry", "0deg");
      mimg.style.setProperty("--rx", "0deg");
    });
  }

  /* ───────── Notes ───────── */

  var NOTES = [
    ["Correct", "ok", "Why is a hash map lookup O(1)?", "Keys hash to a bucket index, so the lookup goes straight there. Named the load factor when pushed."],
    ["Mostly correct", "ok2", "What keeps the buckets short?", "Said resizing. Missed that resizing is triggered by the load factor, and why that keeps the average cost flat."],
    ["Too vague", "mid", "What does an index buy you?", "Said it is faster. Named no mechanism: what is stored, and what a scan would do instead."],
    ["Incorrect", "bad", "Is a view stored on disk?", "Said always. A view stores a query, not rows, unless it is materialised. Challenged in your own words."],
    ["Not answered", "na", "Name one use of a trie.", "Moved on after a pause. Counted as not answered, and listed first under work to do."],
    ["Not backed up", "na", "Your project line: \"cut latency by half\".", "Claimed a number without saying how it was measured. Not scored; kept in the notes."]
  ];
  var note = $("#note");
  function renderNote(i) {
    var n = NOTES[+i];
    note.textContent = "";
    var h = el("h3");
    h.appendChild(el("i", "dot " + n[1]));
    h.appendChild(document.createTextNode(n[0]));
    note.appendChild(h);
    note.appendChild(el("p", "q", n[2]));
    note.appendChild(el("p", "t", n[3]));
  }
  tabs($("#ntabs"), "data-n", renderNote);
  renderNote(0);
})();
