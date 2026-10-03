"""Watch persistence. Library records are read, never admitted or changed here."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import json

from deixis.domain import canonical
from deixis.domain.record_identity import notice_type
from deixis.providers import registry
from deixis.providers.contract import CONTRACT_ID
from deixis.storage.db import dumps, new_id, now
from . import check as policy

TABLES = ("watches", "watch_checks", "watch_reads", "watch_seen", "watch_seen_alias", "watch_items")


class WatchRefusal(Exception):
    def __init__(self, code, detail, status=409):
        self.code, self.detail, self.status = code, detail, status
        super().__init__(detail)


@contextmanager
def transaction(conn):
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def command_hash(route, research_id, resource_id, body):
    return canonical.sha256_hex({"route": route, "research_id": research_id,
                                 "resource_id": resource_id, "body": body})


class WatchStore:
    def __init__(self, main):
        self.main, self.conn = main, main.conn

    def watch(self, research_id, watch_id):
        self.main.research(research_id)
        row = self.conn.execute("SELECT * FROM watches WHERE id=? AND research_id=?", (watch_id, research_id)).fetchone()
        if row is None:
            from deixis.workflow.store import NotFound
            raise NotFound(watch_id)
        return dict(row)

    def check(self, research_id, check_id, watch_id=None):
        self.main.research(research_id)
        row = self.conn.execute("SELECT * FROM watch_checks WHERE id=? AND research_id=?", (check_id, research_id)).fetchone()
        if row is None or (watch_id is not None and row["watch_id"] != watch_id):
            from deixis.workflow.store import NotFound
            raise NotFound(check_id)
        return dict(row)

    def watches(self, research_id):
        self.main.research(research_id)
        return [dict(r) for r in self.conn.execute("SELECT * FROM watches WHERE research_id=? ORDER BY created_at,id", (research_id,))]

    def checks(self, watch_id):
        return [dict(r) for r in self.conn.execute("SELECT * FROM watch_checks WHERE watch_id=? ORDER BY created_at,id", (watch_id,))]

    def undated_titles(self, check_id):
        return [json.loads(r[0])["title"] for r in self.conn.execute(
            "SELECT record_json FROM watch_seen WHERE first_seen_check_id=? AND origin='baseline_undated' ORDER BY created_at,id", (check_id,))]

    def seen_identity(self, seen_id):
        return dict(self.conn.execute("SELECT created_at,identity_uncertain FROM watch_seen WHERE id=?", (seen_id,)).fetchone())

    def outcome_unknown(self, run_id):
        return self.conn.execute("SELECT 1 FROM run_steps WHERE run_id=? AND status='outcome_unknown'", (run_id,)).fetchone() is not None

    def reads(self, check):
        units = json.loads(check["config_json"])["units"]
        order = {u["unit_key"]: u["index"] for u in units}
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM watch_reads WHERE check_id=?", (check["id"],))]
        return sorted(rows, key=lambda r: (order[r["unit_key"]], r["page_number"]))

    def items(self, research_id, status="new"):
        self.main.research(research_id)
        sql = "SELECT * FROM watch_items WHERE research_id=?"
        args = [research_id]
        if status is not None:
            sql += " AND status=?"
            args.append(status)
        return [dict(r) for r in self.conn.execute(sql + " ORDER BY created_at,id", args)]

    def item(self, research_id, item_id):
        self.main.research(research_id)
        row = self.conn.execute("SELECT * FROM watch_items WHERE id=? AND research_id=?", (item_id, research_id)).fetchone()
        if row is None:
            from deixis.workflow.store import NotFound
            raise NotFound(item_id)
        return dict(row)

    def follows_old_scope(self, watch):
        current = self.main.research(watch["research_id"])["current_scope_revision"]
        if watch["scope_revision"] != current:
            return "scope_revised"
        if watch["kind"] == "protocol_queries":
            protocol = self.main.current_protocol(watch["research_id"], current)
            if protocol is None or protocol["id"] != watch["protocol_record_id"]:
                return "watch_protocol_changed"
        return None

    def _scope(self, research_id, kind):
        research = self.main.research(research_id)
        self.main._guard_legacy_scope(research_id, research["current_scope_revision"])
        protocol = self.main.current_protocol(research_id, research["current_scope_revision"])
        if kind == "protocol_queries" and protocol is None:
            raise WatchRefusal("no_protocol", "Freeze a protocol before following its queries.", 422)
        return research["current_scope_revision"], protocol

    def units(self, research_id, kind, protocol=None):
        units = []
        if kind == "protocol_queries":
            for index, query in enumerate(protocol["body"]["compiled_queries"]):
                connector = registry.reading(query)
                unit = dict(query, index=index, unit_key=f"query:{index}", kind=kind,
                    display_name=connector.display_name, page_size=min(connector.max_results, policy.WATCH_PER_PAGE),
                    paging=connector.paging, page_gap=connector.page_gap, date_sorted=query["provider_id"] == "openalex",
                    contract_id=CONTRACT_ID, adapter_revision=connector.adapter_revision,
                    first_cursor="*" if connector.paging != "single_page" else None,
                    status="skipped_not_searchable" if not connector.searchable else
                        "not_configured" if connector.access_mode() == "not_configured" else "ready")
                units.append(unit)
        else:
            work_ids = sorted({self.main.source(svid)["work_id"] for svid in self.main.included_works(research_id)})
            used = set()
            for work_id in work_ids:
                ids = sorted({r[0].rsplit("/", 1)[-1] for r in self.conn.execute(
                    "SELECT i.value FROM identifier_mappings i JOIN source_versions v ON v.id=i.source_version_id"
                    " WHERE v.work_id=? AND i.scheme='openalex'", (work_id,))})
                if not ids:
                    units.append({"unit_key": "work:" + work_id, "work_id": work_id,
                                  "status": "no_openalex_id", "openalex_id": None})
                for identifier in ids:
                    if identifier in used:
                        continue
                    used.add(identifier)
                    connector = registry.CONNECTORS["openalex"]
                    units.append({"unit_key": "cites:" + identifier, "work_id": work_id,
                        "openalex_id": identifier, "provider_id": "openalex", "kind": kind,
                        "query_text": "cites:" + identifier, "display_name": connector.display_name,
                        "page_size": policy.WATCH_PER_PAGE, "paging": "cursor", "page_gap": connector.page_gap,
                        "date_sorted": True, "contract_id": CONTRACT_ID, "adapter_revision": connector.adapter_revision,
                        "first_cursor": "*", "status": "ready"})
        return units

    def preview(self, research_id, kind):
        _, protocol = self._scope(research_id, kind)
        units = self.units(research_id, kind, protocol)
        return {"kind": kind, "units": units, "caps": policy.caps(),
            "citing_works_count": len({u.get("work_id") for u in units}) if kind == "citing_works" else 0,
            "no_openalex_id": sum(u["status"] == "no_openalex_id" for u in units),
            "notice": "DEIXIS checks only while it is running."}

    def _replay(self, key, digest):
        # A command key is scoped to its canonical route and resource content, even across command tables.
        for table, column, hash_column, action in (
                ("watches", "idempotency_key", "request_hash", "create"),
                ("watches", "disable_key", "disable_hash", "disable"),
                ("watch_checks", "request_key", "request_hash", "check"),
                ("watch_items", "dismiss_key", "dismiss_hash", "dismiss")):
            row = self.conn.execute(f"SELECT * FROM {table} WHERE {column}=?", (key,)).fetchone()
            if row:
                if row[hash_column] != digest:
                    raise WatchRefusal("idempotency_key_reused", "This key was used for different watch command content.")
                row = dict(row)
                if action == "dismiss":
                    return {"replayed": True, "item_id": row["id"]}
                if action == "check":
                    return {"replayed": True, "watch_id": row["watch_id"], "check_id": row["id"], "run_id": row["run_id"]}
                result = {"replayed": True, "watch_id": row["id"]}
                if action == "create":
                    first = self.conn.execute("SELECT id,run_id FROM watch_checks WHERE watch_id=?"
                        " AND request_key IS NULL AND request_hash=?", (row["id"], row["request_hash"])).fetchone()
                    result.update(check_id=first["id"], run_id=first["run_id"])
                return result
        return None

    def _idle(self, research_id, watch=None):
        if self.conn.execute("SELECT 1 FROM runs WHERE research_id=? AND status IN ('queued','running','pause_requested')",
                             (research_id,)).fetchone():
            raise WatchRefusal("run_active", "Finish or cancel the active research run first.")
        if watch and self.conn.execute(
            "SELECT 1 FROM watch_checks c JOIN runs r ON r.id=c.run_id WHERE c.watch_id=?"
            " AND (r.status='paused' OR (r.status NOT IN ('completed','failed','cancelled') AND EXISTS"
            " (SELECT 1 FROM run_steps s WHERE s.run_id=r.id AND s.status='outcome_unknown')))", (watch["id"],)).fetchone():
            raise WatchRefusal("check_paused", "Resume or cancel this watch's unfinished check first.")

    def _version(self, watch, expected):
        if watch["state_version"] != expected:
            raise WatchRefusal("watch_changed", "The watch changed. Read its current state before trying again.")

    def cancel_unavailable(self, run_id):
        # update_run's person-reading follow-up needs a visible research. A trashed research has no watch admission
        # or person-file work to close here; retain the run transition without that unrelated live-scope read.
        with transaction(self.conn):
            run = self.main.run(run_id)
            self.conn.execute("UPDATE runs SET status='cancelled',pause_reason='research_unavailable',"
                "error_json=?,updated_at=?,version=version+1 WHERE id=?",
                (dumps({"code": "research_unavailable"}), now(), run_id))
            self.main._event(run["research_id"], "run_cancelled", {"pause_reason": "research_unavailable"}, run_id)

    def refuse_revision(self, run_id):
        self.main.update_run(run_id, event="run_failed", status="failed", pause_reason="adapter_revision_changed",
                             error_json={"code": "adapter_revision_changed"})

    def _insert_watch(self, research_id, body, key, digest):
        revision, protocol = self._scope(research_id, body["kind"])
        if body["mode"] != "manual":
            raise WatchRefusal("interval_not_built", "Interval checks are not built yet.", 422)
        if revision != body["expected_scope_revision"]:
            raise WatchRefusal("scope_changed", "The research scope changed. Read it before enabling follow-up.")
        if self.conn.execute("SELECT 1 FROM watches WHERE research_id=? AND kind=? AND enabled=1",
                             (research_id, body["kind"])).fetchone():
            raise WatchRefusal("watch_enabled", "This kind of follow-up is already enabled.")
        wid = new_id("wat")
        self.conn.execute("INSERT INTO watches (id,research_id,kind,mode,enabled,protocol_record_id,scope_revision,"
            "idempotency_key,request_hash,created_at) VALUES (?,?,?,'manual',1,?,?,?,?,?)",
            (wid, research_id, body["kind"], protocol["id"] if body["kind"] == "protocol_queries" else None,
             revision, key, digest, now()))
        return self.watch(research_id, wid)

    def _queue(self, watch, key=None, digest=None):
        research_id = watch["research_id"]
        self._idle(research_id, watch)
        if not watch["enabled"]:
            raise WatchRefusal("watch_disabled", "This watch is disabled.")
        if self.follows_old_scope(watch):
            raise WatchRefusal("watch_follows_old_scope", "Rebind this watch to the current research scope first.")
        ts, cid = now(), new_id("wch")
        baseline = json.loads(watch["baseline_json"])
        protocol = self.main.current_protocol(research_id, watch["scope_revision"])
        units = self.units(research_id, watch["kind"], protocol)
        skipped = []
        rolled_over, rolled_over_units, next_position = 0, 0, None
        if watch["kind"] == "citing_works":
            skipped = [u for u in units if u["status"] == "no_openalex_id"]
            work_ids = {u["work_id"] for u in units if u.get("openalex_id")}
            units, rolled_over_units, next_position = policy.citing_roll(units, baseline, baseline.get("_citing_position", 0),
                                                                  policy.WATCH_CITING_SOURCES)
            rolled_over = len(work_ids - {u["work_id"] for u in units})
        units = policy.unit_plan(units, baseline, ts)
        for index, unit in enumerate(units):
            unit["index"] = index
        deadline = (datetime.fromisoformat(ts) + timedelta(seconds=policy.WATCH_DEADLINE_SECONDS)).isoformat()
        limits = policy.caps()
        budget = {"max_provider_requests": limits["max_provider_requests"], "max_records": limits["max_records"]}
        config = {"version": 1, "kind": watch["kind"], "scope_revision": watch["scope_revision"],
            "protocol_record_id": watch["protocol_record_id"], "units": units, "skipped_units": skipped,
            "rolled_over": rolled_over, "rolled_over_units": rolled_over_units, "next_citing_position": next_position,
            "caps": limits, "budget": budget, "deadline_at": deadline}
        period = "manual:" + ts
        run = self.main.create_run(research_id, "watch_check", budget, f"watch:{watch['id']}:{period}",
            {"watch_id": watch["id"], "check_id": cid, "deadline_at": deadline, "request_hash": digest})
        starts = [u["requested_from"] for u in units if u["requested_from"]]
        self.conn.execute("INSERT INTO watch_checks (id,watch_id,research_id,run_id,trigger,period_start,requested_from,"
            "requested_to,config_json,state_version,request_key,request_hash,created_at)"
            " VALUES (?,?,?,?,'manual',?,?,?,?,?,?,?,?)",
            (cid, watch["id"], research_id, run["id"], period, min(starts) if starts else None, ts,
             dumps(config), watch["state_version"], key, digest, ts))
        return {"replayed": False, "watch_id": watch["id"], "check_id": cid, "run_id": run["id"]}

    def create(self, research_id, body, key):
        digest = command_hash("create", research_id, None, body)
        with transaction(self.conn):
            replay = self._replay(key, digest)
            if replay:
                return replay
            self._idle(research_id)
            watch = self._insert_watch(research_id, body, key, digest)
            return self._queue(watch, digest=digest)

    def check_now(self, research_id, watch_id, body, key):
        digest = command_hash("check", research_id, watch_id, body)
        with transaction(self.conn):
            replay = self._replay(key, digest)
            if replay:
                return replay
            watch = self.watch(research_id, watch_id)
            self._version(watch, body["expected_state_version"])
            return self._queue(watch, key, digest)

    def disable(self, research_id, watch_id, body, key):
        digest = command_hash("disable", research_id, watch_id, body)
        with transaction(self.conn):
            replay = self._replay(key, digest)
            if replay:
                return replay
            watch = self.watch(research_id, watch_id)
            self._version(watch, body["expected_state_version"])
            if not watch["enabled"]:
                raise WatchRefusal("watch_disabled", "This watch is already disabled.")
            self.conn.execute("UPDATE watches SET enabled=0,disabled_at=?,state_version=state_version+1,"
                "disable_key=?,disable_hash=? WHERE id=?", (now(), key, digest, watch_id))
            return {"replayed": False, "watch_id": watch_id}

    def rebind(self, research_id, watch_id, body, key):
        digest = command_hash("rebind", research_id, watch_id, body)
        with transaction(self.conn):
            replay = self._replay(key, digest)
            if replay:
                return replay
            watch = self.watch(research_id, watch_id)
            self._version(watch, body["expected_state_version"])
            self._idle(research_id, watch)
            self.conn.execute("UPDATE watches SET enabled=0,disabled_at=?,state_version=state_version+1 WHERE id=?", (now(), watch_id))
            revision = self.main.research(research_id)["current_scope_revision"]
            new = self._insert_watch(research_id, {"kind": watch["kind"], "mode": "manual", "expected_scope_revision": revision}, key, digest)
            return self._queue(new, digest=digest)

    def dismiss(self, research_id, item_id, body, key):
        digest = command_hash("dismiss", research_id, item_id, body)
        with transaction(self.conn):
            replay = self._replay(key, digest)
            if replay:
                return replay
            item = self.item(research_id, item_id)
            if body["expected_status"] != "new" or item["status"] != "new":
                raise WatchRefusal("item_changed", "The item changed. Read it before dismissing it.")
            self.conn.execute("UPDATE watch_items SET status='dismissed',dismissed_reason=?,dismissed_at=?,"
                "dismiss_key=?,dismiss_hash=? WHERE id=?", (body.get("reason"), now(), key, digest, item_id))
            return {"replayed": False, "item_id": item_id}

    def record_read(self, check, unit, page, step, outcome, records, returned, dropped, connector,
                    payload_path, payload_digest, file_digest, refusal=None, finish=True):
        dates = [r["publication_date"] for r in records if r["publication_date"]]
        with transaction(self.conn):
            self.conn.execute("INSERT INTO watch_reads (id,check_id,research_id,step_id,unit_key,page_number,provider,"
                "status,error_code,request_description,http_status,error_kind,returned_count,dropped_count,next_cursor,"
                "oldest_publication_date,newest_publication_date,records_json,connector_json,raw_payload_path,"
                "payload_sha256,payload_file_sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("wrd"), check["id"], check["research_id"], step["id"], unit["unit_key"], page,
                 unit["provider_id"], refusal or outcome.status, refusal or outcome.error, outcome.request_description,
                 outcome.http_status, outcome.error_kind, returned, dropped, outcome.next_cursor,
                 min(dates) if dates else None, max(dates) if dates else None, dumps(records),
                 dumps(connector) if connector else None, payload_path, payload_digest, file_digest, now()))
            if finish:
                success = outcome.status in ("completed", "zero_results") and refusal is None
                self.main.finish_step(step["id"], "succeeded" if success else "failed",
                    {"status": refusal or outcome.status, "returned": returned, "dropped": dropped},
                    error_code=None if success else refusal or outcome.status,
                    error={"http_status": outcome.http_status, "error_kind": outcome.error_kind},
                    delivery_class=outcome.delivery_class)

    def _library_matches(self, record):
        found = set()
        for alias in record["aliases"]:
            scheme, value = alias.split(":", 1)
            found.update(r[0] for r in self.conn.execute(
                "SELECT source_version_id FROM identifier_mappings WHERE scheme=? AND value=?", (scheme, value)))
        return sorted(found)

    def _live_seen(self, research_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM watch_seen WHERE research_id=? AND merged_into IS NULL ORDER BY created_at,id", (research_id,))]

    def _append_relation(self, item_id, relation):
        item = self.conn.execute("SELECT relations_json FROM watch_items WHERE id=?", (item_id,)).fetchone()
        relations = json.loads(item[0])
        identity = {k: v for k, v in relation.items() if k != "check_id"}
        if not any({k: v for k, v in r.items() if k != "check_id"} == identity for r in relations):
            relations.append(relation)
            self.conn.execute("UPDATE watch_items SET relations_json=? WHERE id=?", (dumps(relations), item_id))

    def _reconcile(self, check, record, seen_id, item_id):
        rid, cid = check["research_id"], check["id"]
        for other in self._live_seen(rid):
            if other["id"] == seen_id:
                continue
            counterpart = self.conn.execute("SELECT i.* FROM watch_items i JOIN watch_seen s ON s.id=i.seen_id"
                " WHERE (s.id=? OR s.merged_into=?) AND i.status!='merged' ORDER BY i.created_at,i.id LIMIT 1",
                (other["id"], other["id"])).fetchone()
            if counterpart is None and other["origin"] not in ("baseline", "in_library"):
                continue
            other_record = json.loads(other["record_json"])
            relation = policy.relation_to(record, other_record, "seen", other["id"], cid)
            if relation:
                self._append_relation(item_id, relation)
                if counterpart:
                    reverse = policy.relation_to(other_record, record, "seen", seen_id, cid)
                    if reverse:
                        self._append_relation(counterpart["id"], reverse)
        for source in self.conn.execute(
            "SELECT v.* FROM source_versions v JOIN corpus_memberships m ON m.source_version_id=v.id"
            " WHERE m.research_id=? AND m.removed_at IS NULL ORDER BY v.id", (rid,)):
            other = dict(source)
            other["authors"] = json.loads(other["authors_json"])
            other["abstract"] = self.conn.execute(
                "SELECT text FROM passages WHERE source_version_id=? AND kind='abstract' ORDER BY rowid LIMIT 1", (other["id"],)).fetchone()
            other["abstract"] = other["abstract"][0] if other["abstract"] else None
            identifiers = {r[0]: r[1] for r in self.conn.execute(
                "SELECT scheme,value FROM identifier_mappings WHERE source_version_id=?", (other["id"],))}
            other["relations"] = []
            if (other.get("doi") or "").startswith(policy.ARXIV_DOI_PREFIX):
                other["relations"].append({"relation": "version_family_doi", "doi": other["doi"]})
            if identifiers.get("published_doi"):
                other["relations"].append({"relation": "names_published_doi", "doi": identifiers["published_doi"]})
            relation = policy.relation_to(record, other, "library", other["id"], cid)
            if relation:
                self._append_relation(item_id, relation)

    def _announce(self, check, unit, record, counts):
        rid, cid, ts = check["research_id"], check["id"], now()
        hits = set()
        for alias in record["aliases"]:
            row = self.conn.execute("SELECT seen_id FROM watch_seen_alias WHERE research_id=? AND alias=?", (rid, alias)).fetchone()
            if row:
                seen_id = row[0]
                while True:
                    merged = self.conn.execute("SELECT merged_into FROM watch_seen WHERE id=?", (seen_id,)).fetchone()[0]
                    if merged is None:
                        break
                    seen_id = merged
                hits.add(seen_id)
        item = None
        kind = "notice" if notice_type(record["title"]) else "new_record"
        if hits:
            rows = sorted((dict(self.conn.execute("SELECT * FROM watch_seen WHERE id=?", (sid,)).fetchone()) for sid in hits),
                          key=lambda r: (r["created_at"], r["id"]))
            seen_id = rows[0]["id"]
            items = []
            for row in rows:
                items.extend(dict(i) for i in self.conn.execute(
                    "SELECT i.* FROM watch_items i JOIN watch_seen s ON s.id=i.seen_id"
                    " WHERE (s.id=? OR s.merged_into=?) AND i.status!='merged'", (row["id"], row["id"])))
            items.sort(key=lambda r: (r["created_at"], r["id"]))
            for row in rows[1:]:
                self.conn.execute("UPDATE watch_seen SET merged_into=? WHERE id=?", (seen_id, row["id"]))
                self.conn.execute("UPDATE watch_seen SET merged_into=? WHERE merged_into=?", (seen_id, row["id"]))
                self.conn.execute("UPDATE watch_seen_alias SET seen_id=? WHERE seen_id=?", (seen_id, row["id"]))
            if items:
                item = items[0]
                for other_item in items[1:]:
                    self.conn.execute("UPDATE watch_items SET status='merged',merged_into_item_id=? WHERE id=?", (item["id"], other_item["id"]))
                    for relation in json.loads(other_item["relations_json"]):
                        self._append_relation(item["id"], relation)
            saved_record = json.loads(rows[0]["record_json"])
            prior_kind = saved_record.get("classification_history", [{"kind": "notice" if notice_type(saved_record["title"]) else "new_record"}])[-1]["kind"]
            if kind != prior_kind:
                saved_record.setdefault("classification_history", []).append({"kind": kind, "check_id": cid})
                self.conn.execute("UPDATE watch_seen SET record_json=? WHERE id=?", (dumps(saved_record), seen_id))
                if item:
                    history = json.loads(item["kind_history_json"])
                    history.append({"from": item["kind"], "to": kind, "check_id": cid})
                    self.conn.execute("UPDATE watch_items SET kind=?,kind_history_json=? WHERE id=?", (kind, dumps(history), item["id"]))
            counts["already_seen"] += 1
        else:
            library = self._library_matches(record)
            origin = "in_library" if library else policy.baseline_origin(unit, record)
            if origin is None:
                origin = "notice" if kind == "notice" else "announced"
            seen_id = new_id("wsn")
            saved_record = deepcopy(record)
            if library:
                saved_record["source_version_ids"] = library
            self.conn.execute("INSERT INTO watch_seen (id,research_id,identity_key,record_json,first_seen_check_id,origin,"
                "identity_uncertain,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (seen_id, rid, record["aliases"][0], dumps(saved_record), cid, origin, int(policy.identity_uncertain(record)), ts))
            if origin in ("announced", "notice"):
                item_id = new_id("wit")
                self.conn.execute("INSERT INTO watch_items (id,research_id,check_id,seen_id,record_json,kind,found_by_json,"
                    "relations_json,kind_history_json,status,created_at) VALUES (?,?,?,?,?,?,? ,?,'[]','new',?)",
                    (item_id, rid, cid, seen_id, dumps(record), kind, "[]", dumps(record["relations"]), ts))
                item = dict(self.conn.execute("SELECT * FROM watch_items WHERE id=?", (item_id,)).fetchone())
                counts["notices" if kind == "notice" else "new"] += 1
            else:
                counts[{"in_library": "already_in_library", "baseline": "baseline", "baseline_undated": "baseline_undated"}[origin]] += 1
        for alias in record["aliases"]:
            self.conn.execute("INSERT OR IGNORE INTO watch_seen_alias (research_id,alias,seen_id,created_at) VALUES (?,?,?,?)", (rid, alias, seen_id, ts))
        if item:
            finders = json.loads(item["found_by_json"])
            finder = {"kind": unit["kind"], "watch_id": check["watch_id"], "check_id": cid, "unit_key": unit["unit_key"]}
            if finder not in finders:
                finders.append(finder)
                self.conn.execute("UPDATE watch_items SET found_by_json=? WHERE id=?", (dumps(finders), item["id"]))
            self._reconcile(check, record, seen_id, item["id"])

    def complete_check(self, check, observed, provider_status):
        config = json.loads(check["config_json"])
        run_id, rid = check["run_id"], check["research_id"]
        with transaction(self.conn):
            done = self.main.existing_step(run_id, "watch_complete")
            if done and done["status"] == "succeeded":
                return
            run = self.main.run(run_id)
            if run["status"] not in ("running", "pause_requested"):
                return
            watch = dict(self.conn.execute("SELECT * FROM watches WHERE id=?", (check["watch_id"],)).fetchone())
            research = self.conn.execute("SELECT * FROM researches WHERE id=? AND trashed_at IS NULL", (rid,)).fetchone()
            reason = "research_unavailable" if research is None else "watch_disabled" if not watch["enabled"] else None
            if reason is None:
                reason = self.follows_old_scope(watch)
            if reason is None and watch["state_version"] != check["state_version"]:
                reason = "watch_state_changed"
            if reason:
                if reason == "research_unavailable":
                    self.cancel_unavailable(run_id)
                else:
                    self.main.update_run(run_id, event="run_failed" if reason == "watch_state_changed" else "run_cancelled",
                        status="failed" if reason == "watch_state_changed" else "cancelled", pause_reason=reason, error_json={"code": reason})
                return
            counts = {name: 0 for name in ("records_read", "new", "notices", "already_seen", "already_in_library", "baseline", "may_be_version", "baseline_undated")}
            counts["caps"] = config["caps"]
            counts["units"] = {}
            units = {u["unit_key"]: u for u in config["units"]}
            rows = self.reads(check)
            for row in rows:
                count = counts["units"].setdefault(row["unit_key"], {"returned": 0, "dropped": 0})
                count["returned"] += row["returned_count"]
                count["dropped"] += row["dropped_count"]
                if row["status"] in ("completed", "zero_results"):
                    records = json.loads(row["records_json"])
                    counts["records_read"] += len(records)
                    for record in records:
                        self._announce(check, units[row["unit_key"]], record, counts)
            baseline = json.loads(watch["baseline_json"])
            for unit in config["units"]:
                key = unit["unit_key"]
                obs = observed["units"][key]
                old = baseline.get(key, {})
                if obs["pages_read"]:
                    completed = obs["finished"]
                    baseline[key] = {"state": "complete" if completed or not unit["baseline"] else "partial",
                        "cut": unit["cut"] if unit["baseline"] else old.get("cut"), "cursor": obs["next_cursor"],
                        "pages_read": unit["pages_read"] + obs["pages_read"] if unit["baseline"] else old.get("pages_read", 0),
                        "page_size": unit["page_size"], "contract_id": unit["contract_id"], "adapter_revision": unit["adapter_revision"],
                        "success_boundary": check["requested_to"] if completed else old.get("success_boundary"),
                        "covered_back_to": obs["oldest_publication_date"] or old.get("covered_back_to")}
                elif key not in baseline:
                    baseline[key] = {"state": "pending", "cut": None, "cursor": None, "pages_read": 0,
                        "page_size": unit["page_size"], "contract_id": unit["contract_id"], "adapter_revision": unit["adapter_revision"],
                        "success_boundary": None, "covered_back_to": None}
            if config["next_citing_position"] is not None:
                baseline["_citing_position"] = config["next_citing_position"]
            returned = sum(r["returned_count"] for r in rows)
            counts.update(returned=returned, dropped=sum(r["dropped_count"] for r in rows),
                          records_over_threshold=max(0, returned-config["caps"]["max_records"]))
            for item in self.items(rid, None):
                if item["check_id"] == check["id"] and any(r.get("relation") == "may_be_version" for r in json.loads(item["relations_json"])):
                    counts["may_be_version"] += 1
            totals = self.conn.execute("SELECT status,count(*) FROM watch_items WHERE research_id=? GROUP BY status", (rid,)).fetchall()
            totals = dict(totals)
            counts.update(new_open=totals.get("new", 0), dismissed=totals.get("dismissed", 0), added=0)
            ts = now()
            success = any(r["status"] in ("completed", "zero_results") for r in rows)
            self.conn.execute("UPDATE watches SET baseline_json=?,state_version=state_version+1,last_checked_at=?,"
                "last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END WHERE id=?",
                (dumps(baseline), ts, success, ts, watch["id"]))
            self.conn.execute("UPDATE watch_checks SET observed_json=?,provider_status_json=?,counts_json=?,completed_at=? WHERE id=?",
                (dumps(observed), dumps(provider_status), dumps(counts), ts, check["id"]))
            step = self.main.step(run_id, "watch_complete", "watch_complete")
            self.main.finish_step(step["id"], "succeeded", counts)
            self.main.update_run(run_id, event="run_completed" if success else "run_failed", status="completed" if success else "failed",
                pause_reason=None if success else "no_provider_read", error_json=None if success else {"code": "no_provider_read"})
            self.main._event(rid, "watch_check_completed", counts, run_id)


def purge_watches(conn, research_id):
    paths = [r[0] for r in conn.execute("SELECT raw_payload_path FROM watch_reads WHERE research_id=? AND raw_payload_path IS NOT NULL", (research_id,))]
    conn.execute("UPDATE watch_items SET merged_into_item_id=NULL WHERE research_id=?", (research_id,))
    conn.execute("UPDATE watch_seen SET merged_into=NULL WHERE research_id=?", (research_id,))
    for table in ("watch_items", "watch_seen_alias", "watch_seen", "watch_reads", "watch_checks", "watches"):
        conn.execute(f"DELETE FROM {table} WHERE research_id=?", (research_id,))
    return paths
