import { useEffect, useState } from "react";
import { ApiError, request, type Dashboard } from "./api";
import { useAuth } from "./auth";

export function DashboardPage() {
  const { state, signOut } = useAuth();
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    let active = true;
    request<Dashboard>("/api/dashboard")
      .then((data) => {
        if (active) setDashboard(data);
      })
      .catch((requestError: unknown) => {
        if (active) {
          setError(
            requestError instanceof ApiError
              ? requestError.message
              : "Unable to load your workspace.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleSignOut() {
    setSigningOut(true);
    setError("");
    try {
      await signOut();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to sign out. Please try again.",
      );
      setSigningOut(false);
    }
  }

  if (state.status !== "authenticated") return null;

  return (
    <main className="dashboard-layout">
      <header className="dashboard-header">
        <a className="wordmark" href="/">
          <span className="brand-mark brand-mark-small" aria-hidden="true">
            MI
          </span>
          Marketing Intelligence Copilot
        </a>
        <button
          className="button button-secondary"
          onClick={() => void handleSignOut()}
          disabled={signingOut}
        >
          {signingOut ? "Signing out…" : "Sign out"}
        </button>
      </header>
      <section className="welcome-panel">
        <p className="eyebrow">YOUR WORKSPACE</p>
        <h1>Welcome back</h1>
        <p className="subtitle">Signed in as {state.user.email}</p>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        {dashboard ? (
          <p className="success-message">{dashboard.message}</p>
        ) : !error ? (
          <p className="status-message">Loading your workspace…</p>
        ) : null}
      </section>
    </main>
  );
}
