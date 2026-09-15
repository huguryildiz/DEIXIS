# P5 dilim 1 — Kanıt tablosu çekirdeği: tasarım notu

**Tarih:** 16 Eylül 2026. **Durum:** §9'daki sorular sahibin isteğiyle Claude tarafından yanıtlandı ([D37](../decisions.md)). Modelsiz ilk alt adım uygulandı: `0019`/`0020` migration'ları, `workflow/tables.py` ve API. SQL'in geçerli hali migration dosyalarıdır; aşağıdaki taslaktan küçük farkları vardır. Örneğin `not_verified`, kanıtı olmayan bir değer taşır. İkinci alt adım da uygulandı ([D38](../decisions.md)): `EvidenceCellDraft` v1 ve `TableColumnProposal` v1, `cell_extraction` ve `table_columns` adımları, doldurma, recheck ve sütun önerisi run'ları ile uçları. Buradaki taslaktan farklar: doldurma da tablonun `expected_version` değerini ister; doldurma planı (kaynaklar, sütunlar, hücre sürümleri) run'ın `target_json` alanında saklanır; recheck hedefi `cell_id` yerine sütun ve kaynak sürümüyle yazılır; verilen pasaj sayısı ve "bütün sayfalar verildi" bilgisi adım çıktısında değil StepInput'un `extraction_target.passage_scope` alanındadır; sınırı aşan kaynakta eşleşen pasajlardan sonra kalan yer sayfa sırasıyla doldurulur. Arayüz ve gerçek model denemesi henüz yok.

**Kısaca:** Bir araştırmanın içinde tablo açılır. Sütunlar talimat ve yanıt biçimi taşır. Satırlar tabloya açıkça eklenen kaynak sürümleridir; tablo, açıldığı anda dahil edilen kaynaklarla başlar. Her hücre değişmez revizyonlar dizisidir ve bir işaretçi "geçerli" revizyonu gösterir. Model yalnız boş hücreyi doldurabilir. "Recheck this cell" ise her zaman bekleyen bir öneri üretir; geçerli değeri yalnız kullanıcının kabulü değiştirir. İnsan yazıları beklenen hücre sürümünü denetler, bu yüzden eski ekran yeni düzenlemeyi ezemez. Model işleri mevcut run/step/StepInput hattından geçer; böylece duraklatma, yeniden başlatma, bütçe ve idempotency yeniden yazılmaz.

## 1. Kodda zaten olanlar

| Parça | Doğrulanan durum | Dilim 1'de kullanımı |
|---|---|---|
| `works` / `source_versions` / `source_assets` / `passages` | Pasaj metni trigger ile değişmez; `extraction_version` sütunu var; başka sürüm ayrı `source_version` (D6) | Satır anahtarı `source_version_id`; kanıt gerçek `passages` kaydına bağlanır |
| `corpus_memberships`, `selections` (`version`, `origin`) | Kullanıcı seçimi model önerisinden üstün; `expected_version` ile 409 | Satır yalnız araştırmanın kendi kaynağı olabilir; ilk satırlar dahil edilenlerden gelir; "model yalnız boşu doldurur" deseni buradan |
| `runs` / `run_steps` / `step_inputs` / `model_sessions`, `Worker.recover` | Adım anahtarıyla devam, yarım adım `outcome_unknown`, `runs.idempotency_key UNIQUE` | Sütun önerisi, doldurma ve recheck üç yeni run türü olur |
| `contracts`: kısa kimlik etiketleri (D12), `locate_anchor`, tek onarım | Yanıt adımı için çalışıyor | Hücre çıktısına genelleştirilir |
| `PassageSheet` + `PdfViewer` (`initialPage`, vurgu) | Düz metin/PDF geçişi, bulunan alıntı vurgusu (D27) | "Show evidence" aynı paneli açar |
| `remove_asset` | Dosya `removed_at` alır, pasajlar kalır | Eski hücre kanıtı çözülmeye devam eder; hücrede "PDF çekildi" işareti |
| Araştırma çöp kutusu (`trashed_at`, purge yetkisi, 0010) | Var | `purge_research` silme listesine yeni tablolar eklenmeli |
| Crossref, arXiv, Semantic Scholar bağlantıları | D13 ile var | Plandaki P5 bağlantı işi zaten yapılmış; dilim 1'de iş yok |
| `deixis backup` / `restore` | SQLite backup API; bütün tablolar | Yeni tablolar kendiliğinden girer; test ile doğrulanır |

**Olmayanlar:** tablo, sütun ve hücre kayıtları; Annotation; kaynak ve tablo için TrashEntry; koleksiyon ve etiket; meta veri düzeltmesi; OCR; run dışındaki oluşturma işlemleri için idempotency.

**Dilim 2 için not:** `_insert_passage` tekrar denetiminde `extraction_version` yok. Yeni çıkarımda aynı metin eski pasaj kimliğini ve eski sürüm etiketini geri döndürür. `upload_to_source` ikinci dosyayı yan yana ekler; "değiştirme" kavramı yok.

