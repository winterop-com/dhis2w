"""DHIS2 v42 tree of dhis2w-core: the plugins and the client binding for a 2.42 server.

`plugins/` holds one folder per DHIS2 domain and `client_context` opens a connected
`dhis2w_client.v42.Dhis2Client` from a resolved profile. Everything a tree does not need to
bind to its client (CLI output, error rendering, the token store, PAT and OAuth2 registration,
task watching) lives once at `dhis2w_core.*` and is typed structurally.
"""
