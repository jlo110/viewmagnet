/**
 * Shared definition of the fallback demo clip used when the Studio is
 * opened standalone (no clip key in the route). Kept in its own module so
 * the URL-migration logic in {@link useEditSession} can stay in sync with
 * whatever {@link StudioPage} hands the editor as a seed.
 *
 * If you change DEMO_SOURCE, you almost certainly want to bump the entries
 * in URL_REWRITES (in useEditSession.ts) so existing sessions saved against
 * the previous demo get rewritten to this one — otherwise users land back
 * on a stale source URL with a transcript that no longer matches the audio.
 */
import type { SourceClip, TranscriptWord } from "./types";

export const DEMO_SOURCE_URL =
  "https://videos.pexels.com/video-files/3209298/3209298-hd_1920_1080_25fps.mp4";

export const DEMO_START = 0;
export const DEMO_END = 15;

/**
 * Transcript paced to actually span the full demo window. The earlier
 * version stopped around 6s, which made it look like the audio cut out
 * partway through playback in sessions migrated from the old bunny clip.
 */
export const DEMO_TRANSCRIPT: TranscriptWord[] = [
  { text: "Four", start: 0.2, end: 0.6 },
  { text: "subjects", start: 0.6, end: 1.3 },
  { text: "detected", start: 1.3, end: 2.1 },
  { text: "automatically.", start: 2.1, end: 3.2 },
  { text: "Press", start: 3.6, end: 4.0 },
  { text: "1,", start: 4.0, end: 4.3 },
  { text: "2,", start: 4.3, end: 4.6 },
  { text: "3,", start: 4.6, end: 4.9 },
  { text: "or", start: 4.9, end: 5.1 },
  { text: "4", start: 5.1, end: 5.4 },
  { text: "to", start: 5.4, end: 5.6 },
  { text: "cut", start: 5.6, end: 5.9 },
  { text: "to", start: 5.9, end: 6.1 },
  { text: "that", start: 6.1, end: 6.4 },
  { text: "person.", start: 6.4, end: 7.2 },
  { text: "Or", start: 7.6, end: 7.9 },
  { text: "hit", start: 7.9, end: 8.2 },
  { text: "Auto-switch", start: 8.2, end: 9.3 },
  { text: "and", start: 9.3, end: 9.5 },
  { text: "let", start: 9.5, end: 9.8 },
  { text: "the", start: 9.8, end: 10.0 },
  { text: "AI", start: 10.0, end: 10.4 },
  { text: "pick", start: 10.4, end: 10.8 },
  { text: "the", start: 10.8, end: 11.0 },
  { text: "cuts", start: 11.0, end: 11.6 },
  { text: "for", start: 11.6, end: 11.9 },
  { text: "you.", start: 11.9, end: 12.4 },
  { text: "Then", start: 12.8, end: 13.2 },
  { text: "hit", start: 13.2, end: 13.5 },
  { text: "Render.", start: 13.5, end: 14.6 },
];

export const DEMO_SOURCE: SourceClip = {
  source_url: DEMO_SOURCE_URL,
  source_clip_path: null,
  start_time: DEMO_START,
  end_time: DEMO_END,
  suggested_title: "Study Group — Multi-Subject Demo",
  transcript: DEMO_TRANSCRIPT,
};
