from app.main import local_path_info, score_checks


def test_score_checks_penalizes_warn_and_fail():
    checks = [
        {"status": "pass"},
        {"status": "warn"},
        {"status": "fail"},
        {"status": "info"},
    ]
    assert score_checks(checks) == 73


def test_score_checks_never_below_zero():
    checks = [{"status": "fail"} for _ in range(10)]
    assert score_checks(checks) == 0


def test_local_path_info_for_visible_directory(tmp_path):
    result = local_path_info(str(tmp_path))
    assert result["visible"] is True
    assert result["readable"] is True
    assert result["totalBytes"] > 0
    assert result["freeBytes"] >= 0


def test_local_path_info_for_missing_directory(tmp_path):
    result = local_path_info(str(tmp_path / "missing"))
    assert result["visible"] is False
