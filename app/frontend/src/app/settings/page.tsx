import AppNavbar from "@/components/Shared/AppNavbar";
import { requireSession } from "@/lib/session";
import SettingsTabs from "./SettingsTabs";

export default async function SettingsPage() {
  const { user } = await requireSession();
  const isAdmin = user?.role === "admin";
  return (
    <>
      <AppNavbar />
      <main className="max-w-2xl mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">Settings</h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          Signed in as <span className="text-ink">{user?.email}</span>.
          {isAdmin ? " You can manage the catalog and API keys here." : ""}
        </p>
        <SettingsTabs
          isAdmin={isAdmin}
          initialFirst={user?.firstName ?? ""}
          initialLast={user?.lastName ?? ""}
        />
      </main>
    </>
  );
}
