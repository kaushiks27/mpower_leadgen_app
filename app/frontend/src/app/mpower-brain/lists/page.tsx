import AppNavbar from "@/components/Shared/AppNavbar";
import { requireAdmin } from "@/lib/session";

import MpowerBrainTabs from "../MpowerBrainTabs";
import ListsClient from "./ListsClient";

export default async function ListsPage() {
  await requireAdmin(); // redirects non-admins to /dashboard
  return (
    <>
      <AppNavbar />
      <main className="max-w-5xl mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">
          mPower&apos;s Brain
        </h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          The live building blocks the lead generator draws on — categories,
          customer types, countries, customers, and the decision-maker roles we
          target. These auto-update from your data; this view is read-only.
        </p>
        <MpowerBrainTabs />
        <ListsClient />
      </main>
    </>
  );
}
