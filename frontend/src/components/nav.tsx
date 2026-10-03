"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const GROUPS = [
  { title: "Overview", links: [
    { href: "/", label: "Dashboard" },
    { href: "/history", label: "History" },
    { href: "/changes", label: "Changes" },
  ] },
  { title: "Holdings", links: [
    { href: "/holdings/stocks", label: "Stocks & ETFs" },
    { href: "/holdings/funds", label: "Mutual funds" },
    { href: "/transactions", label: "Transactions" },
  ] },
  { title: "Analysis", links: [
    { href: "/health", label: "Portfolio health" },
    { href: "/allocation", label: "Allocation" },
    { href: "/sectors", label: "Sectors" },
    { href: "/overlap", label: "Fund look-through" },
    { href: "/fundamentals", label: "Fundamentals" },
  ] },
  { title: "Planning", links: [
    { href: "/simulator", label: "Next contribution" },
    { href: "/planner", label: "Monthly planner" },
    { href: "/projection", label: "Projection" },
    { href: "/emergency-fund", label: "Emergency fund" },
  ] },
  { title: "Data", links: [
    { href: "/import", label: "Import" },
    { href: "/mappings", label: "Mappings" },
    { href: "/classification", label: "Classification" },
    { href: "/settings", label: "Settings" },
  ] },
];

export function Nav() {
  const path = usePathname();
  return (
    <nav aria-label="Main" className="flex gap-1 overflow-x-auto md:flex-col md:gap-4 md:overflow-visible">
      {GROUPS.map((g) => (
        <div key={g.title} className="flex gap-1 md:flex-col">
          <div className="hidden px-3 text-[11px] font-medium tracking-wide text-muted-foreground/70 uppercase md:block">
            {g.title}
          </div>
          {g.links.map((l) => {
            const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm whitespace-nowrap text-muted-foreground hover:bg-muted hover:text-foreground",
                  active && "bg-muted font-medium text-foreground",
                )}
              >
                {l.label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
