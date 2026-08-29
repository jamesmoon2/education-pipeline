"""One shared lone-surrogate scan for every layer that fails closed on them.

Guide validation, profile parsing, and the privacy policy all had to answer the
same question — "does this ``str`` contain a code point in the UTF-16 surrogate
block?" — and each answered it with its own per-character ``ord()`` loop. This
module owns the single compiled character class they now share.

The module deliberately imports nothing from the package: ``profiles`` imports
``config``, ``privacy`` imports both, and ``guides.validation`` imports
``privacy``, so a helper living in any of them would close a cycle for at least
one caller.

Equivalence: a Python ``str`` stores lone surrogates as ordinary code points and
``re`` matches them positionally, so ``[\\ud800-\\udfff]`` is exactly the
``0xD800 <= ord(character) <= 0xDFFF`` test it replaces. Astral characters such
as U+1F600 are one code point outside that range, not a surrogate pair.
"""

from __future__ import annotations

import re

_SURROGATE_RE = re.compile("[\ud800-\udfff]")

#: The character guide validation substitutes for every lone surrogate.
SURROGATE_REPLACEMENT = "\N{REPLACEMENT CHARACTER}"


def has_surrogates(value: str) -> bool:
    """Return whether ``value`` contains any lone surrogate code point."""

    return _SURROGATE_RE.search(value) is not None


def replace_surrogates(value: str, replacement: str = SURROGATE_REPLACEMENT) -> str:
    """Replace every lone surrogate in ``value`` with ``replacement``.

    Returns ``value`` itself when there is nothing to replace. Callers rely on
    that identity: guide sanitization shares whole clean subtrees rather than
    rebuilding them. ``replacement`` is substituted verbatim, never read as a
    regex template.
    """

    if _SURROGATE_RE.search(value) is None:
        return value
    return _SURROGATE_RE.sub(lambda _: replacement, value)


__all__ = ["SURROGATE_REPLACEMENT", "has_surrogates", "replace_surrogates"]
