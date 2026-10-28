/**
 * Tests for hooks/usePlan.ts
 *
 * usePlan reads the current user's plan from AuthContext and returns
 * boolean flags for each tier.  We render a thin test component to
 * drive the hook.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: vi.fn(),
}));

import { useAuth } from "@/contexts/AuthContext";
import { usePlan } from "../hooks/usePlan";

function PlanDisplay() {
  const plan = usePlan();
  return (
    <div>
      <span data-testid="tier">{plan.tier}</span>
      <span data-testid="isFree">{String(plan.isFree)}</span>
      <span data-testid="isStarter">{String(plan.isStarter)}</span>
      <span data-testid="isPro">{String(plan.isPro)}</span>
      <span data-testid="isAgency">{String(plan.isAgency)}</span>
      <span data-testid="hasPaidPlan">{String(plan.hasPaidPlan)}</span>
    </div>
  );
}

function renderWithUser(plan: string | null | undefined) {
  (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({ user: { plan } });
  render(<PlanDisplay />);
}

describe("usePlan", () => {
  it("defaults to free when user has no plan", () => {
    renderWithUser(null);
    expect(screen.getByTestId("tier").textContent).toBe("free");
    expect(screen.getByTestId("isFree").textContent).toBe("true");
    expect(screen.getByTestId("hasPaidPlan").textContent).toBe("false");
  });

  it("defaults to free when user is undefined", () => {
    (useAuth as ReturnType<typeof vi.fn>).mockReturnValue({ user: undefined });
    render(<PlanDisplay />);
    expect(screen.getByTestId("tier").textContent).toBe("free");
  });

  it("starter plan", () => {
    renderWithUser("starter");
    expect(screen.getByTestId("tier").textContent).toBe("starter");
    expect(screen.getByTestId("isStarter").textContent).toBe("true");
    expect(screen.getByTestId("hasPaidPlan").textContent).toBe("true");
    expect(screen.getByTestId("isFree").textContent).toBe("false");
  });

  it("pro plan", () => {
    renderWithUser("pro");
    expect(screen.getByTestId("tier").textContent).toBe("pro");
    expect(screen.getByTestId("isPro").textContent).toBe("true");
    expect(screen.getByTestId("hasPaidPlan").textContent).toBe("true");
  });

  it("agency plan", () => {
    renderWithUser("agency");
    expect(screen.getByTestId("tier").textContent).toBe("agency");
    expect(screen.getByTestId("isAgency").textContent).toBe("true");
    expect(screen.getByTestId("hasPaidPlan").textContent).toBe("true");
  });

  it("enterprise normalises to agency", () => {
    renderWithUser("enterprise");
    expect(screen.getByTestId("tier").textContent).toBe("agency");
    expect(screen.getByTestId("isAgency").textContent).toBe("true");
  });

  it("unknown plan falls back to free", () => {
    renderWithUser("hobbyist");
    expect(screen.getByTestId("tier").textContent).toBe("free");
    expect(screen.getByTestId("isFree").textContent).toBe("true");
  });

  it("plan is case-insensitive", () => {
    renderWithUser("PRO");
    expect(screen.getByTestId("tier").textContent).toBe("pro");
  });

  it("only one flag is true at a time", () => {
    renderWithUser("pro");
    const isFree = screen.getByTestId("isFree").textContent === "true";
    const isStarter = screen.getByTestId("isStarter").textContent === "true";
    const isPro = screen.getByTestId("isPro").textContent === "true";
    const isAgency = screen.getByTestId("isAgency").textContent === "true";
    const trueCount = [isFree, isStarter, isPro, isAgency].filter(Boolean).length;
    expect(trueCount).toBe(1);
  });
});
