"""Conflict Detection of X-CARE.

An action is formed only for an EXECUTED change: the UE's serving cell in the KPM report differs from the previous
cycle, and exactly one xApp requested that target cell within the last ATTRIB_S seconds (no match: RAN-autonomous;
two matches: both xApps agreed, not attributable). Executed actions enter the temporal interaction graph, which
returns the conflicting action pairs.
"""
from collections import deque

from .graph import InteractionGraph

ATTRIB_S = 1.6                # look-back for the command that requested an executed change


class Detection:
    def __init__(self):
        self.graph = InteractionGraph()
        self.recent_cmd = {}       # ue -> deque[(time, xapp, target cell)]
        self.prev_serving = {}     # ue -> serving cell in the previous cycle

    def _issuer(self, ue, cell, t):
        matches, latest = set(), None
        for (tc, xapp, tgt) in self.recent_cmd.get(ue, ()):
            if tgt == cell and 0.0 <= t - tc <= ATTRIB_S:
                matches.add(xapp); latest = xapp
        return latest if len(matches) == 1 else None

    def step(self, commands, serving, t):
        """commands: {xapp: [(ue, target cell)]} issued this cycle; serving: {ue: serving cell} from the KPM report.
        Returns [(ue, {cell: xapp}, reversing xapp)] for the direct serving-cell conflicts found this cycle."""
        for xapp, cmds in commands.items():
            for ue, tgt in cmds:
                self.recent_cmd.setdefault(int(ue), deque()).append((t, xapp, int(tgt)))
        for ue in list(self.recent_cmd):
            dq = self.recent_cmd[ue]
            while dq and t - dq[0][0] > ATTRIB_S:
                dq.popleft()
            if not dq:
                del self.recent_cmd[ue]

        executed = []
        for ue, cell in serving.items():
            prev = self.prev_serving.get(ue)
            if prev is not None and prev != cell:
                xapp = self._issuer(ue, cell, t)
                if xapp is not None:
                    executed.append(dict(xapp=xapp, entity_type="UE", entity_id=ue, parameter="serving_cell",
                                         value=cell, prev_value=prev))
        for ue, cell in serving.items():
            self.prev_serving[ue] = cell

        conflicts = []
        for c in self.graph.step(executed, t):
            if c["pattern"] != "cell_return":
                continue
            (_, v1), (_, v2) = c["values"]
            conflicts.append((c["targets"][0][2], {v1: c["xapps"][0], v2: c["xapps"][1]}, c["xapps"][1]))
        return conflicts
