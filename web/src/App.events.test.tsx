import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// T62b at the shell (design note §6): EventsProvider is owned by App, around
// the rail and every route, so a tab holds one stream however it navigates,
// the rail's pollers and a route's pollers pause together while it is up,
// and <html data-events> mirrors its state for e2e.

vi.mock("./pages/TopicListPage", async () => {
  const { usePolling } = await import("./hooks/usePolling");
  const { getProfiles } = await import("./api/client");
  return {
    // A route-level poller with a filter, standing in for any page.
    default: function LibraryStub() {
      usePolling(getProfiles, 30_000, { events: { topics: true } });
      return <p>Library stub</p>;
    },
  };
});
vi.mock("./pages/RunBoardPage", () => ({ default: () => <p>Run board stub</p> }));
vi.mock("./pages/NewRunPage", () => ({ default: () => <p>New course stub</p> }));
vi.mock("./pages/StageViewerPage", () => ({ default: () => <p>Stage viewer stub</p> }));
vi.mock("./pages/SettingsPage", () => ({ default: () => <p>Settings stub</p> }));
vi.mock("./pages/ProfilesPage", () => ({ default: () => <p>Profiles stub</p> }));
vi.mock("./pages/ProfileEditorPage", () => ({ default: () => <p>Profile editor stub</p> }));

vi.mock("./api/client", async () => {
  const actual = await vi.importActual<typeof import("./api/client")>("./api/client");
  return {
    ApiRequestError: actual.ApiRequestError,
    api: vi.fn(),
    getJobs: vi.fn(),
    getTopics: vi.fn(),
    getProfiles: vi.fn(),
    openEventStream: vi.fn(),
  };
});

import { api, getJobs, getProfiles, getTopics, openEventStream } from "./api/client";
import App from "./App";
import {
  createFakeEventServer,
  eventsAttribute,
  flush,
  idleWithKeepalives,
  useFakeClock,
} from "./test/eventStream";

let server: ReturnType<typeof createFakeEventServer>;

beforeEach(() => {
  vi.clearAllMocks();
  useFakeClock();
  server = createFakeEventServer();
  // clearAllMocks keeps queued mockImplementationOnce answers; start clean.
  vi.mocked(openEventStream).mockReset();
  vi.mocked(openEventStream).mockImplementation(server.open);
  vi.mocked(api).mockResolvedValue({ version: "test", ok: true });
  vi.mocked(getJobs).mockResolvedValue({ jobs: [] });
  vi.mocked(getTopics).mockResolvedValue({ topics: [] });
  vi.mocked(getProfiles).mockResolvedValue({ profiles: [] });
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
  delete document.documentElement.dataset.events;
});

function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

const polled = () =>
  vi.mocked(getJobs).mock.calls.length +
  vi.mocked(getTopics).mock.calls.length +
  vi.mocked(getProfiles).mock.calls.length;

describe("App owns one events stream per tab", () => {
  it("opens exactly one stream, and navigating between routes keeps it", async () => {
    renderApp("/");
    await flush(0);
    expect(openEventStream).toHaveBeenCalledTimes(1);
    server.current.hello();
    await flush(0);

    fireEvent.click(screen.getByRole("link", { name: "Settings" }));
    await flush(0);
    expect(screen.getByText("Settings stub")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Profiles" }));
    await flush(0);
    fireEvent.click(screen.getByRole("link", { name: "Courses" }));
    await flush(0);

    expect(openEventStream).toHaveBeenCalledTimes(1);
    const [signal] = vi.mocked(openEventStream).mock.calls[0] as [AbortSignal];
    expect(signal.aborted).toBe(false);
  });

  it("pauses the rail's pollers and a route's poller together while the stream is up", async () => {
    renderApp("/");
    await flush(0);
    server.current.hello();
    await flush(0);
    const before = polled();
    await idleWithKeepalives(server.current, 120_000);
    expect(polled() - before).toBe(0);

    // A topics notice reaches the rail's /v1/topics and the route's
    // /v1/profiles, and not the rail's /v1/jobs.
    const jobsBefore = vi.mocked(getJobs).mock.calls.length;
    const topicsBefore = vi.mocked(getTopics).mock.calls.length;
    const profilesBefore = vi.mocked(getProfiles).mock.calls.length;
    server.current.change({ kind: "topics" });
    await flush(0);
    expect(vi.mocked(getJobs).mock.calls.length - jobsBefore).toBe(0);
    expect(vi.mocked(getTopics).mock.calls.length - topicsBefore).toBe(1);
    expect(vi.mocked(getProfiles).mock.calls.length - profilesBefore).toBe(1);
  });

  it("mirrors the stream state to <html data-events> for e2e", async () => {
    renderApp("/");
    await flush(0);
    expect(eventsAttribute()).not.toBe("up");
    server.current.hello();
    await flush(0);
    expect(eventsAttribute()).toBe("up");
    server.current.end();
    await flush(0);
    expect(eventsAttribute()).not.toBe("up");
  });
});
