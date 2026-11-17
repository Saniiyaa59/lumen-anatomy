"""The measuring functions, checked against the exported heart.

Several numbers here were first found by hand while building the sample
session (see docs/decisions.md, 2026-11-14). The functions must reproduce them.
"""

import pytest

from app import measure
from app.measure import Stretch
from app.region import get_region

region = get_region()

LAD = "anterior_interventricular_artery"
LCA = "left_coronary_artery"
CIRCUMFLEX = "circumflex_artery_of_heart"
SEPTAL = "septal_branches_of_anterior_interventricular_artery"
PROXIMAL_LAD = [Stretch(piece=f"{LAD}.0", start=0, to=0.0465)]


def view(result, side):
    return next(v for v in result.sides if v.side == side)


# The region itself


def test_region_knows_what_sits_inside_what():
    assert region.ancestors(SEPTAL) == [LAD, LCA, "arteries_of_heart", "arterial_system"]
    assert region.vessel_of(f"{LAD}.3") == LAD
    assert "left_coronary_leaflet" in region.structures_under("valvular_complex_of_heart")


def test_a_hide_list_may_mix_structures_and_groups():
    covered = region.expand(["left_atrium", "cardiac_veins", "left_atrium"])
    assert covered[0] == "left_atrium"
    assert "great_cardiac_vein" in covered and "coronary_sinus" in covered
    assert len(covered) == len(set(covered)) == 7


def test_a_point_along_a_piece_lies_on_its_centre_line():
    path = region.path(f"{LAD}.0")
    assert path.length == pytest.approx(region.pieces[f"{LAD}.0"].length, abs=1e-4)
    assert path.point_at(0) == pytest.approx(path.points[0])
    assert path.point_at(path.length) == pytest.approx(path.points[-1])
    assert path.radius_at(0) > path.radius_at(path.length) > 0


# describe


def test_describe_a_vessel_lists_its_centre_line():
    described = measure.describe(region, LAD)
    assert described.kind == "tube"
    assert described.inside[:2] == ["Left coronary artery", "Arteries of heart"]
    assert described.members == [SEPTAL]
    trunk = described.pieces[0]
    assert (trunk.id, trunk.joins) == (f"{LAD}.0", f"{LCA}.0")
    assert trunk.length == pytest.approx(0.1146, abs=1e-4)
    assert len(described.pieces) == 6


def test_describe_falls_back_to_the_article_of_what_a_structure_is_part_of():
    """The atlas has no article for this artery under its own name, but has one for its parent."""
    described = measure.describe(region, LAD)
    assert (described.article, described.article_is_own) == ("Left coronary artery", False)
    own = measure.describe(region, LCA)
    assert (own.article, own.article_is_own) == ("Left coronary artery", True)


def test_describe_a_group_lists_its_structures():
    described = measure.describe(region, "aortic_valve")
    assert described.kind == "group"
    assert sorted(described.members) == ["left_coronary_leaflet", "non_coronary_leaflet", "right_coronary_leaflet"]
    assert described.pieces == []


def test_describe_rejects_an_unknown_id():
    with pytest.raises(ValueError, match="not a structure or a group"):
        measure.describe(region, "spleen")


# branches_of


def test_branches_come_in_order_and_the_first_septal_branch_leaves_at_46_5_mm():
    branches = measure.branches_of(region, f"{LAD}.0")
    assert [b.at for b in branches] == sorted(b.at for b in branches)
    assert len(branches) == 7
    first = branches[0]
    assert (first.structure, first.named) == (SEPTAL, True)
    assert first.at == pytest.approx(0.0465, abs=1e-4)


def test_unnamed_branches_of_the_same_vessel_are_marked():
    branches = measure.branches_of(region, f"{LAD}.0")
    unnamed = [b for b in branches if not b.named]
    assert len(unnamed) == 4
    assert all(b.structure == LAD for b in unnamed)


def test_the_left_coronary_artery_divides_into_two_at_its_end():
    branches = measure.branches_of(region, f"{LCA}.0")
    assert sorted(b.structure for b in branches) == [LAD, CIRCUMFLEX]
    assert all(b.at == pytest.approx(region.pieces[f"{LCA}.0"].length, abs=1e-4) for b in branches)


def test_a_piece_with_no_branches_has_none():
    assert measure.branches_of(region, f"{SEPTAL}.1") == []
    with pytest.raises(ValueError, match="not a centre-line piece"):
        measure.branches_of(region, "aorta.9")


# beyond


def test_beyond_covers_the_rest_of_the_piece_and_every_later_branch():
    cut = measure.beyond(region, f"{LAD}.0", 0.03)
    assert cut.stretches[0] == Stretch(piece=f"{LAD}.0", start=0.03, to=region.pieces[f"{LAD}.0"].length)
    assert len(cut.stretches) == 12
    assert cut.structures == [LAD, SEPTAL]
    assert cut.length == pytest.approx(sum(s.to - s.start for s in cut.stretches))


