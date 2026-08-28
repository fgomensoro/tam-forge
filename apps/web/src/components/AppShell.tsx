import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { ActiveRoleBadge } from "./ActiveRoleBadge";

export function AppShell({ activeRole = null }: { activeRole?: string | null }) {
  const auth = useAuth();

  return (
    <div className="workspace-shell">
      <header className="workspace-header">
        <a className="brand" href="/" aria-label="TAM Forge home">
          <span className="brand-mark" aria-hidden="true">TF</span>
          <span>
            <strong>TAM Forge</strong>
            <small>Private learning workspace</small>
          </span>
        </a>
        <div className="session-tools">
          <ActiveRoleBadge role={activeRole} />
          <span className="owner-name">@{auth.session?.github_login}</span>
          <button className="text-button" type="button" onClick={() => void auth.logout()}>
            Log out
          </button>
        </div>
      </header>

      <nav className="primary-nav" aria-label="Primary">
        <NavLink to="/" end>Today</NavLink>
        <NavLink to="/roadmaps">Roadmaps</NavLink>
      </nav>

      <main className="workspace-main" id="main-content">
        <Outlet />
      </main>
    </div>
  );
}
