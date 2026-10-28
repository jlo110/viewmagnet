import { Link } from "wouter";
import { ArrowLeft, Zap, Calendar, Clock, User, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export interface BlogPostProps {
  title: string;
  excerpt: string;
  category: string;
  date: string;
  readTime: string;
  author?: {
    name: string;
    role: string;
  };
  children: React.ReactNode;
  relatedPosts?: {
    slug: string;
    title: string;
    category: string;
  }[];
}

const categoryColors: Record<string, string> = {
  Research: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  Algorithm: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  Tips: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  Strategy: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  Wellness: "bg-pink-500/10 text-pink-400 border-pink-500/20",
};

export default function BlogPost({
  title,
  excerpt,
  category,
  date,
  readTime,
  author = { name: "ViewMagnet Team", role: "Data Science" },
  children,
  relatedPosts = [],
}: BlogPostProps) {
  return (
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
            <Link href="/blog">
              <ArrowLeft className="w-4 h-4 mr-2" />
              All Articles
            </Link>
          </Button>
        </div>
      </header>

      <main className="container mx-auto px-4 py-12 max-w-4xl">
        <article>
          <header className="mb-10">
            <div className="flex items-center gap-3 mb-4">
              <Badge variant="outline" className={categoryColors[category] || categoryColors.Research}>
                {category}
              </Badge>
              <span className="text-sm text-muted-foreground flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {readTime}
              </span>
            </div>
            
            <h1 className="text-3xl md:text-4xl font-bold mb-4 leading-tight">
              {title}
            </h1>
            
            <p className="text-xl text-muted-foreground mb-6">
              {excerpt}
            </p>

            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-full bg-cyan-glow/20 flex items-center justify-center">
                <User className="w-5 h-5 text-cyan-glow" />
              </div>
              <div>
                <p className="text-sm font-medium">{author.name}</p>
                <p className="text-xs text-muted-foreground">{author.role}</p>
              </div>
              <Separator orientation="vertical" className="h-8" />
              <div className="flex items-center gap-1 text-sm text-muted-foreground">
                <Calendar className="w-4 h-4" />
                {date}
              </div>
            </div>
          </header>

          <div className="prose prose-invert prose-cyan max-w-none">
            {children}
          </div>

          <Separator className="my-12" />

          <div className="bg-gradient-to-r from-cyan-glow/10 to-amber-glow/10 rounded-xl p-8 text-center">
            <h3 className="text-xl font-semibold mb-2">Ready to optimize your videos?</h3>
            <p className="text-muted-foreground mb-6">
              Get AI-powered insights for your YouTube content with ViewMagnet.
            </p>
            <div className="flex gap-4 justify-center">
              <Button asChild className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90">
                <Link href="/signup">Start Free Trial</Link>
              </Button>
              <Button variant="outline" asChild>
                <Link href="/dashboard/analyzer">Try Video Analyzer</Link>
              </Button>
            </div>
          </div>

          {relatedPosts.length > 0 && (
            <section className="mt-12">
              <h3 className="text-lg font-semibold mb-6">Related Articles</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {relatedPosts.map((post) => (
                  <Card key={post.slug} className="bg-card/50 border-border/50 hover:bg-card/70 transition-colors">
                    <CardContent className="p-4">
                      <Link href={`/blog/${post.slug}`} className="group">
                        <Badge variant="outline" className={`${categoryColors[post.category] || categoryColors.Research} mb-2`}>
                          {post.category}
                        </Badge>
                        <h4 className="font-medium group-hover:text-cyan-glow transition-colors flex items-center gap-1">
                          {post.title}
                          <ChevronRight className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" />
                        </h4>
                      </Link>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          )}
        </article>
      </main>
    </div>
  );
}




