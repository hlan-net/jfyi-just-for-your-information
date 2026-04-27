"""JFYI - Just For Your Information: MCP Server & Analytics Hub."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("jfyi-mcp-server")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"
