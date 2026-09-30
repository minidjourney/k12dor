"""Provider HTTP clients with explicit read-only allowlists."""

import logging

# MCP configures its root logger at INFO. Provider URLs can contain stable
# account identifiers, so request-level transport logs must never inherit it.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
