"""meteoverdict: which weather model gets Czechia right?"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("meteoverdict")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"

__all__ = ["__version__"]
