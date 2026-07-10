import { Link, Route, Routes } from "react-router-dom";
import TopicListPage from "./pages/TopicListPage";

export default function App() {
  return (
    <div className="app">
      <header>
        <h1>
          <Link to="/">Education Pipeline Cockpit</Link>
        </h1>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<TopicListPage />} />
        </Routes>
      </main>
    </div>
  );
}
