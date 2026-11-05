"""Per-epoch evaluation diagnostics with explicit truth-free gaps."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import linear_sum_assignment

from .evaluation import identity_metrics, score
from .innovations import Innovation
from .schema import Observation, SchemaError, TrackEstimate, Truth

_matplotlib_cache: tempfile.TemporaryDirectory[str] | None = None


def diagnostic_report(
    observations: list[Observation],
    estimates: list[TrackEstimate],
    *,
    truth: list[Truth] | None = None,
    innovations: list[Innovation] | None = None,
    gate_m: float = 10.0,
) -> dict[str, Any]:
    """Return counts and values for plots from validated tracker artifacts."""
    if not math.isfinite(gate_m) or not 0 < gate_m <= 1e6:
        raise SchemaError("gate_m must be finite and in (0, 1e6]")
    observation_by_id = {item.observation_id: item for item in observations}
    if len(observation_by_id) != len(observations):
        raise SchemaError("duplicate observation_id")
    for observation_item in observations:
        Observation.from_dict(observation_item.to_dict())
    final: dict[tuple[float, str], TrackEstimate] = {}
    for estimate_item in estimates:
        TrackEstimate.from_dict(estimate_item.to_dict())
        final[(estimate_item.timestamp_s, estimate_item.track_id)] = estimate_item
    nis_by_time: dict[float, list[float]] = defaultdict(list)
    if innovations is not None:
        seen: set[str] = set()
        for innovation_item in innovations:
            Innovation.from_dict(innovation_item.to_dict())
            if innovation_item.observation_id in seen:
                raise SchemaError("duplicate innovation observation_id")
            seen.add(innovation_item.observation_id)
            observation = observation_by_id.get(innovation_item.observation_id)
            linked = final.get((innovation_item.timestamp_s, innovation_item.track_id))
            if (
                observation is None
                or observation.timestamp_s != innovation_item.timestamp_s
                or observation.sensor_id != innovation_item.sensor_id
                or linked is None
                or linked.method == "baseline"
            ):
                raise SchemaError("innovation does not match observation and track")
            if innovation_item.nis is not None:
                nis_by_time[innovation_item.timestamp_s].append(innovation_item.nis)
    truth_by_time: dict[float, list[Truth]] = defaultdict(list)
    if truth is not None:
        if not truth:
            raise SchemaError("cannot diagnose an empty reference")
        seen_truth: set[tuple[float, str]] = set()
        for truth_item in truth:
            Truth.from_dict(truth_item.to_dict())
            key = (truth_item.timestamp_s, truth_item.object_id)
            if key in seen_truth:
                raise SchemaError("duplicate truth timestamp/object_id")
            seen_truth.add(key)
            truth_by_time[truth_item.timestamp_s].append(truth_item)
    times = sorted(
        set(truth_by_time)
        if truth is not None
        else {
            *(item.timestamp_s for item in observations),
            *(item.timestamp_s for item in estimates),
        }
    )
    live_by_time: dict[float, list[TrackEstimate]] = defaultdict(list)
    for (timestamp, _), estimate_item in final.items():
        if estimate_item.lifecycle != "deleted":
            live_by_time[timestamp].append(estimate_item)
    previous_track: dict[str, str] = {}
    series: list[dict[str, Any]] = []
    for timestamp in times:
        actual = sorted(truth_by_time[timestamp], key=lambda item: item.object_id)
        predicted = sorted(live_by_time[timestamp], key=lambda item: item.track_id)
        matches: list[tuple[int, int]] = []
        if actual and predicted:
            distances = np.asarray(
                [
                    [
                        math.hypot(a.state[0] - b.state[0], a.state[1] - b.state[1])
                        for b in predicted
                    ]
                    for a in actual
                ]
            )
            penalty = (max(len(actual), len(predicted)) + 1) * gate_m + 1
            rows, columns = linear_sum_assignment(
                np.where(distances <= gate_m, distances, penalty)
            )
            matches = [
                (int(row), int(column))
                for row, column in zip(rows, columns, strict=True)
                if distances[row, column] <= gate_m
            ]
        errors: list[float] = []
        nees: list[float] = []
        switches = 0
        for row, column in matches:
            a, b = actual[row], predicted[column]
            errors.append(math.hypot(a.state[0] - b.state[0], a.state[1] - b.state[1]))
            if (
                a.object_id in previous_track
                and previous_track[a.object_id] != b.track_id
            ):
                switches += 1
            previous_track[a.object_id] = b.track_id
            if b.method != "baseline":
                try:
                    covariance = np.asarray(b.covariance, dtype=float)
                    factor, lower = cho_factor(
                        covariance, lower=True, check_finite=True
                    )
                    residual = np.asarray(b.state) - np.asarray(a.state)
                    value = float(residual @ cho_solve((factor, lower), residual))
                    if math.isfinite(value):
                        nees.append(value)
                except np.linalg.LinAlgError:
                    pass
        nises = nis_by_time[timestamp]
        series.append(
            {
                "timestamp_s": timestamp,
                "truth_states": len(actual) if truth is not None else None,
                "estimate_states": len(predicted),
                "misses": len(actual) - len(matches) if truth is not None else None,
                "false_tracks": len(predicted) - len(matches)
                if truth is not None
                else None,
                "identity_changes": switches if truth is not None else None,
                "position_error_mean_m": statistics.fmean(errors) if errors else None,
                "position_error_samples": len(errors),
                "nees_mean": statistics.fmean(nees) if nees else None,
                "nees_samples": len(nees),
                "nis_mean": statistics.fmean(nises) if nises else None,
                "nis_samples": len(nises),
            }
        )
    metrics = (
        score(
            truth,
            estimates,
            gate_m=gate_m,
            innovations=innovations,
            observations=observations,
        )
        if truth is not None
        else None
    )
    if metrics is not None and (
        sum(item["misses"] for item in series) != metrics["unmatched_truth_states"]
        or sum(item["false_tracks"] for item in series)
        != metrics["unmatched_estimate_states"]
        or sum(item["identity_changes"] for item in series) != metrics["id_switches"]
    ):
        raise RuntimeError("diagnostic series disagrees with validated scorer")
    return {
        "schema_version": 1,
        "reference_available": truth is not None,
        "matching_gate_m": gate_m if truth is not None else None,
        "scoring": metrics,
        "identity": identity_metrics(truth, estimates, gate_m=gate_m)
        if truth is not None
        else None,
        "series": series,
        "unavailable": (
            []
            if truth is not None
            else [
                "misses",
                "false_tracks",
                "identity_changes",
                "position_error_mean_m",
                "nees_mean",
                "identity",
            ]
        )
        + (["nis_mean"] if innovations is None else []),
        "innovation_available": innovations is not None,
    }


def write_diagnostic_report(path: Path, report: dict[str, Any]) -> None:
    data = (
        json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()
    with path.open("xb") as stream:
        stream.write(data)


def plot_diagnostics(path: Path, report: dict[str, Any]) -> None:
    """Write a six-panel headless PNG or SVG with unavailable data explicit."""
    if path.suffix.lower() not in (".png", ".svg"):
        raise SchemaError("diagnostic plot must be PNG or SVG")
    global _matplotlib_cache
    if "MPLCONFIGDIR" not in os.environ:
        _matplotlib_cache = tempfile.TemporaryDirectory(prefix="mst-mpl-")
        os.environ["MPLCONFIGDIR"] = _matplotlib_cache.name
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("diagnostic plots require the plot extra") from exc
    series = report["series"]
    times = [item["timestamp_s"] for item in series]
    panels = (
        ("misses", "Missed reference states", "count", "truth"),
        ("false_tracks", "Unmatched estimate states", "count", "truth"),
        ("identity_changes", "Identity changes", "count", "truth"),
        ("position_error_mean_m", "Mean position error", "m", "truth"),
        ("nees_mean", "Mean NEES", "squared", "nees"),
        ("nis_mean", "Mean NIS", "squared", "nis"),
    )
    fig, axes = plt.subplots(3, 2, figsize=(12, 11), constrained_layout=True)
    for ax, (key, title, unit, sample_kind) in zip(axes.flat, panels, strict=True):
        values = [item[key] for item in series]
        available = [
            (time, value)
            for time, value in zip(times, values, strict=True)
            if value is not None
        ]
        if key == "position_error_mean_m":
            count = sum(item["position_error_samples"] for item in series)
        elif key == "false_tracks":
            count = sum(item["estimate_states"] for item in series)
        elif sample_kind == "truth":
            count = sum(item["truth_states"] or 0 for item in series)
        elif sample_kind == "nees":
            count = sum(item["nees_samples"] for item in series)
        else:
            count = sum(item["nis_samples"] for item in series)
        ax.set_title(f"{title} (n={count})")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel(unit)
        if available:
            ax.plot(
                [item[0] for item in available],
                [item[1] for item in available],
                marker="o",
            )
            ax.grid(alpha=0.25)
            if unit == "count":
                ax.set_ylim(-0.1, max(1.0, max(item[1] for item in available) * 1.15))
        else:
            reason = (
                "no independent reference"
                if not report["reference_available"] and key != "nis_mean"
                else "no usable samples"
            )
            if key == "nis_mean" and not report["innovation_available"]:
                reason = "innovation artifact unavailable"
            ax.text(
                0.5,
                0.5,
                f"Unavailable: {reason}",
                transform=ax.transAxes,
                ha="center",
                va="center",
            )
    fig.suptitle(
        "Tracking diagnostics — exact-time matching; means use available samples"
    )
    output = io.BytesIO()
    try:
        fig.savefig(output, format=path.suffix[1:].lower(), dpi=140)
    finally:
        plt.close(fig)
    with path.open("xb") as stream:
        stream.write(output.getvalue())


def attach_hashes(
    value: dict[str, Any],
    *,
    observation_path: Path,
    track_path: Path,
    truth_path: Path | None = None,
    innovation_path: Path | None = None,
    source_path: Path | None = None,
) -> None:
    """Bind a diagnostic report to the exact input artifacts."""
    paths = {
        "observations": observation_path,
        "tracks": track_path,
        "truth": truth_path,
        "innovations": innovation_path,
        "source_record": source_path,
    }
    value["input_sha256"] = {
        name: hashlib.sha256(path.read_bytes()).hexdigest() if path else None
        for name, path in paths.items()
    }
