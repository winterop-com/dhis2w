"""What a failing MCP tool call writes to stderr: one line at error level, the traceback behind debug.

An MCP server speaks over stdio and its stderr is the client's server log. FastMCP logs a failing
tool call with `logger.exception(...)`, which renders the whole chain - ninety-odd lines of transport
internals for a DHIS2 instance that is simply not running. The actionable sentence a caller needs is
already on the `ToolError` (`dhis2w_mcp.profile_errors`), so the log's job is to say which tool failed
and stay out of the way.

The traceback is not thrown away. It is re-logged at debug level on the same logger, so a client run
with debug logging on gets exactly what it got before and a client run normally gets one line.

The filter sits on the handlers FastMCP configures for the `fastmcp` logger rather than on a logger
of its own, because a handler filter runs for every record reaching that handler, including the ones
its child loggers propagate up - which is where the tool-call record comes from.
"""

from __future__ import annotations

import logging

#: The logger FastMCP configures its own stderr handlers on; every `fastmcp.*` record reaches them.
FASTMCP_LOGGER_NAME = "fastmcp"


class ToolFailureTracebackFilter(logging.Filter):
    """Take the traceback off an error record, having logged it at debug level first."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep every record, and strip the rendered traceback off the ones logged at error or worse."""
        exception = record.exc_info
        if exception is None or record.levelno < logging.ERROR:
            return True
        record.exc_info = None
        record.exc_text = None
        logger = logging.getLogger(record.name)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("%s", record.getMessage(), exc_info=exception)
        return True


def quieten_tool_failures() -> None:
    """Put every FastMCP stderr handler behind the filter, once, whatever else is already on them.

    The filter goes at the front of each handler's own list: FastMCP splits its records across a
    plain handler and a traceback handler by whether `exc_info` is set, so a filter that clears it
    has to run before that split for the one line to land on the plain handler and nothing on the
    other.
    """
    for handler in logging.getLogger(FASTMCP_LOGGER_NAME).handlers:
        if any(isinstance(existing, ToolFailureTracebackFilter) for existing in handler.filters):
            continue
        handler.filters.insert(0, ToolFailureTracebackFilter())
