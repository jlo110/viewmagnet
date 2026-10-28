/*
 * Drafts page — discoverable list of in-progress Studio sessions.
 *
 * Pulls the user's edit sessions from /studio/sessions and shows them as
 * a grid of cards. Each card has:
 *   - a 16:9 video poster (first frame via <video preload="metadata">)
 *     so we don't need a separate thumbnail endpoint;
 *   - title + last-edited timestamp;
 *   - "Rendered" / "In progress" badge based on last_render_status;
 *   - "Continue editing" (-> /dashboard/studio/{clipKey}) and
 *     "Delete" (DELETE /studio/sessions/{clipKey}) actions.
 *
 * The grid hides the demo clip key behind a "Show demo" toggle so the
 * default view is just the user's own work.
 */
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Activity,
  Clapperboard,
  Download,
  FileStack,
  Film,
  Layers,
  Loader2,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Send,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useLocation } from "wouter";
import { toast } from "sonner";

import { listSessions, deleteSession } from "@/studio/api";
import { proxyVideoUrl } from "@/studio/sourceUrl";
import type { EditSession } from "@/studio/types";
import { buildDistributionLink } from "@/lib/deepLinks";
import {
  createStudioProject,
  deleteStudioProject,
  listStudioProjects,
  renderStudioProject,
  type StudioProjectListItem,
} from "@/lib/api";
import {
  recordRenderTrigger,
} from "@/lib/renderProgress";

type DraftRow = Pick<
  EditSession,
  | "id"
  | "clip_key"
  | "title"
  | "source_video_url"
  | "last_render_status"
  | "last_render_url"
  | "updated_at"
>;

