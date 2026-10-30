import AuthShell from "@/components/Shared/AuthShell";
import ForgotForm from "./ForgotForm";

export default function ForgotPasswordPage() {
  return (
    <AuthShell
      title="Forgot password"
      subtitle="We'll email you a link to reset it."
    >
      <ForgotForm />
    </AuthShell>
  );
}
