"""The 3D reader and renderer, checked on glTF files written by an independent test writer (`glbtools`, following the specification) and on hand-worked projections. Not third-party models."""
import base64
import json
import math
import os
import struct
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from filmcrafter_engine import keying as K, world3d as W3, worldmath as WM  # noqa: E402
from glbtools import cube_faces, glb  # noqa: E402

SIZE = (240, 160)
CAM = {"x": 0.0, "y": 0.0, "z": -5.0, "yaw": 0.0, "pitch": 0.0, "fov": 50.0}


def write(tmp_path, name, data):
    p = str(tmp_path / name)
    open(p, "wb").write(data)
    return p


def draw(model_or_instances, cam=CAM, size=SIZE, lights=None, ambient=0.3):
    insts = model_or_instances if isinstance(model_or_instances, list) else [{"model": model_or_instances, "matrix": np.eye(4)}]
    color, depth, hit = W3.new_buffers(size)
    n = W3.render_meshes(insts, cam, size, lights, ambient, depth, color, hit)
    return K.to_srgb(color), depth, hit, n


def dominant(img, mask):
    px = img[mask]
    return px.mean(axis=0)


# ---------------------------------------------------------------- transforms

def test_yaw_pitch_roll_turn_the_front_the_way_the_conventions_say():
    z = np.array([0.0, 0.0, 1.0])
    assert W3.rotation(90, 0, 0) @ z == pytest.approx([1, 0, 0], abs=1e-9)                              # yaw turns +Z toward +X
    assert W3.rotation(0, 90, 0) @ z == pytest.approx([0, 1, 0], abs=1e-9)                              # pitch tips the front up
    assert W3.rotation(0, 0, 90) @ np.array([1.0, 0, 0]) == pytest.approx([0, 1, 0], abs=1e-9)
    assert W3.rotation(180, 0, 0) @ z == pytest.approx([0, 0, -1], abs=1e-9)


def test_a_matrix_scales_then_turns_then_moves_and_groups_compose_parent_first():
    m = W3.matrix({"x": 1, "y": 2, "z": 3, "yaw": 90, "scale": 2.0})
    assert (m @ np.array([0, 0, 1, 1.0]))[:3] == pytest.approx([1 + 2, 2, 3], abs=1e-9)                # the front point (0,0,1) scaled to 2, turned to +X, then moved
    groups = {"g1": {"x": 10, "y": 0, "z": 0, "yaw": 0}, "g2": {"x": 0, "y": 5, "z": 0, "parent": "g1"}}
    wm = W3.world_matrix({"x": 1, "y": 0, "z": 0, "parent": "g2"}, groups)
    assert (wm @ np.array([0, 0, 0, 1.0]))[:3] == pytest.approx([11, 5, 0])
    groups["g1"]["parent"] = "g2"
    with pytest.raises(SystemExit, match="contain themselves"):
        W3.world_matrix({"parent": "g2"}, groups)
    assert W3.world_matrix({"x": 1, "parent": "gone"}, {}) [0, 3] == 1.0                                 # a parent that is not there is ignored, not fatal


def test_the_world_box_of_a_turned_model_is_the_box_of_its_corners():
    box = [[-1, -1, -1], [1, 1, 1]]
    assert W3.world_bbox(box, np.eye(4)) == [[-1, -1, -1], [1, 1, 1]]
    m = W3.matrix({"yaw": 45})
    b = W3.world_bbox(box, m)
    assert b[1][0] == pytest.approx(math.sqrt(2), abs=1e-3) and b[1][1] == 1.0
    assert W3.world_bbox(box, W3.matrix({"x": 5}))[0][0] == 4.0


# ---------------------------------------------------------------- reading glTF

def test_a_glb_is_read_with_its_meshes_box_triangles_and_materials(tmp_path):
    p = write(tmp_path, "cube.glb", glb(cube_faces(2.0)))
    m = W3.load_model(p)
    s = W3.summary(m)
    assert s["triangles"] == 12 and s["bbox"] == [[-1, -1, -1], [1, 1, 1]] and s["size"] == [2.0, 2.0, 2.0] and s["materials"] == 6 and s["warnings"] == []
    assert len(m["meshes"]) == 6 and m["meshes"][0]["nrm"] is not None and m["meshes"][0]["uv"] is not None


def test_a_gltf_with_embedded_buffers_reads_the_same_as_the_glb(tmp_path):
    a = W3.load_model(write(tmp_path, "a.glb", glb(cube_faces(1.0))))
    b = W3.load_model(write(tmp_path, "b.gltf", glb(cube_faces(1.0), embedded=True)))
    assert W3.summary(a)["bbox"] == W3.summary(b)["bbox"] and a["triangles"] == b["triangles"]


