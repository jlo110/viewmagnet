/**
 * UpgradeModal — marketing card surfaced when a free user touches a
 * PRO-gated control in Studio.
 *
 * Soft-gate by design — the modal explains what they'd unlock but does
 * NOT block the underlying action. Caller still runs its handler so the
 * user feels what they're missing. CTA navigates to /dashboard/settings
 * (billing tab); for now no Stripe redirect.
 */
import { CloudUpload, Layers, Music4, Palette, Sparkles, Wand2, X } from "lucide-react";
import { useLocation } from "wouter";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { UpgradeReason } from "@/contexts/UpgradeContext";

interface UpgradeModalProps {
  open: boolean;
  reason?: UpgradeReason;
  onOpenChange: (open: boolean) => void;
}

const PILLARS: {
  id: UpgradeReason;
  title: string;
  bullet: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  {
    id: "animations",
    title: "Animations",
    bullet:
      "All 15 transitions, auto-zoom punch-ins, and emoji captions across every clip.",
    icon: Wand2,
  },
  {
    id: "sound",
    title: "Sound",
    bullet:
      "Per-boundary SFX stingers + global transition audio so cuts hit with impact.",
    icon: Music4,
  },
  {
    id: "branding",
    title: "Branding",
    bullet:
      "Your logo, brand colors, and font auto-applied to every render — no setup per session.",
    icon: Palette,
  },
  {
    id: "projects",
    title: "Multi-clip projects",
    bullet:
      "Stitch unlimited clips into long-form videos with per-boundary transitions, project brand kit, and one-pass audio loudness normalization.",
    icon: Layers,
  },
  {
    id: "render_budget",
    title: "Cloud renders",
    bullet:
      "Unlimited render minutes, priority queue, 4K + 15-minute project lengths, and email when each render is ready.",
    icon: CloudUpload,
  },
];

export function UpgradeModal({ open, reason, onOpenChange }: UpgradeModalProps) {
  const [, navigate] = useLocation();
  const highlight = reason ?? null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md overflow-hidden border-zinc-800 bg-zinc-950 p-0">
        <div className="relative bg-gradient-to-br from-violet-500/10 via-fuchsia-500/5 to-transparent px-6 pt-6">
          <DialogClose
            className="absolute right-3 top-3 rounded-md p-1 opacity-60 hover:bg-zinc-900 hover:opacity-100"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </DialogClose>
          <div className="mb-3 inline-flex items-center gap-1.5 rounded-full bg-violet-500/20 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-violet-300">
            <Sparkles className="h-3 w-3" />
            Upgrade to Pro
          </div>
          <DialogHeader className="text-left">
            <DialogTitle className="text-xl font-bold text-white">
              {highlight === "branding"
                ? "Make every clip yours"
                : highlight === "sound"
                ? "Sound design that lands"
                : highlight === "emojis"
                ? "Auto-emojis on every line"
                : highlight === "animations"
                ? "Cinematic transitions, unlocked"
                : highlight === "quota_out"
                ? "You're out of analyses this month"
                : highlight === "quota_low"
                ? "You're almost out of analyses"
                : highlight === "render_budget"
                ? "You're out of render minutes"
                : highlight === "render_softcap"
                ? "Unlock 4K and longer projects"
                : "Unlock the full Studio"}
            </DialogTitle>
            <DialogDescription className="text-sm text-zinc-400">
              {highlight === "quota_out"
                ? "Upgrade to Pro for 500 analyses/month (50× the Free cap), plus the full Studio toolkit."
                : highlight === "quota_low"
                ? "At your current pace you'll hit the Free cap soon. Pro gives you 500/month and never throttles."
                : highlight === "render_budget"
                ? "Free plans get 30 render-minutes per UTC month. Pro is unlimited and gets priority in the render queue so your videos ship the moment they're queued."
                : highlight === "render_softcap"
                ? "4K renders and >2-minute projects work on Free too — Pro removes the warning and bumps queue priority so finished videos arrive sooner."
                : "Pro plans get the full transition library, sound design, and per-user branding — all auto-applied to every render."}
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="space-y-3 px-6 py-4">
          {PILLARS.map(({ id, title, bullet, icon: Icon }) => {
            const active = highlight === id;
            return (
              <div
                key={id}
                className={`flex gap-3 rounded-md border p-3 transition-colors ${
                  active
                    ? "border-violet-500/60 bg-violet-500/10"
                    : "border-zinc-800 bg-zinc-900/50"
                }`}
              >
                <div
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded ${
                    active
                      ? "bg-violet-500/30 text-violet-200"
                      : "bg-zinc-800 text-zinc-400"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-white">
                    {title}
                  </div>
                  <div className="text-xs leading-snug text-zinc-400">
                    {bullet}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <DialogFooter className="flex-col gap-2 border-t border-zinc-800 bg-zinc-950 px-6 py-4 sm:flex-col">
          <Button
            className="w-full bg-gradient-to-r from-violet-500 to-fuchsia-500 font-semibold hover:from-violet-400 hover:to-fuchsia-400"
            onClick={() => {
              onOpenChange(false);
              navigate("/dashboard/settings");
            }}
          >
            Upgrade to Pro
          </Button>
          <button
            onClick={() => onOpenChange(false)}
            className="text-xs text-zinc-500 hover:text-zinc-300"
          >
            Maybe later
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
