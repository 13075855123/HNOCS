"""
OmnetEvaluator — runs OMNeT++ simulation for one GA individual.

Each call to evaluate() creates a unique temp directory, writes a task CSV,
generates a minimal INI that extends ONoCGeneral, invokes OMNeT++ via
subprocess, and parses the resulting .sca/.vec + thermal_snapshot.json.

Thread safety: UUID-based temp directories isolate result files and the
simulation working directory, including thermal_snapshot.json fallback.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from .task_graph import TaskGraph
from .csv_writer import write_static_csv
from .omnet_cost_model import OmnetScalars


def _to_win_path(p: str) -> str:
    """Convert MSYS2 /d/... paths to D:/... on Windows Python.

    Handles semicolon-separated path lists (e.g. NED paths).
    """
    import re, sys
    if sys.platform != "win32":
        return p
    parts = p.split(";")
    converted = []
    for part in parts:
        m = re.match(r"^/([a-zA-Z])/", part)
        if m:
            converted.append(f"{m.group(1).upper()}:/" + part[3:])
        else:
            converted.append(part)
    return ";".join(converted)


def _resolve(path_str: str) -> Path:
    """Resolve path with MSYS2-to-Windows conversion."""
    return Path(_to_win_path(path_str)).resolve()


class OmnetEvaluator:
    """Manages OMNeT++ execution for GA fitness evaluation."""

    def __init__(
        self,
        omnet_bin: str = "D:/HNOCS/libhnocs.exe",
        ned_paths: str = "/d/HNOCS/src;/d/HNOCS/examples/task_driven",
        work_dir: str = "/d/HNOCS/examples/task_driven",
        base_ini: str = "/d/HNOCS/examples/task_driven/omnetpp.ini",
        base_config: str = "ONoCGeneral",
        omnetpp_root: str = "/d/omnetpp/omnetpp-6.3.0",
        sim_time_limit_s: float = 0.020,
        timeout_s: float = 60.0,
        verbose: bool = False,
    ):
        self.omnet_bin = _to_win_path(omnet_bin)
        self.ned_paths = _to_win_path(ned_paths)
        self.work_dir = Path(_to_win_path(work_dir))
        self.base_ini = Path(_to_win_path(base_ini))
        self.base_config = base_config
        self.sim_time_limit_s = sim_time_limit_s
        self.timeout_s = timeout_s
        self.verbose = verbose

        # OMNeT++ installation root (for opp_scavetool and DLLs)
        self.omnetpp_root = _to_win_path(omnetpp_root)
        self._omnetpp_bin = str(Path(self.omnetpp_root) / "bin")

        if not Path(self.omnet_bin).exists():
            if self.verbose:
                print(f"  [OmnetEvaluator] WARNING: binary not found: {self.omnet_bin}")

    def evaluate(
        self,
        graph: TaskGraph,
        assignment: dict[int, int],
    ) -> OmnetScalars:
        """Run one OMNeT++ simulation and return parsed scalars.

        Returns OmnetScalars with run_ok=False on failure.
        """
        run_id = uuid.uuid4().hex[:12]
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"omnet_ga_{run_id}_"))
        result_dir = tmp_dir / "results"
        result_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Write CSV with this individual's assignment
            csv_path = tmp_dir / f"tasks_ga_{run_id}.csv"
            write_static_csv(
                graph, assignment, csv_path,
                comment=f"GA individual {run_id}",
            )

            # 2. Generate temp INI
            config_name = f"GA_{run_id}"
            ini_path = tmp_dir / f"omnetpp_ga_{run_id}.ini"
            _write_temp_ini(
                ini_path=ini_path,
                base_ini_abs=str(self.base_ini.resolve()),
                base_config=self.base_config,
                config_name=config_name,
                csv_abs=str(csv_path.resolve()),
                result_dir_abs=str(result_dir.resolve()),
                sim_time_limit_s=self.sim_time_limit_s,
            )

            # 3. Run OMNeT++
            scalars = self._run_omnet(
                ini_path=ini_path,
                config_name=config_name,
                result_dir=result_dir,
                run_cwd=tmp_dir,
            )

            return scalars

        finally:
            # Clean up temp directory
            _rmtree_safe(tmp_dir)

    # ------------------------------------------------------------------
    # Internal: run OMNeT++ subprocess
    # ------------------------------------------------------------------
    def _run_omnet(
        self,
        ini_path: Path,
        config_name: str,
        result_dir: Path,
        run_cwd: Path,
    ) -> OmnetScalars:
        cmd = [
            self.omnet_bin,
            "-u", "Cmdenv",
            "-n", self.ned_paths,
            "-c", config_name,
            str(ini_path.resolve()),
        ]

        if self.verbose:
            print(f"  [OMNeT++] {Path(self.omnet_bin).name} -c {config_name}")

        env = os.environ.copy()
        # Ensure OMNeT++ bin + tools are in PATH (clang64/usr/bin needed for DLLs)
        hnocs_bin_dir = str(Path(self.omnet_bin).parent.resolve())
        tools_dir = str(Path(self.omnetpp_root) / "tools" / "win32.x86_64")
        extra_paths = [
            hnocs_bin_dir,
            self._omnetpp_bin,
            str(Path(tools_dir) / "clang64" / "bin"),
            str(Path(tools_dir) / "usr" / "bin"),
        ]
        extra = ";".join(extra_paths)
        if "PATH" in env:
            env["PATH"] = f"{extra};{env['PATH']}"
        else:
            env["PATH"] = extra

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(run_cwd),
                env=env,
                capture_output=True,
                timeout=self.timeout_s,
                text=True,
            )
        except subprocess.TimeoutExpired:
            if self.verbose:
                print(f"  [OMNeT++] TIMEOUT after {self.timeout_s}s")
            return _invalid_scalars(f"timeout after {self.timeout_s}s")
        except FileNotFoundError:
            if self.verbose:
                print(f"  [OMNeT++] ERROR: binary not found: {self.omnet_bin}")
            return _invalid_scalars(f"binary not found: {self.omnet_bin}")

        if proc.returncode != 0:
            if self.verbose:
                tail = (proc.stderr or "(no stderr)")[-300:]
                print(f"  [OMNeT++] FAILED (rc={proc.returncode}): {tail}")
            return _invalid_scalars(f"OMNeT++ failed with rc={proc.returncode}")

        # Parse .sca output
        sca_files = sorted(result_dir.glob(f"{config_name}-*.sca"))
        if not sca_files:
            if self.verbose:
                print(f"  [OMNeT++] No .sca found in {result_dir}")
            return _invalid_scalars(f"no .sca found in {result_dir}")

        scalars = _parse_sca(sca_files[0])

        # Parse .vec for pe-die-temperature.  Some OMNeT++ 6.x builds emit
        # text version-3 .vec files, while others need opp_scavetool export.
        vec_files = sorted(result_dir.glob(f"{config_name}-*.vec"))
        if vec_files:
            _parse_vec_via_scavetool(vec_files[0], scalars, num_pes=16,
                                     omnetpp_bin=self._omnetpp_bin, env=env)

        # Parse thermal_snapshot.json (fallback if .vec unavailable/incomplete)
        if not scalars.temperature_complete:
            snapshot_path = run_cwd / "thermal_snapshot.json"
            if snapshot_path.exists():
                _parse_thermal_snapshot(snapshot_path, scalars)
                snapshot_path.unlink(missing_ok=True)

        _finalize_scalars(scalars)
        return scalars


# ==========================================================================
# Module-level helpers (used by evaluate_fitness_omnet for pickling)
# ==========================================================================

def _invalid_scalars(reason: str) -> OmnetScalars:
    scalars = OmnetScalars()
    scalars.failure_reason = reason
    return scalars


def _finalize_scalars(scalars: OmnetScalars) -> None:
    """Mark a parsed OMNeT++ result valid only if required fields are present."""
    checks = [
        (scalars.makespan_s > 0.0, "missing makespan"),
        (scalars.pe_peak_temp_K > 0.0, "missing PE temperature"),
        (scalars.temperature_complete, "incomplete PE temperature vectors"),
        (scalars.pe_optical_comm_energy_J > 0.0, "missing PE/optical energy"),
    ]
    failures = [reason for ok, reason in checks if not ok]
    if failures:
        scalars.run_ok = False
        scalars.failure_reason = "; ".join(failures)
        return

    scalars.run_ok = True
    scalars.failure_reason = ""

def _write_temp_ini(
    ini_path: Path,
    base_ini_abs: str,
    base_config: str,
    config_name: str,
    csv_abs: str,
    result_dir_abs: str,
    sim_time_limit_s: float = 0.020,
) -> None:
    """Write a minimal OMNeT++ INI that includes and extends the base config."""
    # Use forward slashes (OMNeT++ normalises on all platforms)
    csv_path_fwd = csv_abs.replace("\\", "/")
    result_dir_fwd = result_dir_abs.replace("\\", "/")
    base_ini_fwd = base_ini_abs.replace("\\", "/")

    lines = [
        f'include {base_ini_fwd}',
        '',
        f'[{config_name}]',
        f'extends = {base_config}',
        f'**.csvFile = "{csv_path_fwd}"',
        '**.pe[*].enablePowerTrace = false',
        f'result-dir = "{result_dir_fwd}"',
        f'sim-time-limit = {sim_time_limit_s}s',
    ]
    ini_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_sca(sca_path: Path) -> OmnetScalars:
    """Parse OMNeT++ .sca file into OmnetScalars.

    OMNeT++ .sca format (one line per scalar):
        scalar <module-path>  <scalar-name>  <value>

    Per-PE scalars (TaskPE[0..15]) are summed; per-PE ratios are collected
    individually for averaging (η_dvfs). Global scalars are taken as-is.
    """
    scalars = OmnetScalars()
    throttle_ratios: list[float] = []
    pe_module_re = re.compile(r"(?:^|\.)pe\[\d+\]$")

    with open(sca_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("scalar "):
                continue

            tokens = line.split()
            if len(tokens) < 4:
                continue

            module = tokens[1]
            name = tokens[-2]
            is_pe_module = bool(pe_module_re.search(module))
            try:
                value = float(tokens[-1])
            except ValueError:
                continue

            if is_pe_module and name == "totalThrottlePenalty":
                scalars.total_throttle_penalty_s += value
            elif is_pe_module and name == "totalComputeTimeNominal":
                scalars.total_compute_time_nominal_s += value
            elif is_pe_module and name == "throttlePenaltyRatio":
                throttle_ratios.append(value)
            elif is_pe_module and name == "totalEnergyJ":
                scalars.pe_total_energy_J += value
            elif is_pe_module and name == "allTrafficDrainedAt":
                scalars.makespan_s = max(scalars.makespan_s, value)
            elif is_pe_module and name == "allTasksCompletedAt":
                if scalars.makespan_s <= 0:
                    scalars.makespan_s = max(scalars.makespan_s, value)
            elif is_pe_module and name == "pe-optical-packets-sent":
                scalars.optical_packets_sent += int(value)
            elif name == "onoc-soa-total-energy-J":
                scalars.soa_energy_J = value
            elif name == "onoc-dynamic-tuning-total-energy-J":
                scalars.tuning_energy_J = value
            elif name == "onoc-laser-total-energy-J":
                scalars.laser_energy_J = value
            elif name == "onoc-optical-budget-computations":
                scalars.optical_budget_count = int(value)
            elif name == "onoc-optical-min-signal-margin-dB":
                scalars.optical_min_signal_margin_dB = value
            elif name == "onoc-optical-min-snr-dB":
                scalars.optical_min_snr_dB = value
            elif name == "onoc-optical-max-ber":
                scalars.optical_max_ber = value
            elif name == "onoc-optical-max-temp-adjusted-loss-dB":
                scalars.optical_max_temp_adjusted_loss_dB = value
            elif name == "onoc-optical-max-ring-detuning-nm":
                scalars.optical_max_ring_detuning_nm = value
            elif name == "onoc-optical-max-path-tuning-power-mW":
                scalars.optical_max_path_tuning_power_mW = value
            elif name == "onoc-optical-max-waveguide-crossing-loss-dB":
                scalars.optical_max_waveguide_crossing_loss_dB = value

    scalars.throttle_penalty_ratios = throttle_ratios
    return scalars


def _parse_vec_via_scavetool(
    vec_path: Path, scalars: OmnetScalars, num_pes: int = 16,
    omnetpp_bin: str = "", env: dict | None = None,
) -> None:
    """Parse pe-die-temperature from OMNeT++ .vec output.

    Tries direct text .vec/.vci parsing first because this project writes text
    version-3 vectors.  Falls back to opp_scavetool JSON export only for binary
    vector files.

    Extracts:
      - pe_max_temp_K: per-PE true peak temperature (over all time steps)
      - sigma_T_K:     time-averaged spatial PE temperature std. deviation
      - N_hot:          count of PEs whose peak exceeds Tthrottle (327.15 K)
    """
    Tthrottle = 327.15

    _parse_vec_text(vec_path, scalars, num_pes=num_pes, Tthrottle=Tthrottle)
    if scalars.temperature_complete:
        return

    scavetool = "opp_scavetool"
    if omnetpp_bin:
        candidate = str(Path(omnetpp_bin) / "opp_scavetool")
        if Path(candidate + ".exe").exists():
            scavetool = candidate + ".exe"
        elif Path(candidate).exists():
            scavetool = candidate

    json_path = vec_path.with_suffix(".json")
    try:
        subprocess.run(
            [scavetool, "export", str(vec_path), "-F", "JSON", "-o", str(json_path)],
            capture_output=True, timeout=60, text=True,
            env=env or os.environ,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        _parse_vec_text(vec_path, scalars, num_pes=num_pes, Tthrottle=Tthrottle)
        return

    if not json_path.exists():
        _parse_vec_text(vec_path, scalars, num_pes=num_pes, Tthrottle=Tthrottle)
        return

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        json_path.unlink(missing_ok=True)
        _parse_vec_text(vec_path, scalars, num_pes=num_pes, Tthrottle=Tthrottle)
        return

    pe_max = [0.0] * num_pes
    observed_pe = [False] * num_pes
    temps_by_time: dict[str, list[float]] = {}
    _pe_re = re.compile(r"pe\[(\d+)\]", re.IGNORECASE)

    # opp_scavetool JSON format:
    #   { "<run-name>": { "vectors": [
    #       {"module": "ONoCMesh.pe[0]", "name": "pe-die-temperature",
    #        "time": 0.0, "value": 318.15, "eventnumber": 1},
    #       ... ] } }
    if isinstance(data, dict):
        # Unwrap the run-name key
        run_keys = [k for k in data if isinstance(data[k], dict) and "vectors" in data[k]]
        if run_keys:
            vectors = data[run_keys[0]].get("vectors", [])
        else:
            vectors = data.get("vectors", [])
    elif isinstance(data, list):
        vectors = data
    else:
        vectors = []

    for entry in vectors:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "")
        if "pe-die-temperature" not in name:
            continue

        module = entry.get("module", "")
        m = _pe_re.search(module)
        if not m:
            continue
        pe = int(m.group(1))
        if pe < 0 or pe >= num_pes:
            continue

        for time_key, v in _json_time_value_pairs(entry):
            try:
                temp = float(v)
            except (ValueError, TypeError):
                continue
            if temp > pe_max[pe]:
                pe_max[pe] = temp
            observed_pe[pe] = True
            temps_by_time.setdefault(time_key, []).append(temp)

    json_path.unlink(missing_ok=True)

    if temps_by_time:
        _store_temperature_metrics(
            scalars, pe_max, temps_by_time, Tthrottle,
            num_pes=num_pes, source="vec", observed_pe=observed_pe,
        )
    else:
        _parse_vec_text(vec_path, scalars, num_pes=num_pes, Tthrottle=Tthrottle)


def _json_time_value_pairs(entry: dict) -> list[tuple[str, object]]:
    """Return (time-key, value) pairs from one scavetool JSON vector entry."""
    values = entry.get("value", [])
    times = entry.get("time", [])

    if isinstance(values, (int, float)):
        values = [values]
    if isinstance(times, (int, float, str)):
        times = [times]

    if isinstance(values, list) and isinstance(times, list):
        if len(times) == len(values):
            return [(str(t), v) for t, v in zip(times, values)]
        if len(times) == 1:
            return [(str(times[0]), v) for v in values]
        return [(str(i), v) for i, v in enumerate(values)]

    return []


def _store_temperature_metrics(
    scalars: OmnetScalars,
    pe_max: list[float],
    temps_by_time: dict[str, list[float]],
    Tthrottle: float,
    num_pes: int,
    source: str,
    observed_pe: list[bool],
) -> None:
    """Store derived PE temperature metrics on an OmnetScalars object."""
    scalars.pe_max_temp_K = pe_max
    scalars.N_hot = sum(1 for t in pe_max if t > Tthrottle)
    scalars.temperature_source = source
    scalars.parsed_pe_count = sum(1 for seen in observed_pe if seen)

    spatial_stds: list[float] = []
    for temps in temps_by_time.values():
        if len(temps) != num_pes:
            continue
        avg = sum(temps) / len(temps)
        var = sum((t - avg) ** 2 for t in temps) / len(temps)
        spatial_stds.append(math.sqrt(var))

    scalars.parsed_temp_timepoints = len(spatial_stds)
    scalars.temperature_complete = (
        scalars.parsed_pe_count == num_pes
        and scalars.parsed_temp_timepoints > 0
    )
    if spatial_stds:
        scalars.sigma_T_K = sum(spatial_stds) / len(spatial_stds)


def _parse_vec_text(
    vec_path: Path,
    scalars: OmnetScalars,
    num_pes: int = 16,
    Tthrottle: float = 327.15,
) -> None:
    """Parse text OMNeT++ .vec files using .vci vector metadata.

    Version-3 .vec files generated by this project are text files with data
    rows of: vectorId eventNumber simTime value.  The companion .vci maps
    vector ids to module/name pairs.
    """
    vector_to_pe: dict[int, int] = {}
    pe_re = re.compile(r"\bpe\[(\d+)\]\s+pe-die-temperature\b", re.IGNORECASE)

    def scan_vector_metadata(path: Path) -> None:
        if not path.exists():
            return
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.startswith("vector "):
                    continue
                tokens = line.split()
                if len(tokens) < 4:
                    continue
                m = pe_re.search(line)
                if not m:
                    continue
                try:
                    vector_id = int(tokens[1])
                    pe = int(m.group(1))
                except ValueError:
                    continue
                if 0 <= pe < num_pes:
                    vector_to_pe[vector_id] = pe

    scan_vector_metadata(vec_path.with_suffix(".vci"))
    if not vector_to_pe:
        scan_vector_metadata(vec_path)
    if not vector_to_pe:
        return

    pe_max = [0.0] * num_pes
    observed_pe = [False] * num_pes
    temps_by_time: dict[str, list[float]] = {}
    with vec_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line or not line[0].isdigit():
                continue
            tokens = line.split()
            if len(tokens) < 4:
                continue
            try:
                vector_id = int(tokens[0])
            except ValueError:
                continue
            pe = vector_to_pe.get(vector_id)
            if pe is None:
                continue
            try:
                temp = float(tokens[3])
            except ValueError:
                continue
            if temp > pe_max[pe]:
                pe_max[pe] = temp
            observed_pe[pe] = True
            temps_by_time.setdefault(tokens[2], []).append(temp)

    _store_temperature_metrics(
        scalars, pe_max, temps_by_time, Tthrottle,
        num_pes=num_pes, source="vec", observed_pe=observed_pe,
    )


def _parse_thermal_snapshot(json_path: Path, scalars: OmnetScalars) -> None:
    """Parse thermal_snapshot.json into OmnetScalars."""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        scalars.pe_temps_final_K = data.get("pe_temperatures_K", [])
        scalars.router_temps_final_K = data.get("router_temperatures_K", [])
        pe_temps = [float(t) for t in scalars.pe_temps_final_K]
        if pe_temps:
            scalars.pe_max_temp_K = pe_temps
            scalars.N_hot = sum(1 for t in pe_temps if t > 327.15)
            scalars.temperature_source = "snapshot"
            scalars.parsed_pe_count = len(pe_temps)
            scalars.parsed_temp_timepoints = 1
            scalars.temperature_complete = len(pe_temps) == 16
            if len(pe_temps) >= 2:
                avg = sum(pe_temps) / len(pe_temps)
                var = sum((t - avg) ** 2 for t in pe_temps) / len(pe_temps)
                scalars.sigma_T_K = math.sqrt(var)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass


def _rmtree_safe(path: Path) -> None:
    """Best-effort recursive deletion."""
    try:
        shutil.rmtree(str(path), ignore_errors=True)
    except Exception:
        pass
