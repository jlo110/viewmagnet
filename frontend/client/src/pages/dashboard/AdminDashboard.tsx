/**
 * Admin Dashboard — unified management interface for platform administrators.
 *
 * Provides tabbed access to:
 *   - Platform stats overview
 *   - User management (list, edit, delete)
 *   - Analysis management
 *   - Render management
 *   - Distribution job management
 *   - Project management
 *
 * Admin access is gated by the ``ADMIN_EMAILS`` env var on the backend.
 */
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  AlertCircle,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Edit,
  Loader2,
  RefreshCw,
  Search,
  ShieldAlert,
  Trash2,
  TrendingUp,
  Users,
  Video,
  Zap,
  FolderKanban,
  Share2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import {
  getAdminStats,
  listAdminUsers,
  getAdminUser,
  updateAdminUser,
  deleteAdminUser,
  setUserAdmin,
  listAdminAnalyses,
  deleteAdminAnalysis,
  listAdminRenders,
  listAdminDistribution,
  listAdminProjects,
  deleteAdminProject,
  type AdminStats,
  type AdminUserSummary,
  type AdminUserDetail,
  type AdminAnalysisSummary,
  type AdminRenderSummary,
  type AdminDistributionSummary,
  type AdminProjectSummary,
} from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/contexts/AuthContext";

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function AdminDashboard() {
  const { user } = useAuth();
  const isAdmin = Boolean(user?.is_admin);
  const [forbidden, setForbidden] = useState(false);
  const [activeTab, setActiveTab] = useState("overview");

  if (!isAdmin && !forbidden) {
    return <AdminGate />;
  }

  if (forbidden) {
    return <AdminGate />;
  }

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Admin Dashboard</h1>
        <p className="text-sm text-zinc-400">
          Manage users, data, and platform settings.
        </p>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-6 bg-zinc-900">
          <TabsTrigger value="overview" className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            Overview
          </TabsTrigger>
          <TabsTrigger value="users" className="flex items-center gap-2">
            <Users className="h-4 w-4" />
            Users
          </TabsTrigger>
          <TabsTrigger value="analyses" className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4" />
            Analyses
          </TabsTrigger>
          <TabsTrigger value="renders" className="flex items-center gap-2">
            <Video className="h-4 w-4" />
            Renders
          </TabsTrigger>
          <TabsTrigger value="distribution" className="flex items-center gap-2">
            <Share2 className="h-4 w-4" />
            Distribution
          </TabsTrigger>
          <TabsTrigger value="projects" className="flex items-center gap-2">
            <FolderKanban className="h-4 w-4" />
            Projects
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-6">
          <StatsOverview onForbidden={() => setForbidden(true)} />
        </TabsContent>

        <TabsContent value="users" className="mt-6">
          <UsersTable onForbidden={() => setForbidden(true)} />
        </TabsContent>

        <TabsContent value="analyses" className="mt-6">
          <AnalysesTable onForbidden={() => setForbidden(true)} />
        </TabsContent>

        <TabsContent value="renders" className="mt-6">
          <RendersTable onForbidden={() => setForbidden(true)} />
        </TabsContent>

        <TabsContent value="distribution" className="mt-6">
          <DistributionTable onForbidden={() => setForbidden(true)} />
        </TabsContent>

        <TabsContent value="projects" className="mt-6">
          <ProjectsTable onForbidden={() => setForbidden(true)} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stats Overview
// ---------------------------------------------------------------------------

function StatsOverview({ onForbidden }: { onForbidden: () => void }) {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getAdminStats();
      setStats(data);
    } catch (err) {
      const status = (err as { status?: number })?.status;
      if (status === 403) {
        onForbidden();
      } else {
        setError("Failed to load stats");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-zinc-400">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading stats...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 text-red-400">
        <AlertCircle className="h-4 w-4" /> {error}
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh
        </Button>
      </div>

      {/* Key Metrics */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Total Users"
          value={stats.total_users}
          subtitle={`+${stats.new_users_7d} this week`}
          icon={<Users className="h-5 w-5 text-blue-400" />}
        />
        <StatCard
          title="Active Users (7d)"
          value={stats.active_users_7d}
          subtitle={`${Math.round((stats.active_users_7d / stats.total_users) * 100)}% of total`}
          icon={<Zap className="h-5 w-5 text-green-400" />}
        />
        <StatCard
          title="Analyses (7d)"
          value={stats.analyses_7d}
          subtitle={`${stats.total_analyses} total`}
          icon={<TrendingUp className="h-5 w-5 text-purple-400" />}
        />
        <StatCard
          title="Est. Monthly Revenue"
          value={`$${stats.revenue_estimate_monthly.toLocaleString()}`}
          subtitle="Based on active subscriptions"
          icon={<BarChart3 className="h-5 w-5 text-amber-400" />}
        />
      </div>

      {/* Secondary Metrics */}
      <div className="grid gap-4 md:grid-cols-3">
        <StatCard
          title="Renders (7d)"
          value={stats.renders_7d}
          subtitle={`${stats.total_renders} total`}
          icon={<Video className="h-5 w-5 text-cyan-400" />}
        />
        <StatCard
          title="Distribution Jobs (7d)"
          value={stats.distribution_jobs_7d}
          subtitle={`${stats.total_distribution_jobs} total`}
          icon={<Share2 className="h-5 w-5 text-pink-400" />}
        />
        <Card className="border-zinc-800 bg-zinc-950/80">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-zinc-300">
              Users by Plan
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {Object.entries(stats.users_by_plan).map(([plan, count]) => (
                <div key={plan} className="flex items-center justify-between text-sm">
                  <span className="capitalize text-zinc-400">{plan}</span>
                  <Badge variant="secondary">{count}</Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatCard({
  title,
  value,
  subtitle,
  icon,
}: {
  title: string;
  value: string | number;
  subtitle: string;
  icon: React.ReactNode;
}) {
  return (
    <Card className="border-zinc-800 bg-zinc-950/80">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-zinc-300">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        <p className="text-xs text-zinc-500">{subtitle}</p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Users Table
// ---------------------------------------------------------------------------

function UsersTable({ onForbidden }: { onForbidden: () => void }) {
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [planFilter, setPlanFilter] = useState<string>("");
  const [editUser, setEditUser] = useState<AdminUserDetail | null>(null);
  const [editLoading, setEditLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    setTableError(null);
    try {
      const data = await listAdminUsers({
        page,
        page_size: 20,
        search: search || undefined,
        plan: planFilter || undefined,
      });
      setUsers(data.items);
      setTotal(data.total);
      setPages(data.pages);
    } catch (err) {
      const status =
        (err as { status?: number; response?: { status?: number } })?.status ??
        (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) {
        onForbidden();
      } else {
        setTableError(
          (err as { message?: string })?.message ?? "Failed to load users. Check the API is reachable."
        );
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [page, planFilter]);

  const handleSearch = () => {
    setPage(1);
    load();
  };

  const handleEdit = async (userId: number) => {
    setEditLoading(true);
    try {
      const user = await getAdminUser(userId);
      setEditUser(user);
    } catch {
      toast.error("Failed to load user details");
    } finally {
      setEditLoading(false);
    }
  };

  const handleSaveUser = async (updates: { plan?: string; name?: string }) => {
    if (!editUser) return;
    try {
      await updateAdminUser(editUser.id, updates);
      toast.success("User updated");
      setEditUser(null);
      load();
    } catch {
      toast.error("Failed to update user");
    }
  };

  const handleDelete = async (userId: number, email: string) => {
    if (!confirm(`Delete user ${email}? This cannot be undone.`)) return;
    try {
      await deleteAdminUser(userId);
      toast.success("User deleted");
      load();
    } catch {
      toast.error("Failed to delete user");
    }
  };

  const handleToggleAdmin = async (userId: number, currentIsAdmin: boolean) => {
    const action = currentIsAdmin ? "Revoke" : "Grant";
    if (!confirm(`${action} admin access for this user?`)) return;
    try {
      await setUserAdmin(userId, !currentIsAdmin);
      toast.success(`Admin access ${currentIsAdmin ? "revoked" : "granted"}`);
      load();
    } catch {
      toast.error("Failed to update admin status");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Input
            placeholder="Search email or name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            className="w-64"
          />
          <Button variant="outline" size="sm" onClick={handleSearch}>
            <Search className="h-4 w-4" />
          </Button>
        </div>
        <Select value={planFilter || "all"} onValueChange={(v) => setPlanFilter(v === "all" ? "" : v)}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder="All plans" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All plans</SelectItem>
            <SelectItem value="free">Free</SelectItem>
            <SelectItem value="starter">Starter</SelectItem>
            <SelectItem value="pro">Pro</SelectItem>
            <SelectItem value="agency">Agency</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
        <span className="ml-auto text-sm text-zinc-400">{total} users</span>
      </div>

      {tableError && (
        <div className="flex items-center gap-2 rounded-md border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {tableError}
        </div>
      )}

      <Card className="border-zinc-800 bg-zinc-950/80">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Plan</TableHead>
              <TableHead>Admin</TableHead>
              <TableHead>Analyses</TableHead>
              <TableHead>Renders</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-zinc-400">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </TableCell>
              </TableRow>
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-zinc-400">
                  No users found
                </TableCell>
              </TableRow>
            ) : (
              users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-mono text-xs">{u.email}</TableCell>
                  <TableCell>{u.name || "-"}</TableCell>
                  <TableCell>
                    <Badge variant={u.plan === "free" ? "secondary" : "default"}>
                      {u.plan}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={Boolean(u.is_admin)}
                      onCheckedChange={() => handleToggleAdmin(u.id, Boolean(u.is_admin))}
                      aria-label="Toggle admin"
                    />
                  </TableCell>
                  <TableCell>{u.total_analyses}</TableCell>
                  <TableCell>{u.total_renders}</TableCell>
                  <TableCell className="text-xs text-zinc-400">
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : "-"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleEdit(u.id)}
                      disabled={editLoading}
                    >
                      <Edit className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(u.id, u.email)}
                      className="text-red-400 hover:text-red-300"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      <Pagination page={page} pages={pages} onPageChange={setPage} />

      {editUser && (
        <EditUserDialog
          user={editUser}
          onClose={() => setEditUser(null)}
          onSave={handleSaveUser}
        />
      )}
    </div>
  );
}

function EditUserDialog({
  user,
  onClose,
  onSave,
}: {
  user: AdminUserDetail;
  onClose: () => void;
  onSave: (updates: { plan?: string; name?: string }) => void;
}) {
  const [plan, setPlan] = useState(user.plan);
  const [name, setName] = useState(user.name || "");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    await onSave({ plan, name: name || undefined });
    setSaving(false);
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit User</DialogTitle>
          <DialogDescription>{user.email}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label>Plan</Label>
            <Select value={plan} onValueChange={setPlan}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="free">Free</SelectItem>
                <SelectItem value="starter">Starter</SelectItem>
                <SelectItem value="pro">Pro</SelectItem>
                <SelectItem value="agency">Agency</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-4 text-sm text-zinc-400">
            <div>
              <span className="font-medium">Stripe:</span>{" "}
              {user.stripe_customer_id || "None"}
            </div>
            <div>
              <span className="font-medium">Status:</span>{" "}
              {user.subscription_status || "N/A"}
            </div>
            <div>
              <span className="font-medium">Analyses this month:</span>{" "}
              {user.analyses_this_month}
            </div>
            <div>
              <span className="font-medium">YouTube connections:</span>{" "}
              {user.youtube_connections}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Analyses Table
// ---------------------------------------------------------------------------

function AnalysesTable({ onForbidden }: { onForbidden: () => void }) {
  const [items, setItems] = useState<AdminAnalysisSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setTableError(null);
    try {
      const data = await listAdminAnalyses({ page, page_size: 20 });
      setItems(data.items);
      setTotal(data.total);
      setPages(data.pages);
    } catch (err) {
      const status =
        (err as { status?: number; response?: { status?: number } })?.status ??
        (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) onForbidden();
      else setTableError((err as { message?: string })?.message ?? "Failed to load analyses.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [page]);

  const handleDelete = async (id: number) => {
    if (!confirm("Delete this analysis?")) return;
    try {
      await deleteAdminAnalysis(id);
      toast.success("Analysis deleted");
      load();
    } catch {
      toast.error("Failed to delete");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-zinc-400">{total} analyses</span>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {tableError && (
        <div className="flex items-center gap-2 rounded-md border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          <AlertCircle className="h-4 w-4 shrink-0" /> {tableError}
        </div>
      )}

      <Card className="border-zinc-800 bg-zinc-950/80">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User</TableHead>
              <TableHead>Video ID</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Score</TableHead>
              <TableHead>Date</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-zinc-400">
                  No analyses found
                </TableCell>
              </TableRow>
            ) : (
              items.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="text-xs">{a.user_email || a.user_id}</TableCell>
                  <TableCell className="font-mono text-xs">{a.video_id}</TableCell>
                  <TableCell className="max-w-[200px] truncate text-sm">
                    {a.title || "-"}
                  </TableCell>
                  <TableCell>
                    {a.prediction_score !== null ? (
                      <Badge variant={a.prediction_score >= 70 ? "default" : "secondary"}>
                        {a.prediction_score.toFixed(0)}
                      </Badge>
                    ) : (
                      "-"
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-zinc-400">
                    {a.analyzed_at ? new Date(a.analyzed_at).toLocaleDateString() : "-"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(a.id)}
                      className="text-red-400 hover:text-red-300"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      <Pagination page={page} pages={pages} onPageChange={setPage} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Renders Table
// ---------------------------------------------------------------------------

function RendersTable({ onForbidden }: { onForbidden: () => void }) {
  const [items, setItems] = useState<AdminRenderSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setTableError(null);
    try {
      const data = await listAdminRenders({ page, page_size: 20 });
      setItems(data.items);
      setTotal(data.total);
      setPages(data.pages);
    } catch (err) {
      const status =
        (err as { status?: number; response?: { status?: number } })?.status ??
        (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) onForbidden();
      else setTableError((err as { message?: string })?.message ?? "Failed to load renders.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [page]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-zinc-400">{total} renders</span>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {tableError && (
        <div className="flex items-center gap-2 rounded-md border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          <AlertCircle className="h-4 w-4 shrink-0" /> {tableError}
        </div>
      )}

      <Card className="border-zinc-800 bg-zinc-950/80">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Date</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-zinc-400">
                  No renders found
                </TableCell>
              </TableRow>
            ) : (
              items.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="text-xs">{r.user_email || r.user_id}</TableCell>
                  <TableCell>{r.render_type}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        r.status === "completed"
                          ? "default"
                          : r.status === "failed"
                          ? "destructive"
                          : "secondary"
                      }
                    >
                      {r.status}
                    </Badge>
                  </TableCell>
                  <TableCell>{r.duration_minutes.toFixed(1)} min</TableCell>
                  <TableCell className="text-xs text-zinc-400">
                    {r.created_at ? new Date(r.created_at).toLocaleDateString() : "-"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      <Pagination page={page} pages={pages} onPageChange={setPage} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Distribution Table
// ---------------------------------------------------------------------------

function DistributionTable({ onForbidden }: { onForbidden: () => void }) {
  const [items, setItems] = useState<AdminDistributionSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setTableError(null);
    try {
      const data = await listAdminDistribution({ page, page_size: 20 });
      setItems(data.items);
      setTotal(data.total);
      setPages(data.pages);
    } catch (err) {
      const status =
        (err as { status?: number; response?: { status?: number } })?.status ??
        (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) onForbidden();
      else setTableError((err as { message?: string })?.message ?? "Failed to load distribution jobs.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [page]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-zinc-400">{total} distribution jobs</span>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {tableError && (
        <div className="flex items-center gap-2 rounded-md border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          <AlertCircle className="h-4 w-4 shrink-0" /> {tableError}
        </div>
      )}

      <Card className="border-zinc-800 bg-zinc-950/80">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Progress</TableHead>
              <TableHead>Date</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-zinc-400">
                  No distribution jobs found
                </TableCell>
              </TableRow>
            ) : (
              items.map((j) => (
                <TableRow key={j.id}>
                  <TableCell className="text-xs">{j.user_email || j.user_id}</TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        j.status === "completed"
                          ? "default"
                          : j.status === "failed"
                          ? "destructive"
                          : "secondary"
                      }
                    >
                      {j.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {j.completed_count} / {j.target_count}
                  </TableCell>
                  <TableCell className="text-xs text-zinc-400">
                    {j.created_at ? new Date(j.created_at).toLocaleDateString() : "-"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      <Pagination page={page} pages={pages} onPageChange={setPage} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Projects Table
// ---------------------------------------------------------------------------

function ProjectsTable({ onForbidden }: { onForbidden: () => void }) {
  const [items, setItems] = useState<AdminProjectSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setTableError(null);
    try {
      const data = await listAdminProjects({ page, page_size: 20 });
      setItems(data.items);
      setTotal(data.total);
      setPages(data.pages);
    } catch (err) {
      const status =
        (err as { status?: number; response?: { status?: number } })?.status ??
        (err as { response?: { status?: number } })?.response?.status;
      if (status === 403) onForbidden();
      else setTableError((err as { message?: string })?.message ?? "Failed to load projects.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [page]);

  const handleDelete = async (id: number, title: string) => {
    if (!confirm(`Delete project "${title}"?`)) return;
    try {
      await deleteAdminProject(id);
      toast.success("Project deleted");
      load();
    } catch {
      toast.error("Failed to delete");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-zinc-400">{total} projects</span>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      {tableError && (
        <div className="flex items-center gap-2 rounded-md border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          <AlertCircle className="h-4 w-4 shrink-0" /> {tableError}
        </div>
      )}

      <Card className="border-zinc-800 bg-zinc-950/80">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Clips</TableHead>
              <TableHead>Render Status</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </TableCell>
              </TableRow>
            ) : items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-zinc-400">
                  No projects found
                </TableCell>
              </TableRow>
            ) : (
              items.map((p) => (
                <TableRow key={p.id}>
                  <TableCell className="text-xs">{p.user_email || p.user_id}</TableCell>
                  <TableCell className="max-w-[200px] truncate">
                    {p.title || "Untitled"}
                  </TableCell>
                  <TableCell>{p.clip_count}</TableCell>
                  <TableCell>
                    {p.last_render_status ? (
                      <Badge
                        variant={
                          p.last_render_status === "completed"
                            ? "default"
                            : p.last_render_status === "failed"
                            ? "destructive"
                            : "secondary"
                        }
                      >
                        {p.last_render_status}
                      </Badge>
                    ) : (
                      "-"
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-zinc-400">
                    {p.updated_at ? new Date(p.updated_at).toLocaleDateString() : "-"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDelete(p.id, p.title || "Untitled")}
                      className="text-red-400 hover:text-red-300"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>

      <Pagination page={page} pages={pages} onPageChange={setPage} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function Pagination({
  page,
  pages,
  onPageChange,
}: {
  page: number;
  pages: number;
  onPageChange: (p: number) => void;
}) {
  if (pages <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      <span className="text-sm text-zinc-400">
        Page {page} of {pages}
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(page + 1)}
        disabled={page >= pages}
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}

function AdminGate() {
  return (
    <div className="p-6">
      <Card className="border-zinc-800 bg-zinc-950/80">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="h-5 w-5 text-amber-300" />
            Admin access required
          </CardTitle>
          <CardDescription>
            This page is operator-only. Add your account email to the{" "}
            <code className="rounded bg-zinc-900 px-1.5 py-0.5 text-xs">
              ADMIN_EMAILS
            </code>{" "}
            environment variable and re-login to get access.
          </CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}
