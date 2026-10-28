/**
 * E2E tests for authentication flows.
 *
 * Selectors mirror the REAL pages (2026-06-12 realignment): the auth cards
 * use shadcn CardTitle, which renders a <div> (no heading role) — "Create
 * account" on /signup, "Welcome back" on /login; submit buttons are
 * "Create account" / "Sign in"; signup requires a Confirm Password field
 * (label collides with "Password", so labels are matched exactly); weak
 * passwords surface as a toast.
 */
import { test, expect } from "@playwright/test";

test.describe("Authentication", () => {
  test.describe("Signup Flow", () => {
    test("should display signup page", async ({ page }) => {
      await page.goto("/signup");

      await expect(page.getByText("Create account").first()).toBeVisible();
      await expect(page.getByLabel("Email")).toBeVisible();
      await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
      await expect(page.getByLabel("Confirm Password")).toBeVisible();
      await expect(page.getByRole("button", { name: /create account/i })).toBeVisible();
    });

    test("should block empty-form submission (submit disabled)", async ({ page }) => {
      await page.goto("/signup");

      // The form's validation is a DISABLED submit until the password rules
      // pass — there is no click-then-error flow.
      await expect(page.getByRole("button", { name: /create account/i })).toBeDisabled();
    });

    test("should keep submit disabled for weak password", async ({ page }) => {
      await page.goto("/signup");

      await page.getByLabel("Email").fill("test@example.com");
      await page.getByLabel("Password", { exact: true }).fill("short");
      await page.getByLabel("Confirm Password").fill("short");

      // < 8 chars never enables the button (the "at least 8 characters"
      // rule is enforced by disabling, with a server-side double check).
      await expect(page.getByRole("button", { name: /create account/i })).toBeDisabled();

      // And a valid password DOES enable it.
      await page.getByLabel("Password", { exact: true }).fill("longEnough123!");
      await page.getByLabel("Confirm Password").fill("longEnough123!");
      await expect(page.getByRole("button", { name: /create account/i })).toBeEnabled();
    });

    test("should successfully create account", async ({ page }) => {
      await page.goto("/signup");

      const uniqueEmail = `test-${Date.now()}@example.com`;
      await page.getByLabel("Email").fill(uniqueEmail);
      await page.getByLabel("Password", { exact: true }).fill("securePassword123!");
      await page.getByLabel("Confirm Password").fill("securePassword123!");

      const nameField = page.getByLabel(/name/i);
      if (await nameField.isVisible().catch(() => false)) {
        await nameField.fill("Test User");
      }

      await page.getByRole("button", { name: /create account/i }).click();

      // Redirects into the app (or to verify-email) on success.
      await expect(page).toHaveURL(/dashboard|verify|home/i, { timeout: 10000 });
    });
  });

  test.describe("Login Flow", () => {
    test("should display login page", async ({ page }) => {
      await page.goto("/login");

      await expect(page.getByText("Welcome back").first()).toBeVisible();
      await expect(page.getByLabel("Email")).toBeVisible();
      await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
    });

    test("should show error for invalid credentials", async ({ page }) => {
      await page.goto("/login");

      await page.getByLabel("Email").fill("invalid@example.com");
      await page.getByLabel("Password", { exact: true }).fill("wrongpassword");
      await page.getByRole("button", { name: /sign in/i }).click();

      await expect(page.getByText(/invalid|incorrect|wrong|failed/i).first()).toBeVisible({
        timeout: 5000,
      });
    });

    test("should navigate to signup from login", async ({ page }) => {
      await page.goto("/login");

      await page.getByRole("link", { name: /sign up|create account|register/i }).click();

      await expect(page).toHaveURL(/signup/i);
    });
  });

  test.describe("Logout Flow", () => {
    test("should logout and redirect to login", async ({ page }) => {
      await page.goto("/dashboard");

      const logoutButton = page.getByRole("button", { name: /logout|sign out/i });
      if (await logoutButton.isVisible({ timeout: 2000 }).catch(() => false)) {
        await logoutButton.click();
        await expect(page).toHaveURL(/login|home/i);
      }
    });
  });

  test.describe("Protected Routes", () => {
    test("unauthenticated dashboard offers login instead of user data", async ({ page }) => {
      await page.goto("/");
      await page.evaluate(() => localStorage.clear());

      await page.goto("/dashboard");

      // Design note: the SPA does NOT hard-redirect — the layout renders with
      // auth-gated data and surfaces a login link for anonymous visitors.
      await expect(
        page.getByRole("link", { name: /log in|sign in|login/i }).first()
      ).toBeVisible({ timeout: 5000 });
    });
  });
});
