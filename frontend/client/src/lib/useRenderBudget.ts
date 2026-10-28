/**
 * useRenderBudget — single source of truth for the current month's
 * render-minute quota inside Studio + StudioProject editors.
 *
 * Why a dedicated hook (Week 8 polish, Day 4.3 of the plan):
 *
 *   - Before this, only the dedicated ``/dashboard/renders`` page
 *     loaded the budget. Users would happily build a 4-minute
 *     project, click Render, and get a surprise 402. The hook lets
 *     us show "12 of 30 free minutes used" right next to the
 *     Render button so they see the wall coming.
 *
 *   - The Render button itself can soft-warn at ≥80% and
 *     hard-disable at ≥100% by reading ``state`` off this hook
 *     without each editor wiring its own logic.
 *
 * Live updates:
 *
 *   - The axios interceptor in ``@/lib/api`` dispatches a
 *     ``RENDER_BUDGET_HEADER_EVENT`` on every API response that
 *     carries the ``X-Render-Budget-Remaining-Minutes`` header
 *     (every successful render enqueue stamps this). We listen
 *     for that event and refetch so the badge updates the moment
 *     the user starts a render — no polling.
 *
 *   - Auth changes (logout, plan upgrade applied via webhook)
 *     refetch via the ``user.plan`` dependency.
 */
import { useCallback, useEffect, useState } from "react";

import { getRenderBudget, RENDER_BUDGET_HEADER_EVENT, type RenderBudget } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";

export type BudgetState = "loading" | "ok" | "warn" | "out" | "unlimited" | "error";

export interface UseRenderBudgetResult {
  /** Coarse traffic-light. ``warn`` is ≥80%, ``out`` is ≥100%. Pro
   *  + Enterprise always resolve to ``"unlimited"``. */
  state: BudgetState;
  budget: RenderBudget | null;
  /** Convenience: free user is past their cap and must upgrade. */
  isOut: boolean;
  /** Convenience: free user crossed 80% — render still works. */
  isWarn: boolean;
  /** Force a refetch (e.g. after a render succeeds without firing
   *  the header — defensive: callers can almost always rely on the
   *  header event listener instead). */
  refresh: () => Promise<void>;
}

export function useRenderBudget(): UseRenderBudgetResult {
  const { user, isAuthenticated } = useAuth();
  const [budget, setBudget] = useState<RenderBudget | null>(null);
  const [state, setState] = useState<BudgetState>("loading");

  const refresh = useCallback(async () => {
    if (!isAuthenticated) {
      setState("loading");
      setBudget(null);
      return;
    }
    try {
      const fresh = await getRenderBudget();
      setBudget(fresh);
      if (fresh.unlimited) {
        setState("unlimited");
      } else if (fresh.percent_used >= 100) {
        setState("out");
      } else if (fresh.percent_used >= 80) {
        setState("warn");
      } else {
        setState("ok");
      }
    } catch {
      // Budget is non-critical for the editor — fail open so the
      // Render button still works. The pre-render server-side check
      // is the final word.
      setState("error");
    }
  }, [isAuthenticated]);

  useEffect(() => {
    refresh();
  }, [refresh, user?.plan]);

  // Live update — when any API response carries the budget header
  // (notably the render-enqueue POST), we refetch once so the
  // editor's "X of Y minutes" number stays in sync without polling.
  useEffect(() => {
    const handler = () => {
      refresh();
    };
    window.addEventListener(RENDER_BUDGET_HEADER_EVENT, handler);
    return () => window.removeEventListener(RENDER_BUDGET_HEADER_EVENT, handler);
  }, [refresh]);

  return {
    state,
    budget,
    isOut: state === "out",
    isWarn: state === "warn",
    refresh,
  };
}
