from pathlib import Path
from backend.config import Config


def test_defaults_used_when_no_file():
    c = Config()
    c.load(Path("/nonexistent/path.toml"))
    assert c.get("match_threshold") == 65
    assert c.get("poll_interval") == 2.0
    assert c.get("confidence_threshold") == 0.3
    assert c.get("ocr_region") is None


def test_toml_overrides(tmp_path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('[ocr]\nmatch_threshold = 80\nhash_change_threshold = 25\n')
    c = Config()
    c.load(toml_file)
    assert c.get("match_threshold") == 80
    assert c.get("hash_change_threshold") == 25
    # Non-overridden keys keep defaults
    assert c.get("poll_interval") == 2.0


def test_unknown_keys_ignored(tmp_path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text('bogus_key = 42\n')
    c = Config()
    c.load(toml_file)
    assert c.get("bogus_key") is None


def test_getitem_syntax():
    c = Config()
    c.load(Path("/nonexistent/path.toml"))
    assert c["port"] == 8765


def test_nested_sections(tmp_path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text(
        '[detector]\nconfidence_threshold = 0.4\nconfidence_gap = 0.08\n'
        '[server]\npoll_interval = 1.5\n'
    )
    c = Config()
    c.load(toml_file)
    assert c.get("confidence_threshold") == 0.4
    assert c.get("confidence_gap") == 0.08
    assert c.get("poll_interval") == 1.5


def test_invalid_toml_falls_back_to_defaults(tmp_path):
    toml_file = tmp_path / "config.toml"
    toml_file.write_text("not valid toml {{{{")
    c = Config()
    c.load(toml_file)
    assert c.get("match_threshold") == 65
