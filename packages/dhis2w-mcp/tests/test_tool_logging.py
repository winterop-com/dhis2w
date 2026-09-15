"""What a failing tool call writes to the client's server log: one line, with the traceback behind debug.

An MCP server's stderr is the client's log for it. A DHIS2 instance that is not running is a routine
failure and its actionable sentence is already on the `ToolError`, so the log says which tool failed
and leaves the transport chain to a debug run.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from dhis2w_mcp.server import build_server
from dhis2w_mcp.tool_logging import FASTMCP_LOGGER_NAME, ToolFailureTracebackFilter, quieten_tool_failures
from fastmcp import Client
from fastmcp.exceptions import ToolError


def _failed_record() -> logging.LogRecord:
    """One record shaped as FastMCP logs a failing tool call: an error carrying the whole exception."""
    try:
        raise ConnectionError("All connection attempts failed")
    except ConnectionError as error:
        return logging.LogRecord(
            name=f"{FASTMCP_LOGGER_NAME}.server.server",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Error calling tool 'system_info'",
            args=(),
            exc_info=(type(error), error, error.__traceback__),
        )


def test_the_traceback_comes_off_an_error_record() -> None:
    """What reaches the handler is the message alone, which is one line however deep the chain was."""
    record = _failed_record()

    kept = ToolFailureTracebackFilter().filter(record)

    assert kept is True
    assert record.exc_info is None
    assert record.exc_text is None
    assert record.getMessage() == "Error calling tool 'system_info'"


def test_the_traceback_is_re_logged_at_debug_level(caplog: pytest.LogCaptureFixture) -> None:
    """Nothing is thrown away: a client running with debug logging on gets the whole chain back."""
    record = _failed_record()

    with caplog.at_level(logging.DEBUG, logger=f"{FASTMCP_LOGGER_NAME}.server.server"):
        ToolFailureTracebackFilter().filter(record)

    debugged = [entry for entry in caplog.records if entry.levelno == logging.DEBUG]
    assert len(debugged) == 1
    assert debugged[0].exc_info is not None


def test_a_warning_carrying_an_exception_is_left_alone() -> None:
    """The rule is about what an error writes to stderr, so nothing below error level is touched."""
    record = _failed_record()
    record.levelno = logging.WARNING
    record.levelname = "WARNING"

    ToolFailureTracebackFilter().filter(record)

    assert record.exc_info is not None


def test_the_filter_is_installed_once_however_often_a_server_is_built() -> None:
    """Building two servers in one process leaves one filter per handler, not two."""
    quieten_tool_failures()
    quieten_tool_failures()

    for handler in logging.getLogger(FASTMCP_LOGGER_NAME).handlers:
        installed = [one for one in handler.filters if isinstance(one, ToolFailureTracebackFilter)]
        assert len(installed) == 1


@pytest.fixture
def _unreachable_instance_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured profile naming a port nothing listens on - the everyday way a tool call fails."""
    for key in ("DHIS2_PROFILE", "DHIS2_URL", "DHIS2_PAT", "DHIS2_USERNAME", "DHIS2_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    config_dir = tmp_path / "xdg" / "dhis2"
    config_dir.mkdir(parents=True)
    (config_dir / "profiles.toml").write_text(
        """
default = "offline"

[profiles.offline]
base_url = "http://127.0.0.1:1"
auth = "pat"
token = "d2p_test"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    working_dir = tmp_path / "cwd"
    working_dir.mkdir()
    monkeypatch.chdir(working_dir)


async def test_an_unreachable_instance_logs_one_line_and_no_traceback(
    _unreachable_instance_env: None, caplog: pytest.LogCaptureFixture
) -> None:
    """End to end: the tool still answers the actionable error, and the log carries no rendered chain."""
    server = build_server()

    with caplog.at_level(logging.INFO, logger=FASTMCP_LOGGER_NAME):
        async with Client(server) as client:
            with pytest.raises(ToolError):
                await client.call_tool("system_info", {})

    failures = [entry for entry in caplog.records if entry.levelno >= logging.ERROR]
    assert failures, "the failing tool call is still logged"
    assert all(entry.exc_info is None for entry in failures)
