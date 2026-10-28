/**
 * Tests for the Dashboard Overview component.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Mock the auth context
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: vi.fn(() => ({
    user: { id: 1, email: "test@example.com", name: "Test User", plan: "free" },
    isAuthenticated: true,
    isLoading: false,
  })),
}));

// Mock the API functions
vi.mock("@/lib/api", () => ({
  getDashboardStats: vi.fn(() => Promise.resolve({
    avg_prediction_score: 75.5,
    total_views_30d: 100000,
    videos_analyzed: 10,
    analyses_remaining: 490,
    above_baseline_pct: 60,
    recent_analyses: [],
    performance_trend: [],
  })),
  getChannelOverview: vi.fn(() => Promise.resolve(null)),
  startYouTubeAuth: vi.fn(),
  getYouTubeConnections: vi.fn(() => Promise.resolve({ connections: [] })),
  disconnectYouTube: vi.fn(),
  analyzeVideo: vi.fn(),
}));

// Mock wouter
vi.mock("wouter", () => ({
  useLocation: vi.fn(() => ["/dashboard", vi.fn()]),
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
  Router: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

// Mock recharts
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
import Overview from "../pages/dashboard/Overview";

describe("Overview Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("Rendering", () => {
    it("should render the overview component", async () => {
      render(<Overview />);

      // Should render some content
      await waitFor(() => {
        const hasContent =
          document.querySelector('[class*="card"]') !== null ||
          screen.queryAllByRole("button").length > 0 ||
          screen.queryAllByRole("link").length > 0;
        
        expect(hasContent).toBeTruthy();
      });
    });

    it("should show stats or loading state", async () => {
      render(<Overview />);

      // Should show either loading or stats
      await waitFor(() => {
        const hasState =
          document.querySelector('[class*="animate"]') !== null ||
          document.querySelector('[class*="spin"]') !== null ||
          screen.queryAllByText(/\d+/).length > 0;
        
        expect(hasState).toBeTruthy();
      }, { timeout: 3000 });
    });
  });

  describe("Quick Actions", () => {
    it("should render action buttons", async () => {
      render(<Overview />);

      await waitFor(() => {
        // Should have some buttons or links for actions
        const buttons = screen.queryAllByRole("button");
        const links = screen.queryAllByRole("link");
        expect(buttons.length + links.length).toBeGreaterThan(0);
      }, { timeout: 3000 });
    });
  });

  describe("Stats Display", () => {
    it("should display stat cards", async () => {
      render(<Overview />);

      await waitFor(() => {
        // Should show card elements
        const cards = document.querySelectorAll('[class*="card"]');
        expect(cards.length).toBeGreaterThan(0);
      }, { timeout: 3000 });
    });
  });
});
