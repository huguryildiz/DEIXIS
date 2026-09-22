# SW dilim 13a — Şemayı zorlayamayan modellerle çalışma: uygulama planı

**Tarih:** 22 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir; bu dilim ana planda yoktur, dilim 13'ün dördüncü koşusundan çıktı). **Karar:** D86. **Önkoşul:** 13 (koşuldu). **Tür:** Kur (ölçülmedi). **Uygulayan:** Opus · high. **İnceleme:** tam, biter bitmez (Fable · high): dilim model sınırına dokunuyor.

**Sahibin kararları (22 Eylül 2026, plan sohbeti):**

1. **Kullanıcı modeli seçer; uygulama seçilen modelle çalışır.** DeepSeek gibi şemayı zorlayamayan bağlantı üründen çıkarılmaz, "ölçüm modeli değiştirilsin" yolu seçilmedi.
2. **Üç katman, hepsi kayıtlı:** şema + iskelet istemde; küçük eş ad tablosu doğrulamadan önce ve `validation_json`'a yazılarak; onarım koşuyu boşaltmaz.
3. **Kabul koşulu:** tam pytest yeşil **ve** DeepSeek ile beşinci duman koşusunda (`data-5`) okuma ve yanıt adımlarının şemaya uyması (okuma koşusu `completed`, yanıt `structurally_valid`). Koşuyu bu dilim yapmaz; dilim 13'ün planıyla ayrı bir oturum yapar (Sonnet).

**Goal:** Dördüncü duman koşusunda ([result-run4.md](../../.local/sw-smoke-2026-09-22/result-run4.md), depoda değil) okuma adımı 40 çağrının 34'ünde, yanıt adımı 2'de 2 geçersiz çıktı aldı. Üç neden, adıyla: (a) DeepSeek adaptörü `run_step`'e gelen `output_schema`'yı **hiç kullanmıyor**; model şemayı görmüyor, alan adlarını yalnızca yöntem dosyasının düzyazısından biliyor. (b) DeepSeek API'si şema zorlamıyor (`json_schema` biçimi 22 Eylül 2026'da HTTP 400 "unavailable now" döndü; `json_object` var). (c) Onarım ve geçersiz çağrı bütçeden ödenince okuma koşusu `budget_exhausted` ile **duraklad** (D85 "sonundaki işler `not_reached`, koşu biter" derken); bu, dilim 12 ön kontrolünün "limiter > 1'de bütçe gediği" açığıdır ve burada kapanır.

**Architecture:** `ModelAdapter` protokolüne `enforces_schema: bool` (Codex, Claude, Gemini `True`; DeepSeek `False`; `FakeAdapter` kurulabilir). `flow._model_step`, zorlamayan adaptör için geliştirici talimatının sonuna şemayı ve iskeleti ekler (`prompt.schema_appendix(task_type, schema)`), saklanan StepInput bunu taşır. `domain/contracts.py`'de `normalise_output(task_type, raw) -> (draft, changes)`; `validate_model_output` çağrılmadan önce koşar, `changes` `validation_json.normalised`'a yazılır. Bütçe: `_send_through_limiter` kullanan iki gönderici (özet, okuma) bir işi ancak borçlu çağrıları **onarım payıyla** sığıyorsa gönderir; yanıt koşusu onarımı bugünkü gibi öder.

## Global constraints

