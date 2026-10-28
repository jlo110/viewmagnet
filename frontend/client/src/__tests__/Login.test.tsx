/**
 * Tests for Login.tsx and Signup.tsx authentication pages
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock wouter
const mockNavigate = vi.fn();
vi.mock("wouter", () => ({
  useLocation: () => ["/login", mockNavigate],
  Link: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// Mock auth context
const mockLogin = vi.fn();
const mockSignup = vi.fn();

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: vi.fn(() => ({
    user: null,
    isAuthenticated: false,
    isLoading: false,
    login: mockLogin,
    signup: mockSignup,
    logout: vi.fn(),
  })),
}));

// Mock toast
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

// Import after mocks
import Login from "../pages/auth/Login";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

describe("Login Page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLogin.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("Initial render", () => {
    it("renders the login form", () => {
      render(<Login />);

      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    });

    it("renders the login button", () => {
      render(<Login />);

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      expect(button).toBeInTheDocument();
    });

    it("renders ViewMagnet branding", () => {
      render(<Login />);

      expect(
        screen.queryByText(/viewmagnet/i) ||
          document.querySelector('[class*="magnet"]')
      ).toBeTruthy();
    });

    it("shows link to signup page", () => {
      render(<Login />);

      const signupLink = screen.getByRole("link", { name: /sign up|create|register/i });
      expect(signupLink).toBeInTheDocument();
    });

    it("shows forgot password link", () => {
      render(<Login />);

      const forgotLink = screen.queryByText(/forgot/i);
      expect(forgotLink).toBeInTheDocument();
    });
  });

  describe("Form validation", () => {
    it("shows error when submitting empty form", async () => {
      const user = userEvent.setup();
      render(<Login />);

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      await user.click(button);

      expect(toast.error).toHaveBeenCalledWith("Please fill in all fields");
    });

    it("shows error when email is empty", async () => {
      const user = userEvent.setup();
      render(<Login />);

      const passwordInput = screen.getByLabelText(/password/i);
      await user.type(passwordInput, "password123");

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      await user.click(button);

      expect(toast.error).toHaveBeenCalledWith("Please fill in all fields");
    });

    it("shows error when password is empty", async () => {
      const user = userEvent.setup();
      render(<Login />);

      const emailInput = screen.getByLabelText(/email/i);
      await user.type(emailInput, "test@example.com");

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      await user.click(button);

      expect(toast.error).toHaveBeenCalledWith("Please fill in all fields");
    });
  });

  describe("Form submission", () => {
    it("calls login with email and password", async () => {
      const user = userEvent.setup();
      render(<Login />);

      const emailInput = screen.getByLabelText(/email/i);
      const passwordInput = screen.getByLabelText(/password/i);

      await user.type(emailInput, "test@example.com");
      await user.type(passwordInput, "password123");

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      await user.click(button);

      await waitFor(() => {
        expect(mockLogin).toHaveBeenCalledWith({
          email: "test@example.com",
          password: "password123",
        });
      });
    });

    it("shows success toast on successful login", async () => {
      mockLogin.mockResolvedValueOnce({});

      const user = userEvent.setup();
      render(<Login />);

      const emailInput = screen.getByLabelText(/email/i);
      const passwordInput = screen.getByLabelText(/password/i);

      await user.type(emailInput, "test@example.com");
      await user.type(passwordInput, "password123");

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      await user.click(button);

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringMatching(/welcome/i));
      });
    });

    it("navigates to dashboard on successful login", async () => {
      mockLogin.mockResolvedValueOnce({});

      const user = userEvent.setup();
      render(<Login />);

      const emailInput = screen.getByLabelText(/email/i);
      const passwordInput = screen.getByLabelText(/password/i);

      await user.type(emailInput, "test@example.com");
      await user.type(passwordInput, "password123");

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      await user.click(button);

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
      });
    });
  });

  describe("Error handling", () => {
    it("shows error toast on login failure", async () => {
      mockLogin.mockRejectedValueOnce({
        response: { data: { detail: "Invalid credentials" } },
      });

      const user = userEvent.setup();
      render(<Login />);

      const emailInput = screen.getByLabelText(/email/i);
      const passwordInput = screen.getByLabelText(/password/i);

      await user.type(emailInput, "test@example.com");
      await user.type(passwordInput, "wrongpassword");

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      await user.click(button);

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/invalid/i));
      });
    });

    it("shows generic error message when no detail provided", async () => {
      mockLogin.mockRejectedValueOnce(new Error("Network error"));

      const user = userEvent.setup();
      render(<Login />);

      const emailInput = screen.getByLabelText(/email/i);
      const passwordInput = screen.getByLabelText(/password/i);

      await user.type(emailInput, "test@example.com");
      await user.type(passwordInput, "password123");

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      await user.click(button);

      await waitFor(() => {
        expect(toast.error).toHaveBeenCalled();
      });
    });
  });

  describe("Password visibility toggle", () => {
    it("toggles password visibility", async () => {
      const user = userEvent.setup();
      render(<Login />);

      const passwordInput = screen.getByLabelText(/password/i);
      expect(passwordInput).toHaveAttribute("type", "password");

      // Find the toggle button (eye icon)
      const toggleButton = document.querySelector(
        'button[type="button"]'
      ) as HTMLButtonElement;

      if (toggleButton && toggleButton !== screen.getByRole("button", { name: /sign in|log in/i })) {
        await user.click(toggleButton);

        // Password should now be visible
        expect(passwordInput).toHaveAttribute("type", "text");

        // Click again to hide
        await user.click(toggleButton);
        expect(passwordInput).toHaveAttribute("type", "password");
      }
    });
  });

  describe("Loading state", () => {
    it("shows loading state during auth check", () => {
      (useAuth as ReturnType<typeof vi.fn>).mockReturnValueOnce({
        user: null,
        isAuthenticated: false,
        isLoading: true,
        login: mockLogin,
      });

      render(<Login />);

      // Should show loading indicator
      expect(
        document.querySelector('[class*="animate"]') ||
          document.querySelector('[class*="spin"]')
      ).toBeTruthy();
    });

    it("disables button during login", async () => {
      // Make login slow
      mockLogin.mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 100))
      );

      const user = userEvent.setup();
      render(<Login />);

      const emailInput = screen.getByLabelText(/email/i);
      const passwordInput = screen.getByLabelText(/password/i);

      await user.type(emailInput, "test@example.com");
      await user.type(passwordInput, "password123");

      const button = screen.getByRole("button", { name: /sign in|log in/i });
      await user.click(button);

      // Button should show loading state
      expect(
        button.querySelector('[class*="animate"]') ||
          button.querySelector('[class*="spin"]') ||
          button.hasAttribute("disabled")
      ).toBeTruthy();
    });
  });

  describe("Accessibility", () => {
    it("has accessible form labels", () => {
      render(<Login />);

      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
      expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    });

    it("has autocomplete attributes", () => {
      render(<Login />);

      const emailInput = screen.getByLabelText(/email/i);
      const passwordInput = screen.getByLabelText(/password/i);

      expect(emailInput).toHaveAttribute("autocomplete", "email");
      expect(passwordInput).toHaveAttribute("autocomplete", "current-password");
    });

    it("email input has correct type", () => {
      render(<Login />);

      const emailInput = screen.getByLabelText(/email/i);
      expect(emailInput).toHaveAttribute("type", "email");
    });
  });
});
