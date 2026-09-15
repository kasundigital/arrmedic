from app.deep_scan import (
    _contains_permission_problem,
    _native_permission_signals,
    _status_for_issues,
    _total_records,
)


def test_download_issue_status():
    assert _status_for_issues([]) == "pass"
    assert _status_for_issues([{"severity": "warning"}]) == "warn"
    assert _status_for_issues([{"severity": "error"}]) == "fail"


def test_permission_problem_detection():
    assert _contains_permission_problem("Permission denied: /data/downloads") is True
    assert _contains_permission_problem("Access to the path is denied") is True
    assert _contains_permission_problem("Import completed successfully") is False


def test_native_permission_signals_are_collected():
    report = {
        "health": [{"type": "error", "message": "Permission denied on /media"}],
        "queueIssues": [{"message": "Import failed: path is not accessible"}],
    }
    signals = _native_permission_signals(report)
    assert len(signals) == 2


def test_total_records_supports_paged_responses():
    assert _total_records({"totalRecords": 42, "records": []}) == 42
    assert _total_records([{"id": 1}, {"id": 2}]) == 2
    assert _total_records(None) is None
