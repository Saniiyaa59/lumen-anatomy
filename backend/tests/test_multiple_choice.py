"""Multiple-choice questions: naming a highlighted structure, or quizzing what the model can't show."""

import pytest

from app import sessions
from app.agent import Brief, PlannedPart, _gives_away, sources_used
from app.session_schemas import ChoiceAnswer, MultipleChoice
from test_agent import (  # the scripted stand-in for Claude, and its fixture
    CIRCUMFLEX,
    CIRCUMFLEX_QUOTE,
    DEMO_ITEM,
    LAD,
    RCA,
    RCA_QUOTE,
    agent_with,
    call,
    client,
    demo_draft,
    lad_source,
    reply,
    scripted_sessions,  # noqa: F401  (a fixture, used by name)
)

NAME_IT = PlannedPart("p2-name-it", "Name the highlighted artery", "multiple_choice", "Highlight the right coronary artery and ask which it is.")


def choice_draft(**changes):
    """A name-it question as the agent would hand it in."""
    draft = {
        "title": "Name the highlighted artery",
        "view": {"look_at": [RCA]},
        "hide": [],
        "highlight": [RCA],
        "story": None,
        "question": "Which artery is highlighted?",
        "options": [
            {"text": "Right coronary artery", "correct": True, "feedback": {"text": "Right. It runs down the right coronary sulcus.", "source": {"type": "atlas", "article": "Right coronary artery", "quote": RCA_QUOTE}}},
            {"text": "Left anterior descending artery", "correct": False, "feedback": {"text": "No. That one runs down the front, towards the septum.", "source": lad_source()}},
            {"text": "Circumflex artery", "correct": False, "feedback": {"text": "No. That one curves to the back and side on the left.", "source": {"type": "atlas", "article": "Circumflex artery of heart", "quote": CIRCUMFLEX_QUOTE}}},
        ],
    }
    return draft | changes


def build(draft, item=NAME_IT):
    agent, llm = agent_with(submit_multiple_choice=[reply(call("submit_multiple_choice", **draft))])
    return agent.build(Brief(request="x"), item), llm


def test_a_name_it_question_is_accepted_with_checked_sources_and_a_view_that_shows_what_it_highlights():
    part, llm = build(choice_draft())
    assert isinstance(part, MultipleChoice) and part.id == "p2-name-it"
    assert part.view.side is not None  # chosen by the code so the highlighted artery shows
    assert [option.feedback.source.type for option in part.options] == ["atlas", "atlas", "atlas"]
    assert "multiple_choice" in llm.asked[0][1][0]["content"] and "submit_multiple_choice" in [t["name"] for t in llm.tools[0]]


def test_a_question_about_what_the_model_cannot_show_needs_no_highlight_and_no_particular_view():
    draft = choice_draft(highlight=[], question="Which artery most often feeds the node that sets the heartbeat?")
    del draft["story"]  # left out: it defaults to no story
    part, _ = build(draft)
    assert part.highlight == [] and part.story is None
    assert part.view.side is None and part.hide == []


@pytest.mark.parametrize(
    ("spoil", "reason"),
    [
        (lambda d: d["options"][1].update(correct=True), "exactly one option must be correct, not 2"),
        (lambda d: d["options"][2].update(text="right coronary ARTERY"), "two options have the same text"),
        (lambda d: d.update(options=d["options"][:1]), "at least 2"),
        (lambda d: d.update(question="Is the highlighted vessel the right coronary artery?"), "gives itself away"),
        (lambda d: d.update(story="Her right coronary artery is blocked.", question="Which is highlighted?"), "gives itself away"),
        (lambda d: d.update(highlight=["spleen"]), '"spleen" is not a structure'),
        (lambda d: d["options"][1]["feedback"]["source"].update(quote="The LAD is a vessel of the heart, made up."), "word for word"),
    ],
)
def test_a_flawed_question_is_sent_back_with_the_reason(spoil, reason):
    bad = choice_draft()
    spoil(bad)
    agent, llm = agent_with(submit_multiple_choice=[reply(call("submit_multiple_choice", **bad)), reply(call("submit_multiple_choice", **choice_draft()))])
    agent.build(Brief(request="x"), NAME_IT)
    sent_back = llm.last_results("submit_multiple_choice")[0]
    assert sent_back["is_error"] is True and reason in sent_back["content"]


