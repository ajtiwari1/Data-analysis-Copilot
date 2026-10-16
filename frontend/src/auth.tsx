import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError, request, type User } from "./api";

type AuthState =
  | { status: "loading"; user: null; error: null }
  | { status: "anonymous"; user: null; error: null }
  | { status: "authenticated"; user: User; error: null }
  | { status: "error"; user: null; error: string };

interface AuthContextValue {
  state: AuthState;
  signIn: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    status: "loading",
    user: null,
    error: null,
  });

  const refresh = useCallback(async () => {
    setState({ status: "loading", user: null, error: null });
    try {
      const user = await request<User>("/api/auth/me");
      setState({ status: "authenticated", user, error: null });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setState({ status: "anonymous", user: null, error: null });
        return;
      }
      setState({
        status: "error",
        user: null,
        error:
          error instanceof Error
            ? error.message
            : "Unable to restore your session.",
      });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(async (email: string, password: string) => {
    const user = await request<User>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setState({ status: "authenticated", user, error: null });
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    const user = await request<User>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setState({ status: "authenticated", user, error: null });
  }, []);

  const signOut = useCallback(async () => {
    await request<void>("/api/auth/logout", { method: "POST" });
    setState({ status: "anonymous", user: null, error: null });
  }, []);

  const value = useMemo(
    () => ({ state, signIn, register, signOut, refresh }),
    [state, signIn, register, signOut, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return value;
}
