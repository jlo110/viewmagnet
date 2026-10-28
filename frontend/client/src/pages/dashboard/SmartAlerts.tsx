/*
 * Smart Alerts: Underperformance, timing, competitor alerts
 * Design: Signal Flow dark theme
 */
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  AlertTriangle,
  TrendingDown,
  TrendingUp,
  Clock,
  Sword,
  Zap,
  Settings,
  Loader2,
  RefreshCw,
  Youtube,
  Link2,
} from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { 
  getAlerts, 
  dismissAlert, 
  updateAlertSettings, 
  getYouTubeConnections,
  type Alert,
  type YouTubeConnection 
} from "@/lib/api";
import { Link } from "wouter";

const defaultAlertSettings = [
  { name: "Underperformance alerts", description: "When a video drops below baseline", enabled: true },
  { name: "Competitor activity", description: "When tracked competitors publish", enabled: true },
  { name: "Upload timing", description: "Optimal upload window reminders", enabled: true },
  { name: "Trending topics", description: "Rising topics in your niche", enabled: true },
  { name: "Milestone alerts", description: "When videos exceed predictions", enabled: true },
  { name: "Weekly digest", description: "Summary of all alerts via email", enabled: false },
];

const severityConfig = {
  high: { color: "text-destructive", bg: "bg-destructive/10", border: "border-destructive/20", label: "Urgent" },
  medium: { color: "text-amber-glow", bg: "bg-amber-glow/10", border: "border-amber-glow/20", label: "Important" },
  info: { color: "text-cyan-glow", bg: "bg-cyan-glow/10", border: "border-cyan-glow/20", label: "Info" },
  positive: { color: "text-emerald-400", bg: "bg-emerald-400/10", border: "border-emerald-400/20", label: "Good News" },
  low: { color: "text-muted-foreground", bg: "bg-muted/10", border: "border-border/20", label: "Low" },
};

const typeToIcon: Record<string, typeof TrendingDown> = {
  underperformance: TrendingDown,
  competitor: Sword,
  timing: Clock,
  trend: TrendingUp,
  milestone: Zap,
  optimal_time: Clock,
  consistency: AlertTriangle,
};

interface LocalAlert {
  type: string;
  icon: typeof TrendingDown;
  title: string;
  description: string;
  time: string;
  severity: string;
  action: string;
  actionUrl?: string;
  id: string;
  dismissed: boolean;
  data?: Record<string, unknown>;
}

function formatTimeAgo(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  
  if (diffMins < 60) return `${diffMins} minutes ago`;
  if (diffHours < 24) return `${diffHours} hours ago`;
  if (diffDays === 1) return "1 day ago";
  return `${diffDays} days ago`;
}

