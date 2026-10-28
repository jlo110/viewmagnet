/**
 * /mcp — public marketing page for the ViewMagnet MCP server.
 *
 * Goals (in order):
 *
 *  1. Make "install in one command" the loudest thing on the page.
 *     The Vugola lesson is that the install ramp is the moat — get
 *     the curl-equivalent above the fold.
 *  2. Spell out the 10 tools with one-line agent-facing descriptions
 *     so the page doubles as the npm-package README and as the
 *     long-form pitch.
 *  3. Cite Claude Desktop / Cursor / Cline by name so the page ranks
 *     for "claude youtube tool" / "cursor mcp video analysis" /
 *     "cline content creation" generative queries.
 *  4. Send authenticated users straight to /dashboard/api-tokens so
 *     they can mint a PAT in one click.
 *
 * Not on this page (deliberately):
 *  - Pricing — handled by the unified Pricing section on /
 *  - The PAT lifecycle UI — that lives in the dashboard
 */
import { Link } from "wouter";
import { useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  Copy,
  ExternalLink,
  FileText,
  Flame,
  KeyRound,
  LayoutTemplate,
  ListChecks,
  Lightbulb,
  Magnet,
  PenTool,
  Search,
  Sparkles,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";
import type { ComponentType } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { SEOHead, StructuredData } from "@/components/seo";

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

interface ToolEntry {
  name: string;
  icon: ComponentType<{ className?: string }>;
  blurb: string;
  example: string;
}

// Keep these in sync with `mcp/src/tools/*.ts` — the tool descriptions
// the agent reads at runtime should match the one-liners users see
// here so there are no surprises when they call them.
const TOOLS: ToolEntry[] = [
  {
    name: "viewmagnet_analyze_video",
    icon: TrendingUp,
    blurb:
      "Predict whether a YouTube video will perform well — 0-100 score, tier, niche comparison, and Start/Keep/Repeat bottleneck.",
    example: '"Will https://youtu.be/… do well? Why isn\'t it working?"',
  },
  {
    name: "viewmagnet_list_frameworks",
    icon: ListChecks,
    blurb:
      "List the 4 viral script frameworks (Authority Myth-Buster, Delta Shift, Progressive Debunking, Lead Magnet) with goals + structure.",
    example: '"Which script framework should I use for a tutorial?"',
  },
  {
    name: "viewmagnet_generate_script",
    icon: PenTool,
    blurb:
      "Generate a full long-form script using one of the frameworks — hook, payoff, body sections, CTA, and assembled `full_script`.",
    example: '"Write me a Lead Magnet script about morning routines."',
  },
  {
    name: "viewmagnet_score_hook",
    icon: Flame,
    blurb:
      "Score a hook on belief challenge, mistake callout, urgency, and specificity. Returns the weakest dimension + rewrite hints.",
    example: '"Rate this hook: \'Most diets are designed to fail.\'"',
  },
  {
    name: "viewmagnet_list_hook_types",
    icon: Lightbulb,
    blurb:
      "List the 6 hook archetypes (Summary, Mistake Callout, Belief Destruction, Authority Anchor, Stake Reversal, Specificity).",
    example: '"What hook type best fits a finance video?"',
  },
  {
    name: "viewmagnet_detect_highlights",
    icon: Search,
    blurb:
      "Find the most clip-worthy moments inside a long video. Ranked by virality, with timestamps + suggested titles.",
    example: '"Pull 5 viral moments from this podcast: https://youtu.be/…"',
  },
  {
    name: "viewmagnet_analyze_pacing",
    icon: Zap,
    blurb:
      "Get a pacing grade, average cut interval, and 'cut here' recommendations for dead-air segments.",
    example: '"Why does my video feel slow? Where should I cut?"',
  },
  {
    name: "viewmagnet_score_title",
    icon: Target,
    blurb:
      "CTR-focused title scoring with per-feature breakdown (curiosity gap, specificity, loss-aversion framing, length).",
    example: '"Is this title click-worthy: \'5 mistakes wrecking your retention\'?"',
  },
  {
    name: "viewmagnet_generate_titles",
    icon: LayoutTemplate,
    blurb:
      "Generate N optimized title variations for a topic + niche. Each comes with a predicted score and rationale.",
    example: '"Give me 8 title options for a morning-routines fitness video."',
  },
  {
    name: "viewmagnet_get_outcomes",
    icon: Magnet,
    blurb:
      "Pull recent published-video performance + the per-recommendation effectiveness rollup. Closes the post-publish loop.",
    example: '"Which framework actually performed best for my last 30 videos?"',
  },
];

interface AgentEntry {
  name: string;
  blurb: string;
  configPath: string;
}

const AGENTS: AgentEntry[] = [
  {
    name: "Claude Desktop",
    blurb:
      "Anthropic's macOS / Windows / Linux app. The most popular MCP host today.",
    configPath: "~/Library/Application Support/Claude/claude_desktop_config.json",
  },
  {
    name: "Cursor",
    blurb: "The AI-native code editor. Loads MCP servers from ~/.cursor/mcp.json.",
    configPath: "~/.cursor/mcp.json",
  },
  {
    name: "Cline",
    blurb:
      "VS Code extension. Lets Cline drive the same MCP servers as Claude Desktop.",
    configPath:
      "~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json",
  },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function McpPage() {
  return (
    <>
      <SEOHead
        title="ViewMagnet MCP server — YouTube analysis tools for Claude, Cursor & Cline"
        description="Install ViewMagnet in Claude Desktop, Cursor, or Cline in one command. Your AI agent gets 10 tools — analyze YouTube videos, generate viral scripts, score hooks, detect highlights, and pull published-video outcomes — via the Model Context Protocol."
        canonicalUrl="/mcp"
        ogType="article"
        keywords="ViewMagnet MCP server, Model Context Protocol, MCP YouTube tool, Claude Desktop YouTube, Cursor MCP video, Cline content creation, viral script generator MCP, AI agent YouTube analysis, npx viewmagnet-mcp"
        markdownUrl="/mcp.md"
        article={{
          publishedTime: "2026-05-26",
          modifiedTime: "2026-05-26",
          author: "ViewMagnet",
          tags: [
            "MCP",
            "Model Context Protocol",
            "Claude Desktop",
            "Cursor",
            "Cline",
            "AI agents",
            "YouTube",
          ],
        }}
      />
      <StructuredData
        type="article"
        headline="ViewMagnet MCP Server — YouTube analysis for any AI agent"
        description="Install ViewMagnet in Claude Desktop, Cursor, or Cline in one command. Exposes 10 tools — analyze video, generate script, score hook, detect highlights, analyze pacing, score & generate titles, pull outcomes — over the Model Context Protocol."
        datePublished="2026-05-26"
        dateModified="2026-05-26"
        author="ViewMagnet"
        url="/mcp"
      />
      <StructuredData
        type="breadcrumb"
        items={[
          { name: "Home", url: "/" },
          { name: "MCP Server", url: "/mcp" },
        ]}
      />
      {/* Expose the 10 tools as a structured ItemList so AI crawlers
          can extract them for "which MCP servers analyze YouTube?"
          generative queries without scraping the DOM. */}
      <StructuredData
        type="itemList"
        name="ViewMagnet MCP Tools (v1)"
        description="The 10 tools the ViewMagnet MCP server exposes to AI agents."
        items={TOOLS.map((t) => ({
          name: t.name,
          description: t.blurb,
          url: `/mcp#${t.name}`,
        }))}
      />
      <StructuredData
        type="howTo"
        name="Install the ViewMagnet MCP server"
        description="Add ViewMagnet's 10 YouTube growth tools to Claude Desktop, Cursor, or Cline in one command."
        steps={[
          {
            name: "Generate a Personal Access Token",
            text: "From the ViewMagnet dashboard at /dashboard/api-tokens, generate a PAT and copy it once — it won't be shown again.",
          },
          {
            name: "Run the installer",
            text: "In your terminal: npx viewmagnet-mcp install. The installer detects Claude Desktop, Cursor, and Cline and writes the MCP server entry into the right config file.",
          },
          {
            name: "Restart your agent",
            text: "Fully quit and reopen Claude / Cursor / Cline. The 10 viewmagnet_* tools will appear in the agent's tool list.",
          },
        ]}
      />

      <div className="min-h-screen bg-gradient-to-b from-deep-charcoal to-gunmetal">
        <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-lg">
          <div className="container mx-auto px-4 h-16 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-glow to-amber-glow flex items-center justify-center">
                <Zap className="w-4 h-4 text-deep-charcoal" strokeWidth={2.5} />
              </div>
              <span className="text-lg font-bold">
                View<span className="text-cyan-glow">Magnet</span>
              </span>
            </Link>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" asChild>
                <a
                  href="https://www.npmjs.com/package/viewmagnet-mcp"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <ExternalLink className="w-4 h-4 mr-1.5" />
                  npm
                </a>
              </Button>
              <Button variant="ghost" size="sm" asChild>
                <Link href="/">
                  <ArrowLeft className="w-4 h-4 mr-2" />
                  Home
                </Link>
              </Button>
            </div>
          </div>
        </header>

        <main className="container mx-auto px-4 py-16 max-w-5xl">
          <Hero />
          <InstallBlock />
          <WhyThisMatters />
          <ToolsGrid />
          <ExamplePrompts />
          <SupportedAgents />
          <Cta />
        </main>
      </div>
    </>
  );
}

function Hero() {
  return (
    <section className="text-center mb-12">
      <Badge
        variant="outline"
        className="mb-4 border-cyan-glow/30 text-cyan-glow"
      >
        <Bot className="w-3 h-3 mr-1.5" />
        Model Context Protocol
      </Badge>
      <h1 className="text-4xl md:text-5xl font-bold mb-4 tracking-tight">
        ViewMagnet for any AI agent
      </h1>
      <p className="text-xl text-muted-foreground max-w-3xl mx-auto leading-relaxed">
        Install ViewMagnet in <strong>Claude Desktop</strong>,{" "}
        <strong>Cursor</strong>, or <strong>Cline</strong> in one command. Your
        agent gets 10 tools — analyze YouTube videos, generate viral scripts,
        score hooks, detect highlights, and pull post-publish outcomes —
        through the Model Context Protocol.
      </p>
    </section>
  );
}

function InstallBlock() {
  const [copied, setCopied] = useState(false);
  const command = "npx viewmagnet-mcp install";

  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      toast.success("Copied to clipboard.");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Couldn't copy — select the command manually.");
    }
  }

  return (
    <section className="mb-20">
      <Card className="bg-background/60 border-cyan-glow/30">
        <CardContent className="p-6 space-y-4">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="font-mono text-base md:text-lg break-all">
              <span className="text-muted-foreground">$</span>{" "}
              <span className="text-cyan-glow">{command}</span>
            </div>
            <Button
              onClick={copy}
              size="sm"
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
            >
              {copied ? (
                <>
                  <Check className="w-4 h-4 mr-1.5" />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="w-4 h-4 mr-1.5" />
                  Copy
                </>
              )}
            </Button>
          </div>
          <div className="grid md:grid-cols-3 gap-3 text-xs text-muted-foreground pt-2 border-t border-border/40">
            <div>
              <strong className="text-foreground block mb-0.5">1. Detect</strong>
              Finds Claude Desktop, Cursor, and Cline if they're installed.
            </div>
            <div>
              <strong className="text-foreground block mb-0.5">2. Prompt for PAT</strong>
              Generate one at{" "}
              <Link
                href="/dashboard/api-tokens"
                className="text-cyan-glow hover:underline"
              >
                /dashboard/api-tokens
              </Link>
              .
            </div>
            <div>
              <strong className="text-foreground block mb-0.5">3. Merge</strong>
              Writes the entry. Existing MCP servers in your config are kept untouched.
            </div>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

function WhyThisMatters() {
  return (
    <section className="mb-20">
      <Card className="bg-background/40 border-border/40">
        <CardContent className="p-8 prose prose-invert max-w-none">
          <h2 className="text-2xl font-semibold mb-4">
            Why use ViewMagnet from an AI agent at all?
          </h2>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Most growth tooling lives behind a dashboard. That means every
            iteration on a video — paste the URL, read the analyzer, copy a
            recommendation, switch tabs to the script writer, paste again,
            score the hook — is a context-switch tax the creator pays out of
            their own focus.
          </p>
          <p className="text-muted-foreground leading-relaxed mb-4">
            Wired into Claude or Cursor, the same loop becomes a single
            sentence: <em>"analyze this URL, write a Lead Magnet script that
              fixes the Repeat bottleneck, and score the hook."</em> The agent
            chains the tool calls for you, you get an answer, and the dashboard
            stays for the visual surfaces (Studio, Outcomes) where it actually
            earns its keep.
          </p>
          <p className="text-muted-foreground leading-relaxed">
            The MCP server is open by design: any agent that speaks the
            protocol can use it, your data stays on your account (auth is a
            revocable Personal Access Token), and the install is one
            command — no API key plumbing, no service account dance.
          </p>
        </CardContent>
      </Card>
    </section>
  );
}

function ToolsGrid() {
  return (
    <section className="mb-20">
      <h2 className="text-2xl font-bold mb-6 text-center">
        10 tools your agent can call
      </h2>
      <div className="grid md:grid-cols-2 gap-4">
        {TOOLS.map((tool) => {
          const Icon = tool.icon;
          return (
            <Card
              key={tool.name}
              id={tool.name}
              className="bg-background/40 border-border/40 scroll-mt-24"
            >
              <CardHeader className="pb-2">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-lg bg-cyan-glow/10 flex items-center justify-center shrink-0">
                    <Icon className="w-5 h-5 text-cyan-glow" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <CardTitle className="text-sm font-mono break-all">
                      {tool.name}
                    </CardTitle>
                    <CardDescription className="text-xs mt-1 leading-relaxed">
                      {tool.blurb}
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="pt-1">
                <p className="text-xs text-muted-foreground italic">
                  {tool.example}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>
      <p className="text-center text-xs text-muted-foreground mt-6">
        Async tools (clip extraction, Studio render, scheduled publish) land in
        v2 — they need server-side job-polling refactors. Tracked publicly.
      </p>
    </section>
  );
}

function ExamplePrompts() {
  const prompts = [
    'Analyze https://youtu.be/dQw4w9WgXcQ and tell me what to fix.',
    'Write a Delta Shift script about why most morning routines waste your time.',
    "Score this hook on a 0-100 scale: 'Most diets are designed to fail.'",
    'Find the 5 best clip moments from this podcast: https://youtu.be/…',
    'Give me 8 title variations for a finance video about index funds.',
    "Pull my recent outcomes and tell me which framework actually performed best.",
  ];
  return (
    <section className="mb-20">
      <h2 className="text-2xl font-bold mb-6 text-center">
        Try these prompts in your agent
      </h2>
      <Card className="bg-background/40 border-border/40">
        <CardContent className="p-6">
          <ul className="space-y-3">
            {prompts.map((p) => (
              <li key={p} className="flex items-start gap-3 text-sm">
                <Sparkles className="w-4 h-4 text-cyan-glow mt-0.5 shrink-0" />
                <span className="text-muted-foreground italic">"{p}"</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </section>
  );
}

function SupportedAgents() {
  return (
    <section className="mb-20">
      <h2 className="text-2xl font-bold mb-6 text-center">
        Works with the agents you already use
      </h2>
      <div className="grid md:grid-cols-3 gap-4">
        {AGENTS.map((agent) => (
          <Card key={agent.name} className="bg-background/40 border-border/40">
            <CardHeader>
              <CardTitle className="text-base">{agent.name}</CardTitle>
              <CardDescription className="text-xs">
                {agent.blurb}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-[11px] text-muted-foreground font-mono break-all">
                {agent.configPath}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
      <p className="text-center text-xs text-muted-foreground mt-6">
        Other MCP client?{" "}
        <code className="font-mono text-foreground">npx viewmagnet-mcp install --print</code>
        {" "}prints the JSON snippet to paste into any config file.
      </p>
    </section>
  );
}

function Cta() {
  return (
    <section className="mb-12 text-center">
      <Card className="bg-gradient-to-br from-cyan-glow/10 via-background/40 to-amber-glow/5 border-cyan-glow/30">
        <CardContent className="p-10 space-y-4">
          <KeyRound className="w-10 h-10 text-cyan-glow mx-auto" />
          <h2 className="text-2xl font-bold">
            Generate a token and install it in two clicks
          </h2>
          <p className="text-sm text-muted-foreground max-w-xl mx-auto">
            Personal Access Tokens are revocable, scope-limited, and
            tied to your account. Free plan and up.
          </p>
          <div className="flex items-center justify-center gap-3 flex-wrap pt-2">
            <Button
              asChild
              size="lg"
              className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
            >
              <Link href="/dashboard/api-tokens">
                <KeyRound className="w-4 h-4 mr-1.5" />
                Generate token
                <ArrowRight className="w-4 h-4 ml-1.5" />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <a
                href="https://www.npmjs.com/package/viewmagnet-mcp"
                target="_blank"
                rel="noopener noreferrer"
              >
                <FileText className="w-4 h-4 mr-1.5" />
                Read the npm README
              </a>
            </Button>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}
