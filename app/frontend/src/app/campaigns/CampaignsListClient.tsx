"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, PrimaryButton } from "@/components/Shared/ui";
import CreateCampaignModal from "./CreateCampaignModal";
import type { Campaign } from "./types";

export default function CampaignsListClient() {
  const [rows, setRows] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [listErr, setListErr] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setListErr("");
    try {
      const res = await apiFetch("/api/campaigns?include_archived=true", {
        method: "GET",
      });
      if (!res.ok) throw new ApiError(res.status, "Could not load campaigns.");
      setRows((await res.json()) as Campaign[]);
    } catch (e) {
      setListErr(e instanceof ApiError ? e.message : "Could not load campaigns.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const setArchived = async (id: number, archived: boolean) => {
    await apiFetch(`/api/campaigns/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ archived }),
    });
    await load();
  };

  if (loading) return <p className="text-sm text-ink/50">Loading…</p>;
  if (listErr) return <ErrorText>{listErr}</ErrorText>;

  const visible = rows.filter((c) => showArchived || !c.archived);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <label className="flex items-center gap-1.5 text-xs text-ink/50 cursor-pointer">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="accent-mpower-orange"
          />
          Show archived
        </label>
        <PrimaryButton className="w-auto px-5" onClick={() => setCreating(true)}>
          New campaign
        </PrimaryButton>
      </div>

      {creating && <CreateCampaignModal onClose={() => setCreating(false)} />}

      {visible.length === 0 ? (
        <div className="bg-surface border border-ink/10 rounded-2xl p-10 text-center">
          <p className="text-sm text-ink/45">No campaigns yet. Create your first one.</p>
        </div>
      ) : (
        <ul className="space-y-3">
          {visible.map((c) => (
            <li
              key={c.id}
              className="bg-surface border border-ink/10 rounded-2xl shadow-sm hover:border-mpower-orange/40"
            >
              <div className="flex items-start justify-between gap-3 p-5">
                <Link href={`/campaigns/${c.id}`} className="min-w-0 flex-1 btn-press">
                  <div className="flex items-center gap-2.5">
                    <p
                      className={
                        "font-heading text-base font-semibold truncate " +
                        (c.archived ? "text-ink/40 line-through" : "text-ink")
                      }
                    >
                      {c.name}
                    </p>
                  </div>
                  <p className="text-sm text-ink/55 mt-1.5">
                    {c.owner ? `${c.owner} · ` : ""}
                    {c.timezone}
                    {c.require_icebreaker ? " · icebreaker required" : ""}
                  </p>
                  <p className="text-xs text-ink/40 mt-1">
                    {c.step_count} email{c.step_count === 1 ? "" : "s"} in sequence
                    {c.archived ? " · archived" : ""}
                  </p>
                </Link>
                {c.archived ? (
                  <button
                    type="button"
                    onClick={() => setArchived(c.id, false)}
                    className="shrink-0 text-xs font-body text-mpower-orange hover:underline btn-press"
                  >
                    restore
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setArchived(c.id, true)}
                    className="shrink-0 text-xs font-body text-ink/55 hover:text-err-red hover:underline btn-press"
                  >
                    archive
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
