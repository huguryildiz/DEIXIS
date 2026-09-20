# SW dilim 02 — Aşama kararlarının saklanması: uygulama planı

**Tarih:** 20 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): SW9 madde 4–5, SW11 madde 1, 2, 5, 7, 10, SW7 madde 3–4. **Önkoşul:** dilim 01 (D70) kapandı. **Sahip kararları:** K1 ve K2 önerildiği gibi kabul edildi (20 Eylül 2026).

**Goal:** Bugün bir kaydın tarama sonucu tek bir satırda durur (`selections`: `included` / `excluded` / `pending`, serbest metin gerekçe) ve o satırı model önerisi doğrudan yazar (`store.apply_screening_proposal`, `workflow/store.py`). SW akışı her kayıt için aşama başına (özet, tam metin) üç cevaptan birini, bir neden koduyla, kimin karar verdiğiyle ve sonraki adımla saklamak; model önerilerini alıntısı ve doğrulama sonucuyla ayrı tutmak; sinyal sıralarını kayıt başına saklamak ister. Bu dilim yalnızca o saklama katmanını ve `selections`'ı bu kararlardan türeten tek işlevi kurar. **Hiçbir akış adımı henüz bu tabloları yazmaz**; yazanlar dilim 05, 07, 09, 12 ve 16'da gelir. Arayüz ve sözleşme değişmez.

