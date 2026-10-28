/**
 * StructuredData — single-source-of-truth for JSON-LD on every
 * marketing page.
 *
 * Why this matters for SEO and GEO:
 *
 *   * Google still leans on JSON-LD to populate rich results
 *     (FAQ accordions, breadcrumb trails, HowTo carousels,
 *     software-app star ratings).
 *   * Generative engines (ChatGPT Search, Perplexity, Claude
 *     web-mode, Bing Copilot) lean on the same schema tags to
 *     decide whether a page is a citation-worthy primary source.
 *     A page that ships explicit ``FAQPage`` / ``HowTo`` /
 *     ``Article`` markup is far more likely to be quoted with
 *     attribution than a page that only ships paragraphs.
 *
 * Add new schema types here rather than inlining JSON-LD on the
 * page — that way we get one place to validate and one place to
 * update if the spec drifts.
 *
 * Every schema we emit must validate against
 * https://validator.schema.org/. If you add a new type, run it
 * through the validator before merging.
 */
import { Helmet } from "react-helmet-async";

const BASE_URL = "https://viewmagnet.io";

// ---------------------------------------------------------------------------
// Schema prop types
// ---------------------------------------------------------------------------

interface OrganizationSchemaProps {
  type: "organization";
}

interface WebSiteSchemaProps {
  type: "website";
}

interface ArticleSchemaProps {
  type: "article";
  headline: string;
  description: string;
  image?: string;
  datePublished: string;
  dateModified?: string;
  author?: string;
  /**
   * Optional canonical URL for the article (relative path). When
   * provided we point the ``mainEntityOfPage`` at the article
   * itself instead of the site root — Google and Perplexity both
   * use this to attribute the snippet correctly.
   */
  url?: string;
}

interface ProductSchemaProps {
  type: "product";
  name: string;
  description: string;
  offers: {
    price: number;
    priceCurrency: string;
    availability?: "InStock" | "OutOfStock";
  }[];
}

/**
 * SaaS / web-app schema. Distinct from Product because Google
 * surfaces SoftwareApplication results with their own rich card
 * (operating system, application category, free-tier badge).
 */
interface SoftwareApplicationSchemaProps {
  type: "softwareApplication";
  name: string;
  description: string;
  applicationCategory: string;
  operatingSystem?: string;
  offers?: {
    price: number;
    priceCurrency: string;
  }[];
  aggregateRating?: {
    ratingValue: number;
    ratingCount: number;
  };
}

/**
 * FAQ rich-result schema. Google deprecated the visual FAQ-card
 * SERP in 2023 for most sites, BUT generative engines still
 * preferentially cite pages with FAQPage markup because it's the
 * cleanest machine-readable answer format. We keep using it.
 */
interface FAQSchemaProps {
  type: "faq";
  questions: { question: string; answer: string }[];
}

/**
 * HowTo schema. Reads naturally as step-by-step content to AI
 * crawlers and remains a viable rich-result type. Use it on
 * tutorial-flavoured guides like the Analyzer Guide bottleneck
 * fixes.
 */
interface HowToSchemaProps {
  type: "howTo";
  name: string;
  description: string;
  totalTime?: string;
  steps: { name: string; text: string; url?: string }[];
}

/**
 * Breadcrumbs. Even on a flat site, breadcrumb markup tells
 * crawlers (both Google and AI) the page hierarchy without them
 * having to parse the nav. Always include on nested guides.
 */
interface BreadcrumbSchemaProps {
  type: "breadcrumb";
  items: { name: string; url: string }[];
}

/**
 * ItemList — useful for index-style pages (the four frameworks,
 * the six hook types). Lets AI crawlers extract the list as
 * structured data instead of having to scrape the DOM.
 */
interface ItemListSchemaProps {
  type: "itemList";
  name: string;
  description?: string;
  items: { name: string; description?: string; url?: string }[];
}

