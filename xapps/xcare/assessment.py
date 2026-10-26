"""Conflict Assessment of X-CARE.

KPM vector of a UE: [-serving SINR, PDCP latency, MAC retransmission rate, serving-cell PRB utilisation], oriented so
that higher is worse. A network-wide baseline (mean, covariance) is learned from WARMUP_SAMPLES vectors and then
updated with an exponentially weighted moving average; vectors beyond the chi-square gate are excluded from the
mean and enter the covariance with bounded (winsorised) influence.

For a conflict over two cells, the state of the UE on each cell is the mean of its clean reports while the
corresponding action was in effect (the first TRANSIENT_SKIP reports after the change are skipped); the two stays
must be consecutive and have enough reports. Each state is scored with the signed degradation score b(x)
(covariance-weighted projection on the degradation direction d, one baseline standard deviation per KPM, which
has unit variance under the baseline). The xApp whose cell has the higher score is the likely culprit; a score
difference below BADNESS_TIE is a tie, and a tie on two degraded cells (better score above BADNESS_JOINT) is
attributed to both xApps.
"""
import math
from collections import deque
import numpy as np

from state import GNB_ID, COL_UE, COL_SERVING, COL_SINR0, COL_RETX, COL_LATENCY

K = 4
ORIENT = np.array([1.0, 1.0, 1.0, 1.0])
EWMA_ALPHA = 0.02
WARMUP_SAMPLES = 200
RIDGE = 1e-3                  # diagonal regularisation of the covariance
CHI2_CRIT = 9.49              # 95th percentile of chi-square with 4 degrees of freedom

TRANSIENT_SKIP = 2            # reports skipped after a cell change (0.2 s)
STATE_WINDOW = 10             # a stay's state is the mean of its last <= 10 clean reports
MIN_BEFORE, MIN_DURING = 3, 2 # clean reports needed before and during the contested action
ADJACENT_GAP_S = 0.35         # the two stays must be consecutive
STATE_MEM_S = 5.0             # reports kept per UE

BADNESS_TIE = 0.44            # score difference below which the two cells are equivalent
BADNESS_REF = 3.27            # score difference that gives full attribution confidence
BADNESS_JOINT = 1.0           # both cells degraded: joint attribution


def kpm_vector(row, cell_prb):
    serving = int(row[COL_SERVING])
    sinr = float(row[COL_SINR0 + sorted(GNB_ID).index(serving)]) if serving in GNB_ID else 0.0
    return np.array([-(sinr or 0.0), float(row[COL_LATENCY]), float(row[COL_RETX]), float(cell_prb.get(serving, 0.0))], dtype=float)


class Assessment:
    def __init__(self):
        self.mu = np.zeros(K); self.Sigma = np.eye(K); self.Sinv = np.eye(K)
        self.warmup = []; self.warmed = False
        self.hist = {}             # ue -> deque[(time, cell, kpm vector or None, reports since the cell change)]

    # ---------------------------------------------------------------- baseline
    def update_baseline(self, vectors):
        if not self.warmed:
            self.warmup.extend(vectors)
            if len(self.warmup) >= WARMUP_SAMPLES:
                M = np.asarray(self.warmup, float)
                self.mu = M.mean(axis=0); self.Sigma = np.cov(M, rowvar=False) + RIDGE * np.eye(K)
                self.Sinv = np.linalg.pinv(self.Sigma); self.warmed = True; self.warmup.clear()
            return
        for x in vectors:
            d = x - self.mu
            d2 = float(d @ self.Sinv @ d)
            if d2 < CHI2_CRIT:
                self.mu = self.mu + EWMA_ALPHA * d
            dd = d * math.sqrt(CHI2_CRIT / d2) if d2 > CHI2_CRIT else d
            self.Sigma = (1.0 - EWMA_ALPHA) * self.Sigma + EWMA_ALPHA * np.outer(dd, dd)
        self.Sinv = np.linalg.pinv(self.Sigma + RIDGE * np.eye(K))

    def mahalanobis(self, x):
        if not self.warmed:
            return None
        d = x - self.mu
        return math.sqrt(max(float(d @ self.Sinv @ d), 0.0))

    def badness(self, x):
        """Signed degradation score b(x) = (x - mu)^T S^-1 d / sqrt(d^T S^-1 d)."""
        if not self.warmed:
            return None
        dvec = ORIENT * np.sqrt(np.maximum(np.diag(self.Sigma), 1e-12))
        den = math.sqrt(max(float(dvec @ self.Sinv @ dvec), 1e-9))
        return float((x - self.mu) @ self.Sinv @ dvec) / den

    # ---------------------------------------------------------------- per-UE history
    def prune(self, t):
        for ue in list(self.hist):
            h = self.hist[ue]
            while h and t - h[0][0] > STATE_MEM_S:
                h.popleft()
            if not h:
                del self.hist[ue]

    def record(self, serving, vectors, t):
        for ue, cell in serving.items():
            h = self.hist.setdefault(ue, deque())
            k = h[-1][3] + 1 if h and h[-1][1] == cell else 0
            h.append((t, cell, vectors.get(ue), k))

    def stay_state(self, ue, cell):
        """(first time, last time, mean vector, n) of the UE's most recent stay on `cell` with clean reports."""
        h = self.hist.get(ue)
        if not h:
            return None
        i = len(h) - 1
        while i >= 0:
            if h[i][1] != cell:
                i -= 1; continue
            j = i
            while j > 0 and h[j - 1][1] == cell:
                j -= 1
            clean = [h[q][2] for q in range(j, i + 1) if h[q][3] >= TRANSIENT_SKIP and h[q][2] is not None]
            if clean:
                clean = clean[-STATE_WINDOW:]
                return h[j][0], h[i][0], np.mean(clean, axis=0), len(clean)
            i = j - 1
        return None

    # ---------------------------------------------------------------- attribution
    def attribute(self, ue, mover_of_cell):
        """mover_of_cell = {cell: xapp}. Returns (culprit or 'BOTH' or None, confidence, score of the worse cell,
        worse cell, outcome, state of the worse cell). outcome: attributed | both_bad | tie | insufficient_data |
        baseline_not_ready."""
        if not self.warmed:
            return None, 0.0, None, None, "baseline_not_ready", None
        cells = list(mover_of_cell)
        st = {c: self.stay_state(ue, c) for c in cells}
        if len(cells) != 2 or any(v is None for v in st.values()):
            return None, 0.0, None, None, "insufficient_data", None
        c_dur = max(cells, key=lambda c: st[c][1])               # the stay that ended last is the contested one
        c_bef = min(cells, key=lambda c: st[c][1])
        gap_t = st[c_dur][0] - st[c_bef][1]
        if (c_dur == c_bef or st[c_dur][3] < MIN_DURING or st[c_bef][3] < MIN_BEFORE
                or gap_t <= 0.0 or gap_t > ADJACENT_GAP_S):
            return None, 0.0, None, None, "insufficient_data", None
        bad = {c: self.badness(st[c][2]) for c in cells}
        cw = max(cells, key=lambda c: bad[c])
        cb = min(cells, key=lambda c: bad[c])
        gap = bad[cw] - bad[cb]
        if gap <= BADNESS_TIE:
            if bad[cb] > BADNESS_JOINT:
                return "BOTH", min(1.0, bad[cb] / BADNESS_REF), bad[cw], cw, "both_bad", st[cw][2]
            return None, 0.0, bad[cw], cw, "tie", st[cw][2]
        return mover_of_cell[cw], min(1.0, gap / BADNESS_REF), bad[cw], cw, "attributed", st[cw][2]