**Architecture:** Yeni bir `DecisionStore` sınıfı, `TableStore` kalıbıyla (`workflow/tables.py:108`: `Store`'u sarar, aynı bağlantıyı kullanır). Kararlar eklemelidir: aynı kayıt ve aşama için yeni karar eskisini `superseded_at` ile kapatır, satır silinmez ve güncellenmez. İnsan kararı ayrı tablo değildir; `decided_by = 'human'` olan bir karar satırıdır ve kod ya da model onu ezemez. Neden kodları veritabanında değil `domain/reason_codes.py` içindeki sözlüktedir; depo, sözlükte olmayan kodu reddeder. Türetme yalnızca `search_workflow = 'sw'` araştırmalarında `selections`'a yazar.

**Tech stack:** Python 3.12, SQLite. Yeni bağımlılık yok.

## Global constraints

- `apps/web/`, `contracts/research/`, `methods/deixis-research/` ve mevcut migration dosyalarına dokunma. `skill_package_hash` değişmez.
- `flow.py` bu dilimde **değişmez**. `legacy` akışın hiçbir davranışı değişmez; mevcut hiçbir test beklentisi değişmemeli. Değişiyorsa dur ve sor.
- Migration numarası bu not yazılırken `0038`'dir; başlamadan önce kontrol et.
- Kullanıcının seçimi her zaman üstündür (`AGENTS.md`, "User Authority"): `selections.origin = 'user'` olan satırın `state`'ini türetme değiştirmez.
- Git durumunu değiştirme.

## Dosya yapısı

Yeni: `backend/deixis/storage/migrations/0038_stage_decisions.sql`, `backend/deixis/domain/reason_codes.py`, `backend/deixis/workflow/decisions.py`, `tests/test_reason_codes.py`, `tests/test_stage_decisions.py`.

Değişecek: `backend/deixis/workflow/store.py` (yalnızca kalıcı silme listeleri: `purge_research` ~243 ve `purge_sources` ~1586), `tests/test_migrations.py`, `tests/determinism_stages.py`, `docs/decisions.md`, `docs/product/search-workflow-review-2026-09-18.md` (durum satırları), `docs/product/sw-status.md`.

## Task 1: reason codes

**Files:** Create `domain/reason_codes.py`, `tests/test_reason_codes.py`.

```python
STAGES = ("abstract", "fulltext")
OUTCOMES = {"abstract": ("candidate", "out_of_scope", "unresolved"),
            "fulltext": ("include", "criterion_not_met", "unresolved")}
DECIDERS = ("code", "model_agreement", "human")
NEXT_STEPS = ("none", "abstract_lookup", "abstract_model", "fulltext_fetch", "reading_queue", "fulltext_model",
              "human_queue", "waiting_for_pdf", "seed_pool", "answer")

@dataclass(frozen=True)
class ReasonCode:
    code: str; stage: str; outcome: str; decided_by: str; next_step: str

REASON_CODES: dict[str, ReasonCode]
def reason(code: str) -> ReasonCode: ...      # KeyError with the code in the message when unknown
```

Bu dilimdeki kodlar (SW11'deki çalışma adları; sonraki dilimler yazarlarıyla birlikte yenilerini ekler, var olanın anlamını değiştirmez):

| Kod | Aşama | Sonuç | Karar veren | Sonraki adım | SW |
|---|---|---|---|---|---|
| `blocks_in_title` | abstract | candidate | code | fulltext_fetch | SW9.1 |
| `both_blocks_missing` | abstract | out_of_scope | code | none | SW9.2 |
| `no_abstract` | abstract | unresolved | code | abstract_lookup | SW5.5 |
| `runs_agree_candidate` | abstract | candidate | model_agreement | fulltext_fetch | SW9.1 |
| `runs_agree_out_of_scope` | abstract | out_of_scope | model_agreement | none | SW9.1 |
| `runs_disagree_kept_as_candidate` | abstract | candidate | code | fulltext_fetch | SW11.4 |
| `quote_not_found_kept_as_candidate` | abstract | candidate | code | fulltext_fetch | SW11.4 |
| `abstract_not_proposed` | abstract | unresolved | code | abstract_model | SW1.1 (model kapalı ya da sıra gelmedi) |
| `all_parts_verified` | fulltext | include | model_agreement | answer | SW11.1 |
| `criterion_absent` | fulltext | criterion_not_met | model_agreement | none | SW11.1–2 |
| `no_fulltext` | fulltext | unresolved | code | waiting_for_pdf | SW11.3 |
| `text_unreadable` | fulltext | unresolved | code | waiting_for_pdf | SW11.9 |
| `not_read_yet` | fulltext | unresolved | code | reading_queue | SW11.3 |
| `fulltext_runs_disagree` | fulltext | unresolved | code | human_queue | SW11.4 |
| `include_quote_unverified` | fulltext | unresolved | code | human_queue | SW11.4 |
| `part_without_evidence` | fulltext | unresolved | code | human_queue | SW11.4 |
| `abstract_promise_absent` | fulltext | unresolved | code | human_queue | SW11.4 |
| `human_include` | fulltext | include | human | answer | SW11.7 |
| `human_criterion_not_met` | fulltext | criterion_not_met | human | none | SW11.7 |
| `human_not_sure` | fulltext | unresolved | human | none | SW11.11 |
| `human_pdf_wrong` | fulltext | unresolved | human | waiting_for_pdf | SW11.11 |

Derleme işareti, kod kapısı ve K3 bütçe kodları bu dilimde **yok**; yazarlarıyla gelir (dilim 05, 23, 09). Ön baskı ve model ailesi neden kodu değildir, etikettir (SW11.5).

- [ ] **Tests first:** her kodun aşaması `STAGES`'te, sonucu o aşamanın `OUTCOMES`'unda, `decided_by` ve `next_step` kendi listelerinde; `human_*` kodlarının hepsi `decided_by == "human"`; bilinmeyen kod `KeyError`; sözlük anahtarı `ReasonCode.code` ile aynı.

## Task 2: migration

**Files:** Create `0038_stage_decisions.sql`. Modify `tests/test_migrations.py` (mevcut kalıba ekle).

```sql
CREATE TABLE stage_decisions (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  stage TEXT NOT NULL CHECK (stage IN ('abstract', 'fulltext')),
  outcome TEXT NOT NULL CHECK (outcome IN ('candidate', 'out_of_scope', 'include', 'criterion_not_met', 'unresolved')),
  reason_code TEXT NOT NULL,
  decided_by TEXT NOT NULL CHECK (decided_by IN ('code', 'model_agreement', 'human')),
  next_step TEXT NOT NULL,
  note TEXT,
  scope_revision INTEGER NOT NULL,
  protocol_hash TEXT,
  criterion_hash TEXT,
  step_id TEXT REFERENCES run_steps(id),
  superseded_at TEXT,
  created_at TEXT NOT NULL,
  CHECK ((stage = 'abstract' AND outcome IN ('candidate', 'out_of_scope', 'unresolved'))
      OR (stage = 'fulltext' AND outcome IN ('include', 'criterion_not_met', 'unresolved')))
);
CREATE UNIQUE INDEX stage_decisions_current ON stage_decisions(research_id, source_version_id, stage) WHERE superseded_at IS NULL;
CREATE INDEX stage_decisions_research ON stage_decisions(research_id, stage, outcome);

CREATE TABLE model_proposals (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  stage TEXT NOT NULL CHECK (stage IN ('abstract', 'fulltext')),
  step_id TEXT NOT NULL REFERENCES run_steps(id),
  run_no INTEGER NOT NULL CHECK (run_no IN (1, 2)),
  criterion_part TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL,
  quote TEXT,
  quote_verified INTEGER CHECK (quote_verified IS NULL OR quote_verified IN (0, 1)),
  quote_passage_id TEXT REFERENCES passages(id),
  quote_page INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE (step_id, source_version_id, criterion_part)
);
CREATE INDEX model_proposals_record ON model_proposals(research_id, source_version_id, stage, run_no);

CREATE TABLE record_signal_ranks (
  ranking_step_id TEXT NOT NULL REFERENCES run_steps(id),
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  signal TEXT NOT NULL,
  rank REAL NOT NULL,
  available INTEGER NOT NULL CHECK (available IN (0, 1)),
  PRIMARY KEY (ranking_step_id, source_version_id, signal)
);
CREATE INDEX record_signal_ranks_research ON record_signal_ranks(research_id, signal, rank);
```

`stage_decisions` ve `model_proposals` için UPDATE tetikleyicisi yazılmaz: `superseded_at` güncellenir. DELETE, migration 0037'deki kalıpla (`research_purge_authorizations` istisnası) engellenir. `rank` `REAL`'dir çünkü eşit puanlı kayıtlar ortalama sıra alır (SW7); birleşik sıra `signal = 'fused'` olarak saklanır.

`selections.origin` CHECK kısıtına `'code_rule'` eklenir. SQLite CHECK'i yerinde değiştiremez; tablo yeniden kurulur. Kalıp için `0021_library_membership.sql` ve `0019_table_run_kinds.sql`'i oku (yeni tablo, satırları kopyala, eskisini düşür, yeniden adlandır, indeksleri ve tetikleyicileri yeniden kur). `selections`'a başka tablodan yabancı anahtar var mı, önce `grep -n "REFERENCES selections" backend/deixis/storage/migrations/*.sql` ile doğrula. `selection_history.origin` üzerinde CHECK yoktur; ona dokunma.

- [ ] **Tests first:** tablolar ve sütunlar vardır; `stage = 'abstract', outcome = 'include'` eklenemez; aynı kayıt ve aşama için ikinci "güncel" satır eklenemez; `selections` yeniden kurulduktan sonra eski satırlar birebir durur (migration öncesi eklenen bir satırla sına) ve `origin = 'code_rule'` eklenebilir; `stage_decisions` DELETE yetkisiz reddedilir.

## Task 3: DecisionStore — writing and reading

**Files:** Create `workflow/decisions.py`, `tests/test_stage_decisions.py`.

```python
class HumanDecisionStands(Exception): ...

class DecisionStore:
    def __init__(self, store: Store): ...
    def record(self, research_id: str, source_version_id: str, reason_code: str, *, step_id: str | None = None,
               note: str | None = None) -> dict[str, Any]: ...
    def current(self, research_id: str, source_version_id: str, stage: str) -> dict[str, Any] | None: ...
    def history(self, research_id: str, source_version_id: str) -> list[dict[str, Any]]: ...
    def undo_human(self, research_id: str, source_version_id: str, stage: str) -> dict[str, Any] | None: ...
    def add_proposal(self, research_id: str, source_version_id: str, stage: str, step_id: str, run_no: int, label: str, *,
                     criterion_part: str = "", quote: str | None = None, quote_verified: bool | None = None,
                     quote_passage_id: str | None = None, quote_page: int | None = None) -> str: ...
    def proposals(self, research_id: str, source_version_id: str, stage: str) -> list[dict[str, Any]]: ...
    def save_ranks(self, ranking_step_id: str, research_id: str, rows: list[dict[str, Any]]) -> None: ...
    def ranks(self, research_id: str, source_version_id: str) -> list[dict[str, Any]]: ...
    def is_stale(self, decision: dict[str, Any]) -> bool: ...
```

Kurallar:

- `record`: aşama, sonuç, karar veren ve sonraki adım `reason_codes.reason(code)`'dan gelir; çağıran bunları vermez. `scope_revision` araştırmanın güncel revizyonudur; `protocol_hash` o revizyonun `store.current_protocol(...)` özetidir (yoksa `NULL`); `criterion_hash`, protokol gövdesindeki `inclusion_criterion`, `criterion_parts` ve `cue_phrases` alanlarının `canonical.sha256_hex` özetidir, üçü de `None` ise `NULL`.
- **Tekrar:** güncel karar aynı `reason_code`, aynı `protocol_hash` ve aynı `step_id` ile zaten varsa yeni satır yazılmaz, var olan döner (sürdürülen koşu).
- **İnsan kararı durur (SW11.7):** güncel karar `decided_by = 'human'` ise ve yeni kodun karar vereni insan değilse `HumanDecisionStands` fırlatılır, hiçbir şey yazılmaz. İnsan, insan kararının üstüne yazabilir.
- Aksi halde eski güncel satır `superseded_at = now()` olur ve yenisi eklenir, tek işlemde.
- `undo_human`: güncel insan kararını kapatır ve ondan önceki, insan olmayan son kararı yeni bir satır olarak geri getirir (aynı kod, `note = "restored after an undone human decision"`); öncesi yoksa aşama kararsız kalır ve `None` döner.
- `add_proposal`: aynı `(step_id, source_version_id, criterion_part)` ikinci kez gelirse var olan kimlik döner.
- `save_ranks`: bir `ranking_step_id` için ikinci çağrı var olan satırları değiştirmez (ilk yazılan durur); satır biçimi `{"source_version_id", "signal", "rank", "available"}`.
- `is_stale` (SW11.10): kararın `scope_revision`'ı güncel revizyondan farklıysa ya da `criterion_hash`'i güncel protokolünkinden farklıysa `True`. Karar silinmez, taşınmaz, yalnızca işaretlenir.
- Her yazma kısa, eşzamanlı bir işlemdir; işlem içinde `await` yok. Arayüzün göreceği olay bu dilimde yazılmaz (yazan akış adımı yok); `record` olay yazmaz.

- [ ] **Tests first**, her kural için bir test: kod alanları sözlükten dolar; bilinmeyen kod `KeyError` ve satır yok; ikinci karar birinciyi kapatır ve `history` ikisini sırayla verir; aynı adımın aynı kararı tek satır; insan kararından sonra kod kararı `HumanDecisionStands`, insan kararı ise yazılır; `undo_human` önceki kararı geri getirir; protokol olmadan `protocol_hash` ve `criterion_hash` `NULL`; kapsam revizyonu değişince `is_stale` `True`; öneri ve sıra yazımı tekrarında satır sayısı değişmez.

## Task 4: deriving `selections`

**Files:** Modify `workflow/decisions.py`. Test: `tests/test_stage_decisions.py`.

```python
def work_outcome(self, research_id: str, work_id: str) -> dict[str, Any]: ...   # {"stage", "outcome", "reason_code", "decided_by", "source_version_id"} or {}
def derive_selection(self, research_id: str, work_id: str) -> str | None: ...   # the state written, or None when nothing was written
```

`work_outcome`, işin bu araştırmadaki (kaldırılmamış) sürümlerinin güncel kararlarını birleştirir (SW9.4, SW1.7):

1. Herhangi bir sürümde güncel **tam metin** kararı varsa sonuç tam metin aşamasından gelir: insan kararı varsa en yenisi; yoksa `include` ve `criterion_not_met` aynı işte birlikte görülüyorsa `unresolved` (neden kodu `fulltext_runs_disagree` **kullanılmaz**; dönen sözlükte `reason_code = "versions_disagree"` ve `decided_by = "code"` yazılır, satır saklanmaz); yoksa `include` > `criterion_not_met` > `unresolved`.
2. Yoksa **özet** aşaması: herhangi bir sürüm `candidate` ise `candidate`; karar verilmiş bütün sürümler `out_of_scope` ise `out_of_scope`; aksi halde `unresolved`. Bir sürümdeki işaret işi düşürmez.
3. Hiç karar yoksa `{}`.

`derive_selection`:

- Araştırmanın güncel kapsamı `search_workflow != 'sw'` ise hiçbir şey yazmaz, `None` döner.
- Hedef satır işin başıdır (`store.work_heads(research_id)[work_id]`); baş yoksa `None`.
- Eşleme: `include` → `included`; `criterion_not_met` ve `out_of_scope` → `excluded`; `candidate` ve `unresolved` → `pending`.
- Hedefin `origin`'i `user` ise `state` değişmez, `None` döner.
- Durum zaten aynıysa ve `origin` zaten `code_rule` ise hiçbir şey yazılmaz.
- Aksi halde `apply_screening_proposal`'ın yaptığı üç şey aynı işlemde yapılır (`store.py` ~1690): `selections` güncellenir (`state`, `origin = 'code_rule'`, `version + 1`, `updated_at`), `selection_history` satırı eklenir (`origin = 'code_rule'`, `reason` = neden kodu), `store._bump_selection_revision(research_id, old_state, new_state)` çağrılır. `proposal*` sütunlarına dokunulmaz.

- [ ] **Tests first:** `legacy` araştırmada hiçbir şey yazılmaz; `sw` araştırmada `all_parts_verified` başı `included` / `code_rule` yapar, geçmişe neden kodu yazılır ve `selection_revision` artar; kullanıcı `excluded` dediyse `include` kararı durumu değiştirmez; ön baskı `candidate`, yayımlanmış kayıt `out_of_scope` ise iş `pending` kalır; bir sürüm `include` diğeri `criterion_not_met` ise iş `pending` ve `work_outcome` `versions_disagree` der; ikinci kez türetme yeni geçmiş satırı yazmaz; `criterion_not_met` → `excluded` ama `work_outcome` hâlâ `criterion_not_met` verir (SW11.2: bu işler "kapsam dışı" değildir, raporda ayrı grup olarak kalır; ayrım `selections`'tan değil karar satırından okunur).

## Task 5: permanent deletion

**Files:** Modify `store.py`. Test: `tests/test_stage_decisions.py` ya da mevcut kalıcı silme testlerinin dosyası (`grep -rn "purge" tests/*.py`).

`purge_research` (~243) ve `purge_sources` (~1586, D65) silme listelerine üç yeni tablo eklenir; sıra yabancı anahtarlara uymalı (`model_proposals` ve `record_signal_ranks` `run_steps`'e, `model_proposals` `passages`'a bakar; bu satırlar `run_steps` ve `passages`'tan **önce** silinir). `purge_sources` yalnızca o kaynakların satırlarını siler.

- [ ] **Tests first:** kararı, önerisi ve sırası olan bir araştırma kalıcı silinebilir; kararı olan, araştırmadan kaldırılmış bir kaynak kalıcı silinebilir ve diğer kaynakların kararları durur.

## Task 6: replay stage

`tests/determinism_stages.py`'deki `STAGES` sözlüğüne `work_outcome` eklenir: sabit bir SYNTHETIC karar kümesi (üç iş, karışık sürüm kararları) karıştırılmış sırayla geçici bir veritabanına yazılır, her iş için `work_outcome` alınır, sonuç `canonical_rows` ile özetlenir. `tests/test_determinism.py` değişmeden onu da koşturmalı.

## Task 7: close the slice

- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; temel ve son sayılar. Bilinen tek başarısızlık: `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
- [ ] `git diff --check`
- [ ] `docs/decisions.md` en üste `## D<NN> — Store one decision per record and stage with a reason code, and derive the selection an answer reads from it` (numarayı kontrol et). Limits şunları adıyla söylemeli: hiçbir akış adımı bu tabloları henüz yazmıyor, yani üründe gözlenen davranış değişmedi; neden kodları SW11'in çalışma adlarıdır; `criterion_not_met` `selections`'ta `excluded` olarak görünür ve ayrımı bugün hiçbir görünüm göstermiyor; konuya özgü özellik satırları (SW9.5) ve geniş dışa aktarım tablosu yapılmadı; sürümler arası çelişki `pending` bırakılır ve hiçbir yerde gösterilmez; arayüz tipi (`apps/web/src/api.ts:117`, `origin`) `code_rule`'u henüz tanımıyor ve ilk yazan dilimde genişletilmeli; testler SYNTHETIC girdiyle koşar.
- [ ] SW belgesinde SW9 ve SW11 **Status** satırlarına birer cümle: hangi maddelerin saklama kısmı `D<NN>` ile uygulandı, yazan adımların olmadığı.
- [ ] `sw-status.md` satır 02: `uygulandı, inceleme bekliyor` + açık kalanlar.

## Son ileti

Değişen ve eklenen dosyalar; temel ve son test sayıları ve komut; `selections` yeniden kurulumunda neyin korunduğunu nasıl doğruladığın; bu dosyada yazıldığı gibi yapılamayan her şey; yapmadıkların; dokunulan kanıt sınırları (beklenen: seçim mantığı, yalnızca `sw` araştırmalarında ve yalnızca yeni işlev çağrılırsa); canlı servise dokunulmadığı ve hiçbir şeyin commit'lenmediği.

## Açık noktalar

- `criterion_not_met` → `excluded` eşlemesi `selections`'ın üç durumuna sığdırmak içindir. Raporda ve kaynak listesinde bu işlerin ayrı grup olarak görünmesi (SW11.2) dilim 12 ve 20'nin işidir ve karar satırından okunur.
- Derleme işaretli kayıt (SW5.4, SW9.3) üç özet sonucundan hangisini alır: SW metni "aday listesinden çıkar, tohum havuzuna girer" der ama bir sonuç adı vermez. Dilim 05'te sahibe sorulacak; bu yüzden kod bu dilimde yok.
- İnsan kararı bu dilimde yalnızca tam metin aşaması için kodlanmıştır (SW11.4: kuyruk tam metin aşamasına aittir). Kullanıcının özet aşamasında "kendi kararını her an kaydedebilmesi" (SW11.9) bugünkü `set_user_selection` ile karşılanır ve `selections.origin = 'user'` olarak kalır.
- `undo_human`'ın "önceki kararı yeni satır olarak geri getirme" davranışı SW11.7'nin "geri alınabilir" sözünün bir yorumudur; SW metni ayrıntı vermez.
