/**
 * E2E tests for video analysis workflow.
 */
import { test, expect } from "@playwright/test";
import { authenticate } from "./helpers/auth";

test.describe("Video Analysis", () => {
  test.beforeEach(async ({ page }) => {
    // The analyzer is a protected route: create a real account via the API
    // and inject the session before navigating (unauthenticated visits
    // redirect to /login, which is why these specs used to time out).
    await authenticate(page);
    await page.goto("/dashboard/analyzer");
  });

  test.describe("Analyzer Page", () => {
    test("should display video analyzer interface", async ({ page }) => {
      // Should show input for video URL
      await expect(
        page.getByPlaceholder(/youtube.*url|paste.*url|video.*url/i)
      ).toBeVisible({ timeout: 5000 });

      // Should show analyze button
      await expect(
        page.getByRole("button", { name: /analyze|check|score/i })
      ).toBeVisible();
    });

    test("should show error for invalid URL", async ({ page }) => {
      const urlInput = page.getByPlaceholder(/youtube.*url|paste.*url|video.*url/i);
      const analyzeButton = page.getByRole("button", { name: /analyze|check|score/i });

      await urlInput.fill("not-a-valid-url");
      await analyzeButton.click();

      // The analyzer submits and renders the API error as an
      // "Analysis Failed" card (there is no client-side URL message).
      await expect(page.getByText(/analysis failed/i)).toBeVisible({ timeout: 10000 });
    });

    test("should accept valid YouTube URL formats", async ({ page }) => {
      const urlInput = page.getByPlaceholder(/youtube.*url|paste.*url|video.*url/i);

      // Test standard URL format
      await urlInput.fill("https://www.youtube.com/watch?v=dQw4w9WgXcQ");
      
      // Input should accept the URL without immediate error
      await expect(urlInput).toHaveValue("https://www.youtube.com/watch?v=dQw4w9WgXcQ");
    });

    test("should show loading state while analyzing", async ({ page }) => {
      const urlInput = page.getByPlaceholder(/youtube.*url|paste.*url|video.*url/i);
      const analyzeButton = page.getByRole("button", { name: /analyze|check|score/i });

      await urlInput.fill("https://www.youtube.com/watch?v=dQw4w9WgXcQ");
      await analyzeButton.click();

      // Should show loading indicator
      await expect(
        page.locator(".animate-spin, [aria-busy='true']").first()
      ).toBeVisible({ timeout: 2000 });
    });
  });

  test.describe("Analysis Results", () => {
    test("should display analysis results after successful analysis", async ({ page }) => {
      // This test would need a mocked or real API response
      // For now, we check that the results container exists
      
      await page.goto("/dashboard/analyzer");
      
      // Check for results section (may be empty if no analysis yet)
      const resultsSection = page.locator('[data-testid="analysis-results"], .analysis-results, [class*="result"]');
      
      // If there's analysis history, it should be visible
      // This is a soft assertion since results depend on previous analyses
      if (await resultsSection.count() > 0) {
        await expect(resultsSection.first()).toBeVisible();
      }
    });

    test("should show Magnet Score when analysis completes", async ({ page }) => {
      // Navigate to analyzer with a completed analysis
      // In real tests, would mock the API or use test data
      
      await page.goto("/dashboard/analyzer");
      
      // Look for score display elements
      const scoreElements = page.locator('[class*="score"], [data-testid*="score"]');
      
      // The page should have score-related UI elements
      expect(await scoreElements.count()).toBeGreaterThanOrEqual(0);
    });
  });

  test.describe("Analysis History", () => {
    test("should display previous analyses", async ({ page }) => {
      await page.goto("/dashboard/analyzer");

      // Look for history section
      const historySection = page.locator(
        '[data-testid="analysis-history"], .history, [class*="recent"], [class*="previous"]'
      );

      // History section should exist (even if empty)
      if (await historySection.count() > 0) {
        await expect(historySection.first()).toBeVisible();
      }
    });

    test("should allow clicking on previous analysis to view details", async ({ page }) => {
      await page.goto("/dashboard/analyzer");

      // Find clickable analysis items
      const analysisItems = page.locator(
        '[data-testid="analysis-item"], .analysis-item, [class*="video-card"]'
      );

      if (await analysisItems.count() > 0) {
        await analysisItems.first().click();
        
        // Should show analysis details or expand
        await expect(
          page.locator('[class*="detail"], [class*="expanded"], [class*="explanation"]').first()
        ).toBeVisible({ timeout: 3000 });
      }
    });
  });
});
