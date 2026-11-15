"""Run one real session with the agent from the command line, and show what it built and what it cost.

THIS CALLS CLAUDE AND SPENDS MONEY: roughly one full session's worth each time.
It needs ANTHROPIC_API_KEY in the repo's .env. It does not need the server.

Run from backend/ with the venv active:

    python -m scripts.try_agent "Prepare me on the blood supply of the heart"
    python -m scripts.try_agent "Prepare me on coronary dominance" --notes path/to/lecture.pdf
    python -m scripts.try_agent "..." --wrong      # answer the first case wrongly once, to see the agent replan

Each part is printed as it is built, with every check it had to pass already
passed. The full session is also written to a JSON file for reading or replaying.
"""

import argparse
import base64
import json
import sys
import time
from pathlib import Path

from app.agent import Agent, AgentError, Brief, sources_used
from app.articles import get_articles
from app.llm import ClaudeLLM, LLMError, Usage
from app.region import get_region
from app.session_schemas import ClickAnswer, ClickCase


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one real session with the agent. Spends API credit.")
    parser.add_argument("request", help="what the student asks to be prepared on")
    parser.add_argument("--notes", type=Path, help="a PDF of lecture notes")
    parser.add_argument("--wrong", action="store_true", help="answer the first case wrongly once before answering it right")
    parser.add_argument("--out", type=Path, default=Path("agent_session.json"), help="where to write the session")
    args = parser.parse_args(argv)

    usage = Usage()
    llm = ClaudeLLM()
    agent = Agent(llm, get_region(), get_articles(), usage)
    brief = Brief(request=args.request)
    started = time.time()
    print(f"Model: {llm.model}, effort: {llm.effort}")

    try:
        if args.notes:
            brief.facts = agent.read_notes(args.request, base64.b64encode(args.notes.read_bytes()).decode(), args.notes.name)
            print(f"\nRead {len(brief.facts)} facts from {args.notes.name}:")
            for fact in brief.facts:
                print(f"  {fact.number}. (page {fact.page}) {fact.text}")

        agent.plan(brief)
        print("\nCan show:", *[f"\n  - {line}" for line in brief.scope.can_show])
        print("Words only:", *[f"\n  - {line}" for line in brief.scope.words_only])
        print("\nPlan:")
        for item in brief.plan:
            print(f"  [{item.kind}] {item.title}: {item.intent}")

        answers: list[ClickAnswer] = []
        answered_wrong = False
        index = 0
        while index < len(brief.plan):
            item = brief.plan[index]
            print(f"\nBuilding [{item.kind}] {item.title} ...")
            try:
                part = agent.build(brief, item)
            except AgentError as error:
                print("  GIVEN UP ON:", *[f"\n    - {problem}" for problem in error.problems])
                brief.plan.pop(index)
                continue
            brief.built.append(part)
            print(json.dumps(part.model_dump(mode="json", by_alias=True), indent=2))
            index += 1

            if isinstance(part, ClickCase) and part.answer.regions:
                region = part.answer.regions[0]
                right = ClickAnswer(
                    part_id=part.id, attempt=1, structure_id=agent.region.vessel_of(region.piece), point=(0, 0, 0),
                    piece=region.piece, at=(region.start + region.to) / 2, correct=True, seconds=10,
                )
                if args.wrong and not answered_wrong:
                    answered_wrong = True
                    # A wrong click a student might make: on the case's first near miss if it has one,
                    # otherwise near the start of the answer's own vessel trunk.
                    near = next((m.regions[0] for m in part.feedback.near_misses if m.regions), None)
                    if near is not None:
                        miss = right.model_copy(update={"structure_id": agent.region.vessel_of(near.piece), "piece": near.piece, "at": (near.start + near.to) / 2, "correct": False})
                    else:
                        miss = right.model_copy(update={"at": max(0.0, region.start - 0.01), "correct": False})
                    tries = [miss, right.model_copy(update={"attempt": 2})]
                    answers += tries
                    print(f"\nThe student clicked {miss.at:.3f} m along {miss.piece} (wrong), then got it right. Asking the agent what to do ...")
                    extra = agent.decide(brief, part, tries)
                    if extra is None:
                        print("  Decision: carry on with the plan.")
                    else:
                        print(f"  Decision: add [{extra.kind}] {extra.title}: {extra.intent}")
                        brief.plan.insert(index, extra)
                else:
                    answers.append(right)

        solid, shaky = agent.summarise(brief, answers)
        print("\nSummary\n  Solid:", solid, "\n  Worth another look:", shaky)
    except (LLMError, AgentError) as error:
        print(f"\nStopped: {error}")
        return 1
    finally:
        print(
            f"\n{usage.calls} requests to Claude in {time.time() - started:.0f} s. "
            f"Tokens in: {usage.input_tokens} fresh, {usage.cache_read_tokens} read from cache, {usage.cache_write_tokens} written to cache. "
            f"Tokens out: {usage.output_tokens}."
        )

    session = {
        "format": "lumen.session/0.1", "session_id": "agent-run", "region": agent.region.id, "request": args.request,
        "scope": brief.scope.model_dump(),
        "plan": [{"part_id": item.part_id, "title": item.title, "kind": item.kind} for item in brief.plan if any(p.id == item.part_id for p in brief.built)],
        "parts": [part.model_dump(mode="json", by_alias=True) for part in brief.built],
        "summary": {"solid": solid, "shaky": shaky, "sources": [s.model_dump(mode="json") for s in sources_used(brief.built)]},
    }
    args.out.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    print(f"Session written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
