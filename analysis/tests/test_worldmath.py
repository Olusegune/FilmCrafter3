"""The geometry of a set, checked against hand-worked numbers: the pinhole projection, parallax, yaw and pitch, the picture a flat layer makes, and the set's state over time."""
import math

import numpy as np
import pytest

from filmcrafter_engine import worldmath as WM

SIZE = (600, 400)
CAM = {"x": 0.0, "y": 1.5, "z": 0.0, "yaw": 0.0, "pitch": 0.0, "fov": 60.0}


def test_a_point_straight_ahead_lands_in_the_middle_and_the_focal_length_is_from_the_field_of_view():
    assert WM.focal_px(600, 60) == pytest.approx(300 / math.tan(math.radians(30)))
    sx, sy, depth = WM.project((0.0, 1.5, 5.0), CAM, SIZE)
    assert (sx, sy, depth) == (pytest.approx(300.0), pytest.approx(200.0), pytest.approx(5.0))


def test_a_point_to_the_right_and_above_lands_right_and_above_by_the_pinhole_rule():
    f = WM.focal_px(600, 60)
    sx, sy, _ = WM.project((1.0, 2.5, 4.0), CAM, SIZE)
    assert sx == pytest.approx(300 + f * 1.0 / 4.0) and sy == pytest.approx(200 - f * 1.0 / 4.0)
    sx2, _, _ = WM.project((-1.0, 1.5, 4.0), CAM, SIZE)
    assert sx2 < 300


def test_things_behind_or_at_the_camera_are_not_projected():
    assert WM.project((0, 1.5, -1.0), CAM, SIZE) is None and WM.project((0, 1.5, 0.0), CAM, SIZE) is None and WM.project((0, 1.5, WM.NEAR), CAM, SIZE) is None
    assert WM.project((0, 1.5, 0.2), CAM, SIZE) is not None


def test_parallax_near_things_move_more_than_far_things_when_the_camera_moves_sideways():
    near, far = (0.0, 1.5, 2.0), (0.0, 1.5, 10.0)
    cam2 = {**CAM, "x": 1.0}
    shift = lambda p: WM.project(p, CAM, SIZE)[0] - WM.project(p, cam2, SIZE)[0]
    f = WM.focal_px(600, 60)
    assert shift(near) == pytest.approx(f * 1.0 / 2.0) and shift(far) == pytest.approx(f * 1.0 / 10.0)
    assert shift(near) == pytest.approx(5 * shift(far))


def test_yaw_turns_the_view_and_a_quarter_turn_puts_a_thing_on_the_right_in_front():
    right = (5.0, 1.5, 0.0)
    assert WM.project(right, CAM, SIZE) is None                                                          # level with the camera and to its side: not in front
    cam = {**CAM, "yaw": 90.0}
    sx, sy, depth = WM.project(right, cam, SIZE)
    assert (sx, sy, depth) == (pytest.approx(300.0), pytest.approx(200.0), pytest.approx(5.0))           # turning right 90 degrees looks at it
    assert WM.project((-5.0, 1.5, 0.0), cam, SIZE) is None


def test_pitch_looks_up_and_a_thing_above_comes_toward_the_middle():
    p = (0.0, 6.5, 5.0)
    y_flat = WM.project(p, CAM, SIZE)[1]
    y_up = WM.project(p, {**CAM, "pitch": 30.0}, SIZE)[1]
    assert y_up > y_flat and 0 < y_up < 400                                                              # looking up moves it down the picture, toward the middle


def test_the_same_inputs_always_give_the_same_answer():
    a = [WM.project((i * 0.37, 1.0 + i * 0.1, 3 + i), {**CAM, "yaw": 12.5}, SIZE) for i in range(5)]
    b = [WM.project((i * 0.37, 1.0 + i * 0.1, 3 + i), {**CAM, "yaw": 12.5}, SIZE) for i in range(5)]
    assert a == b


def test_a_layers_corners_stand_on_its_anchor_and_a_homography_maps_points_exactly():
    c = WM.layer_corners({"x": 2.0, "y": 0.0, "z": 6.0, "width": 4.0, "height": 3.0})
    assert c == [(0.0, 3.0, 6.0), (4.0, 3.0, 6.0), (4.0, 0.0, 6.0), (0.0, 0.0, 6.0)]
    src = [(0, 0), (10, 0), (10, 10), (0, 10)]
    dst = [(5, 5), (25, 8), (27, 30), (3, 22)]
    H = WM.homography(src, dst)
    for (x, y), (u, v) in zip(src, dst):
        w = H[2, 0] * x + H[2, 1] * y + H[2, 2]
        assert ((H[0, 0] * x + H[0, 1] * y + H[0, 2]) / w, (H[1, 0] * x + H[1, 1] * y + H[1, 2]) / w) == (pytest.approx(u), pytest.approx(v))


def solid(w=40, h=30, colour=(1.0, 0.0, 0.0)):
    a = np.zeros((h, w, 4), np.float32)
    a[..., :3], a[..., 3] = colour, 1.0
    return a


