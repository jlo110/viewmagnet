/**
 * ProBadge — a tiny "PRO" pill that decorates a control's label so users
 * see at a glance which Studio features require an upgrade. Hidden when
 * the caller already has access (so paid users see a clean UI).
 */
import { Sparkles } from "lucide-react";

import { usePlan } from "@/hooks/usePlan";

export interface ProBadgeProps {
  /** When true, render even if the user has the plan (debug / story). */
  forceShow?: boolean;
  /** Optional className for layout overrides. */
  className?: string;
}

export function ProBadge({ forceShow = false, className = "" }: ProBadgeProps) {
  const { hasPaidPlan } = usePlan();
  if (hasPaidPlan && !forceShow) return null;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-500 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white shadow-[0_0_8px_rgba(139,92,246,0.5)] ${className}`}
      title="Pro feature"
    >
      <Sparkles className="h-2.5 w-2.5" />
      Pro
    </span>
  );
}
