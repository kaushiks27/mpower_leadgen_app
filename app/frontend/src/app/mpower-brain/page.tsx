import AppNavbar from "@/components/Shared/AppNavbar";
import { requireAdmin } from "@/lib/session";

import MpowerBrainTabs from "./MpowerBrainTabs";
import ProductsServicesClient from "./ProductsServicesClient";

export default async function MpowerBrainPage() {
  await requireAdmin(); // redirects non-admins to /dashboard
  return (
    <>
      <AppNavbar />
      <main className="max-w-5xl mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">
          mPower&apos;s Brain
        </h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          mPower&apos;s proprietary knowledge base. Start with the products and
          services we sell — competitor and OEM intelligence land here next.
        </p>
        <MpowerBrainTabs />
        <ProductsServicesClient />
      </main>
    </>
  );
}
