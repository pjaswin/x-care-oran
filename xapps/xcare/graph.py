"""Temporal interaction graph of X-CARE.

Typed nodes: xApp, entity, resource (entity, control parameter), action, KPI.
Typed edges: issues (xApp -> action), targets (action -> resource), on (resource -> entity),
             affects (resource -> KPI), precedes (consecutive actions on one resource), opposes (conflicting actions).
Only the actions of the last WINDOW_S seconds are kept.

Direct conflict: two actions of different xApps on the same resource that are incompatible. For the serving cell
(a categorical parameter) the later action returns the UE to the cell the earlier action moved it from; for other
parameters a different final value is incompatible by default (DIRECT_RULES can override this per parameter).
Indirect conflict: actions of different xApps on different parameters of the same entity whose signed effects on a
shared KPI (INTERACTION_MAP) are opposite.
"""
from collections import deque, defaultdict

WINDOW_S = 3.0

# parameter -> {KPI: sign of the KPI change when the parameter increases}. Categorical parameters have no entry.
INTERACTION_MAP = {
    "serving_cell": {},
    "tx_power": {"sinr": +1, "interference": +1},
    "ho_margin": {"sinr": -1},
    "prb_quota": {"thp": +1, "load": +1},
    "cell_on": {"availability": +1, "load": +1},
}
DIRECT_RULES = {}             # parameter -> fn(earlier action, later action) -> bool


class InteractionGraph:
    def __init__(self, window=WINDOW_S):
        self.W = window
        self.nodes = {}
        self.adj = defaultdict(lambda: defaultdict(set))       # edge type -> source -> {targets}
        self._actions = deque()
        self._latest_by_resource = {}
        self._reported = set()
        self._ctr = 0

    def _node(self, nid, ntype, **attrs):
        if nid not in self.nodes:
            self.nodes[nid] = {"type": ntype, **attrs}
        return nid

    def _drop_edge(self, etype, src, dst):
        s = self.adj[etype].get(src)
        if s is not None:
            s.discard(dst)
            if not s:
                del self.adj[etype][src]

    @staticmethod
    def _direction(n):
        v, p = n.get("value"), n.get("prev")
        try:
            if v > p:
                return 1
            if v < p:
                return -1
        except TypeError:
            pass
        return 0

    def add_action(self, xapp, entity_type, entity_id, parameter, value, prev_value, t):
        xn = self._node(("xapp", xapp), "xApp")
        en = self._node(("entity", entity_type, entity_id), "Entity")
        rn = self._node(("resource", (entity_type, entity_id), parameter), "Resource", knob=parameter, entity=en)
        aid = ("action", self._ctr); self._ctr += 1
        self._node(aid, "Action", xapp=xapp, entity=en, resource=rn, parameter=parameter, value=value, prev=prev_value, t=t)
        self.adj["ISSUES"][xn].add(aid)
        self.adj["TARGETS"][aid].add(rn)
        self.adj["ON"][rn].add(en)
        for kpi in INTERACTION_MAP.get(parameter, {}):
            kn = self._node(("kpi", (entity_type, entity_id), kpi), "KPI", metric=kpi)
            self.adj["AFFECTS"][rn].add(kn)
        prev_a = self._latest_by_resource.get(rn)
        if prev_a is not None and prev_a in self.nodes:
            self.adj["PRECEDES"][prev_a].add(aid)
        self._latest_by_resource[rn] = aid
        self._actions.append(aid)
        return aid

    def prune(self, t):
        while self._actions and t - self.nodes[self._actions[0]]["t"] > self.W:
            old = self._actions.popleft()
            n = self.nodes[old]
            self._drop_edge("ISSUES", ("xapp", n["xapp"]), old)
            self.adj["TARGETS"].pop(old, None)
            for et in ("PRECEDES", "OPPOSES", "POTENTIALLY_INTERACTS"):
                self.adj[et].pop(old, None)
                for src in list(self.adj[et]):
                    self._drop_edge(et, src, old)
            if self._latest_by_resource.get(n["resource"]) == old:
                self._latest_by_resource.pop(n["resource"], None)
            self._reported = {k for k in self._reported if old not in (k[0], k[1])}
            self.nodes.pop(old, None)

    def _interaction(self, a1, a2, r1, r2):
        """(shared KPIs, KPIs moved in opposite directions) of two actions on different resources."""
        shared_nodes = self.adj["AFFECTS"].get(r1, set()) & self.adj["AFFECTS"].get(r2, set())
        if not shared_nodes:
            return [], []
        p1, p2 = self.nodes[r1]["knob"], self.nodes[r2]["knob"]
        d1, d2 = self._direction(self.nodes[a1]), self._direction(self.nodes[a2])
        shared, opposing = [], []
        for kn in shared_nodes:
            m = self.nodes[kn]["metric"]; shared.append(m)
            if INTERACTION_MAP.get(p1, {}).get(m, 0) * d1 * INTERACTION_MAP.get(p2, {}).get(m, 0) * d2 < 0:
                opposing.append(m)
        return shared, opposing

    def detect(self, new_actions):
        out = []
        for a2 in new_actions:
            n2 = self.nodes[a2]
            for a1 in self._actions:
                if a1 == a2:
                    continue
                n1 = self.nodes[a1]
                if n1["xapp"] == n2["xapp"] or not (0 <= n2["t"] - n1["t"] <= self.W):
                    continue
                r1, r2 = n1["resource"], n2["resource"]
                conf = None
                if r1 == r2:
                    if n2["parameter"] == "serving_cell":
                        if n2["value"] == n1["prev"]:
                            conf = ("direct", "cell_return", [])
                    elif DIRECT_RULES.get(n2["parameter"], lambda x, y: x["value"] != y["value"])(n1, n2):
                        conf = ("direct", "incompatible_setting", [])
                else:
                    shared, opposing = self._interaction(a1, a2, r1, r2)
                    if shared:
                        self.adj["POTENTIALLY_INTERACTS"][a1].add(a2)
                    if opposing:
                        conf = ("indirect", "kpi_opposition", opposing)
                if conf is None:
                    continue
                key = (min(a1, a2), max(a1, a2), conf[0])
                if key in self._reported:
                    continue
                self._reported.add(key)
                self.adj["OPPOSES"][a1].add(a2)
                out.append({"ctype": conf[0], "pattern": conf[1], "actions": [a1, a2], "xapps": [n1["xapp"], n2["xapp"]],
                            "targets": [n1["entity"], n2["entity"]], "resources": [r1, r2], "shared_kpis": conf[2],
                            "values": [(n1["prev"], n1["value"]), (n2["prev"], n2["value"])]})
        return out

    def step(self, actions, t):
        """actions: list of dicts with xapp, entity_type, entity_id, parameter, value, prev_value."""
        self.prune(t)
        new = [self.add_action(a["xapp"], a["entity_type"], a["entity_id"], a["parameter"], a["value"], a["prev_value"], t)
               for a in actions]
        return self.detect(new)
