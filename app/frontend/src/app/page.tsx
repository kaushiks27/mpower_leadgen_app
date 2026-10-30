import { redirect } from "next/navigation";

import { getSession } from "@/lib/session";

// No public landing page (App only). Root redirects by auth state.
export default async function Home() {
  const { signedIn } = await getSession();
  redirect(signedIn ? "/dashboard" : "/login");
}