def test_an_answer_gives_itself_away_only_as_whole_words():
    part = MultipleChoice.model_validate(
        {
            "id": "q",
            "kind": "multiple_choice",
            "title": "t",
            "view": {"look_at": [LAD], "side": None},
            "hide": [],
            "statements": [],
            "highlight": [],
            "story": None,
            "question": "Which artery, blocked, could leave the bladder untouched?",
            "options": [{"text": "LAD", "correct": True, "feedback": {"text": "x", "source": {"type": "model"}}}, {"text": "RCA", "correct": False, "feedback": {"text": "y", "source": {"type": "model"}}}],
        }
    )
    assert _gives_away(part) == []
    assert _gives_away(part.model_copy(update={"question": "Is it the lad?"}))


def picks(*choices):
    return [ChoiceAnswer(part_id=NAME_IT.part_id, attempt=n, choice=c, correct=c == 0, seconds=3.0) for n, c in enumerate(choices, start=1)]


def test_decide_and_summarise_read_the_picks():
    question, _ = build(choice_draft())
    brief = Brief(request="x", plan=[NAME_IT], built=[question])
    agent, llm = agent_with(decide_next=[reply(call("decide_next", action="continue", reason="A slip."))], submit_summary=[reply(call("submit_summary", solid=["Naming the right coronary artery"], shaky=[]))])
    assert agent.decide(brief, question, picks(1, 0)) is None
    task = llm.asked[0][1][0]["content"]
    assert 'try 1: picked "Left anterior descending artery"; wrong' in task and "Right answer: Right coronary artery." in task
    agent.summarise(brief, picks(1, 0))
    assert "Name the highlighted artery: correct on try 2" in llm.asked[1][1][0]["content"]
    assert len(sources_used([question])) == 3


PLAN = {
    "can_show": ["The course of the right coronary artery"],
    "words_only": ["Which node each artery feeds"],
    "parts": [
        {"title": "Where the right coronary artery runs", "kind": "demonstration", "intent": "Show its course."},
        {"title": "Name the highlighted artery", "kind": "multiple_choice", "intent": "Name it."},
    ],
}


def test_a_session_takes_picks_as_answers_checks_them_and_keeps_them_across_a_restart(scripted_sessions):
    scripted_sessions(
        submit_plan=[reply(call("submit_plan", **PLAN))],
        submit_demonstration=[reply(call("submit_demonstration", **demo_draft()))],
        submit_multiple_choice=[reply(call("submit_multiple_choice", **choice_draft()))],
        decide_next=[reply(call("decide_next", action="continue", reason="A slip."))],
    )
    session_id = client.post("/api/sessions", json={"request": "the right coronary artery"}).json()["session_id"]
    demo = client.post(f"/api/sessions/{session_id}/next").json()["part"]
    question = client.post(f"/api/sessions/{session_id}/next").json()["part"]
    assert question["kind"] == "multiple_choice" and len(question["options"]) == 3
    pick = {"part_id": question["id"], "attempt": 1, "choice": 1, "correct": False, "seconds": 2.5}

    assert client.post(f"/api/sessions/{session_id}/answers", json=pick | {"choice": 3}).status_code == 422
    assert client.post(f"/api/sessions/{session_id}/answers", json=pick | {"part_id": demo["id"]}).status_code == 422
    assert client.post(f"/api/sessions/{session_id}/answers", json=pick).status_code == 200
    assert client.post(f"/api/sessions/{session_id}/answers", json=pick | {"attempt": 2, "choice": 0, "correct": True}).status_code == 200

    # The wrong pick has the agent decide whether to add a part; it carries on.
    assert client.post(f"/api/sessions/{session_id}/next").json()["done"] is True
    sessions._sessions.clear()
    answers = client.get(f"/api/sessions/{session_id}").json()["answers"]
    assert [(a["choice"], a["correct"]) for a in answers] == [(1, False), (0, True)]


