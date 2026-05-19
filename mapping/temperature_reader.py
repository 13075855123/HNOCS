"""
Temperature reader — load PE temperature data for the cost model.

Sources (tried in order):
1. JSON snapshot file from ThermalModel::writeThermalSnapshot()
2. OMNeT++ .sca file (parse "pe-die-temperature" scalars)
3. Fallback: all PEs at Tambient (318.15 K)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


def read_temperatures(
    filepath: Optional[str | Path] = None,
    num_pes: int = 16,
    Tambient: float = 318.15,
) -> list[float]:
    """Read PE temperatures from a file, or return uniform Tambient.

    Parameters
    ----------
    filepath : Path or None
        Path to thermal_snapshot.json or .sca file.
    num_pes : int
        Number of PEs in the mesh.
    Tambient : float
        Fallback temperature in Kelvin.

    Returns
    -------
    list[float]
        PE temperatures in Kelvin, index = PE id.
    """
    default = [Tambient] * num_pes

    if filepath is None:
        return default

    filepath = Path(filepath)
    if not filepath.exists():
        print(f"[temperature_reader] {filepath} not found, using Tambient={Tambient:.2f} K")
        return default

    suffix = filepath.suffix.lower()

    if suffix == ".json":
        return _read_json(filepath, num_pes, Tambient)
    elif suffix in (".sca", ".txt"):
        return _read_sca(filepath, num_pes, Tambient)
    else:
        # Try JSON first, then SCA
        temps = _read_json(filepath, num_pes, Tambient)
        if temps != default:
            return temps
        return _read_sca(filepath, num_pes, Tambient)


def _read_json(
    filepath: Path, num_pes: int, Tambient: float
) -> list[float]:
    """Parse JSON thermal snapshot.

    Expected format:
    {
        "pe_temperatures_K": [318.15, 320.3, ...],
        "Tambient_K": 318.15
    }
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[temperature_reader] JSON parse error: {e}, using Tambient")
        return [Tambient] * num_pes

    pe_temps = data.get("pe_temperatures_K")
    if pe_temps and isinstance(pe_temps, list) and len(pe_temps) >= num_pes:
        temps = [float(t) for t in pe_temps[:num_pes]]
        return temps

    print("[temperature_reader] JSON missing pe_temperatures_K, using Tambient")
    return [Tambient] * num_pes


def _read_sca(
    filepath: Path, num_pes: int, Tambient: float
) -> list[float]:
    """Parse OMNeT++ .sca file for pe-die-temperature scalar values.

    Scalar format:
        scalar "hnocs.topologies.TaskMesh.pe[0]" "pe-die-temperature"  318.15
    """
    pattern = re.compile(
        r'scalar\s+"[^"]*pe\[(\d+)\]"\s+"pe-die-temperature"\s+([\d.e+\-]+)'
    )
    temps: dict[int, float] = {}
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    pe_id = int(m.group(1))
                    temp_k = float(m.group(2))
                    temps[pe_id] = temp_k
    except OSError as e:
        print(f"[temperature_reader] Cannot read {filepath}: {e}")

    if not temps:
        print("[temperature_reader] No pe-die-temperature scalars found, using Tambient")
        return [Tambient] * num_pes

    return [temps.get(i, Tambient) for i in range(num_pes)]
