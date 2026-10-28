/**
 * Tests for Impact.tsx - Before/After Impact Dashboard
 *
 * The page is honesty-gated: until a user has >= 5 analyzed videos AND
 * >= 30 days of history it renders an unlock card (with an explicitly
 * labeled sample preview), never fabricated metrics. Past the gate but
 * before the real summary endpoint returns data, it renders a transparent
 * "aggregating your real metrics" card. These tests assert THAT behavior —
 * the old tests asserted the removed fabricated-data dashboard.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the auth context
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: vi.fn(() => ({
    user: { id: 1, email: "test@example.com", name: "Test User" },
    isAuthenticated: true,
    isLoading: false,
  })),
}));

// Mock the API layer. Default = brand-new user (no analyses) -> locked state.
// Individual tests override getAnalysisHistory to cross the unlock gate.
const getAnalysisHistoryMock = vi.fn();
const getImpactSummaryMock = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAnalysisHistory: (...args: unknown[]) => getAnalysisHistoryMock(...args),
    getImpactSummary: (...args: unknown[]) => getImpactSummaryMock(...args),
  };
});

// Mock recharts to avoid canvas issues
vi.mock("recharts", () => ({
  LineChart: ({ children }: { children: React.ReactNode }) => <div data-testid="line-chart">{children}</div>,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CartesianGrid: () => null,
  AreaChart: ({ children }: { children: React.ReactNode }) => <div data-testid="area-chart">{children}</div>,
  Area: () => null,
  BarChart: ({ children }: { children: React.ReactNode }) => <div data-testid="bar-chart">{children}</div>,
  Bar: () => null,
  Legend: () => null,
}));

// Import after mocks
import Impact from "../pages/dashboard/Impact";

const DAY_MS = 24 * 60 * 60 * 1000;

/** N analyses whose first one is `daysAgo` days old. */
function analyses(n: number, daysAgo: number) {
  return {
    analyses: Array.from({ length: n }, (_, i) => ({
      id: i + 1,
      video_id: `vid${i}`,
      title: `Video ${i}`,
      analyzed_at: new Date(Date.now() - daysAgo * DAY_MS + i * 60_000).toISOString(),
    })),
  };
}

describe("Impact Dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: new user, nothing analyzed -> locked.
    getAnalysisHistoryMock.mockResolvedValue({ analyses: [] });
    getImpactSummaryMock.mockResolvedValue({ metrics: [] });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("Initial render", () => {
    it("renders the impact dashboard", async () => {
      render(<Impact />);

      await waitFor(() => {
        const hasContent =
          screen.queryAllByText(/impact/i).length > 0 ||
          document.querySelector('[class*="card"]') !== null;
        expect(hasContent).toBeTruthy();
      });
    });

    it("shows loading or content", () => {
      render(<Impact />);

      const hasLoadingOrContent =
        document.querySelector('[class*="animate"]') !== null ||
        document.querySelector('[class*="spin"]') !== null ||
        screen.queryByText(/loading/i) !== null ||
        document.querySelector('[class*="card"]') !== null;
      expect(hasLoadingOrContent).toBeTruthy();
    });
  });

  describe("Unlock gate (honest empty state)", () => {
    it("explains both unlock thresholds instead of showing fake metrics", async () => {
      render(<Impact />);

      await waitFor(() => {
        expect(screen.getByText(/unlocks at/i)).toBeTruthy();
      });
      expect(screen.getByText(/5 videos analyzed/i)).toBeTruthy();
      expect(screen.getByText(/30 days of history/i)).toBeTruthy();
    });

    it("offers an 'Analyze a video' path toward the threshold", async () => {
      render(<Impact />);

      await waitFor(() => {
        expect(screen.getByText(/analyze a video/i)).toBeTruthy();
      });
    });

    it("explains the honest-attribution reasoning", async () => {
      render(<Impact />);

      await waitFor(() => {
        expect(
          screen.queryByText(/attribute lift honestly/i) ||
            screen.queryByText(/how SaaS dashboards lie/i)
        ).toBeTruthy();
      });
    });

    it("never renders metrics from fabricated data while locked", async () => {
      render(<Impact />);

      await waitFor(() => {
        expect(screen.getByText(/unlocks at/i)).toBeTruthy();
      });
      // No chart should render until the user opts into the labeled sample.
      expect(screen.queryByTestId("line-chart")).toBeNull();
      expect(screen.queryByTestId("area-chart")).toBeNull();
    });
  });

  describe("Sample preview (explicitly labeled)", () => {
    it("reveals a clearly-labeled sample dashboard on demand", async () => {
      const user = userEvent.setup();
      render(<Impact />);

      await waitFor(() => {
        expect(screen.getByText(/sample dashboard/i)).toBeTruthy();
      });
      await user.click(screen.getByText(/preview.*sample dashboard/i));

      await waitFor(() => {
        // The preview must carry the "Sample data" label so it can't be
        // mistaken for the user's own numbers.
        expect(screen.getAllByText(/sample data/i).length).toBeGreaterThan(0);
      });
    });

    it("renders charts only inside the opted-in sample preview", async () => {
      const user = userEvent.setup();
      render(<Impact />);

      await waitFor(() => {
        expect(screen.getByText(/sample dashboard/i)).toBeTruthy();
      });
      await user.click(screen.getByText(/preview.*sample dashboard/i));

      await waitFor(() => {
        const hasChart =
          screen.queryAllByTestId("line-chart").length > 0 ||
          screen.queryAllByTestId("area-chart").length > 0 ||
          document.querySelector('[data-testid*="chart"]') !== null;
        expect(hasChart).toBeTruthy();
      });
    });
  });

  describe("Unlocked, real metrics pending", () => {
    it("shows the transparent 'aggregating your real metrics' state", async () => {
      // 6 analyses, the first 45 days ago -> both thresholds met.
      getAnalysisHistoryMock.mockResolvedValue(analyses(6, 45));
      render(<Impact />);

      await waitFor(() => {
        expect(
          screen.queryByText(/aggregating your real metrics/i) ||
            screen.queryByText(/past the unlock threshold/i)
        ).toBeTruthy();
      });
      // Still no fabricated chart.
      expect(screen.queryByTestId("line-chart")).toBeNull();
    });

    it("stays locked when only the video threshold is met", async () => {
      // 6 analyses but only 2 days of history -> still locked.
      getAnalysisHistoryMock.mockResolvedValue(analyses(6, 2));
      render(<Impact />);

      await waitFor(() => {
        expect(screen.getByText(/unlocks at/i)).toBeTruthy();
      });
    });
  });

  describe("Responsive design", () => {
    it("renders cards in a grid layout", async () => {
      render(<Impact />);

      await waitFor(() => {
        expect(
          document.querySelector('[class*="card"]') ||
            document.querySelector('[class*="grid"]')
        ).toBeTruthy();
      });
    });
  });
});
