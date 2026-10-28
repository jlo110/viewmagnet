import { Link } from "wouter";
import { ArrowLeft, Zap, Sparkles, Bug, Wrench, Rocket } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SEOHead, StructuredData } from "@/components/seo";

interface ChangelogEntry {
  version: string;
  date: string;
  changes: {
    type: "feature" | "improvement" | "fix";
    description: string;
  }[];
}

const changelog: ChangelogEntry[] = [
  {
    version: "2.4.0",
    date: "February 20, 2026",
    changes: [
      { type: "feature", description: "Added collapsible sections across all dashboard tabs for better UX" },
      { type: "feature", description: "Implemented JWT authentication with secure login/signup flow" },
      { type: "feature", description: "Migrated to Supabase PostgreSQL for improved scalability" },
      { type: "improvement", description: "Enhanced velocity mode scoring for more accurate early predictions" },
      { type: "fix", description: "Fixed score calculation issue affecting new videos" },
    ],
  },
  {
    version: "2.3.0",
    date: "February 12, 2026",
    changes: [
      { type: "feature", description: "New 'Why This Score?' detailed breakdown showing factor contributions" },
      { type: "feature", description: "Anti-over-optimization warnings to prevent gaming the system" },
      { type: "feature", description: "Niche-aware messaging throughout the analysis UI" },
      { type: "improvement", description: "Updated ML model with 15,000 additional training videos" },
    ],
  },
  {
    version: "2.2.0",
    date: "February 1, 2026",
    changes: [
      { type: "feature", description: "Velocity Tracker for monitoring real-time video performance" },
      { type: "feature", description: "Competitor Analysis with side-by-side channel comparisons" },
      { type: "improvement", description: "Redesigned dashboard with Signal Flow dark theme" },
      { type: "fix", description: "Resolved thumbnail analysis timeout issues" },
    ],
  },
  {
    version: "2.1.0",
    date: "January 20, 2026",
    changes: [
      { type: "feature", description: "AI-powered Script Writer with customizable tone and length" },
      { type: "feature", description: "Keyword Research tool with search volume estimates" },
      { type: "improvement", description: "Faster video analysis with optimized API calls" },
      { type: "fix", description: "Fixed channel connection issues for some YouTube accounts" },
    ],
  },
  {
    version: "2.0.0",
    date: "January 5, 2026",
    changes: [
      { type: "feature", description: "Complete platform redesign with new Kinetic Minimalism UI" },
      { type: "feature", description: "Multi-mode analysis: Prediction, Velocity, and Evaluation modes" },
      { type: "feature", description: "Winning Formula page with hit vs flop pattern analysis" },
      { type: "improvement", description: "87% prediction accuracy achieved with new ML architecture" },
    ],
  },
];

const typeConfig = {
  feature: { icon: Sparkles, label: "New", className: "bg-cyan-glow/10 text-cyan-glow border-cyan-glow/20" },
  improvement: { icon: Rocket, label: "Improved", className: "bg-amber-500/10 text-amber-400 border-amber-500/20" },
  fix: { icon: Bug, label: "Fixed", className: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
};

export default function Changelog() {
  return (
    <>
    <SEOHead
      title="Changelog"
      description="Release notes, new features, bug fixes, and shipping updates for ViewMagnet's prediction, script writer, studio editor, and distribution hub."
      canonicalUrl="/changelog"
    />
    <StructuredData
      type="breadcrumb"
      items={[
        { name: "Home", url: "/" },
        { name: "Changelog", url: "/changelog" },
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
          <Button variant="ghost" size="sm" asChild>
            <Link href="/">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Home
            </Link>
          </Button>
        </div>
      </header>

      <main className="container mx-auto px-4 py-16 max-w-3xl">
        <div className="text-center mb-12">
          <div className="flex items-center justify-center gap-2 mb-4">
            <Wrench className="w-8 h-8 text-cyan-glow" />
          </div>
          <h1 className="text-4xl font-bold mb-4">Changelog</h1>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            All the latest updates, improvements, and fixes to ViewMagnet.
          </p>
        </div>

        <div className="space-y-8">
          {changelog.map((entry) => (
            <Card key={entry.version} className="bg-card/50 border-border/50">
              <CardContent className="p-6">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <Badge className="bg-cyan-glow/10 text-cyan-glow border-cyan-glow/20 font-mono">
                      v{entry.version}
                    </Badge>
                    <span className="text-sm text-muted-foreground">{entry.date}</span>
                  </div>
                </div>
                <ul className="space-y-3">
                  {entry.changes.map((change, index) => {
                    const config = typeConfig[change.type];
                    return (
                      <li key={index} className="flex items-start gap-3">
                        <Badge variant="outline" className={`${config.className} shrink-0 text-[10px]`}>
                          {config.label}
                        </Badge>
                        <span className="text-sm text-muted-foreground">{change.description}</span>
                      </li>
                    );
                  })}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="text-center mt-12">
          <p className="text-muted-foreground">
            Want to be notified of new releases?{" "}
            <Link href="/signup" className="text-cyan-glow hover:underline">
              Create an account
            </Link>
          </p>
        </div>
      </main>
    </div>
    </>
  );
}




