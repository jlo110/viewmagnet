/**
 * Admin login page — /admin/login
 *
 * Uses the same auth flow as the regular login, but immediately verifies
 * the account has ``is_admin = true`` before granting access. Non-admin
 * accounts are rejected with a clear error; the session token is cleared.
 *
 * Direct link: /admin/login
 * On success: redirected to /dashboard/admin
 */
import { useState } from "react";
import { useLocation } from "wouter";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

export default function AdminLogin() {
  const [, navigate] = useLocation();
  const { login, user, isLoading: authLoading, logout } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already logged in as admin → go straight to dashboard
  if (!authLoading && user?.is_admin) {
    navigate("/dashboard/admin");
    return null;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email || !password) {
      setError("Please enter your email and password.");
      return;
    }

    setLoading(true);
    try {
      const response = await login({ email, password });

      // Check admin flag on the returned user payload
      if (!response?.user?.is_admin) {
        // Not an admin — clear the session immediately so we don't leave a
        // regular-user token in localStorage.
        logout();
        setError("This account does not have admin access.");
        setLoading(false);
        return;
      }

      toast.success("Admin access granted");
      navigate("/dashboard/admin");
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      setError(e.response?.data?.detail || "Invalid email or password.");
    } finally {
      setLoading(false);
    }
  };

  if (authLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950">
        <Loader2 className="h-8 w-8 animate-spin text-amber-400" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-zinc-950 p-4">
      {/* Shield badge */}
      <div className="mb-8 flex flex-col items-center gap-3">
        <div className="flex h-16 w-16 items-center justify-center rounded-full border border-amber-500/30 bg-amber-500/10">
          <ShieldCheck className="h-8 w-8 text-amber-400" />
        </div>
        <div className="text-center">
          <h1 className="text-xl font-semibold tracking-tight text-white">
            Admin Portal
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            Restricted access — administrators only
          </p>
        </div>
      </div>

      {/* Card */}
      <div className="w-full max-w-sm rounded-xl border border-zinc-800 bg-zinc-900 p-8 shadow-2xl">
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-zinc-300">
              Email
            </Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              placeholder="admin@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="border-zinc-700 bg-zinc-800 text-white placeholder:text-zinc-600 focus:border-amber-500"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-zinc-300">
              Password
            </Label>
            <div className="relative">
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="border-zinc-700 bg-zinc-800 pr-10 text-white placeholder:text-zinc-600 focus:border-amber-500"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300"
                tabIndex={-1}
              >
                {showPassword ? (
                  <EyeOff className="h-4 w-4" />
                ) : (
                  <Eye className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>

          {error && (
            <p className="rounded-md border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-300">
              {error}
            </p>
          )}

          <Button
            type="submit"
            disabled={loading}
            className="w-full bg-amber-500 font-semibold text-black hover:bg-amber-400"
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              "Sign in to Admin"
            )}
          </Button>
        </form>

        <p className="mt-6 text-center text-xs text-zinc-600">
          Not an admin?{" "}
          <a href="/login" className="text-zinc-400 hover:text-white underline underline-offset-2">
            Regular login
          </a>
        </p>
      </div>

      <p className="mt-8 text-xs text-zinc-700">
        All admin actions are logged and audited.
      </p>
    </div>
  );
}
