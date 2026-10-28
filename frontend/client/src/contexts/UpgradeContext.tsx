/**
 * UpgradeContext — global "open the upgrade modal" plumbing.
 *
 * Any component can call ``useUpgrade().openUpgrade('animations')`` to
 * surface the marketing modal. The actual modal lives once at the App
 * root so it survives route changes (e.g. dismiss → render → reopen).
 *
 * Mock soft-gating policy: the modal NEVER blocks the underlying action.
 * The caller still executes its handler so the user gets to see the
 * feature in action (and is gently nudged that it requires a paid plan).
 */
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { UpgradeModal } from "@/components/upgrade/UpgradeModal";
import { usePlan } from "@/hooks/usePlan";

export type UpgradeReason =
  | "animations"
  | "sound"
  | "branding"
  | "emojis"
  // Multi-clip Studio Projects (Week 7) — free is capped at 1 active
  // project; nudging this reason highlights the long-form editor
  // pillar in the upgrade modal so the user understands the value
  // before being asked to pay.
  | "projects"
  // Quota-based nudges from the dashboard plan badge — reviewer
  // pushback was that the passive "0/10 analyses" counter should
  // actively convert. ``quota_low`` fires at 70%+ used, ``quota_out``
  // fires when the user is at or over the cap.
  | "quota_low"
  | "quota_out"
  // Cloud-render budget nudges (Week 8). Hybrid gating: ``render_budget``
  // hard-blocks when the user is out of monthly render minutes,
  // ``render_softcap`` is the soft nudge for 4K / >2-min renders that
  // still complete but pop the modal to surface Pro's perks.
  | "render_budget"
  | "render_softcap";

interface UpgradeContextValue {
  /** Pop the upgrade modal. No-op for paid users. Pass a ``reason`` so the
   *  modal can highlight the pillar the user just touched. */
  openUpgrade: (reason?: UpgradeReason) => void;
}

const UpgradeContext = createContext<UpgradeContextValue | undefined>(undefined);

export function UpgradeProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<UpgradeReason | undefined>(undefined);
  const { hasPaidPlan } = usePlan();

  const openUpgrade = useCallback(
    (r?: UpgradeReason) => {
      // Already paid — skip the modal entirely so we never annoy them.
      if (hasPaidPlan) return;
      setReason(r);
      setOpen(true);
    },
    [hasPaidPlan],
  );

  const value = useMemo<UpgradeContextValue>(() => ({ openUpgrade }), [openUpgrade]);

  return (
    <UpgradeContext.Provider value={value}>
      {children}
      <UpgradeModal open={open} reason={reason} onOpenChange={setOpen} />
    </UpgradeContext.Provider>
  );
}

export function useUpgrade(): UpgradeContextValue {
  const ctx = useContext(UpgradeContext);
  if (ctx === undefined) {
    // Soft fallback: in environments where the provider isn't mounted
    // (e.g. isolated tests), expose a no-op so consumers don't throw.
    return { openUpgrade: () => {} };
  }
  return ctx;
}
