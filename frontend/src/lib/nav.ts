// The main menu and "simple mode". Pure (tested in nav.test.ts).

export type NavLink = { href: string; label: string; adminOnly?: boolean };
export type NavGroup = { title: string; links: NavLink[] };

/** Advanced pages hidden from the menu in simple mode (still reachable by URL). */
export const ADVANCED = ["/valuation", "/overlap", "/fundamentals", "/macro"];
/** Never hidden, in any mode. */
export const ALWAYS_VISIBLE = ["/", "/holdings/stocks", "/holdings/funds", "/allocation", "/simulator", "/planner", "/projection", "/help"];

export const GROUPS: NavGroup[] = [
  { title: "Overview", links: [
    { href: "/", label: "Dashboard" },
    { href: "/history", label: "History" },
    { href: "/changes", label: "Changes" },
    { href: "/alerts", label: "Alerts" },
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
    { href: "/valuation", label: "Valuation & peers" },
    { href: "/news", label: "News & announcements" },
    { href: "/macro", label: "Macro & scenarios" },
    { href: "/analysis", label: "AI analysis" },
  ] },
  { title: "Planning", links: [
    { href: "/simulator", label: "Next contribution" },
    { href: "/planner", label: "Monthly planner" },
    { href: "/projection", label: "Projection" },
    { href: "/emergency-fund", label: "Emergency fund" },
    { href: "/journal", label: "Thesis journal" },
    { href: "/strategy", label: "Strategy vs actual" },
  ] },
  { title: "Data", links: [
    { href: "/monthly", label: "Monthly update" },
    { href: "/import", label: "Import" },
    { href: "/mappings", label: "Mappings" },
    { href: "/classification", label: "Classification" },
    { href: "/sources", label: "Source health" },
    { href: "/settings", label: "Settings" },
  ] },
  { title: "You", links: [
    { href: "/account", label: "Account" },
    { href: "/admin", label: "Admin", adminOnly: true },
    { href: "/help", label: "How to use" },
    { href: "/terms", label: "Terms & data" },
  ] },
];


export function visibleGroups(groups: NavGroup[], opts: { isAdmin: boolean; simple: boolean }): NavGroup[] {
  return groups
    .map((g) => ({
      ...g,
      links: g.links.filter((l) => (!l.adminOnly || opts.isAdmin)
        && (!opts.simple || !ADVANCED.includes(l.href) || ALWAYS_VISIBLE.includes(l.href))),
    }))
    .filter((g) => g.links.length > 0);
}

export function isAdvanced(path: string): boolean {
  return ADVANCED.some((p) => path === p || path.startsWith(`${p}/`));
}
