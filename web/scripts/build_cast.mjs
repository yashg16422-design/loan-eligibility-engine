// Generates src/landing/cast.json: the comic's Open Peeps characters (Pablo Stanley, CC0 1.0),
// rendered with DiceBear (MIT). One SVG per character and pose; keys are <who>_<pose>.
// Not run in CI (the output is committed). To regenerate, from web/:
//   npm i --no-save @dicebear/core@9.4.3 @dicebear/collection@9.4.3 && node scripts/build_cast.mjs
import { createAvatar } from "@dicebear/core";
import { openPeeps } from "@dicebear/collection";
import fs from "node:fs";

const skins = ["c68b63", "a86f4c", "8d5a3b", "b07a55"];
const peep = (seed, face, clothing) =>
  createAvatar(openPeeps, {
    seed: "open-peeps" + seed,
    face: [face],
    skinColor: skins,
    clothingColor: [clothing],
    maskProbability: 0,
    accessoriesProbability: 0,
    randomizeIds: true, // several copies share a page, so gradient/mask ids must not collide
  }).toString();
// drop the fixed size on the root tag only, so CSS sizes the figure
const fluid = (svg) => svg.replace(/^<svg([^>]*?) width="\d+"/, "<svg$1").replace(/^<svg([^>]*?) height="\d+"/, "<svg$1");

// A, B: the two engineers. F1, F2: the founders. T1, T2: the team that joins in frame 2.
const cast = {
  A_idle: peep(11, "concerned", "8ea8ff"), A_point: peep(11, "explaining", "8ea8ff"),
  B_idle: peep(16, "concerned", "4be3a0"), B_idea: peep(16, "smileBig", "4be3a0"),
  F1_idle: peep(21, "serious", "2b2e38"), F1_yes: peep(21, "smileBig", "2b2e38"),
  F2_idle: peep(6, "calm", "ffc94d"), F2_yes: peep(6, "smileBig", "ffc94d"),
  T1: peep(1, "smile", "ff7a59"), T2: peep(15, "smileBig", "8ea8ff"),
};
for (const k of Object.keys(cast)) cast[k] = fluid(cast[k]);
const out = new URL("../src/landing/cast.json", import.meta.url);
fs.writeFileSync(out, JSON.stringify(cast));
console.log(fs.statSync(out).size, "bytes");
