import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import {
  TOUR_COMPLETED_KEY,
  TourProvider,
  hasCompletedTour,
  resetTourCompletion,
  useTour,
} from "./TourProvider";
import type { TourStep } from "./steps";

const STEPS: TourStep[] = [
  { id: "intro", title: "Welcome aboard", body: "A floating first step." },
  {
    id: "anchored",
    target: '[data-tour="probe"]',
    title: "An anchored step",
    body: "Points at the probe.",
  },
  {
    id: "elsewhere",
    route: "/settings",
    target: '[data-tour="settings-probe"]',
    title: "Over in settings",
    body: "Hops routes first.",
  },
  {
    id: "ghost",
    target: '[data-tour="never-rendered"]',
    title: "A missing anchor",
    body: "Falls back to a centered card.",
  },
];

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

function Launcher() {
  const tour = useTour();
  return (
    <button onClick={() => tour.start("workbench")}>
      {tour.active ? "Tour running" : "Launch tour"}
    </button>
  );
}

function Harness({ initialEntries = ["/"] }: { initialEntries?: string[] }) {
  return (
    <MemoryRouter initialEntries={initialEntries}>
      <TourProvider tours={{ workbench: STEPS, "run-board": STEPS }}>
        <LocationProbe />
        <Launcher />
        <Routes>
          <Route path="/" element={<section data-tour="probe">Library</section>} />
          <Route
            path="/settings"
            element={<section data-tour="settings-probe">Settings</section>}
          />
        </Routes>
      </TourProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe("TourProvider", () => {
  it("renders nothing until started, then opens an accessible dialog on the first step", async () => {
    render(<Harness />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Launch tour" }));
    const dialog = screen.getByRole("dialog", { name: "Welcome aboard" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("Step 1 of 4")).toBeInTheDocument();
    expect(screen.getByText("A floating first step.")).toBeInTheDocument();
    expect(dialog).toHaveAttribute("data-anchored", "false");
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Tour running" })).toBeInTheDocument();
  });

  it("moves focus into the dialog and returns it to the launcher when the tour ends", async () => {
    render(<Harness />);
    const launcher = screen.getByRole("button", { name: "Launch tour" });
    await userEvent.click(launcher);
    await waitFor(() => expect(screen.getByRole("dialog")).toHaveFocus());
    await userEvent.click(screen.getByRole("button", { name: "Skip tour" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(launcher).toHaveFocus());
  });

  it("anchors to a live target and marks the dialog as anchored", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Launch tour" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    const dialog = screen.getByRole("dialog", { name: "An anchored step" });
    await waitFor(() => expect(dialog).toHaveAttribute("data-anchored", "true"));
    expect(screen.getByTestId("tour-spotlight")).toBeInTheDocument();
    expect(screen.getByText("Step 2 of 4")).toBeInTheDocument();
  });

  it("navigates to a step's route before revealing it", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Launch tour" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "Over in settings" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/settings"));
    await waitFor(() =>
      expect(screen.getByRole("dialog")).toHaveAttribute("data-anchored", "true"),
    );
  });

  it("falls back to a centered card when the anchor never appears", async () => {
    render(<Harness initialEntries={["/settings"]} />);
    await userEvent.click(screen.getByRole("button", { name: "Launch tour" }));
    for (let i = 0; i < 3; i++) {
      await userEvent.click(screen.getByRole("button", { name: "Next" }));
    }
    const dialog = screen.getByRole("dialog", { name: "A missing anchor" });
    await waitFor(() => expect(dialog).toHaveAttribute("data-anchored", "false"), {
      timeout: 3_000,
    });
    expect(screen.queryByTestId("tour-spotlight")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finish" })).toBeInTheDocument();
  });

  it("supports keyboard: arrows step, Escape skips", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Launch tour" }));
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("dialog", { name: "An anchored step" })).toBeInTheDocument();
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("dialog", { name: "Welcome aboard" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem(TOUR_COMPLETED_KEY)).toBe("skipped");
  });

  it("records completion when finished and can be reset", async () => {
    render(<Harness />);
    expect(hasCompletedTour()).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Launch tour" }));
    for (let i = 0; i < 3; i++) {
      await userEvent.click(screen.getByRole("button", { name: "Next" }));
    }
    await userEvent.click(screen.getByRole("button", { name: "Finish" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(hasCompletedTour()).toBe(true);
    expect(localStorage.getItem(TOUR_COMPLETED_KEY)).toBe("done");
    resetTourCompletion();
    expect(hasCompletedTour()).toBe(false);
  });

  it("starts from ?tour=1 and strips the parameter from the URL", async () => {
    render(<Harness initialEntries={["/?tour=1&keep=yes"]} />);
    expect(await screen.findByRole("dialog", { name: "Welcome aboard" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/?keep=yes"));
  });

  it("starts a named tour at a chosen step", async () => {
    function DeepLauncher() {
      const tour = useTour();
      return <button onClick={() => tour.start("run-board", 1)}>Deep</button>;
    }
    render(
      <MemoryRouter>
        <TourProvider tours={{ workbench: STEPS, "run-board": STEPS }}>
          <DeepLauncher />
          <section data-tour="probe" />
        </TourProvider>
      </MemoryRouter>,
    );
    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Deep" }));
    });
    expect(screen.getByRole("dialog", { name: "An anchored step" })).toBeInTheDocument();
  });
});
