import { Link, Route, Routes } from "react-router-dom";
import RunBoardPage from "./pages/RunBoardPage";
import SettingsPage from "./pages/SettingsPage";
import StageViewerPage from "./pages/StageViewerPage";
import TopicListPage from "./pages/TopicListPage";

export default function App() {
  return (
    <div className="app">
      <header>
        <h1>
          <Link to="/">Education Pipeline Cockpit</Link>
        </h1>
        <nav>
          <Link to="/settings">Settings</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<TopicListPage />} />
          <Route path="/topics/:topicId" element={<RunBoardPage />} />
          <Route path="/topics/:topicId/stages/:stage" element={<StageViewerPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
