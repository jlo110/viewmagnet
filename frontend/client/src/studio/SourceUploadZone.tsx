/**
 * SourceUploadZone — shown in the Studio preview area when the source video
 * is a YouTube URL that can't be streamed server-side (datacenter IP block).
 *
 * UX intent: the creator already has the footage on their device — they
 * filmed it and uploaded it to YouTube. This zone lets them drag it in
 * directly. It does NOT ask them to "download from Shorts then re-upload";
 * it asks for the original file they already have.
 *
 * On file selection:
 *   1. Creates a blob: URL immediately → preview works.
 *   2. Uploads to /studio/source-upload in the background (ffmpeg faststart).
 *   3. Calls onSourceReady(serverUrl) so Studio can persist the server-side
 *      URL into the spec for rendering.
 */
import { useCallback, useRef, useState } from "react";
import { Upload, Film, Loader2, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { uploadSourceFile } from "@/lib/api";

interface Props {
  /** Called with the blob: URL the moment the user selects a file — for
   *  instant preview without waiting for the upload. */
  onBlobReady: (blobUrl: string) => void;
  /** Called once the server-side upload finishes with the backend URL that
   *  the render pipeline can access. */
  onSourceReady: (serverUrl: string) => void;
  /** Pixel dimensions to match the PreviewStage container. */
  width: number;
  height: number;
}

type UploadState = "idle" | "uploading" | "done" | "error";

export function SourceUploadZone({ onBlobReady, onSourceReady, width, height }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [progress, setProgress] = useState(0);
  const [isDragging, setIsDragging] = useState(false);

  const handleFile = useCallback(
    async (file: File) => {
      if (!file.type.startsWith("video/") && !file.name.match(/\.(mp4|mov|avi|webm|mkv|m4v)$/i)) {
        toast.error("Please drop a video file (MP4, MOV, etc.)");
        return;
      }

      // Instant blob preview.
      const blobUrl = URL.createObjectURL(file);
      onBlobReady(blobUrl);

      // Background upload to server for rendering.
      setUploadState("uploading");
      setProgress(0);
      try {
        const result = await uploadSourceFile(file, setProgress);
        setUploadState("done");
        onSourceReady(result.url);
      } catch (err) {
        setUploadState("error");
        toast.error("Upload failed — preview works but rendering may not. Try again.");
        console.error("Source upload failed:", err);
      }
    },
    [onBlobReady, onSourceReady],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const onFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div
      style={{ width, height }}
      className={`relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed transition-colors cursor-pointer select-none ${
        isDragging
          ? "border-violet-400 bg-violet-950/30"
          : "border-zinc-600 bg-zinc-900/80 hover:border-zinc-400"
      }`}
      onClick={() => uploadState === "idle" && inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={onDrop}
    >
      <input
        ref={inputRef}
        type="file"
        accept="video/*,.mp4,.mov,.avi,.webm,.mkv,.m4v"
        className="hidden"
        onChange={onFileChange}
      />

      {uploadState === "idle" && (
        <>
          <div className="p-4 rounded-full bg-zinc-800 mb-4">
            <Film className="w-10 h-10 text-violet-400" />
          </div>
          <p className="text-base font-semibold text-white mb-1">
            Drop your source footage here
          </p>
          <p className="text-sm text-zinc-400 text-center max-w-xs px-4">
            Your highlight is trimmed and ready to edit.
            Bring your original video file to preview and export.
          </p>
          <div className="mt-4 px-4 py-2 rounded-md bg-zinc-800 border border-zinc-700 flex items-center gap-2 text-sm text-zinc-300">
            <Upload className="w-4 h-4 text-violet-400 flex-shrink-0" />
            Click or drag a video file
          </div>
          <p className="mt-3 text-xs text-zinc-500 text-center max-w-[260px]">
            MP4, MOV, AVI, WebM · captions &amp; timestamps already configured
          </p>
        </>
      )}

      {uploadState === "uploading" && (
        <>
          <Loader2 className="w-10 h-10 text-violet-400 animate-spin mb-4" />
          <p className="text-sm font-medium text-white mb-2">Preparing footage…</p>
          <div className="w-48 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-violet-500 transition-all duration-200"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-zinc-500">{progress}% uploaded</p>
        </>
      )}

      {uploadState === "done" && (
        <>
          <CheckCircle2 className="w-10 h-10 text-green-400 mb-3" />
          <p className="text-sm font-medium text-white">Footage ready — rendering enabled</p>
        </>
      )}

      {uploadState === "error" && (
        <div
          className="flex flex-col items-center cursor-pointer"
          onClick={() => { setUploadState("idle"); inputRef.current?.click(); }}
        >
          <Film className="w-10 h-10 text-red-400 mb-3" />
          <p className="text-sm text-red-400 font-medium">Upload failed</p>
          <p className="text-xs text-zinc-500 mt-1">Click to try again</p>
        </div>
      )}
    </div>
  );
}
