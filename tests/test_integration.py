"""Integration tests for the FastAPI server and WebSocket protocol."""

import json
import pytest
from unittest.mock import patch

import backend.diagnostics as diag


# Mock LCDA so no real game is needed
NO_GAME = patch("backend.api.server.get_raw_game_data", return_value=None)


@pytest.fixture(autouse=True)
def _patch_report_dir(tmp_path, monkeypatch):
    """Redirect bug reports to tmp dir and reset rate limiter for all tests."""
    monkeypatch.setattr(diag, "REPORT_DIR", tmp_path)
    import backend.api.server as srv
    srv._last_bug_report_time = 0.0


@NO_GAME
def test_health_endpoint(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "champions_loaded" in data
    assert "data_loaded" in data
    assert "augments_loaded" in data
    assert "items_loaded" in data


@NO_GAME
def test_static_names_endpoint(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    resp = client.get("/api/static-names")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "augments" in data
    assert "champions" in data


@NO_GAME
def test_bug_report_endpoint(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    resp = client.post("/api/bug-report")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "created"
    assert "path" in data
    assert "filename" in data
    assert data["filename"].startswith("bug_report_")
    assert "github_url" in data


@NO_GAME
def test_bug_report_with_description(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    resp = client.post(
        "/api/bug-report",
        json={"description": "Augment scoring was wrong for Jinx"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "created"
    assert "github_url" in data  # None when no token configured


@NO_GAME
def test_augment_search_endpoint(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    resp = client.get("/api/augments/search?q=test")
    assert resp.status_code == 200
    # Should return a list (may be empty if no data loaded)
    assert isinstance(resp.json(), list)


@NO_GAME
def test_websocket_set_augment_choices(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    with client.websocket_connect("/ws/game") as ws:
        ws.send_json({"type": "set_augment_choices", "augment_ids": ["aug1", "aug2"]})
        resp = ws.receive_json()
        assert resp["type"] == "ack"
        assert resp["action"] == "set_augment_choices"
        assert resp["augment_ids"] == ["aug1", "aug2"]


@NO_GAME
def test_websocket_choose_augment(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    with client.websocket_connect("/ws/game") as ws:
        ws.send_json({"type": "choose_augment", "augment_id": "aug1"})
        resp = ws.receive_json()
        assert resp["type"] == "ack"
        assert resp["action"] == "choose_augment"
        assert "aug1" in resp["chosen_augments"]


@NO_GAME
def test_websocket_clear_augments(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    with client.websocket_connect("/ws/game") as ws:
        ws.send_json({"type": "clear_augments"})
        resp = ws.receive_json()
        assert resp["type"] == "ack"
        assert resp["action"] == "clear_augments"


@NO_GAME
def test_websocket_toggle_ocr(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    with client.websocket_connect("/ws/game") as ws:
        ws.send_json({"type": "toggle_ocr", "enabled": False})
        resp = ws.receive_json()
        assert resp["type"] == "ack"
        assert resp["action"] == "toggle_ocr"
        assert resp["enabled"] is False


@NO_GAME
def test_websocket_invalid_json(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    with client.websocket_connect("/ws/game") as ws:
        ws.send_text("not valid json{{{")
        resp = ws.receive_json()
        assert "error" in resp


@NO_GAME
def test_websocket_unknown_type(mock_lcda):
    from starlette.testclient import TestClient
    from backend.api.server import app

    client = TestClient(app)
    with client.websocket_connect("/ws/game") as ws:
        ws.send_json({"type": "nonexistent_action"})
        resp = ws.receive_json()
        assert "error" in resp


def test_stat_delta_matching_e2e():
    """Simulate augment detection via stat delta matching."""
    import numpy as np
    from backend.engine.augment_detector import match_augment
    from backend.models import AugmentData, AugmentTier, StatVector

    before = {"abilityPower": 100.0, "attackDamage": 50.0, "maxHealth": 1000.0}
    after = {"abilityPower": 140.0, "attackDamage": 50.0, "maxHealth": 1000.0}

    candidates = [
        AugmentData("a1", "AP Boost", AugmentTier.GOLD, "", StatVector(ap=1.0)),
        AugmentData("a2", "AD Boost", AugmentTier.GOLD, "", StatVector(ad=1.0)),
        AugmentData("a3", "HP Boost", AugmentTier.GOLD, "", StatVector(hp=1.0)),
    ]

    matched, confidence = match_augment(before, after, candidates)
    assert matched is not None
    assert matched.id == "a1"
    assert confidence >= 0.3