def test_the_node_hierarchy_is_applied_translation_rotation_and_scale(tmp_path):
    nodes = [{"children": [1], "translation": [5, 0, 0], "scale": [2, 2, 2]}, {"mesh": 0, "translation": [1, 0, 0], "rotation": [0, math.sin(math.pi / 4), 0, math.cos(math.pi / 4)]}]
    m = W3.load_model(write(tmp_path, "h.glb", glb(cube_faces(1.0)[:1], nodes=nodes)))
    lo, hi = m["bbox"]
    c = (np.array(lo) + np.array(hi)) / 2
    assert c == pytest.approx([8.0, 0.0, 0.0], abs=1e-6)                                                # the child at x=1 inside a parent at x=5 scaled by 2 sits at 5 + 2*1 = 7; its front face (0.5 ahead) turns to +X and is scaled to 1
    assert hi[0] - lo[0] == pytest.approx(0.0, abs=1e-6) and hi[1] - lo[1] == pytest.approx(2.0)        # turned a quarter: the flat face now stands across Z


def test_what_cannot_be_drawn_is_said_and_what_cannot_be_read_is_refused(tmp_path):
    w = W3.load_model(write(tmp_path, "w.glb", glb(cube_faces(1.0)[:2], extra={"animations": [{}], "skins": [{}], "extensionsRequired": ["KHR_draco_mesh_compression"]})))
    assert any("Animations" in x for x in w["warnings"]) and any("Skins" in x for x in w["warnings"]) and any("extensions" in x for x in w["warnings"])
    for name, data, why in (("junk.glb", b"not a model at all", "not a glTF"), ("v1.glb", glb(cube_faces(1.0)[:1], extra={"asset": {"version": "1.0"}}), "Only glTF 2.0"),
                            ("ext.gltf", json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": "mesh.bin", "byteLength": 4}], "meshes": []}).encode(), "separate files"),
                            ("empty.glb", glb([{"pos": [[0, 0, 0]], "idx": [0, 0, 0]}], extra={"meshes": []}), "damaged or incomplete"),
                            ("nomesh.glb", glb([{"pos": [[0, 0, 0]], "idx": [0, 0, 0]}], nodes=[{"name": "empty"}]), "no triangle meshes")):
        with pytest.raises(SystemExit, match=why):
            W3.load_model(write(tmp_path, name, data))


def test_a_triangle_that_points_outside_its_points_and_too_many_triangles_are_refused(tmp_path, monkeypatch):
    bad = glb([{"pos": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "idx": [0, 1, 9]}])
    with pytest.raises(SystemExit, match="does not exist"):
        W3.load_model(write(tmp_path, "bad.glb", bad))
    monkeypatch.setattr(W3, "MAX_TRIANGLES", 5)
    with pytest.raises(SystemExit, match="more than 5 triangles"):
        W3.load_model(write(tmp_path, "cube.glb", glb(cube_faces(1.0))))
    monkeypatch.setattr(W3, "MAX_FILE", 10)
    with pytest.raises(SystemExit, match="larger than 60 MB"):
        W3.load_model(write(tmp_path, "cube2.glb", glb(cube_faces(1.0))))


def test_a_truncated_binary_is_refused(tmp_path):
    data = glb(cube_faces(1.0))
    with pytest.raises(SystemExit):
        W3.load_model(write(tmp_path, "t.glb", data[:40]))


# ---------------------------------------------------------------- drawing

def test_a_cube_seen_from_the_front_shows_its_front_face_in_the_middle_at_the_projected_size(tmp_path):
    model = W3.load_model(write(tmp_path, "c.glb", glb(cube_faces(1.0))))
    img, depth, hit, n = draw(model, lights=[{"azimuth": 180, "elevation": 0, "colour": "#ffffff", "intensity": 1.0}], ambient=0.0)
    f = WM.focal_px(SIZE[0], 50.0)
    half = f * 0.5 / 4.5                                                                                  # the front face is at z=-0.5, 4.5 m from the camera
    ys, xs = np.nonzero(hit)
    assert xs.min() == pytest.approx(SIZE[0] / 2 - half, abs=2) and xs.max() == pytest.approx(SIZE[0] / 2 + half, abs=2) and ys.min() == pytest.approx(SIZE[1] / 2 - half, abs=2)
    c = dominant(img, hit)
    assert c[0] > 0.6 and c[1] < 0.3 and c[2] < 0.3                                                       # the red front of the cube faces the camera
    assert n > 0


def test_a_cube_seen_from_the_front_back_sides_and_above_shows_the_right_face_each_time(tmp_path):
    model = W3.load_model(write(tmp_path, "c.glb", glb(cube_faces(1.0))))
    lights = [{"azimuth": 0, "elevation": 0, "colour": "#ffffff", "intensity": 1.0}, {"azimuth": 180, "elevation": 0, "colour": "#ffffff", "intensity": 1.0}, {"azimuth": 90, "elevation": 0, "colour": "#ffffff", "intensity": 1.0},
              {"azimuth": -90, "elevation": 0, "colour": "#ffffff", "intensity": 1.0}, {"azimuth": 0, "elevation": 90, "colour": "#ffffff", "intensity": 1.0}]

    def face(cam, expect):
        img, _, hit, _ = draw(model, cam=cam, lights=lights, ambient=0.3)
        c = dominant(img, hit)
        assert int(np.argmax(c)) in expect, (cam, c)
        return c
    c0 = face({"x": 0, "y": 0, "z": -5, "yaw": 0, "pitch": 0, "fov": 50}, (0,))                            # from the front of the set: the model's front (+Z in glTF) is red and faces the camera
    c1 = face({"x": 0, "y": 0, "z": 5, "yaw": 180, "pitch": 0, "fov": 50}, (2,))                          # from behind (reverse): the back (-Z in glTF) is blue
    c2 = face({"x": 5, "y": 0, "z": 0, "yaw": -90, "pitch": 0, "fov": 50}, (1,))                          # from +X (the side): the +X face is green
    c3 = face({"x": 0, "y": 5, "z": 0, "yaw": 0, "pitch": -90, "fov": 50}, (0, 1, 2))                      # from above: the white top face, all channels high
    assert c3.min() > 0.5
    assert c0[0] > c0[2] and c1[2] > c1[0] and c2[1] > c2[0]


def test_nearer_things_hide_farther_ones_whatever_order_they_are_drawn_in(tmp_path):
    near = W3.load_model(write(tmp_path, "n.glb", glb(cube_faces(1.0, colors={k: (1, 0, 0) for k in ("+z", "-z", "+x", "-x", "+y", "-y")}))))
    far = W3.load_model(write(tmp_path, "f.glb", glb(cube_faces(3.0, colors={k: (0, 0, 1) for k in ("+z", "-z", "+x", "-x", "+y", "-y")}))))
    a = {"model": near, "matrix": W3.matrix({"z": 0})}
    b = {"model": far, "matrix": W3.matrix({"z": 4})}
    for order in ([a, b], [b, a]):
        img, depth, hit, _ = draw(order, lights=[{"azimuth": 0, "elevation": 0, "colour": "#ffffff", "intensity": 1.0}], ambient=0.5)
        assert img[SIZE[1] // 2, SIZE[0] // 2][0] > img[SIZE[1] // 2, SIZE[0] // 2][2]                       # the near red cube is in front of the big blue one
        assert depth[SIZE[1] // 2, SIZE[0] // 2] == pytest.approx(4.5, abs=0.02)


def test_a_model_behind_or_partly_behind_the_camera_does_not_break_the_drawing(tmp_path):
    model = W3.load_model(write(tmp_path, "c.glb", glb(cube_faces(2.0))))
    img, depth, hit, n = draw([{"model": model, "matrix": W3.matrix({"z": -8})}])
    assert n == 0 and not hit.any()
    floor = W3.load_model(write(tmp_path, "floor.glb", glb([{"pos": [[-5, -1, 8], [5, -1, 8], [5, -1, -8], [-5, -1, -8]], "idx": [0, 1, 2, 0, 2, 3], "color": [0.5, 0.5, 0.5, 1], "double": True}])))
    img, depth, hit, n = draw(floor)                                                                      # a floor that runs from behind the camera to in front of it: clipped at the near plane, still drawn
    assert hit.any() and np.isfinite(depth[hit]).all() and (depth[hit] > W3.NEAR).all()


def test_the_back_of_a_surface_is_not_drawn_unless_it_is_double_sided(tmp_path):
    quad = {"pos": [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], "idx": [0, 1, 2, 0, 2, 3], "color": [1, 0.5, 0, 1]}                     # counter-clockwise seen from +Z
    one = W3.load_model(write(tmp_path, "q1.glb", glb([quad])))
    two = W3.load_model(write(tmp_path, "q2.glb", glb([{**quad, "double": True}])))
    front = {"x": 0, "y": 0, "z": -5, "yaw": 0, "pitch": 0, "fov": 50}                                      # the glTF front faces the camera at rest
    back = {"x": 0, "y": 0, "z": 5, "yaw": 180, "pitch": 0, "fov": 50}
    assert draw(one, cam=front)[2].any() and not draw(one, cam=back)[2].any()
    assert draw(two, cam=front)[2].any() and draw(two, cam=back)[2].any()


def test_a_texture_colours_the_surface_and_the_material_colour_multiplies_it(tmp_path):
    tex = Image.new("RGBA", (2, 2))
    tex.putdata([(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)])
    quad = {"pos": [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], "uv": [[0, 1], [1, 1], [1, 0], [0, 0]], "idx": [0, 1, 2, 0, 2, 3], "color": [1, 1, 1, 1], "tex": True, "nrm": [[0, 0, 1]] * 4}
    m = W3.load_model(write(tmp_path, "t.glb", glb([quad], texture=tex)))
    assert m["meshes"][0]["tex"] is not None and m["textures"] == 1
    img, _, hit, _ = draw(m, cam={"x": 0, "y": 0, "z": -4, "yaw": 0, "pitch": 0, "fov": 50}, lights=[{"azimuth": 180, "elevation": 0, "colour": "#ffffff", "intensity": 1.0}], ambient=0.2)
    ys, xs = np.nonzero(hit)
    cx, cy = (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2
    seen = {tuple((img[cy + dy, cx + dx] > 0.5).astype(int)) for dy in (-12, 12) for dx in (-12, 12)}
    assert len(seen) == 4                                                                                  # four quadrants, four different colours


def test_the_lights_decide_which_side_is_bright_and_with_no_lights_a_key_light_stands_in(tmp_path):
    model = W3.load_model(write(tmp_path, "c.glb", glb(cube_faces(1.0, colors={k: (1, 1, 1) for k in ("+z", "-z", "+x", "-x", "+y", "-y")}))))
    cam = {"x": 3, "y": 3, "z": -4, "yaw": 0, "pitch": 0, "fov": 50}
    cam = {**cam, **{k: v for k, v in WM_look(cam, (0, 0, 0)).items()}}
    lit = lambda az: draw(model, cam=cam, lights=[{"azimuth": az, "elevation": 20, "colour": "#ffffff", "intensity": 1.0}], ambient=0.05)[0]
    a, b = lit(180), lit(0)                                                                               # the light from behind the cube's -Z face (toward -Z) or from the other side
    assert not np.allclose(a, b)
    d = draw(model, cam=cam, lights=None)[0]
    assert d.max() > 0.3


def WM_look(cam, p):
    dx, dy, dz = p[0] - cam["x"], p[1] - cam["y"], p[2] - cam["z"]
    return {"yaw": math.degrees(math.atan2(dx, dz)), "pitch": math.degrees(math.atan2(dy, math.hypot(dx, dz)))}


def test_the_ground_is_a_checker_with_metre_squares_at_the_depth_the_geometry_says():
    color, depth, hit = W3.new_buffers((320, 200))
    cam = {"x": 0.0, "y": 1.6, "z": 0.0, "yaw": 0.0, "pitch": -20.0, "fov": 60.0}
    W3.render_ground(cam, (320, 200), 0.0, ((0.9, 0.9, 0.9), (0.2, 0.2, 0.2)), 50.0, [{"azimuth": 0, "elevation": 90, "colour": "#ffffff", "intensity": 1.0}], 0.0, depth, color, hit)
    assert hit[199, 160] and not hit[0, 160]                                                              # ground at the bottom, sky at the top
    f = WM.focal_px(320, 60.0)
    dirv = np.array([0.0, -(199.5 - 100) / f, 1.0])
    ray = dirv @ W3._cam_to_world_dirs(cam)
    t = (0.0 - 1.6) / ray[1]
    assert depth[199, 160] == pytest.approx(t * 1.0, abs=0.05)
    row = color[150]
    vals = np.round(row[hit[150]][:, 0], 2)
    assert len(set(vals.tolist())) == 2                                                                   # two checker colours only (lit by a light straight above)
    nearer = hit & (depth < 3.0)
    assert nearer.any() and depth[hit].min() > W3.NEAR


def test_things_stand_in_front_of_the_ground_and_the_ground_does_not_paint_over_them(tmp_path):
    model = W3.load_model(write(tmp_path, "c.glb", glb(cube_faces(1.0, colors={k: (1, 0, 0) for k in ("+z", "-z", "+x", "-x", "+y", "-y")}))))
    size = (240, 160)
    color, depth, hit = W3.new_buffers(size)
    cam = {"x": 0.0, "y": 1.5, "z": -5.0, "yaw": 0.0, "pitch": -10.0, "fov": 50.0}
    W3.render_ground(cam, size, 0.0, ((0.9, 0.9, 0.9), (0.9, 0.9, 0.9)), 50.0, None, 0.5, depth, color, hit)
    W3.render_meshes([{"model": model, "matrix": W3.matrix({"y": 0.5})}], cam, size, None, 0.5, depth, color, hit)
    img = K.to_srgb(color)
    mid = img[size[1] // 2 + 8, size[0] // 2]
    assert mid[0] > 0.5 and mid[1] < mid[0] * 0.5                                                          # the cube (red) stands on the grey ground
    assert img[size[1] - 3, 3].std() < 0.2 and abs(img[size[1] - 3, 3][0] - img[size[1] - 3, 3][1]) < 0.05    # the ground at the corner is grey
