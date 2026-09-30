"""Naver read adapter."""

from .adapter import NaverAdapter
from .mapper import _safe_detail_html

__all__ = ["NaverAdapter", "_safe_detail_html"]
