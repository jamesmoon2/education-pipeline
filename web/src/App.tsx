import { Link, Route, Routes } from "react-router-dom";

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
          <Route path="/" element={<p>Cockpit is running. Pages arrive in later tasks.</p>} />
        </Routes>
      </main>
    </div>
  );
}
