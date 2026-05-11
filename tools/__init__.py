"""Tools layer: external, deterministic interfaces (the skills *call* these;
they don't reason). Each tool has a typed input and a Pydantic-validated output.
"""

from tools.web_fetch import fetch_page
from tools.web_search import search_top_n

__all__ = ["fetch_page", "search_top_n"]
