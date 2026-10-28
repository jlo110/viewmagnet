/*
 * Design: Signal Flow — Kinetic Minimalism
 * Footer: Minimal, dark, with gradient top border
 */
import { Link } from "wouter";
import { Zap } from "lucide-react";

interface FooterLink {
  label: string;
  href: string;
}

const footerLinks: Record<string, FooterLink[]> = {
  Product: [
    { label: "Video Analyzer", href: "/dashboard/analyzer" },
    { label: "Title Generator", href: "/dashboard/titles" },
    { label: "Thumbnail Creator", href: "/dashboard/thumbnails" },
    { label: "AI Writer", href: "/dashboard/writer" },
    { label: "Pricing", href: "/#pricing" },
  ],
  Resources: [
    { label: "Blog", href: "/blog" },
    { label: "Script Frameworks", href: "/frameworks" },
    { label: "Analyzer Guide", href: "/analyzer-guide" },
    { label: "Methodology", href: "/methodology" },
    { label: "MCP server (Claude / Cursor)", href: "/mcp" },
    { label: "API Docs", href: "/docs" },
    { label: "Changelog", href: "/changelog" },
    { label: "Status", href: "/status" },
  ],
  Company: [
    { label: "About", href: "/about" },
    { label: "Privacy", href: "/privacy" },
    { label: "Terms", href: "/terms" },
    { label: "Contact", href: "/contact" },
  ],
};

export default function Footer() {
  return (
    <footer className="relative border-t border-border/30 bg-surface-dark">
      <div className="container py-16">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-10">
          {/* Brand */}
          <div className="col-span-2 md:col-span-1">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-md bg-gradient-to-br from-cyan-glow to-amber-glow flex items-center justify-center">
                <Zap className="w-3.5 h-3.5 text-deep-charcoal" strokeWidth={2.5} />
              </div>
              <span className="text-base font-bold font-[var(--font-display)] tracking-tight text-foreground">
                View<span className="text-cyan-glow">Magnet</span>
              </span>
            </Link>
            <p className="mt-3 text-sm text-muted-foreground leading-relaxed max-w-xs">
              AI-powered YouTube analytics and creation tools. Data-driven growth for every creator.
            </p>
          </div>

          {/* Link columns */}
          {Object.entries(footerLinks).map(([title, links]) => (
            <div key={title}>
              <h4 className="text-xs font-semibold font-[var(--font-mono)] tracking-widest uppercase text-muted-foreground mb-4">
                {title}
              </h4>
              <ul className="space-y-2.5">
                {links.map((link) => (
                  <li key={link.href}>
                    <Link 
                      href={link.href}
                      className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Bottom bar */}
        <div className="mt-12 pt-6 border-t border-border/20 flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} ViewMagnet. All rights reserved.
          </p>
          <p className="text-xs text-muted-foreground">
            Trained on 144,641+ YouTube videos. Models updated weekly.
          </p>
        </div>
      </div>
    </footer>
  );
}
