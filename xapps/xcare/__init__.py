"""X-CARE: conflict-aware notification for independently operating xApps.

    events = XCare().observe(commands, t, state, cell_prb)

commands: {"CQM": [(ue, target cell)], "MLB": [...]} issued this cycle; state / cell_prb: the KPM state of the cycle
(see state.py). Each event is a dict with
    ue, type (reversal | tie | low_confidence | insufficient_data | baseline_not_ready), notified (CQM | MLB | BOTH |
    None), severity, confidence, score, cell (UE's serving cell), assessed_cell (less favourable cell, or the
    contested cell when there is no verdict), pair (the two cells), reversed_by, warning_until (or None).
"""
import numpy as np

from state import COL_UE, COL_SERVING
from .assessment import Assessment, kpm_vector
from .detection import Detection
from .notification import Notification, WARNING_MARGIN_DB


class XCare:
    def __init__(self):
        self.detection = Detection()
        self.assessment = Assessment()
        self.notification = Notification()

    def observe(self, commands, t, state, cell_prb):
        rows = {int(r[COL_UE]): r for r in state if int(r[COL_UE]) > 0}
        serving = {u: int(r[COL_SERVING]) for u, r in rows.items()}
        vectors = {u: kpm_vector(r, cell_prb) for u, r in rows.items()}
        vectors = {u: v for u, v in vectors.items() if np.isfinite(v).all()}   # non-finite report: no measurement
        a = self.assessment
        a.update_baseline(list(vectors.values()))
        a.prune(t)
        self.notification.prune(t)
        a.record(serving, vectors, t)

        events, handled = [], set()
        for ue, mover_of_cell, reversed_by in self.detection.step(commands, serving, t):
            if ue in handled:
                continue
            culprit, alpha, _, worse, outcome, worse_state = a.attribute(ue, mover_of_cell)
            assessed = worse if worse is not None else next(iter(mover_of_cell))
            distance = a.mahalanobis(worse_state if worse_state is not None else vectors.get(ue, a.mu))
            kind, notified, sev, score, warning = self.notification.decide(t, ue, culprit, alpha, distance,
                                                                           frozenset(mover_of_cell), outcome)
            events.append(dict(ue=ue, type=kind, notified=notified, severity=round(sev, 3), confidence=round(alpha, 3),
                               score=round(score, 3), cell=serving.get(ue, assessed), assessed_cell=assessed,
                               pair=tuple(sorted(mover_of_cell)), reversed_by=reversed_by, warning_until=warning))
            handled.add(ue)
        return events
