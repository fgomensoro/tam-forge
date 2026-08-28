import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { z } from "zod";
import type { components } from "../api/schema";
import {
  ApiProblemError,
  apiRequest,
  registerUnauthorizedHandler,
  setCsrfToken,
} from "../api/client";

const sessionSchema = z.object({
  github_login: z.string().min(1),
  csrf_token: z.string().min(1),
});

export type AuthSession = components["schemas"]["SessionResponse"];
type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  status: AuthStatus;
  session: AuthSession | null;
  error: string | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [session, setSession] = useState<AuthSession | null>(null);
  const [error, setError] = useState<string | null>(null);

  const markUnauthenticated = () => {
    setCsrfToken(null);
    setSession(null);
    setStatus("unauthenticated");
    queryClient.clear();
  };

  const refresh = async () => {
    setStatus("loading");
    setError(null);
    try {
      const raw = await apiRequest<AuthSession>("/api/v1/auth/session");
      const current = sessionSchema.parse(raw) as AuthSession;
      setCsrfToken(current.csrf_token);
      setSession(current);
      setStatus("authenticated");
    } catch (caught) {
      markUnauthenticated();
      if (!(caught instanceof ApiProblemError && caught.status === 401)) {
        setError("Your private workspace could not be reached. Please try again.");
      }
    }
  };

  const logout = async () => {
    try {
      await apiRequest<void>("/api/v1/auth/logout", { method: "POST" });
    } catch (caught) {
      if (!(caught instanceof ApiProblemError && caught.status === 401)) {
        setError("You were signed out here, but the server could not be reached.");
      }
    } finally {
      markUnauthenticated();
    }
  };

  useEffect(() => {
    void refresh();
    return registerUnauthorizedHandler(markUnauthenticated);
  }, []);

  const value = useMemo(
    () => ({ status, session, error, refresh, logout }),
    [status, session, error],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
