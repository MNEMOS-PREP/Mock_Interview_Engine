// Interactive preview: pick a sample question and the answer, hand-over, follow-up and note change with it.
const SAMPLES = [
  {
    answer: "“I added Redis caching to our placement portal. API response time fell from <b>800 ms to 200 ms.</b>”",
    handover: "Meera → Vikram · handing over to dig deeper",
    av: "VK", avClass: "av-sand", name: "Vikram", role: "AI staff engineer · follows your answer",
    followup: "“You mentioned 800 ms to 200 ms. How did you measure that, and what happened when cached data went stale?”",
    good: "Good: a clear result. Missing: your measurement method and the freshness trade-off.",
    next: "explain p95 latency, test load and cache invalidation. Separate what you measured from what you assumed.",
    queue: "Added to practice queue: defend a project metric",
  },
  {
    answer: "“I’d reach for a hash map when I need <b>constant-time lookups</b> by key, like counting word frequencies.”",
    handover: "Meera → Ananya · handing over to explore your approach",
    av: "AN", avClass: "av-lilac", name: "Ananya", role: "AI software engineer · explores your approach",
    followup: "“Lookups are constant on average. What happens to that when many keys collide, and how would you size the table?”",
    good: "Good: the right use case. Missing: worst-case behaviour and resizing.",
    next: "explain collisions, load factor and when a sorted structure is the better choice.",
    queue: "Added to practice queue: explain complexity trade-offs",
  },
  {
    answer: "“Two of us disagreed on the API design, so I proposed we <b>prototype both</b> and compare them on Friday.”",
    handover: "Meera → Arjun · handing over to test the trade-offs",
    av: "AR", avClass: "av-sand", name: "Arjun", role: "AI bar raiser · tests the trade-offs",
    followup: "“Prototyping is a fair call. What if your teammate still disagreed after seeing the results?”",
    good: "Good: you took initiative. Missing: what you did when the disagreement didn’t resolve.",
    next: "describe the outcome, what you’d change, and how you kept the working relationship.",
    queue: "Added to practice queue: close a disagreement",
  },
];

const $ = (id) => document.getElementById(id);
const choices = [...document.querySelectorAll(".choice")];
const animated = ["answer", "reply", "note"].map($);

function show(i) {
  const s = SAMPLES[i];
  choices.forEach((el, k) => {
    const on = k === i;
    el.classList.toggle("on", on);
    el.setAttribute("aria-checked", String(on));
    el.querySelector("img").src = on ? "assets/circle-check.svg" : "assets/circle.svg";
  });
  $("answer").innerHTML = s.answer;
  $("handover").textContent = s.handover;
  const av = $("who-av");
  av.textContent = s.av;
  av.className = `av ${s.avClass} av-sm`;
  $("who-name").textContent = s.name;
  $("who-role").textContent = s.role;
  $("followup").textContent = s.followup;
  $("note-good").textContent = s.good;
  $("note-next").textContent = s.next;
  $("note-queue").textContent = s.queue;
  animated.forEach((el) => {
    el.classList.remove("swap");
    void el.offsetWidth;
    el.classList.add("swap");
  });
}

choices.forEach((el, i) => el.addEventListener("click", () => show(i)));
show(0);
animated.forEach((el) => el.classList.remove("swap"));
