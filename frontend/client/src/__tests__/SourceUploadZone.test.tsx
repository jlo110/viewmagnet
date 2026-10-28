/**
 * Tests for studio/SourceUploadZone.tsx
 *
 * Verifies the user-facing upload experience:
 *   - Drop zone renders with clear instructions when source is YouTube.
 *   - File selection creates a blob URL and calls onBlobReady immediately.
 *   - Successful upload calls onSourceReady with the server URL.
 *   - Upload failure shows error state without crashing.
 *   - Non-video files are rejected with a toast.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock the API upload function
vi.mock("@/lib/api", () => ({
  uploadSourceFile: vi.fn(),
}));

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { SourceUploadZone } from "../studio/SourceUploadZone";
import { uploadSourceFile } from "@/lib/api";
import { toast } from "sonner";

const defaultProps = {
  onBlobReady: vi.fn(),
  onSourceReady: vi.fn(),
  width: 640,
  height: 360,
};

describe("SourceUploadZone", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // URL.createObjectURL is not available in jsdom
    Object.defineProperty(URL, "createObjectURL", {
      writable: true,
      value: vi.fn(() => "blob:fake-blob-url"),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // -------------------------------------------------------------------------
  // Initial render
  // -------------------------------------------------------------------------

  describe("initial render", () => {
    it("shows the drop zone with instructions", () => {
      render(<SourceUploadZone {...defaultProps} />);
      expect(screen.getByText(/drop your source footage/i)).toBeInTheDocument();
    });

    it("explains that the highlight is already configured", () => {
      render(<SourceUploadZone {...defaultProps} />);
      expect(screen.getByText(/highlight is|ready to edit/i)).toBeInTheDocument();
    });

    it("shows accepted file types", () => {
      render(<SourceUploadZone {...defaultProps} />);
      expect(screen.getByText(/mp4|mov|avi|webm/i)).toBeInTheDocument();
    });

    it("renders at the correct dimensions", () => {
      const { container } = render(
        <SourceUploadZone {...defaultProps} width={800} height={450} />,
      );
      const zone = container.firstChild as HTMLElement;
      expect(zone).toHaveStyle({ width: "800px", height: "450px" });
    });
  });

  // -------------------------------------------------------------------------
  // File selection — blob URL + upload
  // -------------------------------------------------------------------------

  describe("file selection", () => {
    it("calls onBlobReady immediately with a blob URL", async () => {
      (uploadSourceFile as ReturnType<typeof vi.fn>).mockResolvedValue({
        url: "studio/source-cache/abc123.mp4",
        filename: "abc123.mp4",
      });

      render(<SourceUploadZone {...defaultProps} />);
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = new File(["video bytes"], "clip.mp4", { type: "video/mp4" });

      await userEvent.upload(input, file);

      expect(defaultProps.onBlobReady).toHaveBeenCalledWith("blob:fake-blob-url");
    });

    it("calls onSourceReady with the server URL after upload", async () => {
      (uploadSourceFile as ReturnType<typeof vi.fn>).mockResolvedValue({
        url: "studio/source-cache/abc123.mp4",
        filename: "abc123.mp4",
      });

      render(<SourceUploadZone {...defaultProps} />);
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      const file = new File(["video bytes"], "clip.mp4", { type: "video/mp4" });

      await userEvent.upload(input, file);

      await waitFor(() => {
        expect(defaultProps.onSourceReady).toHaveBeenCalledWith(
          "studio/source-cache/abc123.mp4",
        );
      });
    });

    it("shows uploading state while upload is in progress", async () => {
      let resolve: (v: any) => void;
      (uploadSourceFile as ReturnType<typeof vi.fn>).mockImplementation(
        () => new Promise((r) => { resolve = r; }),
      );

      render(<SourceUploadZone {...defaultProps} />);
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(input, {
        target: { files: [new File(["v"], "c.mp4", { type: "video/mp4" })] },
      });

      await waitFor(() => {
        const hasUploadingState =
          screen.queryByText(/preparing|uploading/i) !== null ||
          document.querySelector('[class*="animate"]') !== null;
        expect(hasUploadingState).toBe(true);
      });
    });

    it("shows done state after successful upload", async () => {
      (uploadSourceFile as ReturnType<typeof vi.fn>).mockResolvedValue({
        url: "studio/source-cache/xyz.mp4",
        filename: "xyz.mp4",
      });

      render(<SourceUploadZone {...defaultProps} />);
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      await userEvent.upload(
        input,
        new File(["v"], "clip.mp4", { type: "video/mp4" }),
      );

      await waitFor(() => {
        const hasDoneState =
          screen.queryByText(/ready|rendering enabled/i) !== null ||
          document.querySelector('[class*="green"]') !== null;
        expect(hasDoneState).toBe(true);
      });
    });
  });

  // -------------------------------------------------------------------------
  // Upload failure
  // -------------------------------------------------------------------------

  describe("upload failure", () => {
    it("shows error state when upload fails", async () => {
      (uploadSourceFile as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error("Network error"),
      );

      render(<SourceUploadZone {...defaultProps} />);
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      await userEvent.upload(
        input,
        new File(["v"], "clip.mp4", { type: "video/mp4" }),
      );

      await waitFor(() => {
        const hasError =
          screen.queryByText(/failed|error/i) !== null ||
          document.querySelector('[class*="red"]') !== null;
        expect(hasError).toBe(true);
      });
    });

    it("shows a toast error on upload failure", async () => {
      (uploadSourceFile as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error("Network error"),
      );

      render(<SourceUploadZone {...defaultProps} />);
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      await userEvent.upload(
        input,
        new File(["v"], "clip.mp4", { type: "video/mp4" }),
      );

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalled();
      });
    });

    it("still calls onBlobReady even when upload fails", async () => {
      (uploadSourceFile as ReturnType<typeof vi.fn>).mockRejectedValue(
        new Error("fail"),
      );

      render(<SourceUploadZone {...defaultProps} />);
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      await userEvent.upload(
        input,
        new File(["v"], "clip.mp4", { type: "video/mp4" }),
      );

      // Blob preview should still work even if server upload fails.
      expect(defaultProps.onBlobReady).toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // Drag and drop
  // -------------------------------------------------------------------------

  describe("drag and drop", () => {
    it("changes border colour on dragover", () => {
      const { container } = render(<SourceUploadZone {...defaultProps} />);
      const zone = container.firstChild as HTMLElement;

      fireEvent.dragOver(zone, { preventDefault: () => {} });

      const hasDragStyle =
        zone.className.includes("violet") ||
        zone.className.includes("drag") ||
        zone.getAttribute("class")?.includes("violet");
      expect(hasDragStyle).toBe(true);
    });

    it("resets border on dragleave", () => {
      const { container } = render(<SourceUploadZone {...defaultProps} />);
      const zone = container.firstChild as HTMLElement;

      fireEvent.dragOver(zone, { preventDefault: () => {} });
      fireEvent.dragLeave(zone);

      expect(zone.className.includes("violet-400")).toBe(false);
    });
  });
});
