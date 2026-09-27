import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import BuildFreshnessBanner from "./components/BuildFreshnessBanner";
import ErrorBoundary from "./components/ErrorBoundary";
import GlobalJobActivity from "./components/GlobalJobActivity";
import RouteErrorFallback from "./components/RouteErrorFallback";
import ThemeToggle from "./components/ThemeToggle";
import NewRunPage from "./pages/NewRunPage";
import RunBoardPage from "./pages/RunBoardPage";
import SettingsPage from "./pages/SettingsPage";
import StageViewerPage from "./pages/StageViewerPage";
import TopicListPage from "./pages/TopicListPage";
import ProfilesPage from "./pages/ProfilesPage";
import ProfileEditorPage from "./pages/ProfileEditorPage";

export default function App() {
  const location = useLocation();
  return (
    <div className="app-shell">
      <header className="app-rail">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          Education Pipeline
        </Link>
        <nav className="rail-nav" aria-label="Primary">
          <NavLink to="/" end>
            Courses
          </NavLink>
          <NavLink to="/new">New course</NavLink>
          <NavLink to="/profiles" end>
            Profiles
          </NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
        <GlobalJobActivity />
        <div className="rail-footer">
          <p>
            <strong>Stored on this device</strong>
            Courses, profiles, and runs live in your local workspace.
          </p>
          <ThemeToggle />
        </div>
      </header>
      <main className="workspace">
        <BuildFreshnessBanner />
        {/* The rail and banner stay outside, so a page's render error leaves them usable. */}
        <ErrorBoundary
          resetKey={location.pathname}
          fallback={(error, reset) => <RouteErrorFallback error={error} onRetry={reset} />}
        >
          <Routes>
            <Route path="/" element={<TopicListPage />} />
            <Route path="/new" element={<NewRunPage />} />
            <Route path="/topics/:topicId" element={<RunBoardPage />} />
            <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/profiles" element={<ProfilesPage />} />
            <Route path="/profiles/new" element={<ProfileEditorPage />} />
            <Route path="/profiles/:profileId" element={<ProfileEditorPage />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
