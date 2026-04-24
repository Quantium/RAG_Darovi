"""Map file pipeline counts to UI onboarding phase labels."""

from __future__ import annotations


def compute_pipeline_phase(
    *,
    total_files: int,
    pending: int,
    downloaded: int,
    converted: int,
    embedded: int,
    failed: int,
    skipped: int,
) -> str:
    """Return a coarse pipeline phase for progress UI.

    Phases: downloading, preparing, embedding, ready, error.
    """
    if total_files == 0:
        return "ready"
    if pending > 0:
        return "downloading"
    if downloaded > 0:
        return "preparing"
    if converted > 0:
        return "embedding"
    if failed > 0 and pending == 0 and downloaded == 0 and converted == 0 and embedded == 0 and skipped == 0:
        return "error"
    terminal = embedded + skipped + failed
    if terminal == total_files:
        return "ready"
    return "embedding"
