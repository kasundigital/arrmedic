from pathlib import Path

from app.hostfs import local_path_info


def test_host_root_translates_reported_absolute_path(tmp_path, monkeypatch):
    host_root = tmp_path / "host"
    movie_path = host_root / "mnt" / "Movies"
    movie_path.mkdir(parents=True)
    monkeypatch.setenv("ARRMEDIC_HOST_ROOT", str(host_root))

    info = local_path_info("/mnt/Movies")

    assert info["visible"] is True
    assert info["source"] == "host"
    assert Path(info["checkedPath"]) == movie_path
    assert info["hostRootVisible"] is True


def test_missing_host_path_is_reported_without_writes(tmp_path, monkeypatch):
    host_root = tmp_path / "host"
    host_root.mkdir()
    monkeypatch.setenv("ARRMEDIC_HOST_ROOT", str(host_root))

    info = local_path_info("/definitely/not/present/in/arrmedic-test")

    assert info["visible"] is False
    assert info["writable"] is False
    assert info["hostRoot"] == str(host_root)
