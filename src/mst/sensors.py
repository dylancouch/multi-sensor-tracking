"""Independent virtual Cartesian position sensors."""

from __future__ import annotations

import hashlib
import random

from .schema import VERSION, Observation, Scenario, Truth


def sensor_seed(run_seed: int, sensor_id: str) -> int:
    """Stable seed derivation, independent of Python's randomized hash()."""
    digest = hashlib.sha256(f"mst-v1:{run_seed}:{sensor_id}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def generate_observations(
    scenario: Scenario, truth: list[Truth], seed: int
) -> list[Observation]:
    """Use only position from truth; never copy object identity into observations."""
    steps = round(scenario.duration_s / scenario.step_s)
    per_time: dict[int, list[Truth]] = {index: [] for index in range(steps + 1)}
    for index, record in enumerate(truth):
        per_time[index // len(scenario.objects)].append(record)

    result: list[Observation] = []
    for sensor in scenario.sensors:
        rng = random.Random(sensor_seed(seed, sensor.sensor_id))
        every = round(sensor.sample_interval_s / scenario.step_s)
        variance = sensor.noise_std_m**2
        covariance = ((variance, 0.0), (0.0, variance))
        serial = 0
        for index in range(0, steps + 1, every):
            positions = [
                (
                    record.state[0] + rng.gauss(0, sensor.noise_std_m),
                    record.state[1] + rng.gauss(0, sensor.noise_std_m),
                )
                for record in per_time[index]
                if sensor.miss_probability == 0
                or rng.random() >= sensor.miss_probability
            ]
            if (
                sensor.false_alarm_probability > 0
                and rng.random() < sensor.false_alarm_probability
            ):
                xmin, ymin, xmax, ymax = sensor.false_alarm_bounds_m
                positions.append((rng.uniform(xmin, xmax), rng.uniform(ymin, ymax)))
            rng.shuffle(positions)
            for position in positions:
                result.append(
                    Observation(
                        VERSION,
                        index * scenario.step_s + sensor.timestamp_offset_s,
                        f"{sensor.sensor_id}-{serial:08d}",
                        sensor.sensor_id,
                        position,
                        covariance,
                        "world",
                        "s",
                    )
                )
                serial += 1
    result.sort(
        key=lambda item: (item.timestamp_s, item.sensor_id, item.observation_id)
    )
    return result
