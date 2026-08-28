import { Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AppShell } from "./components/AppShell";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";

function TodayWelcome() {
  return (
    <section className="today-welcome" aria-labelledby="today-title">
      <p className="eyebrow">Your learning day</p>
      <h1 id="today-title">Today</h1>
      <div className="welcome-card">
        <p className="section-label">Next step</p>
        <h2>Your protected study plan is ready.</h2>
        <p>The next workspace screen will place one clear Continue action here.</p>
      </div>
    </section>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell activeRole={null} />}>
          <Route index element={<TodayWelcome />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
