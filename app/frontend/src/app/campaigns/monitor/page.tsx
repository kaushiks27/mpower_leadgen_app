import AppNavbar from "@/components/Shared/AppNavbar";
import { requireAdmin } from "@/lib/session";
import CampaignTabs from "../CampaignTabs";
import MonitorPanel from "./MonitorPanel";

// Live campaign Monitor (S-9). Lists every pushed Instantly campaign with a Sync
// button that pulls reply/bounce/unsub status back into the pipeline.
export default async function CampaignMonitorPage() {
  await requireAdmin(); // redirects non-admins to /dashboard
  return (
    <>
      <AppNavbar />
      <main className="max-w-4xl mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">Campaigns</h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          Track live campaigns once they are sending through Instantly.
        </p>
        <CampaignTabs />
        <MonitorPanel />
      </main>
    </>
  );
}
