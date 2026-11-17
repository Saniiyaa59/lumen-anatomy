"""Searching the student's notes and quoting a page of them.

Most tests give the pages as text. One reads a real PDF, made here by hand.
"""

import json

import pytest

from app import notes, sessions
from app.agent import Brief
from app.agent_tools import run_lookup
from test_agent import (  # the scripted stand-in for Claude, and its fixture
    DEMO_ITEM,
    PLAN,
    agent_with,
    articles,
    call,
    case_draft,
    client,
    demo_draft,
    region,
    reply,
    says,
    scripted_sessions,  # noqa: F401  (a fixture, used by name)
)

PAGES = [
    "Lecture 7: Coronary circulation\n\nThe heart is supplied by two coronary arteries that leave the aortic sinuses.",
    "The left anterior descending artery is called the widow maker. A blockage near its origin stops flow to most of the front wall of the left ventricle.\n\nIt gives off septal and diagonal branches.",
    "Right dominance is found in about 70% of people: the posterior descending artery comes from the right coro-\nnary artery.",
]
WIDOW = "The left anterior descending artery is called the widow maker."


def test_search_finds_the_page_that_says_it_best_first():
    found = notes.search(PAGES, "widow maker LAD blockage")
    assert found[0].page == 2 and "widow maker" in found[0].text
    assert notes.search(PAGES, "dominance")[0].page == 3
    assert notes.search(PAGES, "spleen") == [] and notes.search(PAGES, "the of") == []


def test_a_page_is_read_by_number_and_a_page_that_is_not_there_says_how_many_there_are():
    assert notes.read_page(PAGES, 1).startswith("Lecture 7")
    with pytest.raises(ValueError, match="pages 1 to 3"):
        notes.read_page(PAGES, 4)


def test_a_quote_must_be_on_its_page_but_case_spacing_and_a_broken_line_do_not_matter():
    assert notes.quoted_on(PAGES, 2, WIDOW.upper())
    assert notes.quoted_on(PAGES, 3, "the posterior descending artery comes from the right coronary artery")
    assert not notes.quoted_on(PAGES, 1, WIDOW)  # right words, wrong page
    assert not notes.quoted_on(PAGES, 9, WIDOW)


def test_the_notes_tools_run_and_say_so_when_there_are_no_pages():
    found = json.loads(run_lookup("search_notes", {"query": "widow maker"}, region, articles, PAGES))
    assert found[0]["page"] == 2
    page = json.loads(run_lookup("read_notes_page", {"page": 3}, region, articles, PAGES))
    assert "Right dominance" in page["text"]
    assert "no notes whose text could be read" in run_lookup("search_notes", {"query": "widow"}, region, articles, [])


def statement_from_notes(**source):
    draft = demo_draft()
    draft["statements"] = [{"text": "Your notes call it the widow maker.", "source": {"type": "notes", **source}}]
    return draft


def test_a_statement_can_quote_a_page_of_the_notes_and_carries_the_file_and_page():
    agent, _ = agent_with(submit_demonstration=[reply(call("submit_demonstration", **statement_from_notes(page=2, quote=WIDOW)))])
    part = agent.build(Brief(request="x", notes_file="lecture_07.pdf", pages=PAGES), DEMO_ITEM)
    assert part.statements[0].source.model_dump() == {"type": "notes", "file": "lecture_07.pdf", "page": 2}


@pytest.mark.parametrize(
    ("source", "pages", "reason"),
    [
        ({"page": 1, "quote": WIDOW}, PAGES, "not on page 1 of the notes word for word"),
        ({"page": 7, "quote": WIDOW}, PAGES, "the notes have pages 1 to 3"),
        ({"page": 2, "quote": "Widow."}, PAGES, "full sentence"),
        ({"page": 2, "quote": WIDOW}, [], "cite a fact by its number"),
    ],
)
def test_a_notes_quote_that_does_not_check_out_is_sent_back(source, pages, reason):
    good = demo_draft()
    agent, llm = agent_with(submit_demonstration=[reply(call("submit_demonstration", **statement_from_notes(**source))), reply(call("submit_demonstration", **good))])
    agent.build(Brief(request="x", notes_file="lecture_07.pdf", pages=pages), DEMO_ITEM)
    sent_back = llm.last_results("submit_demonstration")[0]
    assert sent_back["is_error"] is True and reason in sent_back["content"]


def test_the_agent_is_told_the_notes_can_be_searched():
    agent, llm = agent_with(submit_demonstration=[reply(call("submit_demonstration", **demo_draft()))])
    agent.build(Brief(request="x", notes_file="lecture_07.pdf", pages=PAGES), DEMO_ITEM)
    assert "The notes have 3 pages. Search them with search_notes" in llm.asked[0][1][0]["content"]
    assert "Look in the notes before the atlas" in agent.system


def test_the_pages_are_read_at_upload_and_survive_a_restart(scripted_sessions, monkeypatch):
    monkeypatch.setattr(sessions, "read_pages", lambda pdf: PAGES)
    scripted_sessions(notes=[reply(says("NONE"))], submit_plan=[reply(call("submit_plan", **PLAN))], submit_demonstration=[reply(call("submit_demonstration", **demo_draft()))], submit_click_case=[reply(call("submit_click_case", **case_draft()))])
    pdf = "JVBERi0xLjcKJSBzdGFuZC1pbiBub3Rlcwo="  # "%PDF-1.7\n% stand-in notes\n"
    session_id = client.post("/api/sessions", json={"request": "coronary arteries", "notes": {"filename": "lecture_07.pdf", "data": pdf}}).json()["session_id"]
    for future in list(sessions._sessions[session_id].tutor.building.values()):
        future.exception()
    sessions._sessions.clear()
    client.get(f"/api/sessions/{session_id}")
    brief = sessions._sessions[session_id].tutor.brief
    assert (brief.notes_file, brief.pages) == ("lecture_07.pdf", PAGES)


def pdf_of(pages: list[list[str]]) -> bytes:
    """A small PDF with one page per list, each line of text on its own line of the page."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        text = b"BT /F1 12 Tf 72 720 Td 14 TL " + b" ".join(b"(" + line.encode() + b") '" for line in lines) + b" ET"
        objects.append(b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream")
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % len(objects))
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    start = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, start)
    return bytes(out)


def test_the_text_of_each_page_of_a_real_pdf_is_read_and_can_be_quoted():
    pytest.importorskip("pypdf")
    pdf = pdf_of([["Lecture 7: Coronary circulation"], ["The LAD is called the widow maker.", "It gives off septal branches."]])
    pages = notes.read_pages(pdf)
    assert len(pages) == 2 and "Coronary circulation" in pages[0]
    assert notes.quoted_on(pages, 2, "The LAD is called the widow maker.")
    assert notes.search(pages, "septal branches")[0].page == 2


def test_a_pdf_that_cannot_be_read_gives_no_pages_rather_than_failing():
    assert notes.read_pages(b"%PDF-1.7\n% not really a PDF\n") == []


def test_the_agent_is_told_a_statement_says_only_what_its_source_says():
    # A live answer cited page 2 for "You will use it in the patient case at the end of this session."
    agent, _ = agent_with()
    assert "A statement says only what its source says" in agent.system
    assert "leave remarks about the session out" in agent.system
