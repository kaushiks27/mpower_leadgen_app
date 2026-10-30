import AppNavbar from "@/components/Shared/AppNavbar";
import { requireAdmin } from "@/lib/session";
import AdminUsersClient from "./AdminUsersClient";

export default async function AdminUsersPage() {
  await requireAdmin(); // redirects non-admins to /dashboard
  return (
    <>
      <AppNavbar />
      <main className="max-w-4xl mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">Users</h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          Invite teammates, change their role, or remove them. Invites are
          emailed; the new person sets their own password.
        </p>
        <AdminUsersClient />
      </main>
    </>
  );
}
