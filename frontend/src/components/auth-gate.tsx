"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { Loading } from "@/components/common";
import { useApi } from "@/lib/api";
import { AUTH_MODE, PUBLIC_PATHS, useSession } from "@/lib/auth";

export type Me = {
  id: number; email: string; role: "admin" | "user"; is_admin: boolean; has_data: boolean;
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
