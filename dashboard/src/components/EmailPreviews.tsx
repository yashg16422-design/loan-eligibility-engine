// What Workflow C emailed for an upload: up to three of its customers' emails, rebuilt from
// the same matches and the same ranking C uses (best offer per lender), with the test inbox
// each one went to. Shown because result emails only reach the project's test inboxes.
import { EnvelopeSimple } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { EmailPreview } from "../api/types";
import { CHANNEL_LABEL } from "../lib/offers";
import { Disclosure } from "../ui/Disclosure";

function rate(min: number | null, max: number | null): string {
  if (min == null) return "rate on request";
  return max == null || max === min ? `from ${min}% p.a.` : `${min}% to ${max}% p.a.`;
}

export function EmailPreviews({ jobId, kept = false }: { jobId: string; kept?: boolean }) {
  const [emails, setEmails] = useState<EmailPreview[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  useEffect(() => {
    let gone = false;
    setEmails(null);
    setFailed(null);
    api.emailPreviews(jobId).then((e) => !gone && setEmails(e)).catch((err) => !gone && setFailed(err instanceof Error ? err.message : "Could not load the emails."));
    return () => {
      gone = true;
    };
  }, [jobId]);
  if (failed || (emails && emails.length === 0)) return null; // nothing emailed for this dataset
  return (
    <div className="mt-10 border-t border-line">
      <Disclosure title="Emails sent for this upload" meta={emails ? `${emails.length} examples` : "loading"}>
        <p className="max-w-[70ch] text-sm text-mute">
          Workflow C emails every matched customer. As the assignment requires, these go to the project's test inboxes,
          never to addresses in the file. Below are emails from this upload as they were sent: same picks, same order.
          {kept && " This upload's records were deleted; these examples were kept from just before."}
        </p>
        {!emails ? (
          <p className="label mt-6">Loading emails</p>
        ) : (
          <ul className="mt-6 grid gap-px border border-line bg-line xl:grid-cols-3">
            {emails.map((e) => <Email key={e.user_id} email={e} />)}
          </ul>
        )}
      </Disclosure>
    </div>
  );
}

function Email({ email: e }: { email: EmailPreview }) {
  const first = e.name?.split(/\s+/)[0] || "there";
  const best = e.picks[0];
  const subject = best
    ? `${first}, you may qualify for ${e.lenders_total} personal loan${e.lenders_total === 1 ? "" : "s"} (best: ${best.lender})`
    : `${first}, your loan matches`;
  return (
    <li className="min-w-0 bg-bg p-6">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 border-b border-line pb-4 text-sm">
        <dt className="label">To</dt>
        <dd className="truncate">{e.alias_email ?? "not sent (demo cap)"}</dd>
        <dt className="label">Sent</dt>
        <dd className="text-mute">{e.sent_at ? new Date(e.sent_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "-"}</dd>
        <dt className="label">Subject</dt>
        <dd className="text-fg">{subject}</dd>
      </dl>
      <div className="mt-4 text-sm text-mute">
        <p className="flex items-center gap-2 text-fg"><EnvelopeSimple size={16} aria-hidden /> Hi {first},</p>
        <p className="mt-2">Based on the criteria lenders publish, here are your best options:</p>
        <ol className="mt-4 grid gap-3">
          {e.picks.map((p, i) => (
            <li key={p.lender} className="border-l border-line-hi pl-3">
              <p className="text-fg">
                {i === 0 && <span className="label mr-2 text-acc">Best pick</span>}
                {p.lender} <span className="text-mute">on {CHANNEL_LABEL[p.channel]}</span>
              </p>
              <p className="mt-0.5">
                <span className={p.tier === "eligible" ? "text-acc" : "text-amber"}>{p.tier === "eligible" ? "Eligible" : "May qualify"}</span>
                {" · "}{rate(p.interest_rate_min, p.interest_rate_max)}
              </p>
              {p.requirements && <p className="mt-0.5 line-clamp-2">Also needed: {p.requirements}</p>}
            </li>
          ))}
        </ol>
        <p className="mt-4 inline-block border border-line-hi px-3 py-1.5 text-fg">View all {e.matches_total} matches</p>
      </div>
    </li>
  );
}
