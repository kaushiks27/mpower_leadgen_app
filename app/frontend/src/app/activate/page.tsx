import AuthShell from "@/components/Shared/AuthShell";
import ActivateForm from "./ActivateForm";

export default function ActivatePage({
  searchParams,
}: {
  searchParams: { token?: string };
}) {
  const token = searchParams.token ?? "";
  return (
    <AuthShell title="Set your password" subtitle="Activate your account to get started.">
      <ActivateForm token={token} />
    </AuthShell>
  );
}
