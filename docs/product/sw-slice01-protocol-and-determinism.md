# SW dilim 01 — Protokol kaydı ve belirlenimcilik: uygulama planı

**Tarih:** 20 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları bu dilim için de geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md), SW14 (madde 1–7).

**Goal:** Bugün bir araştırmanın "hangi kurallarla arandı" sorusuna tek bir kayıt cevap vermiyor: adım satırında yalnızca `skill_package_hash` var, adım girdisinin, model çıktısının ve sağlayıcı yükünün özeti yok, `fuse_rankings` puan eşitliğini argüman sırasıyla bozuyor (`workflow/flow.py:79-87`). Bu dilim (a) ilk sağlayıcı isteğinden önce dondurulan, özetlenen ve değiştirilemeyen bir protokol kaydı ekler, (b) sonraki her adım satırına o özeti yazar, (c) adım girdisi, model çıktısı ve sağlayıcı yükü için kanonik özet saklar, (d) karara ya da kesime giren sıralamalarda eşitliği kalıcı kimlikle bozar, (e) bunu iki hash tohumu ve karışık satır sırasıyla sınayan bir tekrar testi ekler. Arayüz değişmez.

**Architecture:** Protokol kaydı yeni bir tablodur ve mevcut adım mekanizmasına oturur: `_discovery` içinde, sorgular derlendikten sonra ve ilk `_search` çağrısından önce `operation_key = "protocol"` olan bir adım koşar. Adım `succeeded` ise saklı çıktısı döner; böylece duraklat / sürdür aynı özeti verir. Kanonik biçim tek bir modüldedir (`domain/canonical.py`); ürünün başka hiçbir yeri kendi özetini üretmez.

**Tech stack:** Python 3.12, SQLite (tek bağlantı, kısa eşzamanlı işlemler; işlem içinde `await` yok), `hashlib`, `json`. Yeni bağımlılık yok.

## Global constraints

- Bu dilim sözleşme (`contracts/research/*.schema.json`) ve yöntem paketi değiştirmez; `skill_package_hash` değişmez. Değiştirmen gerekiyorsa dur ve sor.
- Bu dilim `apps/web` altına dokunmaz.
- Migration numarası bu not yazılırken `0037`'dir; başlamadan önce `ls backend/deixis/storage/migrations | tail -1` ile kontrol et. Eski migration düzenlenmez.
- `step_inputs` satırları değiştirilemez (UPDATE ve DELETE tetikleyicileri). Özet sütunu INSERT anında doldurulur.
- `legacy` akışının gözlenen davranışı yalnızca iki yerde değişebilir: puanı eşit pasajların sırası ve puanı eşit kaynakların sırası. Başka bir test beklentisi değişiyorsa dur ve sor.
- `Settings.search_workflow` bu dilimde yalnızca saklanır ve protokole yazılır; hiçbir dallanma ona bakmaz.
- Git durumunu değiştirme (commit, push, stash yok).

## Dosya yapısı

Yeni dosyalar:
- `backend/deixis/storage/migrations/0037_protocol_records.sql`
- `backend/deixis/domain/canonical.py` — kanonik JSON ve SHA-256
- `backend/deixis/workflow/protocol.py` — protokol gövdesini kuran saf işlev
- `tests/test_canonical.py`, `tests/test_protocol_record.py`, `tests/test_determinism.py`
- `tests/determinism_stages.py` — tekrar testinin alt süreçte koşturduğu aşamalar

Değişecek dosyalar:
- `backend/deixis/config.py` — `search_workflow` ayarı
- `backend/deixis/workflow/store.py` — protokol işlevleri; `step()` özeti yazar; `insert_step_input`, `finish_model_session`, `add_search_run` özet yazar; `create_research` akışı saklar
- `backend/deixis/workflow/flow.py` — `protocol` adımı; `fuse_rankings` ve `answer_source_order` eşitlik bozma; yük özeti
- `backend/deixis/api/app.py` — araştırma oluştururken `settings.search_workflow` aktarılır
- `backend/deixis/workflow/views.py` — koşu görünümüne `protocol_hash`
- `docs/decisions.md`, `docs/product/search-workflow-review-2026-09-18.md` (SW14 durum satırı), `docs/product/sw-status.md`

## Task 1: canonical form and hashing

**Files:** Create `backend/deixis/domain/canonical.py`, `tests/test_canonical.py`.

**Interfaces — produces:**

