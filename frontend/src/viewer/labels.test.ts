import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { spreadPoints, stackLabels } from "./labels.ts";

describe("stackLabels", () => {
  it("leaves labels alone when they already fit", () => {
    expect(stackLabels([100, 200, 300], 20, 50, 500)).toEqual([100, 200, 300]);
  });

  it("pushes crowded labels down to keep the gap", () => {
    expect(stackLabels([100, 105, 110], 20, 50, 500)).toEqual([100, 120, 140]);
  });

  it("keeps labels below the top edge", () => {
    expect(stackLabels([10, 20], 20, 50, 500)).toEqual([50, 70]);
  });

  it("pulls labels back up when they would run off the bottom", () => {
    expect(stackLabels([480, 490, 495], 20, 50, 500)).toEqual([460, 480, 500]);
  });

  it("keeps the order and the gap even when there are too many labels to fit", () => {
    const stacked = stackLabels([100, 100, 100, 100], 20, 90, 130);
    expect(stacked).toEqual([70, 90, 110, 130]);
  });

  it("handles an empty column", () => {
    expect(stackLabels([], 20, 50, 500)).toEqual([]);
  });
});

describe("spreadPoints", () => {
  const line = [0, 1, 2, 3, 4, 5, 6, 7, 8].map(
    (x) => new THREE.Vector3(x, 0, 0),
  );

  it("starts with the point farthest from the origin", () => {
    expect(spreadPoints(line, 3)[0].x).toBe(8);
  });

  it("picks points that are far apart", () => {
    const xs = spreadPoints(line, 3).map((point) => point.x);
    expect(xs).toEqual([8, 0, 4]);
  });

  it("returns every point when fewer than requested exist", () => {
    expect(spreadPoints(line.slice(0, 2), 5)).toHaveLength(2);
  });
});
