/**
 * usePlan — read the current user's subscription tier off the auth context.
 *
 * Returns simple booleans for the most common gating checks so call
 * sites don't have to remember the exact string values used by the DB
 * (free / starter / pro / agency).
 *
 * ``enterprise`` is a legacy alias kept for older rows + the dev demo
 * user; it resolves to the same unlimited tier as ``agency``.
 */
import { useAuth } from "@/contexts/AuthContext";

export type PlanTier = "free" | "starter" | "pro" | "agency";

export interface UsePlanResult {
  tier: PlanTier;
  isFree: boolean;
  isStarter: boolean;
  isPro: boolean;
  isAgency: boolean;
  /** True when ANY paid plan — Starter, Pro, or Agency — is active. */
  hasPaidPlan: boolean;
}

export function usePlan(): UsePlanResult {
  const { user } = useAuth();
  const raw = (user?.plan ?? "free").toLowerCase();
  // Normalize legacy "enterprise" → "agency".
  const normalized = raw === "enterprise" ? "agency" : raw;
  const tier: PlanTier =
    normalized === "starter" ||
    normalized === "pro" ||
    normalized === "agency"
      ? (normalized as PlanTier)
      : "free";
  return {
    tier,
    isFree: tier === "free",
    isStarter: tier === "starter",
    isPro: tier === "pro",
    isAgency: tier === "agency",
    hasPaidPlan: tier !== "free",
  };
}
