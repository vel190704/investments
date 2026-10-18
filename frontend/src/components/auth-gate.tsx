"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { Loading } from "@/components/common";
import { useApi } from "@/lib/api";
import { AUTH_MODE, PUBLIC_PATHS, useSession } from "@/lib/auth";
import { isAdvanced } from "@/lib/nav";

export type Me = {
  id: number; email: string; role: "admin" | "user"; is_admin: boolean; has_data: boolean;
  simple_mode: boolean; simple_mode_chosen: boolean | null;
  ai: { calls_this_month: number; cap: number; ai_enabled_by_admin: boolean; own_key: boolean };
};

const MeContext = createContext<{ me: Me | null; reload: () => void }>({ me: null, reload: () => {} });
export const useMe = () => useContext(MeContext);

/** Every page except the public ones needs a signed-in, invited user (Supabase mode). Dev mode: always allowed. */
export function AuthGate({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const session = useSession();
  const isPublic = PUBLIC_PATHS.includes(path);
  const signedOut = AUTH_MODE === "supabase" && session === null;
  useEffect(() => {
    if (signedOut && !isPublic) router.replace("/login");
  }, [signedOut, isPublic, router]);
  if (isPublic) return <>{children}</>;
  if (session === undefined || signedOut) return <div className="p-6"><Loading /></div>;
  return <MeLoader>{children}</MeLoader>;
}

function MeLoader({ children }: { children: ReactNode }) {
  const { data, error, reload } = useApi<Me>("/me");
  if (error) {
    return (
      <div role="alert" className="m-6 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
        {error.includes("not invited") || error.includes("invitation was removed")
          ? "This email has not been invited to the app (or the invitation was removed). Ask the admin."
          : error}
      </div>
    );
  }
  return <MeContext.Provider value={{ me: data, reload }}>{children}</MeContext.Provider>;
}

/** Shown on an advanced page opened directly while simple mode hides it from the menu. */
export function AdvancedPageNote() {
  const path = usePathname();
  const { me } = useMe();
  if (!me?.simple_mode || !isAdvanced(path)) return null;
  return (
    <p className="mb-4 rounded-md border border-border px-3 py-2 text-xs text-muted-foreground">
      This is an advanced page, hidden from the menu in simple mode. Turn simple mode off on the Account page to
      list it.
    </p>
  );
}
