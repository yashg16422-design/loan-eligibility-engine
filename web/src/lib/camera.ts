// The comic is one big "page" of frames moved under a fixed viewport. fit() is the camera:
// the translate + scale that centres a rectangle of the page on screen.

export type Rect = readonly [x: number, y: number, w: number, h: number];
export interface Cam {
  x: number;
  y: number;
  s: number;
}

/** Centre `rect` in a vw × vh viewport, scaled so it fills `pad` of the tighter dimension. */
export function fit([x, y, w, h]: Rect, vw: number, vh: number, pad = 0.86): Cam {
  const s = Math.min((vw * pad) / w, (vh * pad) / h);
  return { s, x: vw / 2 - (x + w / 2) * s, y: vh / 2 - (y + h / 2) * s };
}

/** The 28-point star behind "YES!", as an SVG points list on a 100 × 100 box. */
export function burstPoints(spikes = 14, outer = 48, inner = 30): string {
  const n = spikes * 2;
  return Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2, r = i % 2 ? inner : outer;
    return (50 + Math.cos(a) * r).toFixed(1) + "," + (50 + Math.sin(a) * r).toFixed(1);
  }).join(" ");
}
