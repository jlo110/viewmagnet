/**
 * RenderBudgetNudge — small pill rendered next to the Render button
 * in Studio + StudioProject editors that surfaces the user's
 * monthly render-minute budget.
 *
 * Design (Week 8 polish, Day 4.3):
 *
 *   - **OK** (<80% used or paid plan): the pill is muted — passive
 *     reassurance for the free user, hidden entirely for Pro to
 *     keep the toolbar quiet.
 *   - **Warn** (≥80%): amber pill with "N min left this month"
 *     and a "Go Pro" link. Render still works.
 *   - **Out** (≥100%): red pill, "Out of minutes — upgrade for
 *     unlimited". The Render button itself is hard-disabled by
 *     ``RenderButtonWithBudget`` below.
 *
 * The component is also a click target: clicking it always opens
 * the upgrade modal with reason ``render_budget``. That mirrors
 * the dashboard quota badge so the conversion surface is
 * consistent.
 */
import { ArrowUpRight, Crown } from "lucide-react";

import { useUpgrade } from "@/contexts/UpgradeContext";
import { usePlan } from "@/hooks/usePlan";
import { useRenderBudget, type BudgetState } from "@/lib/useRenderBudget";

interface Props {
  /** Optional override — pre-loaded state from a parent so we don't
   *  fire a second ``/usage/renders`` call. If omitted, the
   *  component fetches its own. */
  state?: BudgetState;
  minutesRemaining?: number;
  minutesLimit?: number;
  className?: string;
}

export function RenderBudgetNudge({
  state: stateOverride,
  minutesRemaining,
  minutesLimit,
  className = "",
}: Props) {
  const { openUpgrade } = useUpgrade();
  const { isFree } = usePlan();
  const { state: hookState, budget } = useRenderBudget();
  const state = stateOverride ?? hookState;
  const remaining =
    minutesRemaining ?? (budget && !budget.unlimited ? budget.minutes_remaining : null);
  const limit = minutesLimit ?? (budget && !budget.unlimited ? budget.minutes_limit : null);

  // Paid plans render nothing — they have no quota to surface and
  // the toolbar should stay quiet.
  if (!isFree || state === "unlimited") return null;

  // While loading / error, just don't render — the Render button is
  // the source of truth for whether the click will succeed.
  if (state === "loading" || state === "error") return null;

  const handleClick = () => openUpgrade("render_budget");

  if (state === "out") {
    return (
      <button
        type="button"
        onClick={handleClick}
        aria-label="Out of render minutes this month. Click to upgrade for unlimited."
        className={
          "group inline-flex items-center gap-1.5 rounded-md border border-red-500/40 " +
          "bg-red-500/10 px-2.5 py-1 text-xs text-red-300 transition-colors " +
          "hover:border-red-400/70 hover:text-red-200 " +
          className
        }
      >
        <Crown className="h-3 w-3" />
        <span className="font-semibold">Out of render minutes</span>
        <span className="opacity-80">— Upgrade for unlimited</span>
        <ArrowUpRight className="h-3 w-3 opacity-70 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
      </button>
    );
  }

  if (state === "warn") {
    return (
      <button
        type="button"
        onClick={handleClick}
        aria-label={`${remaining ?? 0} of ${limit ?? 0} render minutes left this month. Click to upgrade for unlimited.`}
        className={
          "group inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 " +
          "bg-amber-500/10 px-2.5 py-1 text-xs text-amber-200 transition-colors " +
          "hover:border-amber-400/70 hover:text-amber-100 " +
          className
        }
      >
        <Crown className="h-3 w-3" />
        <span className="font-semibold tabular-nums">
          {remaining != null ? Math.max(0, Math.floor(remaining)) : "?"} min left
        </span>
        <span className="opacity-80">· Go Pro</span>
        <ArrowUpRight className="h-3 w-3 opacity-70 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
      </button>
    );
  }

  // OK state — quiet hint, only visible on free plan. Communicates
  // "this is metered" without nagging. We deliberately keep this
  // present in the toolbar so the user knows where their cap is.
  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label={`${remaining ?? 0} of ${limit ?? 0} free render minutes left this month.`}
      className={
        "group inline-flex items-center gap-1.5 rounded-md border border-zinc-800 " +
        "bg-transparent px-2.5 py-1 text-[11px] text-zinc-400 transition-colors " +
        "hover:border-cyan-glow/30 hover:text-zinc-200 " +
        className
      }
    >
      <span className="tabular-nums">
        {remaining != null && limit != null
          ? `${Math.max(0, Math.floor(remaining))} / ${Math.floor(limit)} free min`
          : "Free render budget"}
      </span>
      <ArrowUpRight className="h-3 w-3 opacity-60 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
    </button>
  );
}
