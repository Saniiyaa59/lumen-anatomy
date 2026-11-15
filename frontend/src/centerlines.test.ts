import { describe, expect, it } from "vitest";
import { Centerlines, centerlines, type CenterlinesFile, type Piece, type Point } from "./centerlines.ts";

function piece(id: string, points: Point[], radius: number, attach: Piece["attach"] = null): Piece {
  let length = 0;
  for (let i = 1; i < points.length; i++) length += Math.hypot(...points[i].map((value, k) => value - points[i - 1][k]));
  return { id, length, attach, radius: points.map(() => radius), points };
}

/**
 * A small tree, in metres:
 *
 *   trunk.0  along x from 0 to 0.1, radius 4 mm
 *   trunk.1  a thin branch going up (+y) from the trunk at 0.04, radius 1 mm
 *   twig.0   another vessel, going up from the trunk at 0.07
 *   twig.1   a branch of twig.0, going sideways (+z) from 0.01 along it
 */
const tree = new Centerlines({
  region: "test",
  source: "test",
  units: "metres",
  structures: {
    trunk: [
      piece("trunk.0", [[0, 0, 0], [0.05, 0, 0], [0.1, 0, 0]], 0.004),
      piece("trunk.1", [[0.04, 0, 0], [0.04, 0.03, 0]], 0.001, { piece: "trunk.0", at: 0.04, gap: 0 }),
    ],
    twig: [
      piece("twig.0", [[0.07, 0, 0], [0.07, 0.02, 0]], 0.001, { piece: "trunk.0", at: 0.07, gap: 0 }),
      piece("twig.1", [[0.07, 0.01, 0], [0.07, 0.01, 0.02]], 0.001, { piece: "twig.0", at: 0.01, gap: 0 }),
    ],
  },
} satisfies CenterlinesFile);

describe("locate", () => {
  it("turns a point on the surface into a piece and a distance along it", () => {
    const position = tree.locate("trunk", [0.06, 0.004, 0])!;
    expect(position.pieceId).toBe("trunk.0");
    expect(position.along).toBeCloseTo(0.06);
    expect(position.offset).toBeCloseTo(0.004);
  });

  it("gives the base of a thin branch to the branch, not to the thick trunk it leaves", () => {
    // 1 mm from the branch's centre line (on its surface) and only 3 mm from the trunk's (inside the trunk).
    const position = tree.locate("trunk", [0.041, 0.003, 0])!;
    expect(position.pieceId).toBe("trunk.1");
    expect(position.along).toBeCloseTo(0.003);
  });

  it("measures a branch from where the vessel begins, through the trunk", () => {
    const position = tree.locate("trunk", [0.041, 0.02, 0])!;
    expect(position.along).toBeCloseTo(0.02);
    expect(position.fromStart).toBeCloseTo(0.04 + 0.02);
  });

  it("starts again at zero for a vessel that branches off another vessel", () => {
    expect(tree.locate("twig", [0.071, 0.015, 0])!.fromStart).toBeCloseTo(0.015);
    expect(tree.fromStart("twig.1", 0.005)).toBeCloseTo(0.01 + 0.005);
  });

  it("returns null for a structure with no centre line", () => {
    expect(tree.locate("left_ventricle", [0, 0, 0])).toBeNull();
    expect(tree.has("left_ventricle")).toBe(false);
  });
});

describe("stretch", () => {
  it("keeps both ends inside the piece and in order", () => {
    expect(tree.stretch("trunk.0", 0.09, 0.2)).toEqual({ pieceId: "trunk.0", from: 0.09, to: 0.1 });
    expect(tree.stretch("trunk.0", 0.03, -0.01)).toEqual({ pieceId: "trunk.0", from: 0, to: 0.03 });
  });
});

describe("beyond", () => {
  const ids = (pieceId: string, along: number) => tree.beyond(pieceId, along).map((stretch) => stretch.pieceId);

  it("covers the rest of the piece and every branch that leaves after the place", () => {
    expect(tree.beyond("trunk.0", 0.05)[0]).toEqual({ pieceId: "trunk.0", from: 0.05, to: 0.1 });
    expect(ids("trunk.0", 0.05)).toEqual(["trunk.0", "twig.0", "twig.1"]);
  });

  it("leaves out branches that leave before the place", () => {
    expect(ids("trunk.0", 0.05)).not.toContain("trunk.1");
    expect(ids("trunk.0", 0.08)).toEqual(["trunk.0"]);
  });

  it("includes everything from the very start", () => {
    expect(ids("trunk.0", 0).sort()).toEqual(["trunk.0", "trunk.1", "twig.0", "twig.1"]);
  });

  it("follows branches of branches, whole", () => {
    expect(tree.beyond("twig.0", 0.005)).toEqual([
      { pieceId: "twig.0", from: 0.005, to: 0.02 },
      { pieceId: "twig.1", from: 0, to: 0.02 },
    ]);
  });
});

describe("the exported heart", () => {
  it("places a point on a vessel's surface at the right distance along it", () => {
    const trunk = centerlines.piece("anterior_interventricular_artery.0")!;
    const i = Math.floor(trunk.points.length / 2);
    const [a, b] = [trunk.points[i], trunk.points[i + 1]];
    // Step one radius sideways from the centre line: any direction at right angles to the path.
    const tangent = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    const side = [tangent[1], -tangent[0], 0];
    const scale = trunk.radius[i] / Math.hypot(...side);
    const onSurface: Point = [a[0] + side[0] * scale, a[1] + side[1] * scale, a[2] + side[2] * scale];
    let expected = 0;
    for (let k = 1; k <= i; k++) expected += Math.hypot(...trunk.points[k].map((value, axis) => value - trunk.points[k - 1][axis]));

    const position = centerlines.locate("anterior_interventricular_artery", onSurface)!;
    expect(position.pieceId).toBe("anterior_interventricular_artery.0");
    expect(position.along).toBeCloseTo(expected, 3);
    expect(position.offset).toBeCloseTo(trunk.radius[i], 4);
    expect(position.fromStart).toBeCloseTo(expected, 3);
  });

  it("finds both branches of the left coronary artery beyond its start, and nothing of the right", () => {
    const vessels = new Set(centerlines.beyond("left_coronary_artery.0", 0).map((stretch) => centerlines.structureOf(stretch.pieceId)));
    expect(vessels).toEqual(
      new Set([
        "left_coronary_artery",
        "anterior_interventricular_artery",
        "septal_branches_of_anterior_interventricular_artery",
        "circumflex_artery_of_heart",
      ]),
    );
  });

  it("knows the coronary arteries are thin and the aorta is not", () => {
    expect(centerlines.maxRadius("right_coronary_artery")).toBeLessThan(0.003);
    expect(centerlines.maxRadius("ascending_aorta")).toBeGreaterThan(0.01);
    expect(centerlines.maxRadius("left_ventricle")).toBe(0);
  });
});