type StructuredDataProps =
  | OrganizationSchemaProps
  | WebSiteSchemaProps
  | ArticleSchemaProps
  | ProductSchemaProps
  | SoftwareApplicationSchemaProps
  | FAQSchemaProps
  | HowToSchemaProps
  | BreadcrumbSchemaProps
  | ItemListSchemaProps;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function StructuredData(props: StructuredDataProps) {
  let schema: Record<string, unknown>;

  switch (props.type) {
    case "organization":
      schema = {
        "@context": "https://schema.org",
        "@type": "Organization",
        name: "ViewMagnet",
        url: BASE_URL,
        logo: `${BASE_URL}/logo.png`,
        description:
          "Predict, create, and publish YouTube videos in one app. ML-driven analyzer, scriptwriter, studio editor, and distribution hub.",
        sameAs: [
          "https://twitter.com/viewmagnet",
          "https://www.linkedin.com/company/viewmagnet",
        ],
        contactPoint: {
          "@type": "ContactPoint",
          contactType: "customer support",
          email: "support@viewmagnet.io",
        },
      };
      break;

    case "website":
      schema = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        name: "ViewMagnet",
        url: BASE_URL,
        description:
          "AI-powered YouTube growth tools — predict video performance before publishing, then script, edit, and publish in one app.",
        potentialAction: {
          "@type": "SearchAction",
          target: {
            "@type": "EntryPoint",
            urlTemplate: `${BASE_URL}/dashboard/analyzer?url={search_term_string}`,
          },
          "query-input": "required name=search_term_string",
        },
      };
      break;

    case "article":
      schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        headline: props.headline,
        description: props.description,
        image: props.image || `${BASE_URL}/og-image.png`,
        datePublished: props.datePublished,
        dateModified: props.dateModified || props.datePublished,
        author: {
          "@type": "Organization",
          name: props.author || "ViewMagnet",
          url: BASE_URL,
        },
        publisher: {
          "@type": "Organization",
          name: "ViewMagnet",
          logo: {
            "@type": "ImageObject",
            url: `${BASE_URL}/logo.png`,
          },
        },
        mainEntityOfPage: {
          "@type": "WebPage",
          "@id": props.url ? `${BASE_URL}${props.url}` : BASE_URL,
        },
      };
      break;

    case "product":
      schema = {
        "@context": "https://schema.org",
        "@type": "Product",
        name: props.name,
        description: props.description,
        brand: {
          "@type": "Organization",
          name: "ViewMagnet",
        },
        offers: props.offers.map((offer) => ({
          "@type": "Offer",
          price: offer.price,
          priceCurrency: offer.priceCurrency,
          availability: `https://schema.org/${offer.availability || "InStock"}`,
        })),
      };
      break;

    case "softwareApplication":
      schema = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        name: props.name,
        description: props.description,
        applicationCategory: props.applicationCategory,
        operatingSystem: props.operatingSystem || "Web Browser",
        url: BASE_URL,
        publisher: {
          "@type": "Organization",
          name: "ViewMagnet",
        },
        ...(props.offers && {
          offers: props.offers.map((o) => ({
            "@type": "Offer",
            price: o.price,
            priceCurrency: o.priceCurrency,
          })),
        }),
        ...(props.aggregateRating && {
          aggregateRating: {
            "@type": "AggregateRating",
            ratingValue: props.aggregateRating.ratingValue,
            ratingCount: props.aggregateRating.ratingCount,
          },
        }),
      };
      break;

    case "faq":
      schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: props.questions.map((q) => ({
          "@type": "Question",
          name: q.question,
          acceptedAnswer: {
            "@type": "Answer",
            text: q.answer,
          },
        })),
      };
      break;

    case "howTo":
      schema = {
        "@context": "https://schema.org",
        "@type": "HowTo",
        name: props.name,
        description: props.description,
        ...(props.totalTime && { totalTime: props.totalTime }),
        step: props.steps.map((s, i) => ({
          "@type": "HowToStep",
          position: i + 1,
          name: s.name,
          text: s.text,
          ...(s.url && { url: `${BASE_URL}${s.url}` }),
        })),
      };
      break;

    case "breadcrumb":
      schema = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        itemListElement: props.items.map((item, i) => ({
          "@type": "ListItem",
          position: i + 1,
          name: item.name,
          item: item.url.startsWith("http")
            ? item.url
            : `${BASE_URL}${item.url}`,
        })),
      };
      break;

    case "itemList":
      schema = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        name: props.name,
        ...(props.description && { description: props.description }),
        itemListElement: props.items.map((item, i) => ({
          "@type": "ListItem",
          position: i + 1,
          name: item.name,
          ...(item.description && { description: item.description }),
          ...(item.url && {
            url: item.url.startsWith("http")
              ? item.url
              : `${BASE_URL}${item.url}`,
          }),
        })),
      };
      break;

    default:
      return null;
  }

  return (
    <Helmet>
      <script type="application/ld+json">{JSON.stringify(schema)}</script>
    </Helmet>
  );
}
