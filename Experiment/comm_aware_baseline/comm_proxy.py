"""Communication proxy for the CommAware-Heuristic baseline.

The proxy deliberately uses only static task-graph communication information:

    raw_comm_cost + lambda_cong * max_edge_load

It must not read OMNeT++ results, thermal metrics, DVFS metrics, makespan, or
the B-2 full composite cost.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from mapping.task_graph import TaskGraph


@dataclass(frozen=True)
class CommProxyConfig:
    """Configuration for the communication-only proxy."""

    rows: int = 4
    cols: int = 4
    lambda_cong: float = 0.25

    @property
    def num_pes(self) -> int:
        return self.rows * self.cols


@dataclass(frozen=True)
class CommEdge:
    """One task communication edge."""

    src_task: int
    dst_task: int
    bytes: float


@dataclass(frozen=True)
class CommProxyScore:
    """Detailed communication proxy score."""

    raw_comm_cost: float
    max_edge_load: float
    comm_proxy: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


class CommProxy:
    """Compute communication-only costs for a task mapping."""

    def __init__(self, graph: TaskGraph, config: CommProxyConfig):
        if config.rows <= 0 or config.cols <= 0:
            raise ValueError(f"invalid mesh dimensions: rows={config.rows}, cols={config.cols}")
        if config.lambda_cong < 0:
            raise ValueError("--lambda-cong must be non-negative")
        self.graph = graph
        self.config = config
        self.edges = extract_comm_edges(graph)
        self._hops_cache: dict[tuple[int, int], int] = {}

    def pe_coord(self, pe: int) -> tuple[int, int]:
        self._validate_pe(pe)
        return divmod(pe, self.config.cols)

    def hop_distance(self, pe_a: int, pe_b: int) -> int:
        self._validate_pe(pe_a)
        self._validate_pe(pe_b)
        if pe_a == pe_b:
            return 0
        key = (pe_a, pe_b) if pe_a < pe_b else (pe_b, pe_a)
        if key not in self._hops_cache:
            r1, c1 = divmod(pe_a, self.config.cols)
            r2, c2 = divmod(pe_b, self.config.cols)
            self._hops_cache[key] = abs(r1 - r2) + abs(c1 - c2)
        return self._hops_cache[key]

    def raw_comm_cost(self, assignment: dict[int, int]) -> float:
        total = 0.0
        for edge in self.edges:
            src_pe = assignment.get(edge.src_task)
            dst_pe = assignment.get(edge.dst_task)
            if src_pe is None or dst_pe is None:
                continue
            total += edge.bytes * self.hop_distance(src_pe, dst_pe)
        return total

    def edge_loads(self, assignment: dict[int, int]) -> dict[tuple[int, int], float]:
        loads: dict[tuple[int, int], float] = {}
        for edge in self.edges:
            src_pe = assignment.get(edge.src_task)
            dst_pe = assignment.get(edge.dst_task)
            if src_pe is None or dst_pe is None:
                continue
            self._add_xy_path(loads, src_pe, dst_pe, edge.bytes)
        return loads

    def max_edge_load(self, assignment: dict[int, int]) -> float:
        return max(self.edge_loads(assignment).values(), default=0.0)

    def score(self, assignment: dict[int, int]) -> CommProxyScore:
        raw = self.raw_comm_cost(assignment)
        max_edge = self.max_edge_load(assignment)
        return CommProxyScore(
            raw_comm_cost=raw,
            max_edge_load=max_edge,
            comm_proxy=raw + self.config.lambda_cong * max_edge,
        )

    def _add_xy_path(
        self,
        loads: dict[tuple[int, int], float],
        src_pe: int,
        dst_pe: int,
        bytes_: float,
    ) -> None:
        self._validate_pe(src_pe)
        self._validate_pe(dst_pe)
        if src_pe == dst_pe:
            return
        r1, c1 = divmod(src_pe, self.config.cols)
        r2, c2 = divmod(dst_pe, self.config.cols)
        cur_r, cur_c = r1, c1

        step_c = 1 if c2 > cur_c else -1
        while cur_c != c2:
            nxt_c = cur_c + step_c
            self._add_physical_edge(loads, cur_r * self.config.cols + cur_c, cur_r * self.config.cols + nxt_c, bytes_)
            cur_c = nxt_c

        step_r = 1 if r2 > cur_r else -1
        while cur_r != r2:
            nxt_r = cur_r + step_r
            self._add_physical_edge(loads, cur_r * self.config.cols + cur_c, nxt_r * self.config.cols + cur_c, bytes_)
            cur_r = nxt_r

    @staticmethod
    def _add_physical_edge(
        loads: dict[tuple[int, int], float],
        pe_a: int,
        pe_b: int,
        bytes_: float,
    ) -> None:
        key = (pe_a, pe_b) if pe_a < pe_b else (pe_b, pe_a)
        loads[key] = loads.get(key, 0.0) + bytes_

    def _validate_pe(self, pe: int) -> None:
        if pe < 0 or pe >= self.config.num_pes:
            raise ValueError(f"invalid PE {pe}; valid range is 0..{self.config.num_pes - 1}")


def extract_comm_edges(graph: TaskGraph) -> list[CommEdge]:
    """Extract producer-weighted non-GB task communication edges."""
    mappable = set(graph.mappable_task_ids)
    edges: list[CommEdge] = []
    for src_id in graph.mappable_task_ids:
        src = graph.tasks[src_id]
        if src.is_gb_task:
            continue
        for dst_id in src.successors:
            if dst_id == -1 or dst_id not in mappable:
                continue
            dst = graph.tasks.get(dst_id)
            if dst is None or dst.is_gb_task:
                continue
            edges.append(CommEdge(
                src_task=src_id,
                dst_task=dst_id,
                bytes=float(src.output_data_size),
            ))
    return edges


def communication_degree(graph: TaskGraph, edges: list[CommEdge]) -> dict[int, float]:
    """Return sum of incoming and outgoing traffic per mappable task."""
    degree = {tid: 0.0 for tid in graph.mappable_task_ids}
    for edge in edges:
        if edge.src_task in degree:
            degree[edge.src_task] += edge.bytes
        if edge.dst_task in degree:
            degree[edge.dst_task] += edge.bytes
    return degree

