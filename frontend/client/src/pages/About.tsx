import { Link } from "wouter";
import { ArrowLeft, Zap, Target, Users, Sparkles, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { SEOHead, StructuredData } from "@/components/seo";

const values = [
  {
    icon: Target,
    title: "Data-Driven Decisions",
    description: "Every recommendation is backed by analysis of 144,641+ YouTube videos across 50+ niches.",
  },
  {
    icon: Users,
    title: "Creator-First",
    description: "Built for creators who'd rather know than guess — the whole idea-to-publish loop in one app.",
  },
  {
    icon: Sparkles,
    title: "Continuous Improvement",
    description: "The prediction models are retrained as new data lands, so the analyzer keeps pace with the algorithm.",
  },
  {
    icon: TrendingUp,
    title: "Honest About Accuracy",
    description: "The pre-upload model scores 74.58% balanced accuracy on a held-out test set — and we tell you when we're unsure.",
  },
];

export default function About() {
  return (
    <>
    <SEOHead
      title="About ViewMagnet"
      description="Built by creators, for creators. ViewMagnet predicts video performance with ML, generates scripts on proven frameworks, and ships every step from idea to publish in one app."
      canonicalUrl="/about"
      keywords="about ViewMagnet, YouTube growth platform, AI for creators, creator workflow tool"
    />
    <StructuredData type="organization" />
    <StructuredData
      type="breadcrumb"
      items={[
        { name: "Home", url: "/" },
        { name: "About", url: "/about" },
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

      <main className="container mx-auto px-4 py-16 max-w-4xl">
        <div className="text-center mb-16">
          <h1 className="text-4xl font-bold mb-4">About ViewMagnet</h1>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            We're on a mission to democratize YouTube success through AI-powered analytics and insights.
          </p>
        </div>

        <section className="mb-16">
          <h2 className="text-2xl font-semibold mb-6">Our Story</h2>
          <div className="prose prose-invert prose-cyan max-w-none">
            <p className="text-muted-foreground leading-relaxed mb-4">
              ViewMagnet started with a simple frustration: why do some YouTube videos take off while
              others—seemingly just as good—barely get any views? The goal was to answer that with
              data instead of guesswork.
            </p>
            <p className="text-muted-foreground leading-relaxed mb-4">
              That meant analyzing 144,641 videos across 50+ niches to find the patterns that separate
              videos that beat a channel's baseline from the ones that stall. Those patterns became a
              machine-learning model that predicts performance <em>before</em> you upload, plus a set
              of tools that turn each prediction into a concrete next step — a better hook, a tighter
              title, a fix for the pacing.
            </p>
            <p className="text-muted-foreground leading-relaxed">
              Today ViewMagnet runs the whole loop in one place: predict, write, edit in Studio, and
              publish — without switching between half a dozen tools. We're deliberate about being
              honest with the numbers; you can read exactly how the models work, and what they
              deliberately don't see, on the{" "}
              <Link href="/methodology" className="text-cyan-glow hover:underline">methodology page</Link>.
            </p>
          </div>
        </section>

        <section className="mb-16">
          <h2 className="text-2xl font-semibold mb-6">Our Values</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {values.map((value) => (
              <Card key={value.title} className="bg-card/50 border-border/50">
                <CardContent className="p-6">
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-lg bg-cyan-glow/10 flex items-center justify-center shrink-0">
                      <value.icon className="w-5 h-5 text-cyan-glow" />
                    </div>
                    <div>
                      <h3 className="font-semibold mb-2">{value.title}</h3>
                      <p className="text-sm text-muted-foreground">{value.description}</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <section className="text-center">
          <h2 className="text-2xl font-semibold mb-4">Ready to grow your channel?</h2>
          <p className="text-muted-foreground mb-6">
            Start free and make your next upload a data-driven decision.
          </p>
          <div className="flex gap-4 justify-center">
            <Button asChild className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90">
              <Link href="/signup">Get Started Free</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link href="/contact">Contact Us</Link>
            </Button>
          </div>
        </section>
      </main>
    </div>
    </>
  );
}




