"""Tools layer: external, deterministic interfaces (the skills *call* these;
they don't reason). Each tool has a typed input and a Pydantic-validated output.
"""

from tools.sitemap_parser import SitemapEntry, parse_sitemap
from tools.web_fetch import fetch_page
from tools.web_search import search_top_n

__all__ = ["SitemapEntry", "fetch_page", "parse_sitemap", "search_top_n"]
