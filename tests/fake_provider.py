"""A deterministic stand-in for a provider CLI, used in daemon tests.

Reads the prompt from stdin and echoes a canned response. Behaviour is driven by
environment variables so a test can exercise success, failure, empty output,
slow/timeout, and JSON-shaped output without any network access.
"""

import os
import sys
import time


def main() -> int:
    sys.stdin.buffer.read()  # consume the piped prompt
    delay = float(os.environ.get("FAKE_DELAY", "0"))
    if delay:
        time.sleep(delay)
    if os.environ.get("FAKE_STDERR"):
        sys.stderr.write(os.environ["FAKE_STDERR"])
    # Bytes, not text: Windows text-mode stdout would rewrite \n to \r\n,
    # making the canned output platform-dependent.
    sys.stdout.buffer.write(
        os.environ.get("FAKE_STDOUT", "fake response body\n").encode("utf-8")
    )
    return int(os.environ.get("FAKE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
