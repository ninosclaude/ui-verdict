"""Entry point for running QA-Agent as MCP server."""
from .server import mcp

if __name__ == "__main__":
    mcp.run()
