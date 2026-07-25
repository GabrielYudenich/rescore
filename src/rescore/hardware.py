"""Portable hardware inventory used to size local inference and training."""

from __future__ import annotations

import ctypes
import json
import platform
import shutil
import subprocess
from pathlib import Path


def _cpu_name() -> str:
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                if value.strip():
                    return value.strip()
        except OSError:
            pass
    return platform.processor() or "unknown"


def _ram_bytes() -> int | None:
    if platform.system() == "Windows":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical)
    return None


def _nvidia_gpus() -> list[dict]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        windows_path = (
            Path("C:/Windows/System32/DriverStore/FileRepository")
            if platform.system() == "Windows"
            else None
        )
        if windows_path and windows_path.is_dir():
            candidates = list(windows_path.glob("nv*/*nvidia-smi.exe"))
            executable = str(candidates[0]) if candidates else None
    if not executable:
        return []
    process = subprocess.run(
        [
            executable,
            "--query-gpu=name,memory.total,driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if process.returncode:
        return []
    result = []
    for line in process.stdout.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 3:
            continue
        result.append(
            {
                "name": fields[0],
                "vram_mb": int(fields[1]),
                "driver": fields[2],
                "compute_capability": fields[3] if len(fields) > 3 else None,
            }
        )
    return result


def inspect_hardware(path: Path | None = None) -> dict:
    """Return a privacy-safe local hardware summary."""
    disk = shutil.disk_usage((path or Path.cwd()).resolve())
    ram = _ram_bytes()
    gpus = _nvidia_gpus()
    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {
            "name": _cpu_name(),
            "logical_cores": __import__("os").cpu_count(),
        },
        "memory": {
            "ram_gb": round(ram / 1024**3, 2) if ram is not None else None,
        },
        "gpus": gpus,
        "storage": {
            "path": str((path or Path.cwd()).resolve()),
            "total_gb": round(disk.total / 1024**3, 1),
            "free_gb": round(disk.free / 1024**3, 1),
        },
        "training_guidance": {
            "local_inference": "supported",
            "small_staff_finetuning": (
                "possible_with_small_batches"
                if any(gpu["vram_mb"] >= 4096 for gpu in gpus)
                else "cpu_or_external_gpu_recommended"
            ),
            "general_model_training": (
                "external_or_larger_gpu_recommended"
                if not any(gpu["vram_mb"] >= 12288 for gpu in gpus)
                else "supported"
            ),
        },
    }


def format_hardware_json(path: Path | None = None) -> str:
    return json.dumps(inspect_hardware(path), ensure_ascii=False, indent=2)
