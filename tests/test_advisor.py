from pathlib import Path

from appfootprint.advisor import assess_path


ROOT = Path("/home/test/.var/app/org.example.App")


def test_cache_is_only_name_based():
    result = assess_path(ROOT, ROOT / "cache" / "thumbnails")
    assert result.category == "Possible cache"
    assert result.confidence == "Name-based only"
    assert "prove removal is safe" in result.explanation


def test_data_and_config_never_recommended_for_cleanup():
    for name in ("data", "config", ".local", ".ld.so"):
        result = assess_path(ROOT, ROOT / name / "important.db")
        assert result.category == "Application state"
        assert "No cleanup is recommended" in result.explanation


def test_unrecognized_and_root_are_not_cleanup_targets():
    assert assess_path(ROOT, ROOT / "saves").category == "Unclassified user data"
    assert assess_path(ROOT, ROOT).category == "Application data"


def test_outside_root_is_not_assessed():
    result = assess_path(ROOT, Path("/home/test/Documents"))
    assert result.category == "Outside application data"
