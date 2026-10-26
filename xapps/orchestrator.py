"""Decision cycle shared by all configurations.

Every cycle both xApps decide on the same KPM state. Depending on the configuration:
    baseline       no conflict mitigation
    x-care         X-CARE observes the executed actions and notifies the xApps (no command is ever rejected)
    priority-cqm   fixed priority, CQM wins       (comparison baseline)
    priority-mlb   fixed priority, MLB wins       (comparison baseline)
Commands are then forwarded to the RAN; at most one command per UE is executed every CMD_GUARD_S seconds (ns-3
processes one handover per UE at a time), and CQM's commands are processed before MLB's within a cycle.

Logs (one line per cycle and command): xapp-cqm.log, xapp-mlb.log, xapp-decisions.log.
"""
import traceback

from state import GNB_ID, COL_UE, COL_SERVING
from cqm import CqmXapp
from mlb import MlbXapp
from priority import PriorityMediator
from xcare import XCare, WARNING_MARGIN_DB
from xcare.notification import D_CRIT

CONFIGS = ("baseline", "x-care", "priority-cqm", "priority-mlb")
CMD_GUARD_S = 0.5


class DecisionLoop:
    def __init__(self, config, log_cqm, log_mlb, log_decisions):
        assert config in CONFIGS, config
        self.config = config
        self.cqm, self.mlb = CqmXapp(), MlbXapp()
        self.xcare = XCare() if config == "x-care" else None
        self.mediator = PriorityMediator("CQM" if config == "priority-cqm" else "MLB") if config.startswith("priority") else None
        self.log_cqm, self.log_mlb, self.log_dec = log_cqm, log_mlb, log_decisions   # callables taking one line
        self.last_executed = {}      # ue -> time of the last command sent to the RAN

    def step(self, t, state, cell_prb):
        """One decision cycle. Returns the commands sent to the RAN: [(ue, target cell)]."""
        if state[:, COL_UE].sum() == 0:
            return []
        cqm_cmds = self.cqm.select_action(state, t) or []
        mlb_cmds = self.mlb.select_action(state, cell_prb, t) or []
        ts = round(t, 5)

        if self.xcare is not None:
            self._xcare_cycle(t, ts, state, cell_prb, cqm_cmds, mlb_cmds)
        elif self.mediator is not None:
            cqm_cmds, mlb_cmds, rejected = self.mediator.filter(cqm_cmds, mlb_cmds, t)
            for loser, ue, req, win in rejected:
                self.log_dec(f"At {ts}, [PRIORITY] UE_{ue}: {loser} wanted gNB_{req} but {self.mediator.winner} "
                             f"already has gNB_{win} in effect -> {loser} command REJECTED")
            if not rejected:
                self.log_dec(f"At {ts}, [PRIORITY] no conflicts this cycle (winner={self.mediator.winner})")
        else:
            self.log_dec(f"At {ts}, [CYCLE] FRAMEWORK DISABLED - baseline run (both xApps unmodified, no mitigation)")

        if not cqm_cmds:
            self.log_cqm(f"At {t}, no action.")
        if not mlb_cmds:
            self.log_mlb(f"At {t}, no action.")
        if not cqm_cmds and not mlb_cmds:
            return []

        def source(ue):
            rows = state[state[:, COL_UE] == ue]
            if len(rows) == 0:
                return None
            try:
                s = int(rows[0, COL_SERVING])
                return s if s in GNB_ID else None
            except (ValueError, TypeError):
                return None

        sent = []
        for name, cmds, log in (("CQM", cqm_cmds, self.log_cqm), ("MLB", mlb_cmds, self.log_mlb)):
            for ue, tgt in cmds:
                src = source(ue)
                log(f"At {t}, UE_{ue} {name} from gNB_{src if src is not None else '?'} to gNB_{tgt}.")
                if src is None or src == tgt:
                    continue
                if t - self.last_executed.get(ue, -1.0) >= CMD_GUARD_S:
                    sent.append((ue, tgt))
                    self.last_executed[ue] = t
                    if self.mediator is not None and self.mediator.winner == name:
                        self.mediator.record_executed(ue, src, tgt, t)
        return sent

    def _xcare_cycle(self, t, ts, state, cell_prb, cqm_cmds, mlb_cmds):
        try:
            events = self.xcare.observe({"CQM": cqm_cmds, "MLB": mlb_cmds}, t, state, cell_prb)
        except Exception:                                   # X-CARE is advisory: never stop the decision loop
            self.log_dec(f"At {ts}, [X-CARE] observe() raised, no notification this cycle:\n{traceback.format_exc()}")
            events = []
        active = {}
        for ev in events:
            try:
                ue, who = ev["ue"], ev["notified"]
                if who == "MLB":
                    self.mlb.receive_conflict_notification(ue, ev["cell"], ev["score"]); active[ue] = (who, ev["score"])
                elif who == "CQM" and ev["cell"] is not None:
                    self.cqm.receive_conflict_notification(ue, ev["cell"], ev["score"]); active[ue] = (who, ev["score"])
                elif who == "BOTH":
                    self.mlb.receive_conflict_notification(ue, ev["cell"], ev["score"])
                    if ev["cell"] is not None:
                        self.cqm.receive_conflict_notification(ue, ev["cell"], ev["score"])
                    active[ue] = (who, ev["score"])
                if ev["warning_until"] is not None and ev["pair"]:
                    for c in ev["pair"]:
                        self.cqm.receive_soft_warning(ue, int(c), ev["warning_until"], WARNING_MARGIN_DB)
                    self.mlb.receive_soft_warning(ue, ev["warning_until"], WARNING_MARGIN_DB)

                head = f"At {ts}, [X-CARE] {ev['type'].upper()} UE_{ue}: {ev['reversed_by']} sent it back to gNB_{ev['assessed_cell']}"
                if who is None:
                    self.log_dec(f"{head} | D={ev['severity']:.2f} (chi2 gate {D_CRIT:.2f}) -> harmless, no action")
                else:
                    what = {"MLB": "MLB hold UE", "BOTH": "BOTH xApps hold UE (no better cell available)",
                            "CQM": "CQM block its last target for UE"}[who]
                    rep = (f" | CHRONIC pair {tuple(ev['pair'])} -> soft bar until t={ev['warning_until']:.1f}"
                           if ev["warning_until"] is not None else "")
                    self.log_dec(f"{head} | sev={ev['severity']:.2f} share={ev['confidence']:.2f} -> notify {what} "
                                 f"(score {ev['score']:.2f}){rep}")
            except Exception:
                self.log_dec(f"At {ts}, [X-CARE] routing failed for {ev}:\n{traceback.format_exc()}")
        if active:
            self.log_dec(f"At {ts}, [CYCLE] blocklists set: " + ", ".join(f"UE_{k}:{v[1]:.2f}[->{v[0]}]" for k, v in sorted(active.items())))
        else:
            self.log_dec(f"At {ts}, [CYCLE] no blame sent this cycle")
