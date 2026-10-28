/*
 * A/B Tester: Compare title/thumbnail variations pre-upload
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  FlaskConical,
  Plus,
  Trophy,
  BarChart3,
  Type,
  Image,
  ArrowRight,
  Sparkles,
  Loader2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { simulateABTest } from "@/lib/api";

interface TestResult {
  id: number;
  variantA: string;
  variantB: string;
  scoreA: number;
  scoreB: number;
  winner: string;
  reason: string;
  date: string;
}

const titleTests: TestResult[] = [
  {
    id: 1,
    variantA: "I Built a $10K/mo SaaS in 30 Days",
    variantB: "How to Build a Profitable SaaS From Scratch",
    scoreA: 87,
    scoreB: 71,
    winner: "A",
    reason: "Personal story pattern + specific number outperforms generic 'How to' by 22%",
    date: "2 hours ago",
  },
  {
    id: 2,
    variantA: "5 VS Code Extensions That Changed My Life",
    variantB: "Best VS Code Extensions for 2026",
    scoreA: 82,
    scoreB: 76,
    winner: "A",
    reason: "Emotional hook + specific number beats generic 'Best' title by 8%",
    date: "1 day ago",
  },
  {
    id: 3,
    variantA: "Why I Quit My $200K Job to Code Full Time",
    variantB: "Quitting My Job to Become a Full-Time Developer",
    scoreA: 91,
    scoreB: 84,
    winner: "A",
    reason: "'Why I...' pattern with salary number creates stronger curiosity gap",
    date: "3 days ago",
  },
];

export default function ABTester() {
  const [titleA, setTitleA] = useState("");
  const [titleB, setTitleB] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResults, setTestResults] = useState<TestResult[]>(titleTests);
  const [latestResult, setLatestResult] = useState<TestResult | null>(null);

  const handleTest = async () => {
    if (!titleA.trim() || !titleB.trim()) {
      toast.error("Please enter both title variations");
      return;
    }
    setTesting(true);
    
    try {
      const result = await simulateABTest({
        variation_a: titleA,
        variation_b: titleB,
        test_type: "title",
        sample_size: 1000,
      });

      const newResult: TestResult = {
        id: Date.now(),
        variantA: titleA,
        variantB: titleB,
        scoreA: result.variation_a.score,
        scoreB: result.variation_b.score,
        winner: result.winner,
        reason: result.recommendation,
        date: "Just now",
      };

      setLatestResult(newResult);
      setTestResults((prev) => [newResult, ...prev]);
      toast.success(`Variant ${result.winner} is strongest by the packaging rubric`);
    } catch (error) {
      console.error("A/B test failed:", error);
      // Surface the failure rather than fabricating a "winner" with a random
      // score — that was actively misleading.
      toast.error("Couldn't run the A/B simulation right now. Please try again.");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          A/B Tester
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Compare title and thumbnail variations against proven packaging principles — coaching to help you pick, not a CTR or performance prediction. The audience decides once it's live.
        </p>
      </div>

      <Tabs defaultValue="titles" className="space-y-6">
        <TabsList className="bg-secondary/50">
          <TabsTrigger value="titles" className="gap-1.5">
            <Type className="w-3.5 h-3.5" />
            Title Test
          </TabsTrigger>
          <TabsTrigger value="thumbnails" className="gap-1.5">
            <Image className="w-3.5 h-3.5" />
            Thumbnail Test
          </TabsTrigger>
        </TabsList>

        <TabsContent value="titles" className="space-y-6">
          {/* New Test */}
          <Card className="bg-card border-border/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">New Title Test</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-medium text-cyan-glow mb-1.5 block font-[var(--font-mono)]">
                    VARIANT A
                  </label>
                  <Input
                    placeholder="Enter first title variation..."
                    value={titleA}
                    onChange={(e) => setTitleA(e.target.value)}
                    className="bg-secondary/50 border-border/50"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-amber-glow mb-1.5 block font-[var(--font-mono)]">
                    VARIANT B
                  </label>
                  <Input
                    placeholder="Enter second title variation..."
                    value={titleB}
                    onChange={(e) => setTitleB(e.target.value)}
                    className="bg-secondary/50 border-border/50"
                  />
                </div>
              </div>
              <Button
                onClick={handleTest}
                disabled={testing}
                className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
              >
                {testing ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <FlaskConical className="w-4 h-4 mr-2" />
                )}
                Run A/B Test
              </Button>
            </CardContent>
          </Card>

          {/* Previous Tests */}
          <div>
            <h2 className="text-sm font-semibold text-foreground mb-3">Previous Tests</h2>
            <div className="space-y-4">
              {titleTests.map((test) => (
                <Card key={test.id} className="bg-card border-border/50">
                  <CardContent className="p-5">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                      {/* Variant A */}
                      <div
                        className={`p-4 rounded-lg border ${
                          test.winner === "A"
                            ? "bg-cyan-glow/5 border-cyan-glow/30"
                            : "bg-secondary/30 border-border/30"
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <Badge
                            variant="outline"
                            className="text-[10px] border-cyan-glow/30 text-cyan-glow"
                          >
                            Variant A
                          </Badge>
                          <div className="flex items-center gap-1.5">
                            {test.winner === "A" && (
                              <Trophy className="w-3.5 h-3.5 text-amber-glow" />
                            )}
                            <span
                              className={`text-lg font-bold font-[var(--font-display)] ${
                                test.winner === "A" ? "text-cyan-glow" : "text-muted-foreground"
                              }`}
                            >
                              {test.scoreA}
                            </span>
                          </div>
                        </div>
                        <p className="text-sm text-foreground">{test.variantA}</p>
                      </div>

                      {/* Variant B */}
                      <div
                        className={`p-4 rounded-lg border ${
                          test.winner === "B"
                            ? "bg-amber-glow/5 border-amber-glow/30"
                            : "bg-secondary/30 border-border/30"
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <Badge
                            variant="outline"
                            className="text-[10px] border-amber-glow/30 text-amber-glow"
                          >
                            Variant B
                          </Badge>
                          <div className="flex items-center gap-1.5">
                            {test.winner === "B" && (
                              <Trophy className="w-3.5 h-3.5 text-amber-glow" />
                            )}
                            <span
                              className={`text-lg font-bold font-[var(--font-display)] ${
                                test.winner === "B" ? "text-amber-glow" : "text-muted-foreground"
                              }`}
                            >
                              {test.scoreB}
                            </span>
                          </div>
                        </div>
                        <p className="text-sm text-foreground">{test.variantB}</p>
                      </div>
                    </div>

                    {/* Explanation */}
                    <div className="p-3 rounded-lg bg-secondary/20 border border-border/20">
                      <div className="flex items-start gap-2">
                        <Sparkles className="w-4 h-4 text-cyan-glow shrink-0 mt-0.5" />
                        <div>
                          <p className="text-xs font-medium text-foreground">ML Analysis</p>
                          <p className="text-xs text-muted-foreground mt-0.5">{test.reason}</p>
                        </div>
                      </div>
                    </div>

                    <p className="text-[10px] text-muted-foreground mt-3">{test.date}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="thumbnails" className="space-y-6">
          <Card className="bg-card border-border/50">
            <CardContent className="p-8 text-center">
              <div className="w-16 h-16 rounded-2xl bg-amber-glow/10 flex items-center justify-center mx-auto mb-4">
                <Image className="w-8 h-8 text-amber-glow" />
              </div>
              <h3 className="text-lg font-semibold font-[var(--font-display)] text-foreground">
                Thumbnail A/B Testing
              </h3>
              <p className="text-sm text-muted-foreground mt-2 max-w-md mx-auto">
                Upload two thumbnail variations and our CLIP + MobileNetV3 models will predict which one
                will drive more clicks based on your niche's visual patterns.
              </p>
              <Button className="mt-4 bg-amber-glow text-deep-charcoal hover:bg-amber-glow/90 font-semibold">
                <Plus className="w-4 h-4 mr-2" />
                Upload Thumbnails
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
