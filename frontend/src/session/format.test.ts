import { describe, expect, it } from "vitest";
import sample from "../../../assets/fixtures/sessions/coronary_arteries.json";
import { centerlines } from "../centerlines.ts";
import { atlasTitle, checkSession, parseSession, PART_KINDS } from "./format.ts";

/** A copy of the sample with one change made to it. */
function broken(change: (session: any) => void): unknown {
  const copy = structuredClone(sample);
  change(copy);
  return copy;
}

const problemsWith = (change: (session: any) => void) => checkSession(broken(change));

describe("the sample session", () => {
  it("fits the format", () => {
    expect(checkSession(sample)).toEqual([]);
    expect(parseSession(sample).parts).toHaveLength(5);
  });

  it("has one part of every kind, so the player can be built against it", () => {
    expect(sample.parts.map((part) => part.kind).sort()).toEqual([...PART_KINDS].sort());
  });

  it("puts the case's answer exactly before the first septal branch", () => {
    const answer = sample.parts.find((part) => part.kind === "click_case")!.answer!.regions[0];
    const firstSeptal = Math.min(
      ...centerlines
        .pieces("septal_branches_of_anterior_interventricular_artery")
        .filter((piece) => piece.attach?.piece === answer.piece)
        .map((piece) => piece.attach!.at),
    );
    expect(answer.to).toBeCloseTo(firstSeptal, 3);
  });
});

describe("checkSession", () => {
  it("rejects something that is not a session at all", () => {
    expect(checkSession("hello")).toEqual(["session: must be an object"]);
  });

  it("rejects another format version", () => {
    expect(problemsWith((s) => (s.format = "lumen.session/9"))).toEqual(['session.format: must be "lumen.session/0.1"']);
  });

  it("rejects a session for a region the viewer has not loaded", () => {
    expect(problemsWith((s) => (s.region = "arm"))[0]).toContain('must be "heart"');
  });

  it("names a structure that does not exist", () => {
    expect(problemsWith((s) => s.parts[0].highlight.push("spleen"))).toEqual([
      'session.parts[0].highlight[2]: "spleen" is not a structure in this region',
    ]);
  });

  it("lets a part hide a whole group, but not something that is neither a structure nor a group", () => {
    expect(problemsWith((s) => (s.parts[0].hide = ["cardiac_veins", "left_atrium"]))).toEqual([]);
    expect(problemsWith((s) => (s.parts[0].hide = ["spleen"]))).toEqual([
      'session.parts[0].hide[0]: "spleen" is not a structure or a group in this region',
    ]);
  });

  it("names a centre-line piece that does not exist", () => {
    expect(problemsWith((s) => (s.parts[1].from.piece = "left_coronary_artery.7"))).toEqual([
      'session.parts[1].from.piece: "left_coronary_artery.7" is not a centre-line piece in this region',
    ]);
  });

  it("rejects a stretch that runs past the end of its piece", () => {
    const problems = problemsWith((s) => (s.parts[3].answer.regions[0].to = 0.5));
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain("session.parts[3].answer.regions[0]: from 0 to 0.5 is not a stretch of the piece");
  });

  it("rejects a stretch written backwards", () => {
    expect(problemsWith((s) => Object.assign(s.parts[3].answer.regions[0], { from: 0.04, to: 0.01 }))[0]).toContain("is not a stretch of the piece");
  });

  it("rejects a pulse that would have to run back toward the trunk", () => {
    const problems = problemsWith((s) => {
      s.parts[1].from = { piece: "anterior_interventricular_artery.0", at: 0.05 };
      s.parts[1].to = { piece: "left_coronary_artery.0", at: 0.01 };
    });
    expect(problems).toEqual(["session.parts[1].to: is not further along the vessel than the start, so a pulse can't run there"]);
  });

  it("accepts a pulse that ends on a branch beyond its start", () => {
    expect(problemsWith((s) => (s.parts[1].to = { piece: "circumflex_artery_of_heart.0", at: 0.05 }))).toEqual([]);
  });

  it("rejects a slider that starts off its track", () => {
    expect(problemsWith((s) => (s.parts[2].start_at = 0.2))).toEqual([
      "session.parts[2].start_at: 0.2 is outside the track (0 to 0.1145)",
    ]);
  });

  it("rejects a case with no correct place", () => {
    expect(problemsWith((s) => (s.parts[3].answer.regions = []))).toEqual([
      "session.parts[3].answer: must name at least one stretch of vessel or one structure",
    ]);
  });

  it("rejects a near miss that overlaps the correct answer", () => {
    expect(problemsWith((s) => (s.parts[3].feedback.near_misses[1].regions[0].from = 0.03))).toEqual([
      "session.parts[3].feedback.near_misses[1]: overlaps the correct answer",
    ]);
  });

  it("rejects text with no source, or a source of an unknown kind", () => {
    expect(problemsWith((s) => delete s.parts[0].statements[0].source)).toEqual([
      "session.parts[0].statements[0].source: must be an object",
    ]);
    expect(problemsWith((s) => (s.parts[0].statements[0].source = { type: "memory" }))).toEqual([
      'session.parts[0].statements[0].source.type: must be "notes", "atlas", "web" or "model"',
    ]);
  });

  it("checks a notes source has a file and a real page number", () => {
    expect(problemsWith((s) => (s.parts[0].statements[0].source = { type: "notes", file: "lecture_07.pdf", page: 12 }))).toEqual([]);
    expect(problemsWith((s) => (s.parts[0].statements[0].source = { type: "notes", file: "lecture_07.pdf", page: 0 }))).toEqual([
      "session.parts[0].statements[0].source.page: must be a page number, 1 or more",
    ]);
  });

  it("rejects a part of an unknown kind", () => {
    expect(problemsWith((s) => (s.parts[0].kind = "quiz"))[0]).toContain("session.parts[0].kind: must be one of demonstration");
  });

  it("rejects a plan item that points to no part, or names the wrong kind", () => {
    expect(problemsWith((s) => (s.plan[0].part_id = "intro"))).toEqual(['session.plan[0].part_id: "intro" is not the id of a part']);
    expect(problemsWith((s) => (s.plan[0].kind = "pulse"))).toEqual([
      'session.plan[0].kind: must be "demonstration", the kind of part "origins"',
    ]);
  });

  it("rejects two parts with the same id", () => {
    expect(problemsWith((s) => (s.parts[1].id = "origins"))).toContain('session.parts[1].id: "origins" is used by more than one part');
  });

  it("lists every problem, not only the first", () => {
    const problems = problemsWith((s) => {
      s.parts[0].title = "";
      s.parts[0].view.side = "front";
      s.parts[3].question = "";
    });
    expect(problems).toHaveLength(3);
  });
});