def test_after_a_wrong_pick_the_extra_part_is_decided_and_built_before_next_is_pressed(scripted_sessions):
    extra = {"title": "Where the right coronary artery runs again", "kind": "demonstration", "intent": "Show its course once more."}
    llm = scripted_sessions(
        submit_plan=[reply(call("submit_plan", **PLAN))],
        submit_demonstration=[reply(call("submit_demonstration", **demo_draft())), reply(call("submit_demonstration", **demo_draft(extra["title"])))],
        submit_multiple_choice=[reply(call("submit_multiple_choice", **choice_draft()))],
        decide_next=[reply(call("decide_next", action="insert", reason="Mixed it up with the LAD.", part=extra))],
    )
    session_id = client.post("/api/sessions", json={"request": "the right coronary artery"}).json()["session_id"]
    client.post(f"/api/sessions/{session_id}/next")
    question = client.post(f"/api/sessions/{session_id}/next").json()["part"]
    tutor = sessions._sessions[session_id].tutor
    pick = {"part_id": question["id"], "attempt": 1, "choice": 1, "correct": False, "seconds": 2.5}

    client.post(f"/api/sessions/{session_id}/answers", json=pick)
    assert tutor.deciding == {}  # still open: nothing is decided on a wrong pick alone
    client.post(f"/api/sessions/{session_id}/answers", json=pick | {"attempt": 2, "choice": 0, "correct": True})

    # The right pick starts the decision, and the extra part is built with it, before Next.
    planned, built = tutor.deciding[question["id"]].result()
    assert planned.title == extra["title"] and built.title == extra["title"]
    asked_before_next = len(llm.asked)

    added = client.post(f"/api/sessions/{session_id}/next").json()
    assert added["part"]["title"] == extra["title"] and added["plan"][-1]["title"] == extra["title"]
    assert len(llm.asked) == asked_before_next  # Next needed no request to Claude


def test_a_question_right_first_time_starts_no_decision(scripted_sessions):
    scripted_sessions(
        submit_plan=[reply(call("submit_plan", **PLAN))],
        submit_demonstration=[reply(call("submit_demonstration", **demo_draft()))],
        submit_multiple_choice=[reply(call("submit_multiple_choice", **choice_draft()))],
    )
    session_id = client.post("/api/sessions", json={"request": "the right coronary artery"}).json()["session_id"]
    client.post(f"/api/sessions/{session_id}/next")
    question = client.post(f"/api/sessions/{session_id}/next").json()["part"]
    client.post(f"/api/sessions/{session_id}/answers", json={"part_id": question["id"], "attempt": 1, "choice": 0, "correct": True, "seconds": 2.0})
    assert sessions._sessions[session_id].tutor.deciding == {}
    assert client.post(f"/api/sessions/{session_id}/next").json()["done"] is True


def test_no_part_is_added_after_an_added_part_and_at_most_two_in_a_session():
    question, _ = build(choice_draft())
    agent, llm = agent_with()  # no decide_next reply scripted: asking would fail the test
    added = PlannedPart("extra1-name-it-again", "Name it again", "multiple_choice", "Again.")
    tutor = sessions.AgentTutor(agent, Brief(request="x", plan=[NAME_IT, added], built=[question]))
    assert tutor._may_add_after(question)

    again = question.model_copy(update={"id": added.part_id})
    tutor.brief.built.append(again)
    assert not tutor._may_add_after(again)
    tutor.answered([ChoiceAnswer(part_id=again.id, attempt=n, choice=c, correct=c == 0, seconds=1.0) for n, c in ((1, 1), (2, 0))])
    assert tutor.deciding == {} and llm.asked == []

    tutor.brief.plan.append(PlannedPart("extra2-another", "Another", "demonstration", "More."))
    assert sessions.MAX_EXTRAS == 2 and not tutor._may_add_after(question)  # two added already


def test_atlas_entries_that_share_a_page_are_one_source_in_the_summary():
    question, _ = build(choice_draft())
    page = "https://en.wikipedia.org/wiki/Ventricle_(heart)"
    twins = [option.feedback.source.model_copy(update={"article": name, "url": page}) for option, name in zip(question.options, ["Left ventricle", "Right ventricle", "Left ventricle"])]
    options = [option.model_copy(update={"feedback": option.feedback.model_copy(update={"source": source})}) for option, source in zip(question.options, twins)]
    used = sources_used([question.model_copy(update={"options": options})])
    assert [(s.article, s.url) for s in used] == [("Left ventricle", page)]


def test_a_group_in_look_at_or_highlight_stands_for_the_structures_in_it():
    part, _ = build(choice_draft(view={"look_at": ["arteries_of_heart"]}, highlight=["arteries_of_heart"], question="Which of these supplies the right ventricle?"))
    arteries = sessions.get_region().structures_under("arteries_of_heart")
    assert part.view.look_at == arteries and part.highlight == arteries


def test_the_plan_tools_say_how_many_parts_a_plan_may_have():
    from app.agent_tools import ANSWER_STUDENT_TOOL, SUBMIT_PLAN_TOOL

    new_plan = ANSWER_STUDENT_TOOL["input_schema"]["properties"]["new_plan"]
    parts = SUBMIT_PLAN_TOOL["input_schema"]["properties"]["parts"]
    assert (new_plan["minItems"], new_plan["maxItems"], parts["minItems"], parts["maxItems"]) == (1, 5, 2, 5)
