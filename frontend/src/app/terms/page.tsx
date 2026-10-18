import { PageHeader, Section } from "@/components/common";

export const metadata = { title: "Terms & data · Portfolio Analytics" };

// Set to the database backup retention of the hosting plan (docs/DEPLOY.md §18). Static: inlined at build time.
const RETENTION_DAYS = process.env.NEXT_PUBLIC_BACKUP_RETENTION_DAYS || "7";

export default function TermsPage() {
  return (
    <>
      <PageHeader title="Terms and data" subtitle="Plain-language summary of what this app is, what it stores and who can see it." />
      <div className="flex flex-col gap-4 text-sm leading-relaxed">
        <Section title="What this app is">
          <p>
            A private, invite-only <b>analytics</b> tool for a small group of friends and family. It reads the Excel
            workbook you upload and shows allocation, history, concentration and similar views. It is <b>not
            investment advice</b>, and neither the app nor the person running it is a SEBI-registered investment
            adviser or research analyst. It never places orders and never connects to a broker or your trading
            account. Scenarios and projections are mathematical illustrations, not predictions.
          </p>
        </Section>
        <Section title="What is stored">
          <ul className="list-disc space-y-1 pl-5">
            <li>Your email address (to sign you in) and when you were last active.</li>
            <li>What you upload or enter: transactions, holdings, monthly plan, settings, targets, emergency-fund
              figures, thesis journal and notes, peers, fund disclosure files, and AI analyses you request.</li>
            <li>Shared market data (prices, NAVs, fundamentals, news headlines, macro values). It contains nothing
              about you.</li>
            <li>Technical logs with a numeric user id and request ids, never your financial figures, file contents,
              journal text or keys.</li>
          </ul>
        </Section>
        <Section title="Who can see it">
          <p>
            Only you see your data in the app; every request is checked against your account, and other users cannot
            read it. Technically, the admin who runs the server and database can access the stored data. The admin
            page shows only counts (for example, how many transactions you have), not your figures.
          </p>
          <p className="mt-2">
            If AI analysis is enabled for you and you turn it on, the inputs listed on the AI analysis page
            (percentages, not rupee amounts) are sent to the AI provider. Journal text is sent only for holdings
            where you opt in.
          </p>
        </Section>
        <Section title="Deleting your data">
          <p>
            Account › <b>Export my data</b> downloads everything you entered as Excel. Account › <b>Delete my account
            and all data</b> removes it from the live database <b>immediately</b>: your transactions, holdings,
            snapshots, settings, journal, notes, uploads and analyses, and your sign-in account. You can also ask the
            admin to do it for you.
          </p>
          <p className="mt-2">
            <b>Backups:</b> the hosting provider keeps automatic database backups for up to <b>{RETENTION_DAYS} days</b>.
            A deleted account still exists in backups made before the deletion until they expire, at the latest{" "}
            {RETENTION_DAYS} days after you delete it. Backups are only used to recover from an outage or a mistake. If one
            is ever restored, your deletion is carried out again before the app is reopened. Application logs never
            contain your figures, workbook contents, journal text or email (only a numeric account id).
          </p>
        </Section>
        <Section title="Limits of the data">
          <p>
            Prices and fundamentals come from public sources (Yahoo Finance via yfinance, AMFI, NSE lists). They can
            be delayed, incomplete or wrong; anything missing is shown as unavailable rather than estimated. Always
            check important figures against your broker, AMC or the exchange.
          </p>
        </Section>
      </div>
    </>
  );
}