describe("parseSession", () => {
  it("throws with every problem listed", () => {
    const bad = broken((s) => {
      s.request = "";
      s.parts[0].hide = ["spleen"];
    });
    expect(() => parseSession(bad)).toThrow(/does not fit the format[\s\S]*session\.request[\s\S]*spleen/);
  });
});

describe("a multiple-choice question", () => {
  const at = sample.parts.findIndex((part) => part.kind === "multiple_choice");
  const path = `session.parts[${at}]`;
  const withQuestion = (change: (question: any) => void) => problemsWith((s) => change(s.parts[at]));

  it("may have no story, but needs a question", () => {
    expect(withQuestion((q) => (q.story = "A man has chest pain."))).toEqual([]);
    expect(withQuestion((q) => (q.question = ""))).toEqual([`${path}.question: must be a non-empty string`]);
  });

  it("needs exactly one right option", () => {
    expect(withQuestion((q) => (q.options[1].correct = true))).toEqual([`${path}.options: exactly one option must be correct, not 2`]);
    expect(withQuestion((q) => (q.options[0].correct = false))).toEqual([`${path}.options: exactly one option must be correct, not 0`]);
  });

  it("needs two to five options, each different, each with sourced feedback", () => {
    expect(withQuestion((q) => (q.options = q.options.slice(0, 1)))).toContain(`${path}.options: must have 2 to 5 options`);
    expect(withQuestion((q) => (q.options[2].text = "right coronary ARTERY"))).toEqual([`${path}.options[2].text: is the same as another option's`]);
    expect(withQuestion((q) => delete q.options[1].feedback.source)).toEqual([`${path}.options[1].feedback.source: must be an object`]);
  });

  it("may highlight only real structures", () => {
    expect(withQuestion((q) => (q.highlight = ["spleen"]))).toEqual([`${path}.highlight[0]: "spleen" is not a structure in this region`]);
  });
});

describe("the name shown for an atlas source", () => {
  it("is the title of the page it links to, not the atlas entry's name", () => {
    expect(atlasTitle({ article: "Left ventricle", url: "https://en.wikipedia.org/wiki/Ventricle_(heart)" })).toBe("Ventricle (heart)");
    expect(atlasTitle({ article: "x", url: "https://en.wikipedia.org/wiki/Sinoatrial_node#Blood_supply" })).toBe("Sinoatrial node");
    expect(atlasTitle({ article: "x", url: "https://en.wikipedia.org/wiki/M%C3%BCller%27s_muscle" })).toBe("Müller's muscle");
  });

  it("falls back to the entry's name with no link, or a link that is not a Wikipedia article", () => {
    expect(atlasTitle({ article: "Left ventricle", url: null })).toBe("Left ventricle");
    expect(atlasTitle({ article: "Left ventricle", url: "https://example.org/heart" })).toBe("Left ventricle");
  });
});
