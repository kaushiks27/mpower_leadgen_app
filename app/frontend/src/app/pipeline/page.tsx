import AppNavbar from "@/components/Shared/AppNavbar";
import { requireSession } from "@/lib/session";
import PipelineBoard from "./PipelineBoard";

export default async function PipelinePage() {
  await requireSession(); // both admin + rep
  return (
    <>
      <AppNavbar />
      <main className="max-w-[1400px] mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">Pipeline</h1>
        <p className="text-ink/55 mt-1.5 mb-8">
          The full funnel. Drag a lead between stages — every move is recorded
          (who moved it, when, and from where).
        </p>
        <PipelineBoard />
      </main>
    </>
  );
}