def test_beyond_leaves_out_branches_that_left_earlier():
    after_first_septal = measure.beyond(region, f"{LAD}.0", 0.047)
    pieces = [s.piece for s in after_first_septal.stretches]
    assert f"{SEPTAL}.2" not in pieces  # left at 46.5 mm
    assert f"{SEPTAL}.3" not in pieces  # a branch of that one
    assert f"{LAD}.5" in pieces  # leaves at 48.9 mm


def test_beyond_the_start_of_the_left_coronary_artery_is_its_whole_tree():
    cut = measure.beyond(region, f"{LCA}.0", 0)
    assert set(cut.structures) == {LCA, LAD, SEPTAL, CIRCUMFLEX}
    assert "right_coronary_artery" not in cut.structures


def test_beyond_rejects_a_place_off_the_piece():
    with pytest.raises(ValueError, match="outside"):
        measure.beyond(region, f"{LAD}.0", 0.5)


# route


def test_route_follows_the_single_path_to_a_branch():
    path = measure.route(region, f"{LCA}.0", 0, f"{CIRCUMFLEX}.0", 0.05)
    lca_length = region.pieces[f"{LCA}.0"].length
    assert [(s.piece, s.start) for s in path.segments] == [(f"{LCA}.0", 0), (f"{CIRCUMFLEX}.0", 0)]
    assert [s.to for s in path.segments] == pytest.approx([lca_length, 0.05], abs=1e-4)
    assert path.length == pytest.approx(lca_length + 0.05, abs=1e-4)


def test_route_along_one_piece():
    path = measure.route(region, f"{LAD}.0", 0.01, f"{LAD}.0", 0.04)
    assert path.segments == [Stretch(piece=f"{LAD}.0", start=0.01, to=0.04)]


def test_route_refuses_to_run_back_toward_the_trunk_or_across_to_another_tree():
    with pytest.raises(ValueError, match="pulse can't run there"):
        measure.route(region, f"{LAD}.0", 0.05, f"{LCA}.0", 0.01)
    with pytest.raises(ValueError, match="pulse can't run there"):
        measure.route(region, f"{LAD}.0", 0.05, f"{LAD}.0", 0.01)
    with pytest.raises(ValueError, match="pulse can't run there"):
        measure.route(region, f"{LCA}.0", 0, "right_coronary_artery.0", 0.02)


# what_hides: what is in the way of seeing something


def test_the_start_of_the_anterior_interventricular_artery_is_hidden_from_every_side():
    """Found by hand in the browser: the sample case's answer could not be clicked from the front."""
    result = measure.what_hides(region, stretches=PROXIMAL_LAD)
    assert result.points_tested >= 10
    assert all(v.visible < 0.25 for v in result.sides)
    assert view(result, "left").blockers[0].structure == "left_atrium"
    assert {"left_atrium", "right_ventricle"} <= set(view(result, "anterior").hide_to_see_all)


def test_hiding_what_the_sample_hides_shows_it_from_the_left():
    """The view the sample's case uses: from the left with the left atrium, pulmonary trunk and cardiac veins hidden."""
    result = measure.what_hides(
        region,
        stretches=PROXIMAL_LAD,
        look_at=[LCA, LAD, CIRCUMFLEX],
        hidden=["pulmonary_trunk", "left_atrium", "cardiac_veins"],
    )
    assert result.sides[0].side == "left"
    assert view(result, "left").visible > 0.9
    assert "left_atrium" not in view(result, "left").hide_to_see_all
    assert view(result, "anterior").visible < 0.6  # the right ventricle is still in front


def test_hide_to_see_all_is_enough_to_see_all():
    first = measure.what_hides(region, stretches=PROXIMAL_LAD, sides=["left"])
    needed = view(first, "left").hide_to_see_all
    assert needed
    after = measure.what_hides(region, stretches=PROXIMAL_LAD, sides=["left"], hidden=needed)
    assert view(after, "left").visible == 1
    assert view(after, "left").blockers == []


def test_the_left_coronary_trunk_cannot_be_seen_from_any_side():
    """It starts inside the aorta's tube: every side needs at least the aorta hidden."""
    result = measure.what_hides(region, stretches=[Stretch(piece=f"{LCA}.0", start=0, to=0.0165)])
    assert all(v.visible == 0 for v in result.sides)
    assert sum("ascending_aorta" in v.hide_to_see_all for v in result.sides) >= 5


def test_an_exposed_artery_is_seen_from_the_front():
    result = measure.what_hides(region, stretches=[Stretch(piece="right_coronary_artery.0", start=0.03, to=0.08)], sides=["anterior", "posterior"])
    assert result.sides[0].side == "anterior"
    assert view(result, "anterior").visible > 0.7
    assert view(result, "posterior").visible < 0.2


def test_whole_structures_can_be_looked_for_too():
    covered = measure.what_hides(region, structures=["left_coronary_leaflet"], sides=["superior"])
    assert view(covered, "superior").visible < 0.2
    great_vessels = ["ascending_aorta", "aortic_arch", "pulmonary_trunk", "bifurcation_of_pulmonary_trunk", "left_atrium"]
    opened = measure.what_hides(region, structures=["left_coronary_leaflet"], sides=["superior"], hidden=great_vessels)
    assert view(opened, "superior").visible > view(covered, "superior").visible