## 2. Veri modeli ve migration taslağı

Kurallar:

- Tablo araştırmaya aittir, çünkü RAG yalnız aktif araştırmada çalışır (§2).
- Hücre `(column, source_version)` çiftidir. Aynı yayının iki sürümü iki ayrı satırdır ve kanıt birinden ötekine geçmez (T03 ön koşulu).
- Satırlar `table_rows` tablosunda açıkça tutulur (§9, karar 1). Satır çıkarmak hücreleri silmez; kaynak seçimindeki değişiklik tabloyu küçültmez.
- Sütun tanımı revizyonludur. Hücre revizyonu hangi sütun revizyonuyla üretildiğini taşır; talimat değişince eski değer silinmez, `stale_column` olarak görünür.
- Hücre revizyonları ve kanıt bağları eklenir, değiştirilmez. Silmeye yalnız araştırmanın kalıcı silinmesinde izin verilir.
- `evidence_cells.version` yalnız geçerli revizyonu ya da bekleyen öneri kararını değiştiren yazılarda artar.

**0019 — run türleri.** Sorun: SQLite bir CHECK kısıtını yerinde değiştiremez, `runs` tablosuna da altı tablo foreign key ile bağlıdır. SQLite'ın belgelediği 12 adımlı yeniden kurma yolu `foreign_keys=OFF` ister. `db.migrate` her dosyayı `foreign_keys=ON` ve bir işlem içinde çalıştırdığından küçük bir kod değişikliği gerekir. Dosyanın ilk satırında `-- deixis:foreign-keys-off` varsa pragma işlem dışında kapatılır, `PRAGMA foreign_key_check` commit öncesi işlem içinde çalışır, ardından pragma yeniden açılır.

```sql
-- deixis:foreign-keys-off
CREATE TABLE runs_new (
  id TEXT PRIMARY KEY,
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('discovery', 'answer', 'table_columns', 'table_fill', 'cell_recheck')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'pause_requested', 'paused', 'completed', 'failed', 'cancelled')),
  stage TEXT NOT NULL CHECK (stage IN ('intake', 'discovery', 'screening', 'inspection', 'answer', 'extraction',
                                       'synthesis', 'candidate', 'claim_check', 'export')),
  pause_reason TEXT, error_json TEXT,
  budget_json TEXT NOT NULL, usage_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT UNIQUE,
  target_json TEXT,  -- table runs: {"table_id", "column_ids", "cell_id", "include_stale"}
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
INSERT INTO runs_new (id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
                      usage_json, idempotency_key, version, created_at, updated_at)
  SELECT id, research_id, scope_revision, kind, status, stage, pause_reason, error_json, budget_json,
         usage_json, idempotency_key, version, created_at, updated_at FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE INDEX runs_status ON runs(status, created_at);
```

**0020 — tablolar.**

