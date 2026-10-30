import AuthShell from "@/components/Shared/AuthShell";
import ResetForm from "./ResetForm";

export default function ResetPasswordPage({
  searchParams,
}: {
  searchParams: { token?: string };
}) {
  const token = searchParams.token ?? "";
  return (
    <AuthShell title="Reset password" subtitle="Choose a new password.">
      <ResetForm token={token} />
    </AuthShell>
  );
}
