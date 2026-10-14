from datetime import datetime

from monster_gpu import gate
from monster_gpu.config import Settings


def settings(**kw):
    base = dict(server="http://x/", token="t", worker_id="w", steps=["ai3d"],
                game_patterns=["steamapps/common/", "wine64-preloader"])
    return Settings(**{**base, **kw})


def fake_proc(tmp_path, cmdlines):
    for pid, cmd in enumerate(cmdlines, start=100):
        (tmp_path / str(pid)).mkdir()
        (tmp_path / str(pid) / "cmdline").write_bytes(cmd.replace(" ", "\0").encode())
    (tmp_path / "self").mkdir()  # not a pid: skipped
    return tmp_path


WED_10 = datetime(2026, 10, 14, 10, 0)
SAT_10 = datetime(2026, 10, 17, 10, 0)


def test_hours_window_and_overnight_window():
    assert gate.in_hours(settings(), WED_10)
    assert gate.in_hours(settings(hours="08:00-18:00"), WED_10)
    assert not gate.in_hours(settings(hours="12:00-18:00"), WED_10)
    assert gate.in_hours(settings(hours="22:00-11:00"), WED_10)
    assert not gate.in_hours(settings(hours="22:00-07:00"), WED_10)
    assert not gate.in_hours(settings(weekdays_only=True), SAT_10)


def test_game_is_found_by_its_command_line(tmp_path):
    proc = fake_proc(tmp_path, ["/usr/bin/steam -silent",
                                "/home/t/.steam/steamapps/common/Portal 2/portal2_linux -game portal2"])
    assert "portal2_linux" in gate.game_running(["steamapps/common/"], proc)
    assert gate.game_running(["wine64-preloader"], proc) is None
    assert gate.game_running([], proc) is None


def test_why_not_now(tmp_path):
    (tmp_path / "a").mkdir()
    quiet = fake_proc(tmp_path / "a", [])
    s = settings()
    assert gate.why_not_now(s, WED_10, quiet, vram=lambda: 600) is None
    assert gate.why_not_now(s, WED_10, quiet, vram=lambda: 5000)[0] == "gpu_busy"
    assert gate.why_not_now(s, WED_10, quiet, vram=lambda: None)[0] == "no_gpu"
    assert gate.why_not_now(settings(placeholder=True), WED_10, quiet, vram=lambda: None) is None
    assert gate.why_not_now(settings(hours="12:00-13:00"), WED_10, quiet, vram=lambda: 0)[0] == "quiet_hours"
    (tmp_path / "b").mkdir()
    gaming = fake_proc(tmp_path / "b", ["Z:\\game.exe wine64-preloader"])
    assert gate.why_not_now(s, WED_10, gaming, vram=lambda: 0)[0] == "gaming"