- **Model sınırı değişmez:** araç yok, başka modelin çıktısı kullanılmaz, ham çıktı olduğu gibi saklanır. Eş ad düzeltmesi yalnızca **ad** değiştirir, **değer** değiştirmez: etiket değeri, alıntı metni, pasaj kimliği, eksik zorunlu alan doğrulamaya olduğu gibi gider ve reddedilir. Tablo dışı hiçbir şey düzeltilmez; "modelin ne demek istediği" tahmin edilmez.
- **Zorlayan adaptörün StepInput'u bayt bayt aynı kalır:** iskelet yalnızca `enforces_schema` `False` iken eklenir. Yöntem paketi dosyaları değişmez, `skill_package_hash` aynı kalır (başlamadan ve bitince `GET /api/health` ile değil, `domain/skill.py`'nin hesabıyla doğrula; canlı sunucu açılmaz). Mevcut araştırmaların saklı StepInput'ları taşınmaz.
- **`legacy` akış, `discovery` / `answer` / tablo koşuları:** normalizasyon bütün model adımlarına uygulanır (aynı tablo, görev türüne göre satırlar); bütçe değişikliği yalnızca `_send_through_limiter` göndericilerini etkiler. `TEST_EFFORT_BUDGETS` ve `MAX_SCHEMA_REPAIRS` (1) değişmez.
- **Ders D (D85):** başlatılan her çağrı sayılır; onarım ayrı paydan ödenmez. Bu dilimin yaptığı yalnızca **göndermeden önce** onarım olasılığını hesaba katmaktır: iş, `owed × (1 + schema_repairs(task))` çağrı sığmıyorsa gönderilmez ve `not_reached` sayılır. Böylece `_model_step`'in `budget_exhausted` duraklaması limiter yolundan hiç tetiklenmez; tetiklenirse bu bir hatadır (test).
- Testlerde ağ ve canlı model yok. Ürün koduna konuya özgü sözcük girmez.
- Başlamadan kontrol et: son karar `D88` (bu dilim `D86`'yı alır, yazıldı), son migration `0047`. Bu dilim migration açmaz.

## Dosya yapısı

Değişecek: `backend/deixis/models/adapter.py` (protokol + `CodexAdapter.enforces_schema = True`), `models/claude.py`, `models/gemini.py`, `models/deepseek.py`, `models/prompt.py`, `domain/contracts.py`, `workflow/flow.py` (`_model_step`, `_abstract_stage.jobs`, `_fulltext_adjudication`'ın gönderici döngüsü, `_model_calls_left`), `tests/fakes.py` (`FakeAdapter(enforces_schema=...)`), yeni `tests/test_schema_lenient_models.py`, `tests/test_deepseek_adapter.py`, `docs/decisions.md` (D86 Status → implemented), `sw-status.md`.

## Task 1: adaptör bayrağı ve DeepSeek'in şemayı göstermesi

- `ModelAdapter` protokolüne `enforces_schema: bool`. Codex/Claude/Gemini `True`. DeepSeek `False`; `run_step` sistem iletisine `output_schema`'yı JSON metni olarak ekler ("The output must match this JSON schema exactly: …") — `json_object` modu kalır.
- `FakeAdapter` bayrağı kurucu parametresi olarak alır, varsayılan `True` (mevcut testler değişmez).

- [ ] **Tests first:** DeepSeek `run_step`'in gönderdiği sistem iletisi şemayı içerir (`MockTransport` ile gövde okunur); Gemini/Claude'un gönderdiği istek değişmez (mevcut testler).

## Task 2: iskelet eki

- `prompt.schema_appendix(task_type, schema) -> str`: şemanın `required` alanlarından türetilen, dizilerde tek öğeli, değerleri türüne göre yer tutucu (`"<string>"`, `0`, `null`, enum'da ilk değer) bir iskelet + "Use exactly these field names" cümlesi. Saf işlev; şema `additionalProperties: false` olduğu için iskelet şemadan **türetilir**, elle yazılmaz.
- `flow._model_step`: `adapter.enforces_schema` `False` ise `developer = developer + "\n\n" + prompt.schema_appendix(...)`; `insert_step_input` bunu saklar. `True` ise hiçbir şey eklenmez.

- [ ] **Tests first:** `abstract_screening`, `fulltext_adjudication`, `grounded_answer` için iskelet şemadaki her zorunlu alanı taşır ve şemaya göre geçerlidir (`Draft202012Validator`); zorlayan adaptörle saklanan `developer_instructions` bayt bayt önceki ile aynı; zorlamayanla eki taşır.

## Task 3: eş ad düzeltmesi, kayıtlı

- `contracts.normalise_output(task_type, draft) -> (draft, changes)`. Tablo `domain/contracts.py`'de adlı sabit `OUTPUT_ALIASES`: görev başına `{"parts[].name": "part", "parts[].verdict": "label", "parts[].status": "label"}` (`fulltext_adjudication`), `{"citation_anchors[].claim_label": lower, "claims[].claim_label": lower}` (`grounded_answer`, `answer_review`) ve `abstract_screening` için aynı ad eşlemesi (`records[].verdict` → `label`). Hedef ad zaten varsa **hiçbir şey yapılmaz** (iki alan da kalır, doğrulama `additionalProperties` ile reddeder). `changes` listesi: `[{"path": "/parts/0/name", "renamed_to": "part"}]` biçiminde.
- `flow._model_step`: `resolve_citation_handles`'tan sonra, `validate_model_output`'tan önce; `recorded["validation_json"]["normalised"] = changes`. Ham çıktı (`raw_output`) değişmez.

- [ ] **Tests first:** `name`/`verdict` çıktısı normalize edilip geçer ve `validation_json.normalised` iki satır taşır; `C1` → `c1` geçer ve kaydedilir; eksik `passage_id` normalize edilmez, `schema_invalid` kalır; `label` değeri (`present` yerine `yes`) değişmez ve reddedilir; iki ad da varsa dokunulmaz ve reddedilir; `raw_output` bayt bayt modelin verdiği; tablo dışı görev türünde `changes` boş.

## Task 4: bütçe, onarım payıyla gönderim

- `_model_calls_left(run, wanted, submitted, before)` çağrılarına gönderici `wanted = owed × (1 + schema_repairs(task_type))` verir (özet: `abstract_screening` onarımsız, `schema_repairs` 0, davranış aynı; okuma: `fulltext_adjudication` için 1 onarım → iş başına 4 çağrı yer ister). Sığmayan iş `not_reached`; koşu `completed`. Yanıt koşusu değişmez.
- Dilim 12 ön kontrolünün açığı: "limiter > 1'de bir iş bütçe sınırında tek koşuyla kalabilir" — bu hesapla kapanır; test adıyla.

- [ ] **Tests first:** 20 işlik plan, bütçe 40, her ilk çağrı geçersiz + onarım: koşu `completed`, `not_reached` > 0, hiçbir adım `budget_exhausted` yazmaz, hiçbir iş yarım gönderilmez; limiter 4 ile aynı sonuç; onarımsız koşuda (her çıktı geçerli) 20 işin 20'si okunur (bütçe boşa ayrılmaz: onarım payı yalnızca **kalan** çağrıların sığıp sığmadığına bakarken kullanılır, önceden rezerve edilmez — uygulayan bunu `_model_calls_left`'in `submitted` sayacıyla kurar).

## Task 5: kapanış

- Tam pytest, `git diff --check`, D86 Status → `accepted; implemented`, satır 13a `uygulandı, inceleme bekliyor`, tek commit, push.
- Beşinci duman koşusu bu dilimin işi değil: satırda "kabul koşulu bekliyor: DeepSeek ile `data-5`" yazılır; koşu dilim 13'ün planıyla, `run4.py` kalıbıyla, Sonnet'e verilir ve sonucu satıra işlenir.

## Ölçülmedi

DeepSeek'in iskelete uyma oranı; Gemini/Luna ile aynı adımlar; eş ad tablosunun başka modellerde gerekip gerekmediği; onarım payının okuma sayısına etkisi.
