from app.download_doctor import (
    _apply_remote_mapping,
    _extract_download_health_path,
    _field_value,
    _friendly_path_guidance,
    _looks_like_path_problem,
)


def test_extract_download_client_field():
    client = {"fields": [{"name": "host", "value": "sabnzbd"}, {"name": "port", "value": 8080}]}
    assert _field_value(client, "host") == "sabnzbd"
    assert _field_value(client, "port") == 8080


def test_remote_path_mapping_rewrites_matching_path():
    mappings = [{"host": "sabnzbd", "remotePath": "/downloads/complete", "localPath": "/data/downloads/complete"}]
    path, mapping = _apply_remote_mapping("/downloads/complete/Movie.Name", mappings, "sabnzbd")
    assert path == "/data/downloads/complete/Movie.Name"
    assert mapping == mappings[0]


def test_remote_path_mapping_does_not_apply_wrong_host():
    mappings = [{"host": "sabnzbd", "remotePath": "/downloads", "localPath": "/data/downloads"}]
    path, mapping = _apply_remote_mapping("/downloads/Movie.Name", mappings, "qbittorrent")
    assert path == "/downloads/Movie.Name"
    assert mapping is None


def test_common_path_errors_are_detected():
    assert _looks_like_path_problem("Import failed, path does not exist or is not accessible by Radarr")
    assert _looks_like_path_problem("Remote path mapping is missing")
    assert _looks_like_path_problem("Download client SABnzbd places downloads in /config/Downloads/complete but this directory does not appear to exist inside the container.")
    assert not _looks_like_path_problem("Download completed successfully")


def test_radarr_health_message_extracts_downloader_and_path():
    client, path = _extract_download_health_path(
        "You are using docker; download client SABnzbd places downloads in /config/Downloads/complete but this directory does not appear to exist inside the container."
    )
    assert client == "SABnzbd"
    assert path == "/config/Downloads/complete"


def test_beginner_guidance_warns_about_config_download_path():
    guidance = _friendly_path_guidance(
        "Radarr",
        "SABnzbd",
        "/config/Downloads/complete",
        "/config/Downloads/complete",
        {"kind": "remote_path_mapping_needed"},
    )
    assert guidance["title"] == "Radarr cannot see SABnzbd downloads"
    assert "same download folder" in guidance["recommended"]
    assert "/config is normally meant for application settings" in guidance["note"]
    assert len(guidance["steps"]) >= 4