```python
def canonical_json(value: Any) -> str: ...
def sha256_hex(value: Any) -> str: ...          # sha256 of canonical_json(value).encode("utf-8")
def canonical_rows(rows: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]: ...
def unordered_pair(a: str, b: str) -> tuple[str, str]: ...
```

Kurallar (SW14.4): anahtarlar sıralı, ayırıcılar boşluksuz (`separators=(",", ":")`), `ensure_ascii=False`, metinler NFC; `set` ve `frozenset` sıralı listeye çevrilir; `tuple` liste olur; `NaN` ve sonsuz `ValueError` verir; `canonical_rows` satırları `key` alanına göre sıralar ve `key` eksikse `KeyError` verir; `unordered_pair` iki kimliği sıralı döndürür. Ham bayt özeti denetim için kullanılmaz.

- [ ] **Step 1: failing tests.** Anahtar sırası farklı iki sözlük aynı özeti verir; satır sırası farklı iki liste `canonical_rows` sonrası aynı özeti verir; `{"b", "a"}` ile `["a", "b"]` aynı; NFC ve NFD yazılmış "ü" aynı; `float("nan")` hata; `unordered_pair("b", "a") == ("a", "b")`.
- [ ] **Step 2: implement.**
- [ ] **Step 3:** `PYTHONPATH=backend:. uv run pytest tests/test_canonical.py -q`

## Task 2: migration and the workflow setting

**Files:** Create `0037_protocol_records.sql`. Modify `config.py`, `store.py` (`create_research`), `api/app.py`. Test: `tests/test_protocol_record.py`, `tests/test_migrations.py` (mevcut kalıba bir satır).

```sql
CREATE TABLE protocol_records (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  protocol_revision INTEGER NOT NULL,
  reason TEXT,
  body_json TEXT NOT NULL,
  body_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (research_id, protocol_revision)
);
CREATE INDEX protocol_records_scope ON protocol_records(research_id, scope_revision, protocol_revision);
CREATE TRIGGER protocol_records_no_update BEFORE UPDATE ON protocol_records
BEGIN SELECT RAISE(ABORT, 'protocol_records are immutable'); END;
CREATE TRIGGER protocol_records_no_delete BEFORE DELETE ON protocol_records
BEGIN SELECT RAISE(ABORT, 'protocol_records are immutable'); END;

ALTER TABLE scope_revisions ADD COLUMN search_workflow TEXT NOT NULL DEFAULT 'legacy' CHECK (search_workflow IN ('legacy', 'sw'));
ALTER TABLE run_steps ADD COLUMN protocol_hash TEXT;
ALTER TABLE step_inputs ADD COLUMN payload_sha256 TEXT;
ALTER TABLE model_sessions ADD COLUMN output_sha256 TEXT;
ALTER TABLE search_runs ADD COLUMN payload_sha256 TEXT;
```

`protocol_revision` araştırma içinde 1'den artar; bir kapsam revizyonunun birden çok protokol revizyonu olabilir (dilim 08 dağarcık onayında bunu kullanacak). `reason` ilk kayıtta `NULL`, sonrakilerde zorunlu.

`config.py`: `search_workflow: str = "legacy"`; `DEIXIS_SEARCH_WORKFLOW` okunur, `legacy` ya da `sw` değilse `ValueError` (`query_strategy` kalıbı, `config.py:84-86`). `create_research` yeni `search_workflow: str = "legacy"` parametresi alır ve `scope_revisions`'a yazar; `seed_mode` için yapılan "sütun var mı" koruması (`store.py:148-152`) bunun için de yapılır, çünkü geçmiş migration testleri 0037'den önce `Store` kurar. `revise_scope` ve ikinci kapsam ekleme yolu satırı bütün olarak kopyaladığı için değeri kendiliğinden taşır; bunu testle doğrula. `api/app.py` araştırma oluştururken `settings.search_workflow`'u geçirir.

- [ ] **Step 1: failing tests.** Migration uygulanır ve sütunlar vardır; `protocol_records` UPDATE ve DELETE `sqlite3.IntegrityError` verir; `DEIXIS_SEARCH_WORKFLOW=bogus` ile `load_settings()` hata verir; `sw` ile açılan araştırmanın kapsamı `search_workflow == "sw"` döner ve `revise_scope` sonrası da öyle kalır.
- [ ] **Step 2: implement.**
- [ ] **Step 3:** `PYTHONPATH=backend:. uv run pytest tests/test_protocol_record.py tests/test_migrations.py -q`

## Task 3: the protocol body and its step

**Files:** Create `backend/deixis/workflow/protocol.py`. Modify `store.py`, `flow.py`. Test: `tests/test_protocol_record.py`, `tests/test_provider_flow.py`.

