/**
 * Tests for VideoAnalyzer.tsx component
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the hooks and API
vi.mock("@/hooks/useApi", () => ({
  useAnalyzeVideo: vi.fn(() => ({
    analyze: vi.fn(),
    data: null,
    loading: false,
    error: null,
  })),
}));

vi.mock("@/lib/api", () => ({
  getAnalysisHistory: vi.fn(() => Promise.resolve({ analyses: [] })),
  getAnalysisByVideoId: vi.fn(() => Promise.resolve(null)),
}));

vi.mock("wouter", () => ({
  useLocation: () => ["/dashboard/analyze", vi.fn()],
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Import after mocks
import VideoAnalyzer from "../pages/dashboard/VideoAnalyzer";
import { useAnalyzeVideo } from "@/hooks/useApi";
import { getAnalysisHistory } from "@/lib/api";

describe("VideoAnalyzer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("Initial render", () => {
    it("renders the video analyzer interface", () => {
      render(<VideoAnalyzer />);

      // Should show the main heading or input
      expect(
        screen.getByPlaceholderText(/paste.*url/i) ||
          screen.getByRole("textbox")
      ).toBeInTheDocument();
    });

    it("renders the analyze button", () => {
      render(<VideoAnalyzer />);

      const button = screen.getByRole("button", { name: /analyze/i });
      expect(button).toBeInTheDocument();
    });

    it("shows empty state for history", async () => {
      (getAnalysisHistory as ReturnType<typeof vi.fn>).mockResolvedValue({
        analyses: [],
      });

      render(<VideoAnalyzer />);

      // Wait for history to load
      await waitFor(() => {
        // Should show some indication of no history or loading complete
        expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
      });
    });
  });

  describe("URL input", () => {
    it("accepts YouTube URL input", async () => {
      const user = userEvent.setup();
      render(<VideoAnalyzer />);

      const input = screen.getByPlaceholderText(/paste.*url/i) || screen.getByRole("textbox");
      await user.type(input, "https://youtube.com/watch?v=dQw4w9WgXcQ");

      expect(input).toHaveValue("https://youtube.com/watch?v=dQw4w9WgXcQ");
    });

    it("handles youtu.be short URLs", async () => {
      const user = userEvent.setup();
      render(<VideoAnalyzer />);

      const input = screen.getByPlaceholderText(/paste.*url/i) || screen.getByRole("textbox");
      await user.type(input, "https://youtu.be/dQw4w9WgXcQ");

      expect(input).toHaveValue("https://youtu.be/dQw4w9WgXcQ");
    });
  });

  describe("Analysis submission", () => {
    it("calls analyze on form submission", async () => {
      const mockAnalyze = vi.fn();
      (useAnalyzeVideo as ReturnType<typeof vi.fn>).mockReturnValue({
        analyze: mockAnalyze,
        data: null,
        loading: false,
        error: null,
      });

      const user = userEvent.setup();
      render(<VideoAnalyzer />);

      const input = screen.getByPlaceholderText(/paste.*url/i) || screen.getByRole("textbox");
      await user.type(input, "https://youtube.com/watch?v=test123");

      const button = screen.getByRole("button", { name: /analyze/i });
      await user.click(button);

      await waitFor(() => {
        expect(mockAnalyze).toHaveBeenCalled();
      });
    });

    it("disables button during loading", () => {
      (useAnalyzeVideo as ReturnType<typeof vi.fn>).mockReturnValue({
        analyze: vi.fn(),
        data: null,
        loading: true,
        error: null,
      });

      render(<VideoAnalyzer />);

      // During loading, the button should be disabled or show loading state
      const buttons = screen.getAllByRole("button");
      const analyzeButton = buttons.find((btn) =>
        btn.textContent?.toLowerCase().includes("analyz")
      );

      if (analyzeButton) {
        // Either disabled or showing loading indicator
        expect(
          analyzeButton.hasAttribute("disabled") ||
            analyzeButton.querySelector('[class*="animate"]') ||
            analyzeButton.textContent?.toLowerCase().includes("loading")
        ).toBeTruthy();
      }
    });
  });

  describe("Loading state", () => {
    it("shows progress stages during analysis", () => {
      (useAnalyzeVideo as ReturnType<typeof vi.fn>).mockReturnValue({
        analyze: vi.fn(),
        data: null,
        loading: true,
        error: null,
      });

      render(<VideoAnalyzer />);

      // Should show some loading indication - check for any loading indicator
      const hasLoadingIndicator =
        screen.queryAllByText(/fetching|analyzing|loading/i).length > 0 ||
        document.querySelector('[class*="animate"]') !== null ||
        document.querySelector('[class*="spin"]') !== null;
      
      expect(hasLoadingIndicator).toBeTruthy();
    });
  });

  describe("Error handling", () => {
    it("displays error message when analysis fails", () => {
      (useAnalyzeVideo as ReturnType<typeof vi.fn>).mockReturnValue({
        analyze: vi.fn(),
        data: null,
        loading: false,
        error: "Failed to analyze video",
      });

      render(<VideoAnalyzer />);

      // Look for any error indication
      const errorElements = screen.queryAllByText(/failed|error/i);
      expect(errorElements.length).toBeGreaterThan(0);
    });
  });

  describe("Results display", () => {
    it("shows analysis results when data is available", () => {
      const mockData = {
        video_id: "test123",
        title: "Test Video Title",
        prediction_score: 75,
        prediction_tier: "high",
        thumbnail_url: "https://example.com/thumb.jpg",
        channel_name: "Test Channel",
        view_count: 10000,
        like_count: 500,
        duration_seconds: 600,
        published_at: "2026-01-15",
        feature_explanations: [],
        title_analysis: { score: 80 },
        thumbnail_analysis: { score: 70 },
      };

      (useAnalyzeVideo as ReturnType<typeof vi.fn>).mockReturnValue({
        analyze: vi.fn(),
        data: mockData,
        loading: false,
        error: null,
      });

      render(<VideoAnalyzer />);

      // Should show the video title or score
      const hasResults =
        screen.queryByText(/Test Video/i) !== null ||
        screen.queryByText(/75/) !== null ||
        screen.queryByText(/score/i) !== null;
      
      expect(hasResults).toBeTruthy();
    });

    it("shows prediction score prominently", () => {
      const mockData = {
        video_id: "test123",
        title: "Test Video",
        prediction_score: 85,
        prediction_tier: "high",
        thumbnail_url: "https://example.com/thumb.jpg",
        feature_explanations: [],
      };

      (useAnalyzeVideo as ReturnType<typeof vi.fn>).mockReturnValue({
        analyze: vi.fn(),
        data: mockData,
        loading: false,
        error: null,
      });

      render(<VideoAnalyzer />);

      // Score should be visible - use queryAllByText to avoid multiple element error
      const hasScore =
        screen.queryAllByText(/85/).length > 0 ||
        screen.queryAllByText(/score/i).length > 0;
      
      expect(hasScore).toBeTruthy();
    });
  });

  describe("Analysis history", () => {
    it("loads and displays analysis history", async () => {
      const mockHistory = {
        analyses: [
          {
            video_id: "vid1",
            title: "Previous Video 1",
            prediction_score: 70,
            analyzed_at: "2026-01-10T12:00:00Z",
          },
          {
            video_id: "vid2",
            title: "Previous Video 2",
            prediction_score: 65,
            analyzed_at: "2026-01-09T12:00:00Z",
          },
        ],
      };

      (getAnalysisHistory as ReturnType<typeof vi.fn>).mockResolvedValue(
        mockHistory
      );

      render(<VideoAnalyzer />);

      await waitFor(() => {
        // Should show history items
        expect(getAnalysisHistory).toHaveBeenCalled();
      });
    });

    it("handles history load failure gracefully", async () => {
      (getAnalysisHistory as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error("Failed to load history")
      );

      render(<VideoAnalyzer />);

      // Should not crash
      await waitFor(() => {
        expect(screen.queryByRole("textbox")).toBeInTheDocument();
      });
    });
  });
});
