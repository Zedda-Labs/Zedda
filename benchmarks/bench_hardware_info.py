"""
benchmarks/bench_hardware_info.py — Hardware detection for normalized benchmarking.

Captures CPU architecture, core counts (physical & logical), RAM, and system specs
so all benchmarks report hardware-normalized metrics (rows/sec/core).
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HardwareInfo:
    cpu_model: str
    physical_cores: int
    logical_cores: int
    ram_gb: float
    os_name: str
    python_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_model": self.cpu_model,
            "physical_cores": self.physical_cores,
            "logical_cores": self.logical_cores,
            "ram_gb": round(self.ram_gb, 2),
            "os_name": self.os_name,
            "python_version": self.python_version,
        }

    def summary(self) -> str:
        return (
            f"{self.cpu_model} ({self.physical_cores}P/{self.logical_cores}L cores) | "
            f"{self.ram_gb:.1f} GB RAM | {self.os_name} | Python {self.python_version}"
        )


def _get_cpu_model_windows() -> str:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        model, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        winreg.CloseKey(key)
        return str(model).strip()
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["wmic", "cpu", "get", "name"], text=True, stderr=subprocess.DEVNULL
        )
        lines = [line.strip() for line in out.splitlines() if line.strip() and "Name" not in line]
        if lines:
            return lines[0]
    except Exception:
        pass
    return platform.processor() or "Unknown CPU"


def _get_physical_cores_windows(logical: int) -> int:
    try:
        out = subprocess.check_output(
            ["wmic", "cpu", "get", "NumberOfCores"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        lines = [line.strip() for line in out.splitlines() if line.strip() and "NumberOfCores" not in line]
        if lines and lines[0].isdigit():
            return int(lines[0])
    except Exception:
        pass
    # Conservative fallback for hyperthreaded dual/quad cores
    return max(1, logical // 2) if logical > 1 else 1


def _get_ram_gb_windows() -> float:
    try:
        out = subprocess.check_output(
            ["wmic", "computersystem", "get", "totalphysicalmemory"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        lines = [line.strip() for line in out.splitlines() if line.strip() and "TotalPhysicalMemory" not in line]
        if lines and lines[0].isdigit():
            return int(lines[0]) / (1024**3)
    except Exception:
        pass
    return 0.0


def get_hardware_info() -> HardwareInfo:
    """Detect and return current system hardware specifications."""
    logical_cores = os.cpu_count() or 1

    if sys.platform == "win32":
        cpu_model = _get_cpu_model_windows()
        physical_cores = _get_physical_cores_windows(logical_cores)
        ram_gb = _get_ram_gb_windows()
    else:
        cpu_model = platform.processor() or "Unknown CPU"
        physical_cores = max(1, logical_cores // 2)
        ram_gb = 0.0

    os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    return HardwareInfo(
        cpu_model=cpu_model,
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        ram_gb=ram_gb,
        os_name=os_info,
        python_version=py_ver,
    )


if __name__ == "__main__":
    hw = get_hardware_info()
    print("Detected Hardware:")
    print(hw.summary())
