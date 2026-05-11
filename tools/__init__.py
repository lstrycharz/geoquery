"""Tools layer: external, deterministic interfaces (the skills *call* these;
they don't reason). Each tool has a typed input and a Pydantic-validated output.
"""

from tools.web_search import search_top_n

__all__ = ["search_top_n"]
