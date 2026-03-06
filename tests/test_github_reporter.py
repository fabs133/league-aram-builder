"""Tests for the GitHub issue reporter module."""

from unittest.mock import patch, MagicMock

from backend.github_reporter import post_issue, MAX_BODY_LENGTH


@patch("backend.github_reporter.config")
def test_missing_token_returns_none(mock_config):
    mock_config.get.return_value = ""
    result = post_issue("title", "body")
    assert result is None


@patch("backend.github_reporter.config")
def test_missing_repo_returns_none(mock_config):
    def side_effect(key, default=""):
        if key == "github_token":
            return "ghp_fake"
        return ""
    mock_config.get.side_effect = side_effect
    result = post_issue("title", "body")
    assert result is None


@patch("backend.github_reporter.requests.post")
@patch("backend.github_reporter.config")
def test_successful_post_returns_dict(mock_config, mock_post):
    mock_config.get.side_effect = lambda k, d="": {
        "github_token": "ghp_fake",
        "github_repo": "owner/repo",
    }.get(k, d)

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"html_url": "https://github.com/owner/repo/issues/1", "number": 1}
    mock_post.return_value = mock_resp

    result = post_issue("title", "body")
    assert result is not None
    assert result["html_url"] == "https://github.com/owner/repo/issues/1"
    mock_post.assert_called_once()


@patch("backend.github_reporter.requests.post")
@patch("backend.github_reporter.config")
def test_http_error_returns_none(mock_config, mock_post):
    mock_config.get.side_effect = lambda k, d="": {
        "github_token": "ghp_fake",
        "github_repo": "owner/repo",
    }.get(k, d)

    mock_resp = MagicMock()
    mock_resp.status_code = 422
    mock_resp.text = "Validation Failed"
    mock_post.return_value = mock_resp

    result = post_issue("title", "body")
    assert result is None


@patch("backend.github_reporter.requests.post")
@patch("backend.github_reporter.config")
def test_body_truncation(mock_config, mock_post):
    mock_config.get.side_effect = lambda k, d="": {
        "github_token": "ghp_fake",
        "github_repo": "owner/repo",
    }.get(k, d)

    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"html_url": "https://github.com/x/y/issues/1"}
    mock_post.return_value = mock_resp

    long_body = "x" * 70_000
    post_issue("title", long_body)

    # Check the body that was actually sent
    call_kwargs = mock_post.call_args
    sent_body = call_kwargs.kwargs["json"]["body"] if "json" in call_kwargs.kwargs else call_kwargs[1]["json"]["body"]
    assert len(sent_body) < 65_000
    assert "truncated" in sent_body