**Interfaces — produces:**

```python
# workflow/protocol.py
PROTOCOL_SCHEMA = "deixis.protocol.v1"
def build_protocol(scope: dict[str, Any], budget: dict[str, Any], plan: dict[str, Any] | None, queries: list[dict[str, Any]],
                   skill_package_hash: str, settings: Settings) -> dict[str, Any]: ...

# workflow/store.py
def freeze_protocol(self, research_id: str, scope_revision: int, body: dict[str, Any], reason: str | None = None) -> dict[str, Any]: ...
def current_protocol(self, research_id: str, scope_revision: int) -> dict[str, Any] | None: ...
```

`build_protocol` saftır (saat, rastgelelik, ağ yok). Gövde, SW14.1'in çalışma listesidir; bugün olmayan alanlar `None` yazılır ve sonraki dilimler doldurur:

| Alan | Bu dilimde değer |
|---|---|
| `schema` | `deixis.protocol.v1` |
| `search_workflow` | kapsamdan |
| `question`, `steering`, `language_hint`, `source_scope`, `seed_mode` | kapsamdan |
| `inclusion_criterion`, `criterion_parts`, `cue_phrases`, `exclusion_title_words` | `None` (dilim 06) |
| `concept_blocks`, `claim_words`, `exclusion_words` | `None` (dilim 04) |
| `vocabulary` | planın `concepts` listesi (etiket, rol, eş anlamlılar); plan yoksa `None` |
| `compiled_queries` | `provider_id`, `query_text`, varsa `results` |
| `providers` | kapsamın sağlayıcı listesi, sıralı |
| `arms` | `["keyword_search"]` |
| `signals` | `[]` (dilim 07) |
| `thresholds` | `screening_batch`, `max_abstract_chars`, `rrf_k`, `chunk_chars`, `max_passages_per_source`, `pdf_pages_per_source`, `formulation_score_threshold`; değerler sabitlerden okunur, elle yazılmaz |
| `rule_table_version` | `"legacy"` |
| `budget` | koşunun `budget` sözlüğü |
| `models` | adım rolü başına `{connection, model, reasoning_effort}`: araştırma, literatür, gözden geçirme (`domain/rules.py::step_model`, `effective_reviewer`) |
| `skill_package_hash` | paketten |
| `code_version` | `importlib.metadata.version("deixis")` + `query_compiler` sürüm metni |
| `query_strategy` | ayardan |

`freeze_protocol`: aynı kapsam revizyonunun son kaydının özeti yeni gövdenin özetine eşitse yeni satır yazmaz, var olanı döndürür; farklıysa `reason` zorunludur (`ValueError`), `protocol_revision` bir artar. Kayıt ve `protocol_frozen` olayı (`{"protocol_revision", "protocol_hash"}`) aynı işlemde yazılır. Dönen sözlük: `id`, `protocol_revision`, `body`, `hash`.

`flow._discovery`: sorgular derlenip adım çıktısına yazıldıktan sonra (`flow.py:229-242`), `_search` döngüsünden önce:

```python
step = self.store.step(run_id, "protocol", "protocol:freeze")
if step["status"] != "succeeded":
    self.store.start_step(step["id"])
    record = self.store.freeze_protocol(rid, revision, protocol.build_protocol(...))
    self.store.finish_step(step["id"], "succeeded", output={"protocol_revision": ..., "protocol_hash": ...})
```

`store.step()`: yeni bir adım satırı açarken, koşunun araştırması ve kapsam revizyonu için `current_protocol` varsa `protocol_hash`'i INSERT'e koyar. `protocol` adımının kendisi ve ondan önce açılan `search_plan` adımı `NULL` kalır; bu beklenen davranıştır ve testle sabitlenir. Yanıt koşusu aynı kapsam revizyonunun protokol özetini taşır. `source_scope == "attached"` araştırmalarda keşif koşmaz, protokol kaydı olmaz, özet `NULL` kalır (bkz. Açık noktalar).

`"protocol:freeze"` türünü `store.py:31`'deki `STEP_OUTPUT_KINDS` demetine ekle ki küçük çıktısı koşu görünümüne taşınsın; `views.py` koşu görünümüne `protocol_hash` alanını ekler (arayüz bunu göstermez).

