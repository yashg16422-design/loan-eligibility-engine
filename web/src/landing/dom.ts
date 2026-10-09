// Small DOM helpers shared by the landing sections.

/** The one element matching `sel`; throws if the markup is missing it (a bug, not a state). */
export function $<T extends Element = HTMLElement>(sel: string, root: ParentNode = document): T {
  const el = root.querySelector<T>(sel);
  if (!el) throw new Error(`landing: missing element ${sel}`);
  return el;
}

/** Every element matching `sel`, as an array. */
export const $$ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document): T[] => [
  ...root.querySelectorAll<T>(sel),
];

/** Phone layout breakpoint, kept in step with the CSS (max-width: 860px). */
export const isSmall = (): boolean => innerWidth < 861;

/** Reduced motion: set in index.html before first paint; every section renders its end state. */
export const isStatic = (): boolean => document.documentElement.classList.contains("static");

/** The current accent colour (it changes with the palette switch). */
export const accent = (): string =>
  getComputedStyle(document.documentElement).getPropertyValue("--acc").trim() || "#4BE3A0";

/** Fired on window when the palette changes, so canvas and SVG colours can follow. */
export const THEME_EVENT = "themechange";

/** Run `fn` once input has been quiet for `ms` (resize storms rebuild timelines once). */
export function debounce(fn: () => void, ms: number): () => void {
  let t: ReturnType<typeof setTimeout> | undefined;
  return () => {
    clearTimeout(t);
    t = setTimeout(fn, ms);
  };
}

/** Read from storage without throwing (private mode, blocked site data). */
export function readStore(store: "local" | "session", key: string): string | null {
  try {
    return (store === "local" ? localStorage : sessionStorage).getItem(key);
  } catch {
    return null;
  }
}

/** Write to storage; failure only loses a convenience, never breaks the page. */
export function writeStore(store: "local" | "session", key: string, value: string): void {
  try {
    (store === "local" ? localStorage : sessionStorage).setItem(key, value);
  } catch {
    /* storage unavailable: the choice just isn't remembered */
  }
}
