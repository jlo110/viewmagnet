/**
 * SEOHead — drop-in head-tag manager for every public page.
 *
 * Why each block is here:
 *
 *   * **Title / description / canonical / OG / Twitter** — standard
 *     SEO. Owned by ``react-helmet-async`` so per-page values
 *     override the defaults in ``index.html`` without a flash.
 *   * **``meta name="robots"`` with ``max-snippet`` etc.** — caps
 *     and floors for what crawlers can extract. We use generous
 *     limits because generative-engine snippets need more than the
 *     classic 160-char meta description to actually quote a useful
 *     paragraph.
 *   * **AI-crawler hint tags** (``ChatGPT-User``, ``GPTBot``,
 *     ``ClaudeBot``, ``PerplexityBot``, ``Google-Extended``) — a
 *     few of the generative engines respect per-URL meta hints in
 *     addition to robots.txt. We explicitly opt in unless the page
 *     is marked ``noIndex``.
 *   * **``article:published_time`` / ``modified_time``** — fed
 *     into ``Article`` JSON-LD elsewhere; also surfaced directly
 *     on Twitter and OpenGraph so the rendered card shows a date.
 *   * **``keywords`` meta** — Google ignores it, but some
 *     generative engines (Perplexity in particular) still weight
 *     it during indexing. Cheap to include.
 *
 * If a page is marked ``noIndex`` the AI-bot opt-ins flip to
 * ``noindex`` too — we never want a private page indexed by
 * Google but cited by ChatGPT.
 */
import { Helmet } from "react-helmet-async";

interface SEOHeadProps {
  title?: string;
  description?: string;
  canonicalUrl?: string;
  ogImage?: string;
  ogType?: "website" | "article";
  /**
   * Comma-separated keywords. Ignored by Google but still
   * weighted by some generative engines and a few non-Google
   * search indexes (Kagi, Marginalia). Cheap to include for a
   * GEO bump.
   */
  keywords?: string;
  article?: {
    publishedTime?: string;
    modifiedTime?: string;
    author?: string;
    tags?: string[];
  };
  noIndex?: boolean;
  /**
   * Absolute path to the per-page plain-markdown twin (e.g.
   * "/methodology.md"). When provided, a
   * ``<link rel="alternate" type="text/markdown">`` tag is
   * injected — the standard discovery signal for AI crawlers
   * that prefer markdown over HTML (per the GEO research
   * showing markdown reliably surfaces in LLM responses).
   */
  markdownUrl?: string;
}

const BASE_URL = "https://viewmagnet.io";
// Reviewer feedback: "AI-Powered" is table-stakes language at this
// point. We lead with positioning — predict / create / publish in one
// app — which mirrors the actual creator loop we own end-to-end.
const DEFAULT_TITLE =
  "ViewMagnet — Predict, create, publish: the full YouTube workflow";
const DEFAULT_DESCRIPTION =
  "Predict a video's performance before you film it, then script + edit + publish in one app. The full YouTube creator loop, no tool-switching.";
const DEFAULT_OG_IMAGE = `${BASE_URL}/og-image.png`;

export default function SEOHead({
  title,
  description = DEFAULT_DESCRIPTION,
  canonicalUrl,
  ogImage = DEFAULT_OG_IMAGE,
  ogType = "website",
  keywords,
  article,
  noIndex = false,
  markdownUrl,
}: SEOHeadProps) {
  const fullTitle = title ? `${title} | ViewMagnet` : DEFAULT_TITLE;
  const fullCanonical = canonicalUrl
    ? `${BASE_URL}${canonicalUrl}`
    : BASE_URL;

  // Generous snippet caps so generative engines can quote a real
  // paragraph (the 2024 Google default of -1 lets the engine pick).
  // We pass an explicit cap to discourage random truncation.
  const robotsDirective = noIndex
    ? "noindex, nofollow"
    : "index, follow, max-snippet:320, max-image-preview:large, max-video-preview:-1";

  // AI-crawler per-URL opt-in (some engines honor these even when
  // robots.txt is permissive). The string must match the bot's
  // user-agent token exactly.
  const aiCrawlerDirective = noIndex ? "noindex" : "index";
  const aiCrawlers = [
    "GPTBot",
    "ChatGPT-User",
    "ClaudeBot",
    "anthropic-ai",
    "PerplexityBot",
    "Google-Extended",
    "Applebot-Extended",
    "Bytespider",
    "CCBot",
  ];

  return (
    <Helmet>
      {/* Basic Meta Tags */}
      <title>{fullTitle}</title>
      <meta name="description" content={description} />
      {keywords && <meta name="keywords" content={keywords} />}
      {canonicalUrl && <link rel="canonical" href={fullCanonical} />}

      {/* Per-page markdown alternate — discovery signal for AI
          crawlers that prefer clean markdown over HTML. Research
          shows markdown reliably surfaces in LLM responses; bots
          that respect this link skip the React shell entirely. */}
      {markdownUrl && (
        <link
          rel="alternate"
          type="text/markdown"
          href={`${BASE_URL}${markdownUrl}`}
        />
      )}

      {/* Crawler directives — generous snippet caps so generative
          engines can extract a usable paragraph. */}
      <meta name="robots" content={robotsDirective} />
      <meta name="googlebot" content={robotsDirective} />
      <meta name="bingbot" content={robotsDirective} />

      {/* Per-URL hints for generative-engine crawlers. */}
      {aiCrawlers.map((bot) => (
        <meta key={bot} name={bot} content={aiCrawlerDirective} />
      ))}

      {/* Open Graph */}
      <meta property="og:title" content={fullTitle} />
      <meta property="og:description" content={description} />
      <meta property="og:image" content={ogImage} />
      <meta property="og:image:alt" content={fullTitle} />
      <meta property="og:url" content={fullCanonical} />
      <meta property="og:type" content={ogType} />
      <meta property="og:site_name" content="ViewMagnet" />
      <meta property="og:locale" content="en_US" />

      {/* Twitter Card */}
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:site" content="@viewmagnet" />
      <meta name="twitter:title" content={fullTitle} />
      <meta name="twitter:description" content={description} />
      <meta name="twitter:image" content={ogImage} />
      <meta name="twitter:image:alt" content={fullTitle} />

      {/* Article-specific meta (for blog posts + guides) */}
      {ogType === "article" && article && (
        <>
          {article.publishedTime && (
            <meta
              property="article:published_time"
              content={article.publishedTime}
            />
          )}
          {article.modifiedTime && (
            <meta
              property="article:modified_time"
              content={article.modifiedTime}
            />
          )}
          {article.author && (
            <meta property="article:author" content={article.author} />
          )}
          {article.tags?.map((tag) => (
            <meta key={tag} property="article:tag" content={tag} />
          ))}
        </>
      )}
    </Helmet>
  );
}
