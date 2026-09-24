"""Stage decisions: what became of each record at each screening stage, and why (SW9, SW11).

A decision is added, never edited. A new decision for the same record and stage closes the one before it with
`superseded_at`, so the whole history of a record stays readable and a report can say who decided what and under which
protocol. The user's decision is a row like any other with `decided_by = 'human'`; code and models never overwrite it.

The stage, outcome, decider and next step of a decision come from its reason code (`domain/reason_codes.py`), not from
the caller, so a decision cannot mean one thing in one call site and another in the next. `derive_selection` is the one
place these decisions reach `selections`, and only for a research on the `sw` workflow.
"""

from __future__ import annotations

from typing import Any

from deixis.domain.canonical import sha256_hex
from deixis.domain.reason_codes import reason
from deixis.storage.db import new_id, now, transaction
from deixis.workflow.store import Store

CRITERION_FIELDS = ("inclusion_criterion", "criterion_parts", "cue_phrases")
# Which of the three selection states each stage outcome shows as. `criterion_not_met` and `out_of_scope` both read as
# `excluded` because a selection has no third state; the two stay apart in the decision row a report reads (SW11.2).
SELECTION_STATE = {"include": "included", "criterion_not_met": "excluded", "out_of_scope": "excluded",
                   "candidate": "pending", "unresolved": "pending"}
FULLTEXT_ORDER = ("include", "criterion_not_met", "unresolved")


class HumanDecisionStands(Exception):
    """Code or a model tried to decide over the user's own decision (AGENTS.md, User Authority; SW11.7)."""


