import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Link } from "wouter";
import {
  ArrowLeft,
  Bot,
  ExternalLink,
  Key,
  Loader2,
  Zap,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { SEOHead, StructuredData } from "@/components/seo";

// Scalar is ~350KB of CSS + Vue runtime. Lazy-load it so the marketing
// chrome (header, hero card, quick-links) paints instantly and the
// heavy reference renders in the second tick. Wrapping it in its own
// chunk also means the rest of the site never pays for the OpenAPI
// renderer.
const ApiReferenceLazy = lazy(() => import("@/components/docs/ScalarReference"));

// Same env switch the rest of the SPA uses (``frontend/client/src/lib/api.ts``).
// In dev the Vite proxy rewrites ``/api/*`` to ``localhost:8000/*``.
// In prod the SPA is served from ``viewmagnet.io`` and the API lives
// on ``api.viewmagnet.com`` — set ``VITE_API_URL`` accordingly there.
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api";
const OPENAPI_URL = `${API_BASE.replace(/\/$/, "")}/openapi.json`;

export default function Docs() {
  // Defer mounting Scalar until after first paint so the LCP for the
  // hero is the curated copy, not a spinner. Without this delay,
  // Scalar's Vue runtime steals the main thread on cold load.
  const [readyForReference, setReadyForReference] = useState(false);
  useEffect(() => {
    const id = window.requestIdleCallback
      ? window.requestIdleCallback(() => setReadyForReference(true))
      : window.setTimeout(() => setReadyForReference(true), 50);
    return () => {
      if (typeof id === "number") window.clearTimeout(id);
    };
  }, []);

  // The deep-link target we hand to "Jump to full reference" — keeps
  // browser back-button behaviour sane.
  const referenceAnchor = useMemo(() => "#reference", []);

  return (
    <>
      <SEOHead
        title="API Documentation"
        description="ViewMagnet REST API reference: 130+ endpoints for video analysis, prediction, script generation, hook scoring, Studio rendering, and post-publish outcomes. Authenticate with a Personal Access Token or use the ViewMagnet MCP server."
        canonicalUrl="/docs"
        keywords="ViewMagnet API, YouTube prediction API, video analysis API, OpenAPI reference, MCP server, REST API"
        markdownUrl="/docs.md"
      />
      <StructuredData
        type="breadcrumb"
        items={[
          { name: "Home", url: "/" },
          { name: "API Docs", url: "/docs" },
        ]}
      />
      <StructuredData
        type="article"
        headline="ViewMagnet API Documentation"
        description="Complete OpenAPI reference for the ViewMagnet REST API and the viewmagnet-mcp server."
        url="/docs"
        datePublished="2026-05-26"
        dateModified="2026-05-26"
      />

      <div className="min-h-screen bg-deep-charcoal">
        <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-lg">
          <div className="container mx-auto flex h-16 items-center justify-between px-4">
            <Link href="/" className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-cyan-glow to-amber-glow">
                <Zap className="h-4 w-4 text-deep-charcoal" strokeWidth={2.5} />
              </div>
              <span className="text-lg font-bold">
                View<span className="text-cyan-glow">Magnet</span>
              </span>
            </Link>

            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" asChild>
                <a href={referenceAnchor}>
                  Jump to full reference
                </a>
              </Button>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/">
                  <ArrowLeft className="mr-2 h-4 w-4" />
                  Back to Home
                </Link>
              </Button>
            </div>
          </div>
        </header>

        {/* Curated intro — keeps Scalar from being the first thing
            visitors see, because most of them should not be wiring
            against the REST API directly. */}
        <section className="border-b border-border/40 bg-gradient-to-b from-deep-charcoal via-deep-charcoal to-gunmetal">
          <div className="container mx-auto max-w-5xl px-4 py-12 lg:py-16">
            <div className="mb-8 max-w-3xl">
              <h1 className="text-4xl font-bold lg:text-5xl">
                ViewMagnet <span className="text-cyan-glow">API</span> Documentation
              </h1>
              <p className="mt-4 text-lg text-muted-foreground">
                130+ REST endpoints covering video analysis, script generation,
                hook and title scoring, Studio rendering, and post-publish outcomes.
                Authenticate with a Personal Access Token, or skip the plumbing
                entirely with the MCP server.
              </p>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <Card className="border-cyan-glow/30 bg-cyan-glow/5">
                <CardContent className="p-6">
                  <div className="mb-3 flex items-center gap-2">
                    <Bot className="h-5 w-5 text-cyan-glow" />
                    <h2 className="text-base font-semibold">
                      Easiest: ViewMagnet MCP server
                    </h2>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    For Claude Desktop, Cursor, Cline, and any other MCP-compatible
                    agent. One command wires the 10 most-used endpoints to your
                    agent — no HTTP code required.
                  </p>
                  <pre className="my-4 overflow-x-auto rounded-md bg-deep-charcoal px-4 py-3 font-mono text-sm text-cyan-glow">
                    npx viewmagnet-mcp install
                  </pre>
                  <Button
                    asChild
                    size="sm"
                    className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
                  >
                    <Link href="/mcp">
                      MCP server overview
                      <ExternalLink className="ml-1.5 h-3.5 w-3.5" />
                    </Link>
                  </Button>
                </CardContent>
              </Card>

              <Card className="border-border/60 bg-card/40">
                <CardContent className="p-6">
                  <div className="mb-3 flex items-center gap-2">
                    <Key className="h-5 w-5 text-amber-glow" />
                    <h2 className="text-base font-semibold">
                      Direct REST access
                    </h2>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Generate a Personal Access Token, then call any endpoint with
                    a standard <code className="rounded bg-deep-charcoal px-1 py-0.5 text-xs">Authorization: Bearer …</code> header.
                    PATs are revocable, scope-limited, and never expose your password.
                  </p>
                  <pre className="my-4 overflow-x-auto whitespace-pre rounded-md bg-deep-charcoal px-4 py-3 font-mono text-xs text-muted-foreground">
{`curl -X POST https://api.viewmagnet.com/analyze \\
  -H "Authorization: Bearer vm_pat_<your-token>" \\
  -H "Content-Type: application/json" \\
  -d '{"url": "https://youtube.com/watch?v=VIDEO_ID"}'`}
                  </pre>
                  <Button asChild size="sm" variant="outline">
                    <Link href="/dashboard/api-tokens">
                      Generate a token
                      <ExternalLink className="ml-1.5 h-3.5 w-3.5" />
                    </Link>
                  </Button>
                </CardContent>
              </Card>
            </div>

            <p className="mt-6 text-xs text-muted-foreground">
              Spec format: <a href={OPENAPI_URL} className="text-cyan-glow hover:underline" rel="nofollow">OpenAPI 3.1</a> ·
              {" "}Full machine-readable reference rendered below by{" "}
              <a
                href="https://scalar.com"
                target="_blank"
                rel="noopener noreferrer"
                className="text-cyan-glow hover:underline"
              >
                Scalar
              </a>.
            </p>
          </div>
        </section>

        <section id="reference" className="bg-deep-charcoal">
          {/* Scalar comes with its own sidebar + scroll container, so
              we hand it the full viewport width and let it own its
              chrome. Sticky header above remains accessible because
              Scalar's internal layout is itself scrollable. */}
          <Suspense
            fallback={
              <div className="flex h-[60vh] items-center justify-center text-muted-foreground">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                Loading interactive reference…
              </div>
            }
          >
            {readyForReference ? (
              <ApiReferenceLazy openApiUrl={OPENAPI_URL} />
            ) : (
              <div className="flex h-[60vh] items-center justify-center text-muted-foreground">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                Preparing API reference…
              </div>
            )}
          </Suspense>
        </section>
      </div>
    </>
  );
}
