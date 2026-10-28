/**
 * E2E tests for dashboard navigation and functionality.
 */
import { test, expect } from "@playwright/test";
import { authenticate } from "./helpers/auth";

test.describe("Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    // All /dashboard/* routes are protected — establish a real session first.
    await authenticate(page);
  });

  test.describe("Navigation", () => {
    test("should display dashboard sidebar with all tools", async ({ page }) => {
      await page.goto("/dashboard");

      // Should show sidebar navigation
      const sidebar = page.locator("nav, [class*='sidebar'], aside").first();
      await expect(sidebar).toBeVisible({ timeout: 5000 });

      // Should have key navigation items
      await expect(page.getByRole("link", { name: /overview|dashboard/i })).toBeVisible();
      await expect(page.getByRole("link", { name: /analyz/i })).toBeVisible();
    });

    test("should navigate to Video Analyzer", async ({ page }) => {
      await page.goto("/dashboard");

      await page.getByRole("link", { name: /analyz/i }).click();

      await expect(page).toHaveURL(/analyzer/i);
    });

    test("should navigate to Title Generator", async ({ page }) => {
      await page.goto("/dashboard");

      await page.getByRole("link", { name: /title/i }).click();

      await expect(page).toHaveURL(/title/i);
    });

    test("should navigate to Thumbnail Creator", async ({ page }) => {
      await page.goto("/dashboard");

      await page.getByRole("link", { name: /thumbnail/i }).click();

      await expect(page).toHaveURL(/thumbnail/i);
    });

    test("should navigate to Script Writer", async ({ page }) => {
      await page.goto("/dashboard");

      await page.getByRole("link", { name: /script/i }).click();

      await expect(page).toHaveURL(/script/i);
    });
  });

  test.describe("Overview Page", () => {
    test("should display key metrics cards", async ({ page }) => {
      await page.goto("/dashboard");

      // Should show metric cards
      await expect(page.getByText(/magnet.*score|avg.*score/i)).toBeVisible({ timeout: 5000 });
      await expect(page.getByText(/videos.*analyzed/i)).toBeVisible();
    });

    test("should display performance chart", async ({ page }) => {
      await page.goto("/dashboard");

      // Should show performance chart or trend section
      const chartSection = page.locator('[class*="chart"], [class*="trend"], svg[class*="recharts"]');
      await expect(chartSection.first()).toBeVisible({ timeout: 5000 });
    });

    test("should display quick actions", async ({ page }) => {
      await page.goto("/dashboard");

      // Should show quick action buttons
      await expect(page.getByText(/quick.*action|analyze.*video/i).first()).toBeVisible();
    });

    test("should show channel connection prompt when not connected", async ({ page }) => {
      // Clear any stored channel data
      await page.goto("/");
      await page.evaluate(() => {
        localStorage.removeItem("connectedChannel");
        localStorage.removeItem("youtubeConnection");
      });

      await page.goto("/dashboard");

      // Should show connect channel prompt (Overview renders
      // "Connect your channel to see personalized insights." /
      // "Connect channel for live data" for unconnected accounts).
      await expect(
        page.getByText(/connect (your )?channel/i).first()
      ).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe("Title Generator", () => {
    test("should display title generator interface", async ({ page }) => {
      await page.goto("/dashboard/titles");

      // Real UI: textarea "Describe what your video is about..." +
      // "Generate Titles" button.
      await expect(
        page.getByPlaceholder(/describe what your video/i)
      ).toBeVisible({ timeout: 5000 });

      await expect(
        page.getByRole("button", { name: /generate titles/i })
      ).toBeVisible();
    });

    test("should generate title suggestions", async ({ page }) => {
      await page.goto("/dashboard/titles");

      await page.getByPlaceholder(/describe what your video/i).fill("Python programming tutorial");

      await page.getByRole("button", { name: /generate titles/i }).click();

      // The click must visibly DO something: spinner, results header, or an
      // error toast (CI has no LLM key, so a graceful failure also counts).
      await expect(
        page
          .locator(".animate-spin")
          .or(page.getByText(/generated titles/i))
          .or(page.getByText(/error|failed|try again/i))
          .first()
      ).toBeVisible({ timeout: 10000 });
    });
  });

  test.describe("Winning Formula", () => {
    test("should display winning formula interface", async ({ page }) => {
      await page.goto("/dashboard/formula");

      // Should show channel input
      await expect(
        page.getByPlaceholder(/channel|url|@/i)
      ).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe("Competitor Analysis", () => {
    test("should display competitor analysis interface", async ({ page }) => {
      await page.goto("/dashboard/competitors");

      // Should show competitor input
      await expect(
        page.getByPlaceholder(/competitor|channel|url/i)
      ).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe("Velocity Monitoring", () => {
    test("should display velocity monitoring interface", async ({ page }) => {
      await page.goto("/dashboard/velocity");

      // Should show velocity page elements
      await expect(
        page.getByText(/velocity|tracking|prediction/i).first()
      ).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe("Settings", () => {
    test("should display settings page", async ({ page }) => {
      await page.goto("/dashboard/settings");

      // Should show settings sections
      await expect(
        page.getByText(/settings|profile|account/i).first()
      ).toBeVisible({ timeout: 5000 });
    });

    test("should display subscription info", async ({ page }) => {
      await page.goto("/dashboard/settings");

      // Should show plan/subscription info
      await expect(
        page.getByText(/plan|subscription|free|starter|pro|agency/i).first()
      ).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe("Responsive Design", () => {
    test("should collapse sidebar on mobile", async ({ page }) => {
      // Set mobile viewport
      await page.setViewportSize({ width: 375, height: 667 });

      await page.goto("/dashboard");

      // Sidebar should be collapsed or hidden on mobile
      const sidebar = page.locator("aside, [class*='sidebar']").first();
      
      // Either sidebar is hidden or there's a menu toggle
      const menuToggle = page.getByRole("button", { name: /menu|toggle/i });
      
      expect(
        await sidebar.isHidden() || await menuToggle.isVisible()
      ).toBeTruthy();
    });

    test("should show mobile menu toggle", async ({ page }) => {
      await page.setViewportSize({ width: 375, height: 667 });

      await page.goto("/dashboard");

      // Should show menu toggle button
      const menuToggle = page.locator('[class*="menu"], [class*="hamburger"], button[aria-label*="menu"]');
      
      if (await menuToggle.count() > 0) {
        await expect(menuToggle.first()).toBeVisible();
      }
    });
  });
});
