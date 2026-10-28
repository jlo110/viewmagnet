/**
 * Product analytics via PostHog.
 *
 * Initialized lazily so that VITE_POSTHOG_KEY can be omitted in dev builds.
 * Keys are read from Vite env at startup; events fan out through `track`.
 *
 * Tracked events (rev these centrally to avoid drift):
 *   analyze_started, analyze_completed,
 *   script_generated, distribution_published,
 *   account_connected, signup, login, upgrade_clicked
 */
import posthog from "posthog-js";

const POSTHOG_KEY = import.meta.env.VITE_POSTHOG_KEY;
const POSTHOG_HOST = import.meta.env.VITE_POSTHOG_HOST || "https://us.i.posthog.com";

let initialized = false;

export function initAnalytics(): void {
  if (initialized || !POSTHOG_KEY) return;
  posthog.init(POSTHOG_KEY, {
    api_host: POSTHOG_HOST,
    person_profiles: "identified_only",
    capture_pageview: true,
    capture_pageleave: true,
    autocapture: false,
  });
  initialized = true;
}

export function identifyUser(userId: string | number, properties?: Record<string, unknown>): void {
  if (!initialized) return;
  posthog.identify(String(userId), properties);
}

export function resetAnalytics(): void {
  if (!initialized) return;
  posthog.reset();
}

export type AnalyticsEvent =
  | "analyze_started"
  | "analyze_completed"
  | "script_generated"
  | "distribution_published"
  | "account_connected"
  | "signup"
  | "login"
  | "logout"
  | "upgrade_clicked"
  | "page_view"
  | "referral_copied";

export function track(event: AnalyticsEvent, properties?: Record<string, unknown>): void {
  if (!initialized) {
    if (import.meta.env.DEV) {
      console.debug(`[analytics:noop] ${event}`, properties);
    }
    return;
  }
  posthog.capture(event, properties);
}
