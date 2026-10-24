import Link from "next/link";
import { PageHeader, Section } from "@/components/common";

// Plain-language guide for friends and family. Public (readable before signing in); linked from the menu, the
// footer and the sign-in page.
export default function HelpPage() {
  return (
    <>
      <PageHeader title="How to use this app" subtitle="A short guide. Five minutes to read, about twenty to set up." />
      <div className="flex max-w-3xl flex-col gap-4 text-sm leading-relaxed">
        <Section title="What it is (and isn't)">
          <ul className="list-disc space-y-1 pl-5">
            <li>It shows your investments (stocks, ETFs and mutual funds) in one place: what they are worth, how they
              are split, and how that compares with the mix you want.</li>
            <li>It works only from what you type into an Excel file (or add on the Transactions page). It never
              connects to your broker or bank and it can&apos;t buy or sell anything.</li>
            <li>It is an analytics tool, <b>not investment advice</b>. Scenarios and projections are maths with stated
              assumptions, not predictions.</li>
          </ul>
        </Section>

        <Section title="1. Sign in">
          <p>Open the app and enter the email you were invited with. You get an email with a sign-in link and a
            6-digit code; there is no password. Either open the link <b>in the same browser</b> where you asked for it,
            or type the code on the sign-in page (this works from any browser or device, e.g. when you read the email
            on your phone). If no email arrives, check spam, then ask the person who invited you.</p>
        </Section>

        <Section title="2. Put your investments in the Excel template">
          <ol className="list-decimal space-y-1 pl-5">
            <li>On the Dashboard, press <b>Download the Excel template</b>.</li>
            <li>In the <i>transactions</i> sheet, add one row per purchase, SIP instalment, sale or dividend. If you
              don&apos;t have the history, one <b>OPENING</b> row per holding (today&apos;s quantity and what you paid in
              total) is enough.</li>
            <li>Optional: the <i>monthly_plan</i> sheet holds how much you invest each month and where.</li>
          </ol>
          <p className="mt-2">You don&apos;t need account numbers, folio numbers, PAN or login details anywhere. Please
            don&apos;t add them.</p>
        </Section>

        <Section title="3. Import it">
          <ol className="list-decimal space-y-1 pl-5">
            <li>Go to <Link className="underline" href="/import">Import</Link> and choose your file. You see a preview
              first; <b>nothing changes until you press Confirm</b>.</li>
            <li>Go to <Link className="underline" href="/mappings">Mappings</Link> and confirm the suggested codes for
              your stocks and funds (&quot;Confirm all exact matches&quot; does most of it). Funds get their daily NAV only
              after you confirm their scheme code.</li>
            <li>Prices and NAVs update every evening. A number with no price shows &quot;Data unavailable&quot; rather
              than a guess.</li>
          </ol>
        </Section>

        <Section title="4. Each month">
          <p>Add the new rows to the same Excel file and import it again: rows already in the app are recognised, so
            nothing is counted twice. Keep the old rows in the file: a row you delete from the Excel is removed from the app
            at the next import (the preview shows it first). For a single purchase you can also use{" "}
            <b>Transactions › Add transaction</b>. The{" "}
            <Link className="underline" href="/monthly">Monthly update</Link> page walks you through it.</p>
        </Section>

        <Section title="The main pages">
          <ul className="list-disc space-y-1 pl-5">
            <li><b>Dashboard</b>: total value, what you put in, gain or loss, and the date of every price used.</li>
            <li><b>Stocks &amp; ETFs</b>, <b>Mutual funds</b>: each holding with its value and return.</li>
            <li><b>Allocation</b>: your mix by asset class, and how far it is from your targets (set them in Settings).</li>
            <li><b>Next contribution</b>: what adding an amount to one holding would do to your mix, e.g. &quot;Adding ₹1,000
              here would raise X from a% to b%&quot;.</li>
            <li><b>Monthly planner</b> and <b>Projection</b>: your monthly plan, and a &quot;what if it grew at X% a year&quot;
              calculation with the assumptions shown.</li>
          </ul>
          <p className="mt-2"><b>Simple mode</b> (on by default) hides the advanced pages from the menu. Turn it off on
            the <Link className="underline" href="/account">Account</Link> page if you want them.</p>
        </Section>

        <Section title="Your privacy">
          <ul className="list-disc space-y-1 pl-5">
            <li>Only you see your data in the app. The admin page shows how many rows you have, not your figures.</li>
            <li>AI analysis is off unless the admin enables it for you and you switch it on. It sends percentages,
              never rupee amounts.</li>
            <li><Link className="underline" href="/account">Account</Link> › <b>Export my data</b> gives you everything as
              Excel; <b>Delete my account</b> removes it all. Details on the{" "}
              <Link className="underline" href="/terms">Terms &amp; data</Link> page.</li>
          </ul>
        </Section>

        <Section title="If something looks wrong">
          <ul className="list-disc space-y-1 pl-5">
            <li><b>&quot;The server is waking up&quot;</b>: the server may have been asleep. Wait up to a minute; it retries
              by itself (or press <b>Retry now</b>).</li>
            <li>An error box shows a <b>request id</b>. Copy it into your message; it lets the admin find the problem
              without seeing your data.</li>
            <li>Use <b>Send feedback</b> at the bottom of any page. Describe what you saw and on which page, but
              please no account numbers or personal financial figures.</li>
          </ul>
        </Section>
      </div>
    </>
  );
}
