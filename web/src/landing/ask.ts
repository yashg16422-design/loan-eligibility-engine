// "What's stopping your loan?": borrower questions type themselves in at random free spots
// around the ask box, stay long enough to read, then fade, while new ones appear elsewhere.
// Each is tagged with the feature that answers it; click one, or type your own, to get the
// answer. Spots are picked so a question never covers the heading, the ask box, the answer
// or another question. Typing only runs while the section is on screen.
import { gsap } from "gsap";
import {
  ANSWERS, type AnswerKey, type Box, classify, overlaps, pickSpot, QUESTIONS, seeded, shuffle,
} from "../lib/ask";
import { $, $$, debounce, isSmall, isStatic } from "./dom";
import { scrollToEl } from "./scroll";

const ARROW_RIGHT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
const ARROW_UP = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';

const TYPE_MS = [16, 30] as const; // per character: quick, but still reads as typing
const HOLD_MS = 4200; // fully typed, on screen long enough to read
const FADE_MS = 700; // matches the .fq.gone transition
const EVERY_MS = [700, 1100] as const; // a new question this often, while there's room
const PAD = 18; // px kept clear around every question

const between = ([lo, hi]: readonly [number, number]): number => lo + Math.random() * (hi - lo);

export function initAsk(): void {
  const host = $("#floaters");
  const section = $("#ask");
  const core = $(".ask-core", section);
  const form = $<HTMLFormElement>("#ask-form");
  const input = $<HTMLInputElement>("#ask-in");
  const out = $("#ask-answer");
  const shown = new Set<HTMLButtonElement>();

  /** Section-relative rect of an element. */
  const boxOf = (el: Element): Box => {
    const s = section.getBoundingClientRect(), r = el.getBoundingClientRect();
    return { x: r.left - s.left, y: r.top - s.top, w: r.width, h: r.height };
  };
  /** Where questions may go: clear of the fixed top bar and, on phones, the section pill. */
  const area = (): Box => {
    const w = section.clientWidth, h = section.clientHeight, top = 84, bottom = isSmall() ? 76 : 24;
    return { x: 12, y: top, w: w - 24, h: h - top - bottom };
  };
  const max = (): number => (isSmall() ? 3 : 6);

  function showAnswer(question: string, key: AnswerKey = classify(question)): void {
    const a = ANSWERS[key];
    const tag = document.createElement("small");
    tag.textContent = a.tag;
    const title = document.createElement("h3");
    title.textContent = a.title;
    const body = document.createElement("p");
    body.textContent = a.body;
    const link = document.createElement("a");
    link.href = a.href;
    link.innerHTML = ARROW_RIGHT;
    link.prepend(a.cta);
    link.addEventListener("click", (e) => {
      e.preventDefault();
      scrollToEl($(a.href), 0, 1.3);
    });
    out.replaceChildren(tag, title, body, link);
    out.hidden = false;
    // the answer card grows the centre block: clear any question it now covers
    const c = boxOf(core);
    shown.forEach((b) => overlaps(boxOf(b), c, PAD) && retire(b));
    if (!isStatic()) gsap.fromTo(out, { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.45, ease: "power3.out" });
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    showAnswer(input.value.trim() || input.placeholder);
  });

  /** A question button, measured at its full typed size and placed in a free spot (or null). */
  function place(text: string, key: AnswerKey, rand: () => number): HTMLButtonElement | null {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "fq";
    b.innerHTML = `<span class="t"></span><em>${ANSWERS[key].tag} ${ARROW_UP}</em>`;
    b.setAttribute("aria-label", `${text} (${ANSWERS[key].tag})`);
    b.addEventListener("click", () => {
      input.value = text;
      showAnswer(text, key);
    });
    // measure the finished question invisibly, so typing never grows it into a neighbour
    const t = $(".t", b);
    t.textContent = text;
    b.style.visibility = "hidden";
    host.append(b);
    const size = { w: b.offsetWidth, h: b.offsetHeight };
    const spot = pickSpot(area(), size, [boxOf(core), ...[...shown].map(boxOf)], rand, PAD);
    if (!spot) {
      b.remove();
      return null;
    }
    Object.assign(b.style, { left: spot.x + "px", top: spot.y + "px", width: size.w + "px", visibility: "" });
    return b;
  }

  function retire(b: HTMLButtonElement): void {
    if (!shown.delete(b)) return;
    b.classList.add("gone");
    setTimeout(() => b.remove(), FADE_MS);
  }

  if (isStatic()) {
    // reduced motion: a still, readable (and focusable) set, laid out the same way every visit
    host.removeAttribute("aria-hidden");
    const layout = (): void => {
      host.replaceChildren();
      shown.clear();
      const rand = seeded(42);
      for (const [text, key] of QUESTIONS) {
        if (shown.size >= max()) break;
        const b = place(text, key, rand);
        if (b) {
          b.classList.add("done");
          shown.add(b);
        }
      }
    };
    void document.fonts.ready.then(layout);
    addEventListener("resize", debounce(layout, 200));
    return;
  }

  // moving questions are decoration for pointer users (#floaters is aria-hidden); the form is
  // the accessible path
  let order: Array<readonly [string, AnswerKey]> = [];
  let alive = false;
  let spawnTimer: ReturnType<typeof setTimeout> | undefined;
  let placeholderTimer: ReturnType<typeof setTimeout> | undefined;

  /** The next random question that isn't already on screen. */
  function nextQuestion(): readonly [string, AnswerKey] {
    const onScreen = new Set([...shown].map((b) => b.getAttribute("aria-label")));
    for (let i = 0; i < QUESTIONS.length * 2; i++) {
      if (order.length === 0) order = shuffle(QUESTIONS, Math.random);
      const q = order.shift();
      if (q && !onScreen.has(`${q[0]} (${ANSWERS[q[1]].tag})`)) return q;
    }
    return QUESTIONS[0];
  }

  function spawn(): void {
    if (!alive) return;
    if (shown.size < max()) {
      const [text, key] = nextQuestion();
      const b = place(text, key, Math.random);
      if (b) {
        b.tabIndex = -1;
        shown.add(b);
        const t = $(".t", b), tag = $("em", b);
        t.textContent = "";
        tag.style.visibility = "hidden";
        let n = 0;
        const type = (): void => {
          if (!b.isConnected) return;
          t.textContent = text.slice(0, ++n);
          if (n < text.length) setTimeout(type, between(TYPE_MS));
          else {
            tag.style.visibility = "";
            b.classList.add("done");
            setTimeout(() => retire(b), HOLD_MS);
          }
        };
        type();
      }
    }
    spawnTimer = setTimeout(spawn, between(EVERY_MS));
  }

  // the ask box types sample questions as its placeholder
  let pi = 0;
  function cyclePlaceholder(): void {
    const text = QUESTIONS[pi][0];
    pi = (pi + 5) % QUESTIONS.length;
    let n = 0;
    const tick = (): void => {
      if (!alive) return;
      input.placeholder = text.slice(0, ++n);
      placeholderTimer = setTimeout(n < text.length ? tick : cyclePlaceholder, n < text.length ? 32 : 2600);
    };
    tick();
  }

  // a new layout invalidates every spot: clear and let new questions find room
  addEventListener("resize", debounce(() => $$<HTMLButtonElement>(".fq", host).forEach(retire), 150));

  new IntersectionObserver(
    ([e]) => {
      if (e.isIntersecting && !alive) {
        alive = true;
        spawn();
        cyclePlaceholder();
      } else if (!e.isIntersecting && alive) {
        alive = false;
        clearTimeout(spawnTimer);
        clearTimeout(placeholderTimer);
      }
    },
    { threshold: 0.15 },
  ).observe(section);
}
