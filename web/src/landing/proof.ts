// The lender ticker: two copies of the list back to back, so the CSS loop has no seam.
import { LENDERS } from "../content/demo";
import { $ } from "./dom";

export function initProof(): void {
  const track = $("#lenders");
  track.replaceChildren(
    ...[...LENDERS, ...LENDERS].map((name, i) => {
      const s = document.createElement("span");
      s.textContent = name;
      if (i >= LENDERS.length) s.setAttribute("aria-hidden", "true"); // the copy is decoration
      return s;
    }),
  );
}
