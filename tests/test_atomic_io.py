"""Tests for the one shared atomic file replacement used across the package."""

import os
import stat
from pathlib import Path

import pytest

from education_pipeline import atomic_io
from education_pipeline.atomic_io import atomic_write_bytes, atomic_write_text


def _flaky_replace(monkeypatch: pytest.MonkeyPatch, failures: int) -> dict:
    """Make ``os.replace`` raise PermissionError ``failures`` times, then work."""

    real_replace = os.replace
    calls = {"count": 0, "sources": []}

    def replace(source, target):
        calls["count"] += 1
        calls["sources"].append(os.fspath(source))
        if calls["count"] <= failures:
            raise PermissionError("sharing violation")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", replace)
    return calls


def test_atomic_write_bytes_writes_content_and_leaves_no_temp_file(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"

    atomic_write_bytes(target, b'{"a": 1}\n')

    assert target.read_bytes() == b'{"a": 1}\n'
    assert [entry.name for entry in tmp_path.iterdir()] == ["manifest.json"]


def test_atomic_write_bytes_creates_missing_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "manifest.json"

    atomic_write_bytes(target, b"{}\n")

    assert target.read_bytes() == b"{}\n"


def test_atomic_write_bytes_replaces_prior_contents_wholesale(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    target.write_bytes(b"a much longer previous payload\n")

    atomic_write_bytes(target, b"{}\n")

    assert target.read_bytes() == b"{}\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode")
def test_atomic_write_bytes_restricts_the_temp_file_before_writing_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The payload may be a secret (the daemon token), and mkstemp has already
    # linked the temp file into the target directory, so the restrictive mode
    # must land before any content does -- and again on the replaced target.
    target = tmp_path / "daemon.json"
    real_chmod = os.chmod
    observed: list[tuple[str, int, int]] = []

    def recording_chmod(path, mode, *args, **kwargs):
        observed.append((os.fspath(path), os.path.getsize(path), mode))
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "chmod", recording_chmod)
    atomic_write_bytes(target, b'{"token": "s3cret"}', mode=0o600)

    assert len(observed) == 2
    temp_name, temp_size, temp_mode = observed[0]
    assert Path(temp_name).name.startswith(".tmp-")
    assert temp_size == 0  # chmod happened before any content was written
    assert temp_mode == 0o600
    assert observed[1] == (os.fspath(target), len(b'{"token": "s3cret"}'), 0o600)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_atomic_write_bytes_cleans_up_temp_file_when_the_write_fails(
    tmp_path: Path,
) -> None:
    target = tmp_path / "manifest.json"
    target.write_bytes(b"original\n")

    with pytest.raises(TypeError):
        atomic_write_bytes(target, "not bytes")  # type: ignore[arg-type]

    assert target.read_bytes() == b"original\n"
    assert [entry.name for entry in tmp_path.iterdir()] == ["manifest.json"]


def test_atomic_write_bytes_cleans_up_temp_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "manifest.json"
    target.write_bytes(b"original\n")

    def failing_replace(source, destination):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        atomic_write_bytes(target, b"{}\n")

    assert target.read_bytes() == b"original\n"
    assert [entry.name for entry in tmp_path.iterdir()] == ["manifest.json"]


def test_atomic_write_bytes_retries_replace_on_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows sharing semantics: os.replace onto a file another process (or
    # thread) holds open for reading fails with PermissionError. Readers are
    # transient, so every writer retries briefly rather than crashing.
    sleeps: list[float] = []
    monkeypatch.setattr(atomic_io.time, "sleep", sleeps.append)
    calls = _flaky_replace(monkeypatch, failures=2)
    target = tmp_path / "manifest.json"

    atomic_write_bytes(target, b"{}\n")

    assert calls["count"] == 3
    assert sleeps == [atomic_io.REPLACE_RETRY_SECONDS] * 2
    assert target.read_bytes() == b"{}\n"


def test_atomic_write_bytes_raises_after_retries_are_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(atomic_io.time, "sleep", sleeps.append)
    calls = _flaky_replace(monkeypatch, failures=atomic_io.REPLACE_ATTEMPTS)
    target = tmp_path / "manifest.json"

    with pytest.raises(PermissionError, match="sharing violation"):
        atomic_write_bytes(target, b"{}\n")

    assert calls["count"] == atomic_io.REPLACE_ATTEMPTS
    assert len(sleeps) == atomic_io.REPLACE_ATTEMPTS - 1
    assert not target.exists()
    assert list(tmp_path.iterdir()) == []  # temp file cleaned up


def test_atomic_write_bytes_can_opt_out_of_the_permission_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _flaky_replace(monkeypatch, failures=1)
    target = tmp_path / "manifest.json"

    with pytest.raises(PermissionError):
        atomic_write_bytes(target, b"{}\n", retry_on_permission_error=False)

    assert calls["count"] == 1
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_bytes_names_the_temp_file_after_the_target_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _flaky_replace(monkeypatch, failures=0)

    atomic_write_bytes(tmp_path / "job.json", b"{}\n")

    temp_name = Path(calls["sources"][0]).name
    assert temp_name.startswith(".tmp-")
    assert temp_name.endswith(".json")


def test_atomic_write_bytes_honors_custom_temp_naming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _flaky_replace(monkeypatch, failures=0)
    target = tmp_path / "visual-profile.toml"

    atomic_write_bytes(
        target, b"id = 'x'\n", tmp_prefix=f".{target.name}.", tmp_suffix=".tmp"
    )

    temp_name = Path(calls["sources"][0]).name
    assert temp_name.startswith(".visual-profile.toml.")
    assert temp_name.endswith(".tmp")


def test_atomic_write_bytes_fsyncs_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_fsync = os.fsync
    synced: list[int] = []

    def recording_fsync(fd):
        synced.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)

    atomic_write_bytes(tmp_path / "a.toml", b"a\n")
    assert synced == []

    atomic_write_bytes(tmp_path / "b.toml", b"b\n", fsync=True)
    assert len(synced) == 1


def test_atomic_write_text_encodes_utf8_without_newline_translation(
    tmp_path: Path,
) -> None:
    target = tmp_path / "plan.toml"

    atomic_write_text(target, 'title = "café"\nline\r\nnext\n')

    assert target.read_bytes() == 'title = "café"\nline\r\nnext\n'.encode("utf-8")


def test_atomic_write_text_forwards_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _flaky_replace(monkeypatch, failures=1)
    monkeypatch.setattr(atomic_io.time, "sleep", lambda _seconds: None)
    target = tmp_path / "workspaces.json"

    atomic_write_text(
        target, "{}\n", tmp_prefix=f".{target.name}.", tmp_suffix=".tmp"
    )

    assert calls["count"] == 2
    assert Path(calls["sources"][0]).name.startswith(".workspaces.json.")
    assert target.read_text(encoding="utf-8") == "{}\n"
