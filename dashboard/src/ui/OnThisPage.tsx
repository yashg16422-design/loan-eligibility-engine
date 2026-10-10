import { useEffect, useState } from "react";

/** The reference's "On this page" rail: where you are on a long page, one click to anywhere. */
export function OnThisPage({ sections }: { sections: { id: string; label: string }[] }) {
  const [active, setActive] = useState(sections[0]?.id);
  useEffect(() => {
    const seen = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActive(top.target.id);
      },
      { rootMargin: "-20% 0px -65% 0px" },
    );
    sections.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) seen.observe(el);
    });
    return () => seen.disconnect();
  }, [sections]);
  return (
    <nav aria-label="On this page" className="sticky top-28 hidden self-start xl:block">
      <p className="label">On this page</p>
      <ul className="mt-6 grid gap-4">
        {sections.map((s) => (
          <li key={s.id}>
            <a href={`#${s.id}`} aria-current={active === s.id ? "location" : undefined}
              className={`group flex items-center gap-3 font-mono text-[0.7rem] tracking-[0.14em] uppercase no-underline transition-colors duration-150 ${
                active === s.id ? "text-fg" : "text-mute hover:text-fg"
              }`}>
              <span aria-hidden className={`h-px transition-all duration-200 ${active === s.id ? "w-6 bg-fg" : "w-3 bg-line-hi group-hover:bg-mute"}`} />
              {s.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
