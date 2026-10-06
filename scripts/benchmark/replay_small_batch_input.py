"""Replay D238 input membership on explicit isolated round-2 snapshots, without models.

Existing decisions are held fixed. This is allocation evidence, not semantic validation
or a simulation of discovery under the new runner. Original SQLite files are read-only;
code steps are written only into disposable temporary copies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from deixis.workflow import ranking, small_batch
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store
from replay_ranking import snapshot_path


def measure(database: Path, replay_path: Path, check_path: Path) -> dict:
    replay = json.loads(replay_path.read_text())
    checks = json.loads(check_path.read_text())
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    if before != replay["snapshot_sha256"]:
        raise ValueError("Snapshot hash differs from the pinned ranking replay")
    with tempfile.TemporaryDirectory(prefix="deixis-slice3-") as temporary:
        original = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
        conn = sqlite3.connect(Path(temporary) / "library.sqlite", isolation_level=None)
        original.backup(conn)
        original.close()
        conn.row_factory = sqlite3.Row
        store = Store(conn)
        rid = replay["provenance"]["research_id"]
        scope = store.scope(rid)
        versions = ranking._versions(store, rid)
        heads = store.work_heads(rid)
        order = replay["replay"]["orders"]["C"]
        priority = sorted(row[0] for row in conn.execute(
            "SELECT source_version_id FROM selections WHERE research_id = ? AND origin = 'user'"
            " AND state = 'included'", (rid,)))
        priority_works = set(store.work_ids(priority).values())
        priority_heads = sorted(heads[wid] for wid in priority_works if wid in heads)
        order = priority_heads + [svid for svid in order if versions[svid]["work_id"] not in priority_works]
        by_work = {}
        for svid, row in versions.items():
            by_work.setdefault(row["work_id"], []).append(svid)
        listing = {"manifest_hash": hashlib.sha256(json.dumps(order).encode()).hexdigest(),
                   "manifest": {"scope_revision": scope["revision"], "versions": versions}, "items": [
                       {"head": svid, "work_id": versions[svid]["work_id"],
                        "versions": by_work[versions[svid]["work_id"]], "position": i + 1,
                        "user_priority": svid in priority_heads} for i, svid in enumerate(order)]}
        discovery = store.create_run(rid, "discovery", {"inspection": {"policy": small_batch.POLICY}}, None)
        step = store.step(discovery["id"], small_batch.LIST_KEY, "code:small_batch_list")
        store.finish_step(step["id"], "succeeded", output=small_batch.json_value(listing))
        store.update_run(discovery["id"], status="completed")
        old_budget = store.run(checks["answer_run_id"])["budget"]
        budget = small_batch.answer_budget(store, rid, scope["revision"], old_budget)
        answer = store.create_run(rid, "answer", budget, None)
        flow = object.__new__(ResearchFlow)
        flow.store = store
        flow._checkpoint = lambda *args: None
        included_heads = store.included_works(rid)
        included = [svid for head in included_heads if (svid := store.answer_version(rid, head)) is not None]
        extra = flow._abstract_sources(answer, included_heads)
        passages = flow._small_batch_answer_passages(answer, scope, included, extra, None,
                                                    flow._criterion_phrases(answer, scope))
        given = set(store.work_ids([p["source_version_id"] for p in passages]).values())
        allocation = store.existing_step(answer["id"], "small_batch:v1:answer_input")["output"]
        eligible = {item["work_id"]: i + 1 for i, item in enumerate(allocation["items"])}
        positions = {versions[svid]["work_id"]: i + 1 for i, svid in enumerate(order)}
        targets = []
        fulltext_works = {store.source(svid)["work_id"] for svid in included if store.has_pdf_text(svid)}
        fulltext_passages = [p for p in passages if store.source(p["source_version_id"])["work_id"] in fulltext_works]
        represented_fulltext = {store.source(p["source_version_id"])["work_id"] for p in fulltext_passages}
        for paper in checks["papers"]:
            works = {v["work_id"] for v in paper["source_versions"]}
            targets.append({"key": paper["target_key"], "label": paper["label"],
                            "in_input": bool(works & given), "eligible": bool(works & eligible.keys()),
                            "passages": sum(store.source(p["source_version_id"])["work_id"] in works for p in passages),
                            "list_position": min((positions[w] for w in works if w in positions), default=None),
                            "eligible_position": min((eligible[w] for w in works if w in eligible), default=None)})
        result = {"snapshot": str(database), "snapshot_sha256": before,
                  "replay": str(replay_path), "research_id": rid,
                  "answer_id": checks["answer_id"], "decision_basis": "existing snapshot decisions",
                  "passages": len(passages), "passage_limit": budget["max_answer_passages"], "represented_works": len(given),
                  "eligible_works": len(eligible), "user_priority_works": len(priority_heads),
                  "deferred_works": sum(i["reason"] == "answer_budget_deferred" for i in allocation["items"]),
                  "represented_fulltext_works": len(represented_fulltext),
                  "fulltext_passages_per_represented_work": len(fulltext_passages) / len(represented_fulltext) if represented_fulltext else None,
                  "fulltext_passages_per_eligible_work": len(fulltext_passages) / len(fulltext_works) if fulltext_works else None,
                  "targets": targets, "allocation": allocation}
        conn.close()
    if hashlib.sha256(database.read_bytes()).hexdigest() != before:
        raise ValueError("Original snapshot changed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--replay-dir", type=Path, required=True)
    parser.add_argument("--check-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = {case: measure(snapshot_path(args.snapshot_root / case), args.replay_dir / f"r2-{case}.json",
                             args.check_dir / f"{case}-check.json")
               for case in ("dbr_vbf", "kurt2017", "uwsn_kconn2022", "irs2021")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Dilim 3: tur 2 cevap girdisi replay'i", "",
             "Model, ağ ve yeni embedding çağrısı yok. C sırası ve snapshot'taki mevcut kararlar sabit tutuldu; "
             "kullanıcı dahil seçimleri öncelik bölümüne alındı. Ürün uygunluk ve pasaj dağıtım kodu geçici "
             "SQLite kopyalarında çalıştırıldı. Orijinal snapshot hashleri önceki replay ile eşleşti ve değişmedi.", "",
             "İlk temsil turu en çok 24 işi kapsar; kalan yerler aynı işler içinde tur tur dağıtılır. "
             "Abstract-only iş en çok bir, tam metinli iş en çok altı pasaj alır. Derinlik dağıtımı bittikten sonra "
             "yer kalırsa, aynı liste sırasıyla 25. ve sonraki uygun işlere birer pasaj verilir. "
             "Yalnız kapasite dolduğu için girdiye alınamayan işler ertelenir.", "",
             "| Soru | Uygun iş | Girdide iş | Pasaj / bütçe | Ertelenen iş | Tam metinli iş başına pasaj (girdide / tüm uygun) |", "|---|---:|---:|---:|---:|---:|"]
    for case, result in results.items():
        lines.append(f"| {case} | {result['eligible_works']} | {result['represented_works']} | "
                     f"{result['passages']} / {result['passage_limit']} | {result['deferred_works']} | "
                     f"{result['fulltext_passages_per_represented_work']:.2f} / {result['fulltext_passages_per_eligible_work']:.2f} |")
    lines += ["", "Ortalama, tam metni bulunan dahil işin aldığı tüm pasajları (abstract dahil) sayar; "
              "ilk payda girdide temsil edilen, ikinci payda ertelenenler dahil tüm uygun tam metinli işlerdir.", "",
              "| Hedef | C + kullanıcı önceliği yeri | Uygun işler içindeki yeri | Girdide mi? | Pasaj |",
              "|---|---:|---:|---|---:|"]
    for case, key in (("dbr_vbf", "hakim2018"), ("kurt2017", "kurt2017_17")):
        target = next(t for t in results[case]["targets"] if t["key"] == key)
        lines.append(f"| {key} | {target['list_position']} | {target['eligible_position']} | "
                     f"{'Evet' if target['in_input'] else 'Hayır'} | {target['passages']} |")
    lines += ["", "Bu bir semantik doğruluk testi değildir. Yeni runner ile keşif/abstract/tam metin "
              "kararları yürütülmedi; eski kararların yeni dağıtımda hangi işleri girdiye taşıdığı ölçüldü. "
              "Pasaj içi sıralama konu/criterion ile yapıldı; mevcut passage embedding sıralaması yeniden "
              "hesaplanmadı. Kaynak sinyalleri önceki replay'dendir ve sıralama anından sonra zenginleşmiş "
              "metadata içerebilir. Modelin bu girdiden doğru iddia üretmesi veya atıf yapması ölçülmedi.", "",
              f"Komut: `PYTHONPATH=backend uv run python scripts/benchmark/replay_small_batch_input.py "
              f"--snapshot-root {args.snapshot_root} --replay-dir {args.replay_dir} "
              f"--check-dir {args.check_dir} --output {args.output}`"]
    args.output.write_text("\n".join(lines) + "\n")
    print(json.dumps({case: {t["key"]: t["in_input"] for t in result["targets"]
                            if t["key"] in ("hakim2018", "kurt2017_17")}
                      for case, result in results.items()}))


if __name__ == "__main__":
    main()
