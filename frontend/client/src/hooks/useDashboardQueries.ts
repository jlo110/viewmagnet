/**
 * TanStack Query hooks for dashboard data.
 *
 * These wrappers replace ad-hoc useEffect+useState data fetching with cached,
 * deduplicated queries. Pages that adopt these hooks get free background
 * refetch, request deduplication, and a consistent loading/error model.
 */
import { useQuery } from "@tanstack/react-query";
import {
  getDashboardStats,
  getYouTubeConnections,
  getAlertSummary,
  getAlerts,
  getAnalysisHistory,
  type UserDashboardStats,
  type YouTubeConnection,
  type AlertSummary,
  type Alert as AlertItem,
  type AnalysisHistoryResponse,
} from "@/lib/api";

const KEYS = {
  dashboardStats: ["dashboard-stats"] as const,
  youtubeConnections: ["youtube-connections"] as const,
  alertSummary: (channelId: string | undefined) => ["alert-summary", channelId] as const,
  alerts: (channelId: string | undefined) => ["alerts", channelId] as const,
  analysisHistory: (limit: number) => ["analysis-history", limit] as const,
};

export function useDashboardStats(enabled = true) {
  return useQuery<UserDashboardStats>({
    queryKey: KEYS.dashboardStats,
    queryFn: getDashboardStats,
    enabled,
  });
}

export function useYouTubeConnections(enabled = true) {
  return useQuery<{ connections: YouTubeConnection[] }>({
    queryKey: KEYS.youtubeConnections,
    queryFn: getYouTubeConnections,
    enabled,
  });
}

export function useAlertSummary(channelId: string | undefined) {
  return useQuery<AlertSummary>({
    queryKey: KEYS.alertSummary(channelId),
    queryFn: () => getAlertSummary(channelId!),
    enabled: !!channelId,
  });
}

export function useAlerts(channelId: string | undefined) {
  return useQuery<AlertItem[]>({
    queryKey: KEYS.alerts(channelId),
    queryFn: () => getAlerts(channelId!),
    enabled: !!channelId,
  });
}

export function useAnalysisHistory(limit = 20, enabled = true) {
  return useQuery<AnalysisHistoryResponse>({
    queryKey: KEYS.analysisHistory(limit),
    queryFn: () => getAnalysisHistory(limit),
    enabled,
  });
}

export const QUERY_KEYS = KEYS;
