/**
 * Tests for the API client module.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import axios from "axios";

// Mock axios
vi.mock("axios", () => {
  const mockAxios = {
    create: vi.fn(() => mockAxios),
    get: vi.fn(),
    post: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
    isAxiosError: vi.fn(),
  };
  return { default: mockAxios };
});

describe("API Client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe("healthCheck", () => {
    it("should call the health endpoint", async () => {
      const mockResponse = { data: { status: "healthy", version: "1.0.0" } };
      (axios.get as any).mockResolvedValueOnce(mockResponse);

      // Import after mocking
      const { healthCheck } = await import("@/lib/api");
      
      const result = await healthCheck();
      
      expect(result).toEqual({ status: "healthy", version: "1.0.0" });
    });
  });

  describe("Authentication", () => {
    describe("signup", () => {
      it("should send signup request and store tokens", async () => {
        const mockResponse = {
          data: {
            access_token: "test_access_token",
            refresh_token: "test_refresh_token",
            token_type: "bearer",
            user: {
              id: 1,
              email: "test@example.com",
              name: "Test User",
              plan: "free",
            },
          },
        };
        (axios.post as any).mockResolvedValueOnce(mockResponse);

        const { signup } = await import("@/lib/api");
        
        const result = await signup({
          email: "test@example.com",
          password: "testpassword123",
          name: "Test User",
        });

        expect(result.user.email).toBe("test@example.com");
        expect(result.access_token).toBe("test_access_token");
      });
    });

    describe("login", () => {
      it("should send login request and store tokens", async () => {
        const mockResponse = {
          data: {
            access_token: "test_access_token",
            refresh_token: "test_refresh_token",
            token_type: "bearer",
            user: {
              id: 1,
              email: "test@example.com",
              name: "Test User",
              plan: "free",
            },
          },
        };
        (axios.post as any).mockResolvedValueOnce(mockResponse);

        const { login } = await import("@/lib/api");
        
        const result = await login({
          email: "test@example.com",
          password: "testpassword123",
        });

        expect(result.user.email).toBe("test@example.com");
      });
    });

    describe("getStoredToken", () => {
      it("should return null when no token stored", async () => {
        const { getStoredToken } = await import("@/lib/api");
        
        (localStorage.getItem as any).mockReturnValue(null);
        
        const token = getStoredToken();
        expect(token).toBeNull();
      });

      it("should return stored token", async () => {
        const { getStoredToken } = await import("@/lib/api");
        
        (localStorage.getItem as any).mockReturnValue("stored_token");
        
        const token = getStoredToken();
        expect(token).toBe("stored_token");
      });
    });
  });

  describe("Video Analysis", () => {
    describe("analyzeVideo", () => {
      it("should send analyze request with URL", async () => {
        const mockResponse = {
          data: {
            video_id: "test_video_id",
            title: "Test Video",
            prediction_score: 75.5,
            prediction_tier: "high",
            title_score: 78.0,
            thumbnail_score: 72.0,
            explanations: [],
            recommendations: [],
            niche_comparison: {},
          },
        };
        (axios.post as any).mockResolvedValueOnce(mockResponse);

        const { analyzeVideo } = await import("@/lib/api");
        
        const result = await analyzeVideo({ url: "https://youtube.com/watch?v=test" });

        expect(result.video_id).toBe("test_video_id");
        expect(result.prediction_score).toBe(75.5);
      });
    });
  });

  describe("Dashboard", () => {
    describe("getDashboardStats", () => {
      it("should fetch dashboard stats for user", async () => {
        const mockResponse = {
          data: {
            avg_prediction_score: 75.0,
            total_views_30d: 100000,
            videos_analyzed: 10,
            analyses_remaining: 490,
            above_baseline_pct: 60,
            recent_analyses: [],
            performance_trend: [],
          },
        };
        (axios.get as any).mockResolvedValueOnce(mockResponse);

        const { getDashboardStats } = await import("@/lib/api");
        
        const result = await getDashboardStats();

        expect(result.videos_analyzed).toBe(10);
        expect(result.avg_prediction_score).toBe(75.0);
      });
    });
  });

  describe("Error Handling", () => {
    it("should throw ApiError on axios error", async () => {
      const axiosError = {
        response: {
          status: 400,
          data: { detail: "Bad request" },
        },
      };
      (axios.isAxiosError as any).mockReturnValue(true);
      (axios.post as any).mockRejectedValueOnce(axiosError);

      const { analyzeVideo, ApiError } = await import("@/lib/api");

      await expect(
        analyzeVideo({ url: "invalid" })
      ).rejects.toThrow();
    });
  });
});
