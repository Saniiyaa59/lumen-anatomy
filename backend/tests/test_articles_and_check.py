import copy
import json

from app.articles import Articles, get_articles, passages_of, words
from app.region import get_region
from app.session_check import check_part, check_session
from app.session_schemas import RecordedSession
from app.sessions import SAMPLE_PATH, load_sample

region = get_region()
articles = get_articles()
SAMPLE = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def changed(change) -> RecordedSession:
    """The sample with one change made to it."""
    session = copy.deepcopy(SAMPLE)
    change(session)
    return RecordedSession.model_validate(session)


# Articles


def test_every_article_can_be_looked_up_including_ones_filed_under_two_names():
    assert len(articles) == 3821
    left, right = articles.get("Left atrium"), articles.get("Right atrium")
    assert left is not None and left is right  # the atlas has one "atrium" article for both
    assert articles.get("Left coronary artery").url == "https://en.wikipedia.org/wiki/Left_coronary_artery"
    assert articles.get("Not an article") is None


def test_words_drop_the_commonest_and_cut_plurals():
    assert words("The branches of the Arteries, and its Vessels.") == ["branche", "artery", "vessel"]
    assert words("of the and") == []


def test_passages_keep_a_heading_with_the_text_under_it():
    text = "TITLE\n\n\nFirst paragraph. " + "x" * 200 + "\n\n== Branches ==\n\nSecond paragraph. " + "y" * 800
    passages = passages_of(text)
    assert passages[0].startswith("TITLE")
    assert any(p.startswith("== Branches ==") and "Second paragraph" in p for p in passages)


def test_search_finds_the_article_a_question_is_about():
    top = articles.search("coronary dominance posterior descending artery")
    assert top[0].article == "Coronary circulation"
    assert "dominan" in top[0].text
    assert top[0].url == "https://en.wikipedia.org/wiki/Coronary_circulation"
    assert [p.score for p in top] == sorted((p.score for p in top), reverse=True)


def test_search_returns_one_passage_per_article_up_to_the_limit():
    found = articles.search("left coronary artery bifurcation", limit=3)
    assert len(found) == 3
    assert len({p.article for p in found}) == 3
    assert found[0].article == "Left coronary artery"


def test_search_reaches_an_article_filed_under_another_name_than_the_model_uses():
    """The model calls it the anterior interventricular artery; the article is "Left anterior descending artery"."""
    found = [p.article for p in articles.search("widow maker anterior descending artery blockage")]
    assert found[0] == "Left anterior descending artery"


def test_search_can_prefer_the_articles_of_the_region_in_hand():
    plain = [p.article for p in articles.search("septum", limit=5)]
    preferred = [p.article for p in articles.search("septum", limit=5, prefer=region.article_keys)]
    assert "Interatrial septum" in region.article_keys
    assert preferred.index("Interatrial septum") <= plain.index("Interatrial septum") if "Interatrial septum" in plain else True
    assert preferred[0] in region.article_keys


def test_search_with_nothing_to_look_for_finds_nothing():
    assert articles.search("the of and") == []
    assert articles.search("zzzzqqqq") == []


def test_articles_can_be_read_from_any_file(tmp_path):
    path = tmp_path / "articles.jsonl"
    path.write_text(
        '{"key": "Heart", "source_url": "https://example.org/heart", "text": "The heart pumps blood."}\n'
        '{"key": "Cor", "same_as": "Heart"}\n',
        encoding="utf-8",
    )
    small = Articles(path)
    assert len(small) == 2
    assert small.get("Cor").key == "Heart"
    assert small.search("pumps blood")[0].article == "Heart"


# Checking a session against the model


def test_the_sample_refers_only_to_real_things():
    assert check_session(load_sample(), region, articles) == []
    assert [check_part(part, region, articles) for part in load_sample().parts] == [[], [], [], [], []]


def test_check_names_a_structure_that_does_not_exist():
    session = changed(lambda s: s["parts"][0]["highlight"].append("spleen"))
    assert check_session(session, region) == ['session.parts[0].highlight[2]: "spleen" is not a structure in this region']


def test_hide_may_name_a_group_but_other_lists_may_not():
    assert check_session(changed(lambda s: s["parts"][0].update(hide=["cardiac_veins"])), region) == []
    assert check_session(changed(lambda s: s["parts"][0].update(hide=["spleen"])), region) == [
        'session.parts[0].hide[0]: "spleen" is not a structure or a group in this region'
    ]
    assert check_session(changed(lambda s: s["parts"][0]["view"].update(look_at=["cardiac_veins"])), region) == [
        'session.parts[0].view.look_at[0]: "cardiac_veins" is not a structure in this region'
    ]


def test_check_names_a_piece_that_does_not_exist_and_a_distance_off_its_piece():
    missing = changed(lambda s: s["parts"][1]["from"].update(piece="left_coronary_artery.7"))
    assert check_session(missing, region) == ['session.parts[1].from.piece: "left_coronary_artery.7" is not a centre-line piece in this region']

    too_far = changed(lambda s: s["parts"][2]["track"].update(to=0.5))
    problems = check_session(too_far, region)
    assert len(problems) == 1
    assert problems[0].startswith("session.parts[2].track: from 0.0 to 0.5 is not a stretch of the piece")


def test_check_refuses_a_pulse_that_would_run_back_toward_the_trunk():
    def backwards(s):
        s["parts"][1]["from"] = {"piece": "anterior_interventricular_artery.0", "at": 0.05}
        s["parts"][1]["to"] = {"piece": "left_coronary_artery.0", "at": 0.01}

    assert check_session(changed(backwards), region) == [
        "session.parts[1].to: is not further along the vessel than the start, so a pulse can't run there"
    ]
    onto_a_branch = changed(lambda s: s["parts"][1].update(to={"piece": "circumflex_artery_of_heart.0", "at": 0.05}))
    assert check_session(onto_a_branch, region) == []


def test_check_catches_an_article_that_does_not_exist_or_a_link_that_is_not_its_own():
    """The browser cannot make this check: the articles are too large to load there."""
    invented = changed(lambda s: s["parts"][0]["statements"][0]["source"].update(article="Coronary arteries of the heart"))
    assert check_session(invented, region, articles) == [
        'session.parts[0].statements[0].source.article: "Coronary arteries of the heart" is not an article in the atlas'
    ]
    assert check_session(invented, region) == []  # without the articles, sources are not checked

    wrong_link = changed(lambda s: s["parts"][0]["statements"][0]["source"].update(url="https://en.wikipedia.org/wiki/Heart"))
    assert check_session(wrong_link, region, articles) == [
        "session.parts[0].statements[0].source.url: must be the article's own link, https://en.wikipedia.org/wiki/Left_coronary_artery"
    ]


def test_check_lists_every_problem_and_covers_feedback_zones_and_the_summary():
    def several(s):
        s["parts"][2]["zones"][0]["regions"][0]["piece"] = "nowhere.0"
        s["parts"][3]["feedback"]["near_misses"][2]["structures"] = ["spleen"]
        s["summary"]["sources"][0]["article"] = "Nothing"

    problems = check_session(changed(several), region, articles)
    assert [p.split(":")[0] for p in problems] == [
        "session.parts[2].zones[0].regions[0].piece",
        "session.parts[3].feedback.near_misses[2].structures[0]",
        "session.summary.sources[0].article",
    ]


def test_check_refuses_a_session_for_another_region():
    assert check_session(changed(lambda s: s.update(region="arm")), region)[0] == 'session.region: must be "heart", the region being checked against'
