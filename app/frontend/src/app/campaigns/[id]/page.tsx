import Link from "next/link";

import AppNavbar from "@/components/Shared/AppNavbar";
import { requireAdmin } from "@/lib/session";
import CampaignEditor from "./CampaignEditor";

export default async function EditCampaignPage({
  params,
}: {
  params: { id: string };
}) {
  await requireAdmin(); // redirects non-admins to /dashboard
  const id = Number(params.id);
  return (
    <>
      <AppNavbar />
      <main className="max-w-3xl mx-auto px-6 py-10">
        <Link
          href="/campaigns"
          className="text-sm font-body text-ink/55 hover:text-ink btn-press"
        >
          ← Back to campaigns
        </Link>
        <h1 className="font-heading text-2xl font-semibold text-ink mt-3">
          Edit campaign
        </h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          Review the lead mix, add leads, edit the send window or email sequence,
          and push to Instantly.
        </p>
        <CampaignEditor campaignId={id} />
      </main>
    </>
  );
}
