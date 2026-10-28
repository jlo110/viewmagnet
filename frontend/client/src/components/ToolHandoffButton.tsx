/**
 * ``<ToolHandoffButton>`` — the standard pill that takes the user
 * from one dashboard tool to another with the right deep-link
 * context attached.
 *
 * Lives at the heart of Week 9 "Connected Tools". The whole point of
 * having ~25 dashboards is that they talk to each other; this
 * component is what the visual handoff actually looks like.
 *
 * Two ways to use it:
 *
 *   1. With a structured CTA from ``mapRecommendationToCta`` /
 *      ``structuredCtaToFrontend``:
 *
 *          <ToolHandoffButton cta={cta} size="xs" />
 *
 *   2. Standalone:
 *
 *          <ToolHandoffButton
 *            href="/dashboard/studio/abc123"
 *            label="Open in Studio"
 *            icon={<Wand2 />}
 *          />
 *
 * Size variants:
 *   * ``xs`` — tight pill for inline-with-text recommendations
 *     (Algorithm Signals card, full Recommendations list, etc.).
 *   * ``sm`` — slightly larger pill for standalone places like
 *     Drafts row buttons.
 *
 * The default trailing icon is an arrow; pass ``icon`` to use a
 * tool-specific icon (Wand2 for Studio, Send for Distribution, etc.).
 */
import { Link } from "wouter";
import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

import type { RecommendationCta } from "@/lib/deepLinks";

type Size = "xs" | "sm";

type Variant = "primary" | "ghost";

interface CommonProps {
  size?: Size;
  variant?: Variant;
  /** Optional tooltip override. Defaults to the action label. */
  tooltip?: string;
  /** Replace the default trailing arrow with a tool-specific icon. */
  icon?: ReactNode;
  /** Place the icon before the label instead of after. */
  iconPosition?: "leading" | "trailing";
  /** Analytics or instrumentation hook — does NOT cancel navigation. */
  onSelect?: () => void;
  className?: string;
}

interface CtaProps extends CommonProps {
  /** Structured CTA from ``mapRecommendationToCta`` or the backend. */
  cta: RecommendationCta;
  href?: never;
  label?: never;
}

interface ExplicitProps extends CommonProps {
  href: string;
  label: string;
  cta?: never;
}

type Props = CtaProps | ExplicitProps;

function sizeClasses(size: Size): string {
  switch (size) {
    case "xs":
      return "px-2 py-0.5 text-[10px] gap-1";
    case "sm":
    default:
      return "px-2.5 py-1 text-xs gap-1";
  }
}

function iconSizeClasses(size: Size): string {
  return size === "xs" ? "w-3 h-3" : "w-3.5 h-3.5";
}

function variantClasses(variant: Variant): string {
  switch (variant) {
    case "ghost":
      return "bg-transparent text-cyan-glow border border-cyan-glow/30 hover:bg-cyan-glow/10";
    case "primary":
    default:
      return "bg-cyan-glow/10 text-cyan-glow border border-cyan-glow/20 hover:bg-cyan-glow/20";
  }
}

export function ToolHandoffButton(props: Props) {
  const size: Size = props.size ?? "sm";
  const variant: Variant = props.variant ?? "primary";
  const iconPosition = props.iconPosition ?? "trailing";

  const href = "cta" in props && props.cta ? props.cta.href : props.href;
  const labelRaw =
    "cta" in props && props.cta ? props.cta.actionLabel ?? props.cta.label : props.label;
  const label = labelRaw ?? "Open tool";

  // Gracefully no-op when there's no destination (the backend may
  // ship a label-only entry — we still want the text to render
  // upstream, just don't render the button at all).
  if (!href) return null;

  const tooltip = props.tooltip ?? `${label} with this video's context pre-loaded`;
  const icon = props.icon ?? <ArrowRight className={iconSizeClasses(size)} />;

  const base =
    "shrink-0 inline-flex items-center rounded-md font-medium transition-colors";
  const className = [
    base,
    sizeClasses(size),
    variantClasses(variant),
    props.className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Link href={href}>
      <button
        type="button"
        className={className}
        title={tooltip}
        onClick={props.onSelect}
      >
        {iconPosition === "leading" && icon}
        <span>{label}</span>
        {iconPosition === "trailing" && icon}
      </button>
    </Link>
  );
}

export default ToolHandoffButton;