def test_several_threads_can_ask_what_hides_something_at_once():
    """Parts are built on background threads. The search tree behind the ray casts is not safe to
    share, so casts must take turns; without that this raised or crashed the process."""
    from concurrent.futures import ThreadPoolExecutor

    def ask(_):
        return measure.what_hides(region, stretches=PROXIMAL_LAD).model_dump()

    expected = ask(None)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(ask, range(24)))
    assert all(result == expected for result in results)


def test_blockers_are_listed_most_blocking_first_with_their_names():
    blockers = view(measure.what_hides(region, stretches=PROXIMAL_LAD, sides=["left"]), "left").blockers
    assert [b.share for b in blockers] == sorted((b.share for b in blockers), reverse=True)
    assert blockers[0].name == "Left atrium"
    assert all(0 < b.share <= 1 for b in blockers)


def test_what_hides_rejects_nothing_to_look_for_and_unknown_ids():
    with pytest.raises(ValueError, match="nothing to look for"):
        measure.what_hides(region)
    with pytest.raises(ValueError, match="not structures"):
        measure.what_hides(region, structures=["spleen"])
    with pytest.raises(ValueError, match="outside"):
        measure.what_hides(region, stretches=[Stretch(piece=f"{LAD}.0", start=0, to=0.9)])


# choose_view: the side to look from and what to hide


def test_hiding_a_chamber_costs_most_and_veins_leaflets_and_great_vessels_least():
    assert measure.hide_cost(region, "left_atrium") == measure.HIDE_CHAMBER
    for free in ("great_cardiac_vein", "left_coronary_leaflet", "ascending_aorta", "pulmonary_trunk", "anterior_papillary_muscle_of_right_ventricle"):
        assert measure.hide_cost(region, free) == measure.HIDE_FREELY, free
    assert measure.hide_cost(region, "circumflex_artery_of_heart") == measure.HIDE_OTHER


def test_the_start_of_the_anterior_interventricular_artery_is_shown_from_the_left_with_the_left_atrium_hidden():
    # Found by hand while playing the sample: it is behind the left atrium and the pulmonary trunk from the front.
    choice = measure.choose_view(region, 0.9, stretches=PROXIMAL_LAD)
    assert choice.side == "left" and "left_atrium" in choice.added and choice.visible >= 0.9
    check = measure.what_hides(region, stretches=PROXIMAL_LAD, hidden=choice.hide, sides=["left"])
    assert check.sides[0].visible == pytest.approx(choice.visible)


def test_a_view_that_already_works_needs_nothing_hidden_and_what_was_hidden_is_kept():
    choice = measure.choose_view(region, 0.5, stretches=[Stretch(piece="right_coronary_artery.0", start=0.03, to=0.08)], hidden=["cardiac_veins"])
    assert choice.side == "anterior" and choice.added == [] and choice.hide == ["cardiac_veins"]


def test_once_enough_shows_what_is_free_to_hide_goes_too():
    leaflets = ["left_coronary_leaflet", "right_coronary_leaflet", "non_coronary_leaflet"]
    choice = measure.choose_view(region, 0.3, structures=leaflets)
    assert choice.visible > 0.5  # well past the 30% needed
    assert all(measure.hide_cost(region, i) == measure.HIDE_FREELY for i in choice.added)


def test_the_subject_is_never_hidden_so_some_views_cannot_be_had():
    chambers = ["left_atrium", "left_ventricle", "right_atrium", "right_ventricle"]
    choice = measure.choose_view(region, 0.9, structures=chambers)
    assert choice.side is None and choice.added == [] and choice.hide == []
    assert set(choice.sides[0].still_in_front) <= set(chambers) and choice.sides[0].still_in_front
    assert all(not set(side.added) & set(chambers) for side in choice.sides)


def test_what_is_framed_is_hidden_only_when_it_must_be():
    # Framing the aorta points the camera at the valve; when it was never hidden, a ventricle went instead.
    leaflets = ["left_coronary_leaflet", "right_coronary_leaflet", "non_coronary_leaflet"]
    choice = measure.choose_view(region, 0.3, structures=leaflets, look_at=["ascending_aorta", *leaflets])
    assert choice.side is not None
    assert not {"left_atrium", "left_ventricle", "right_atrium", "right_ventricle"} & set(choice.added)
    # A framed vessel that isn't in the way stays.
    rca = [Stretch(piece="right_coronary_artery.0", start=0.03, to=0.08)]
    assert measure.choose_view(region, 0.5, stretches=rca, look_at=["right_coronary_artery", "ascending_aorta"]).added == []


def test_the_side_asked_for_wins_a_tie():
    rca = [Stretch(piece="right_coronary_artery.0", start=0.03, to=0.08)]
    free = [c.side for c in measure.choose_view(region, 0.1, stretches=rca).sides if c.passes and c.cost == 0]
    assert len(free) > 1
    assert measure.choose_view(region, 0.1, stretches=rca, prefer=free[-1]).side == free[-1]
