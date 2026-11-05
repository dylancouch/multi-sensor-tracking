"""Optional headless plots for validated synthetic runs."""

from __future__ import annotations

import io
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .schema import Observation, SchemaError, TrackEstimate, Truth

_matplotlib_cache: tempfile.TemporaryDirectory[str] | None = None


def make_figure(
    truth: list[Truth], observations: list[Observation], estimates: list[TrackEstimate]
) -> Any:
    global _matplotlib_cache
    if "MPLCONFIGDIR" not in os.environ:
        _matplotlib_cache = tempfile.TemporaryDirectory(prefix="mst-mpl-")
        os.environ["MPLCONFIGDIR"] = _matplotlib_cache.name
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Ellipse
    except ImportError as exc:
        raise SchemaError(
            "plotting requires the optional dependency: pip install -e '.[plot]'"
        ) from exc

    figure, axis = plt.subplots(figsize=(8, 6), layout="constrained")
    truth_groups: dict[str, list[Truth]] = defaultdict(list)
    for truth_item in truth:
        truth_groups[truth_item.object_id].append(truth_item)
    for object_id, truth_group in sorted(truth_groups.items()):
        axis.plot(
            [truth_item.state[0] for truth_item in truth_group],
            [truth_item.state[1] for truth_item in truth_group],
            marker="o",
            linewidth=1.7,
            label=f"truth {object_id}",
        )

    sensor_groups: dict[str, list[Observation]] = defaultdict(list)
    for sensor_item in observations:
        sensor_groups[sensor_item.sensor_id].append(sensor_item)
    for sensor_id, sensor_group in sorted(sensor_groups.items()):
        axis.scatter(
            [sensor_item.position_m[0] for sensor_item in sensor_group],
            [sensor_item.position_m[1] for sensor_item in sensor_group],
            marker="x",
            s=22,
            alpha=0.65,
            label=f"observation {sensor_id}",
        )

    # Keep the final update at each track/time, matching the scoring convention.
    final: dict[tuple[str, float], TrackEstimate] = {}
    for track_item in estimates:
        final[(track_item.track_id, track_item.timestamp_s)] = track_item
    track_groups: dict[str, list[TrackEstimate]] = defaultdict(list)
    for track_item in final.values():
        if track_item.lifecycle != "deleted":
            track_groups[track_item.track_id].append(track_item)
    for track_id, track_group in sorted(track_groups.items()):
        track_group.sort(key=lambda track_item: track_item.timestamp_s)
        axis.plot(
            [track_item.state[0] for track_item in track_group],
            [track_item.state[1] for track_item in track_group],
            linestyle="--",
            linewidth=1.5,
            label=f"estimate {track_id}",
        )
        stride = max(1, math.ceil(len(track_group) / 20))
        for track_item in track_group[::stride]:
            covariance = np.asarray(track_item.covariance, dtype=float)[:2, :2]
            eigenvalues, vectors = np.linalg.eigh((covariance + covariance.T) / 2)
            if np.min(eigenvalues) < -1e-10 or np.max(eigenvalues) <= 0:
                continue
            eigenvalues = np.maximum(eigenvalues, 0)
            major = vectors[:, 1]
            angle = math.degrees(math.atan2(major[1], major[0]))
            radius = math.sqrt(5.991464547)  # chi-square 2 dof, 95% region
            ellipse = Ellipse(
                (track_item.state[0], track_item.state[1]),
                2 * radius * math.sqrt(eigenvalues[1]),
                2 * radius * math.sqrt(eigenvalues[0]),
                angle=angle,
                fill=False,
                edgecolor="tab:gray",
                alpha=0.35,
                linewidth=0.7,
            )
            axis.add_patch(ellipse)
    axis.set_title("Synthetic trajectories and nominal 95% covariance regions")
    axis.set_xlabel("World x (m)")
    axis.set_ylabel("World y (m)")
    axis.set_aspect("equal", adjustable="datalim")
    axis.grid(True, alpha=0.25)
    if truth_groups or sensor_groups or track_groups:
        axis.legend(loc="best", fontsize="small")
    return figure


def plot_run(
    output: Path,
    truth: list[Truth],
    observations: list[Observation],
    estimates: list[TrackEstimate],
) -> None:
    suffix = output.suffix.lower()
    if suffix not in (".png", ".svg"):
        raise SchemaError("plot output must end in .png or .svg")
    figure = make_figure(truth, observations, estimates)
    try:
        buffer = io.BytesIO()
        figure.savefig(buffer, format=suffix[1:], dpi=150)
        with output.open("xb") as stream:
            stream.write(buffer.getvalue())
    finally:
        import matplotlib.pyplot as plt

        plt.close(figure)
