import { useState, useEffect, useCallback } from "react";
import { Link } from "wouter";
import {
  ArrowLeft,
  Zap,
  CheckCircle2,
  AlertCircle,
  Clock,
  RefreshCw,
  Database,
  Server,
  Cpu,
  Radio,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SEOHead, StructuredData } from "@/components/seo";
import api from "@/lib/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  database: "connected" | "disconnected";
  redis: "connected" | "disconnected";
  model_loaded: boolean;
  velocity_models_loaded: boolean;
  environment: string;
}

type ServiceStatus = "operational" | "degraded" | "outage";

interface ServiceRow {
  name: string;
  icon: typeof Server;
  status: ServiceStatus;
  detail?: string;
}

// ── Constants ────────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 30_000;

const statusConfig = {
  operational: {
    icon: CheckCircle2,
    label: "Operational",
    className: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    dotColor: "bg-emerald-400",
  },
  degraded: {
    icon: AlertCircle,
    label: "Degraded",
    className: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    dotColor: "bg-amber-400",
  },
  outage: {
    icon: AlertCircle,
    label: "Outage",
    className: "bg-red-500/10 text-red-400 border-red-500/20",
    dotColor: "bg-red-400",
  },
};

// Map /health response to individual service rows shown to the user.
function buildServiceRows(h: HealthResponse): ServiceRow[] {
  return [
    {
      name: "API",
      icon: Server,
      status: h.status === "unhealthy" ? "outage" : h.status === "degraded" ? "degraded" : "operational",
      detail: h.environment !== "production" ? h.environment : undefined,
    },
    {
      name: "Database",
      icon: Database,
      status: h.database === "connected" ? "operational" : "outage",
    },
    {
      name: "Cache / Queue (Redis)",
      icon: Radio,
      status: h.redis === "connected" ? "operational" : "degraded",
    },
    {
      name: "ML Prediction Model",
      icon: Cpu,
      status: h.model_loaded ? "operational" : "degraded",
      detail: h.model_loaded ? undefined : "Model file not found — analysis scoring unavailable",
    },
    {
      name: "Velocity Models",
      icon: Cpu,
      status: h.velocity_models_loaded ? "operational" : "degraded",
      detail: h.velocity_models_loaded ? undefined : "Velocity index not found — projections use estimates",
    },
  ];
}

const PAST_INCIDENTS = [
  {
    date: "February 18, 2026",
    title: "Elevated API Latency",
    status: "resolved" as const,
    description:
      "Some users experienced slower than normal API response times. Issue was identified and resolved within 45 minutes.",
  },
  {
    date: "February 10, 2026",
    title: "Scheduled Maintenance",
    status: "completed" as const,
    description:
      "Database migration completed successfully. No service interruption occurred.",
  },
];

// ── Component ────────────────────────────────────────────────────────────────

