"""
Event-driven Optical NoC simulator — Python replica of OMNeT++.

Mirrors: TaskPE.cc (handshake, dual queues), GlobalBuffer.cc (dispatch), LTM (wavelength).
"""

from __future__ import annotations
import heapq, math
from dataclasses import dataclass, field
from typing import Optional
from .task_graph import TaskGraph, TaskNode
from .optical_budget import (compute_optical_budget, OpticalBudgetParams,
                              mesh_hop_count, mesh_xy_path)
from .wavelength_alloc import WavelengthAllocator

# Events
class EvT: TASK = 1; FLIT = 2; CREDIT = 3; TICK = 4; OPTIC = 5

@dataclass(order=True)
class Ev:
    t: float; kind: int = field(compare=False)
    src: int = field(compare=False, default=-1); dst: int = field(compare=False, default=-1)
    pk: int = field(compare=False, default=0); m: dict = field(default_factory=dict, compare=False)

# Circuit state per destination
@dataclass
class C:
    rdy: bool = False; pend: bool = False; exp: float = 0.0
    tok: int = 0; act: int = 0; nxt: float = 0.0

# PE state
@dataclass
class PE:
    pid: int; cred: int = 8
    rq: list = field(default_factory=list); cur: Optional[TaskNode] = None
    tasks: list = field(default_factory=list); done: int = 0
    iq: list = field(default_factory=list); cq: list = field(default_factory=list)
    oq: list = field(default_factory=list); pq: dict = field(default_factory=dict)
    cs: dict = field(default_factory=dict); opt_sent: int = 0
    def c(self, d: int) -> C:
        if d not in self.cs: self.cs[d] = C()
        return self.cs[d]
    def p(self, d: int) -> list:
        if d not in self.pq: self.pq[d] = []
        return self.pq[d]

# GB state
@dataclass
class GB:
    n: int = 4; cred: list = field(default_factory=list)
    iq: list = field(default_factory=list); cq: list = field(default_factory=list)
    pd: dict = field(default_factory=dict); cs: dict = field(default_factory=dict)
    def c(self, d: int) -> C:
        if d not in self.cs: self.cs[d] = C()
        return self.cs[d]
    def p(self, d: int) -> list:
        if d not in self.pd: self.pd[d] = []
        return self.pd[d]