export default function SmartAlerts() {
  useAuth(); // ensures we redirect on logout; user is resolved server-side from JWT
  const [alertList, setAlertList] = useState<LocalAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState(defaultAlertSettings);
  const [youtubeConnection, setYoutubeConnection] = useState<YouTubeConnection | null>(null);
  const [connectionLoading, setConnectionLoading] = useState(true);

  const channelId = youtubeConnection?.channel_id || "";

  const fetchAlerts = useCallback(async () => {
    if (!channelId) {
      setLoading(false);
      return;
    }
    
    setLoading(true);
    try {
      const apiAlerts = await getAlerts(channelId);
      
      const mappedAlerts: LocalAlert[] = apiAlerts.map(a => ({
        type: a.type,
        icon: typeToIcon[a.type] || AlertTriangle,
        title: a.title,
        description: a.message,
        time: formatTimeAgo(a.created_at),
        severity: a.priority,
        action: a.action,
        actionUrl: a.action_url,
        id: a.id,
        dismissed: a.dismissed,
        data: a.data,
      }));
      
      setAlertList(mappedAlerts.filter(a => !a.dismissed));
      
      if (mappedAlerts.length > 0) {
        toast.success(`Found ${mappedAlerts.length} alerts`);
      }
    } catch (error) {
      console.error("Failed to fetch alerts:", error);
      toast.error("Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }, [channelId]);

  useEffect(() => {
    const loadConnection = async () => {
      setConnectionLoading(true);
      try {
        const savedConnection = localStorage.getItem("youtubeConnection");
        if (savedConnection) {
          const parsed = JSON.parse(savedConnection);
          setYoutubeConnection(parsed);
        } else {
          const { connections } = await getYouTubeConnections();
          if (connections.length > 0) {
            setYoutubeConnection(connections[0]);
            localStorage.setItem("youtubeConnection", JSON.stringify(connections[0]));
          }
        }
      } catch (error) {
        console.error("Failed to load YouTube connection:", error);
      } finally {
        setConnectionLoading(false);
      }
    };
    
    loadConnection();
  }, []);

  useEffect(() => {
    if (channelId) {
      fetchAlerts();
    } else {
      setLoading(false);
    }
  }, [channelId, fetchAlerts]);

  const handleDismiss = async (alertId: string) => {
    try {
      await dismissAlert(alertId);
      setAlertList(prev => prev.filter(a => a.id !== alertId));
      toast.success("Alert dismissed");
    } catch (error) {
      setAlertList(prev => prev.filter(a => a.id !== alertId));
    }
  };

  const handleToggleSetting = async (index: number) => {
    const newSettings = [...settings];
    newSettings[index].enabled = !newSettings[index].enabled;
    setSettings(newSettings);
    
    try {
      await updateAlertSettings({
        underperformance_alerts: newSettings[0].enabled,
        competitor_alerts: newSettings[1].enabled,
        optimal_time_alerts: newSettings[2].enabled,
        trend_alerts: newSettings[3].enabled,
        milestone_alerts: newSettings[4].enabled,
      });
      toast.success("Settings updated");
    } catch (error) {
      console.error("Failed to update settings:", error);
    }
  };

  const handleActionClick = (alert: LocalAlert) => {
    if (alert.actionUrl) {
      window.open(alert.actionUrl, "_blank");
    } else if (alert.data?.video_id) {
      window.open(`https://youtube.com/watch?v=${alert.data.video_id}`, "_blank");
    }
  };

  const unreadCount = alertList.length;

  if (connectionLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-8 h-8 animate-spin text-cyan-glow" />
      </div>
    );
  }

  if (!youtubeConnection) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
            Smart Alerts
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Stay ahead with AI-powered notifications about your channel and competitors.
          </p>
        </div>
        
        <Card className="bg-card border-border/50 border-dashed">
          <CardContent className="p-12 text-center">
            <div className="w-16 h-16 rounded-full bg-cyan-glow/10 flex items-center justify-center mx-auto mb-4">
              <Youtube className="w-8 h-8 text-cyan-glow" />
            </div>
            <h2 className="text-lg font-semibold mb-2">Connect Your Channel</h2>
            <p className="text-sm text-muted-foreground mb-6 max-w-md mx-auto">
              Connect your YouTube channel to receive smart alerts about video performance, 
              optimal posting times, and more.
            </p>
            <Link href="/dashboard">
              <Button className="bg-cyan-glow hover:bg-cyan-glow/90 text-background">
                <Link2 className="w-4 h-4 mr-2" />
                Go to Dashboard to Connect
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
            Smart Alerts
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Monitoring <span className="text-cyan-glow">{youtubeConnection.channel_name}</span> for performance insights.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="text-xs"
            onClick={fetchAlerts}
            disabled={loading}
          >
            {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            <span className="ml-1">Refresh</span>
          </Button>
          {unreadCount > 0 && (
            <Badge variant="destructive" className="text-xs">
              {unreadCount} alert{unreadCount !== 1 ? "s" : ""}
            </Badge>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Alerts List */}
        <div className="lg:col-span-2 space-y-3">
          {loading ? (
            <Card className="bg-card border-border/50">
              <CardContent className="p-8 text-center">
                <Loader2 className="w-8 h-8 animate-spin mx-auto text-cyan-glow mb-3" />
                <p className="text-sm text-muted-foreground">
                  Checking your channel for alerts...
                </p>
              </CardContent>
            </Card>
          ) : alertList.length === 0 ? (
            <Card className="bg-card border-border/50 border-dashed">
              <CardContent className="p-8 text-center">
                <Zap className="w-10 h-10 mx-auto text-emerald-400/50 mb-3" />
                <p className="text-sm font-medium text-foreground mb-1">
                  All Clear!
                </p>
                <p className="text-xs text-muted-foreground">
                  No alerts right now. Your channel is running smoothly.
                </p>
              </CardContent>
            </Card>
          ) : alertList.map((alert, i) => {
            const config = severityConfig[alert.severity as keyof typeof severityConfig] || severityConfig.info;
            const IconComponent = alert.icon || AlertTriangle;
            return (
              <Card key={alert.id} className={`bg-card border-border/50 ${i < 3 ? "border-l-2 " + config.border : ""}`}>
                <CardContent className="p-4">
                  <div className="flex items-start gap-3">
                    <div className={`w-9 h-9 rounded-lg ${config.bg} flex items-center justify-center shrink-0`}>
                      <IconComponent className={`w-4 h-4 ${config.color}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <p className="text-sm font-medium text-foreground">{alert.title}</p>
                        <Badge variant="outline" className={`text-[9px] ${config.border} ${config.color}`}>
                          {config.label}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        {alert.description}
                      </p>
                      <div className="flex items-center gap-3 mt-2">
                        <span className="text-[10px] text-muted-foreground">{alert.time}</span>
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          className="text-[10px] text-cyan-glow hover:text-cyan-glow/80 h-6 px-2"
                          onClick={() => handleActionClick(alert)}
                        >
                          {alert.action} →
                        </Button>
                        <Button 
                          variant="ghost" 
                          size="sm" 
                          className="text-[10px] text-muted-foreground hover:text-foreground h-6 px-2"
                          onClick={() => handleDismiss(alert.id)}
                        >
                          Dismiss
                        </Button>
                      </div>
                    </div>
                    {i < 3 && (
                      <div className="w-2 h-2 rounded-full bg-cyan-glow shrink-0 mt-2" />
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>

        {/* Alert Settings */}
        <Card className="bg-card border-border/50 h-fit">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Settings className="w-4 h-4 text-muted-foreground" />
              Alert Settings
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {settings.map((setting, i) => (
              <div key={i} className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-foreground">{setting.name}</p>
                  <p className="text-[10px] text-muted-foreground">{setting.description}</p>
                </div>
                <Switch 
                  checked={setting.enabled} 
                  onCheckedChange={() => handleToggleSetting(i)}
                />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
