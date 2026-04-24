"""Tests for pipeline onboarding phase mapping."""

from __future__ import annotations

from src.drive.onboarding_phase import compute_pipeline_phase


def test_empty_corpus_is_ready() -> None:
    assert (
        compute_pipeline_phase(
            total_files=0,
            pending=0,
            downloaded=0,
            converted=0,
            embedded=0,
            failed=0,
            skipped=0,
        )
        == "ready"
    )


def test_pending_is_downloading() -> None:
    assert (
        compute_pipeline_phase(
            total_files=3,
            pending=2,
            downloaded=1,
            converted=0,
            embedded=0,
            failed=0,
            skipped=0,
        )
        == "downloading"
    )


def test_downloaded_is_preparing() -> None:
    assert (
        compute_pipeline_phase(
            total_files=2,
            pending=0,
            downloaded=2,
            converted=0,
            embedded=0,
            failed=0,
            skipped=0,
        )
        == "preparing"
    )


def test_converted_is_embedding() -> None:
    assert (
        compute_pipeline_phase(
            total_files=2,
            pending=0,
            downloaded=0,
            converted=1,
            embedded=0,
            failed=0,
            skipped=0,
        )
        == "embedding"
    )


def test_all_terminal_is_ready() -> None:
    assert (
        compute_pipeline_phase(
            total_files=2,
            pending=0,
            downloaded=0,
            converted=0,
            embedded=1,
            failed=0,
            skipped=1,
        )
        == "ready"
    )


def test_all_failed_is_error() -> None:
    assert (
        compute_pipeline_phase(
            total_files=2,
            pending=0,
            downloaded=0,
            converted=0,
            embedded=0,
            failed=2,
            skipped=0,
        )
        == "error"
    )
