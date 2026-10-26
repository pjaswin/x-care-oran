"""Connection Quality Management (CQM) xApp.

Hands a UE over to a neighbouring cell that offers clearly better SINR (A3-like event with hysteresis and
time-to-trigger), with a minimum interval between handovers of a UE and a timed ban on returning a UE to the cell
it was just moved out of. An emergency path rescues UEs whose link fails.

Reaction to X-CARE: a conflict notification with score C bars the cell CQM last moved the UE to for
HOLD_MIN_S + (HOLD_MAX_S - HOLD_MIN_S) * C^2 seconds; a repeated-conflict warning raises the hysteresis towards a cell.
A restricted cell is released if it stays at least OVERRIDE_GAIN_DB better than the serving cell for OVERRIDE_TTT
cycles.
"""
import numpy as np

from state import GNB_ID, COL_UE, COL_SERVING, COL_SINR0, COL_RETX

HYSTERESIS_DB = 4.0          # SINR gain required for a normal handover
TTT_CYCLES = 3               # cycles (100 ms) the condition must hold on the same candidate
MIN_HO_INTERVAL_S = 1.5      # minimum time between two handovers of a UE
PINGPONG_PROHIBIT_S = 4.0    # a UE may not return to the cell it left within this time

SINR_FLOOR_DB = 0.0          # emergency: serving SINR below this
EMERGENCY_GAIN_DB = 4.0      # emergency target must be this much better than the serving cell
TTT_EMERGENCY = 2
# Emergency on "persistent poor cycles": counts consecutive cycles in which the value in state column COL_RETX is
# below POOR_THRESH. That column carries the MAC retransmission rate (%), so this path fires after five cycles with
# fewer than 1 % retransmissions (and a cell >= EMERGENCY_GAIN_DB better). Kept exactly as in the experiments.
POOR_THRESH = 1.0
POOR_CYCLES = 5

OVERRIDE_GAIN_DB = 10.0      # a restricted cell this much better than the serving cell ...
OVERRIDE_TTT = 4             # ... for this many consecutive cycles is released and used

HOLD_MIN_S, HOLD_MAX_S = 3.0, 6.0


