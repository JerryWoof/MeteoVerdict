"""Command-line entry point for ``mvd``.

This is a minimal placeholder; the real command set (``fetch-obs``, ``fetch-fc``,
``score``, ...) arrives with roadmap item 0.3.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from meteoverdict import __version__


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--version"], ["-V"]):
        print(f"mvd {__version__}")
        return 0
    print("mvd: no commands yet (see ROADMAP.md, item 0.3). Try `mvd --version`.")
    return 0 if not args else 2


if __name__ == "__main__":
    raise SystemExit(main())
