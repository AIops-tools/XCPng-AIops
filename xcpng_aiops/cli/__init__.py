"""CLI package for xcpng-aiops.

Re-exports ``app`` so the pyproject entry point
``xcpng-aiops = "xcpng_aiops.cli:app"`` works unchanged.
"""

from xcpng_aiops.cli._root import app

__all__ = ["app"]
