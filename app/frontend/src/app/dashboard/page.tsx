import "server-only";

import Link from "next/link";
import { cookies } from "next/headers";

import AppNavbar from "@/components/Shared/AppNavbar";
import { requireSession } from "@/lib/session";

const API_BASE =
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  "http://localhost:8030";
const SESSION_COOKIE = "mp_session";

const STAGES = [
  "new",
  "enriched",
  "queued",
  "emailed",
  "replied",
  "interested",
  "won",
] as const;

type Funnel = {
  campaign_id: number | null;
  campaign_name: string;
  stages: Record<string, number>;
  flags: Record<string, number>;
  total: number;
  contacted: number;
  replied: number;
  positive: number;
  reply_rate: number;
  positive_rate: number;
};
type Goal = {
  pushed_this_month: number;
  goal: number;
  pct: number;
  period: string;
};
type CreditBurn = {
  provider: string;
  used: number;
  limit: number;
  pct: number;
  unlimited: boolean;
};
type HotReply = {
  lead_id: number;
  name: string;
  company: string | null;
  title: string | null;
  campaign_name: string | null;
  value_inr: number | null;
  unibox_url: string;
  lead_url: string;
};
type Summary = {
  active_campaigns: number;
  overall_reply_rate: number;
  overall_positive_rate: number;
  funnels: Funnel[];
  goal: Goal;
  credit_burn: CreditBurn[];
  hot_replies: HotReply[];
};

const inr = (n: number | null) =>
  n == null ? "—" : "₹" + new Intl.NumberFormat("en-IN").format(n);

const PROVIDER_LABEL: Record<string, string> = {
  apollo: "Apollo",
  millionverifier: "MillionVerifier",
};

