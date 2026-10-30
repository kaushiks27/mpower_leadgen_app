import { redirect } from "next/navigation";

// 08062026_cr CR-3/4/5 — the full-page create form is replaced by an in-app
// modal launched from the campaigns list. This route now just redirects there.
export default function NewCampaignPage() {
  redirect("/campaigns");
}
