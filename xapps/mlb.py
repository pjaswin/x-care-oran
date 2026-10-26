"""Mobility Load Balancing (MLB) xApp.

When a cell's filtered PRB utilisation stays above OVERLOAD for N_TTT cycles, MLB offloads one UE from it to a
cell that is at least REL_GAP less loaded. A target may be up to MAX_SINR_SACRIFICE_DB weaker than the serving cell
(load balancing has to accept weaker cells) but must keep SINR_MIN_DB. Among the valid moves of each source cell,
MLB takes the target with the best resulting SINR and, for it, the UE whose move frees the most PRBs. MLB does not
check whether a move reverses the load imbalance.

Reaction to X-CARE: a conflict notification with score C excludes the UE from offloading for
HOLD_MIN_S + (HOLD_MAX_S - HOLD_MIN_S) * C^2 seconds (MLB offloads another UE); a repeated-conflict warning requires
the target to improve the UE's SINR by the warning margin instead of allowing a sacrifice.
"""
import numpy as np

from state import GNB_ID, COL_UE, COL_SERVING, COL_SINR0, COL_RETX

EMA_ALPHA = 0.85             # weight of the latest PRB report in the filtered cell load
OVERLOAD = 0.60              # a cell above 60 % PRB utilisation is overloaded
REL_GAP = 0.30               # a target must be at least 30 % less loaded than the source (relative)
N_TTT = 2                    # cycles (100 ms) the overload must persist
MIN_STAY_S = 1.0             # minimum time between two offloads of a UE
SINR_MIN_DB = 5.0            # SINR the UE must keep at the target
MAX_SINR_SACRIFICE_DB = 12.0 # the target may be this much weaker than the serving cell
SE_CAP = 7.4                 # spectral-efficiency ceiling (bit/s/Hz) of the PRB-cost estimate
DEMAND_FLOOR = 0.1
# The PRB-cost ranking weights each UE by state column COL_RETX, which carries the MAC retransmission rate (%);
# it only ranks valid moves. Kept exactly as in the experiments.
HOLD_MIN_S, HOLD_MAX_S = 3.0, 6.0


class MlbXapp:
    name = "MLB"

    def __init__(self):
        self.ema = np.zeros(len(GNB_ID))
        self.overload_count = np.zeros(len(GNB_ID), dtype=int)
        self.last_move = {}          # ue -> time of the last offload
        self.ue_block = {}           # ue -> expiry time               (X-CARE notification)
        self.soft_warn = {}          # ue -> (expiry, required gain dB) (X-CARE repeated-conflict warning)
        self.notify_pending = {}     # ue -> score, applied at the next decision

    # ---------------------------------------------------------------- X-CARE interface
    def receive_conflict_notification(self, ue, cell, score):
        self.notify_pending[int(ue)] = float(score)

    def receive_soft_warning(self, ue, until, extra_db):
        self.soft_warn[int(ue)] = (float(until), float(extra_db))

    # ---------------------------------------------------------------- decision
    def select_action(self, state, cell_prb, t):
        for ue in [u for u, v in self.ue_block.items() if v <= t]:
            del self.ue_block[ue]
        for ue, score in self.notify_pending.items():
            self.ue_block[ue] = t + HOLD_MIN_S + (HOLD_MAX_S - HOLD_MIN_S) * score ** 2
        self.notify_pending.clear()
        for ue in [u for u, v in self.soft_warn.items() if v[0] <= t]:
            del self.soft_warn[ue]

        ue_ids = state[:, COL_UE]
        serving = state[:, COL_SERVING].astype(int)
        sinr = state[:, COL_SINR0:COL_SINR0 + len(GNB_ID)]
        demand = state[:, COL_RETX]
        gnb = np.array(GNB_ID)

        load = np.array([cell_prb.get(g, float(self.ema[i])) for i, g in enumerate(GNB_ID)])
        self.ema[:] = (1.0 - EMA_ALPHA) * self.ema + EMA_ALPHA * load
        self.overload_count = np.where(self.ema > OVERLOAD, self.overload_count + 1, 0)

        commands = []
        for src, g_src in enumerate(GNB_ID):
            if self.overload_count[src] < N_TTT:
                continue
            not_held = np.array([int(ue_ids[i]) not in self.ue_block for i in range(len(ue_ids))])
            ues = np.where((ue_ids > 0) & (serving == g_src) & not_held)[0]
            if len(ues) == 0:
                continue
            targets = np.where((gnb != g_src) & (self.ema < self.ema[src] * (1.0 - REL_GAP)))[0]
            if len(targets) == 0:
                continue
            targets = targets[np.argsort(self.ema[targets])]

            sinr_src = sinr[ues, src]
            stay_ok = (t - np.array([self.last_move.get(int(ue_ids[i]), -MIN_STAY_S) for i in ues])) > MIN_STAY_S
            se_src = np.minimum(np.log2(1 + 10 ** (sinr_src / 10)), SE_CAP)
            margin = np.array([self.soft_warn[int(ue_ids[i])][1] if int(ue_ids[i]) in self.soft_warn else 0.0 for i in ues])
            required = np.where(margin > 0.0, margin, -MAX_SINR_SACRIFICE_DB)

            best = None                                          # (resulting target SINR, target cell, ue)
            for tgt in targets:
                sinr_tgt = sinr[ues, tgt]
                valid = (sinr_tgt >= SINR_MIN_DB) & stay_ok & (sinr_tgt >= sinr_src + required)
                se_tgt = np.minimum(np.log2(1 + 10 ** (sinr_tgt / 10)), SE_CAP)
                freed = np.maximum(demand[ues], DEMAND_FLOOR) * (1 / se_src - 1 / se_tgt)
                if not valid.any():
                    continue
                k = int(np.argmax(np.where(valid, freed, -np.inf)))
                if best is None or float(sinr_tgt[k]) > best[0]:
                    best = (float(sinr_tgt[k]), int(gnb[tgt]), int(ue_ids[ues[k]]))
            if best is not None:
                _, g_tgt, ue = best
                commands.append((ue, g_tgt))
                self.last_move[ue] = t
                self.overload_count[src] = max(0, N_TTT - 2)
        return commands
