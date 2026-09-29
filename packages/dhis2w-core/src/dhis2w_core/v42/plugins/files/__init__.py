"""Files plugin — documents + fileResources (uploads, downloads, metadata)."""

from __future__ import annotations

from dhis2w_core.plugin import Contribution, extension


class _FilesPlugin:
    """Plugin descriptor for document management + file-resource binary attachments."""

    @extension
    def contribute(self, version_key: str) -> Contribution:
        """Contribute `d2w files`; its MCP tools are the dhis2w-mcp pack's."""
        return Contribution(
            name="files",
            description=(
                "DHIS2 document management + file resources. CLI for `/api/documents` (user-uploaded "
                "attachments, external URLs) and `/api/fileResources` (typed binary blobs — DATA_VALUE, ICON, "
                "MESSAGE_ATTACHMENT)."
            ),
            cli_module="dhis2w_core.v42.plugins.files.cli",
            mcp_module=None,
        )


plugin = _FilesPlugin()
