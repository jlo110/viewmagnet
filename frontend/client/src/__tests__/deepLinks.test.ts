/**
 * Tests for ``mapRecommendationToCta`` — Week 9 Connected Tools.
 *
 * The Analyzer "Recommendations" panel renders a long-tail list of
 * SHAP / feature-driven recommendations from
 * ``src/api/analyze.py::_generate_recommendations``. Most of these
 * are free text, so the only thing keeping them from rendering as a
 * wall of dead bullets is the regex matcher in
 * ``frontend/client/src/lib/deepLinks.ts``.
 *
 * These tests pin the matcher to the actual phrasings the backend
 * produces today so we don't silently regress to "dead text" for
 * common recs when someone tweaks the regex.
 */
import { describe, it, expect } from "vitest";

import {
  approximateTranscriptTimings,
  buildDistributionLink,
  mapRecommendationToCta,
  readDistributionDeepLink,
} from "@/lib/deepLinks";

interface ExpectedRoute {
  text: string;
  href: string | RegExp;
  hasAction?: boolean; // default true
}

// Production phrasings drawn straight from
// ``src/api/analyze.py::_generate_recommendations``. If one of these
// regresses to "no CTA" that's a real user-visible UX bug.
const CASES: ExpectedRoute[] = [
  // ---- Frameworks → Script Writer -----------------------------
  // Current production copy uses the "Lead Magnet" display name.
  // The legacy "HYPE/HEIT" wording is also kept as a parallel case
  // because older analysis blobs persisted under the original
  // terminology still ship that exact string and need to route.
  { text: "Try the Lead Magnet framework", href: /\/dashboard\/scripts\?tab=frameworks&framework=hype_heit/ },
  { text: "Try the HYPE/HEIT framework", href: /\/dashboard\/scripts\?tab=frameworks&framework=hype_heit/ },
  { text: "Try Authority Myth-Buster", href: /framework=authority_myth_buster/ },
  { text: "Run a Delta Shift script (built for save rate)", href: /framework=delta_shift/ },
  { text: "Try Progressive Debunking", href: /framework=progressive_debunking/ },

  // ---- Hook Lab (Title Generator hooks tab) -------------------
  { text: "Engineer a stronger hook in Hook Lab", href: "/dashboard/titles?tab=hooks" },
  { text: "Rewrite title with a stronger hook—your thumbnail is fine", href: "/dashboard/titles?tab=hooks" },
  { text: "Try: curiosity gap, specific numbers, or emotional words", href: "/dashboard/titles" },
  { text: "Example hooks: 'I Finally...', 'The Truth About...', 'X Things You Need...'", href: "/dashboard/titles?tab=hooks" },

  // ---- Title Generator (titles tab) ---------------------------
  { text: "Shorten to 50-60 characters for mobile", href: "/dashboard/titles" },
  { text: "Expand with more context (40-60 chars)", href: "/dashboard/titles" },
  { text: "Add power words (amazing, shocking, ultimate)", href: "/dashboard/titles" },
  { text: "Add a number or question to create curiosity", href: "/dashboard/titles" },
  { text: "Try tweaking title hook while keeping core topic", href: "/dashboard/titles?tab=hooks" },

  // ---- A/B Tester --------------------------------------------
  { text: "A/B test 3-5 packaging variations", href: "/dashboard/ab-test" },
  { text: "Consider A/B testing a new hook while views are building", href: "/dashboard/ab-test" },
  { text: "Next time: test title hooks before publishing", href: "/dashboard/ab-test" },

  // ---- Thumbnails --------------------------------------------
  { text: "Update thumbnail—your title is fine", href: "/dashboard/thumbnails" },
  { text: "Add a face with expression to thumbnail", href: "/dashboard/thumbnails" },
  { text: "Reaction faces in thumbnails boost CTR significantly", href: "/dashboard/thumbnails" },
  { text: "Increase brightness—dark thumbnails get skipped", href: "/dashboard/thumbnails" },
  { text: "Boost color saturation to stand out in feeds", href: "/dashboard/thumbnails" },
  { text: "Add contrast—make elements pop", href: "/dashboard/thumbnails" },
  { text: "Try a brighter/more expressive thumbnail version", href: "/dashboard/thumbnails" },

  // ---- Velocity / pacing -------------------------------------
  { text: "Cut dead air with the Pacing Analyzer", href: "/dashboard/velocity" },
  { text: "Pick up the speaking pace slightly", href: "/dashboard/velocity" },
  { text: "Slow down your delivery for clarity", href: "/dashboard/velocity" },

  // ---- Loop Designer -----------------------------------------
  { text: "Close the loop with Loop Designer", href: "/dashboard/loop-designer" },
  { text: "Design a loop ending", href: "/dashboard/loop-designer" },

  // ---- Shorts Creator ----------------------------------------
  { text: "Create a Short teaser to drive more traffic", href: "/dashboard/shorts" },
  { text: "Create a YouTube Short linking to this video", href: "/dashboard/shorts" },

  // ---- Distribution Hub --------------------------------------
  { text: "Share to Instagram/Twitter/TikTok with a hook clip", href: "/dashboard/distribution" },
  { text: "Share to social media to boost visibility", href: "/dashboard/distribution" },
  { text: "Promote this video now while momentum is high", href: "/dashboard/distribution" },
  { text: "✅ Title & thumbnail are solid—boost with promotion", href: "/dashboard/distribution" },

  // ---- AI Writer ---------------------------------------------
  { text: "Optimize description for SEO with chapter timestamps", href: "/dashboard/writer" },
  { text: "Add hashtags to the description", href: "/dashboard/writer" },

  // ---- Studio ------------------------------------------------
  { text: "Add more cuts in the first 10 seconds to boost engagement", href: "/dashboard/studio" },
  { text: "Show your face earlier in the video (under 2 seconds)", href: "/dashboard/studio" },
  { text: "Consider adding a music intro for polish", href: "/dashboard/studio" },
];