- [ ] **Step 1: failing tests.**
  - Bir keşif koşusundan sonra tam bir `protocol_records` satırı vardır; `body_sha256 == sha256_hex(json.loads(body_json))`.
  - `protocol` adımı, ilk `provider_search:*` adımından önce sıralanır (`run_steps` rowid).
  - `search:*`, `screening*` ve sonraki yanıt koşusunun adımları aynı `protocol_hash`'i taşır; `search_plan` adımınınki `NULL`'dır.
  - Duraklatılıp sürdürülen koşu ikinci bir protokol satırı yazmaz.
  - `freeze_protocol` farklı gövde ve `reason=None` ile `ValueError` verir; `reason` ile `protocol_revision == 2` yazar.
  - `build_protocol` aynı girdiyle iki kez çağrıldığında aynı özeti verir; `thresholds` değerleri `rules.SCREENING_BATCH` ve `flow` sabitleriyle eşittir.
- [ ] **Step 2: implement.**
- [ ] **Step 3:** `PYTHONPATH=backend:. uv run pytest tests/test_protocol_record.py tests/test_provider_flow.py tests/test_api_flow.py -q`

## Task 4: hashes of step inputs, model outputs and provider payloads

**Files:** Modify `store.py` (`insert_step_input`, `finish_model_session`, `add_search_run`), `flow.py` (`_search`). Test: `tests/test_protocol_record.py`.

- `insert_step_input`: `payload_sha256 = sha256_hex(payload)` INSERT'e eklenir.
- `finish_model_session`: `raw_output` alanı geldiyse ve `None` değilse `output_sha256` yazılır. Çıktı geçerli JSON ise ayrıştırılmış değerin kanonik özeti, değilse metnin NFC UTF-8 özeti alınır; hangisinin kullanıldığı özetin önüne `json:` ya da `text:` olarak yazılır.
- `_search`: yük dosyası yazıldığı yerde (`flow.py:368-371`) `sha256_hex(outcome.raw_payload)` hesaplanır ve `search_fields["payload_sha256"]` olarak geçer; yük yoksa `None`.
- İstenen ve yanıtlayan model zaten `model_sessions.requested_model` / `resolved_model` içindedir (SW14.3); yeni sütun gerekmez.

- [ ] **Step 1: failing tests.** Bir model adımından sonra `step_inputs.payload_sha256`, saklı `payload_json`'ın kanonik özetine eşittir; `model_sessions.output_sha256` `json:` ile başlar ve ham çıktının ayrıştırılmış özetine eşittir; JSON olmayan çıktı `text:` verir; `search_runs.payload_sha256`, diskteki yük dosyasının ayrıştırılmış özetine eşittir.
- [ ] **Step 2: implement.**
- [ ] **Step 3:** ilgili testler + `tests/test_api_flow.py`.

## Task 5: stable tie-breaking

**Files:** Modify `flow.py`. Test: `tests/test_semantic_retrieval.py`, `tests/test_determinism.py`.

- `fuse_rankings` (`flow.py:79-87`): sıralama anahtarı `(-scores[id], id)`. Eşit puanlı iki satırın sırası artık argüman sırasına bağlı değildir.
- `answer_source_order` (`flow.py:95-118`): son anahtar `position[s]` bugün girdi sırasıdır. `position` yerine kaynak kimliği kullanılmaz, çünkü "seçim sırası" D17'de ölçülmüş bir sinyaldir; bunun yerine `included` listesinin her çağrıda aynı sırada geldiği doğrulanır (`store.included_works` sorgusunun `ORDER BY`'ı). Sorguda kararlı bir sıralama yoksa eklenir ve `position`'dan sonra son anahtar olarak kimlik gelir.
- `flow.py` ve `providers/query_compiler.py` içinde bir `set`'in üzerinde dönülüp sonucu çıktıya ulaşan yer aranır (`grep -n "set(" `); bulunursa `sorted(...)` ile sabitlenir. Yalnızca üyelik denetimi için kullanılan kümelere (`heads`) dokunulmaz. Bulunan ve dokunulmayan her yer son iletide listelenir.
- SQLite FTS `bm25()` eşitliği: `store.search_passages` sorgusunun `ORDER BY`'ına ikinci anahtar olarak pasaj kimliği eklenir.

- [ ] **Step 1: failing tests.** `fuse_rankings(a, b)` ile `fuse_rankings(b, a)` aynı kimlik sırasını verir; eşit puanlı iki satır kimlik sırasıyla gelir.
- [ ] **Step 2: implement; sırası değişen mevcut test beklentilerini tek tek gözden geçir.** Yalnızca eşitlikten doğan sıra farkı kabul edilir; başka bir fark varsa dur.
- [ ] **Step 3:** `PYTHONPATH=backend:. uv run pytest tests/test_semantic_retrieval.py tests/test_api_flow.py -q`

