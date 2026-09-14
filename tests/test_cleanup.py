from app.cleanup import extract_removed_ids


def test_extract_removed_tmdb_ids():
    health = [{"message": "Movie A (tmdbid 123), Movie B (tmdbid 456) were removed from TMDb"}]
    assert extract_removed_ids(health, "radarr") == {123, 456}


def test_extract_removed_tvdb_ids():
    health = [{"message": "Series A (tvdbid 77) was removed from TVDb"}]
    assert extract_removed_ids(health, "sonarr") == {77}


def test_unrelated_health_warning_is_ignored():
    health = [{"message": "No indexers available"}]
    assert extract_removed_ids(health, "radarr") == set()
