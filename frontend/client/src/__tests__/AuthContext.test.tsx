/**
 * Tests for the AuthContext provider and useAuth hook.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";

// Mock the API functions
vi.mock("@/lib/api", () => ({
  getStoredUser: vi.fn(),
  getStoredToken: vi.fn(),
  login: vi.fn(),
  signup: vi.fn(),
  logout: vi.fn(),
  refreshToken: vi.fn(),
  storeAuth: vi.fn(),
  clearAuth: vi.fn(),
  loginAsDemo: vi.fn(),
  isDemoLoginEnabled: vi.fn(() => false),
}));

// Test component that uses the auth context
function TestComponent() {
  const { user, isAuthenticated, isLoading, login, logout } = useAuth();

  if (isLoading) {
    return <div>Loading...</div>;
  }

  return (
    <div>
      <div data-testid="auth-status">
        {isAuthenticated ? "Authenticated" : "Not Authenticated"}
      </div>
      {user && <div data-testid="user-email">{user.email}</div>}
      <button onClick={() => login({ email: "test@example.com", password: "password" })}>
        Login
      </button>
      <button onClick={logout}>Logout</button>
    </div>
  );
}

describe("AuthContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  describe("AuthProvider", () => {
    it("should render children", async () => {
      const { getStoredToken, getStoredUser, refreshToken } = await import("@/lib/api");
      (getStoredToken as any).mockReturnValue(null);
      (getStoredUser as any).mockReturnValue(null);
      (refreshToken as any).mockResolvedValue(null);

      render(
        <AuthProvider>
          <div>Test Child</div>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByText("Test Child")).toBeInTheDocument();
      });
    });

    it("should show loading state initially", async () => {
      const { getStoredToken, refreshToken } = await import("@/lib/api");
      (getStoredToken as any).mockReturnValue("token");
      (refreshToken as any).mockImplementation(() => new Promise(() => {})); // Never resolves

      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>
      );

      expect(screen.getByText("Loading...")).toBeInTheDocument();
    });

    it("should show not authenticated when no token", async () => {
      const { getStoredToken, getStoredUser, refreshToken } = await import("@/lib/api");
      (getStoredToken as any).mockReturnValue(null);
      (getStoredUser as any).mockReturnValue(null);
      (refreshToken as any).mockResolvedValue(null);

      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("auth-status")).toHaveTextContent("Not Authenticated");
      });
    });

    it("should restore user from stored data", async () => {
      const mockUser = {
        id: 1,
        email: "stored@example.com",
        name: "Stored User",
        plan: "free",
        avatar_url: null,
      };

      const { getStoredToken, getStoredUser, refreshToken } = await import("@/lib/api");
      (getStoredToken as any).mockReturnValue("stored_token");
      (getStoredUser as any).mockReturnValue(mockUser);
      (refreshToken as any).mockResolvedValue({
        user: mockUser,
        access_token: "new_token",
        refresh_token: "new_refresh",
      });

      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("auth-status")).toHaveTextContent("Authenticated");
        expect(screen.getByTestId("user-email")).toHaveTextContent("stored@example.com");
      });
    });
  });

  describe("useAuth hook", () => {
    it("should throw error when used outside provider", () => {
      // Suppress console.error for this test
      const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

      expect(() => {
        render(<TestComponent />);
      }).toThrow("useAuth must be used within an AuthProvider");

      consoleSpy.mockRestore();
    });

    it("should handle login", async () => {
      const mockUser = {
        id: 1,
        email: "test@example.com",
        name: "Test User",
        plan: "free",
        avatar_url: null,
      };

      const { getStoredToken, getStoredUser, refreshToken, login } = await import("@/lib/api");
      (getStoredToken as any).mockReturnValue(null);
      (getStoredUser as any).mockReturnValue(null);
      (refreshToken as any).mockResolvedValue(null);
      (login as any).mockResolvedValue({
        user: mockUser,
        access_token: "access_token",
        refresh_token: "refresh_token",
      });

      const user = userEvent.setup();

      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("auth-status")).toHaveTextContent("Not Authenticated");
      });

      await user.click(screen.getByText("Login"));

      await waitFor(() => {
        expect(screen.getByTestId("auth-status")).toHaveTextContent("Authenticated");
        expect(screen.getByTestId("user-email")).toHaveTextContent("test@example.com");
      });
    });

    it("should handle logout", async () => {
      const mockUser = {
        id: 1,
        email: "test@example.com",
        name: "Test User",
        plan: "free",
        avatar_url: null,
      };

      const { getStoredToken, getStoredUser, refreshToken, logout } = await import("@/lib/api");
      (getStoredToken as any).mockReturnValue("token");
      (getStoredUser as any).mockReturnValue(mockUser);
      (refreshToken as any).mockResolvedValue({
        user: mockUser,
        access_token: "token",
        refresh_token: "refresh",
      });
      (logout as any).mockImplementation(() => {});

      const user = userEvent.setup();

      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId("auth-status")).toHaveTextContent("Authenticated");
      });

      await user.click(screen.getByText("Logout"));

      await waitFor(() => {
        expect(screen.getByTestId("auth-status")).toHaveTextContent("Not Authenticated");
      });
    });
  });
});