## Task 6: replay check

**Files:** Create `tests/determinism_stages.py`, `tests/test_determinism.py`.

`determinism_stages.py` bir `STAGES: dict[str, Callable[[list], Any]]` sözlüğü ve `python -m`/betik girişi taşır: aşama adı ve satır karıştırma tohumu alır, sabit SYNTHETIC girdiyi o tohumla karıştırır, aşamayı koşar ve `sha256_hex(canonical(...))` yazar. Bu dilimdeki aşamalar: `compile_queries`, `chunk_page`, `fuse_rankings`, `answer_source_order`, `build_protocol`. Sonraki her dilim kendi kod aşamasını bu sözlüğe ekler (ana plan §2.9).

`test_determinism.py`: her aşamayı `subprocess.run([sys.executable, ...], env={..., "PYTHONHASHSEED": seed})` ile `seed ∈ {"1", "2"}` × karıştırma ∈ {yok, 1, 2} koşullarında çalıştırır ve altı özetin eşit olduğunu doğrular (SW14.7). Alt süreç `PYTHONPATH=backend` ile koşar.

- [ ] **Step 1: write the test; it must fail for `fuse_rankings` before Task 5 and pass after.** Bunu son iletide doğrula (Task 5'i geri alıp koşmana gerek yok; Task 5'ten önce yazıp kırmızı gördüysen söyle).
- [ ] **Step 2:** `PYTHONPATH=backend:. uv run pytest tests/test_determinism.py -q`

## Task 7: close the slice

- [ ] `PYTHONPATH=backend:. uv run pytest` — tamamı. Başlamadan önceki temel sayıyı ve bittikten sonraki sayıyı yaz.
- [ ] `git diff --check`
- [ ] `grep -n '^## D' docs/decisions.md | head -3` ile sıradaki numarayı bul ve en üste şu girişi taslakla (İngilizce; Status / Date / Context / Decision / Limits): `## D<NN> — Freeze and hash one protocol record per research before the first search, and break ranking ties by a stable identifier`. Limits şunları adıyla söylemeli: protokol gövdesinin ölçüt, blok ve sinyal alanları henüz boş; ekli-PDF araştırmalarında kayıt yok; gömme vektörleri makineler arası yeniden hesaplanmadı; FTS eşitliği yalnızca ikinci anahtarla sabitlendi, ayrıca ölçülmedi; testler SYNTHETIC girdiyle koşar ve iş akışı davranışını gösterir.
- [ ] `search-workflow-review-2026-09-18.md` SW14 **Status** satırına ekle: `Points 1–7 implemented in D<NN> (2026-09-..); the protocol body's criterion, block and signal fields are filled by later slices.` Girişin geri kalanına dokunma.
- [ ] `sw-status.md`'de 01 satırını "uygulandı, inceleme bekliyor" yap ve açık kalanları yaz.

## Son ileti

Şunları içermeli: değişen ve eklenen dosyalar; temel ve son test sayıları; sırası değişen her mevcut test beklentisi ve nedeni; `set` taramasında bulunan yerler ve her biri için yapılan; bu dosyada yazıldığı gibi yapılamayan her şey; **yapmadıkların**; canlı servise (8765) dokunulup dokunulmadığı; hiçbir şeyin commit'lenmediği.

## Açık noktalar

- `code_version` yalnızca paket sürümüdür (`0.1.0`) ve her commit'te değişmez; SW14.5'in "aynı kod sürümü" koşulunu zayıf karşılar. Git commit özeti paketlenmiş masaüstü sürümünde bulunmayacağı için bu dilimde eklenmedi; dilim 24'ten önce karara bağlanmalı.
- Ekli-PDF araştırmalarında (`source_scope = attached`) keşif koşmadığı için protokol kaydı yazılmaz. SW14 "ilk aramadan önce" der; yanıt koşusunun da bir protokolü olmalı mı sorusu sahibe aittir.
- `search_plan` model adımı protokolden önce koşar, çünkü `legacy` akışta dağarcık ondan gelir. `sw` akışında (dilim 04, 06, 08) sıra değişecek: dağarcık ve ölçüt onaylanır, sonra protokol dondurulur.
- `protocol_revision`'ın kapsam revizyonuyla ilişkisi (dağarcık onayı yeni kapsam revizyonu mu açar, yalnızca protokol revizyonu mu) dilim 08'de karara bağlanır; tablo ikisine de izin verir.
