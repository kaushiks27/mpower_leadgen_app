import AuthShell from "@/components/Shared/AuthShell";
import { redirectIfSignedIn } from "@/lib/session";
import LoginForm from "./LoginForm";

export default async function LoginPage() {
  await redirectIfSignedIn();
  return (
    <AuthShell title="Sign in" subtitle="Welcome back to your pipeline.">
      <LoginForm />
    </AuthShell>
  );
}