class DecisionStore:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    # ---- the protocol a decision was made under ---------------------------------------
    def _protocol_hashes(self, research_id: str, scope_revision: int) -> tuple[str | None, str | None]:
        """The frozen protocol's digest and the digest of just its criterion fields, for the staleness check (SW11.10)."""
        protocol = self.store.current_protocol(research_id, scope_revision)
        if protocol is None:
            return None, None
        criterion = {field: protocol["body"].get(field) for field in CRITERION_FIELDS}
        if all(value is None for value in criterion.values()):
            return protocol["hash"], None
        return protocol["hash"], sha256_hex(criterion)

    # ---- decisions --------------------------------------------------------------------
    def record(self, research_id: str, source_version_id: str, reason_code: str, *, step_id: str | None = None,
               note: str | None = None, renew_stale: bool = False) -> dict[str, Any]:
        """Decide this record's stage under `reason_code`, closing whatever the stage said before.

        The same decision from the same step is written once, so a resumed run repeats the call without adding a row.
        With `renew_stale`, the same decision gone stale is written again under what the research asks now: a person
        who gives the same answer to a `look_again` row decides afresh (slice 16).
        """
        code = reason(reason_code)
        with transaction(self.conn):
            scope_revision = self.store.research(research_id)["current_scope_revision"]
            protocol_hash, criterion_hash = self._protocol_hashes(research_id, scope_revision)
            current = self.current(research_id, source_version_id, code.stage)
            if current is not None:
                if (current["reason_code"] == reason_code and current["protocol_hash"] == protocol_hash
                        and current["step_id"] == step_id and not (renew_stale and self.is_stale(current))):
                    return current
                if current["decided_by"] == "human" and code.decided_by != "human":
                    raise HumanDecisionStands(f"{source_version_id}: the user decided this record's {code.stage} stage")
            return self._insert(research_id, source_version_id, code, step_id, note, scope_revision,
                                protocol_hash, criterion_hash, closing=current)

    def _insert(self, research_id: str, source_version_id: str, code: Any, step_id: str | None, note: str | None,
                scope_revision: int, protocol_hash: str | None, criterion_hash: str | None,
                closing: dict[str, Any] | None) -> dict[str, Any]:
        """Close the current decision and add the new one; the caller holds the transaction."""
        ts, did = now(), new_id("dec")
        if closing is not None:
            self.conn.execute("UPDATE stage_decisions SET superseded_at = ? WHERE id = ?", (ts, closing["id"]))
        self.conn.execute(
            "INSERT INTO stage_decisions (id, research_id, source_version_id, stage, outcome, reason_code, decided_by,"
            " next_step, note, scope_revision, protocol_hash, criterion_hash, step_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (did, research_id, source_version_id, code.stage, code.outcome, code.code, code.decided_by, code.next_step,
             note, scope_revision, protocol_hash, criterion_hash, step_id, ts),
        )
        return dict(self.conn.execute("SELECT * FROM stage_decisions WHERE id = ?", (did,)).fetchone())

    def current(self, research_id: str, source_version_id: str, stage: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM stage_decisions WHERE research_id = ? AND source_version_id = ? AND stage = ?"
            " AND superseded_at IS NULL", (research_id, source_version_id, stage),
        ).fetchone()
        return dict(row) if row else None

    def history(self, research_id: str, source_version_id: str) -> list[dict[str, Any]]:
        """Every decision this record carried, oldest first. The clock has millisecond resolution and two decisions can
        share a timestamp, so the order they were written in (rowid) settles a tie rather than a random identifier."""
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM stage_decisions WHERE research_id = ? AND source_version_id = ? ORDER BY created_at, rowid",
            (research_id, source_version_id),
        )]

    def undo_human(self, research_id: str, source_version_id: str, stage: str) -> dict[str, Any] | None:
        """Take back the user's decision and bring the last decision before it back as a new row (SW11.7).

        Nothing is deleted: the undone decision stays in the history, closed. With no earlier non-human decision the
        stage is left undecided and `None` comes back.
        """
        with transaction(self.conn):
            current = self.current(research_id, source_version_id, stage)
            if current is None or current["decided_by"] != "human":
                return None
            previous = self.conn.execute(
                "SELECT * FROM stage_decisions WHERE research_id = ? AND source_version_id = ? AND stage = ?"
                " AND decided_by != 'human' AND superseded_at IS NOT NULL ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (research_id, source_version_id, stage),
            ).fetchone()
            if previous is None:
                self.conn.execute("UPDATE stage_decisions SET superseded_at = ? WHERE id = ?", (now(), current["id"]))
                return None
            # The restored row keeps the revision and protocol it was decided under: nobody decided again, so a
            # decision that went stale while the user's stood must still read as stale (SW11.10).
            return self._insert(research_id, source_version_id, reason(previous["reason_code"]), previous["step_id"],
                                "restored after an undone human decision", previous["scope_revision"],
                                previous["protocol_hash"], previous["criterion_hash"], closing=current)

    def human_decided_works(self, research_id: str, stage: str | None = None) -> set[str]:
        """The works a person decided, on any version still in the research, at `stage` or at any stage (SW11.7).

        Read by the stages that must not send such a work to a model again, right before they send (slice 16).
        """
        return {row[0] for row in self.conn.execute(
            "SELECT DISTINCT v.work_id FROM stage_decisions d JOIN source_versions v ON v.id = d.source_version_id"
            " JOIN corpus_memberships m ON m.research_id = d.research_id AND m.source_version_id = d.source_version_id"
            " AND m.removed_at IS NULL WHERE d.research_id = ? AND d.decided_by = 'human' AND d.superseded_at IS NULL"
            f"{' AND d.stage = ?' if stage else ''}", (research_id, stage) if stage else (research_id,))}

    def staleness_key(self, research_id: str) -> tuple[int, str | None]:
        """What a decision must have been made under to still be current: the question revision and the criterion
        digest (SW11.10). Read once by a stage that judges many decisions, rather than twice per record."""
        scope_revision = self.store.research(research_id)["current_scope_revision"]
        _, criterion_hash = self._protocol_hashes(research_id, scope_revision)
        return scope_revision, criterion_hash

    def is_stale(self, decision: dict[str, Any], key: tuple[int, str | None] | None = None) -> bool:
        """Whether the research moved on from what this decision was decided under (SW11.10). It is marked, not moved."""
        scope_revision, criterion_hash = key if key is not None else self.staleness_key(decision["research_id"])
        return decision["scope_revision"] != scope_revision or decision["criterion_hash"] != criterion_hash

    # ---- what each model run proposed --------------------------------------------------
    def add_proposal(self, research_id: str, source_version_id: str, stage: str, step_id: str, run_no: int, label: str, *,
                     criterion_part: str = "", quote: str | None = None, quote_verified: bool | None = None,
                     quote_passage_id: str | None = None, quote_page: int | None = None) -> str:
        """Store one run's proposal for one record, kept apart from the decision it feeds.

        A step that is replayed proposes the same thing again: the row already stored comes back unchanged.
        """
        with transaction(self.conn):
            existing = self.conn.execute(
                "SELECT id FROM model_proposals WHERE step_id = ? AND source_version_id = ? AND criterion_part = ?",
                (step_id, source_version_id, criterion_part),
            ).fetchone()
            if existing:
                return existing["id"]
            pid = new_id("prp")
            self.conn.execute(
                "INSERT INTO model_proposals (id, research_id, source_version_id, stage, step_id, run_no, criterion_part,"
                " label, quote, quote_verified, quote_passage_id, quote_page, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, research_id, source_version_id, stage, step_id, run_no, criterion_part, label, quote,
                 None if quote_verified is None else int(quote_verified), quote_passage_id, quote_page, now()),
            )
            return pid

    def proposals(self, research_id: str, source_version_id: str, stage: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM model_proposals WHERE research_id = ? AND source_version_id = ? AND stage = ?"
            " ORDER BY run_no, criterion_part, created_at, rowid", (research_id, source_version_id, stage),
        )]

    # ---- where each record stood in each ranking signal --------------------------------
    def save_ranks(self, ranking_step_id: str, research_id: str, rows: list[dict[str, Any]]) -> None:
        """Store one ranking step's places. A replayed step writes nothing new: what it stored the first time stands."""
        with transaction(self.conn):
            self.conn.executemany(
                "INSERT OR IGNORE INTO record_signal_ranks (ranking_step_id, research_id, source_version_id, signal,"
                " rank, available) VALUES (?, ?, ?, ?, ?, ?)",
                [(ranking_step_id, research_id, row["source_version_id"], row["signal"], float(row["rank"]),
                  int(row["available"])) for row in rows],
            )

    def ranks(self, research_id: str, source_version_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(
            "SELECT * FROM record_signal_ranks WHERE research_id = ? AND source_version_id = ?"
            " ORDER BY signal, ranking_step_id", (research_id, source_version_id),
        )]

    def ranking_order(self, ranking_step_id: str) -> list[str]:
        """The inspection order one ranking step wrote, best first."""
        return [row[0] for row in self.conn.execute(
            "SELECT source_version_id FROM record_signal_ranks WHERE ranking_step_id = ? AND signal = 'inspection'"
            " ORDER BY rank", (ranking_step_id,),
        )]

    def signal_ranks(self, ranking_step_id: str, signals: tuple[str, ...]) -> dict[str, dict[str, tuple[float, bool]]]:
        """One ranking step's stored places in these signals, as `ranking.fuse` reads them."""
        ranks: dict[str, dict[str, tuple[float, bool]]] = {}
        marks = ",".join("?" * len(signals))
        for row in self.conn.execute(
            f"SELECT source_version_id, signal, rank, available FROM record_signal_ranks WHERE ranking_step_id = ?"
            f" AND signal IN ({marks})", (ranking_step_id, *signals),
        ):
            ranks.setdefault(row["signal"], {})[row["source_version_id"]] = (row["rank"], bool(row["available"]))
        return ranks

    def latest_chain_ranking(self, research_id: str, scope_revision: int) -> list[str]:
        """The order the chained works of this question revision were last ranked in; empty when nothing was chained.

        The chain's ranking is its own step (D95), so `latest_ranking` never reads it and the keyword order stays
        what the keyword ranking wrote.
        """
        row = self.conn.execute(
            "SELECT s.id FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
            " AND r.scope_revision = ? AND s.operation_key = 'chain_ranking' AND s.kind = 'code:chain_ranking'"
            " AND s.status = 'succeeded' ORDER BY s.finished_at DESC, s.id DESC LIMIT 1",
            (research_id, scope_revision),
        ).fetchone()
        return [] if row is None else self.ranking_order(row["id"])

    def latest_ranking(self, research_id: str, scope_revision: int) -> list[str] | None:
        """The inspection order this question revision was last ranked in; `None` when it was never ranked.

        A later discovery run of the same revision opens its own ranking step and the earlier step's rows stay, so
        this is the newest one, not a merge of them (slices 10 and 15 read it).
        """
        row = self.conn.execute(
            "SELECT s.id FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
            " AND r.scope_revision = ? AND s.operation_key = 'ranking' AND s.kind = 'code:ranking'"
            " AND s.status = 'succeeded' ORDER BY s.finished_at DESC, s.id DESC LIMIT 1",
            (research_id, scope_revision),
        ).fetchone()
        return None if row is None else self.ranking_order(row["id"])

    # ---- from the decisions of a work's versions to one selection ----------------------
    def facts(self, research_id: str, work_id: str | None = None) -> dict[str, Any]:
        """Everything `work_outcome` reads, for one work or for the whole research, in three statements.

        `work_heads` walks every record of the research, so asking it once per work was 173 s of the 203 s an
        abstract stage spent on a 4,700-work research (slice 13d's profile). A caller with many works reads this
        once and hands it to every `work_outcome` call.
        """
        open_decisions: dict[str, list[dict[str, Any]]] = {}
        for row in self.conn.execute(
            "SELECT d.*, v.work_id AS in_work FROM stage_decisions d"
            " JOIN corpus_memberships m ON m.research_id = d.research_id"
            " AND m.source_version_id = d.source_version_id AND m.removed_at IS NULL"
            " JOIN source_versions v ON v.id = d.source_version_id"
            " WHERE d.research_id = ? AND d.superseded_at IS NULL"
            f"{' AND v.work_id = ?' if work_id is not None else ''} ORDER BY d.created_at, d.rowid",
            (research_id,) if work_id is None else (research_id, work_id),
        ):
            decision = dict(row)
            open_decisions.setdefault(decision.pop("in_work"), []).append(decision)
        return {"heads": self.store.work_heads(research_id), "decisions": open_decisions,
                "stale_key": self.staleness_key(research_id)}

    def work_outcome(self, research_id: str, work_id: str, facts: dict[str, Any] | None = None) -> dict[str, Any]:
        """What this research decided about the work, over every version of it still in the research (SW9.4, SW1.7).

        The full-text stage answers when any version reached it. The user's decision answers before any other; two
        versions that reached opposite full-text decisions leave the work unresolved rather than picking one. An
        abstract decision on one version never drops the work while another version is still a candidate. When several
        versions carry the winning outcome, the work's head is named, else the smallest identifier, never the one
        that happened to be decided first.
        """
        facts = self.facts(research_id, work_id) if facts is None else facts
        head = facts["heads"].get(work_id)

        def named(rows: list[dict[str, Any]]) -> dict[str, Any]:
            return min(rows, key=lambda d: (d["source_version_id"] != head, d["source_version_id"]))

        decisions = facts["decisions"].get(work_id, [])

        fulltext = [d for d in decisions if d["stage"] == "fulltext"]
        if fulltext:
            human = [d for d in fulltext if d["decided_by"] == "human"]
            if human:
                return _outcome(human[-1])  # the user's newest stands, stale or not (SW11.7)
            # A stale code decision no longer speaks for the work: the abstract outcome does (slice 12). A fresh
            # full-text decision still answers first, and two versions at opposite fresh decisions stay unresolved.
            fresh = [d for d in fulltext if not self.is_stale(d, facts["stale_key"])]
            if fresh:
                outcomes = {d["outcome"] for d in fresh}
                if {"include", "criterion_not_met"} <= outcomes:
                    including = named([d for d in fresh if d["outcome"] == "include"])
                    return {"stage": "fulltext", "outcome": "unresolved", "reason_code": "versions_disagree",
                            "decided_by": "code", "source_version_id": including["source_version_id"]}
                best = next(outcome for outcome in FULLTEXT_ORDER if outcome in outcomes)
                return _outcome(named([d for d in fresh if d["outcome"] == best]))

        abstract = [d for d in decisions if d["stage"] == "abstract"]
        if not abstract:
            return {}
        candidates = [d for d in abstract if d["outcome"] == "candidate"]
        if candidates:
            return _outcome(named(candidates))
        if all(d["outcome"] == "out_of_scope" for d in abstract):
            return _outcome(named(abstract))
        return _outcome(named([d for d in abstract if d["outcome"] == "unresolved"]))

    def derive_selection(self, research_id: str, work_id: str) -> str | None:
        """Write the work's decision onto the selection its head record carries; returns the state written.

        Only a research on the `sw` workflow derives selections, and a selection the user set is never changed
        (AGENTS.md, User Authority). Nothing is written when the state is already the derived one.
        """
        return self.derive_selections(research_id, [work_id]).get(work_id)

    def derive_selections(self, research_id: str, work_ids: list[str]) -> dict[str, str]:
        """`derive_selection` for several distinct works at once; returns the state written for each one written.

        The same rule and the same rows as one call per work, in the same order: what the research holds is read
        once instead of four statements per work, and the rows go in one transaction rather than one each. The
        whole batch carries one timestamp, which is what a single write would have given it anyway.
        """
        if not work_ids or self.store.scope(research_id)["search_workflow"] != "sw":
            return {}
        facts = self.facts(research_id, work_ids[0] if len(work_ids) == 1 else None)
        selections = {row["source_version_id"]: dict(row) for row in self.conn.execute(
            "SELECT * FROM selections WHERE research_id = ?", (research_id,))}
        written: dict[str, str] = {}
        updates: list[tuple[Any, ...]] = []
        history: list[tuple[Any, ...]] = []
        bumps = 0
        ts = now()
        for work_id in work_ids:
            head = facts["heads"].get(work_id)
            if head is None:
                continue
            outcome = self.work_outcome(research_id, work_id, facts)
            if not outcome:
                continue
            state = SELECTION_STATE[outcome["outcome"]]
            current = selections.get(head)
            if current is None or current["origin"] == "user":
                continue
            if current["state"] == state and current["origin"] == "code_rule":
                continue
            updates.append((state, ts, research_id, head))
            history.append((research_id, head, current["state"], state, outcome["reason_code"], ts))
            bumps += current["state"] != state and "included" in (current["state"], state)
            written[work_id] = state
        if not updates:
            return written
        with transaction(self.conn):
            self.conn.executemany(
                "UPDATE selections SET state = ?, origin = 'code_rule', version = version + 1, updated_at = ?"
                " WHERE research_id = ? AND source_version_id = ?", updates,
            )
            self.conn.executemany(
                "INSERT INTO selection_history (research_id, source_version_id, old_state, new_state, origin, reason,"
                " created_at) VALUES (?, ?, ?, ?, 'code_rule', ?, ?)", history,
            )
            if bumps:
                self.conn.execute("UPDATE researches SET selection_revision = selection_revision + ? WHERE id = ?",
                                  (bumps, research_id))
        return written


def _outcome(decision: dict[str, Any]) -> dict[str, Any]:
    return {key: decision[key] for key in ("stage", "outcome", "reason_code", "decided_by", "source_version_id")}
