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
    vision_pending: int = 0,
    vision_processing: int = 0,
    vision_failed: int = 0,
) -> str:
    """Return a coarse pipeline phase for progress UI.

    Phases: downloading, preparing, transcribing, embedding, ready, error.
    `transcribing` covers the VLM stage (Llama-3.2-Vision via Ollama),
    which is the slowest segment of the pipeline and therefore deserves
    its own label so the UI does not falsely report "ready".
    """
    if total_files == 0:
        return "ready"
    if pending > 0:
        return "downloading"
    if downloaded > 0:
        return "preparing"
    if vision_pending > 0 or vision_processing > 0:
        return "transcribing"
    if converted > 0:
        return "embedding"
    if (
        failed + vision_failed > 0
        and pending == 0
        and downloaded == 0
        and converted == 0
        and embedded == 0
        and skipped == 0
        and vision_pending == 0
        and vision_processing == 0
    ):
        return "error"
    terminal = embedded + skipped + failed + vision_failed
    if terminal == total_files:
        return "ready"
    return "embedding"
