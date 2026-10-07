
from __future__ import annotations

import argparse
import logging
import math
import shutil
import subprocess
import time
from pathlib import Path

LOGGER = logging.getLogger("health_monitor")


def _cpu_counters() -> tuple[int, int]:
    with open("/proc/stat", encoding="ascii") as stat_file:
        fields = stat_file.readline().split()

    if not fields or fields[0] != "cpu" or len(fields) < 5:
        raise RuntimeError("Could not read aggregate CPU counters from /proc/stat")

    counters = [int(value) for value in fields[1:9]]
    total = sum(counters)
    idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
    return total, idle


def cpu_usage(sample_interval: float) -> float:
    total_before, idle_before = _cpu_counters()
    time.sleep(sample_interval)
    total_after, idle_after = _cpu_counters()

    total_delta = total_after - total_before
    idle_delta = idle_after - idle_before
    if total_delta <= 0:
        raise RuntimeError("CPU counters did not advance during the sample")

    return 100.0 * (total_delta - idle_delta) / total_delta


def memory_usage() -> tuple[int, int, float]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as meminfo:
        for line in meminfo:
            key, separator, value = line.partition(":")
            if separator and key in {"MemTotal", "MemAvailable", "MemFree", "Buffers", "Cached"}:
                values[key] = int(value.split()[0])

    total = values.get("MemTotal")
    if not total:
        raise RuntimeError("Could not read MemTotal from /proc/meminfo")

    available = values.get("MemAvailable")
    if available is None:
        required = ("MemFree", "Buffers", "Cached")
        if not all(key in values for key in required):
            raise RuntimeError("Could not determine available RAM from /proc/meminfo")
        available = sum(values[key] for key in required)

    used = max(0, total - available)
    return used, total, 100.0 * used / total


def disk_usage(path: Path) -> tuple[int, int, float]:
    usage = shutil.disk_usage(path)
    if usage.total <= 0:
        raise RuntimeError(f"Disk capacity for {path} is zero")
    used = usage.total - usage.free
    return used, usage.total, 100.0 * used / usage.total


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def percentage(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0 <= parsed <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=percentage,
        default=80.0,
        help="trigger log rotation above this disk utilization percentage (default: 80)",
    )
    parser.add_argument(
        "--interval",
        type=positive_float,
        default=60.0,
        help="seconds between health checks (default: 60)",
    )
    parser.add_argument(
        "--cpu-sample-interval",
        type=positive_float,
        default=1.0,
        help="seconds used to sample CPU utilization (default: 1)",
    )
    parser.add_argument(
        "--disk-path",
        type=Path,
        default=Path("/"),
        help="filesystem path whose disk usage is monitored (default: /)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("/var/log/myapp"),
        help="directory containing application .log files",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path("/var/backups/myapp"),
        help="directory where timestamped archives are saved",
    )
    parser.add_argument(
        "--rotator",
        type=Path,
        default=Path(__file__).with_name("log_rotator.sh"),
        help="path to the Bash log rotator script",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="perform one health check and exit instead of polling continuously",
    )
    return parser.parse_args()


def check_system(args: argparse.Namespace) -> None:
    cpu = cpu_usage(args.cpu_sample_interval)
    ram_used, ram_total, ram_percent = memory_usage()
    disk_used, disk_total, disk_percent = disk_usage(args.disk_path)

    LOGGER.info(
        "CPU: %.1f%% | RAM: %.1f%% (%s / %s KiB) | Disk (%s): %.1f%% (%s / %s bytes)",
        cpu,
        ram_percent,
        f"{ram_used:,}",
        f"{ram_total:,}",
        args.disk_path,
        disk_percent,
        f"{disk_used:,}",
        f"{disk_total:,}",
    )

    if disk_percent > args.threshold:
        LOGGER.warning(
            "Disk utilization %.1f%% exceeds the %.1f%% threshold; starting log rotation",
            disk_percent,
            args.threshold,
        )
        subprocess.run(
            [
                "bash",
                str(args.rotator),
                str(args.log_dir),
                str(args.backup_dir),
            ],
            check=True,
        )


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = parse_args()

    try:
        while True:
            check_system(args)
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        LOGGER.info("Health monitoring stopped")
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        LOGGER.error("Health monitoring failed: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
