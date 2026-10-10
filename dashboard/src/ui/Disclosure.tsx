import { Minus, Plus } from "@phosphor-icons/react";
import { useId, useState, type ReactNode } from "react";

/**
 * A full-width row that opens a panel beneath it: the extras (history, runs, retries) stay one
 * click away instead of crowding the page. No animation: the panel is simply there or not.
 */
export function Disclosure({
  title,
  meta,
  defaultOpen = false,
  children,
}: {
  title: string;
  meta?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className="border-b border-line">
      <h3>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((o) => !o)}
          className="group grid w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-6 py-6 text-left"
        >
          <span className="text-xl font-light tracking-[-0.02em] text-fg">{title}</span>
          {meta && <span className="label hidden sm:inline">{meta}</span>}
          <span aria-hidden className="grid size-9 place-items-center border border-line-hi text-mute transition-colors duration-150 group-hover:border-fg group-hover:text-fg">
            {open ? <Minus size={14} /> : <Plus size={14} />}
          </span>
        </button>
      </h3>
      <div id={id} hidden={!open} className="pb-10">
        {open && children}
      </div>
    </div>
  );
}
