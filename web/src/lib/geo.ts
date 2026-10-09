// Globe data helpers. public/geo/globe.json holds Natural Earth points (scripts/build_geo.py) as
// base64 Int16 arrays of lat/lon × 100, about 6× smaller than JSON numbers.

export const D2R = Math.PI / 180;
export const SURAT = { lat: 21.2019, lon: 72.8381 } as const;

/** base64 -> Int16Array (little-endian, as numpy wrote it). */
export function decodeInt16(b64: string): Int16Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

/** Lat/lon in degrees to a point on a sphere of radius r, in three.js's y-up convention. */
export function latLonToXYZ(lat: number, lon: number, r = 1): [number, number, number] {
  const phi = (90 - lat) * D2R, th = (lon + 180) * D2R;
  return [-r * Math.sin(phi) * Math.cos(th), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(th)];
}

/** Hermite smoothstep (works with e0 > e1 for a falling edge, as GLSL does). */
export function smoothstep(e0: number, e1: number, x: number): number {
  const t = Math.min(Math.max((x - e0) / (e1 - e0), 0), 1);
  return t * t * (3 - 2 * t);
}

/** 0..1 for how far a value has travelled through [from, to], clamped. */
export const progress = (x: number, from: number, to: number): number =>
  Math.min(Math.max((x - from) / (to - from), 0), 1);

export interface GlobeData {
  land: string;
  india: string;
  guj: string;
  cities: string;
}
