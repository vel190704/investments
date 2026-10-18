"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe } from "@/components/auth-gate";
import { AUTH_MODE, PUBLIC_PATHS, signOut } from "@/lib/auth";
import { GROUPS, visibleGroups } from "@/lib/nav";
import { cn } from "@/lib/utils";

export function Nav() {
  const path = usePathname();
  const { me } = useMe();
  if (PUBLIC_PATHS.includes(path) && path !== "/terms") return null;
  return (
    <nav aria-label="Main" className="flex gap-1 overflow-x-auto md:flex-col md:gap-4 md:overflow-visible">
      {visibleGroups(GROUPS, { isAdmin: !!me?.is_admin, simple: !!me?.simple_mode }).map((g) => (
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
      {me && (
        <div className="flex gap-1 md:flex-col">
          <div className="hidden truncate px-3 text-[11px] text-muted-foreground md:block" title={me.email}>{me.email}</div>
          {AUTH_MODE === "supabase" && (
            <button className="rounded-md px-3 py-1.5 text-left text-sm text-muted-foreground hover:bg-muted" onClick={signOut}>
              Sign out
            </button>
          )}
        </div>
      )}
    </nav>
  );
}
