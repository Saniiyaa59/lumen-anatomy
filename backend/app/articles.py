"""The atlas' description articles: look one up, or search them all for some words.

The articles are extracts of Wikipedia stored in the Z-Anatomy file and exported
to assets/text/z_anatomy_articles.jsonl. Search is plain word matching with
no AI and no index to build: about 3,700 articles is small enough to score on
the spot. It ranks passages, not whole articles, so the agent gets the
paragraph that matters and the link to cite.
"""

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.config import REPO_ROOT

ARTICLES_PATH = REPO_ROOT / "assets" / "text" / "z_anatomy_articles.jsonl"

WORD = re.compile(r"[a-z0-9]+")
# A section heading as the atlas writes it: "== Branches ==".
HEADING = re.compile(r"^=+[^=\n]+=+$")
# Words too common to tell one passage from another.
IGNORED = frozenset("a an and are as at be by for from in is it its of on or that the to which with".split())
# A word in the article's own title counts for this many in the text.
TITLE_WEIGHT = 3.0
# Passages shorter than this are headings or fragments, and are joined to what follows.
MIN_PASSAGE_CHARS = 120
MAX_PASSAGE_CHARS = 900
# Articles the caller says are about the region in hand score this much higher.
PREFERRED_WEIGHT = 1.5


class Article(BaseModel):
    key: str  # the name the atlas files it under; `article` in a session's source
    url: str | None  # where it came from, to show with anything taken from it
    text: str


class Passage(BaseModel):
    """A paragraph or two from an article that matched a search."""

    article: str
    url: str | None
    text: str
    score: float


def words(text: str) -> list[str]:
    """The words of some text, lower-cased, without the commonest ones. Plurals are cut to their stem, crudely."""
    found = []
    for word in WORD.findall(text.lower()):
        if word in IGNORED:
            continue
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        found.append(word)
    return found


def passages_of(text: str) -> list[str]:
    """Split an article into passages of a readable size, keeping a heading with the text under it."""
    passages: list[str] = []
    current = ""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        long_enough = len(current) >= MIN_PASSAGE_CHARS
        # A heading starts a new passage, so it stays with the text under it, not the text before it.
        if long_enough and (HEADING.match(block) or len(current) + len(block) > MAX_PASSAGE_CHARS):
            passages.append(current)
            current = ""
        current = f"{current}\n\n{block}" if current else block
    if current:
        passages.append(current)
    return passages


@dataclass
class _Indexed:
    article: Article
    title_words: frozenset[str]
    passages: list[tuple[str, list[str]]]  # each passage with its words


class Articles:
    def __init__(self, path: Path):
        self._articles: dict[str, Article] = {}
        same_as: dict[str, str] = {}
        with path.open(encoding="utf-8") as lines:
            for line in lines:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if "same_as" in entry:
                    same_as[entry["key"]] = entry["same_as"]
                else:
                    self._articles[entry["key"]] = Article(key=entry["key"], url=entry["source_url"], text=entry["text"])
        # The atlas files some articles under two names, e.g. one "atrium" article for both atria.
        self._same_as = same_as
        self._indexed: list[_Indexed] | None = None
        self._document_count: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._articles) + len(self._same_as)

    def keys(self) -> list[str]:
        return [*self._articles, *self._same_as]

    def get(self, key: str) -> Article | None:
        """An article by the name the atlas files it under."""
        return self._articles.get(self._same_as.get(key, key))

    def _index(self) -> list[_Indexed]:
        if self._indexed is None:
            self._indexed = []
            for article in self._articles.values():
                passages = [(passage, words(passage)) for passage in passages_of(article.text)]
                self._indexed.append(_Indexed(article, frozenset(words(article.key)), passages))
                for word in {w for _, passage_words in passages for w in passage_words} | set(words(article.key)):
                    self._document_count[word] = self._document_count.get(word, 0) + 1
        return self._indexed

    def search(self, query: str, limit: int = 5, prefer: frozenset[str] = frozenset()) -> list[Passage]:
        """The passages that best match some words, best first, at most one per article.

        A word counts for more the rarer it is across the articles, and for more
        again when it is in the article's title. Articles named in `prefer` are
        ranked higher: pass the articles of the region in hand, so that a search
        for "septum" during a heart session favours the heart's over the nose's.
        """
        indexed = self._index()
        wanted = list(dict.fromkeys(words(query)))
        if not wanted:
            return []
        total = len(indexed)
        weight = {word: math.log(1 + total / (1 + self._document_count.get(word, 0))) for word in wanted}
        preferred = {self._same_as.get(key, key) for key in prefer}
        best: list[Passage] = []
        for entry in indexed:
            title_score = sum(weight[word] for word in wanted if word in entry.title_words) * TITLE_WEIGHT
            top: tuple[float, str] | None = None
            for passage, passage_words in entry.passages:
                counts = {word: passage_words.count(word) for word in wanted}
                # Each further mention of a word adds less, and longer passages are not favoured for being long.
                body = sum(weight[word] * math.log(1 + count) for word, count in counts.items() if count)
                if body == 0 and title_score == 0:
                    continue
                matched = sum(1 for word in wanted if counts[word] or word in entry.title_words)
                score = (body + title_score) * matched / len(wanted)
                if entry.article.key in preferred:
                    score *= PREFERRED_WEIGHT
                if top is None or score > top[0]:
                    top = (score, passage)
            if top:
                best.append(Passage(article=entry.article.key, url=entry.article.url, text=top[1], score=round(top[0], 3)))
        best.sort(key=lambda passage: (-passage.score, passage.article))
        return best[:limit]


@lru_cache
def get_articles() -> Articles:
    """All the atlas' articles, loaded once."""
    return Articles(ARTICLES_PATH)
