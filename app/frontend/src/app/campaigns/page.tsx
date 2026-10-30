import AppNavbar from "@/components/Shared/AppNavbar";
import { requireAdmin } from "@/lib/session";
import CampaignsListClient from "./CampaignsListClient";
import CampaignTabs from "./CampaignTabs";

export default async function CampaignsPage() {
  await requireAdmin(); // redirects non-admins to /dashboard
  return (
    <>
      <AppNavbar />
      <main className="max-w-4xl mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">Campaigns</h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          Design an outreach campaign: pick who you&apos;re targeting, when to send,
          and write the email sequence. Nothing sends yet — this is the blueprint.
        </p>
        <CampaignTabs />
        <CampaignsListClient />
      </main>
    </>
  );
}
