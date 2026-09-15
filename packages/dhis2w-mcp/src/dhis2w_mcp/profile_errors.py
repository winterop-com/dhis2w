"""Actionable profile and connection errors for MCP tool calls (hard requirement 1).

Two failures reach a tool the same way and have to read the same way on both surfaces. When no
DHIS2 profile is configured, `resolve_profile()` raises `NoProfileError` inside the tool function;
when the profile names an instance nothing answers at, the client raises a transport error. The CLI
renders each with a hint block - `d2w profile add <name>` / `d2w profile bootstrap` for the first,
the dialled URL and `d2w profile show <name>` for the second - and this middleware gives MCP
clients the same guidance. FastMCP wraps the tool's exception in a `ToolError` before it reaches
middleware, so the middleware walks the cause chain and re-raises a `ToolError` carrying the shared
text (`dhis2w_core.profile.NO_PROFILE_HINT_LINES` and
`dhis2w_core.cli_errors.unreachable_instance_message` - one source of truth for both surfaces).
"""

from __future__ import annotations

import mcp.types as mt
from dhis2w_core.cli_errors import CONNECT_HINT_LINES, transport_error_in_chain, unreachable_instance_message
from dhis2w_core.profile import NO_PROFILE_HINT_LINES, NoProfileError
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult


def _find_no_profile_error(exc: BaseException) -> NoProfileError | None:
    """Return the `NoProfileError` in `exc`'s cause/context chain, or None."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, NoProfileError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def _with_hint(message: str, hint_lines: tuple[str, ...]) -> str:
    """One MCP-facing message: what went wrong, then the CLI's own hint block under it."""
    hint = "\n".join(f"  {line}" for line in hint_lines)
    return f"{message}\nhint:\n{hint}"


def no_profile_message(error: NoProfileError) -> str:
    """Render the error plus the shared setup hint as one MCP-facing message."""
    return _with_hint(str(error), NO_PROFILE_HINT_LINES)


def unreachable_instance_tool_message(error: BaseException) -> str:
    """Render the CLI's unreachable-instance line plus its hint as one MCP-facing message."""
    transport = transport_error_in_chain(error)
    if transport is None:
        return str(error)
    return _with_hint(unreachable_instance_message(transport), CONNECT_HINT_LINES)


class NoProfileHintMiddleware(Middleware):
    """Rewrite profile and connection tool failures into the CLI's own actionable guidance."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Run the tool; if it failed on the profile or on reaching the instance, surface the CLI's message."""
        try:
            return await call_next(context)
        except Exception as exc:
            no_profile = _find_no_profile_error(exc)
            if no_profile is not None:
                raise ToolError(no_profile_message(no_profile)) from exc
            if transport_error_in_chain(exc) is not None:
                raise ToolError(unreachable_instance_tool_message(exc)) from exc
            raise
