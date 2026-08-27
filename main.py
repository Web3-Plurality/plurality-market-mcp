from dotenv import load_dotenv
load_dotenv()

from plurality_mcp_server.app import mcp_server  # noqa: E402

__all__ = ["mcp_server"]
