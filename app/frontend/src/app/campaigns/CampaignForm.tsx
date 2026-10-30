"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, apiFetch } from "@/lib/api";
import { ErrorText, Field, PrimaryButton } from "@/components/Shared/ui";
import { PLACEHOLDERS, SEND_DAYS, type Campaign, type Step } from "./types";

// 08062026_cr CR-3/4/5 — slimmed campaign editor. The taxonomy dropdowns, target
// roles, ICP filters, status, target-lead-count, and manual timezone are GONE
// (taxonomy is now the read-only "Lead mix" panel; timezone is auto-derived).
// This form edits only: name, owner, the require-icebreaker toggle, the send
// window, and the email sequence. Creation lives in CreateCampaignModal.

const SELECT_CLS =
  "w-full px-4 py-3 rounded-xl border border-ink/15 font-body text-ink " +
  "focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 focus:border-mpower-orange btn-press bg-surface";

const HOURS = Array.from({ length: 24 }, (_, h) => h);

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-sm font-body font-medium text-ink mb-1.5">
      {children}
    </label>
  );
}

function emptyStep(): Step {
  return { wait_days: 0, subject: "", body: "" };
}

export default function CampaignForm({
  campaignId,
  onSaved,
}: {
  campaignId?: number;
  onSaved?: (campaign: Campaign) => void;
}) {
  const router = useRouter();
  const isEdit = campaignId != null;

  const [name, setName] = useState("");
  const [owner, setOwner] = useState("");
  const [requireIcebreaker, setRequireIcebreaker] = useState(true);
  const [sendDays, setSendDays] = useState<string[]>(["mon", "tue", "wed", "thu", "fri"]);
  const [startHour, setStartHour] = useState(9);
  const [endHour, setEndHour] = useState(17);
  const [steps, setSteps] = useState<Step[]>([emptyStep()]);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const init = useCallback(async () => {
    setErr("");
    try {
      if (isEdit) {
        const res = await apiFetch(`/api/campaigns/${campaignId}`, { method: "GET" });
        if (!res.ok) throw new ApiError(res.status, "Could not load campaign.");
        const camp = (await res.json()) as Campaign;
        setName(camp.name);
        setOwner(camp.owner ?? "");
        setRequireIcebreaker(camp.require_icebreaker);
        setSendDays(camp.send_days);
        setStartHour(camp.send_start_hour);
        setEndHour(camp.send_end_hour);
        setSteps(
          (camp.steps ?? []).map((s) => ({
            wait_days: s.wait_days,
            subject: s.subject,
            body: s.body,
          })),
        );
        if ((camp.steps ?? []).length === 0) setSteps([emptyStep()]);
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Could not load form.");
    } finally {
      setLoading(false);
    }
  }, [campaignId, isEdit]);

  useEffect(() => {
    void init();
  }, [init]);

  const toggleDay = (key: string) =>
    setSendDays((prev) =>
      prev.includes(key) ? prev.filter((d) => d !== key) : [...prev, key],
    );

  const setStep = (i: number, patch: Partial<Step>) =>
    setSteps((prev) => prev.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  const addStep = () => setSteps((prev) => [...prev, emptyStep()]);
  const removeStep = (i: number) =>
    setSteps((prev) => (prev.length > 1 ? prev.filter((_, j) => j !== i) : prev));
  const insertPlaceholder = (i: number, token: string) =>
    setSteps((prev) =>
      prev.map((s, j) =>
        j === i ? { ...s, body: (s.body ? s.body + " " : "") + token } : s,
      ),
    );

  const validate = (): string | null => {
    if (!name.trim()) return "Give the campaign a name.";
    if (startHour >= endHour) return "Send start hour must be before the end hour.";
    for (let i = 0; i < steps.length; i++) {
      if (!steps[i].subject.trim()) return `Step ${i + 1} needs a subject.`;
      if (!steps[i].body.trim()) return `Step ${i + 1} needs a body.`;
    }
    return null;
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;
    const v = validate();
    if (v) {
      setErr(v);
      return;
    }
    setErr("");
    setSaving(true);
    try {
      const body = JSON.stringify({
        name,
        owner: owner.trim() || null,
        require_icebreaker: requireIcebreaker,
        send_days: sendDays,
        send_start_hour: startHour,
        send_end_hour: endHour,
        steps: steps.map((s, i) => ({
          wait_days: i === 0 ? 0 : Number(s.wait_days) || 0,
          subject: s.subject,
          body: s.body,
        })),
      });
      const res = await apiFetch(
        isEdit ? `/api/campaigns/${campaignId}` : "/api/campaigns",
        { method: isEdit ? "PATCH" : "POST", body },
      );
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new ApiError(res.status, b.detail ?? "Could not save campaign.");
      }
      const saved = (await res.json()) as Campaign;
      if (onSaved) onSaved(saved);
      else router.push(`/campaigns/${saved.id}`);
      router.refresh();
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : "Could not save campaign.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="text-sm text-ink/50">Loading…</p>;

  return (
    <form onSubmit={submit} className="space-y-6">
      <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm space-y-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <Label>Campaign name</Label>
            <Field
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Drone OEMs — India Q3"
            />
          </div>
          <div>
            <Label>Campaign owner</Label>
            <Field
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
              placeholder="e.g. Priya Sharma"
            />
            <p className="text-xs text-ink/45 font-body mt-1.5">
              Who owns this campaign. Shows on the lead list and filters the
              pipeline. Optional.
            </p>
          </div>
        </div>
        <label className="flex items-center gap-2.5 cursor-pointer text-sm font-body text-ink/80">
          <input
            type="checkbox"
            checked={requireIcebreaker}
            onChange={(e) => setRequireIcebreaker(e.target.checked)}
            className="accent-mpower-orange"
          />
          Require an icebreaker before a lead can be added or sent
        </label>
      </section>

      <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm space-y-4">
        <h2 className="font-heading text-base font-semibold text-ink">Send window</h2>
        <div className="flex flex-wrap gap-2">
          {SEND_DAYS.map((d) => {
            const on = sendDays.includes(d.key);
            return (
              <button
                key={d.key}
                type="button"
                onClick={() => toggleDay(d.key)}
                className={
                  "px-3 py-1.5 rounded-lg text-sm font-body btn-press border " +
                  (on
                    ? "bg-mpower-orange/10 text-mpower-orange border-mpower-orange/40"
                    : "text-ink/55 border-ink/15 hover:bg-ink/5")
                }
              >
                {d.label}
              </button>
            );
          })}
        </div>
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <Label>From hour</Label>
            <select
              className={SELECT_CLS}
              value={startHour}
              onChange={(e) => setStartHour(Number(e.target.value))}
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>
              ))}
            </select>
          </div>
          <div>
            <Label>To hour</Label>
            <select
              className={SELECT_CLS}
              value={endHour}
              onChange={(e) => setEndHour(Number(e.target.value))}
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>
              ))}
            </select>
          </div>
        </div>
        <p className="text-xs text-ink/45 font-body">
          The send timezone is derived automatically from your leads&apos; majority
          country (see the Lead mix above).
        </p>
      </section>

      <section className="bg-surface border border-ink/10 rounded-2xl p-6 shadow-sm space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="font-heading text-base font-semibold text-ink">Email sequence</h2>
          <button
            type="button"
            onClick={addStep}
            className="text-sm font-body text-mpower-orange hover:underline btn-press"
          >
            + Add email
          </button>
        </div>

        {steps.map((s, i) => (
          <div key={i} className="border border-ink/10 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-body font-medium text-ink">
                Email {i + 1}
                {i === 0 ? " (sent immediately)" : ""}
              </span>
              {steps.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeStep(i)}
                  className="text-xs font-body text-ink/55 hover:text-err-red hover:underline btn-press"
                >
                  remove
                </button>
              )}
            </div>

            {i > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-ink/55 font-body">Wait</span>
                <input
                  type="number"
                  min={0}
                  max={365}
                  value={s.wait_days}
                  onChange={(e) => setStep(i, { wait_days: Number(e.target.value) || 0 })}
                  className="w-20 px-3 py-2 rounded-lg border border-ink/15 font-body text-ink focus:outline-none focus:ring-2 focus:ring-mpower-orange/30"
                />
                <span className="text-sm text-ink/55 font-body">days before sending</span>
              </div>
            )}

            <Field
              value={s.subject}
              onChange={(e) => setStep(i, { subject: e.target.value })}
              placeholder="Subject line"
            />
            <textarea
              value={s.body}
              onChange={(e) => setStep(i, { body: e.target.value })}
              placeholder="Email body…"
              rows={5}
              className="w-full px-4 py-3 rounded-xl border border-ink/15 font-body text-ink placeholder:text-ink/30 focus:outline-none focus:ring-2 focus:ring-mpower-orange/30 focus:border-mpower-orange"
            />
            <div className="flex flex-wrap gap-1.5">
              <span className="text-xs text-ink/40 font-body mr-1 self-center">
                Insert:
              </span>
              {PLACEHOLDERS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => insertPlaceholder(i, p)}
                  className="px-2 py-1 rounded-md text-xs font-mono text-ink/65 bg-ink/5 hover:bg-mpower-orange/10 hover:text-mpower-orange btn-press"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        ))}
      </section>

      {err && <ErrorText>{err}</ErrorText>}

      <div className="flex items-center gap-3">
        <PrimaryButton type="submit" disabled={saving} className="w-auto px-6">
          {saving ? "Saving…" : isEdit ? "Save changes" : "Create campaign"}
        </PrimaryButton>
        <button
          type="button"
          onClick={() => router.push("/campaigns")}
          className="text-sm font-body text-ink/55 hover:text-ink btn-press"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
