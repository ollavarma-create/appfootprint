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


def test_minecraft_archived_logs_preserve_diagnostic_context():
    result = assess_path(
        ROOT, ROOT / "data/PrismLauncher/instances/26.3/minecraft/logs/2026-10-05-1.log.gz"
    )
    assert result.category == "Archived diagnostic log"
    assert "diagnostic history" in result.consequence
    assert "Pattern-based only" == result.confidence


def test_telemetry_is_not_automatically_disposable():
    result = assess_path(ROOT, ROOT / "data/PrismLauncher/telemetry")
    assert result.category == "Possible telemetry data"
    assert "documentation" in result.action


def test_minecraft_world_is_protected():
    result = assess_path(ROOT, ROOT / "data/PrismLauncher/instances/26.3/minecraft/saves/World")
    assert result.category == "Saved game data"
    assert "destroy" in result.consequence


def test_space_significance_is_not_a_cleanup_claim():
    from appfootprint.advisor import space_significance
    assert "unknown" in space_significance(None).lower()
    assert "negligible" in space_significance(200 * 1024)
    assert "limited" in space_significance(20 * 1024 * 1024)
    assert "worth understanding" in space_significance(7 * 1024**3)
