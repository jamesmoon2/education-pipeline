import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import BuildFreshnessBanner from "./components/BuildFreshnessBanner";
import GlobalJobActivity from "./components/GlobalJobActivity";
import ThemeToggle from "./components/ThemeToggle";
import {
  BrandMark,
  LibraryIcon,
  ProfileIcon,
  SettingsIcon,
  SparkIcon,
  TourIcon,
} from "./components/icons";
import NewRunPage from "./pages/NewRunPage";
import RunBoardPage from "./pages/RunBoardPage";
import SettingsPage from "./pages/SettingsPage";
import StageViewerPage from "./pages/StageViewerPage";
import TopicListPage from "./pages/TopicListPage";
import ProfilesPage from "./pages/ProfilesPage";
import ProfileEditorPage from "./pages/ProfileEditorPage";
import { TourProvider, useTour } from "./tour";

function TourLauncher() {
  const tour = useTour();
  return (
    <button
      type="button"
      className="rail-tour"
      onClick={() => tour.start("workbench")}
      disabled={tour.active}
    >
      <TourIcon />
      <span>Take the tour</span>
      <span className="rail-tour-meta" aria-hidden="true">2 min</span>
    </button>
  );
}

function Dock() {
  return (
    <header className="app-rail">
      <Link to="/" className="brand">
        <BrandMark />
        <span className="brand-text">Education Pipeline</span>
      </Link>
      <nav className="rail-nav" aria-label="Primary" data-tour="nav">
        <NavLink to="/" end>
          <LibraryIcon />
          <span>Courses</span>
        </NavLink>
        <NavLink to="/new">
          <SparkIcon />
          <span>New course</span>
        </NavLink>
        <NavLink to="/profiles">
          <ProfileIcon />
          <span>Profiles</span>
        </NavLink>
        <NavLink to="/settings">
          <SettingsIcon />
          <span>Settings</span>
        </NavLink>
      </nav>
      <section className="rail-activity" aria-label="Workspace activity" data-tour="activity">
        <h2 className="rail-label">Activity</h2>
        <GlobalJobActivity />
      </section>
      <div className="rail-foot">
        <TourLauncher />
        <ThemeToggle />
        <p className="rail-footer">
          <strong>Stored on this device</strong>
          Courses, profiles, and runs live in your local workspace.
        </p>
      </div>
    </header>
  );
}

function Workspace() {
  const location = useLocation();
  return (
    <main className="workspace" id="workspace" tabIndex={-1}>
      <BuildFreshnessBanner />
      <div className="page-enter" key={location.pathname}>
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
      </div>
    </main>
  );
}

export default function App() {
  return (
    <TourProvider>
      <a className="skip-link" href="#workspace">
        Skip to content
      </a>
      <div className="app-backdrop" aria-hidden="true">
        <i className="aurora aurora-a" />
        <i className="aurora aurora-b" />
        <i className="aurora aurora-c" />
      </div>
      <div className="app-shell">
        <Dock />
        <Workspace />
      </div>
    </TourProvider>
  );
}