async function getSummary(): Promise<Summary | null> {
  const token = cookies().get(SESSION_COOKIE)?.value;
  if (!token) return null;
  try {
    const res = await fetch(`${API_BASE}/api/dashboard/summary`, {
      headers: { cookie: `${SESSION_COOKIE}=${token}` },
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as Summary;
  } catch {
    return null;
  }
}

function Card({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="bg-surface border border-ink/10 rounded-2xl p-5 shadow-sm">
      <p className="text-xs font-mono tracking-wider text-ink/40 uppercase">
        {label}
      </p>
      <p className="font-heading text-3xl font-semibold text-ink mt-2">{value}</p>
      {sub && <p className="text-xs text-ink/45 mt-1">{sub}</p>}
    </div>
  );
}

function Bar({ pct }: { pct: number }) {
  const w = Math.max(0, Math.min(100, pct));
  return (
    <div className="h-2 rounded-full bg-ink/10 mt-3 overflow-hidden">
      <div
        className="h-full bg-mpower-orange rounded-full"
        style={{ width: `${w}%` }}
      />
    </div>
  );
}

export default async function DashboardPage() {
  const { user } = await requireSession();
  const name = user?.firstName ? `, ${user.firstName}` : "";
  const data = await getSummary();

  return (
    <>
      <AppNavbar />
      <main className="max-w-7xl mx-auto px-6 py-10">
        <h1 className="font-heading text-2xl font-semibold text-ink">
          Welcome{name}.
        </h1>
        <p className="text-ink/55 mt-1.5">
          Your live lead-gen funnel — replies to action, pipeline, monthly goal,
          and credit burn.
        </p>

        {!data ? (
          <div className="mt-8 bg-surface border border-ink/10 rounded-2xl p-6 text-ink/60">
            Couldn&apos;t load the dashboard right now. Refresh to retry.
          </div>
        ) : (
          <>
            {/* Hot replies — top priority */}
            <section className="mt-8">
              <h2 className="font-heading text-lg font-semibold text-ink mb-3">
                Replies to action
                <span className="ml-2 text-sm font-body font-medium text-ink/45">
                  {data.hot_replies.length}
                </span>
              </h2>
              {data.hot_replies.length === 0 ? (
                <div className="bg-surface border border-ink/10 rounded-2xl p-5 shadow-sm text-sm text-ink/55">
                  <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 align-middle mr-2" />
                  All clear — no replies waiting.
                </div>
              ) : (
                <div className="bg-surface border border-mpower-orange/40 rounded-2xl shadow-sm divide-y divide-ink/10 overflow-hidden">
                  {data.hot_replies.map((h) => (
                    <div
                      key={h.lead_id}
                      className="flex items-center justify-between gap-4 px-5 py-3"
                    >
                      <div className="min-w-0">
                        <Link
                          href={h.lead_url}
                          className="font-medium text-ink hover:text-mpower-orange truncate"
                        >
                          {h.name}
                        </Link>
                        <p className="text-xs text-ink/50 truncate">
                          {[h.title, h.company, h.campaign_name]
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </p>
                      </div>
                      <div className="flex items-center gap-4 shrink-0">
                        <span className="font-mono text-sm text-ink/70">
                          {inr(h.value_inr)}
                        </span>
                        <a
                          href={h.unibox_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-mpower-orange text-white btn-press"
                        >
                          Open in Unibox
                        </a>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Top metrics */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-8">
              <div className="bg-surface border border-ink/10 rounded-2xl p-5 shadow-sm">
                <p className="text-xs font-mono tracking-wider text-ink/40 uppercase">
                  Leads pushed this month
                </p>
                <p className="font-heading text-3xl font-semibold text-ink mt-2">
                  {new Intl.NumberFormat("en-IN").format(
                    data.goal.pushed_this_month
                  )}
                </p>
                <p className="text-xs text-ink/45 mt-1">
                  / {new Intl.NumberFormat("en-IN").format(data.goal.goal)} goal ·{" "}
                  {data.goal.pct}%
                </p>
                <Bar pct={data.goal.pct} />
              </div>
              <Card
                label="Reply rate"
                value={`${data.overall_reply_rate}%`}
                sub="of contacted leads"
              />
              <Card
                label="Positive rate"
                value={`${data.overall_positive_rate}%`}
                sub="replied + interested"
              />
              <Card
                label="Active campaigns"
                value={String(data.active_campaigns)}
                sub="live in Instantly"
              />
            </div>

            {/* Per-campaign funnel */}
            <section className="mt-8">
              <h2 className="font-heading text-lg font-semibold text-ink mb-3">
                Funnel by campaign
              </h2>
              <div className="bg-surface border border-ink/10 rounded-2xl shadow-sm overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs font-mono uppercase tracking-wider text-ink/40 border-b border-ink/10">
                      <th className="px-4 py-3">Campaign</th>
                      {STAGES.map((s) => (
                        <th key={s} className="px-3 py-3 text-right">
                          {s}
                        </th>
                      ))}
                      <th className="px-3 py-3 text-right">Reply%</th>
                      <th className="px-3 py-3 text-right">Pos%</th>
                      <th className="px-4 py-3 text-right">Flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.funnels.map((f) => {
                      const isTotal = f.campaign_name === "All campaigns";
                      const flagBits = [
                        f.flags.bounced ? `B${f.flags.bounced}` : "",
                        f.flags.unsubscribed ? `U${f.flags.unsubscribed}` : "",
                        f.flags.not_interested ? `N${f.flags.not_interested}` : "",
                      ].filter(Boolean);
                      return (
                        <tr
                          key={`${f.campaign_id}-${f.campaign_name}`}
                          className={
                            "border-b border-ink/5 last:border-0 " +
                            (isTotal ? "font-semibold bg-ink/[0.03]" : "")
                          }
                        >
                          <td className="px-4 py-3 text-ink">
                            {f.campaign_name}
                          </td>
                          {STAGES.map((s) => (
                            <td
                              key={s}
                              className="px-3 py-3 text-right text-ink/70 font-mono"
                            >
                              {f.stages[s] ?? 0}
                            </td>
                          ))}
                          <td className="px-3 py-3 text-right text-ink font-mono">
                            {f.reply_rate}%
                          </td>
                          <td className="px-3 py-3 text-right text-ink font-mono">
                            {f.positive_rate}%
                          </td>
                          <td className="px-4 py-3 text-right text-ink/50 font-mono text-xs">
                            {flagBits.length ? flagBits.join(" ") : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-ink/40 mt-2">
                Flags: B = bounced · U = unsubscribed · N = not-interested.
              </p>
            </section>

            {/* Credit burn */}
            <section className="mt-8">
              <h2 className="font-heading text-lg font-semibold text-ink mb-3">
                Credit burn this month
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {data.credit_burn.map((c) => (
                  <div
                    key={c.provider}
                    className="bg-surface border border-ink/10 rounded-2xl p-5 shadow-sm"
                  >
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium text-ink">
                        {PROVIDER_LABEL[c.provider] ?? c.provider}
                      </p>
                      <p className="text-xs font-mono text-ink/50">
                        {c.unlimited
                          ? `${c.used} used · no ceiling`
                          : `${c.used} / ${c.limit} · ${c.pct}%`}
                      </p>
                    </div>
                    {!c.unlimited && <Bar pct={c.pct} />}
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </main>
    </>
  );
}
