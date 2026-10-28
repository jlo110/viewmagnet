import { ApiReferenceReact } from "@scalar/api-reference-react";
import "@scalar/api-reference-react/style.css";

import "./scalar-overrides.css";

type Props = {
  /** Fully-qualified URL to the OpenAPI 3.x document Scalar should render. */
  openApiUrl: string;
};

/**
 * Thin wrapper around Scalar's React renderer so the surrounding
 * page can stay free of Scalar-specific config + style imports.
 *
 * Why this exists as its own file (instead of inline in
 * ``Docs.tsx``):
 *
 * 1. Scalar pulls in a sizable Vue runtime + CSS bundle. Isolating
 *    the import keeps it in its own lazy chunk so the rest of the
 *    SPA never pays for it.
 * 2. The dark theme + brand colour tweaks live in
 *    ``scalar-overrides.css`` which has to be imported next to the
 *    Scalar component so Vite's CSS layering puts ours *after*
 *    Scalar's defaults.
 */
export default function ScalarReference({ openApiUrl }: Props) {
  return (
    <ApiReferenceReact
      configuration={{
        // Scalar fetches this on mount. Cross-origin in prod (CORS
        // is already configured on the API), same-origin in dev
        // through the Vite proxy.
        url: openApiUrl,

        // 'modern' = single-column layout with a left sidebar. The
        // alternative ('classic') is two-column with code samples on
        // the right; we use 'modern' because the request-builder pane
        // doubles as the code-sample column and it gives us more
        // horizontal real estate for the response schemas.
        layout: "modern",

        // Force dark mode regardless of the visitor's OS preference
        // — the brand is a dark site and a white docs panel reads as
        // "wrong product".
        darkMode: true,

        // Brand colour mapping. Scalar lets us override per-property
        // CSS variables here, but the heavy lifting is done by the
        // ``scalar-overrides.css`` sibling so designers can iterate
        // without rebuilding the bundle.
        theme: "default",

        // Hide the floating "powered by Scalar" pill — looks
        // unprofessional in production docs.
        hideClientButton: false,
        hideDownloadButton: false,
        hideSearch: false,
        showSidebar: true,

        // Default the request-builder's "Authorize" dropdown to the
        // PAT scheme so first-time visitors land on the right entry
        // (the API document defines both PAT and JWT). We do **not**
        // pre-fill a token value — leaking even a placeholder via
        // cached HTML would be a footgun.
        authentication: {
          preferredSecurityScheme: "PersonalAccessToken",
        },

        // Surface the meta-data we set in ``src/api/openapi.py``
        // (custom logo, external docs link). Scalar reads these
        // straight from the spec so no extra config is needed here.

        // Expand every tag group on first render. The default
        // (collapsed) hides every endpoint behind a click and makes
        // the page look "half-built" — first-time visitors scroll
        // past empty section headers thinking the sidebar lied.
        // 130+ endpoints is fine to render up-front: Scalar
        // virtualises the operation panes and the sidebar handles
        // the actual navigation.
        defaultOpenAllTags: true,
      }}
    />
  );
}
