import { CaretDown, Check } from "@phosphor-icons/react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

export interface Option<T extends string> {
  value: T;
  label: string;
}

/**
 * A listbox dropdown in the landing's style (sharp, hairline, no animation) replacing the
 * browser's native select. Keyboard: Enter/Space/ArrowDown opens, arrows move, Enter picks,
 * Escape or Tab closes, typing jumps to the first label with that letter.
 */
export function Select<T extends string>({
  label,
  value,
  options,
  onChange,
  inline = false,
}: {
  label: string;
  value: T;
  options: Option<T>[];
  onChange: (v: T) => void;
  inline?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(() => Math.max(options.findIndex((o) => o.value === value), 0));
  const root = useRef<HTMLDivElement>(null);
  const id = useId();
  const current = options.find((o) => o.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const pick = (i: number) => {
    onChange(options[i].value);
    setOpen(false);
  };

  const onKey = (e: KeyboardEvent) => {
    if (!open && ["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault();
      setActive(Math.max(options.findIndex((o) => o.value === value), 0));
      setOpen(true);
      return;
    }
    if (!open) return;
    if (e.key === "Escape" || e.key === "Tab") setOpen(false);
    else if (e.key === "ArrowDown") (e.preventDefault(), setActive((a) => Math.min(a + 1, options.length - 1)));
    else if (e.key === "ArrowUp") (e.preventDefault(), setActive((a) => Math.max(a - 1, 0)));
    else if (e.key === "Enter" || e.key === " ") (e.preventDefault(), pick(active));
    else if (e.key.length === 1) {
      const i = options.findIndex((o) => o.label.toLowerCase().startsWith(e.key.toLowerCase()));
      if (i >= 0) setActive(i);
    }
  };

  return (
    <div ref={root} className={`relative ${inline ? "inline-flex items-center gap-2" : "grid gap-2"}`}>
      <span id={`${id}-label`} className={inline ? "text-sm text-mute" : "text-sm"}>
        {label}
      </span>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-label ${id}-value`}
        aria-activedescendant={open ? `${id}-${active}` : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={onKey}
        className={`flex h-10 items-center justify-between gap-3 border bg-bg px-3 text-left text-sm transition-colors duration-150 hover:border-line-hi ${
          open ? "border-acc" : "border-line"
        } ${inline ? "min-w-[150px]" : "w-full"}`}
      >
        <span id={`${id}-value`}>{current.label}</span>
        <CaretDown size={14} className={`text-mute ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <ul
          role="listbox"
          aria-labelledby={`${id}-label`}
          className={`absolute z-30 border border-line-hi bg-panel-2 py-1 shadow-[0_18px_40px_rgb(0_0_0/0.6)] ${
            inline ? "top-full right-0 mt-1 min-w-[180px]" : "top-full left-0 mt-1 w-full"
          }`}
        >
          {options.map((o, i) => (
            <li
              key={o.value}
              id={`${id}-${i}`}
              role="option"
              aria-selected={o.value === value}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => (e.preventDefault(), pick(i))}
              className={`flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm ${
                i === active ? "bg-line text-fg" : "text-fg/85"
              }`}
            >
              {o.label}
              {o.value === value && <Check size={14} className="text-acc" aria-hidden />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
