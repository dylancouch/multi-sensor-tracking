"""Analytic fixed-step constant-velocity truth in a local world frame."""

from __future__ import annotations

from .schema import VERSION, Scenario, Truth


def generate_truth(scenario: Scenario) -> list[Truth]:
    """Include both t=0 and t=duration_s, with no process noise."""
    steps = round(scenario.duration_s / scenario.step_s)
    result: list[Truth] = []
    for index in range(steps + 1):
        t = index * scenario.step_s
        for obj in scenario.objects:
            px, py, vx, vy = obj.initial_state
            result.append(
                Truth(
                    VERSION,
                    t,
                    obj.object_id,
                    (px + vx * t, py + vy * t, vx, vy),
                    "world",
                    "m",
                    "m/s",
                )
            )
    return result