```sql
CREATE TABLE table_templates (
  id TEXT PRIMARY KEY,                -- tpl_
  name TEXT NOT NULL,
  columns_json TEXT NOT NULL,         -- [{name, instruction, answer_format, options, allow_multiple, unit_hint}]
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL, trashed_at TEXT
);

CREATE TABLE evidence_tables (
  id TEXT PRIMARY KEY,                -- tbl_
  research_id TEXT NOT NULL REFERENCES researches(id),
  title TEXT NOT NULL,
  template_id TEXT REFERENCES table_templates(id),
  version INTEGER NOT NULL DEFAULT 1,
  idempotency_key TEXT UNIQUE,
  trashed_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE table_rows (
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),  -- a corpus member of the table's research (checked in code)
  added_by TEXT NOT NULL CHECK (added_by IN ('included_at_creation', 'user')),
  created_at TEXT NOT NULL,
  removed_at TEXT,                    -- removing a row keeps its cells; adding it again clears this
  PRIMARY KEY (table_id, source_version_id)
);

CREATE TABLE table_columns (
  id TEXT PRIMARY KEY,                -- col_
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  position INTEGER NOT NULL,
  current_revision INTEGER NOT NULL DEFAULT 1,
  origin TEXT NOT NULL CHECK (origin IN ('user', 'model_suggestion', 'template')),
  suggestion_step_id TEXT REFERENCES run_steps(id),
  version INTEGER NOT NULL DEFAULT 1,
  removed_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE column_revisions (
  column_id TEXT NOT NULL REFERENCES table_columns(id),
  revision INTEGER NOT NULL,
  name TEXT NOT NULL,                 -- short name
  instruction TEXT NOT NULL,          -- written as for a human annotator
  answer_format TEXT NOT NULL CHECK (answer_format IN ('choice', 'number_unit', 'yes_no', 'text')),
  options_json TEXT,                  -- choice: [{"id": "o1", "label": "..."}]
  allow_multiple INTEGER NOT NULL DEFAULT 0,
  unit_hint TEXT,                     -- number_unit: the unit the user expects; nothing is converted
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  PRIMARY KEY (column_id, revision),
  CHECK (answer_format <> 'choice' OR options_json IS NOT NULL)
);

CREATE TABLE evidence_cells (
  id TEXT PRIMARY KEY,                -- cel_, created with its first revision
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  column_id TEXT NOT NULL REFERENCES table_columns(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  current_revision_id TEXT REFERENCES cell_revisions(id),
  version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (column_id, source_version_id)
);

CREATE TABLE cell_revisions (
  id TEXT PRIMARY KEY,                -- crv_
  cell_id TEXT NOT NULL REFERENCES evidence_cells(id),
  kind TEXT NOT NULL CHECK (kind IN ('model_fill', 'model_proposal', 'system_fill',
                                     'human_edit', 'accept_proposal', 'dismiss_proposal')),
  author TEXT NOT NULL CHECK (author IN ('model', 'human', 'system')),
  based_on_revision_id TEXT REFERENCES cell_revisions(id),   -- accept/dismiss: the proposal; human_edit: the revision corrected
  column_revision INTEGER NOT NULL,
  state TEXT CHECK (state IN ('value', 'unknown', 'not_reported', 'not_verified', 'not_applicable',
                              'inaccessible', 'not_found_in_inspected_scope')),
  value_json TEXT,  -- choice {"option_ids"}, number_unit {"number", "unit", "as_stated"}, yes_no {"answer": "yes"|"no"}, text {"text"} (≤ 500 chars)
  note TEXT,        -- model reason or human note
  reading_depth TEXT CHECK (reading_depth IN ('metadata', 'abstract', 'selected_sections', 'full_text')),
  output_status TEXT CHECK (output_status IN ('structurally_valid', 'unverified_draft')),
  cell_version_at_request INTEGER,    -- model rows: the cell version the request saw
  scope_revision INTEGER,
  run_id TEXT REFERENCES runs(id), step_id TEXT REFERENCES run_steps(id), step_input_id TEXT REFERENCES step_inputs(id),
  model_connection TEXT, resolved_model TEXT,
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  CHECK ((kind IN ('model_fill', 'model_proposal')) = (author = 'model')),
  CHECK (author <> 'model' OR (step_input_id IS NOT NULL AND output_status IS NOT NULL)),
  CHECK (kind <> 'system_fill' OR (author = 'system' AND state = 'inaccessible')),
  CHECK (kind NOT IN ('human_edit', 'accept_proposal', 'dismiss_proposal') OR author = 'human'),
  CHECK (kind NOT IN ('accept_proposal', 'dismiss_proposal') OR based_on_revision_id IS NOT NULL),
  CHECK ((kind = 'dismiss_proposal') = (state IS NULL)),
  CHECK (state IS NULL OR (state IN ('value', 'not_verified')) = (value_json IS NOT NULL))
);
CREATE INDEX cell_revisions_cell ON cell_revisions(cell_id, created_at);

CREATE TABLE cell_evidence_links (
  cell_revision_id TEXT NOT NULL REFERENCES cell_revisions(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  step_input_id TEXT REFERENCES step_inputs(id),   -- the StepInput that gave the passage; kept when a proposal is accepted
  anchor_text TEXT,
  anchor_match TEXT CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy')),
  PRIMARY KEY (cell_revision_id, passage_id)
);

-- Evidence must come from the cell's own source version (never another version of the same work).
CREATE TRIGGER cell_evidence_same_source BEFORE INSERT ON cell_evidence_links
WHEN NEW.source_version_id <> (SELECT c.source_version_id FROM cell_revisions r JOIN evidence_cells c ON c.id = r.cell_id
                               WHERE r.id = NEW.cell_revision_id)
  OR NEW.source_version_id <> (SELECT source_version_id FROM passages WHERE id = NEW.passage_id)
BEGIN SELECT RAISE(ABORT, 'cell evidence must come from the cell source version'); END;
-- Plus no-update / no-delete triggers on cell_revisions, cell_evidence_links and column_revisions;
-- deletes pass only under research_purge_authorizations, as for step_inputs (0010).
```

**Okuma düzeyi (backend hesaplar):** Pasaj verilmediyse `metadata`, yalnız özet verildiyse `abstract`, herhangi bir PDF sayfası verildiyse `selected_sections` olur. Bu, mevcut kodun pasaj etiketiyle aynıdır. Dilim 1'de hiçbir hücre `full_text` almaz (§9, karar 5). "Çıkarılmış sayfaların hepsi verildi" ayrı bir kayıtlı olgu olarak adım çıktısında tutulur ve hücrede öyle yazılır; okuma düzeyi sayılmaz. Denklem garantisi verilmez (T10).

## 3. Hücre durum makinesi

İki kural var. İnsan yazıları `expected_version` denetler ve sürümü artırır. Model ve sistem yazıları sürüm denetlemez, geçerli değeri yalnız boş hücrede koyar.

