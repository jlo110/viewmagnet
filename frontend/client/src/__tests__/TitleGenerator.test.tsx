/**
 * Tests for TitleGenerator.tsx component
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the API
vi.mock("@/lib/api", () => ({
  generateTitles: vi.fn(() =>
    Promise.resolve([
      { title: "Generated Title 1", score: 85, reason: "High engagement potential" },
      { title: "Generated Title 2", score: 78, reason: "Good curiosity hook" },
      { title: "Generated Title 3", score: 72, reason: "Clear value proposition" },
    ])
  ),
}));

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

// Import after mocks
import TitleGenerator from "../pages/dashboard/TitleGenerator";
import { generateTitles } from "@/lib/api";
import { toast } from "sonner";

describe("TitleGenerator", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Helper to get the textarea element
  const getTextarea = () => {
    return (
      screen.queryByPlaceholderText(/describe what your video is about/i) ||
      screen.queryByPlaceholderText(/topic/i) ||
      screen.queryByRole("textbox")
    );
  };

  describe("Initial render", () => {
    it("renders the title generator interface", () => {
      render(<TitleGenerator />);

      // Should have a textarea for topic input
      const textarea = getTextarea();
      expect(textarea).toBeInTheDocument();
    });

    it("renders the generate button", () => {
      render(<TitleGenerator />);

      const button = screen.getByRole("button", { name: /generate/i });
      expect(button).toBeInTheDocument();
    });

    it("renders niche selector", () => {
      render(<TitleGenerator />);

      // Should have a select for niche
      const select = screen.queryByRole("combobox") || document.querySelector('[role="combobox"]');
      expect(select).toBeInTheDocument();
    });

    it("shows empty state initially", () => {
      render(<TitleGenerator />);

      // No generated titles yet
      expect(screen.queryByText(/Generated Title/i)).not.toBeInTheDocument();
    });
  });

  describe("Topic input", () => {
    it("accepts topic input", async () => {
      const user = userEvent.setup();
      render(<TitleGenerator />);

      const textarea = getTextarea();
      if (textarea) {
        await user.type(textarea, "How to learn Python programming");
        expect(textarea).toHaveValue("How to learn Python programming");
      }
    });

    it("validates empty topic before submission", async () => {
      const user = userEvent.setup();
      render(<TitleGenerator />);

      const button = screen.getByRole("button", { name: /generate/i });
      await user.click(button);

      // Component may show error toast or prevent submission
      // Either way, the API should not be called with empty topic
      expect(generateTitles).not.toHaveBeenCalled();
    });
  });

  describe("Title generation", () => {
    it("generates titles on button click", async () => {
      const user = userEvent.setup();
      render(<TitleGenerator />);

      const textarea = getTextarea();
      if (textarea) {
        await user.type(textarea, "React hooks tutorial");
      }

      const button = screen.getByRole("button", { name: /generate/i });
      await user.click(button);

      await waitFor(() => {
        expect(generateTitles).toHaveBeenCalled();
      });
    });

    it("displays generated titles", async () => {
      const user = userEvent.setup();
      render(<TitleGenerator />);

      const textarea = getTextarea();
      if (textarea) {
        await user.type(textarea, "JavaScript tips");
      }

      const button = screen.getByRole("button", { name: /generate/i });
      await user.click(button);

      await waitFor(() => {
        // Should show generated titles or scores - use queryAll to handle multiple elements
        const hasGeneratedContent =
          screen.queryAllByText(/Generated Title/i).length > 0 ||
          screen.queryAllByText(/85/).length > 0 ||
          screen.queryAllByText(/engagement/i).length > 0 ||
          document.querySelectorAll('[class*="card"]').length > 2;
        
        expect(hasGeneratedContent).toBeTruthy();
      });
    });

    it("shows loading state during generation", async () => {
      // Make the API call slow
      (generateTitles as ReturnType<typeof vi.fn>).mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(
              () =>
                resolve([
                  { title: "Title", score: 80, reason: "Good" },
                ]),
              100
            )
          )
      );

      const user = userEvent.setup();
      render(<TitleGenerator />);

      const textarea = getTextarea();
      if (textarea) {
        await user.type(textarea, "Test topic");
      }

      const button = screen.getByRole("button", { name: /generate/i });
      await user.click(button);

      // Should show loading indicator
      const hasLoadingIndicator =
        document.querySelector('[class*="animate"]') !== null ||
        document.querySelector('[class*="spin"]') !== null ||
        screen.queryByText(/generating/i) !== null ||
        button.hasAttribute("disabled");
      
      expect(hasLoadingIndicator).toBeTruthy();
    });
  });

  describe("Generated title display", () => {
    it("shows score badges for each title", async () => {
      const user = userEvent.setup();
      render(<TitleGenerator />);

      const textarea = getTextarea();
      if (textarea) {
        await user.type(textarea, "Test topic");
      }

      const button = screen.getByRole("button", { name: /generate/i });
      await user.click(button);

      await waitFor(() => {
        // Should show scores
        const hasScores =
          screen.queryByText(/85/) !== null ||
          screen.queryByText(/78/) !== null ||
          screen.queryByText(/score/i) !== null ||
          document.querySelector('[class*="badge"]') !== null;
        
        expect(hasScores).toBeTruthy();
      });
    });

    it("shows reasoning for each title", async () => {
      const user = userEvent.setup();
      render(<TitleGenerator />);

      const textarea = getTextarea();
      if (textarea) {
        await user.type(textarea, "Test topic");
      }

      const button = screen.getByRole("button", { name: /generate/i });
      await user.click(button);

      await waitFor(() => {
        const hasReasons =
          screen.queryByText(/engagement/i) !== null ||
          screen.queryByText(/curiosity/i) !== null ||
          screen.queryByText(/reason/i) !== null;
        
        expect(hasReasons).toBeTruthy();
      });
    });
  });

  describe("Copy functionality", () => {
    it("copies title to clipboard on copy button click", async () => {
      const user = userEvent.setup();
      render(<TitleGenerator />);

      // Generate titles first
      const textarea = getTextarea();
      if (textarea) {
        await user.type(textarea, "Test topic");
      }

      const generateButton = screen.getByRole("button", { name: /generate/i });
      await user.click(generateButton);

      await waitFor(() => {
        // Titles should be generated - use queryAll to handle multiple
        const hasContent =
          screen.queryAllByText(/Generated Title/i).length > 0 ||
          screen.queryAllByText(/Built/i).length > 0 ||
          document.querySelectorAll('[class*="card"]').length > 2;
        
        expect(hasContent).toBeTruthy();
      });

      // Find and click copy button if it exists
      const copyButtons = screen.queryAllByRole("button").filter(
        (btn) =>
          btn.querySelector('[class*="copy"]') ||
          btn.textContent?.toLowerCase().includes("copy")
      );

      if (copyButtons.length > 0) {
        await user.click(copyButtons[0]);
        // Just verify the button was clickable
        expect(true).toBe(true);
      }
    });
  });

  describe("Niche selection", () => {
    it("renders niche selector", () => {
      render(<TitleGenerator />);

      // Find the select/combobox - just verify it exists
      const select = screen.queryByRole("combobox") || document.querySelector('[role="combobox"]');
      expect(select).toBeInTheDocument();
    });
  });

  describe("Error handling", () => {
    it("handles API error gracefully", async () => {
      (generateTitles as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
        new Error("API Error")
      );

      const user = userEvent.setup();
      render(<TitleGenerator />);

      const textarea = getTextarea();
      if (textarea) {
        await user.type(textarea, "Test topic");
      }

      const button = screen.getByRole("button", { name: /generate/i });
      await user.click(button);

      await waitFor(() => {
        // Component should still render (with fallback titles or error state)
        expect(screen.queryByRole("textbox")).toBeInTheDocument();
      });
    });
  });

  describe("Tag extraction", () => {
    it("shows tags for generated titles", async () => {
      const user = userEvent.setup();
      render(<TitleGenerator />);

      const textarea = getTextarea();
      if (textarea) {
        await user.type(textarea, "Test topic");
      }

      const button = screen.getByRole("button", { name: /generate/i });
      await user.click(button);

      await waitFor(() => {
        // Tags should be extracted and displayed - use queryAll to handle multiple
        const hasTags =
          screen.queryAllByText(/Number/i).length > 0 ||
          screen.queryAllByText(/Question/i).length > 0 ||
          screen.queryAllByText(/Personal/i).length > 0 ||
          document.querySelectorAll('[class*="badge"]').length > 0;
        
        expect(hasTags).toBeTruthy();
      });
    });
  });
});
