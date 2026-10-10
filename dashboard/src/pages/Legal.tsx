// Privacy policy and terms: plain statements of what this service actually does with data.
import type { ReactNode } from "react";

function Page({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-[760px] px-5 pt-14 pb-20 sm:px-10 lg:pt-24">
      <h1 className="text-[2.75rem] sm:text-[3.5rem]">{title}</h1>
      <p className="label mt-4">Last updated {updated}</p>
      <div className="mt-10 grid gap-8 text-mute [&_h2]:text-xl [&_h2]:text-fg [&_li]:mt-1.5 [&_ul]:list-disc [&_ul]:pl-5">{children}</div>
    </article>
  );
}

export function Privacy() {
  return (
    <Page title="Privacy policy" updated="10 October 2026">
      <section>
        <h2>Who we are</h2>
        <p className="mt-3">ClickPar Match checks loan eligibility against lenders' published criteria. It is a demonstration service built for an engineering assessment, operated by its developer.</p>
      </section>
      <section>
        <h2>What we collect</h2>
        <ul className="mt-3">
          <li><b className="text-fg">Account:</b> your email address, and your name if you sign in with Google. Passwords are handled only by Amazon Cognito; we never see or store them.</li>
          <li><b className="text-fg">Eligibility checks:</b> the four numbers you enter (monthly income, credit score, age, how you earn) and an optional first name.</li>
          <li><b className="text-fg">Bulk uploads (merchants):</b> the CSV rows you upload, kept with your account.</li>
        </ul>
      </section>
      <section>
        <h2>How we use it</h2>
        <p className="mt-3">Only to match profiles against lenders' published criteria and show the results. Result emails go only to the project's own test inboxes, never to addresses in an uploaded file. We do not sell or share data, and we run no advertising or tracking.</p>
      </section>
      <section>
        <h2>Where it is stored</h2>
        <p className="mt-3">In Amazon Web Services, Sydney region (ap-southeast-2): accounts in Amazon Cognito, data in an encrypted PostgreSQL database and an encrypted S3 bucket, neither reachable from the internet.</p>
      </section>
      <section>
        <h2>Deleting your data</h2>
        <ul className="mt-3">
          <li>A check: "Start over" on your results page deletes it and its matches.</li>
          <li>Saved checks: "Start fresh" on your account page.</li>
          <li>Uploads: "Delete" on each upload in the merchant console removes its customers, matches and email records.</li>
        </ul>
      </section>
      <section>
        <h2>Contact</h2>
        <p className="mt-3">Questions or deletion requests: yashg16422@gmail.com.</p>
      </section>
    </Page>
  );
}

export function Terms() {
  return (
    <Page title="Terms of use" updated="10 October 2026">
      <section>
        <h2>Indicative only</h2>
        <p className="mt-3">Results are indicative, based on criteria lenders publish. They are not a loan offer, an approval or financial advice; the lender decides. Checking never affects your credit score.</p>
      </section>
      <section>
        <h2>Fair use</h2>
        <p className="mt-3">This is a demonstration service with daily limits. Upload only data you are allowed to process, and do not try to access other accounts' data.</p>
      </section>
      <section>
        <h2>No warranty</h2>
        <p className="mt-3">The service is provided as is, without guarantees of availability or accuracy. Lender criteria change; results reflect the last daily read of their sites.</p>
      </section>
      <section>
        <h2>Contact</h2>
        <p className="mt-3">yashg16422@gmail.com</p>
      </section>
    </Page>
  );
}
