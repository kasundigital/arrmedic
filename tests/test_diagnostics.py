from datetime import datetime, timedelta, timezone

from app.main import build_recommendations, local_path_info, recent_failure_items, score_checks


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


def test_recent_failure_items_only_returns_recent_failures():
    now = datetime.now(timezone.utc)
    data = {
        "records": [
            {
                "eventType": "downloadFailed",
                "date": (now - timedelta(hours=2)).isoformat(),
                "sourceTitle": "Recent failure",
                "data": {"message": "Import failed"},
            },
            {
                "eventType": "downloadFailed",
                "date": (now - timedelta(days=2)).isoformat(),
                "sourceTitle": "Old failure",
            },
            {
                "eventType": "grabbed",
                "date": now.isoformat(),
                "sourceTitle": "Not a failure",
            },
        ]
    }
    failures = recent_failure_items(data)
    assert len(failures) == 1
    assert failures[0]["title"] == "Recent failure"
    assert failures[0]["message"] == "Import failed"


def test_recommendations_prioritize_connection_failure():
    report = {
        "checks": [
            {"code": "connection", "status": "fail"},
        ],
        "doctors": {},
        "rootFolders": [],
    }
    recommendations = build_recommendations(report)
    assert len(recommendations) == 1
    assert recommendations[0]["code"] == "fix_connection"
    assert recommendations[0]["priority"] == "high"


def test_recommendations_include_storage_queue_and_hardlink_fixes():
    report = {
        "checks": [
            {"code": "connection", "status": "pass"},
            {"code": "storage", "status": "warn"},
            {"code": "queue", "status": "warn"},
        ],
        "doctors": {
            "hardlink": {"status": "warn"},
            "path": {"status": "pass"},
            "permission": {"status": "pass"},
        },
        "rootFolders": [{"path": "/data/media"}],
    }
    recommendations = build_recommendations(report)
    codes = {item["code"] for item in recommendations}
    assert {"fix_storage", "fix_queue", "fix_hardlink_layout"}.issubset(codes)
    assert all(item["priority"] == "high" for item in recommendations)