class CqmXapp:
    name = "CQM"

    def __init__(self):
        self.last_ho_time = {}       # ue -> time of the last handover command
        self.last_ho_from = {}       # ue -> (source cell, time) of the last handover (timed anti-ping-pong)
        self.last_ho_to = {}         # ue -> target cell of the last handover (cell barred on a notification)
        self.pending = {}            # ue -> (candidate cell, consecutive cycles)  time-to-trigger
        self.poor_count = {}         # ue -> consecutive cycles below POOR_THRESH
        self.override_pending = {}   # ue -> (restricted best cell, consecutive cycles)
        self.cell_block = {}         # (ue, cell) -> expiry time        (X-CARE notification)
        self.soft_warn = {}          # (ue, cell) -> (expiry, extra dB)  (X-CARE repeated-conflict warning)
        self.notify_pending = {}     # ue -> score, applied at the next decision

    # ---------------------------------------------------------------- X-CARE interface
    def receive_conflict_notification(self, ue, cell, score):
        self.notify_pending[int(ue)] = float(score)

    def receive_soft_warning(self, ue, cell, until, extra_db):
        self.soft_warn[(int(ue), int(cell))] = (float(until), float(extra_db))

    # ---------------------------------------------------------------- decision
    def select_action(self, state, t):
        n = state.shape[0]
        ue_ids = state[:, COL_UE]
        serving = state[:, COL_SERVING].astype(int)
        sinr = state[:, COL_SINR0:COL_SINR0 + len(GNB_ID)]
        retx = state[:, COL_RETX]
        serving_sinr = sinr[np.arange(n), np.array([GNB_ID.index(g) for g in serving])]

        best_idx_true = np.argmax(sinr, axis=1)                 # true best cell (emergency and override)
        best_sinr_true = sinr[np.arange(n), best_idx_true]
        best_gnb_true = np.array(GNB_ID)[best_idx_true]

        for k in [k for k, v in self.cell_block.items() if v <= t]:
            del self.cell_block[k]
        for k in [k for k, v in self.soft_warn.items() if v[0] <= t]:
            del self.soft_warn[k]
        for ue, score in self.notify_pending.items():           # bar the cell CQM last moved the UE to
            tgt = self.last_ho_to.get(ue)
            if tgt is not None:
                self.cell_block[(ue, int(tgt))] = t + HOLD_MIN_S + (HOLD_MAX_S - HOLD_MIN_S) * score ** 2
        self.notify_pending.clear()

        sinr_av = sinr.copy()                                    # best cell among the cells not barred
        if self.cell_block:
            for i in range(n):
                for ci, g in enumerate(GNB_ID):
                    if (int(ue_ids[i]), g) in self.cell_block:
                        sinr_av[i, ci] = -np.inf
        best_idx = np.argmax(sinr_av, axis=1)
        best_sinr = sinr_av[np.arange(n), best_idx]
        best_gnb = np.array(GNB_ID)[best_idx]

        extra_hys = np.array([self.soft_warn.get((int(ue_ids[i]), int(best_gnb[i])), (0.0, 0.0))[1] for i in range(n)])
        active = ue_ids > 0
        cooldown_ok = np.array([t - self.last_ho_time.get(int(ue_ids[i]), -MIN_HO_INTERVAL_S) >= MIN_HO_INTERVAL_S for i in range(n)])

        def pingpong_banned(ue, cell):
            ent = self.last_ho_from.get(ue)
            return ent is not None and ent[0] == cell and (t - ent[1]) < PINGPONG_PROHIBIT_S

        for i in np.where(active)[0]:
            ue = int(ue_ids[i])
            self.poor_count[ue] = self.poor_count.get(ue, 0) + 1 if retx[i] < POOR_THRESH else 0

        emergency = (active & ((serving_sinr < SINR_FLOOR_DB)
                               | np.array([self.poor_count.get(int(ue_ids[i]), 0) >= POOR_CYCLES for i in range(n)]))
                     & (best_sinr_true > serving_sinr + EMERGENCY_GAIN_DB) & (best_gnb_true != serving) & cooldown_ok
                     & np.array([not pingpong_banned(int(ue_ids[i]), int(best_gnb_true[i])) for i in range(n)]))

        override_gain = best_sinr_true > serving_sinr + OVERRIDE_GAIN_DB
        for i in np.where(active)[0]:
            ue, bc = int(ue_ids[i]), int(best_gnb_true[i])
            restricted = (ue, bc) in self.cell_block or (ue, bc) in self.soft_warn
            if restricted and override_gain[i] and best_gnb_true[i] != serving[i]:
                prev = self.override_pending.get(ue)
                self.override_pending[ue] = (bc, prev[1] + 1 if prev and prev[0] == bc else 1)
            else:
                self.override_pending.pop(ue, None)
        override = np.array([bool(active[i]) and bool(cooldown_ok[i])
                             and self.override_pending.get(int(ue_ids[i]), (None, 0))[0] == int(best_gnb_true[i])
                             and self.override_pending.get(int(ue_ids[i]), (None, 0))[1] >= OVERRIDE_TTT for i in range(n)])

        normal = (active & (best_sinr > serving_sinr + HYSTERESIS_DB + extra_hys) & (best_gnb != serving) & cooldown_ok
                  & np.array([not pingpong_banned(int(ue_ids[i]), int(best_gnb[i])) for i in range(n)]))
        trigger = emergency | override | normal
        target = np.where(emergency | override, best_gnb_true, best_gnb)

        present = set(int(ue_ids[i]) for i in np.where(active)[0])
        for ue in set(self.last_ho_time) - present:
            for d in (self.last_ho_time, self.last_ho_from, self.pending, self.poor_count):
                d.pop(ue, None)
        for ue in set(self.override_pending) - present:
            self.override_pending.pop(ue, None)

        commands = []
        for i in np.where(active)[0]:
            ue = int(ue_ids[i])
            if trigger[i]:
                cand = int(target[i])
                prev_cand, prev_n = self.pending.get(ue, (None, 0))
                self.pending[ue] = (cand, prev_n + 1 if cand == prev_cand else 1)
            else:
                self.pending[ue] = (None, 0)
            required = 1 if override[i] else (TTT_EMERGENCY if emergency[i] else TTT_CYCLES)
            if self.pending.get(ue, (None, 0))[1] >= required:
                tgt = int(target[i])
                if override[i]:                                  # release the restriction for this cell
                    self.cell_block.pop((ue, tgt), None)
                    self.soft_warn.pop((ue, tgt), None)
                commands.append((ue, tgt))
                self.last_ho_time[ue] = t
                self.last_ho_from[ue] = (int(serving[i]), t)
                self.last_ho_to[ue] = tgt
                self.pending[ue] = (None, 0)
                self.override_pending.pop(ue, None)
                self.poor_count[ue] = 0
        return commands
