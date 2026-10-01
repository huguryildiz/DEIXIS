"""Synchronous read models over stored decisions and publication history.

Currency checks describe recorded inputs; they do not assess scientific support.
"""

import json
from dataclasses import asdict, replace

from deixis.storage.db import transaction
from deixis.workflow.lineage import assembly, baseline, edges
from deixis.workflow.lineage.candidates import find_candidates
from deixis.workflow.lineage.mentions import PassageText
from deixis.workflow.lineage.run import (
    ROLES, build_snapshot, decision_currency, node_snapshot, scope_node_reasons,
    stale_link_reasons, text_sha256,
)
from deixis.workflow.lineage.store import LineageStore
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore


class LineageView:
    def __init__(self, store: Store):
        self.store, self.conn = store, store.conn
        self.lineage, self.tables = LineageStore(store), TableStore(store)

    def _node(self, sid, live):
        source = self.store.source(sid)
        row = live.get(sid)
        return {"source_version_id": sid, **{k: source[k] for k in ("work_id", "title", "year", "version_label")},
                "source_key": self.store.source_key(source["work_id"]), "live": row is not None,
                "position": row.work.position if row else None, "eligible": row.eligible if row else None,
                "access_level": json.loads(row.source_json)["access_level"] if row else None}

    @staticmethod
    def _pair(pair):
        return pair["from_source_version_id"], pair["to_source_version_id"]

    def _link(self, pair, nodes, edge_states, stale, heads):
        revision = self.lineage._current(pair)
        frm, to = self._pair(pair)
        state = edge_states.get((frm, to))
        evidence = []
        for item in self.lineage.evidence(revision["id"]):
            passage = self.store.passage(item["passage_id"])
            evidence.append({**{k: item[k] for k in ("passage_id", "anchor_text", "anchor_match")},
                             **{k: passage[k] for k in ("physical_page", "printed_label", "kind")}})
        return {"link_id": pair["id"], "version": pair["version"], "revision_id": revision["id"], "from": frm, "to": to,
                **{k: revision[k] for k in ("relation", "what_changed", "support_type", "author", "note", "output_status",
                                            "scope_revision", "run_id", "created_at")},
                "human_edited": revision["author"] == "human", "edge_state": state,
                "unexpected_no_citation_edge": state == "absent_in_read_list",
                "year_order_warning": nodes[to]["year"] is not None and nodes[frm]["year"] is not None
                and nodes[to]["year"] < nodes[frm]["year"],
                "not_head_ends": [end for end, sid in (("from", frm), ("to", to))
                                  if heads.get(nodes[sid]["work_id"]) != sid],
                "evidence": evidence, "stale_reasons": list(stale.get(pair["id"], (None, ()))[1])}

    def _outcomes(self, snapshot, pairs, revisions, node_snapshots):
        """Keep the last record per pair/kind; carried failures retain their time."""
        latest, last_run, chunks_by_entry = {}, {}, {}
        pair_map = {self._pair(p): p for p in pairs}

        def closed(frm, to, recorded_at):
            pair = pair_map.get((frm, to))
            if not pair:
                return False
            current = self.lineage._current(pair)
            return bool(current and current["author"] == "human") or any(
                r["kind"] == "model_propose" and r["created_at"] > recorded_at for r in revisions[pair["id"]])

        for row in self.conn.execute(
            "SELECT id FROM runs WHERE research_id = ? AND kind = 'lineage_links'"
            " AND json_extract(target_json, '$.table_id') = ? ORDER BY created_at, rowid",
            (snapshot.research_id, snapshot.table_id),
        ):
            run = self.store.run(row["id"])
            step = self.store.existing_step(run["id"], "lineage_publication")
            if not step or step["status"] != "succeeded":
                continue
            output = self.store.step_output(step["id"]) or {}
            at = step["finished_at"] or step["created_at"]
            for target in output.get("targets", []):
                last_run[target["to"]] = {"run_id": run["id"], "scope_revision": run["scope_revision"], "recorded_at": at}
            chunks = run["target"].get("chunks", [])
            for kind, field in (("failed_pair", "failed_pairs"), ("unsent_pair", "not_sent_budget"),
                                ("step_failed", "step_failed"), ("skipped", "skipped")):
                for item in output.get(field, []):
                    pair_level = kind in ("failed_pair", "unsent_pair")
                    frm = item["from"] if pair_level else None
                    key = None if pair_level else item["key"]
                    identity = (kind, frm, item["to"]) if pair_level else (kind, run["id"], key)
                    if pair_level:
                        chunk = next((c for c in chunks if c["to"] == item["to"] and frm in c["from"]), None)
                    else:
                        chunk = next((c for c in chunks if c["key"] == key), None)
                    latest[identity] = {"kind": kind, "from": frm, "to": item["to"], "key": key,
                                        "pair_fp": item.get("pair_fp", item.get("pair_fingerprint")),
                                        "reason": item.get("reason"), "run_id": run["id"],
                                        "scope_revision": run["scope_revision"], "recorded_at": at}
                    chunks_by_entry[identity] = chunk
        outcomes, affected = [], {}
        for identity, item in latest.items():
            chunk = chunks_by_entry[identity]
            planned = [(frm, chunk["to"]) for frm in chunk["from"]] if chunk else []
            related = [(item["from"], item["to"])] if item["from"] is not None else planned
            # Missing frozen chunks cannot justify dropping a recorded failure.
            if related and all(closed(frm, to, item["recorded_at"]) for frm, to in related):
                continue
            currency = self._outcome_currency(item, chunk, snapshot, node_snapshots)
            entry = item | currency
            outcomes.append(entry)
            affected[(item["kind"], item["run_id"], item["from"], item["to"], item["key"])] = {
                sid for pair in related for sid in pair} | {item["to"]}
        outcomes.sort(key=lambda o: (o["recorded_at"], o["run_id"], o["kind"], o["to"], o["from"] or "", o["key"] or ""))
        return outcomes, last_run, affected

    def _outcome_currency(self, item, chunk, snapshot, nodes):
        unknown = {"current": False if item["scope_revision"] != snapshot.scope_revision else None,
                   "stale_reasons": ["scope_changed"] if item["scope_revision"] != snapshot.scope_revision else [],
                   "unchecked": ["node_snapshots", "passages"]}
        if item["kind"] == "unsent_pair" or not chunk:
            return unknown
        step = self.store.existing_step(item["run_id"], chunk["key"])
        output = (step or {}).get("output") or {}
        sent = output.get("send_record") or (output.get("blocked_send_record") or {}).get("send_record")
        if not sent:
            return unknown
        records = sent.get("pairs", [])
        if item["from"] is not None:
            records = [r for r in records if (r["from"], r["to"], r["pair_fp"]) ==
                       (item["from"], item["to"], item["pair_fp"])]
        else:
            records = [r for r in records if r["to"] == chunk["to"] and r["from"] in chunk["from"]]
            if {r["from"] for r in records} != set(chunk["from"]):
                return unknown
        if not records:
            return unknown
        reasons = []
        for record in records:
            reasons.extend(scope_node_reasons(self.store, snapshot.table_id, item["scope_revision"],
                                             snapshot.scope_revision, record["inputs"], record["from"], record["to"], nodes))
        current = {p["id"]: p for p in self.store.passages_for(item["to"])}
        shown = {p["id"]: p for p in sent.get("passages", [])}
        mentions = {pid for r in records for pid in r["inputs"].get("mention_passage_ids", [])}
        unchecked = []
        if not shown or not mentions <= shown.keys():
            unchecked.append("passages")
        if any(pid not in current or not p.get("current") or
               text_sha256(current[pid]["text"]) != p["text_sha256"] for pid, p in shown.items()):
            reasons.append("passage_changed")
        reasons = list(dict.fromkeys(reasons))
        return {"current": False if reasons else None if unchecked else True,
                "stale_reasons": reasons, "unchecked": unchecked}

    @staticmethod
    def _detail(reason, frm=None, to=None, pair=None, revision=None, currency=None, outcome=None):
        return {"reason": reason, "from": frm, "to": to, "link_id": pair["id"] if pair else None,
                "revision_id": revision["id"] if revision else None,
                "run_id": outcome["run_id"] if outcome else revision["run_id"] if revision else None,
                "scope_revision": outcome["scope_revision"] if outcome else revision["scope_revision"] if revision else None,
                "recorded_at": outcome["recorded_at"] if outcome else revision["created_at"] if revision else None,
                **(currency or {"current": None, "stale_reasons": [], "unchecked": []})}

    def view(self, research_id: str, table_id: str) -> dict:
        with transaction(self.conn):
            table = self.tables._table(research_id, table_id)
            snapshot = build_snapshot(self.store, table_id)
            live = {r.work.source_version_id: r for r in snapshot.rows}
            node_snapshots = {sid: node_snapshot(json.loads(r.node_json)) for sid, r in live.items()}
            pairs = [dict(p) for p in self.conn.execute("SELECT * FROM lineage_links WHERE table_id = ? ORDER BY created_at, id", (table_id,))]
            revisions = {p["id"]: self.lineage.revisions(p["id"]) for p in pairs}
            currents = {p["id"]: self.lineage._current(p) for p in pairs}
            outcomes, last_run, affected = self._outcomes(snapshot, pairs, revisions, node_snapshots)
            ids = set(live) | {sid for p in pairs for sid in self._pair(p)} | set(last_run)
            ids |= {sid for group in affected.values() for sid in group}
            nodes = {sid: self._node(sid, live) for sid in sorted(ids)}
            row_order = lambda sid: assembly.node_order(nodes[sid]["year"], nodes[sid]["position"] or 0, sid)
            def pair_order(pair):
                to, frm = nodes[pair["to"]], nodes[pair["from"]]
                # Non-live rows have no position; sort that unknown position last.
                return (to["year"] is None, to["year"] or 0, to["position"] is None, to["position"] or 0,
                        frm["position"] is None, frm["position"] or 0, pair["link_id"])
            works = tuple(r.work for r in snapshot.rows)
            current_edges = edges.derive_edges(
                (edges.EdgeTo(w.source_version_id, w.work_id, w.references_read, w.referenced_ids) for w in works),
                (edges.EdgeFrom(w.source_version_id, w.work_id, w.openalex_ids) for w in works))
            edge_states = {(e.from_source_version_id, e.to_source_version_id): e.state for e in current_edges}
            stale = stale_link_reasons(self.store, table_id)
            heads = self.store.work_heads(research_id)
            development, cross, history = [], [], {"stale": [], "out_of_scope": []}
            details = {sid: [] for sid in live}

            def attach_detail(detail):
                for sid in {detail["from"], detail["to"]} & live.keys():
                    details[sid].append(detail)

            for pair in self.lineage.active_links(table_id):
                link = self._link(pair, nodes, edge_states, stale, heads)
                not_live = [end for end in ("from", "to") if link[end] not in live]
                if not_live:
                    history["out_of_scope"].append(link | {"not_live_ends": not_live})
                elif link["stale_reasons"]:
                    history["stale"].append(link)
                elif link["relation"] == "independent_parallel":
                    cross.append(link)
                else:
                    development.append(link)
                reason = "stale_only" if not_live or link["stale_reasons"] else "cross_relation_only" if link["relation"] == "independent_parallel" else None
                if reason:
                    attach_detail(self._detail(reason, link["from"], link["to"], pair, currents[pair["id"]],
                                              {"current": not bool(not_live or link["stale_reasons"]),
                                               "stale_reasons": link["stale_reasons"], "unchecked": []}))
            pure_links = [assembly.Link(l["link_id"], l["from"], l["to"], l["relation"], nodes[l["from"]]["year"],
                                        nodes[l["to"]]["year"], nodes[l["from"]]["position"], nodes[l["to"]]["position"])
                          for l in development + cross]
            order = {l.link_id: assembly.link_order(l) for l in pure_links}
            cross.sort(key=lambda l: order[l["link_id"]])
            by_id = {l["link_id"]: l for l in development}
            components = []
            for component in assembly.assemble(pure_links).components:
                value = asdict(component)
                value["links"] = [by_id[lid] for lid in component.links]
                components.append(value)
            placed = {sid for c in components for sid in c["members"]}
            pair_decisions, not_accepted = [], []
            for pair in pairs:
                frm, to = self._pair(pair)
                current, revs = currents[pair["id"]], revisions[pair["id"]]
                pair_decisions.append({"link_id": pair["id"], "from": frm, "to": to, "version": pair["version"],
                                       "current_revision_id": pair["current_revision_id"],
                                       **{k: current[k] if current else None for k in ("decision", "author", "disposition")}})
                model = [r for r in revs if r["kind"] == "model_propose"]
                negative = current if current and current["author"] == "model" and current["decision"] in ("no_relation", "insufficient_evidence") else None
                for reason, revision in ((negative["decision"] if negative else None, negative),
                                         ("rejected", model[-1] if model and model[-1]["disposition"] == "rejected" else None),
                                         ("human_removed", current if current and current["kind"] == "human_remove" else None)):
                    if revision:
                        currency = decision_currency(self.store, table_id, revision, frm, to, snapshot, node_snapshots) if revision["author"] == "model" else {"current": True, "stale_reasons": [], "unchecked": []}
                        attach_detail(self._detail(reason, frm, to, pair, revision, currency))
                rejected = [r for r in model if r["disposition"] == "rejected"]
                if rejected:
                    revision = rejected[-1]
                    not_accepted.append({"link_id": pair["id"], "from": frm, "to": to, "revision_id": revision["id"],
                                         **{k: revision[k] for k in ("rejection_code", "decision", "relation", "what_changed", "support_type", "note", "run_id", "created_at")},
                                         "superseded": any(r["created_at"] > revision["created_at"] and r["disposition"] == "accepted" for r in revs),
                                         "pair_state": {"decision": current["decision"] if current else "none", "author": current["author"] if current else None}})
            pair_map = {self._pair(p): p for p in pairs}
            for outcome in outcomes:
                reason = "not_sent_budget" if outcome["kind"] == "unsent_pair" else "step_failed" if outcome["kind"] in ("failed_pair", "step_failed") else None
                if reason:
                    pair = pair_map.get((outcome["from"], outcome["to"]))
                    detail = self._detail(reason, outcome["from"], outcome["to"], pair,
                                          currents[pair["id"]] if pair else None,
                                          {k: outcome[k] for k in ("current", "stale_reasons", "unchecked")}, outcome)
                    for sid in affected[(outcome["kind"], outcome["run_id"], outcome["from"], outcome["to"], outcome["key"])] & live.keys():
                        details[sid].append(detail)
            # A recorded target is historical; its current mention scan uses today's text.
            scanned = frozenset(sid for sid in last_run if sid in live and live[sid].eligible)
            scan_works = tuple(replace(w, passages=tuple(PassageText(p["id"], p["kind"], p["text"], p["physical_page"])
                                                       for p in self.store.passages_for(w.source_version_id)))
                               if w.source_version_id in scanned else w for w in works)
            found = find_candidates(scan_works, targets=(w for w in scan_works if w.source_version_id in scanned),
                                    excluded_pairs=frozenset())
            unplaceable = []
            for sid in sorted(live.keys() - placed, key=row_order):
                flags = {d["reason"] for d in details[sid]}
                reasons = assembly.unplaceable_reasons(assembly.RowFacts(
                    live[sid].eligible, sid in last_run, sid in found.no_candidate_targets,
                    *[reason in flags for reason in ("no_relation", "insufficient_evidence", "rejected", "not_sent_budget",
                                                     "step_failed", "human_removed", "cross_relation_only", "stale_only")]))
                for reason in reasons:
                    if reason not in flags:
                        details[sid].append(self._detail(reason, to=sid))
                details[sid].sort(key=lambda d: assembly.REASONS.index(d["reason"]))
                unplaceable.append({"source_version_id": sid, "reasons": list(reasons), "details": details[sid], "last_run": last_run.get(sid)})
            active_pairs = {(l["from"], l["to"]) for l in development + cross}
            unassessed = [{"from": e.from_source_version_id, "to": e.to_source_version_id} for e in edges.unassessed_edges(
                current_edges, frozenset((c.from_source_version_id, c.to_source_version_id) for c in found.candidates),
                scanned, snapshot.human_pairs | active_pairs)]
            unscanned = [{"from": e.from_source_version_id, "to": e.to_source_version_id,
                          "to_reason": "no_pdf_text" if not live[e.to_source_version_id].eligible else "not_run"}
                         for e in current_edges if e.state == "present" and e.to_source_version_id not in scanned
                         and (e.from_source_version_id, e.to_source_version_id) not in snapshot.human_pairs | active_pairs]
            cells = [sum(c["state"] != "missing" for c in json.loads(r.node_json)["cells"]) for r in snapshot.rows]
            status = {"roles": {role: any(c["lineage_role"] == role for c in self.tables._columns(table_id)) for role in ROLES},
                      "live_rows": len(live), "pdf_text_rows": sum(r.eligible for r in snapshot.rows),
                      "nodes_complete": cells.count(3), "nodes_partial": sum(0 < n < 3 for n in cells),
                      "missing_cells": len(live) * 3 - sum(cells), "placed_rows": len(placed), "unplaced_rows": len(unplaceable)}
            unsent = [o for o in outcomes if o["kind"] == "unsent_pair"]
            failures = [o for o in outcomes if o["kind"] == "failed_pair"]
            counts = {"components": len(components), "current_links": len(development) + len(cross), "cross_relations": len(cross),
                      "history_stale": len(history["stale"]), "history_out_of_scope": len(history["out_of_scope"]),
                      "unplaceable": {"total": len(unplaceable), "reasons": {reason: sum(reason in u["reasons"] for u in unplaceable) for reason in assembly.REASONS}},
                      "not_accepted": len(not_accepted), "unassessed_edges": len(unassessed), "edges_into_unscanned_targets": len(unscanned),
                      "not_sent_budget": len(unsent), "failed_pairs": len(failures), "step_outcomes": len(outcomes),
                      "human_edited_links": sum(l["human_edited"] for l in development + cross + history["stale"] + history["out_of_scope"]),
                      # Citation-list states over live ordered pairs of different works, not link counts.
                      "edge_states": edges.edge_counts(current_edges)}
            # Convert tuple-valued frozen graph records into JSON arrays as well.
            return json.loads(json.dumps({"table_id": table_id, "table_version": table["version"], "status": status,
                    "nodes": nodes, "pair_decisions": pair_decisions, "components": components, "cross_relations": cross,
                    "unplaceable": unplaceable, "not_accepted": sorted(not_accepted, key=pair_order),
                    "unassessed_edges": unassessed, "edges_into_unscanned_targets": unscanned,
                    "step_outcomes": outcomes, "not_sent_budget": unsent, "failed_pairs": failures,
                    "history": history, "counts": counts}))

    def baseline(self, research_id: str, table_id: str) -> dict:
        with transaction(self.conn):
            self.tables._table(research_id, table_id)
            snapshot = build_snapshot(self.store, table_id)
            heads, versions = self.store.work_heads(research_id), []
            sources = {}
            for row in snapshot.rows:
                w = row.work
                source = self.store.source(w.source_version_id)
                sources[w.source_version_id] = source
                member_at = self.conn.execute("SELECT created_at FROM corpus_memberships WHERE research_id = ? AND source_version_id = ?",
                                              (research_id, w.source_version_id)).fetchone()[0]
                active_asset = self.conn.execute("SELECT 1 FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                                                (w.source_version_id,)).fetchone() is not None
                versions.append(baseline.BaselineVersion(w.source_version_id, w.work_id, heads.get(w.work_id) == w.source_version_id,
                                active_asset, member_at, source["cited_by_count"], source["cited_by_count_at"], source["publication_type"],
                                w.references_read, w.referenced_ids, w.openalex_ids))
            result = baseline.field_baseline(versions)

            def entry(value):
                source = sources[value.source_version_id]
                return {"work_id": value.work_id, "source_version_id": value.source_version_id,
                        "source_key": self.store.source_key(value.work_id), **{k: source[k] for k in ("title", "year")},
                        "cited_by_count": value.cited_by_count, "cited_by_count_at": value.cited_by_count_at,
                        "publication_type": value.publication_type, "cited_by_included_works": asdict(value.cited_by_included)}

            def listing(value, note):
                entries = [entry(e) for e in value.entries]
                return {"total": value.total, "shown": entries[:5], "entries": entries, "note": note}

            return {"table_id": table_id, "scope": "Among the works this research included",
                    "representatives": [{**asdict(r), "versions_considered": list(r.versions_considered)} for r in result.representatives],
                    "most_cited_in_corpus": listing(result.most_cited_in_corpus,
                        "Counts come from the provider and date shown; works without a stored count are not ranked and not counted as zero."),
                    "review_in_corpus": listing(result.review_in_corpus, baseline.REVIEW_NOTE),
                    "unknown_count_works": result.unknown_count_works}
