"""KPM state shared by all xApps: assembling one decision cycle from the E2 reports.

Every 100 ms each cell sends CU-CP, CU-UP and DU reports (decoded by ric_io.deserialize_map). A cycle is complete
when all NUM_UE UEs have all three. The state matrix has one row per UE:

    col 0      UE id (IMSI)
    col 1      serving cell
    col 2..4   SINR to cells 2, 3, 4 (dB)
    col 5      unused (0)
    col 6      MAC retransmission rate (%), from the DU report
    col 7      PDCP latency (ms), from the CU-UP report
"""
import numpy as np

GNB_ID = [2, 3, 4]                # mmWave cells controlled by the xApps
NUM_UE = 10                       # must equal the number of UEs in the ns-3 scenario
DL_AVAILABLE_PRBS = 139.0         # PRBs reported as available by the mmWave cells
COL_UE, COL_SERVING, COL_SINR0, COL_RETX, COL_LATENCY = 0, 1, 2, 6, 7


class KpmCollector:
    """Accumulates the decoded E2 reports; add() returns (time, state, cell_prb) when a cycle is complete."""

    def __init__(self, verbose=False):
        self.verbose = verbose
        self.ue = {}
        self.cell_prb = {g: 0.0 for g in GNB_ID}
        self.t = 0.0

    def _entry(self, imsi):
        return self.ue.setdefault(imsi, {"serving": None, "sinr": {}, "latency": 0.0, "error_rate": 0.0,
                                         "has_cucp": False, "has_cuup": False, "has_du": False})

    @staticmethod
    def _complete(u):
        return u["serving"] is not None and u["has_cucp"] and u["has_cuup"] and u["has_du"]

    def add(self, report):
        try:
            cell = int(report.get("cellId"))
        except (TypeError, ValueError):
            return None
        if cell not in GNB_ID:
            return None
        try:
            self.t = float(report.get("timestamp", self.t))
        except (TypeError, ValueError):
            pass
        ues = []
        for tok in report.get("ue_list", "").split(","):
            try:
                imsi = int(float(tok.strip()))
            except (TypeError, ValueError):
                continue
            if imsi not in ues:
                ues.append(imsi)
        if not ues:
            return None

        kind = report.get("type")
        if kind == "CuCp":                       # ue.<imsi> = servingSINR,neighCell,neighSINR,...
            for imsi in ues:
                parts = [p.strip() for p in report.get(f"ue.{imsi}", "").split(",") if p.strip()]
                if not parts:
                    continue
                try:
                    sinr = {cell: float(parts[0])}
                except ValueError:
                    continue
                for i in range(1, len(parts) - 1, 2):
                    try:
                        nc, ns = int(float(parts[i])), float(parts[i + 1])
                    except ValueError:
                        continue
                    if nc in GNB_ID:
                        sinr[nc] = ns
                u = self._entry(imsi); u["serving"] = cell; u["sinr"] = sinr; u["has_cucp"] = True
        elif kind == "CuUp":                     # ue.<imsi> = pdcpLatency
            for imsi in ues:
                try:
                    lat = float(report.get(f"ue.{imsi}", ""))
                except ValueError:
                    continue
                u = self._entry(imsi); u["latency"] = lat; u["has_cuup"] = True
        elif kind == "Du":                       # prbUsedDl; ue.<imsi> = macPduUe,macRetx
            try:
                self.cell_prb[cell] = min(max(float(report.get("prbUsedDl", 0.0)) / DL_AVAILABLE_PRBS, 0.0), 1.0)
            except (TypeError, ValueError):
                pass
            for imsi in ues:
                parts = [p.strip() for p in report.get(f"ue.{imsi}", "").split(",") if p.strip()]
                if len(parts) < 2:
                    continue
                try:
                    pdus, retx = int(float(parts[0])), int(float(parts[1]))
                except ValueError:
                    continue
                u = self._entry(imsi); u["error_rate"] = retx / max(pdus, 1) * 100.0; u["has_du"] = True
        else:
            return None
        if self.verbose:
            done = sum(self._complete(u) for u in self.ue.values())
            print(f"[KPM] {kind} cell {cell} t={self.t:.3f}: {done}/{NUM_UE} UEs complete", flush=True)

        if len(self.ue) != NUM_UE or not all(self._complete(u) for u in self.ue.values()):
            return None
        rows = [[float(imsi), float(u["serving"]), *[float(u["sinr"].get(g, 0.0)) for g in sorted(GNB_ID)], 0.0,
                 float(u["error_rate"]), float(u["latency"])] for imsi, u in sorted(self.ue.items())]
        state = np.round(np.array(rows, dtype=float), decimals=2)
        cell_prb = {g: min(max(float(self.cell_prb.get(g, 0.0)), 0.0), 1.0) for g in GNB_ID}
        self.ue.clear()
        self.cell_prb = {g: 0.0 for g in GNB_ID}
        return self.t, state, cell_prb