class NoCSimulator:
    def __init__(self, graph: TaskGraph, rows=4, cols=4, optical_p=None,
                 wl_s="lowest", en_opt=True, pend_to=2e-6, retry_dt=5e-8,
                 flit_B=16, dr=16e9, hop_lat=1e-8, opb=0.5e-9, oph=0.1e-9,
                 wl_br=256e9, init_c=8):
        self.g = graph; self.R = rows; self.C = cols; self.N = rows * cols
        self.en = en_opt; self.pto = pend_to; self.rdt = retry_dt
        self.fB = flit_B; self.dr = dr; self.hl = hop_lat
        self.opb = opb; self.oph = oph; self.wbr = wl_br; self.ic = init_c
        self.op = optical_p or OpticalBudgetParams()
        self.Ta = 318.15
        # Simple RC thermal model per PE
        self._T_pe = [self.Ta] * self.N  # current PE temperatures (K)
        self._T_last = [0.0] * self.N    # last update time
        self._Rconv = 10.0   # K/W
        self._Cpe = 1e-6     # J/K  (tau ≈ 8μs)
        self._power_idle = 0.5   # W
        self._power_comp = 2.0   # W
        self.wl = WavelengthAllocator(rows=rows, cols=cols, strategy=wl_s, budget_params=self.op)
        self.wl.node_temperatures = {i: self.Ta for i in range(self.N)}
        self.pes = {}; self.gb = None; self.eq = []
        self.t = 0.0; self.ack_ok = 0; self.ack_st = 0; self.to = 0; self.sf = 0; self.ofl = 0
        self._bid = {}; self._gb_bid = 1000

    def _s(self, t, k, s=-1, d=-1, p=0, m=None):
        heapq.heappush(self.eq, Ev(t, k, s, d, p, m or {}))

    def _hops(self, a, b): return mesh_hop_count(a, b, self.C)
    def _row(self, pid): return pid // self.C
    def _map_gb(self, node_id):
        """Map GB ID (1000+) to column-0 router for hop count calculation."""
        if node_id >= self._gb_bid:
            return (node_id - self._gb_bid) * self.C
        return node_id
    def _ed(self, s, d, b):
        sm = self._map_gb(s); dm = self._map_gb(d)
        return self._hops(sm, dm) * self.hl + (b * 8) / self.dr
    def _od(self, s, d):
        sm = self._map_gb(s); dm = self._map_gb(d)
        return self.opb + self._hops(sm, dm) * self.oph
    def _nf(self, ds): return max(2, math.ceil(ds / self.fB))

    # ═══════════════ init ═══════════════
    def init(self):
        nc = self.R; self.gb = GB(n=nc, cred=[self.ic] * nc,
                                  iq=[[] for _ in range(nc)], cq=[[] for _ in range(nc)])
        tasks = list(self.g.tasks.values())
        # Per-PE task loading
        for pid in range(self.N):
            pe = PE(pid=pid, cred=self.ic); self.pes[pid] = pe
            for raw in tasks:
                if raw.assigned_pe != pid: continue
                t = TaskNode(task_id=raw.task_id, assigned_pe=raw.assigned_pe,
                             compute_time_ns=raw.compute_time_ns,
                             output_data_size=raw.output_data_size)
                t.successors = list(raw.successors)
                t.successor_pe = dict(raw.successor_pe)
                t.predecessor_set = set(raw.predecessor_set)
                t.pending = len(t.predecessor_set)
                t.state = "READY" if t.pending == 0 else "WAITING"
                pe.tasks.append(t)
                if t.state == "READY": pe.rq.append(t)
        # GB explicit dispatch (PE=-1 with successors)
        for raw in tasks:
            if raw.assigned_pe != -1 or not raw.successors: continue
            for sid in raw.successors:
                dp = raw.successor_pe.get(sid, -1)
                if 0 <= dp < self.N:
                    ci = self._row(dp)
                    self._gb_dispatch(sid, dp, ci, raw.output_data_size)
        # Implicit: tasks with 0 predecessors not already in rq
        for raw in tasks:
            if raw.assigned_pe < 0: continue
            if len(raw.predecessor_set) != 0: continue
            pe = self.pes.get(raw.assigned_pe)
            if pe:
                already = any(t.task_id == raw.task_id for t in pe.rq)
                if not already:
                    t = pe.tasks[0] if pe.tasks else None
                    for tt in pe.tasks:
                        if tt.task_id == raw.task_id:
                            tt.state = "READY"; pe.rq.append(tt); break
        # Start ready tasks
        for pe in self.pes.values():
            if pe.rq and not pe.cur: self._next(pe)
        # Periodic tick
        self._s(2e-8, EvT.TICK)
        # Initial credits
        for pid in range(self.N):
            self._s(0, EvT.CREDIT, pid, pid, 0, {"v": 0, "f": self.ic})

    # ═══════════════ run ═══════════════
    def run(self, tmax=0.01, max_ev=800000):
        n = 0
        while self.eq and n < max_ev:
            n += 1; ev = heapq.heappop(self.eq); self.t = ev.t
            if self.t > tmax: break
            if ev.kind == EvT.TASK: self._on_done(ev)
            elif ev.kind == EvT.TICK: self._on_tick()
            elif ev.kind == EvT.FLIT: self._on_flit(ev)
            elif ev.kind == EvT.CREDIT: self._on_cred(ev)
            elif ev.kind == EvT.OPTIC: self._on_optic(ev)
            if self._all() and self._qempty(): break
        return {"t": self.t, "ack": self.ack_ok, "stale": self.ack_st,
                "to": self.to, "fail": self.sf, "ofl": self.ofl,
                "evals": self.wl._evaluations, "events": n}

    # ═══════════════ tasks ═══════════════
    def _next(self, pe: PE):
        if not pe.rq: return
        t = pe.rq.pop(0); t.state = "RUNNING"; pe.cur = t
        ct = t.compute_time_ns * 1e-9
        self._s(self.t + ct, EvT.TASK, pe.pid, pe.pid)

    def _on_done(self, ev: Ev):
        pe = self.pes[ev.src]; t = pe.cur
        if not t: return
        t.state = "DONE"; pe.done += 1; pe.cur = None
        self._send(pe, t); self._next(pe)

    def _send(self, pe: PE, t: TaskNode):
        for sid in t.successors:
            gb = (sid == -1)
            dp = (self._gb_bid + self._row(pe.pid)) if gb else t.successor_pe.get(sid, -1)
            if dp < 0 or dp == pe.pid: continue
            self._tx(pe, dp, t, sid, gb, t.output_data_size)

    def _tx(self, pe: PE, dp: int, t: TaskNode, sid: int, gb: bool, ds: int):
        """Send data from PE to dp (PE or GB). Optical handshake for PE→PE, electrical for GB."""
        if not self.en:
            self._elec_send(pe, dp, ds, t.task_id, sid, pe.pid); return
        # For GB: use optical bypass too (matching OMNeT++)
        use_opt = True
        cs = pe.c(dp)
        # Timeout check
        if cs.pend and self.t >= cs.exp:
            self.to += 1
            if cs.tok: self.wl.release(cs.tok)
            cs.pend = False; cs.tok = 0; cs.nxt = self.t
        # Initiate handshake
        if not cs.rdy and not cs.pend and self.t >= cs.nxt:
            ok, tok, sp, wls = self.wl.allocate(pe.pid, self._map_gb(dp))
            if ok:
                for fi in range(2):
                    pe.cq.append({"d": dp, "pk": tok, "fi": fi, "nf": 2,
                                  "tp": "SREQ" if fi == 1 else "SREQ_S",
                                  "s": pe.pid, "sz": self.fB, "gb": int(gb)})
                cs.pend = True; cs.exp = self.t + self.pto; cs.tok = tok
                cs.nxt = self.t + self.rdt
                self._bid[tok] = compute_optical_budget(pe.pid, dp, wls,
                              self.wl.node_temperatures, self.op, self.C, self.R)
            else: self.sf += 1; cs.nxt = self.t + self.rdt
        # Data to pending
        pe.p(dp).append({"tid": t.task_id, "sid": sid, "ds": ds, "prod": pe.pid})
        if cs.rdy: self._flush(pe, dp)
        self._drain(pe)

    def _elec_send(self, pe: PE, dp: int, ds: int, tid: int, sid: int, prod: int):
        """Electrical data send (GB-bound or non-optical)."""
        nf = self._nf(ds)
        for fi in range(nf):
            pe.iq.append({"d": dp, "pk": tid, "fi": fi, "nf": nf, "sz": self.fB,
                          "tp": "DATA", "tid": sid if sid != -1 else tid, "prod": prod})
        self._drain(pe)

    # ═══════════════ queues ═══════════════
    def _drain(self, pe: PE):
        self._dcq(pe)
        while pe.iq and pe.cred > 0:
            d = pe.iq.pop(0); pe.cred -= 1
            self._s(self.t + self._ed(pe.pid, d["d"], d["sz"]),
                    EvT.FLIT, pe.pid, d["d"], d["pk"], d)
        if pe.oq: self._send_opt()

    def _dcq(self, pe: PE):
        while pe.cq and pe.cred > 0:
            d = pe.cq.pop(0); pe.cred -= 1
            self._s(self.t + self._ed(pe.pid, d["d"], d["sz"]),
                    EvT.FLIT, pe.pid, d["d"], d["pk"], d)

    def _flush(self, pe: PE, dp: int):
        if dp not in pe.pq or not pe.pq[dp]: return
        cs = pe.c(dp)
        if not cs.rdy: return
        for pl in pe.pq[dp]:
            nf = self._nf(pl["ds"])
            for fi in range(nf):
                pe.oq.append({"d": dp, "s": pe.pid, "fi": fi, "nf": nf, "pl": pl, "sz": self.fB})
        pe.pq[dp].clear()
        self._send_opt()

    def _send_opt(self):
        for pid, pe in self.pes.items():
            if not pe.oq: continue
            f = pe.oq.pop(0); d = f["d"]; cs = pe.c(d)
            if not cs.rdy: pe.oq.insert(0, f); return
            self._s(self.t + self._od(pe.pid, d), EvT.OPTIC, pe.pid, d, f.get("pk", 0), f)
            pe.opt_sent += 1; self.ofl += 1
            if f["fi"] == f["nf"] - 1:
                if cs.act: self.wl.release(cs.act)
                cs.rdy = False; cs.act = 0
            return

    # ═══════════════ event handlers ═══════════════
    def _on_flit(self, ev: Ev):
        d = ev.m; tp = d.get("tp", ""); dst = ev.dst
        # DATA flit → resolve dependency at destination PE (END flit only)
        if tp == "DATA" and d.get("fi", 0) == d.get("nf", 1) - 1:
            pe = self.pes.get(dst) if 0 <= dst < self.N else None
            if pe and d.get("tid", -1) >= 0:
                self._activate(pe, d["tid"])
            self._s(self.t, EvT.CREDIT, ev.src, ev.dst, 0, {"v": 0, "f": 1})
            return
        # SETUP_REQ END → destination sends ACK
        if tp == "SREQ":
            self._do_ack(ev)
            self._s(self.t, EvT.CREDIT, ev.src, ev.dst, 0, {"v": 0, "f": 1})
            return
        # SETUP_ACK → source processes
        if "SACK" in tp:
            src = d.get("s", -1); pk = d.get("pk", 0)
            # ACK at PE
            pe = self.pes.get(dst) if 0 <= dst < self.N else None
            if pe:
                cs = pe.c(src)
                if cs.pend and cs.tok > 0 and pk == cs.tok:
                    self.ack_ok += 1; cs.rdy = True; cs.pend = False; cs.act = pk
                    self._flush(pe, src)
                else: self.ack_st += 1
            # ACK at GB
            elif self.gb and dst >= self._gb_bid:
                gcs = self.gb.c(src)
                if gcs.pend and gcs.tok > 0 and pk == gcs.tok:
                    self.ack_ok += 1; gcs.rdy = True; gcs.pend = False; gcs.act = pk
                    # Deliver GB→PE pending data via optical to PE
                    if src in self.gb.pd:
                        for pl in self.gb.pd[src]:
                            self._s(self.t + self._od(self._gb_bid, src),
                                    EvT.OPTIC, self._gb_bid, src, 0, pl)
                        self.gb.pd[src].clear()
                else: self.ack_st += 1
            self._s(self.t, EvT.CREDIT, ev.src, ev.dst, 0, {"v": 0, "f": 1})
            return
        # Default: credit
        self._s(self.t, EvT.CREDIT, ev.src, ev.dst, 0, {"v": 0, "f": 1})

    def _do_ack(self, ev: Ev):
        """Destination received SETUP_REQ → send SETUP_ACK back."""
        d = ev.m; src = d.get("s", -1); dst = ev.dst; pk = d.get("pk", 0)
        ack_type = "SACK"
        if 0 <= dst < self.N:
            pe = self.pes.get(dst)
            if pe:
                for fi in range(2):
                    pe.cq.append({"d": src, "pk": pk, "fi": fi, "nf": 2,
                                  "tp": ack_type if fi else "SACK_S",
                                  "s": pe.pid, "sz": self.fB, "gb": 0})
                self._dcq(pe)
        elif dst >= self._gb_bid and self.gb:
            ci = (dst - self._gb_bid)
            # print(f'  GB DO_ACK: src={src} pk={pk} ci={ci}')
            for fi in range(2):
                self.gb.cq[ci].append({"d": src, "pk": pk, "fi": fi, "nf": 2,
                                       "tp": ack_type if fi else "SACK_S",
                                       "s": dst, "sz": self.fB, "gb": 1})
            self._gb_drain()

    def _on_optic(self, ev: Ev):
        """Optical data arrived at destination (PE or GB). Activate only on END flit."""
        pl = ev.m; dst = ev.dst
        if 0 <= dst < self.N:
            pe = self.pes.get(dst)
            if pe and pl and pl.get("fi", 0) == pl.get("nf", 1) - 1:  # END flit only
                inner = pl.get("pl", pl)
                target = inner.get("sid", inner.get("tid", -1))
                if target >= 0: self._activate(pe, target)
        elif dst >= self._gb_bid:
            pass  # PE→GB optical arrival

    def _on_cred(self, ev: Ev):
        src = ev.src
        if 0 <= src < self.N:
            pe = self.pes.get(src)
            if pe and ev.m: pe.cred += ev.m.get("f", 1)
            if pe: self._drain(pe)
        elif self.gb and src >= self._gb_bid:
            ci = src - self._gb_bid
            if 0 <= ci < self.R and ev.m:
                self.gb.cred[ci] += ev.m.get("f", 1)
                while self.gb.iq[ci]:
                    d = self.gb.iq[ci].pop(0); self.gb.cred[ci] -= 1
                    self._s(self.t + self._ed(src, d["d"], d["sz"]),
                            EvT.FLIT, src, d["d"], d["pk"], d)

    def _on_tick(self):
        for pe in self.pes.values():
            self._dcq(pe)
            for d, cs in pe.cs.items():
                # Timeout
                if cs.pend and self.t >= cs.exp:
                    self.to += 1
                    if cs.tok: self.wl.release(cs.tok)
                    cs.pend = False; cs.tok = 0; cs.nxt = self.t + self.rdt
                # Retry
                if d in pe.pq and pe.pq[d] and self.t >= cs.nxt:
                    if not cs.rdy and not cs.pend:
                        ok, tok, sp, wls = self.wl.allocate(pe.pid, d)
                        if ok:
                            for fi in range(2):
                                pe.cq.append({"d": d, "pk": tok, "fi": fi, "nf": 2,
                                              "tp": "SREQ" if fi else "SREQ_S",
                                              "s": pe.pid, "sz": self.fB, "gb": 0})
                            cs.pend = True; cs.exp = self.t + self.pto; cs.tok = tok
                            cs.nxt = self.t + self.rdt
            if pe.oq: self._send_opt()
        self._gb_tick()
        self._s(self.t + 2e-8, EvT.TICK)

    def _gb_tick(self):
        if not self.gb: return
        for ci in range(self.R):
            while self.gb.cq[ci]:
                d = self.gb.cq[ci].pop(0)
                self._s(self.t + self._ed(self._gb_bid + ci, d["d"], d["sz"]),
                        EvT.FLIT, self._gb_bid + ci, d["d"], d["pk"], d)
            while self.gb.iq[ci]:
                d = self.gb.iq[ci].pop(0)
                self._s(self.t + self._ed(self._gb_bid + ci, d["d"], d["sz"]),
                        EvT.FLIT, self._gb_bid + ci, d["d"], d["pk"], d)

    def _gb_drain(self):
        if self.gb:
            for ci in range(self.R):
                while self.gb.cq[ci]:
                    d = self.gb.cq[ci].pop(0)
                    self._s(self.t + self._ed(self._gb_bid + ci, d["d"], d["sz"]),
                            EvT.FLIT, self._gb_bid + ci, d["d"], d["pk"], d)
                while self.gb.iq[ci]:
                    d = self.gb.iq[ci].pop(0)
                    self._s(self.t + self._ed(self._gb_bid + ci, d["d"], d["sz"]),
                            EvT.FLIT, self._gb_bid + ci, d["d"], d["pk"], d)

    def _gb_dispatch(self, tid: int, dp: int, ci: int, ds: int):
        """GB→PE task dispatch: optical handshake + pending data."""
        if not self.en:
            nf = self._nf(ds)
            for fi in range(nf):
                self.gb.iq[ci].append({"d": dp, "pk": tid, "fi": fi, "nf": nf, "sz": self.fB,
                                       "tp": "DATA", "tid": tid})
            self._gb_drain(); return
        cs = self.gb.c(dp)
        ok, tok, sp, wls = self.wl.allocate(ci * self.C, dp)
        if ok:
            gs = self._gb_bid + ci
            for fi in range(2):
                self.gb.iq[ci].append({"d": dp, "pk": tok, "fi": fi, "nf": 2,
                                       "tp": "SREQ" if fi else "SREQ_S",
                                       "s": gs, "sz": self.fB, "gb": 1})
            cs.pend = True; cs.exp = self.t + self.pto
            cs.tok = tok; cs.nxt = self.t + self.rdt
        else: self.sf += 1; cs.nxt = self.t + self.rdt
        self.gb.p(dp).append({"ds": ds, "tid": tid, "sid": tid, "prod": -1})
        self._gb_drain()

    def _activate(self, pe: PE, tid: int):
        """Resolve dependency: decrement pending, activate task if ready."""
        for t in pe.tasks:
            if t.task_id == tid and hasattr(t, 'state') and t.state == "WAITING":
                t.pending -= 1
                if t.pending <= 0:
                    t.state = "READY"; pe.rq.append(t)
                    if not pe.cur: self._next(pe)
                return

    # ═══════════════ helpers ═══════════════
    def _all(self) -> bool:
        for pe in self.pes.values():
            for t in pe.tasks:
                if getattr(t, 'state', '') not in ("DONE", "READY"):
                    if getattr(t, 'state', '') != "DONE":
                        return False
        return True

    def _qempty(self) -> bool:
        for pe in self.pes.values():
            if pe.cur or pe.iq or pe.cq or pe.oq: return False
            for q in pe.pq.values():
                if q: return False
        if self.gb:
            for q in self.gb.iq + self.gb.cq:
                if q: return False
            for q in self.gb.pd.values():
                if q: return False
        return True
