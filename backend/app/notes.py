"""The student's notes, page by page: read once at upload, then searched like the atlas.

When a session starts with notes, Claude reads the whole PDF once and lists the
facts that matter for the request (Agent.read_notes); those guide the plan. This
module keeps the text of every page as well, so that later, while building a
part or answering in chat, the agent can search the notes for something the
first read left out and quote a page word for word. A quote is checked against
the page's text, as an atlas quote is checked against its article.

Reading a page's text needs pypdf. Without it the pages are empty, search says
so, and the agent cites the facts from the first read instead.
"""

import io
import logging
import math
import re

from pydantic import BaseModel

from app.articles import passages_of, words

log = logging.getLogger("uvicorn.error")

MAX_NOTES_CHARS = 400_000  # all pages together; more than this is cut, with a note in the log
SEARCH_LIMIT = 4  # passages returned by one search
READ_LIMIT = 8000  # characters of one page returned when the agent reads it


class NotePassage(BaseModel):
    page: int  # counted from 1, as the student's PDF viewer shows it
    text: str
    score: float


def read_pages(pdf: bytes) -> list[str]:
    """The text of each page of a PDF, in order. Empty when pypdf is missing or the PDF has no text layer (a scan)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        log.warning("pypdf is not installed, so the notes can't be searched; the agent will use only the facts read when the session started.")
        return []
    try:
        reader = PdfReader(io.BytesIO(pdf))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as error:  # a PDF pypdf can't parse is not worth failing the session over
        log.warning("Could not read the notes' text (%s); the agent will use only the facts read when the session started.", error)
        return []
    kept, total = [], 0
    for text in pages:
        text = text[: max(0, MAX_NOTES_CHARS - total)]
        total += len(text)
        kept.append(text)
    if total >= MAX_NOTES_CHARS:
        log.warning("The notes are longer than %d characters; the rest is not searched.", MAX_NOTES_CHARS)
    return kept if any(kept) else []


def search(pages: list[str], query: str, limit: int = SEARCH_LIMIT) -> list[NotePassage]:
    """The passages of the notes that best match some words, best first.

    Scored as the atlas search scores articles: a word counts for more the rarer
    it is across the notes, and each further mention adds less.
    """
    wanted = list(dict.fromkeys(words(query)))
    if not wanted:
        return []
    chunks = [(number, passage, words(passage)) for number, text in enumerate(pages, start=1) for passage in passages_of(text)]
    if not chunks:
        return []
    count = {word: sum(1 for _, _, found in chunks if word in found) for word in wanted}
    weight = {word: math.log(1 + len(chunks) / (1 + count[word])) for word in wanted}
    found: list[NotePassage] = []
    for number, passage, passage_words in chunks:
        mentions = {word: passage_words.count(word) for word in wanted}
        body = sum(weight[word] * math.log(1 + n) for word, n in mentions.items() if n)
        if body:
            matched = sum(1 for n in mentions.values() if n)
            found.append(NotePassage(page=number, text=passage, score=round(body * matched / len(wanted), 3)))
    found.sort(key=lambda passage: (-passage.score, passage.page))
    return found[:limit]


def read_page(pages: list[str], number: int) -> str:
    if not 1 <= number <= len(pages):
        raise ValueError(f"the notes have pages 1 to {len(pages)}" if pages else "the notes' text could not be read")
    text = pages[number - 1]
    if len(text) > READ_LIMIT:
        text = f"{text[:READ_LIMIT]}\n\n[The page continues for {len(text) - READ_LIMIT} more characters. Use search_notes to find passages further on.]"
    return text


def squash(text: str) -> str:
    """Text with case, spacing and line-end hyphens ironed out, for comparing a quote with a page.

    A PDF's text breaks lines where the page did ("coro-\\nnary"), which the agent won't copy.
    """
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def quoted_on(pages: list[str], number: int, quote: str) -> bool:
    """Whether a quote is on that page, word for word (case and spacing aside)."""
    return 1 <= number <= len(pages) and squash(quote) in squash(pages[number - 1])
