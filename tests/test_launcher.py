from __future__ import annotations

from unittest import mock

import pytest

from kairos.models import AppItem
from kairos.launcher import (
    launch_code, launch_terminal, launch_chrome, launch_spotify,
    launch_app, launch_session, DISPATCH,
)


@mock.patch("kairos.launcher.shutil.which", return_value="C:\\fake\\exe.exe")
@mock.patch("kairos.launcher.subprocess.Popen")
def test_launch_code(mock_popen, mock_which):
    item = AppItem(type="code", path="C:\\dev\\project")
    launch_code(item)
    mock_popen.assert_called_once()


@mock.patch("kairos.launcher.shutil.which", return_value="C:\\fake\\wt.exe")
@mock.patch("kairos.launcher.subprocess.Popen")
def test_launch_terminal(mock_popen, mock_which):
    item = AppItem(type="terminal", cwd="C:\\dev", run="npm run dev")
    launch_terminal(item)
    mock_popen.assert_called_once()


@mock.patch("kairos.launcher.shutil.which", return_value="C:\\fake\\chrome.exe")
@mock.patch("kairos.launcher.subprocess.Popen")
def test_launch_chrome(mock_popen, mock_which):
    item = AppItem(type="chrome", urls=["localhost:3000", "github.com"])
    launch_chrome(item)
    mock_popen.assert_called_once()


@mock.patch("kairos.launcher.shutil.which", return_value="C:\\fake\\spotify.exe")
@mock.patch("kairos.launcher.subprocess.Popen")
def test_launch_spotify(mock_popen, mock_which):
    item = AppItem(type="spotify")
    launch_spotify(item)
    mock_popen.assert_called_once()


@mock.patch("kairos.launcher.shutil.which", return_value="C:\\fake\\exe.exe")
@mock.patch("kairos.launcher.subprocess.Popen")
def test_dispatch_all_types(mock_popen, mock_which):
    items = [
        AppItem(type="code", path="C:\\dev"),
        AppItem(type="terminal", cwd="C:\\dev", run="dir"),
        AppItem(type="chrome", urls=["example.com"]),
        AppItem(type="spotify"),
    ]
    for item in items:
        result = launch_app(item)
        assert result is True
    assert mock_popen.call_count == 4


@mock.patch("kairos.launcher.subprocess.Popen")
def test_unknown_type_skipped(mock_popen):
    item = AppItem(type="unknown_app")
    result = launch_app(item)
    assert result is False
    mock_popen.assert_not_called()


def test_dispatch_contains_all_types():
    assert "code" in DISPATCH
    assert "terminal" in DISPATCH
    assert "chrome" in DISPATCH
    assert "spotify" in DISPATCH


@mock.patch("kairos.launcher.shutil.which", return_value="C:\\fake\\exe.exe")
@mock.patch("kairos.launcher.subprocess.Popen")
def test_one_failure_doesnt_prevent_others(mock_popen, mock_which):
    """If one item fails (FileNotFound), remaining items should still launch."""
    mock_popen.side_effect = [FileNotFoundError, mock.MagicMock()]
    items = [
        AppItem(type="code", path="C:\\dev"),
        AppItem(type="chrome", urls=["example.com"]),
    ]
    result1 = launch_app(items[0])
    result2 = launch_app(items[1])
    assert result1 is False
    assert result2 is True


@mock.patch("kairos.launcher.launch_app")
def test_launch_session_empty(mock_launch):
    from kairos.launcher import launch_session
    result = launch_session("test", [])
    assert result == 0
    mock_launch.assert_not_called()
