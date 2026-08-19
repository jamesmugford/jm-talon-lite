"""Immutable Control Mouse gaze samples and formatting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GazeSample:
    """One normalized gaze sample with its corresponding pointer position."""

    timestamp: float
    x: float
    y: float
    gaze_x: float
    gaze_y: float
    delta_x: float | None = None
    delta_y: float | None = None


def format_gaze_sample(sample: GazeSample | None) -> str:
    """Format one Control Mouse sample for diagnostic logging."""
    if sample is None:
        return "control1 no samples"
    line = f"control1 ts={sample.timestamp:.3f} xy_px=({sample.x:.1f},{sample.y:.1f}) "
    if sample.delta_x is not None and sample.delta_y is not None:
        line += f"delta=({sample.delta_x:.2f},{sample.delta_y:.2f}) "
    return line + f"gaze_norm=({sample.gaze_x:.3f},{sample.gaze_y:.3f})"
