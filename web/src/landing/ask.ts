// "What's stopping your loan?": borrower questions type themselves in around the ask box,
// each tagged with the feature that answers it. Click one, or type your own, to get the answer.
// Typing only runs while the section is on screen.
import { gsap } from "gsap";
import {
  ANSWERS, type AnswerKey, classify, freeSlots, QUESTIONS, SLOTS_DESKTOP, SLOTS_PHONE,
} from "../lib/ask";
import { $, isSmall, isStatic } from "./dom";
import { scrollToEl } from "./scroll";

const ARROW_RIGHT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';
const ARROW_UP = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17 17 7M9 7h8v8" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>';

const slots = (): ReadonlyArray<readonly [number, number]> => (isSmall() ? SLOTS_PHONE : SLOTS_DESKTOP);

export function initAsk(): void {
  const host = $("#floaters");
  const section = $("#ask");
  const form = $<HTMLFormElement>("#ask-form");
  const input = $<HTMLInputElement>("#ask-in");
  const out = $("#ask-answer");

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
    if (!isStatic()) gsap.fromTo(out, { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.45, ease: "power3.out" });
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    showAnswer(input.value.trim() || input.placeholder);
  });

  const floater = (text: string, key: AnswerKey, [x, y]: readonly [number, number]): HTMLButtonElement => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "fq";
    b.style.left = x + "%";
    b.style.top = y + "%";
    b.innerHTML = `<span class="t"></span><em>${ANSWERS[key].tag} ${ARROW_UP}</em>`;
    b.setAttribute("aria-label", `${text} (${ANSWERS[key].tag})`);
    b.addEventListener("click", () => {
      input.value = text;
      showAnswer(text, key);
    });
    return b;
  };

  if (isStatic()) {
    // reduced motion: a still, readable (and focusable) set of questions
    host.removeAttribute("aria-hidden");
    slots().slice(0, 6).forEach((slot, i) => {
      const [text, key] = QUESTIONS[i];
      const b = floater(text, key, slot);
      b.classList.add("done");
      $(".t", b).textContent = text;
      host.append(b);
    });
    return;
  }

  // moving questions are decoration for pointer users (#floaters is aria-hidden); the form is
  // the accessible path
  const shown = new Map<HTMLButtonElement, number>(); // button -> slot index
  let next = Math.floor(Math.random() * QUESTIONS.length);
  let alive = false;
  let spawnTimer: ReturnType<typeof setTimeout> | undefined;
  let placeholderTimer: ReturnType<typeof setTimeout> | undefined;

  const retire = (b: HTMLButtonElement | undefined): void => {
    if (!b) return;
    shown.delete(b);
    b.classList.add("gone");
    setTimeout(() => b.remove(), 900);
  };

  function spawn(): void {
    if (!alive) return;
    const free = freeSlots(slots().length, shown.values());
    if (free.length === 0) {
      retire(shown.keys().next().value);
      spawnTimer = setTimeout(spawn, 700);
      return;
    }
    const slot = free[Math.floor(Math.random() * free.length)];
    const [text, key] = QUESTIONS[next];
    next = (next + 1) % QUESTIONS.length;
    const b = floater(text, key, slots()[slot]);
    b.tabIndex = -1;
    const tag = $("em", b);
    tag.style.visibility = "hidden";
    host.append(b);
    shown.set(b, slot);

    // type it in, letter by letter, then show which feature answers it
    const t = $(".t", b);
    let n = 0;
    const type = (): void => {
      if (!b.isConnected) return;
      t.textContent = text.slice(0, ++n);
      if (n < text.length) setTimeout(type, 38 + Math.random() * 45);
      else {
        tag.style.visibility = "";
        setTimeout(() => b.classList.add("done"), 1400);
        setTimeout(() => b.classList.add("old"), 5200);
      }
    };
    type();
    if (shown.size > (isSmall() ? 4 : 6)) retire(shown.keys().next().value);
    spawnTimer = setTimeout(spawn, 1700 + Math.random() * 900);
  }

  // the ask box types sample questions as its placeholder
  let pi = 0;
  function cyclePlaceholder(): void {
    const text = QUESTIONS[pi][0];
    pi = (pi + 3) % QUESTIONS.length;
    let n = 0;
    const tick = (): void => {
      if (!alive) return;
      input.placeholder = text.slice(0, ++n);
      placeholderTimer = setTimeout(n < text.length ? tick : cyclePlaceholder, n < text.length ? 55 : 2600);
    };
    tick();
  }

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
