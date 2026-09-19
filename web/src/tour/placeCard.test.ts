import { describe, expect, it } from "vitest";
import { placeCard } from "./TourOverlay";

const viewport = { width: 1440, height: 960 };

describe("placeCard", () => {
  it("prefers sitting below a short anchor", () => {
    const result = placeCard({ top: 100, left: 300, width: 400, height: 60 }, { width: 360, height: 240 }, viewport);
    expect(result.placement).toBe("bottom");
    expect(result.style.top).toBe(100 + 60 + 10 + 16);
  });

  it("moves above when there is no room below, using the card's real height", () => {
    const anchor = { top: 300, left: 300, width: 400, height: 640 };
    const short = placeCard(anchor, { width: 360, height: 240 }, viewport);
    expect(short.placement).toBe("top");
    expect(short.style.top).toBe(300 - 10 - 16 - 240);
    // A taller card would overlap the anchor from above, so it goes beside it.
    const tall = placeCard(anchor, { width: 360, height: 420 }, viewport);
    expect(tall.placement).toBe("right");
    expect(tall.style.left).toBe(300 + 400 + 10 + 16);
  });

  it("clamps into the viewport when the anchor hugs an edge", () => {
    const result = placeCard({ top: 20, left: 1300, width: 120, height: 40 }, { width: 360, height: 240 }, viewport);
    expect(result.placement).toBe("bottom");
    expect(result.style.left).toBe(1440 - 360 - 16);
  });

  it("tucks into the lower-right corner when the anchor fills the viewport", () => {
    const result = placeCard({ top: 40, left: 40, width: 1360, height: 900 }, { width: 360, height: 420 }, viewport);
    expect(result.placement).toBe("overlay");
    expect(result.style.left).toBe(1440 - 360 - 16);
    expect(result.style.top).toBe(960 - 420 - 16);
  });

  it("centers when there is no anchor", () => {
    expect(placeCard(null, { width: 360, height: 240 }, viewport).placement).toBe("center");
  });
});