| Olay | Ön koşul | Yazılan revizyon | Geçerli değer | `version` |
|---|---|---|---|---|
| Doldurma sonucu | Hücrede geçerli değer yok | `model_fill` | Yeni değer | +1 |
| Doldurma sonucu | Bu arada insan değer girmiş | `model_proposal` (bekler) | Değişmez | — |
| Kaynakta metin yok | Pasaj yok (özet de yok) | `system_fill`, `inaccessible`, model çağrısı yok | Boşsa yeni değer | Boşsa +1 |
| İnsan düzenlemesi | `expected_version` eşit | `human_edit` | Yeni değer | +1 |
| Recheck isteği | Sürüm eşit, satır tabloda, pasaj var, araştırmada etkin run yok | Yok; `cell_recheck` run'ı kuyruğa girer | Değişmez | — |
| Recheck geçerli çıktı | — | `model_proposal`, `structurally_valid` | Değişmez | — |
| Recheck onarımdan sonra geçersiz | — | `model_proposal`, `unverified_draft`; kabul edilemez | Değişmez | — |
| Recheck duraklar, iptal edilir ya da düşer | — | Yok; run nedeni gösterir | Değişmez | — |
| Öneriyi kabul | Öneri bekliyor, geçerli, sürüm eşit | `accept_proposal`: değer, okuma düzeyi ve kanıt bağları kopyalanır | Öneri değeri, yazarı insan | +1 |
| Öneriyi reddet | Öneri bekliyor, sürüm eşit | `dismiss_proposal` | Değişmez | +1 |
| Sütun talimatı değişir | — | Yok | Değişmez; `stale_column` işareti | — |

