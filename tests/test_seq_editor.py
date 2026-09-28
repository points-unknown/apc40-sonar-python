from apc40sonar import seq_editor as se

VEL = {"normal": 100, "accent": 127, "soft": 60}


def test_off_cells_mark_the_beats():
    assert se.cell_color(0, VEL, 0) == se.CELL_OFF_BEAT
    assert se.cell_color(0, VEL, 1) == se.CELL_OFF


def test_louder_steps_are_brighter():
    quiet = se.cell_color(90, VEL, 0)
    loud = se.cell_color(110, VEL, 0)
    assert quiet != loud and quiet.startswith("#") and len(loud) == 7


def test_wheel_starts_an_off_step_at_normal_and_clamps():
    assert se.wheel_velocity(0, True, False, VEL) == 100
    assert se.wheel_velocity(0, False, False, VEL) == 0
    assert se.wheel_velocity(125, True, False, VEL) == 127
    assert se.wheel_velocity(3, False, False, VEL) == 1
    assert se.wheel_velocity(50, True, True, VEL) == 51


def test_map_file_names_are_safe():
    assert se.map_file_name("My kit: SSD5/Rock?") == "My kit_ SSD5_Rock_.json"
    assert se.map_file_name("  ..  ") == "drum map.json"


def test_saved_maps_are_listed_by_name(tmp_path):
    assert se.saved_maps(tmp_path) == {}
    folder = se.maps_dir(tmp_path)
    folder.mkdir()
    (folder / "b kit.json").write_text("{}")
    (folder / "A kit.json").write_text("{}")
    (folder / "notes.txt").write_text("")

    assert list(se.saved_maps(tmp_path)) == ["A kit", "b kit"]
