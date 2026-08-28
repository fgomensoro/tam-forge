import { Route, Routes } from "react-router-dom";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { AppShell } from "./components/AppShell";
import { ActivityWorkspacePage } from "./features/activities/ActivityWorkspacePage";
import { EvidenceLedgerPage } from "./features/evidence/EvidenceLedgerPage";
import { RoadmapImportPage } from "./features/roadmaps/RoadmapImportPage";
import { TodayPage } from "./features/today/TodayPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell activeRole={null} />}>
          <Route index element={<TodayPage />} />
          <Route path="activities/:activityId" element={<ActivityWorkspacePage />} />
          <Route path="evidence" element={<EvidenceLedgerPage />} />
          <Route path="roadmaps" element={<RoadmapImportPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
