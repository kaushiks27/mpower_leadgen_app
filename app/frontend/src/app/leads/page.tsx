import AppNavbar from "@/components/Shared/AppNavbar";
import { requireSession } from "@/lib/session";
import LeadsTabs from "./LeadsTabs";

export default async function LeadsPage() {
  await requireSession(); // both admin + rep
  return (
    <>
      <AppNavbar />
      <main className="max-w-6xl mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">Leads</h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          Every captured lead lives here, deduped and contacted once. Scrapers
          fill this in the next slices — for now you&apos;re looking at sample
          leads. The do-not-contact list keeps anyone you&apos;ve flagged out of
          future sends.
        </p>
        <LeadsTabs />
      </main>
    </>
  );
}