export default function Status() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchHealth = useCallback(async () => {
    try {
      const response = await api.get<HealthResponse>("/health");
      setHealth(response.data);
      setLastUpdated(new Date());
      setError(null);
    } catch (err: any) {
      // If we get a 503, the response body still contains health data
      if (err?.response?.data) {
        setHealth(err.response.data as HealthResponse);
        setLastUpdated(new Date());
        setError(null);
      } else {
        setError("Unable to reach the API. The service may be down.");
        // Keep stale data if we have it
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch + polling every 30 s
  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [fetchHealth]);

  const services: ServiceRow[] = health ? buildServiceRows(health) : [];
  const allOperational = services.length > 0 && services.every((s) => s.status === "operational");
  const anyOutage = services.some((s) => s.status === "outage");

  const overallStatus = error
    ? "unreachable"
    : anyOutage
      ? "outage"
      : !allOperational
        ? "degraded"
        : "operational";

  return (
    <>
      <SEOHead
        title="System Status"
        description="Live status of ViewMagnet's API, dashboard, analysis pipeline, render queue, and integration endpoints. Updated every 30 seconds."
        canonicalUrl="/status"
      />
      <StructuredData
        type="breadcrumb"
        items={[
          { name: "Home", url: "/" },
          { name: "Status", url: "/status" },
        ]}
      />
      <div className="min-h-screen bg-gradient-to-b from-deep-charcoal to-gunmetal">
        <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-lg">
          <div className="container mx-auto px-4 h-16 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-glow to-amber-glow flex items-center justify-center">
                <Zap className="w-4 h-4 text-deep-charcoal" strokeWidth={2.5} />
              </div>
              <span className="text-lg font-bold">
                View<span className="text-cyan-glow">Magnet</span>
              </span>
            </Link>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/">
                <ArrowLeft className="w-4 h-4 mr-2" />
                Back to Home
              </Link>
            </Button>
          </div>
        </header>

        <main className="container mx-auto px-4 py-16 max-w-3xl">
          <div className="text-center mb-12">
            <h1 className="text-4xl font-bold mb-4">System Status</h1>
            <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
              Live status of ViewMagnet services — updated every 30 seconds.
            </p>
          </div>

          {/* ── Overall banner ──────────────────────────────────────────────── */}
          <Card
            className={`mb-8 ${
              overallStatus === "operational"
                ? "bg-emerald-500/5 border-emerald-500/20"
                : overallStatus === "unreachable"
                  ? "bg-red-500/5 border-red-500/20"
                  : "bg-amber-500/5 border-amber-500/20"
            }`}
          >
            <CardContent className="p-6">
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  {loading ? (
                    <RefreshCw className="w-8 h-8 text-muted-foreground animate-spin" />
                  ) : overallStatus === "operational" ? (
                    <CheckCircle2 className="w-8 h-8 text-emerald-400" />
                  ) : (
                    <AlertCircle
                      className={`w-8 h-8 ${overallStatus === "unreachable" ? "text-red-400" : "text-amber-400"}`}
                    />
                  )}
                  <div>
                    {loading ? (
                      <h2 className="text-xl font-semibold text-muted-foreground">Checking…</h2>
                    ) : overallStatus === "operational" ? (
                      <h2 className="text-xl font-semibold text-emerald-400">All Systems Operational</h2>
                    ) : overallStatus === "unreachable" ? (
                      <h2 className="text-xl font-semibold text-red-400">API Unreachable</h2>
                    ) : overallStatus === "outage" ? (
                      <h2 className="text-xl font-semibold text-red-400">Service Outage Detected</h2>
                    ) : (
                      <h2 className="text-xl font-semibold text-amber-400">Some Services Degraded</h2>
                    )}
                    {lastUpdated && (
                      <p className="text-sm text-muted-foreground">
                        Last updated: {lastUpdated.toLocaleTimeString()}
                      </p>
                    )}
                    {error && (
                      <p className="text-sm text-red-400 mt-1">{error}</p>
                    )}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={fetchHealth}
                  disabled={loading}
                  className="text-muted-foreground hover:text-white flex-shrink-0"
                >
                  <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? "animate-spin" : ""}`} />
                  Refresh
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* ── Service rows ────────────────────────────────────────────────── */}
          <Card className="bg-card/50 border-border/50 mb-8">
            <CardHeader>
              <CardTitle>Services</CardTitle>
            </CardHeader>
            <CardContent>
              {loading && !health ? (
                <div className="space-y-4">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="flex items-center justify-between py-2 border-b border-border/30 last:border-0 animate-pulse">
                      <div className="h-4 w-40 bg-muted/30 rounded" />
                      <div className="h-6 w-24 bg-muted/20 rounded-full" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-4">
                  {services.map((service) => {
                    const config = statusConfig[service.status];
                    const Icon = service.icon;
                    return (
                      <div
                        key={service.name}
                        className="flex items-center justify-between py-2 border-b border-border/30 last:border-0"
                      >
                        <div className="flex items-center gap-3">
                          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${config.dotColor}`} />
                          <Icon className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                          <div>
                            <span className="text-sm">{service.name}</span>
                            {service.detail && (
                              <p className="text-xs text-muted-foreground">{service.detail}</p>
                            )}
                          </div>
                        </div>
                        <Badge variant="outline" className={config.className}>
                          {config.label}
                        </Badge>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* ── Past incidents ──────────────────────────────────────────────── */}
          <Card className="bg-card/50 border-border/50">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="w-5 h-5 text-muted-foreground" />
                Recent Incidents
              </CardTitle>
            </CardHeader>
            <CardContent>
              {PAST_INCIDENTS.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  No incidents reported in the last 30 days.
                </p>
              ) : (
                <div className="space-y-6">
                  {PAST_INCIDENTS.map((incident, index) => (
                    <div key={index} className="border-l-2 border-border/50 pl-4">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs text-muted-foreground">{incident.date}</span>
                        <Badge
                          variant="outline"
                          className={
                            incident.status === "resolved"
                              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                              : "bg-blue-500/10 text-blue-400 border-blue-500/20"
                          }
                        >
                          {incident.status}
                        </Badge>
                      </div>
                      <h3 className="font-medium mb-1">{incident.title}</h3>
                      <p className="text-sm text-muted-foreground">{incident.description}</p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </main>
      </div>
    </>
  );
}