describe("mapRecommendationToCta", () => {
  for (const c of CASES) {
    it(`maps "${c.text}" to ${c.href}`, () => {
      const cta = mapRecommendationToCta(c.text);
      expect(cta.href, `no href for: ${c.text}`).toBeTruthy();
      if (c.href instanceof RegExp) {
        expect(cta.href!).toMatch(c.href);
      } else {
        expect(cta.href).toBe(c.href);
      }
      if (c.hasAction !== false) {
        expect(cta.actionLabel, `no actionLabel for: ${c.text}`).toBeTruthy();
      }
    });
  }

  it("falls back to plain text for unknown recs", () => {
    const cta = mapRecommendationToCta(
      "Wait at least 3-7 days before re-analyzing.",
    );
    expect(cta.href).toBeUndefined();
    expect(cta.actionLabel).toBeUndefined();
    expect(cta.label).toMatch(/wait at least/i);
  });

  it("passes the video title through to framework links as topic", () => {
    const cta = mapRecommendationToCta("Try Lead Magnet", {
      title: "How I Built a $1M Business",
    });
    expect(cta.href).toMatch(/topic=/);
    expect(cta.href).toMatch(/hype_heit/);
  });

  it("still routes legacy HYPE/HEIT phrasing to the Lead Magnet framework", () => {
    // Persisted analyses from before the rename still ship the
    // legacy string; the regression here protects against the
    // matcher accidentally dropping the parallel branch.
    const cta = mapRecommendationToCta("Try HYPE/HEIT");
    expect(cta.href).toMatch(/framework=hype_heit/);
    expect(cta.actionLabel).toBe("Try Lead Magnet");
  });
});

describe("approximateTranscriptTimings", () => {
  it("distributes words evenly across the duration window", () => {
    const words = approximateTranscriptTimings(
      "hello world this is a test",
      10,
      16,
    );
    expect(words).toHaveLength(6);
    // 6 words across 6 seconds → 1s each.
    expect(words[0]).toEqual({ start: 10, end: 11, text: "hello" });
    expect(words[5]).toEqual({ start: 15, end: 16, text: "test" });
  });

  it("returns [] for empty input", () => {
    expect(approximateTranscriptTimings("", 0, 10)).toEqual([]);
    expect(approximateTranscriptTimings("   ", 0, 10)).toEqual([]);
    expect(approximateTranscriptTimings(undefined, 0, 10)).toEqual([]);
    expect(approximateTranscriptTimings(null, 0, 10)).toEqual([]);
  });

  it("returns [] when the duration is zero or negative", () => {
    expect(approximateTranscriptTimings("hello world", 5, 5)).toEqual([]);
    expect(approximateTranscriptTimings("hello world", 10, 5)).toEqual([]);
  });

  it("preserves punctuation glued to words", () => {
    const words = approximateTranscriptTimings("Wait, what?", 0, 2);
    expect(words.map((w) => w.text)).toEqual(["Wait,", "what?"]);
  });

  it("handles a single word across the full window", () => {
    const words = approximateTranscriptTimings("Wait", 5, 6);
    expect(words).toEqual([{ start: 5, end: 6, text: "Wait" }]);
  });

  it("approximate word boundaries always span the full window", () => {
    const words = approximateTranscriptTimings(
      "one two three four five",
      0,
      10,
    );
    expect(words[0].start).toBe(0);
    expect(words[words.length - 1].end).toBeCloseTo(10, 5);
  });
});

// ----------------------------------------------------------------------
// Studio → Distribution handoff (Week 9 Connected Tools).
//
// ``buildDistributionLink`` / ``readDistributionDeepLink`` are the
// contract for pre-filling the publish form. If they regress, the
// "Publish" button on Drafts, Renders, and StudioProject all drop
// useful context silently.
// ----------------------------------------------------------------------

describe("build / readDistributionDeepLink", () => {
  it("round-trips renderUrl, title, clipKey", () => {
    const href = buildDistributionLink({
      renderUrl: "https://example.com/out.mp4",
      title: "My Render",
      clipKey: "abc123",
    });
    const parsed = readDistributionDeepLink(
      new URLSearchParams(href.split("?")[1] ?? ""),
    );
    expect(parsed.renderUrl).toBe("https://example.com/out.mp4");
    expect(parsed.title).toBe("My Render");
    expect(parsed.clipKey).toBe("abc123");
  });

  it("round-trips description, thumbnailUrl, projectId", () => {
    const href = buildDistributionLink({
      renderUrl: "https://example.com/out.mp4",
      title: "Long form",
      description: "A multi-clip project description.",
      thumbnailUrl: "https://example.com/thumb.jpg",
      projectId: 42,
    });
    const parsed = readDistributionDeepLink(
      new URLSearchParams(href.split("?")[1] ?? ""),
    );
    expect(parsed.description).toBe("A multi-clip project description.");
    expect(parsed.thumbnailUrl).toBe("https://example.com/thumb.jpg");
    expect(parsed.projectId).toBe(42);
  });

  it("omits undefined / empty fields from the query string", () => {
    const href = buildDistributionLink({
      renderUrl: "https://example.com/out.mp4",
    });
    expect(href).not.toMatch(/title=/);
    expect(href).not.toMatch(/description=/);
    expect(href).not.toMatch(/thumbnailUrl=/);
    expect(href).not.toMatch(/projectId=/);
  });

  it("ignores garbage projectId values", () => {
    const parsed = readDistributionDeepLink(
      new URLSearchParams("projectId=not-a-number"),
    );
    expect(parsed.projectId).toBeUndefined();
  });
});
