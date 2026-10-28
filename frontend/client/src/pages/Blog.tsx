import { Link } from "wouter";
import { ArrowLeft, Zap, Clock, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SEOHead, StructuredData } from "@/components/seo";

const posts = [
  {
    slug: "thumbnail-psychology-2026",
    title: "The Psychology of Thumbnails: What Makes Viewers Click in 2026",
    excerpt: "We analyzed 50,000 thumbnails to find out what visual elements drive the highest CTR. The results might surprise you.",
    category: "Research",
    date: "Feb 18, 2026",
    readTime: "8 min read",
  },
  {
    slug: "algorithm-changes-february",
    title: "YouTube Algorithm Update: What Changed in February 2026",
    excerpt: "A deep dive into the latest algorithm shifts and how they affect content discovery and recommendations.",
    category: "Algorithm",
    date: "Feb 15, 2026",
    readTime: "6 min read",
  },
  {
    slug: "title-formulas-that-work",
    title: "7 Title Formulas That Actually Work (Backed by Data)",
    excerpt: "Not all title formulas are created equal. Here are the ones our ML model consistently ranks as high performers.",
    category: "Tips",
    date: "Feb 10, 2026",
    readTime: "5 min read",
  },
  {
    slug: "shorts-vs-longform",
    title: "Shorts vs Long-Form: Where Should You Focus Your Energy?",
    excerpt: "A data-driven analysis of how Shorts impact your long-form content and channel growth trajectory.",
    category: "Strategy",
    date: "Feb 5, 2026",
    readTime: "7 min read",
  },
  {
    slug: "posting-time-myths",
    title: "The Best Time to Post: Debunking Common Myths",
    excerpt: "We analyzed posting times across 10,000 channels. The 'best time' is more nuanced than you think.",
    category: "Research",
    date: "Jan 28, 2026",
    readTime: "6 min read",
  },
  {
    slug: "creator-burnout-prevention",
    title: "Sustainable Growth: Preventing Creator Burnout",
    excerpt: "90% of creators experience burnout. Here's how successful channels maintain consistency without sacrificing mental health.",
    category: "Wellness",
    date: "Jan 20, 2026",
    readTime: "9 min read",
  },
];

const categoryColors: Record<string, string> = {
  Research: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  Algorithm: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  Tips: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  Strategy: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  Wellness: "bg-pink-500/10 text-pink-400 border-pink-500/20",
};

export default function Blog() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-deep-charcoal to-gunmetal">
      <SEOHead
        title="Blog — YouTube Growth Tips &amp; Research"
        description="Expert insights on YouTube growth, algorithm updates, thumbnail psychology, hook formulas, and data-driven strategies to grow your channel."
        canonicalUrl="/blog"
        keywords="YouTube growth, YouTube algorithm, thumbnail psychology, hook formulas, creator strategy, YouTube SEO, video retention"
      />
      <StructuredData
        type="breadcrumb"
        items={[
          { name: "Home", url: "/" },
          { name: "Blog", url: "/blog" },
        ]}
      />
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
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold mb-4">Blog</h1>
          <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
            Data-driven insights, YouTube strategy tips, and creator resources.
          </p>
        </div>

        <div className="space-y-6">
          {posts.map((post) => (
            <Link key={post.slug} href={`/blog/${post.slug}`}>
              <Card className="bg-card/50 border-border/50 hover:bg-card/70 transition-colors cursor-pointer">
                <CardContent className="p-6">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-3">
                        <Badge variant="outline" className={categoryColors[post.category]}>
                          {post.category}
                        </Badge>
                        <span className="text-xs text-muted-foreground flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {post.readTime}
                        </span>
                      </div>
                      <h2 className="text-xl font-semibold mb-2 hover:text-cyan-glow transition-colors">
                        {post.title}
                      </h2>
                      <p className="text-muted-foreground text-sm mb-3">
                        {post.excerpt}
                      </p>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted-foreground">{post.date}</span>
                        <Button variant="ghost" size="sm" className="text-cyan-glow">
                          Read More <ArrowRight className="w-3 h-3 ml-1" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>

        <div className="text-center mt-12">
          <p className="text-muted-foreground mb-4">
            More articles coming soon. Subscribe to stay updated.
          </p>
          <Button variant="outline">Subscribe to Newsletter</Button>
        </div>
      </main>
    </div>
  );
}




