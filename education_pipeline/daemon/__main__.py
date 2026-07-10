"""``python -m education_pipeline.daemon <workspace>`` runs the run daemon."""

from __future__ import annotations

import sys

from education_pipeline.daemon import serve


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = args[0] if args else "."
    serve(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
