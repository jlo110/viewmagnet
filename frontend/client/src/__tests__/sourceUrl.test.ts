/**
 * Tests for studio/sourceUrl.ts helpers.
 *
 * Covers:
 *   - isYouTubeUrl() — must recognise all YouTube URL shapes and reject
 *     non-YouTube URLs, so Studio knows when to show the upload zone.
 *   - isPlaceholderSource() — unchanged behaviour guard.
 *   - proxyVideoUrl() — blob/data/file URIs pass through; http(s) gets
 *     routed through the source-proxy; YouTube URLs are routed too (the
 *     upload zone handles the fallback, not proxyVideoUrl).
 */
import { describe, it, expect } from "vitest";
import {
  isYouTubeUrl,
  isPlaceholderSource,
  proxyVideoUrl,
  PLACEHOLDER_SOURCE_SCHEME,
} from "../studio/sourceUrl";

// ---------------------------------------------------------------------------
// isYouTubeUrl
// ---------------------------------------------------------------------------

describe("isYouTubeUrl", () => {
  it.each([
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=abc",
    "http://youtube.com/watch?v=abc",
  ])("returns true for %s", (url) => {
    expect(isYouTubeUrl(url)).toBe(true);
  });

  it.each([
    "https://r2.example.com/clip.mp4",
    "https://pexels.com/video/foo.mp4",
    "https://vimeo.com/123456",
    "blob:https://app.example.com/abc",
    "/local/path/clip.mp4",
    "",
  ])("returns false for %s", (url) => {
    expect(isYouTubeUrl(url)).toBe(false);
  });

  it("returns false for null", () => {
    expect(isYouTubeUrl(null)).toBe(false);
  });

  it("returns false for undefined", () => {
    expect(isYouTubeUrl(undefined)).toBe(false);
  });

  it("is case-insensitive", () => {
    expect(isYouTubeUrl("https://WWW.YOUTUBE.COM/watch?v=abc")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// isPlaceholderSource
// ---------------------------------------------------------------------------

describe("isPlaceholderSource", () => {
  it("returns true for placeholder:// URIs", () => {
    expect(isPlaceholderSource(`${PLACEHOLDER_SOURCE_SCHEME}no-footage`)).toBe(true);
  });

  it("returns false for real URLs", () => {
    expect(isPlaceholderSource("https://cdn.example.com/clip.mp4")).toBe(false);
  });

  it("returns false for null/undefined", () => {
    expect(isPlaceholderSource(null)).toBe(false);
    expect(isPlaceholderSource(undefined)).toBe(false);
    expect(isPlaceholderSource("")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// proxyVideoUrl
// ---------------------------------------------------------------------------

describe("proxyVideoUrl", () => {
  it("returns empty string for null/undefined/empty", () => {
    expect(proxyVideoUrl(null)).toBe("");
    expect(proxyVideoUrl(undefined)).toBe("");
    expect(proxyVideoUrl("")).toBe("");
  });

  it("returns empty string for placeholder sources", () => {
    expect(proxyVideoUrl(`${PLACEHOLDER_SOURCE_SCHEME}no-footage`)).toBe("");
  });

  it("passes blob URIs through unchanged", () => {
    const url = "blob:https://app.example.com/abc-123";
    expect(proxyVideoUrl(url)).toBe(url);
  });

  it("passes data URIs through unchanged", () => {
    const url = "data:video/mp4;base64,AAAA";
    expect(proxyVideoUrl(url)).toBe(url);
  });

  it("passes local paths through unchanged", () => {
    const url = "/local/path/clip.mp4";
    expect(proxyVideoUrl(url)).toBe(url);
  });

  it("routes http(s) URLs through the source-proxy endpoint", () => {
    const url = "https://cdn.example.com/clip.mp4";
    const result = proxyVideoUrl(url);
    expect(result).toContain("source-proxy");
    expect(result).toContain(encodeURIComponent(url));
  });

  it("also routes YouTube URLs through source-proxy (upload zone handles fallback)", () => {
    const url = "https://www.youtube.com/watch?v=abc123";
    const result = proxyVideoUrl(url);
    expect(result).toContain("source-proxy");
  });
});
