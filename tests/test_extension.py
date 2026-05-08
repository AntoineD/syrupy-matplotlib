"""Unit tests for `_extension.py`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pytest

from syrupy_matplotlib._extension import MplFigureExtension
from syrupy_matplotlib._extension import _coerce_bytes
from syrupy_matplotlib._params import SnapshotParams
from syrupy_matplotlib._reporting import ResultCollector


def _params() -> SnapshotParams:
    return SnapshotParams(
        tolerance=2.0,
        style="classic",
        backend="agg",
        remove_text=False,
    )


def _fresh_extension(
    *,
    params: SnapshotParams | None = None,
    update_snapshots: bool = False,
    collector: ResultCollector | None = None,
) -> MplFigureExtension:
    ext = MplFigureExtension()
    ext._mpl_params = params if params is not None else _params()
    ext._mpl_collector = collector
    ext._mpl_nodeid = "tests/example.py::test_it"
    ext._mpl_update_snapshots = update_snapshots
    ext._mpl_last_stem = "test_it"
    return ext


def test_serialize_requires_figure() -> None:
    ext = _fresh_extension()
    with pytest.raises(TypeError, match="expected a Figure"):
        ext.serialize([1, 2, 3])


def test_serialize_returns_png_bytes() -> None:
    ext = _fresh_extension()
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    try:
        out = ext.serialize(fig)
    finally:
        plt.close(fig)
    assert out.startswith(b"\x89PNG")


def test_serialize_remove_text_strips_title() -> None:
    params = SnapshotParams(
        tolerance=2.0,
        style="classic",
        backend="agg",
        remove_text=True,
    )
    ext = _fresh_extension(params=params)
    fig, ax = plt.subplots()
    ax.set_title("remove me")
    ax.plot([1, 2])
    try:
        ext.serialize(fig)
    finally:
        plt.close(fig)
    assert ax.get_title() == ""


def test_matches_update_snapshots_equal() -> None:
    """Update mode with byte-equal baseline returns True; serialize records it."""
    coll = ResultCollector()
    ext = _fresh_extension(update_snapshots=True, collector=coll)
    assert ext.matches(serialized_data=b"same", snapshot_data=b"same") is True
    assert coll.records == []


def test_serialize_update_snapshots_records_generated() -> None:
    """`serialize()` is the single source of GENERATED records in update mode."""
    coll = ResultCollector()
    ext = _fresh_extension(update_snapshots=True, collector=coll)
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    try:
        ext.serialize(fig)
    finally:
        plt.close(fig)
    assert len(coll.records) == 1
    assert coll.records[0].passed is True
    assert coll.records[0].image_status == "generated"


def test_matches_update_snapshots_diff_returns_false() -> None:
    """Update mode with differing baseline returns False so syrupy rewrites."""
    coll = ResultCollector()
    ext = _fresh_extension(update_snapshots=True, collector=coll)
    assert ext.matches(serialized_data=b"new", snapshot_data=b"old") is False


def test_record_no_op_without_collector() -> None:
    """`_record` returns early when no collector is stamped."""
    ext = _fresh_extension(update_snapshots=True)
    ext._mpl_collector = None
    # update_snapshots + no collector: byte-equality path still runs.
    assert ext.matches(serialized_data=b"x", snapshot_data=b"x") is True


def test_serialize_update_no_collector_no_record() -> None:
    """`serialize()` in update mode is a no-op for the collector when not stamped."""
    ext = _fresh_extension(update_snapshots=True, collector=None)
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    try:
        # Should not raise even though `_record` runs without a collector.
        out = ext.serialize(fig)
    finally:
        plt.close(fig)
    assert out.startswith(b"\x89PNG")


def test_matches_bytes_equal_fast_path_no_filesystem_io(tmp_path: Path) -> None:
    """Bytes-equal baseline with no report flag: MATCH without touching disk."""
    results_root = tmp_path / "figure-report"
    coll = ResultCollector(results_root=results_root)
    ext = _fresh_extension(collector=coll)
    ext._mpl_keep_match_artifacts = False
    ext._mpl_test_filepath = str(tmp_path / "test_it.py")
    ext._mpl_rootpath = tmp_path

    same = b"\x89PNG identical bytes"
    assert ext.matches(serialized_data=same, snapshot_data=same) is True

    assert not results_root.exists()
    assert len(coll.records) == 1
    record = coll.records[0]
    assert record.image_status == "match"
    assert record.passed is True
    assert record.result_image is None
    assert record.baseline_image is None
    assert record.diff_image is None


def test_matches_bytes_equal_with_keep_artifacts_falls_through(tmp_path: Path) -> None:
    """When report flag is set, fast path is bypassed so artifacts are written."""
    results_root = tmp_path / "figure-report"
    coll = ResultCollector(results_root=results_root)
    ext = _fresh_extension(collector=coll)
    ext._mpl_keep_match_artifacts = True
    ext._mpl_test_filepath = str(tmp_path / "test_it.py")
    ext._mpl_rootpath = tmp_path

    # Use real PNG bytes so compare_images() can decode them.
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    try:
        png = ext.serialize(fig)
    finally:
        plt.close(fig)

    assert ext.matches(serialized_data=png, snapshot_data=png) is True
    assert results_root.exists()
    record = coll.records[0]
    assert record.image_status == "match"
    assert record.result_image is not None
    assert record.baseline_image is not None


def test_artifact_subdir_falls_back_when_outside_rootpath(tmp_path: Path) -> None:
    """Files outside the pytest rootpath get a `<stem>-<sha1>` subdir."""
    ext = _fresh_extension()
    # Test file lives outside rootpath: relative_to() raises ValueError,
    # hash fallback fires.
    ext._mpl_rootpath = tmp_path / "project"
    ext._mpl_test_filepath = str(tmp_path / "elsewhere" / "test_thing.py")

    sub = ext._artifact_subdir()
    assert sub.name.startswith("test_thing-")
    assert len(sub.name) == len("test_thing-") + 8


def test_artifact_subdir_returns_empty_when_filepath_unset() -> None:
    """No test filepath stamped → no subdir."""
    ext = _fresh_extension()
    ext._mpl_test_filepath = None
    assert ext._artifact_subdir() == Path()


def test_artifact_subdir_falls_back_when_rootpath_unset(tmp_path: Path) -> None:
    """No rootpath stamped → still falls back to `<stem>-<sha1>`."""
    ext = _fresh_extension()
    ext._mpl_rootpath = None
    ext._mpl_test_filepath = str(tmp_path / "test_thing.py")
    sub = ext._artifact_subdir()
    assert sub.name.startswith("test_thing-")


def test_matches_missing_baseline_records_missing(tmp_path: Path) -> None:
    """Non-update mode with no baseline records a MISSING result and returns False."""
    coll = ResultCollector(results_root=tmp_path)
    ext = _fresh_extension(collector=coll)
    assert ext.matches(serialized_data=b"\x89PNG fake", snapshot_data=None) is False
    assert len(coll.records) == 1
    record = coll.records[0]
    assert record.image_status == "missing"
    assert record.passed is False
    assert record.error_message == "Baseline image not found on disk."


def test_diff_lines_default_message() -> None:
    ext = _fresh_extension()
    ext._mpl_last_failure_message = None
    out = ext.diff_lines(b"", b"")
    assert out == ["Figure comparison failed."]


def test_diff_lines_uses_stashed_message() -> None:
    ext = _fresh_extension()
    ext._mpl_last_failure_message = "line1\nline2"
    assert ext.diff_lines(b"", b"") == ["line1", "line2"]


def test_coerce_bytes_roundtrip() -> None:
    assert _coerce_bytes(b"abc") == b"abc"


def test_coerce_bytes_memoryview() -> None:
    mv: Any = memoryview(b"xyz")
    assert _coerce_bytes(mv) == b"xyz"
