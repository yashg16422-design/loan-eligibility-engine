import { Trash } from "@phosphor-icons/react";
import { useState } from "react";

/**
 * A destructive action that asks once, in place: the button turns into a sentence saying exactly
 * what will be deleted, with Delete and Cancel. No modal, no browser confirm().
 */
export function ConfirmDelete({
  label,
  question,
  onConfirm,
  disabled = false,
  small = false,
}: {
  label: string;
  question: string;
  onConfirm: () => Promise<void>;
  disabled?: boolean;
  small?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const size = small ? "min-h-9 px-3 text-sm" : "";
  if (!asking) {
    return (
      <button type="button" disabled={disabled} onClick={() => setAsking(true)} className={`btn btn-ghost hover:border-coral hover:text-coral ${size}`}>
        <Trash size={16} aria-hidden /> {label}
      </button>
    );
  }
  return (
    <span role="group" aria-label={label} className="inline-flex flex-wrap items-center gap-3">
      <span className="text-sm text-fg">{question}</span>
      <button
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
            setAsking(false);
          }
        }}
        className={`btn border-coral bg-coral/15 text-coral hover:bg-coral/25 ${size}`}
      >
        {busy ? "Deleting" : "Delete"}
      </button>
      <button type="button" disabled={busy} onClick={() => setAsking(false)} className={`btn btn-ghost ${size}`}>
        Cancel
      </button>
    </span>
  );
}