**Türetilen görünüm:** `empty`, `filling` (hücrenin run'ı etkin), `model_value`, `human_value` (`human_edit` ya da `accept_proposal`), `system_value`. İşaretler:

- `pending_proposal`: sonrasında kabul ya da red almamış en yeni `model_proposal`. Daha eskileri geçmişte "yerini yenisine bıraktı" diye görünür.
- `proposal_before_edit`: öneri istendikten sonra hücre sürümü değişmiş.
- `proposal_invalid`
- `stale_column`
- `pdf_withdrawn`: kanıt pasajının dosyası `removed_at` almış.
- `row_removed`: satır tablodan çıkarılmış; hücreler saklanır, varsayılan görünümde gizlenir.

Satır başlığı kaynağın Sources'taki seçim durumunu (dahil / kararsız / hariç) bilgi olarak gösterir; bu durum hücreleri değiştirmez.

Anlambilimsel destek alanı dilim 1'de her hücrede `not_checked` kalır. Kabul etmek "değeri kullan" demektir, "desteği denetledim" demek değildir.

## 4. API uçları

Bütün mutasyonlar mevcut loopback, Host/Origin ve CSRF korumasından geçer. Kaynak, sütun ya da hücre başka araştırmaya aitse 404 döner. Sürüm uyuşmazlığı mevcut `RevisionConflict` yoluyla 409 döner. `Idempotency-Key`, run'larda olduğu gibi `{research_id}:{key}` biçiminde ilgili tablonun UNIQUE sütununa yazılır; aynı anahtarla gelen tekrar istek aynı kaydı döndürür. Yol öneki: `/api/researches/{rid}`.

| Uç | Gövde | Anahtar / sürüm | Sonuç |
|---|---|---|---|
| `GET /tables` | — | — | Tablo listesi |
| `POST /tables` | `title`, `template_id?`, `rows?` (varsayılan: dahil edilen kaynaklar) | Idempotency-Key | 201 tablo görünümü |
| `POST /tables/{tid}/rows` | `source_version_ids` | Idempotency-Key + tablo `expected_version` | Satırlar eklenir; araştırmanın kaynağı olmayan kimlik 422 |
| `DELETE /tables/{tid}/rows/{svid}` | — | tablo `expected_version` | `removed_at`; hücreler kalır |
| `GET /tables/{tid}` | — | — | Sütunlar, satırlar, hücre özetleri, sayılar, doldurma tahmini |
| `PATCH /tables/{tid}` | `title` | `expected_version` | Tablo görünümü |
| `DELETE /tables/{tid}` | — | `expected_version` | Yalnız `trashed_at`; geri alma ekranı dilim 3'te |
| `POST /tables/{tid}/columns` | `name`, `instruction`, `answer_format`, `options?`, `allow_multiple?`, `unit_hint?`, `origin` | Idempotency-Key + tablo `expected_version` | 201 |
| `PATCH /tables/{tid}/columns/{cid}` | Aynı alanlar, `position?` | `expected_version` | Yeni sütun revizyonu |
| `DELETE /tables/{tid}/columns/{cid}` | — | `expected_version` | `removed_at`; hücreler kalır |
| `POST /tables/{tid}/column-suggestions` | — | Idempotency-Key | 202 run (`table_columns`); öneriler kendiliğinden eklenmez |
| `POST /tables/{tid}/fill` | `column_ids?`, `include_stale?` | Idempotency-Key | 202 run (`table_fill`); eskimiş hücreler öneri olarak gelir |
| `GET /tables/{tid}/cells/{cid}/{svid}` | — | — | Revizyon geçmişi ve her revizyonun kanıtı (pasaj, konum, alıntı, dosya çekildi mi) |
| `PUT /tables/{tid}/cells/{cid}/{svid}` | `state`, `value?`, `note?`, `keep_evidence_from?` | Idempotency-Key + `expected_version` (yeni hücre için 0) | `human_edit` |
| `POST /tables/{tid}/cells/{cid}/{svid}/recheck` | — | Idempotency-Key + `expected_version` | 202 run (`cell_recheck`); satır tabloda değilse ya da pasaj yoksa 422, etkin run varsa 409 |
| `POST .../cells/{cid}/{svid}/proposals/{rev}/accept` | — | Idempotency-Key + `expected_version` | `accept_proposal`; geçersiz öneride 422 |
| `POST .../cells/{cid}/{svid}/proposals/{rev}/dismiss` | — | Idempotency-Key + `expected_version` | `dismiss_proposal` |
| `GET /api/table-templates`, `POST /api/table-templates` (`name`, `table_id`), `DELETE /api/table-templates/{id}` | — | POST: Idempotency-Key | Kütüphane genelinde şablon |

"Show evidence" için yeni uç yok. Mevcut `GET /passages/{pid}` ve `GET /assets/{aid}` üyelik denetimiyle kullanılır. `keep_evidence_from`, kullanıcı yalnız birimi ya da yazımı düzelttiğinde düzelttiği revizyonun kanıtını taşımasını sağlar ve aynı hücrenin revizyonu olmak zorundadır. SSE akışına `table_changed` ve `cell_revision_saved` olayları eklenir.

## 5. Model adımı ve sözleşme

- **Görevler:** `table_columns` (`TableColumnProposal` v1) ve `cell_extraction` (`EvidenceCellDraft` v1). Her ikisi araştırma (yanıt) modeliyle çalışır, stage `extraction` olur. StepInput'a `extraction_target` eklenir: `table_id`, hedef sütunlar (kimlik, revizyon, ad, talimat, biçim, seçenekler, birim) ve tek `source_id`. `human_corrections` boş kalır; recheck mevcut insan değerini görmez (§9, karar 3).
- **Çağrı birimi:** Doldurmada her kaynak için bir çağrı yapılır ve o kaynağın hedef sütunları birlikte istenir; 8'den fazla sütun varsa kaynak başına 8'erli çağrılara bölünür. Recheck tek kaynak ve tek sütun için bir çağrıdır. Allowlist yalnız o `source_version`'ın pasajlarıdır. İzin verilen dosya çekilmemiş olmalıdır.
- **Pasaj seçimi:** Kaynağın pasajları 48 pasaj ve 60.000 karakteri aşmıyorsa hepsi verilir. Aşıyorsa önce özet, sonra sütun adı ve talimat terimleriyle FTS sırası verilir; anlamsal arama açıksa mevcut `fuse_rankings` ile birleştirilir. Üst sınır doldurmada 24, recheck'te 16 pasajdır. Bunlar test varsayılanıdır; dilim 5'te ölçülür. Adım çıktısı verilen pasaj sayısını ve "bütün sayfalar verildi mi" bilgisini kaydeder.
- **Bütçe:** Doldurma run'ı en fazla 25 kaynak alır ve en fazla `2 × kaynak × ⌈sütun / 8⌉` çağrı yapar (onarım dahil). Kalan hücreler boş kalır ve yeniden "Fill" istenebilir. Recheck ve sütun önerisi en fazla 2 çağrıdır. Çağrı sayısı ve model başlatmadan önce gösterilir.
- **Deterministik denetimler** (hata tek onarıma gider):
  - Her hedef sütun tam bir kez yanıtlanır.
  - Pasaj kimlikleri allowlist'tedir. Başka kaynağın ya da aynı yayının başka sürümünün pasajı reddedilir.
  - `value` biçime uyar: seçenek kimliği listede olur, `allow_multiple` değilse tek olur; sayı sonludur; `yes_no` yalnız yes ya da no alır; `text` en fazla 500 karakterdir. `value` en az bir pasaj ve bulunabilen alıntı ister (D27).
  - `unknown` en az bir pasaj ister. `not_applicable` gerekçe ister. Okunan pasajlarda karşılık yoksa model `not_found_in_inspected_scope` yazar ve pasaj vermez.
  - `inaccessible`, `not_verified` ve `not_reported` model tarafından yazılamaz. `not_verified` insan tarafından kanıtsız girilen değer içindir. `not_reported` yalnız insan yazısıdır, çünkü "yayında yok" demek çıkarılmış metnin ötesinde okuma ister (§9, karar 5).
  - `note` içinde sayfa ya da denklem konumu yazılamaz (`locator_in_claim_text` kuralı).
- **Yöntem dosyası:** `references/evidence-table.md` eklenir. Sütun talimatını insan etiketleyici gibi izlemeyi, boş durumların tanımlarını, birim dönüştürmemeyi ve sayıyı kaynaktaki gibi yazmayı anlatır. Paket hash'i ve `task_type` sözleşme enum'u değişir.

## 6. Ekran akışı

Mevcut sekmeler Answer, Sources ve Activity'dir. Sources ile Activity arasına **Evidence** sekmesi eklenir. Plandaki Answer/Papers/Evidence/Report yerleşiminde Papers karşılığı mevcut Sources sekmesidir; Report yanıtın rapor sayfası olarak kalır (P6). Tablo arayüzü yeni `EvidenceTable.tsx` dosyasında yazılır. `ResearchView.tsx` içinde yalnız sekme bağlantısı değişir, çünkü bu dosya şu anda başka bir oturumda düzenleniyor.

1. **Boş durum.** "Henüz tablo yok" metninin altında üç eylem durur: "Sorudan sütun öner" (model adı ve 1–2 çağrı yazılı), "Sütun ekle" ve "Şablondan başlat".
2. **Sütun düzenleyici** (sağ panel). Alanlar: kısa ad, talimat ("bir insana yazar gibi yazın"), biçim seçimi (Seçenekler / Sayı ve birim / Evet–Hayır / Kısa metin) ve seçenek listesi. Model önerileri taslak satırlar olarak gelir; her birinde "Ekle", "Düzenle" ve "At" vardır.
3. **Tablo.**
   - İlk sütun yapışkandır: kaynak kısa anahtarı, yıl, sürüm etiketi, okuma düzeyi ve Sources'taki seçim durumu.
   - "Satır ekle" araştırmanın kaynaklarını onay kutularıyla listeler (dahil edilenler başta); satır menüsünde "Tablodan çıkar" vardır.
   - Sütun başlığına odaklanınca talimat görünür.
   - Araç çubuğunda "Boş hücreleri doldur · {n} kaynak · en fazla {m} çağrı · {model}" ve "Şablon olarak kaydet" bulunur.
   - Dar ekranda tablo kendi kabında yatay kayar, sayfa kaymaz.
4. **Hücre.**
   - Değer ya da boş durum etiketi gösterilir. Boş durumlar yalnız renkle değil metinle ayrılır: "Bildirilmemiş", "Okunan kısımda bulunamadı", "Metin yok".
   - Küçük yazar işareti (model / siz / sistem) ve okuma düzeyi işareti yer alır.
   - Kehribar renk yeni öneri, sütun değişikliği ve çekilmiş PDF içindir. Kırmızı geçersiz öneriyi gösterir.
   - Tablonun altında şu not durur: "Anlamsal destek denetlenmedi."
5. **Hücre paneli** (tıklayınca sağda açılır).
   - Geçerli değer: durum, yazar, model ve run, tarih, sütun revizyonu.
   - Kanıt listesi: konum ve vurgulu alıntı, yanında **Show evidence** düğmesi. Bu düğme `PassageSheet`'i açar; PDF sekmesi ilgili sayfadan başlar.
   - **Değeri düzenle:** durum seçimi, biçime göre değer ve not.
   - **Recheck this cell:** kapsam açıkça yazılır ("Yalnız {kaynak} · {n} pasaj · {model} · 1–2 çağrı").
   - Bekleyen öneri geçerli değerin yanında karşılaştırmalı gösterilir. Eylemler "Bu değeri kullan" ve "Mevcut kalsın" olur; öneri düzenlemeden önce istendiyse bu yazılır.
   - Geçmiş katlanmış gelir: bütün revizyonlar ve her birinin kanıtı.
6. **409 çakışması.** Mevcut ileti gösterilir ("Uygulanmadı… sayfa son durumu gösteriyor"). Yazılan taslak formda korunur.
7. **Canlı durum.** Recheck sırasında hücre "Yeniden inceleniyor" gösterir; hareket `prefers-reduced-motion` ayarına uyar. Run, üstteki mevcut run kartında ve Activity'de tek kayıt olarak görünür.

Doğrulama masaüstü ve dar ekranda, açık ve koyu temada yapılır; klavyeyle hücre gezme ve panel açma denetlenir.

## 7. Testler

**Sözleşme ve depolama**

- Migration P4 dönemi bir veritabanı kopyasında çalışır: `runs` satırları ve foreign key denetimi temiz kalır, yeni run türleri kabul edilir, `-- deixis:foreign-keys-off` işareti olmayan dosyalar eskisi gibi çalışır.
- Revizyon ve kanıt tetikleyicileri güncellemeyi ve silmeyi reddeder; purge yetkisiyle silme çalışır; `purge_research` yeni tabloları temizler.
- Başka kaynağın pasajı `cell_evidence_same_source` tetikleyicisiyle reddedilir.
- `EvidenceCellDraft` denetimi: bir sütunun eksik ya da çift yanıtlanması, bilinmeyen pasaj, aynı işin başka sürümünün pasajı, her biçimde hatalı değer (500 karakteri aşan metin dahil), modelin `inaccessible`, `not_verified` ya da `not_reported` yazması, bulunamayan alıntı, notta konum.
- Kısa kimliklerin hücre çıktısında geri çözülmesi.
- Okuma düzeyi kuralı: yalnız özet `abstract`, bazı ya da bütün sayfalar `selected_sections`; hiçbir durumda `full_text` yazılmaz; "bütün sayfalar verildi" olgusu ayrı kaydedilir; çekilmiş dosyanın pasajı verilmez.
- Satırlar: araştırmanın kaynağı olmayan kimlik 422 alır; satır çıkarılınca hücreler kalır; kaynak Sources'ta hariç tutulunca satır ve hücreleri değişmez.

**Akış** (sahte adaptörle)

- Doldurma, kanıtı o kaynak sürümünün gerçek pasajlarına bağlar.
- Metni olmayan kaynak model çağrısı olmadan `inaccessible` alır.
- Yeniden başlatılan doldurma revizyonları çoğaltmaz.
- Bütçe dolunca run duraklar.
- Recheck StepInput'unun allowlist'i yalnız o kaynağın çekilmemiş pasajlarıdır (T08 ve T03 ön koşulu).

**T09 senaryoları**

- a. İnsan değeri varken doldurma: geçerli değer değişmez, model çıktısı öneri olarak kalır.
- b. İnsan değerine recheck: öneri bekler. Kabulden sonra geçerli değer `accept_proposal` olur ve eski insan revizyonu geçmişte kalır.
- c. Red: geçerli değer ve öneri geçmişte kalır.
- d. Eski ekran: A ve B aynı sürümü görür, A düzenler, B'nin yazısı 409 alır ve A'nın değeri korunur.
- e. Recheck sonucu kullanıcı düzenlerken gelir: düzenleme başarılı olur, öneri `proposal_before_edit` gösterir.
- f. Boş hücrede doldurma ile insan düzenlemesi yarışır: insan önce yazarsa model çıktısı öneri olur.
- g. Aynı `Idempotency-Key` ile çift gönderim düzenlemede aynı revizyonu, recheck'te aynı run'ı döndürür.
- h. Onarımdan sonra geçersiz öneri: kabul 422 alır, geçerli değer değişmez.
- i. Sütun talimatı değişir: eski değer `stale_column` gösterir; `include_stale` doldurması yalnız öneri üretir.
- j. Tablodan çıkarılmış satırda ya da pasajsız kaynakta recheck 422, etkin run varken 409 alır.
- k. Recheck sırasında backend yeniden başlar: adım `outcome_unknown` olur, devamdan sonra tam bir öneri oluşur.
- l. Model değeri olan, insanın dokunmadığı hücrede recheck: sonuç öneri olarak bekler, geçerli model değeri değişmez.
- m. Recheck StepInput'u hücrenin mevcut insan değerini içermez.

**Kanıtın dayanıklılığı**

- Doldurmadan sonra PDF çekilir: hücre kanıtı metin olarak açılır, PDF sekmesi kapanır, `pdf_withdrawn` görünür.
- Yedekle ve geri yükle: yeni tabloların satır sayıları eşleşir ve hücre kanıtı açılır (T15'in bu dilimdeki payı).

**API**

- Bütün yeni mutasyonlar CSRF ister.
- Başka araştırmanın hücresi 404 döner.
- Beklenen sürüm uyuşmazsa 409 döner.

**Web**

- `npm run build`.
- Fixture sunucusu ve senaryolu modelle Playwright testi: tablo, sütun, doldurma, düzenleme, recheck, kabul ve ikinci sekmede 409.
- Ekran görüntüleri masaüstü ve dar ekranda, açık ve koyu temada alınır.

**Gerçek model (gpt-5.6-luna, bütün roller açıkça):** Kurt 2017 araştırmasında sütun önerisi, 25 kaynaklık doldurma ve 3 recheck yapılır. Raporlananlar: yapısal geçerlilik oranı, bulunan alıntı oranı ve elle denetlenen örnek hücrelerde değerin ve pasajın doğru olup olmadığı. Bu dilim 5 ölçümünün ön denemesidir; arama recall'u ve tam metin edinme oranı ayrı kalır.

**Bu dilimde geçmeyecekler:** T03'ün sürüm taşıma kısmı ve T15'in çöp kutusu kısmı dilim 2 ve 3'e, T10 dilim 4'e kalır.

## 8. Varsayımlar

- Yeni model rolü yoktur; hücre işleri araştırma (yanıt) modeliyle çalışır ve yanıt incelemecisi (D14) hücrelere uygulanmaz.
- Evet–hayır biçimindeki "belirsiz" ayrı bir değer olmaz; `unknown` durumuna eşlenir.
- Hesaplanan hücre yoktur: birim dönüştürülmez, `calculation` alanı bu dilimde yoktur.
- Tek etkin run kuralı sürer: bir araştırmada run çalışırken recheck 409 alır ve düğme kapalı görünür.
- Tablo dışa aktarma (CSV/Excel) P6 işidir; kullanıcı eliyle kanıt pasajı seçme bu dilimde yoktur.
- Dilim 1 beş alt adımda uygulanır, her birinin sonunda testler çalışır:
  1. Migration, store ve API (modelsiz)
  2. `cell_extraction` adımı, doldurma ve recheck
  3. Arayüz
  4. Sütun önerisi ve şablonlar
  5. Gerçek Luna denemesi

## 9. Kararlar (16 Eylül 2026, sahibin isteğiyle Claude yanıtladı)

Bu kararlar uygulama onayıyla birlikte `docs/decisions.md`'ye D-girdisi olarak yazılacak.

1. **Satırlar tabloya özel bir listede tutulur.** Tablo açılırken dahil edilen kaynaklarla başlar; kullanıcı araştırmanın başka kaynaklarını ekleyip çıkarabilir.
   - *Neden:* D34'te kullanıcı yanıt girdisine PDF sayfası sığsın diye 26 kaynağı "kararsız"a çekti. Satırlar seçimden türetilseydi, yanıtı daraltmak tabloyu da küçültürdü. Tablo her kaynağı ayrı çağrıyla okuduğu için 48 pasaj sınırına bağlı değildir.
   - *Bedeli:* bir tablo daha (`table_rows`). Dilim 3'teki "seçili kaynaklardan tablo başlat" akışı da bu yapıya doğrudan oturur.
2. **Dördüncü biçim olarak kısa metin (`text`, en fazla 500 karakter) eklenir.**
   - *Neden:* "Yöntem", "veri seti", "ana bulgu" gibi alanlar seçenek, sayı ya da evet–hayır ile yazılamaz. Bunlar kanıt tablosunun en sık sütunlarıdır.
   - *Risk:* modelin serbest yorum yazması. Bu yüzden diğer biçimlerle aynı kural geçerlidir: en az bir pasaj ve bulunabilen alıntı gerekir, notta konum yazılmaz.
3. **Recheck modele mevcut insan değerini göstermez.**
   - *Neden:* Değeri gören model ona yaslanabilir. O durumda "model de aynı şeyi buldu" sonucu bir kanıt olmaz. Karşılaştırma ekranda, iki değer yan yana gösterilerek yapılır.
4. **Recheck sonucu her durumda öneri olarak bekler; hücrenin değerini model de yazmış olsa kendiliğinden değişmez.**
   - *Neden:* Model çıktısı her çağrıda değişebilir. Kendiliğinden değişen bir değer, kullanıcının daha önce baktığı değerin sessizce yer değiştirmesi olur. "Yalnız kabul değiştirir" kuralı tek ve öngörülebilirdir.
5. **Dilim 1'de hiçbir hücre `full_text` almaz ve model `not_reported` yazamaz.**
   - *Neden:* Bütün çıkarılmış sayfaların verilmesi yayının tamamının okunması demek değildir. D25'e göre MuPDF gösterilen denklemleri bozuk çıkarıyor. Şekil içindeki bilgi metinde hiç yok. Metinsiz taranmış sayfalar da OCR gelene kadar okunamıyor.
   - *Sonuç:* Bu koşullarda modelin "yayında bildirilmemiş" demesi T10'un yasakladığı türden bir garanti olur. Model `not_found_in_inspected_scope` yazar. `not_reported` yalnız insanın kararıdır. "Bütün sayfalar verildi" ayrı bir olgu olarak görünür.
   - *Ne zaman yeniden bakılır:* OCR ve sayfa denetimi (dilim 4) ile ölçüm (dilim 5) sonrasında.
6. **Doldurma run'ı en fazla 25 kaynak alır. Her kaynak için bir çağrı yapılır; 8'den fazla sütun varsa çağrı 8'erli bölünür.**
   - *Neden kaynak başına:* Allowlist tek kaynağın pasajlarıyla sınırlı kalır, bu da başka kaynaktan ya da başka sürümden kanıt karışmasını yapısal olarak önler. Sütun başına çağrı yapılsaydı, 25 kaynak ve 5 sütun için 125 çağrı gerekirdi.
   - *Neden 25:* D34'teki düzeltilmiş çekirdek küme 25 eserdi. Bu boyutta bir run'ın maliyeti ve süresi başlamadan önce gösterilebilir. Run duraklatılıp devam ettirilebilir; büyük tablolar ikinci bir "Fill" ister.
   - *Ölçülmeyen:* Luna'nın bu yükte kota ve süre davranışı. İlk gerçek deneme bunu raporlar.
