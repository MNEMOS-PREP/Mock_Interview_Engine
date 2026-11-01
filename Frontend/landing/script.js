(function () {
  var root = document.documentElement;
  root.classList.add("js");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Hero: the slip shrinks toward the bottom-left corner as the page moves. */
  var hero = document.getElementById("top");
  var slip = document.getElementById("slip");
  function shrink() {
    if (!hero || !slip || reduce) return;
    var travel = hero.offsetHeight - window.innerHeight;
    var p = Math.min(Math.max(window.scrollY / travel, 0), 1);
    var eased = 1 - Math.pow(1 - p, 2);
    var rect = slip.getBoundingClientRect();
    var w = slip.offsetWidth;
    var h = slip.offsetHeight;
    var left0 = (window.innerWidth - w) / 2;
    if (window.innerWidth <= 860) left0 = 16;
    var bottom0 = (window.innerHeight + h) / 2;
    var tx = (left0 - 24) * eased;
    var ty = (window.innerHeight - 24 - bottom0) * eased;
    var s = 1 - 0.7 * eased;
    slip.style.transform = "translate(" + -tx + "px," + ty + "px) scale(" + s + ")";
    var body = slip.querySelector(".slip-body");
    if (body) {
      var f = 1 - Math.min(1, Math.max(0, (p - 0.25) / 0.25));
      body.style.opacity = String(f);
      body.style.visibility = f < 0.02 ? "hidden" : "visible";
    }
    slip.style.opacity = String(1 - Math.max(0, p - 0.85) / 0.15);
    void rect;
  }
  window.addEventListener("scroll", shrink, { passive: true });
  window.addEventListener("resize", shrink);
  shrink();

  /* Entrances: once, as each part scrolls in, staggered by --d. */
  /* Parts of a section enter one after another. */
  document.querySelectorAll(".items li, .rows li, .slip-note, .facts li").forEach(function (el, i) {
    el.classList.add("reveal");
    el.style.setProperty("--d", String(i % 6));
  });
  var items = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && !reduce) {
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -6% 0px" }
    );
    items.forEach(function (el) {
      io.observe(el);
    });
  } else {
    items.forEach(function (el) {
      el.classList.add("in");
    });
  }

  /* The one live thing: pick an answer, see the follow-up and the note. */
  var replies = {
    good: {
      says: "Good. What keeps the buckets short as the map grows?",
      status: "Correct so far",
      note: "You named the mechanism. The follow-up goes one step deeper, to the load factor and resizing."
    },
    vague: {
      says: "Fast compared to what? Walk me through what happens to the key.",
      status: "Too vague",
      note: "The answer named no mechanism. The panel asks for the steps, and the note records that it stayed general."
    },
    wrong: {
      says: "You said the keys are kept sorted. If they were, which lookup would you use, and does a hash map keep keys sorted?",
      status: "Incorrect",
      note: "Challenged in your own words, not corrected on the spot. The notes explain it afterwards."
    }
  };
  var out = document.getElementById("try-out");
  var opts = document.querySelectorAll(".opt");
  opts.forEach(function (btn) {
    btn.setAttribute("aria-pressed", "false");
    btn.addEventListener("click", function () {
      var r = replies[btn.getAttribute("data-k")];
      opts.forEach(function (o) {
        o.setAttribute("aria-pressed", o === btn ? "true" : "false");
      });
      out.innerHTML =
        '<div class="fade"><h3>The panel asks</h3><p class="says"></p>' +
        '<h3 class="status"></h3><p class="note"></p></div>';
      out.querySelector(".says").textContent = r.says;
      out.querySelector(".status").textContent = "Your note: " + r.status;
      out.querySelector(".note").textContent = r.note;
    });
  });
})();
