import AppNavbar from "@/components/Shared/AppNavbar";
import { requireAdmin } from "@/lib/session";

import MpowerBrainTabs from "../MpowerBrainTabs";
import CompetitorsClient from "./CompetitorsClient";

export default async function CompetitorsPage() {
  await requireAdmin(); // redirects non-admins to /dashboard
  return (
    <>
      <AppNavbar />
      <main className="max-w-5xl mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">mPower&apos;s Brain</h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          mPower&apos;s proprietary knowledge base. Competitors — every drone-battery /
          pack manufacturer worldwide, split into Global and Local (India).
        </p>
        <MpowerBrainTabs />
        <CompetitorsClient />
      </main>
    </>
  );
}
