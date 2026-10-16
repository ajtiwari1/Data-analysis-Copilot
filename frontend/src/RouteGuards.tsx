import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "./auth";

function SessionStatus() {
  const { state, refresh } = useAuth();

  if (state.status === "loading") {
    return <p className="status-message">Restoring your session…</p>;
  }
  if (state.status === "error") {
    return (
      <section className="status-message" role="alert">
        <p>{state.error}</p>
        <button className="button button-secondary" onClick={() => void refresh()}>
          Try again
        </button>
      </section>
    );
  }
  return null;
}

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const location = useLocation();

  if (state.status === "loading" || state.status === "error") {
    return <SessionStatus />;
  }
  if (state.status === "anonymous") {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return children;
}

export function GuestRoute({ children }: { children: ReactNode }) {
  const { state } = useAuth();

  if (state.status === "loading" || state.status === "error") {
    return <SessionStatus />;
  }
  if (state.status === "authenticated") {
    return <Navigate to="/" replace />;
  }
  return children;
}
