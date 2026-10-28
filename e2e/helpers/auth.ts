/**
 * E2E auth helper: create a real account via the API and inject the session
 * into localStorage BEFORE the app boots, so protected dashboard routes render
 * instead of redirecting to /login (the root cause of most of the original
 * spec failures — they navigated to /dashboard/* unauthenticated).
 */
import type { Page } from "@playwright/test";

const API_BASE = process.env.E2E_API_BASE ?? "http://localhost:8000";

// Must mirror frontend/client/src/lib/api.ts
const TOKEN_KEY = "ViewMagnet_access_token";
const REFRESH_KEY = "ViewMagnet_refresh_token";
const USER_KEY = "ViewMagnet_user";

// One session per worker process: signup is rate-limited (5/min), so a
// per-test signup 429s the whole suite. All tests in a worker share it.
let cached: { access: string; refresh: string; user: string } | null = null;

export async function authenticate(page: Page): Promise<void> {
  if (!cached) {
    const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
    // Signup is rate-limited (5/min). Workers race for the budget (and CI
    // retries spawn fresh workers), so back off and retry on 429.
    let resp = await page.request.post(`${API_BASE}/auth/signup`, {
      data: { email, password: "e2ePassword123!", name: "E2E User" },
    });
    for (let attempt = 0; resp.status() === 429 && attempt < 4; attempt++) {
      await new Promise((r) => setTimeout(r, 15000 * (attempt + 1)));
      resp = await page.request.post(`${API_BASE}/auth/signup`, {
        data: { email, password: "e2ePassword123!", name: "E2E User" },
      });
    }
    if (!resp.ok()) {
      throw new Error(`e2e signup failed: ${resp.status()} ${await resp.text()}`);
    }
    const body = await resp.json();
    cached = {
      access: body.access_token,
      refresh: body.refresh_token,
      user: JSON.stringify(body.user),
    };
  }
  const body = { access_token: cached.access, refresh_token: cached.refresh, user: JSON.parse(cached.user) };
  await page.addInitScript(
    ([t, r, u, tk, rk, uk]) => {
      localStorage.setItem(tk, t);
      localStorage.setItem(rk, r);
      localStorage.setItem(uk, u);
    },
    [
      body.access_token,
      body.refresh_token,
      JSON.stringify(body.user),
      TOKEN_KEY,
      REFRESH_KEY,
      USER_KEY,
    ],
  );
}
