# Security policy

Report security issues privately to the repository maintainers via GitHub's private vulnerability reporting if enabled, rather than publishing exploit details in an issue.

Treat third-party QGIS plugins, Blender scripts and MCP bridges as executable code. Run only trusted automations; keep local services bound to localhost and protect credentials. GeoJSON inputs should be validated and must not be treated as executable instructions.

Never commit API keys, secrets, or confidential project data.
