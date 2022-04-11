"""
Definition of different benchmark-types.
"""
from __future__ import annotations

import dataclasses
import logging
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any
import re

from galaxy_benchmarker.benchmarks import base
from galaxy_benchmarker.bridge import ansible
from galaxy_benchmarker.utils.posix import PosixBenchmarkDestination

if TYPE_CHECKING:
    from galaxy_benchmarker.benchmarker import Benchmarker

log = logging.getLogger(__name__)


@dataclasses.dataclass
class DdConfig:
    blocksize: str
    blockcount: str

    def asdict(self):
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}


def parse_result_file(file: Path) -> dict[str, Any]:
    if not file.is_file():
        raise ValueError(f"{file} is not a file.")

    with file.open() as file_handle:
        last_line = file_handle.readlines()[-1]

    match = re.search(r" s, ([0-9\.]+) MB/s$", last_line)
    if match:
        bw = float(match.groups()[0])
    else:
        bw = 0

    return {"bw_in_mb": bw}


@base.register_benchmark
class DdFixedParams(base.Benchmark):
    """Benchmarking system with 'dd'"""

    dd_config_default = DdConfig(
        blocksize="1G",
        blockcount="1"
    )

    def __init__(self, name: str, config: dict, benchmarker: Benchmarker):
        super().__init__(name, config, benchmarker)

        merged_dict = {**self.dd_config_default.asdict(), **config.get("dd", {})}
        self.merged_dd_config = DdConfig(**merged_dict)

        self.destinations: list[PosixBenchmarkDestination] = []
        for item in config.get("destinations", []):
            self.destinations.append(PosixBenchmarkDestination(**item))

        if not self.destinations:
            raise ValueError(
                f"At least one destination is required for benchmark {self.__class__.__name__}"
            )

        self._run_task = ansible.AnsibleTask(playbook="run_dd_benchmark.yml")

    def run(self):
        """Run 'dd' on each destination"""

        with tempfile.TemporaryDirectory() as temp_dir:
            for dest in self.destinations:
                log.info("Start %s for %s", self.name, dest.name)
                self.benchmark_results[dest.name] = []
                for i in range(self.repetitions):
                    log.info("Run %d of %d", i + 1, self.repetitions)
                    result_file = Path(temp_dir) / f"{self.name}_{dest.name}_{i}.json"

                    result = self._run_at(result_file, dest, self.merged_dd_config)
                    self.benchmark_results[dest.name].append(result)

    def _run_at(
        self, result_file: Path, dest: PosixBenchmarkDestination, dd_config: DdConfig
    ) -> dict:
        """Perform a single run"""

        start_time = time.monotonic()

        self._run_task.run_at(
            dest.host,
            {
                "dd_dir": dest.target_folder,
                "dd_result_file": result_file.name,
                "controller_dir": result_file.parent,
                **{f"dd_{key}": value for key, value in dd_config.asdict().items()},
            },
        )

        total_runtime = time.monotonic() - start_time

        result = parse_result_file(result_file)
        result["runtime_in_s"] = total_runtime
        log.info("Run took %d s", total_runtime)

        return result


@base.register_benchmark
class DdOneDimParams(DdFixedParams):
    """Run dd with multiple values for a singel dimension"""

    def __init__(self, name: str, config: dict, benchmarker: Benchmarker):
        super().__init__(name, config, benchmarker)

        if len(self.destinations) != 1:
            raise ValueError(f"A single destination is required for {name}")

        self.dim_key = config.get("dim_key", None)
        if not self.dim_key:
            raise ValueError(
                f"Property 'dim_key' (str) is missing for {name}. Must be a vaild dd_config property name"
            )

        self.dim_values = config.get("dim_values", [])
        if not self.dim_values:
            raise ValueError(
                f"Property 'dim_values' (list) is missing for {name}. Must be a list of values for 'dim_key'"
            )

        # Validate configurations
        key = self.dim_key
        for value in self.dim_values:
            dataclasses.replace(self.merged_dd_config, **{key: value})

    def run(self):
        """Run 'dd', only a single destination supported"""

        with tempfile.TemporaryDirectory() as temp_dir:
            dest = self.destinations[0]

            key = self.dim_key
            for value in self.dim_values:
                log.info("Run with %s set to %s", key, value)

                current_config = dataclasses.replace(
                    self.merged_dd_config, **{key: value}
                )

                self.benchmark_results[value] = []
                for i in range(self.repetitions):
                    log.info("Run %d of %d", i + 1, self.repetitions)

                    result_file = Path(temp_dir) / f"{self.name}_{value}_{i}.json"
                    result = self._run_at(result_file, dest, current_config)
                    self.benchmark_results[value].append(result)

    def get_tags(self) -> dict[str, str]:
        return {
            **super().get_tags(),
            "dim_key": self.dim_key,
            "dim_values": self.dim_values,
        }