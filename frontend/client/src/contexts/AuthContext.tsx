import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import {
  User,
  getStoredUser,
  getStoredToken,
  login as apiLogin,
  signup as apiSignup,
  logout as apiLogout,
  refreshToken,
  loginAsDemo as apiLoginAsDemo,
  isDemoLoginEnabled,
  LoginRequest,
  SignupRequest,
  AuthResponse,
} from "@/lib/api";

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  demoLoginEnabled: boolean;
  login: (data: LoginRequest) => Promise<AuthResponse>;
  signup: (data: SignupRequest) => Promise<AuthResponse>;
  loginAsDemo: () => Promise<AuthResponse>;
  logout: () => void;
  refreshAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refreshAuth = useCallback(async () => {
    const token = getStoredToken();
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }

    const storedUser = getStoredUser();
    if (storedUser) {
      setUser(storedUser);
    }

    try {
      const result = await refreshToken();
      if (result) {
        setUser(result.user);
      } else {
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshAuth();
  }, [refreshAuth]);

  const login = async (data: LoginRequest): Promise<AuthResponse> => {
    const response = await apiLogin(data);
    setUser(response.user);
    return response;
  };

  const signup = async (data: SignupRequest): Promise<AuthResponse> => {
    const response = await apiSignup(data);
    setUser(response.user);
    return response;
  };

  const loginAsDemo = async (): Promise<AuthResponse> => {
    const response = await apiLoginAsDemo();
    setUser(response.user);
    return response;
  };

  const logout = () => {
    apiLogout();
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        demoLoginEnabled: isDemoLoginEnabled(),
        login,
        signup,
        loginAsDemo,
        logout,
        refreshAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
