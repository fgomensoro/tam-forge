import { Navigate, useLocation, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";

const callbackMessages: Record<string, string> = {
  identity_provider_error: "GitHub sign-in is temporarily unavailable. Please try again.",
  forbidden_identity: "This workspace is restricted to its owner.",
  invalid_oauth_state: "That sign-in attempt expired. Please start again.",
  auth_unavailable: "Sign-in is temporarily unavailable. Please try again.",
};

export function LoginPage() {
  const auth = useAuth();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const callbackError = searchParams.get("auth_error");
  const errorMessage = callbackError
    ? callbackMessages[callbackError] ?? "Sign-in could not be completed. Please try again."
    : auth.error;

  if (auth.status === "loading") {
    return (
      <main className="centered-page" aria-live="polite">
        <p className="eyebrow">Private study workspace</p>
        <p className="loading-copy">Checking your session…</p>
      </main>
    );
  }

  if (auth.status === "authenticated") {
    const state = location.state as { from?: string } | null;
    return <Navigate to={state?.from ?? "/"} replace />;
  }

  return (
    <main className="login-page">
      <section className="login-intro" aria-labelledby="login-title">
        <p className="eyebrow">Private study workspace</p>
        <h1 id="login-title">Practice with purpose.</h1>
        <p className="intro-copy">
          One calm place for your TAM roadmap, independent attempts, evidence, and the two corrections that matter next.
        </p>
      </section>

      <section className="login-card" aria-label="Sign in">
        <div className="card-number" aria-hidden="true">01</div>
        <h2>Welcome to TAM Forge</h2>
        <p>Sign in with your approved GitHub account. Your workspace is private and belongs only to you.</p>
        {errorMessage ? <p className="error-message" role="alert">{errorMessage}</p> : null}
        <a className="primary-action" href="/api/v1/auth/login">Continue with GitHub</a>
        <p className="privacy-note">No login tokens are saved in your browser storage.</p>
      </section>
    </main>
  );
}
