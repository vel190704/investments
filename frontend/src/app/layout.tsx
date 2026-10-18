import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AuthGate } from "@/components/auth-gate";
import { Nav } from "@/components/nav";
import "./globals.css";

const geistSans = Geist({ variable: "--font-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Portfolio Analytics",
  description: "Invite-only portfolio analytics. Not investment advice.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`dark ${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col md:flex-row">
        <AuthGate>
        <aside className="border-b border-border p-3 md:sticky md:top-0 md:h-screen md:w-56 md:overflow-y-auto md:shrink-0 md:border-r md:border-b-0 md:p-4">
          <div className="mb-3 px-3 text-sm font-semibold md:mb-6">Portfolio Analytics</div>
          <Nav />
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8">{children}</main>
          <footer className="border-t border-border px-4 py-4 text-xs text-muted-foreground md:px-8">
            Personal analytics tool, not investment advice. Figures are historical or derived from the stated
            sources and dates; scenarios are mathematical illustrations, not predictions. Nothing here places orders.
            {" "}<a className="underline" href="/terms">Terms &amp; data</a>
          </footer>
        </div>
        </AuthGate>
      </body>
    </html>
  );
}
