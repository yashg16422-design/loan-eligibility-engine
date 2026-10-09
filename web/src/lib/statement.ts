// The problem statement is written once with [brackets] round the words that get a colour.
// tokenize() turns it into words (each revealed letter by letter) and the spaces between them.

export type Tone = "" | "coral" | "amber";
export type Token = { kind: "space"; text: string } | { kind: "word"; text: string; tone: Tone };

/** "[rejected]" is coral (the rejection itself); any other bracketed phrase is amber. */
const toneOf = (phrase: string): Tone => (phrase.startsWith("rej") ? "coral" : "amber");

export function tokenize(source: string): Token[] {
  return source.split(/(\[[^\]]+\])/).flatMap((part): Token[] => {
    const hot = part.startsWith("[");
    const text = hot ? part.slice(1, -1) : part;
    const tone: Tone = hot ? toneOf(text) : "";
    return text
      .split(/(\s+)/)
      .filter((w) => w !== "")
      .map((w): Token => (/^\s+$/.test(w) ? { kind: "space", text: w } : { kind: "word", text: w, tone }));
  });
}

/** The sentence as a screen reader should hear it: no brackets. */
export const plain = (source: string): string => source.replace(/[[\]]/g, "");
