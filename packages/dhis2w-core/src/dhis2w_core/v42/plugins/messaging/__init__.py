"""Messaging plugin — DHIS2 `/api/messageConversations`."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _MessagingPlugin:
    """Plugin descriptor for DHIS2 internal messaging (conversations + attachments)."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w messaging` and the `messaging_*` MCP tools."""
        return Contribution(
            name="messaging",
            description=(
                "DHIS2 internal messaging. CLI + MCP surfaces for /api/messageConversations — list, read, send, reply, "
                "mark-read, delete. Pairs with the files plugin for MESSAGE_ATTACHMENT fileResources."
            ),
            cli_module="dhis2w_core.v42.plugins.messaging.cli",
            mcp_module="dhis2w_core.v42.plugins.messaging.mcp",
        )


plugin = _MessagingPlugin()
