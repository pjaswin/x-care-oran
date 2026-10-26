"""Conflict Notification of X-CARE.

severity      s = min(1, max(0, (D_M - D_crit) / (D_ref - D_crit))), D_M the Mahalanobis distance of the less
                  favourable state, D_crit = sqrt(chi2_{4,0.95}), D_ref = 3 D_crit
confidence    alpha from the assessment (normalised score difference); an individual notification needs
                  alpha >= ALPHA_MIN, a joint one does not
escalation    e = 1 + GAMMA * max(0, n - 1), n = attributed conflicts of the UE within ESCALATION_WINDOW_S
score         C = min(1, max(C_MIN, s * e) * alpha)
repeated-conflict warning: when the same UE and pair of cells are involved in at least REPEAT_MIN conflicts within
REPEAT_WINDOW_S (detections closer than REPEAT_DEDUP_S count once), the notification is accompanied by a warning to
both xApps, valid for WARNING_S, that raises their decision margins by WARNING_MARGIN_DB.
"""
import math
from collections import deque

D_CRIT = math.sqrt(9.49)
D_REF = 3.0 * D_CRIT
ALPHA_MIN = 0.30
C_MIN = 0.30
GAMMA = 0.25
ESCALATION_WINDOW_S = 4.0
REPEAT_MIN = 2
REPEAT_DEDUP_S = 5.0
REPEAT_WINDOW_S = 200.0
WARNING_S = 90.0
WARNING_MARGIN_DB = 4.0       # CQM: extra hysteresis; MLB: required SINR gain


class Notification:
    def __init__(self):
        self.attributed = {}       # ue -> deque[time] of attributed conflicts (escalation)
        self.pair_hist = {}        # (ue, frozenset{cell, cell}) -> deque[time] (repeated conflicts)

    def prune(self, t):
        for ue in list(self.attributed):
            dq = self.attributed[ue]
            while dq and t - dq[0] > ESCALATION_WINDOW_S:
                dq.popleft()
            if not dq:
                del self.attributed[ue]
        for key in list(self.pair_hist):
            dq = self.pair_hist[key]
            while dq and t - dq[0] > REPEAT_WINDOW_S:
                dq.popleft()
            if not dq:
                del self.pair_hist[key]

    def decide(self, t, ue, culprit, alpha, distance, pair, outcome):
        """Returns (event type, notified xApp or None, severity, score, repeat-warning expiry or None)."""
        sev = 0.0 if distance is None else max(0.0, min(1.0, (distance - D_CRIT) / (D_REF - D_CRIT)))
        dq = self.pair_hist.setdefault((ue, pair), deque())
        if not dq or t - dq[-1] > REPEAT_DEDUP_S:
            dq.append(t)
        if culprit is None or (culprit != "BOTH" and alpha < ALPHA_MIN):
            return (outcome if culprit is None else "low_confidence"), None, sev, 0.0, None
        self.attributed.setdefault(ue, deque()).append(t)
        e = 1.0 + GAMMA * max(0, len(self.attributed[ue]) - 1)
        score = min(1.0, max(C_MIN, sev * e) * alpha)
        warning = round(t + WARNING_S, 3) if len(dq) >= REPEAT_MIN else None
        return "reversal", culprit, sev, score, warning