// Compact "5m ago" / "3h ago" / "2d ago" formatter — avoids pulling in
// date-fns for a single use site.
function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(1, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

function DraftCard({
  row,
  onDelete,
}: {
  row: DraftRow;
  onDelete: (clipKey: string) => void;
}) {
  const [, navigate] = useLocation();
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // last_render_url > source_video_url so the user sees the most
  // representative frame (the rendered output) when available.
  const posterUrl = row.last_render_url || row.source_video_url;
  const playbackUrl = proxyVideoUrl(posterUrl);

  const handleContinue = () => {
    navigate(`/dashboard/studio/${row.clip_key}`);
  };

  const handleDeleteClick = async () => {
    if (!confirming) {
      setConfirming(true);
      // Auto-cancel the confirm state after 3s of inactivity.
      setTimeout(() => setConfirming(false), 3000);
      return;
    }
    setDeleting(true);
    try {
      await deleteSession(row.clip_key);
      onDelete(row.clip_key);
      toast.success("Draft deleted");
    } catch {
      toast.error("Couldn't delete draft");
      setDeleting(false);
      setConfirming(false);
    }
  };

  const rendered = row.last_render_status === "done" && !!row.last_render_url;
  const failed = row.last_render_status === "failed";
  const inFlight =
    row.last_render_status === "queued" || row.last_render_status === "rendering";

  return (
    <Card className="bg-card border-border/50 overflow-hidden group flex flex-col">
      <button
        onClick={handleContinue}
        className="relative aspect-video bg-black/70 overflow-hidden cursor-pointer w-full"
        title="Continue editing"
      >
        {playbackUrl ? (
          // <video preload="metadata"> shows the first frame on most
          // browsers without playing audio. Muted is required for
          // autoplay-eligibility on iOS even though we don't autoplay.
          <video
            src={playbackUrl}
            preload="metadata"
            muted
            playsInline
            className="w-full h-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-violet-500/15 to-cyan-glow/10">
            <Clapperboard className="w-10 h-10 opacity-40" />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent pointer-events-none" />
        <div className="absolute top-2 left-2 flex gap-1.5">
          {rendered && (
            <Badge className="bg-emerald-500/90 text-emerald-50 border-0 text-[10px] h-5">
              Rendered
            </Badge>
          )}
          {inFlight && (
            <Badge className="bg-cyan-glow/90 text-deep-charcoal border-0 text-[10px] h-5 gap-1">
              <Loader2 className="w-2.5 h-2.5 animate-spin" /> Rendering
            </Badge>
          )}
          {failed && (
            <Badge className="bg-amber-500/90 text-amber-50 border-0 text-[10px] h-5">
              Render failed
            </Badge>
          )}
          {!rendered && !inFlight && !failed && (
            <Badge variant="secondary" className="text-[10px] h-5">
              In progress
            </Badge>
          )}
        </div>
      </button>

      <CardContent className="p-3 space-y-2 flex-1 flex flex-col">
        <div className="space-y-0.5 flex-1">
          <div
            className="text-sm font-semibold truncate"
            title={row.title || "Untitled draft"}
          >
            {row.title || "Untitled draft"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            Edited {timeAgo(row.updated_at)}
          </div>
        </div>

        <div className="flex gap-1.5">
          <Button
            size="sm"
            variant="default"
            className="flex-1 gap-1.5 h-8 text-xs"
            onClick={handleContinue}
          >
            <Pencil className="w-3 h-3" />
            Continue
          </Button>
          {rendered && row.last_render_url && (
            // Cross-tool deep link: hand the finished render off to the
            // Distribution Hub publish form with title + render URL
            // pre-filled. The hub fetches the user's brand kit on mount
            // so the caption signature + default hashtags auto-apply.
            <Link
              href={buildDistributionLink({
                renderUrl: row.last_render_url,
                title: row.title || "Untitled render",
                clipKey: row.clip_key,
              })}
            >
              <Button
                size="sm"
                variant="outline"
                className="h-8 px-2 text-xs border-cyan-glow/40 text-cyan-glow hover:bg-cyan-glow/10"
                title="Publish this render to your connected social accounts"
              >
                <Send className="w-3 h-3" />
              </Button>
            </Link>
          )}
          <Button
            size="sm"
            variant="outline"
            className={`h-8 px-2 text-xs ${
              confirming
                ? "border-red-500 text-red-300 hover:text-red-200"
                : "text-muted-foreground hover:text-red-300"
            }`}
            onClick={handleDeleteClick}
            disabled={deleting}
            title={confirming ? "Click again to confirm" : "Delete draft"}
          >
            {deleting ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Trash2 className="w-3 h-3" />
            )}
            {confirming && (
              <span className="ml-1 text-[10px]">Sure?</span>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ProjectCard({
  project,
  onDelete,
}: {
  project: StudioProjectListItem;
  onDelete: (projectId: number) => void;
}) {
  const [, navigate] = useLocation();
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const handleOpen = () =>
    navigate(`/dashboard/studio/project/${project.id}`);

  const handleRetry = async () => {
    setRetrying(true);
    try {
      const status = await renderStudioProject(project.id);
      recordRenderTrigger("project", project.id, status.status);
      toast.success("Render re-queued");
    } catch {
      toast.error("Couldn't re-queue render");
    } finally {
      setRetrying(false);
    }
  };

  const handleDeleteClick = async () => {
    if (!confirming) {
      setConfirming(true);
      window.setTimeout(() => setConfirming(false), 3000);
      return;
    }
    setDeleting(true);
    try {
      await deleteStudioProject(project.id);
      onDelete(project.id);
      toast.success("Project deleted");
    } catch {
      toast.error("Couldn't delete project");
    } finally {
      setDeleting(false);
    }
  };

  const status = project.last_render_status;
  const isRendered = status === "done" && project.last_render_url;

  return (
    <Card className="bg-card border-border/50 hover:border-cyan-glow/40 transition-colors">
      <CardContent className="p-4 space-y-3">
        <div
          onClick={handleOpen}
          className="aspect-video rounded-md bg-deep-charcoal cursor-pointer flex items-center justify-center overflow-hidden"
        >
          {project.last_render_url ? (
            <video
              src={project.last_render_url}
              preload="metadata"
              className="w-full h-full object-cover"
              muted
            />
          ) : (
            <Layers className="w-8 h-8 text-muted-foreground/40" />
          )}
        </div>
        <div className="flex items-center justify-between gap-2">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold truncate">{project.title}</p>
            <div className="flex items-center gap-2 mt-1 text-[11px] text-muted-foreground">
              <span>
                {project.clip_count} clip{project.clip_count === 1 ? "" : "s"}
              </span>
              <span>•</span>
              <span>{project.default_aspect}</span>
              <span>•</span>
              <span>{timeAgo(project.updated_at)}</span>
            </div>
          </div>
          <Badge
            variant="outline"
            className={`text-[10px] shrink-0 ${
              isRendered
                ? "border-emerald-500/40 text-emerald-400"
                : status === "failed"
                ? "border-red-500/40 text-red-400"
                : status === "queued" || status === "rendering"
                ? "border-cyan-glow/40 text-cyan-glow"
                : "border-border/40 text-muted-foreground"
            }`}
          >
            {status}
          </Badge>
        </div>
        <div className="flex gap-1.5">
          <Button
            size="sm"
            variant="default"
            className="flex-1 gap-1.5 h-8 text-xs"
            onClick={handleOpen}
          >
            <Pencil className="w-3 h-3" />
            Open
          </Button>
          {isRendered && project.last_render_url && (
            <Link
              href={buildDistributionLink({
                renderUrl: project.last_render_url,
                title: project.title,
              })}
            >
              <Button
                size="sm"
                variant="outline"
                className="h-8 px-2 text-xs border-cyan-glow/40 text-cyan-glow hover:bg-cyan-glow/10"
                title="Publish this project to your connected social accounts"
              >
                <Send className="w-3 h-3" />
              </Button>
            </Link>
          )}
          {status === "failed" && (
            <Button
              size="sm"
              variant="outline"
              className="h-8 px-2 text-xs border-red-500/40 text-red-300 hover:bg-red-500/10"
              title="Retry render"
              onClick={handleRetry}
              disabled={retrying}
            >
              {retrying ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <RotateCcw className="w-3 h-3" />
              )}
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            className={`h-8 px-2 text-xs ${
              confirming
                ? "border-red-500 text-red-300 hover:text-red-200"
                : "text-muted-foreground hover:text-red-300"
            }`}
            onClick={handleDeleteClick}
            disabled={deleting}
            title={confirming ? "Click again to confirm" : "Delete project"}
          >
            {deleting ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <Trash2 className="w-3 h-3" />
            )}
            {confirming && <span className="ml-1 text-[10px]">Sure?</span>}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function Drafts() {
  const [, navigate] = useLocation();
  const [rows, setRows] = useState<DraftRow[] | null>(null);
  const [projects, setProjects] = useState<StudioProjectListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creatingProject, setCreatingProject] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const items = await listSessions();
        if (!cancelled) setRows(items);
      } catch (err) {
        if (!cancelled) {
          setError("Couldn't load drafts");
          setRows([]);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const items = await listStudioProjects();
        if (!cancelled) setProjects(items);
      } catch {
        if (!cancelled) setProjects([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleDelete = (clipKey: string) => {
    setRows((cur) => (cur ? cur.filter((r) => r.clip_key !== clipKey) : cur));
  };

  const handleProjectDelete = (projectId: number) => {
    setProjects((cur) =>
      cur ? cur.filter((p) => p.id !== projectId) : cur,
    );
  };

  const handleCreateProject = async () => {
    setCreatingProject(true);
    try {
      const project = await createStudioProject({});
      navigate(`/dashboard/studio/project/${project.id}`);
    } catch {
      toast.error("Couldn't create project");
    } finally {
      setCreatingProject(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight flex items-center gap-2">
            <FileStack className="w-6 h-6 text-cyan-glow" />
            Drafts
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Pick up where you left off. Projects stitch multiple clips into
            long-form videos; single clips are one-off edits.
          </p>
        </div>
        <Link href="/dashboard/renders">
          <Button variant="outline" size="sm" className="gap-2">
            <Activity className="w-3.5 h-3.5" />
            Renders queue
          </Button>
        </Link>
      </div>

      <Tabs defaultValue="projects" className="space-y-4">
        <TabsList>
          <TabsTrigger value="projects" className="gap-2">
            <Layers className="w-3.5 h-3.5" />
            Projects
            {projects && projects.length > 0 && (
              <span className="ml-1 text-[10px] text-muted-foreground">
                ({projects.length})
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="clips" className="gap-2">
            <Film className="w-3.5 h-3.5" />
            Single clips
            {rows && rows.length > 0 && (
              <span className="ml-1 text-[10px] text-muted-foreground">
                ({rows.length})
              </span>
            )}
          </TabsTrigger>
        </TabsList>

        {/* ---- Projects tab -------------------------------------------- */}
        <TabsContent value="projects" className="space-y-4">
          <div className="flex justify-end">
            <Button
              onClick={handleCreateProject}
              disabled={creatingProject}
              className="gap-2 bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
            >
              {creatingProject ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Plus className="w-4 h-4" />
              )}
              New project
            </Button>
          </div>

          {projects === null && (
            <div className="flex items-center justify-center h-48">
              <Loader2 className="w-6 h-6 animate-spin text-cyan-glow" />
            </div>
          )}

          {projects !== null && projects.length === 0 && (
            <Card className="bg-card border-border/50 border-dashed">
              <CardContent className="p-10 flex flex-col items-center text-center gap-3">
                <div className="w-14 h-14 rounded-full bg-cyan-glow/10 flex items-center justify-center">
                  <Layers className="w-7 h-7 text-cyan-glow" />
                </div>
                <div>
                  <div className="text-base font-semibold">No projects yet</div>
                  <div className="text-sm text-muted-foreground mt-1 max-w-sm">
                    Projects stitch multiple saved clips into a single
                    long-form video. Edit clips in the Studio first, then
                    combine them here.
                  </div>
                </div>
                <Button
                  onClick={handleCreateProject}
                  disabled={creatingProject}
                  className="gap-2 mt-2 bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
                >
                  <Plus className="w-4 h-4" />
                  Create your first project
                </Button>
              </CardContent>
            </Card>
          )}

          {projects !== null && projects.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {projects.map((p) => (
                <ProjectCard
                  key={p.id}
                  project={p}
                  onDelete={handleProjectDelete}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* ---- Single clips tab --------------------------------------- */}
        <TabsContent value="clips" className="space-y-4">
          <div className="flex justify-end">
            <Link href="/dashboard/studio">
              <Button className="gap-2 bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90">
                <Plus className="w-4 h-4" />
                New clip
              </Button>
            </Link>
          </div>

          {rows === null && (
            <div className="flex items-center justify-center h-48">
              <Loader2 className="w-6 h-6 animate-spin text-cyan-glow" />
            </div>
          )}

          {rows !== null && rows.length === 0 && (
            <Card className="bg-card border-border/50 border-dashed">
              <CardContent className="p-10 flex flex-col items-center text-center gap-3">
                <div className="w-14 h-14 rounded-full bg-violet-500/10 flex items-center justify-center">
                  <Sparkles className="w-7 h-7 text-violet-400" />
                </div>
                <div>
                  <div className="text-base font-semibold">No drafts yet</div>
                  <div className="text-sm text-muted-foreground mt-1 max-w-sm">
                    {error ??
                      "Open Studio and tweak a clip — your edits auto-save and show up here so you can come back any time."}
                  </div>
                </div>
                <Link href="/dashboard/studio">
                  <Button className="gap-2 mt-2 bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90">
                    <Clapperboard className="w-4 h-4" />
                    Open Studio
                  </Button>
                </Link>
              </CardContent>
            </Card>
          )}

          {rows !== null && rows.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {rows.map((row) => (
                <DraftCard
                  key={row.clip_key}
                  row={row}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
