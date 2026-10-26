"""Fixed-priority conflict resolution (comparison baseline, cf. Adamczyk and Kliks).

The higher-priority xApp's commands always pass. A command of the lower-priority xApp is rejected if it would send a
UE back to the cell from which the higher-priority xApp's last executed handover moved it, within WINDOW_S seconds;
all other commands of the lower-priority xApp pass.
"""
WINDOW_S = 3.0                # same window as X-CARE's interaction graph


class PriorityMediator:
    def __init__(self, winner):
        assert winner in ("CQM", "MLB")
        self.winner = winner
        self.loser = "MLB" if winner == "CQM" else "CQM"
        self.last_winner_move = {}       # ue -> (source cell, target cell, time) of the winner's last executed handover

    def record_executed(self, ue, source, target, t):
        """Called only for winner commands actually sent to the RAN."""
        self.last_winner_move[int(ue)] = (source, target, t)

    def filter(self, cqm_cmds, mlb_cmds, t):
        """Returns (cqm_cmds, mlb_cmds, rejected) with rejected = [(loser, ue, requested cell, winner's cell)]."""
        for ue in [u for u, v in self.last_winner_move.items() if t - v[2] > WINDOW_S]:
            del self.last_winner_move[ue]
        kept, rejected = [], []
        for ue, tgt in (mlb_cmds if self.winner == "CQM" else cqm_cmds):
            prev = self.last_winner_move.get(ue)
            if prev is not None and prev[0] is not None and tgt == prev[0]:
                rejected.append((self.loser, ue, tgt, prev[1]))
            else:
                kept.append((ue, tgt))
        if self.winner == "CQM":
            return list(cqm_cmds), kept, rejected
        return kept, list(mlb_cmds), rejected