def test_a_drawn_layer_lands_where_the_projection_says_and_at_the_size_it_says():
    layer = {"x": 0.0, "y": 0.0, "z": 5.0, "width": 2.0, "height": 3.0}
    out = WM.draw_layer(solid(), layer, CAM, SIZE)
    ys, xs = np.nonzero(out[..., 3] > 0.5)
    f = WM.focal_px(600, 60)
    left, right = 300 - f * 1.0 / 5.0, 300 + f * 1.0 / 5.0
    top, bottom = 200 - f * (3.0 - 1.5) / 5.0, 200 + f * 1.5 / 5.0
    assert xs.min() == pytest.approx(left, abs=1.5) and xs.max() == pytest.approx(right, abs=1.5) and ys.min() == pytest.approx(top, abs=1.5) and ys.max() == pytest.approx(bottom, abs=1.5)
    assert out[..., 0][out[..., 3] > 0.9].min() > 0.99 and out[..., 1][out[..., 3] > 0.9].max() < 0.01        # the colour is its own, with no halo from the empty area


def test_a_layer_behind_the_camera_or_outside_the_view_is_not_drawn():
    assert WM.draw_layer(solid(), {"x": 0, "y": 0, "z": -3.0, "width": 2, "height": 2}, CAM, SIZE) is None
    assert WM.draw_layer(solid(), {"x": 50.0, "y": 0, "z": 5.0, "width": 2, "height": 2}, CAM, SIZE) is None


def test_a_soft_edged_layer_keeps_its_straight_alpha_after_resampling():
    a = solid(64, 64)
    a[..., 3] = np.linspace(0, 1, 64, dtype=np.float32)[None, :]
    out = WM.draw_layer(a, {"x": 0.0, "y": 0.0, "z": 4.0, "width": 2.0, "height": 2.0}, CAM, SIZE)
    solid_px = out[..., 3] > 0.5
    assert np.allclose(out[..., :3][solid_px], [1.0, 0.0, 0.0], atol=0.02)                                 # colour is not darkened by the transparent edge (premultiplied resampling)


def test_coverage_and_the_gap_a_move_exposes():
    full = np.ones((400, 600), np.float32)
    half = np.zeros((400, 600), np.float32)
    half[:, :300] = 1.0
    assert WM.coverage([full], SIZE) == 1.0 and WM.uncovered([full], SIZE) == 0.0
    assert WM.coverage([half], SIZE) == pytest.approx(0.5) and WM.uncovered([half], SIZE) == pytest.approx(0.5)
    assert WM.uncovered([half, np.roll(half, 300, axis=1)], SIZE) == 0.0                                    # two layers together close the gap
    assert WM.uncovered([], SIZE) == 1.0


A = [{"id": "a1", "x": 0.0, "y": 0.0, "z": 5.0, "width": 1, "height": 1}, {"id": "a2", "x": 1.0, "y": 0.0, "z": 6.0, "width": 1, "height": 1}]
C = [{"id": "c1", "x": -1.0, "z": 3.0, "facing": 90}]
ORDER = ["S1", "S2", "S3", "S4"]


def test_the_state_of_the_set_replays_events_in_shot_order_without_changing_the_set():
    ev = [{"id": "e1", "shot": "S2", "asset": "a1", "kind": "move", "to": {"x": 0.5, "z": 5.5}, "state": "on the floor"},
          {"id": "e2", "shot": "S3", "asset": "a1", "kind": "move", "to": {"x": 2.0}}, {"id": "e3", "shot": "S3", "character": "c1", "to": {"x": 4.0}}]
    a_before, _ = WM.state_at(A, C, ev, ORDER, "S1")
    assert next(x for x in a_before if x["id"] == "a1")["x"] == 0.0                                          # nothing has happened yet
    a2, _ = WM.state_at(A, C, ev, ORDER, "S2")
    assert next(x for x in a2 if x["id"] == "a1")["x"] == 0.0                                                # an event takes effect from the shot after it
    a3, c3 = WM.state_at(A, C, ev, ORDER, "S3")
    one = next(x for x in a3 if x["id"] == "a1")
    assert (one["x"], one["z"], one["state"]) == (0.5, 5.5, "on the floor") and c3[0]["x"] == -1.0
    a4, c4 = WM.state_at(A, C, ev, ORDER, "S4")
    assert next(x for x in a4 if x["id"] == "a1")["x"] == 2.0 and c4[0]["x"] == 4.0
    assert A[0]["x"] == 0.0 and C[0]["x"] == -1.0                                                            # the set as defined is untouched
    assert WM.state_at(A, C, ev, ORDER, None)[0][0]["x"] == 2.0                                              # no shot named: after everything


def test_things_can_leave_and_come_back_and_unknown_things_are_ignored():
    ev = [{"id": "e1", "shot": "S1", "asset": "a2", "kind": "remove"}, {"id": "e2", "shot": "S3", "asset": "a2", "kind": "appear", "to": {"x": 3.0}}, {"id": "e3", "shot": "S1", "asset": "nope", "kind": "remove"}]
    ids = lambda s: [x["id"] for x in WM.state_at(A, C, ev, ORDER, s)[0]]
    assert ids("S2") == ["a1"] and ids("S4") == ["a1", "a2"] and WM.state_at(A, C, ev, ORDER, "S4")[0][1]["x"] == 3.0


def test_side_of_the_axis_between_two_people():
    a, b = (0.0, 4.0), (2.0, 4.0)                                                                            # two people side by side, facing the camera line
    assert WM.side_of_axis(a, b, (1.0, 0.0)) != WM.side_of_axis(a, b, (1.0, 8.0))
    assert WM.side_of_axis(a, b, (1.0, 4.0)) == 0
