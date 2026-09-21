# SW dilim 05 — Derleme işareti, eksik özet ve dış sürüm bağlantıları: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): SW5 (tümü), SW9 madde 3, SW6 madde 4, SW11 madde 3. **Önkoşul:** 02 (D71), 03 (D72), 04b (D76), 04c (D75) kapandı. **Tür:** Kur. **Uygulayan:** Opus · **high** (ana tablodaki `medium` yükseltildi: karar satırı yazan ilk dilim ve birleştirme yoluna dokunuyor). **İnceleme:** tam (gerekçe en altta).

**Goal:** `sw` keşif koşusunda, iki arama turundan sonra ve taramadan önce üç iş yapılır, hiçbiri model çağırmaz: (1) özeti olmayan kayıtlar için DOI ile önce Semantic Scholar'a, sonra Crossref'e sorulur ve gelen özet, nereden geldiğiyle saklanır; (2) aynı yanıtlardaki dış bağlantılar (S2 `externalIds`, Crossref ön baskı ilişkisi) ve arXiv'in yazar DOI alanı bir birleştirmeyi doğrular ya da engeller; (3) kod derleme işaretlerini koyar. Yalnızca **güçlü başlık sözcüğü** kaydı tarama listesinden çıkarır; özetin kendini tanımlaması ve 150+ referans yalnızca işaret koyar, kayıt aday kalır (SW9.3, SW5.4'ü daraltır). Özetsiz kayıt hiçbir yoldan "kapsam dışı" olmaz. `legacy` araştırmada hiçbir şey değişmez.

**Dayanak ölçümler.** Derleme kuralı (`.local/quantum-source-comparison-2026-09-18/survey_metadata.py`, SW5 Context): 1.336 kayıt, başlık sözcüğü ya da özet ifadesi kesinlik 0,72 / duyarlılık %62; 150+ referans kesinlik 0,83 / duyarlılık %29; OpenAlex `type = review` duyarlılık %2. Referans sayısı o sondada OpenAlex'in `referenced_works_count` alanıydı. Dış bağlantılar (SW6 Context): S2 181 arXiv–yayımlanmış çiftin 150'sini tek makale tutuyor, 12'sinde ön baskıyı **başka** bir yayımlanmış DOI'ye bağlıyor (11'i 0,60–0,85 başlık bandında); S2'nin bağlamadığı 19 çiftte arXiv DOI alanı 1, Crossref ilişkisi 1 bağlantı verdi. **Ölçülmeyen:** ikinci kaynağın kaç eksik özeti doldurduğu. Eldeki havuzlar: kuantum 1.369 kayıtta 107 özetsiz (105'i DOI'li) ve 304 arXiv DOI'li kayıt; KAA 978 kayıtta 129 özetsiz (122'si DOI'li).

**Kodda bugün ne var (21 Eylül 2026'da okundu):**

- Hiçbir sağlayıcıda DOI ile tek kayıt sorgusu yok (yalnızca `scripts/p4_eval/measure.py` Crossref'e DOI ile soruyor; ürün kodu değil). `providers/common.py::send` yalnızca GET atıyor; D67'nin S2 kapısı `send`'in içinde, ana makine adına göre.
- Referans sayısı hiçbir yerde alınmıyor. `openalex.SELECT`'te `referenced_works_count` yok; Crossref `SELECT`'inde `reference-count` ve `relation`, S2 `FIELDS`'inde `referenceCount` yok. Bu sabitlere alan eklemek `legacy` isteğini de değiştirir.
- S2 arama kaydının `externalIds`'i `ProviderRecord.identifiers`'ta duruyor ama `_insert_mappings` yalnızca sağlayıcı kimliğini, `doi`'yi ve arXiv'in `published_doi`'sini saklıyor. arXiv DOI alanı dilim 03'te zaten **doğrulama** yönünde kullanılıyor (`links._published_doi_pairs`, kural 5 `preprint_names_published_doi`); **engelleme** yönü yok.
- Özet, `passages` tablosunda `kind = 'abstract'` satırıdır; `abstract_origin` sütununda CHECK yok. `upsert_provider_source` özeti yalnızca kayıtta hiç özet yoksa yazar; aynı "boşsa doldur" kalıbını 04b `_store_author_keywords`'te sütun için kullandı.
- `stage_decisions`'ı hiçbir akış adımı yazmıyor. `no_abstract` kodu var (`unresolved`, sonraki adım `abstract_lookup`); derleme kodu yok; `NEXT_STEPS`'te `seed_pool` hazır.
- `sw` koşusunda tarama hâlâ `legacy` sözleşmesiyle koşuyor ve modelin `exclude` önerisi doğrudan `selections`'a yazılıyor (`apply_screening_proposal`). Bugün özetsiz bir kayıt bu yolla dışlanabiliyor; kabul koşulu bunu kapatır.

**Architecture:** Kurallar saf koddur (`domain/survey.py`, sözcük listeleri `domain/survey_words.py`). Sorgu istemcileri `providers/lookup.py`'dedir. Planlama, sorma, saklama ve karar `workflow/lookups.py`'dedir; akış yalnızca çağırır. Sorulan her kayıt için yanıt, kütüphane genelindeki `record_lookups` tablosuna yazılır (bağlantılar gibi, D46): aynı kayıt aynı kaynağa ikinci kez sorulmaz, ne sürdürülen koşuda ne aynı kapsamdaki ikinci keşif koşusunda ne de başka bir araştırmada. Kimin hangi sırayla sorulacağı **plan adımının saklı çıktısında** durur, çünkü sürdürülen koşuda "hâlâ özetsiz olanlar" listesi değişmiştir ve yeniden türetilen parti numaraları başka kayıtları gösterir. Dış bağlantı `identifier_mappings`'e ayrı bir şemayla (`linked_doi`) yazılır ki `legacy`'nin okuduğu `published_doi` yolu onu görmesin.

**Tech stack:** Python 3.12. Yeni bağımlılık yok.

## Global constraints

- `apps/web/`, `contracts/research/`, `methods/deixis-research/` ve mevcut migration dosyalarına dokunma. `skill_package_hash` değişmez. Model çağrısı eklenmez.
- `legacy` araştırmanın davranışı, **sağlayıcı istekleri** ve mevcut test beklentileri değişmez. `openalex.SELECT`, `crossref.SELECT`, `semantic_scholar.FIELDS` sabitleri olduğu gibi kalır.
- Ürün koduna konu sözcüğü girmez. Sözcük listeleri alan-bağımsızdır ve SW5.1'deki listedir. OpenAlex `type` ve mekân adı derleme sinyali olarak **kullanılmaz** (SW5.3); S2 `publicationTypes` de kullanılmaz (ölçülmedi).
- İşaret kayıt silmez, `selections`'a dokunmaz, yalnızca yönlendirir. Kullanıcının seçimi (`selections.origin = 'user'`) hiçbir adımda değişmez.
- Başarısız sorgu koşuyu durdurmaz ve duraklatmaz (D18). Bu dilim `budget_exhausted` yolu **açmaz**.
- Dilim 03'ün on altı satırlık kural tablosu, `save_link`'in "iki yayımlanmış kayıt tek işe girmez" koruması, `undone` belleği ve `undo_json` aynen kalır; yeni satırlar eklenir, var olan satırın anlamı değişmez.
- Tarama kesimine (`max_candidates`) dokunma (dilim 09). Tohum havuzu kurulmaz (dilim 15): işaret saklanır, o kadar.
- Testlerde ağ yok. Fikstürler SYNTHETIC ve en az iki alandan.
- Son migration `0042`, son karar `D76`'dır; bu dilim `0043` ve `D77`'yi kullanır. Başlamadan önce kontrol et.

## Dosya yapısı

Yeni: `backend/deixis/domain/survey.py`, `backend/deixis/domain/survey_words.py`, `backend/deixis/providers/lookup.py`, `backend/deixis/workflow/lookups.py`, `backend/deixis/storage/migrations/0043_record_lookups_and_flags.sql`, `tests/test_survey_rule.py`, `tests/test_record_lookups.py`, `tests/test_lookup_flow.py`, `tests/test_external_links.py`.

Değişecek: `providers/common.py` (`ProviderRecord.reference_count`; `send`'e `json_body`), `providers/openalex.py` (`search_works(..., reference_count=False)`), `providers/registry.py` (`Connector.sw_options`), `workflow/store.py` (`upsert_provider_source`: referans sayısı; iki purge tablo listesi), `domain/reason_codes.py` (iki kod), `domain/record_identity.py` (`classify_pair`: iki anahtar sözcük argümanı, iki satır), `workflow/links.py` (`link_external`, engelleme girdisi), `workflow/flow.py` (`_search`: `sw_options`; `_discovery`: tek `sw` bloğu ve tarama süzgeci), `workflow/protocol.py`, `tests/test_providers.py`, `tests/test_protocol_record.py`, `tests/determinism_stages.py`, `docs/decisions.md`, SW belgesi (SW5, SW6, SW9 durum satırları), `docs/product/sw-status.md`.

## Task 1: referans sayısı, yalnızca `sw` isteğinde

`ProviderRecord.reference_count: int | None = None`. Migration: `ALTER TABLE source_versions ADD COLUMN reference_count INTEGER;`. `upsert_provider_source` yeni kayıtta yazar, var olan kayıtta **yalnızca sütun boşsa** doldurur (`_store_author_keywords` kalıbı, 0043 öncesi şema için aynı sütun denetimiyle). Atıf sayısı gibi tarihlenip üzerine yazılmaz: bir makalenin kaynakçası değişmez.

`legacy` isteği değişmesin diye alan yalnızca `sw`'nin sayfalı okumasında istenir:

- `openalex.search_works(..., reference_count: bool = False)`: `True` ise `select` = `SELECT + ",referenced_works_count"`, ve `_record` alanı okur. `False` iken istek bayt bayt bugünküdür.
- `Connector.sw_options: dict[str, Any] = field(default_factory=dict)`; yalnızca `openalex` satırı `{"reference_count": True}` taşır. `flow._search`, `page is not None` iken `connector.search`'e `**connector.sw_options` geçirir. Akışta sağlayıcı adı geçmez. bioRxiv satırına verilmez.
- Başka sağlayıcıdan gelen kayıt sayıyı yalnızca aynı DOI OpenAlex'ten de geldiyse ya da Task 3'teki sorgu yanıtından alır (S2 `referenceCount`, Crossref `reference-count`). Sayısı olmayan kayıtta sinyal **yoktur**, sıfır değildir.

- [ ] **Tests first:** `reference_count=False` iken istek parametreleri mevcut testlerdekiyle aynı (mevcut OpenAlex istek testi dokunulmadan geçer); `True` iken `select` alanı taşır ve kayıt sayıyı okur; `legacy` koşusunun OpenAlex isteğinde alan yok, `sw` koşusunun her sayfasında var; dolu sütunu ikinci sağlayıcı ezmez; `None` sütunu sonradan gelen sayı doldurur.

## Task 2: `domain/survey.py` — derleme sinyalleri (saf)

`domain/survey_words.py` (yalnızca veri, SW5.1 ve ölçülen sondanın desenleri):

```python
STRONG_TITLE_WORDS = ("survey", "review", "overview", "tutorial", "roadmap", "primer", "taxonomy",
                      "state of the art", "systematic mapping", "bibliometric")
# The abstract names itself a survey. These are the patterns the SW5 probe measured, not a wider guess.
ABSTRACT_SELF_DESCRIPTIONS = (
    r"this (survey|review|tutorial|overview)", r"we (survey|review)\b", r"in this (survey|review)",
    r"comprehensive (survey|review|overview)",
    r"this (paper|article|work|chapter) (surveys|reviews|provides an overview|presents a (survey|review|comprehensive))",
    r"literature review")
```

`domain/survey.py`:

```python
REFERENCE_COUNT_SURVEY = 150   # SW5.1; chosen on one topic, not measured elsewhere

@dataclass(frozen=True)
class SurveySignal:
    flag: str        # "survey_title_word" | "survey_abstract_phrase" | "survey_reference_count"
    evidence: str    # the matched word or phrase as it stands in the text, or the count as text

def title_words(question_forms: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]: ...   # (kept, dropped)
def signals(title: str | None, abstract: str | None, reference_count: int | None, words: tuple[str, ...]) -> list[SurveySignal]: ...
```

Kurallar:

- Eşleşme büyük/küçük harfe duyarsız ve **sözcük sınırında**dır; "state of the art" tireli yazımı da tutar. Başlık, `record_identity.comparable_title`'ın HTML/LaTeX temizliğinden geçmiş haliyle okunur (yeni normalleştirici yazılmaz).
- **Sorunun kendi sözcüğü sinyal değildir.** Güçlü sözcüklerden biri araştırmanın sorguya giren terimlerinde ya da yan listesinde (iddia, dışlama) sözcük sınırında geçiyorsa o araştırmada listeden düşer (`title_words` → `dropped`). Gerekçe: "code review" ya da "tutorial dialogue" soran bir araştırmada bu sözcük konunun kendisidir ve konunun bütün makalelerini tarama listesinden çıkarırdı. Liste alan-bağımsız kalır; düşen sözcük protokole yazılır.
- Zayıf başlık sözcükleri (recent advances, trends, challenges, perspective, vision, future directions, open problems) için kod **yazılmaz**: tek başına hiçbir şey işaretlemezler (SW5.2) ve 80 referanslı birleşik kural kabul edilmedi.
- Özet yoksa özet sinyali, sayı yoksa sayı sinyali yoktur. Sıra sabittir: başlık, özet, sayı.

- [ ] **Tests first** (iki alandan SYNTHETIC başlıklar): her güçlü sözcük tutar; "previewing", "reviewer" tutmaz; "Recent advances in …" tek başına işaret almaz; "state-of-the-art" tutar; özet deseni tutar, özet yokken yok; 149 yok, 150 var, `None` yok; sorusu "code review" içeren araştırmada "review" düşer ve "A survey of code review" yine `survey` ile tutar; çıktı sırası kararlı.

## Task 3: `providers/lookup.py` — DOI ile iki istemci

`common.send`'e `json_body: Any = None` eklenir: verilirse `client.post(url, params=params, json=json_body, ...)`, verilmezse bugünkü `client.get`. S2 kapısı (`SEMANTIC_SCHOLAR_PACER`) ve 429 yeniden denemeleri aynı yoldan geçer; mevcut çağrıların hiçbiri değişmez.

```python
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_LOOKUP_FIELDS = "externalIds,abstract,referenceCount"
S2_LOOKUP_BATCH = 200          # ids per request; the endpoint takes up to 500
CROSSREF_WORK_URL = "https://api.crossref.org/works/"

@dataclass
class LookupAnswer:
    status: str                      # "found" | "not_found" | "failed"
    abstract: str | None = None
    reference_count: int | None = None
    linked_dois: list[str] = field(default_factory=list)   # DOIs the source names as another version of this record
    paper_id: str | None = None      # Semantic Scholar only

async def semantic_scholar_batch(client, dois: list[str], api_key) -> tuple[dict[str, LookupAnswer], SearchOutcome]: ...
async def crossref_work(client, doi: str, contact_email) -> tuple[LookupAnswer, SearchOutcome]: ...
```

- **S2:** tek POST, gövde `{"ids": [...]}`, `fields` sorgu parametresinde. Kimlik: DOI `10.48550/arxiv.` ile başlıyorsa `ARXIV:<kalanı>`, değilse `DOI:<doi>`. Yanıt, girdiyle aynı sırada bir listedir; `null` öğe `not_found`'dur. `externalIds.DOI` sorulan kaydın kendi DOI'sinden **farklıysa** `linked_dois`'e girer (normalleştirilmiş). Bütün istek başarısızsa partideki her kayıt `failed`'dir. `unstated_wait=semantic_scholar.UNSTATED_RATE_LIMIT_WAIT`.
- **Crossref:** `GET /works/<yüzde-kodlanmış doi>`, `mailto` ile. HTTP 404 `not_found`'dur, `failed` değil (`send` bunu `failed` diye sınıflar; burada `http_status`'a bakılır). Özet `crossref.strip_markup`'tan geçer. `relation["is-preprint-of"]` ve `relation["has-preprint"]` içindeki `id-type == "doi"` kimlikleri okunur: ilki `linked_dois`'e girer; ikincisi için yanıt `has_preprint: list[str]` alanını da taşır (Task 6 onu karşı kayda yazar). `reference-count` okunur.
- Uygulayan, uç noktayı, 500'lük sınırı, `null` öğeyi, kimlik öneklerini ve `relation` biçimini **sağlayıcı belgesinden** doğrular (S2 Academic Graph API, "paper/batch"; Crossref REST API, "works/{doi}" ve "relation") ve tarihini modül docstring'ine yazar, diğer sağlayıcı modülleri gibi. Belge farklı diyorsa belge kazanır ve son iletide söylenir. Canlı istek yalnızca Task 8'de.

- [ ] **Tests first** (mock taşıyıcı): S2 kimlik önekleri; `null` öğe → `not_found`; özetsiz ama bulunan kayıt → `found`, `abstract is None`; farklı `externalIds.DOI` → `linked_dois`, aynısı → boş; 429 üç kez → partinin tamamı `failed`, `outcome.retries == 2`; S2 isteği D67 kapısından geçer (mevcut pacing testinin kalıbı); Crossref 404 → `not_found`; JATS işaretlemesi temizlenir; iki `relation` yönü; DOI yolu yüzde-kodlanır.

## Task 4: `workflow/lookups.py` — plan, sorma, saklama

Migration `0043` (tek dosya):

```sql
-- What a second source answered when it was asked about one record by DOI. Library-wide, as links are (D46): a
-- record is asked once per source, by whichever research asks first. A 'failed' row is asked again; the others are not.
CREATE TABLE record_lookups (
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  provider TEXT NOT NULL CHECK (provider IN ('semantic_scholar', 'crossref')),
  status TEXT NOT NULL CHECK (status IN ('found', 'not_found', 'failed')),
  had_abstract INTEGER NOT NULL CHECK (had_abstract IN (0, 1)),
  step_id TEXT,
  asked_at TEXT NOT NULL,
  PRIMARY KEY (source_version_id, provider)
);
-- A routing label code put on a record under one research's protocol (SW5.4). It removes nothing.
CREATE TABLE record_flags (
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  flag TEXT NOT NULL,
  evidence TEXT NOT NULL,
  step_id TEXT,
  protocol_hash TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (research_id, scope_revision, source_version_id, flag)
);
ALTER TABLE source_versions ADD COLUMN reference_count INTEGER;
```

Aynı dosyada `record_links` yeniden kurulur: `source` CHECK'i `('text', 'arxiv_doi', 'semantic_scholar', 'crossref_relation')` olur (0039'daki yorum bunu bu dilime bırakmıştı). Kalıp: dilim 02'nin `selections` yeniden kurulumu — yeni tablo, satırları kopyala, eskisini düşür, yeniden adlandır, iki indeksi yeniden kur; önce `grep -n "REFERENCES record_links" backend/deixis/storage/migrations/*.sql` ile yabancı anahtar olmadığını doğrula. `purge_research` ve `purge_sources`: `record_flags` araştırma tabloları listesine, `record_lookups` kaynak silinirken `record_links` ile aynı yere eklenir.

Sabitler (hepsi `THRESHOLDS`'ta ve protokolün `thresholds.lookup` alanında):

```python
MAX_LOOKUP_REQUESTS = 200    # planned requests of one run over both sources; hand-picked, not measured
CROSSREF_CHUNK = 25          # Crossref requests that share one step
```

Akış, `_discovery`'nin `sw` dalında, ikinci tur döngüsünden **sonra** ve `stage="screening"`'den önce (Task 5 ve 6 aynı bloktadır):

1. **`lookup_plan:semantic_scholar`** (kod adımı). Kimler: bu kapsam revizyonunun adayları (`store.candidates(rid, revision)`), `store.candidates` sırasıyla, **iş başları önce**, sonra diğer sürümler; DOI'si olan ve şu ikisinden biri olan kayıt: (a) özeti yok ve başlığında güçlü sözcük **yok** (başlık derlemesi listeden çıkacağı için özeti sorulmaz), (b) `record_kind == "preprint"` (bağlantı için). `record_lookups`'ta bu sağlayıcı için `found` ya da `not_found` satırı olan kayıt plana girmez. Plan `S2_LOOKUP_BATCH`'lik partilere bölünür; parti sayısı `MAX_LOOKUP_REQUESTS`'i aşarsa sondan kesilir. Saklı çıktı: `{"batches": [[{"source_version_id", "doi"}, ...], ...], "outside_limit": n, "skipped": null | "out_of_scope"}`.
2. **`record_lookup:semantic_scholar:<n>`**, parti başına bir adım. Yanıt ham yük olarak aramalardaki gibi `payloads_dir/<step_id>.json`'a yazılır. Her kayıt için **tek kısa işlemde**: `record_lookups` satırı (`INSERT OR REPLACE`; yalnızca `failed` satırın üzerine yazılır), özet geldiyse ve kayıtta özet yoksa `_insert_passage(..., "abstract", ..., abstract_origin="lookup_semantic_scholar", payload_ref=<yük dosyası>)`, referans sayısı boşsa doldurulur, `linked_dois` `identifier_mappings`'e `scheme = 'linked_doi'`, `provider = 'semantic_scholar'` ile `INSERT OR IGNORE` yazılır. `await` işlem dışındadır. Adım, istek sonuçlanınca `succeeded` olur (parti `failed` dönse bile: başarısızlık satırlarda durur ve koşu sürer); çıktısı `{"asked", "found", "abstracts_filled", "links", "failed"}` sayılarıdır.
3. **`lookup_plan:crossref`** (kod adımı), S2 partileri bittikten sonra: plan (a) grubundan **hâlâ** özetsiz olan ve Crossref'te `found`/`not_found` satırı olmayan kayıtlar, aynı sırayla; S2'de `failed` olan kayıt da buraya girer (S2'nin başarısızlığı Crossref'i engellemez). İzin: `MAX_LOOKUP_REQUESTS − S2 parti sayısı`; fazlası `outside_limit`. `CROSSREF_CHUNK`'lık parçalar saklanır.
4. **`record_lookup:crossref:<n>`**, parça başına bir adım; parçanın içinde kayıt başına bir istek, her yanıt kendi kısa işleminde yukarıdaki gibi yazılır (`abstract_origin="lookup_crossref_jats"`, `provider = 'crossref'`; `has_preprint` DOI'si kütüphanede bir kaydın `doi` eşlemesiyse `linked_doi` **o kayda**, sorulan kaydın DOI'siyle yazılır). Parça yarıda kesilip yeniden koşarsa `record_lookups` satırı olan kayıt yeniden sorulmaz. Her parçadan sonra `_checkpoint`.

Kurallar:

- **Kapsam:** bir kaynağa yalnızca `scope["providers"]` içindeyse ve `access_mode() != "not_configured"` ise sorulur (`_count_probe`'un kuralı). Değilse plan adımı `skipped = "out_of_scope"` yazar ve istek atılmaz.
- **İstek sayımı:** her istek ve her yeniden deneme `store.add_usage(run_id, "lookup_requests")` ile sayılır (`outcome.retries` dâhil). `provider_requests` sayacına **girmez**: böylece sürdürülen koşuda başarısız aramaları yeniden deneyen `_search`'ün izni sorgu istekleriyle dolmuş olmaz (04c incelemesinin bulgusu). Üst sınır planlanan istekleri sayar; yeniden denemeler istek başına en çok `MAX_RATE_LIMIT_RETRIES` ile yapıca sınırlıdır, bu yüzden ayrı bir izin ve `budget_exhausted` yolu yoktur. En kötü durumun sayısı (`MAX_LOOKUP_REQUESTS × (1 + MAX_RATE_LIMIT_RETRIES)`) protokole `thresholds.lookup.max_requests_with_retries` diye yazılır.
- **Tekrar:** sürdürülen koşu `succeeded` adımı atlar, plan saklı çıktıdan okunur, hiçbir istek iki kez atılmaz. Aynı kapsamda ikinci keşif koşusu yeni plan kurar ama `record_lookups` yanıtlanmış kayıtları dışarıda bırakır: yalnızca `failed` kalanlar, sınırın dışında kalanlar ve yeni bulunan kayıtlar sorulur.
- **Geri besleme yok:** bu blok iki tur da bittikten sonra koşar ve aramaya hiçbir şey vermez; sonraki bir koşunun genişlemesi (04b) başlık ve yazar sözcüklerinden öğrenir, bu dilim ikisini de yazmaz.

- [ ] **Tests first** (`tests/test_record_lookups.py`, depo düzeyi; `tests/test_lookup_flow.py`, `tests/test_expansion_flow.py` kalıbıyla akış düzeyi, mock taşıyıcı OpenAlex aramasını, S2 partisini ve Crossref'i sunar):
  - **Kabul 1:** S2'nin verdiği özet `lookup_semantic_scholar` kökeniyle, S2'nin vermediği ve Crossref'in verdiği `lookup_crossref_jats` kökeniyle saklanır; yük dosyası `payload_ref`'te durur.
  - **Kabul 2:** S2 her istekte 429 verir → kayıtlar `failed`, Crossref yine sorulur, koşu taramaya geçer; Crossref 500 verir → o kayıt `failed`, parçanın kalanı sorulur.
  - **Kabul 3:** parçanın ortasında duraklatılıp sürdürülen koşu hiçbir DOI'yi iki kez sormaz (istek sayacıyla sına); aynı kapsamda ikinci keşif koşusu yanıtlanmış hiçbir kaydı sormaz, `failed` kalanı sorar.
  - sınırın dışında kalan sayılır (test `MAX_LOOKUP_REQUESTS`'i küçültür); başlığı güçlü sözcük taşıyan özetsiz kayıt özet için sorulmaz; DOI'siz kayıt sorulmaz; kapsam dışı kaynak hiç istek almaz; `lookup_requests` yeniden denemeleri de sayar ve `provider_requests` değişmez; dolu özetin üzerine yazılmaz; `legacy` araştırmada hiçbir adım açılmaz ve hiçbir sorgu isteği çıkmaz; purge iki tabloyu da temizler.

## Task 5: işaretler, karar satırları, tarama süzgeci

`domain/reason_codes.py`'ye iki kod (mevcut kodların anlamı değişmez):

```python
# A strong title word routes the record out of screening and into the seed pool; it is not "out of scope" (SW5.4, SW9.3).
ReasonCode("survey_title_word", "abstract", "unresolved", "code", "seed_pool"),
# Both second sources answered without an abstract, or the record has no DOI to ask by; only a full text can decide it.
ReasonCode("abstract_not_found", "abstract", "unresolved", "code", "fulltext_fetch"),
```

**`record_flags` kod adımı** (`workflow/lookups.py::flag_and_decide`, sorgulardan ve Task 6'dan sonra). Revizyonun bütün aday kayıtları (her sürüm) için `survey.signals` koşar:

- Her sinyal `record_flags`'e `INSERT OR IGNORE` ile yazılır (üçü de; dilim 15 tohum havuzunu bu tablodan okuyacak). Havuz kurulmaz.
- Kaydın **isteyeceği** özet-aşaması kodu, sırayla: başlık sinyali varsa `survey_title_word`; yoksa ve özeti yoksa — DOI'si yoksa ya da kapsamdaki her kaynak `found`/`not_found` dediyse (ya da kapsamda kaynak yoksa) `abstract_not_found`, aksi halde (sınırın dışında kaldı, `failed`) `no_abstract`; yoksa ve özeti var ama güncel kararı `no_abstract` ya da `abstract_not_found` ise `abstract_not_proposed` (özet sonradan geldi, satır yalan söylemesin); bunların hiçbiri değilse karar yazılmaz. Özet ifadesi ve referans sayısı **karar yazmaz**: kayıt aday kalır.
- `DecisionStore.record` yalnızca şu durumda çağrılır: güncel özet kararı yok, ya da güncel karar bu dört koddan biri **ve** istenen koddan farklı. Aynı kod güncelse hiçbir şey yazılmaz (yeni koşunun `step_id`'si ve protokol özeti farklı diye satır kapatıp aynısını yeniden yazmak, 03 incelemesinde bulunan kusurdur). Başka bir adımın koduna (dilim 09'un kodları) dokunulmaz. `note`: `abstract_not_found` için `"no_doi"` ya da sorulan kaynaklar.
- **`derive_selection` çağrılmaz.** Bu dilimin bütün sonuçları `unresolved`'dır, o da `pending`'dir, yani seçimin zaten bulunduğu durum; türetilecek bir şey yoktur. Sonuç: `selections.origin = 'code_rule'` bu dilimde hiçbir satıra yazılmaz ve API'ye ulaşmaz. `apps/web/src/api.ts:117`'deki birleşim tipi derleme zamanıdır; arayüzün bu alanı okuduğu tek yer (`Transcript.tsx:283`) yalnızca `=== 'user'` karşılaştırır, yani değer geldiğinde de çalışma zamanında yanlış saymaz. Tipi, `apps/web`'e dokunan ilk dilim (08) genişletir; ilk türeten dilim (09) arka uçtur ve bunu beklemek zorunda değildir.
- Adım çıktısı: işaret başına sayı, kod başına yazılan karar sayısı, `reference_count_unknown` (sayısı olmayan kayıt), `held_from_screening`.

**Tarama süzgeci** (`_discovery`, yalnızca `sw`): tarama listesinden iki tür iş başı çıkar — (1) **kendi** özeti olmayan baş (model `exclude` önerisi `selections`'a doğrudan yazıldığı için özetsiz kaydı kapsam dışı yapabilecek tek yol budur); (2) araştırmadaki **her** sürümünün güncel özet kararı `survey_title_word` olan iş (SW9.4: tek sürümdeki işaret işi düşürmez; sürüm kümesi `work_outcome`'ın okuduğu kümedir). Çıkan kayıt `pending` kalır, gizlenmez, silinmez; kullanıcı onu dahil edebilir. Seçimi `user` olan kayıt zaten taranmıyor. Süzgeç `max_candidates` kesiminden **önce** uygulanır.

- [ ] **Tests first:**
  - **Kabul (ana plan):** her öneride `exclude` diyen betikli modelle `sw` koşusu: özetsiz kayıt tarama adımının girdisinde yok, seçimi `pending`, güncel kararı `no_abstract` ya da `abstract_not_found`; hiçbir yoldan `excluded` olmaz.
  - başlık derlemesi tarama girdisinde yok, kararı `survey_title_word`, sonraki adımı `seed_pool`, seçimi değişmemiş (`state`, `origin`, `version` aynı); özet ifadesi ya da 150+ referans taşıyan kayıt işaret alır **ve** taranır; ön baskısı "survey" başlıklı, yayımlanmış sürümü başka başlıklı iş taranır; kullanıcının dahil ettiği başlık derlemesi `included` kalır ve karar satırı yine yazılır; ikinci keşif koşusu yeni karar satırı ve yeni işaret satırı yazmaz (satır sayısıyla sına); sonradan özeti gelen kaydın kararı `abstract_not_proposed` olur ve kayıt taranır; koşudan sonra hiçbir seçimin kökeni `code_rule` değil; `legacy` araştırmada hiçbir karar ve işaret satırı yok.
  - `tests/determinism_stages.py`'ye `survey_flags` aşaması: sabit SYNTHETIC kayıtlarla `signals` + istenen kod; iki hash tohumu, iki karışım, tek özet.

## Task 6: dış bağlantılar iki yönde (SW6.4)

Bir kaydın **adlandırdığı DOI'ler**: `identifier_mappings`'te o kayda yazılı `published_doi` (arXiv'in yazar alanı, mevcut) ve `linked_doi` (S2, Crossref; bu dilim) değerleri. `linked_doi`'yi yalnızca `sw` yolu okur; `legacy`'nin `_flag_suspected_duplicates`'i `published_doi` okumaya devam eder ve hiçbir şey görmez.

`classify_pair` iki anahtar sözcük argümanı kazanır; on altı satırın hiçbiri değişmez:

- `external_link: bool = False` — satır 5 genişler: `names_published_doi or external_link`, türler `{preprint, published}` → `same_work`, `merge=True`; kural adı yazar alanı için `preprint_names_published_doi` (aynı), dış kaynak için `external_link_names_published_doi`. Başlık benzerliği aranmaz (SW6.4: "even when the title differs").
- `names_other_doi: bool = False` — yeni satır 12b, yıl farkı satırından (12) sonra, 13'ten önce: `would_merge and names_other_doi and set(kinds) == {"preprint", "published"}` → `related_suspected`, kural `external_link_names_other_doi`, birleşme yok.

`links.py`:

- `link_records` her çift için `names_other_doi`'yi hesaplar: ön baskının adlandırdığı DOI'ler boş değil **ve** yayımlanmış kaydın DOI'si aralarında yok. Böylece arXiv yazar alanının engelleme yönü arama anında da çalışır (bugün yalnızca doğruluyordu).
- Yeni `link_external(store, research_id)` (çağıran işlemi tutar): bu araştırmanın adayları arasında, birinin `linked_doi`'si diğerinin `doi` eşlemesi olan her çift, **kimlik sırasıyla**. Bir kaydın adlandırdığı DOI'ler (iki şema birlikte) **birden fazla farklı değer** ise hiçbiri birleştirmeyi doğrulamaz: havuzdaki her eşi `related_suspected`, kural `external_links_disagree` olarak saklanır. Aksi halde `classify_pair(..., external_link=True)` → `save_link(..., source="semantic_scholar" | "crossref_relation")`. Birleştirme `save_link`'in **aynı** yolundan geçer: iki yayımlanmış kayıt koruması, `undone` belleği ve `undo_json` aynen geçerlidir; kullanıcının geri aldığı çift yeniden birleşmez.
- **`external_links` kod adımı** (`_discovery`, sorgulardan sonra, `record_flags`'ten önce), tek işlemde: önce bu koşuda özeti doldurulan kayıtlar için `link_records(store, rid, filled_svids)` (özet gelince satır 13'ün hükmü değişebilir; `save_link` aynı hükmü yeniden yazmaz, güçlü hüküm eskisini `superseded` kapatır), sonra `link_external`. Çıktı: `{"confirmed", "blocked", "disagree", "contradicted_merges": [[a, b], ...]}`.
- **Çoktan birleşmiş çifti dış bağlantı ayırmaz.** Arama anında metinle birleşmiş bir çiftin ön baskısı sonradan başka bir DOI adlandırırsa çift `contradicted_merges`'e yazılır ve birleşik kalır: dilim 03'ün kuralı "birleşmiş bağlantıyı yalnızca kullanıcı geri alır" der ve `undone` kullanıcının kararıdır, kodun değil. Ölçümde bu, 181 çiftin yaklaşık 1'idir (12 aykırı bağlantının 11'i zaten 0,85'in altında).

**03'ün açık kalanı, açıkça:** "iki DOI altında tek makale" olan 23 `extended_version` çiftini bu dilim **çözmez**. İkisi de yayımlanmış kayıttır; SW6.5 ve `save_link` koruması iki yayımlanmış kaydı hiçbir yoldan tek işe koymaz, bir dış bağlantı da koymaz. Çiftler iki iş olarak kalır ve iki kez taranır; tek sayılmaları dilim 20'dedir. Task 8 yalnızca kanıt toplar: S2 iki DOI'yi aynı `paperId`'ye çözüyor mu.

- [ ] **Tests first** (`tests/test_external_links.py`; `tests/test_record_links.py` kalıbı): başlığı tümüyle değişmiş ön baskı + yayımlanmış kayıt `linked_doi` ile birleşir, satır `source = 'semantic_scholar'`, kural `external_link_names_published_doi`, `undo_link` işi geri ayırır; metinle birleşecek çift, ön baskı başka DOI adlandırınca `related_suspected` / `external_link_names_other_doi` kalır (hem arXiv alanıyla arama anında, hem `linked_doi` ile); iki kaynak iki ayrı DOI adlandırırsa birleşme yok; iki yayımlanmış kayıt dış bağlantıyla da birleşmez (`work_already_has_published`); kullanıcının geri aldığı çift `link_external` ile yeniden birleşmez; `link_external` iki kez çağrılınca satır eklenmez; özeti sonradan dolan çift yeniden sınıflanır ve eski satır `superseded` kapanır; çoktan birleşmiş aykırı çift birleşik kalır ve çıktıda sayılır; `legacy` araştırma `linked_doi` eşlemesi olan kayıtla bugünkü gibi davranır; dilim 03'ün testleri dokunulmadan geçer; `tests/determinism_stages.py`'deki bağlantı aşaması `linked_doi` satırlarıyla iki karışımda tek özet verir.

## Task 7: protokol

`build_protocol`, `sw` gövdesine ilk dondurmada (yeni revizyon açılmaz; değerler aramadan önce bilinir): `thresholds.survey = {"reference_count": 150}`, `thresholds.lookup = lookups.THRESHOLDS`, ve gövdeye `survey = {"title_words": [...kalan], "dropped_title_words": [...], "abstract_patterns": [...]}`. `legacy` gövdesi ve özeti değişmez.

- [ ] **Tests first** (`tests/test_protocol_record.py`): `sw` gövdesi üç alanı taşır; sorusunda güçlü sözcük geçen araştırmada sözcük `dropped_title_words`'te; `legacy` gövdesinin özeti bu dilimden önceki ile aynı; aynı girdiyle iki kurulum tek özet.

## Task 8: canlı sayım ve dilimi kapat

- [ ] **Canlı sayım, iki konuda (zorunlu; ağ yoksa söyle ve dilimi yine bitir).** Ürün veritabanına ve 8765'teki servise dokunmadan, yalnızca `providers/lookup.py` işlevleriyle küçük bir betik: `.local/quantum-rank-fusion-2026-09-18/round.json` (`docs`, özet alanı `abs`; 107 özetsiz, 105'i DOI'li) ve `.local/second-topic-packet-size-2026-09-20/round.json` (`results`, `abstract_inverted_index`; 129 özetsiz, 122'si DOI'li). Her konuda: özetsiz DOI'ler S2'ye tek partide, S2'nin vermediği her biri Crossref'e. Yaz: sorulan, S2'nin doldurduğu, Crossref'in doldurduğu, hâlâ özetsiz kalan, `failed`, istek ve yeniden deneme sayısı, süre. Ek olarak kuantumdaki 304 arXiv DOI'li kayıt için S2'nin kaçında başka bir DOI adlandırdığı (iki parti), ve `.local/sw-slice03-pairs-2026-09-20/pairs.csv`'deki 23 `extended_version` çiftinin kaçında iki DOI'nin aynı `paperId`'ye çözüldüğü (tek parti). Toplam en çok ~235 istek. Çıktı `.local/sw-abstract-lookup-<tarih>/` altına; betik de oraya. Bu sayım ölçülmeyeni sayar, kalite yargısı değildir. **Sonuca göre hiçbir eşiği, parti boyunu ya da sınırı değiştirme**; sonuç kötüyse (ör. S2 anahtarsız havuzda hiç yanıt vermiyor) son iletinin başında söyle.
- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `git diff --check`.
- [ ] `docs/decisions.md` en üste `## D<NN> — Flag surveys by title, abstract and reference count, ask a second source for a missing abstract by DOI, and let an external link confirm or block a merge`. Limits adıyla söylemeli: yalnızca `sw`; tohum havuzu yok (dilim 15), işaret yalnızca saklanıyor; SW5.4'ün "tam metni sıkı ipucu kapısını geçen derleme insan kuyruğuna gider" yolu yok (dilim 12/16); başlık derlemesi `unresolved` sayılıyor ve bunu hiçbir ekran göstermiyor; sözcük listeleri ve 150 eşiği tek konuda seçildi, etiket bir modelin eski yargısıydı; sorunun kendi sözcüğünü listeden düşürme kuralı ölçülmedi; referans sayısı yalnızca OpenAlex'in `sw` isteğinden ve sorgu yanıtlarından geliyor, sayısı olmayan kayıtta sinyal yok; S2 `publicationTypes` kullanılmadı; ikinci kaynağın doldurma oranı yalnızca iki havuzda sayıldı (sayılarıyla); `MAX_LOOKUP_REQUESTS` elle seçildi, sınırın dışında kalan kayıt `no_abstract` ile bekler ve ancak yeni bir keşif koşusu sorar; `not_found` yanıtı bir daha sorulmaz, S2'nin çifti sonradan bağlaması kaçar; S2 anahtarsız havuzda sık 429 verir (D67) ve o zaman iş Crossref'e kalır; Crossref ilişkisi yalnızca özet için zaten sorulan kayıtlarda okunuyor; S2 arama kayıtlarının `externalIds`'i kullanılmadı; çoktan birleşmiş aykırı çift ayrılmıyor, yalnızca sayılıyor; iki DOI altındaki tek makale (iki yayımlanmış kayıt) çözülmedi; kendi özeti olmayan baş, başka sürümünün özeti olsa da taramadan tutuluyor (dilim 09 iş düzeyinde okuyacak); bağlantılar, işaretler ve kararlar hiçbir ekranda yok; `selections.origin = 'code_rule'` hâlâ hiçbir satırda yok; testler SYNTHETIC ve ağsız.
- [ ] SW belgesinde SW5, SW6 (madde 4) ve SW9 (madde 3) **Status** satırlarına birer cümle. `sw-status.md` satır 05: `uygulandı, inceleme bekliyor` + açık kalanlar + canlı sayımın özeti.
- [ ] `git pull --ff-only`, tek commit, `git push origin main` (ana plan §2.11).

**Bölünme noktası (plan sohbetinin kararı).** Bu dilim 04b'den büyüktür. Oturum uzarsa Task 6 atlanabilir: Task 1–5, 7 ve 8 kendi başına tamdır (`linked_doi` eşlemeleri yazılır ama okunmaz; migration `record_links`'i yine yeniden kurar). O durumda tek commit yine atılır, satır 05'e "Task 6 yapılmadı" yazılır ve dış bağlantılar `05b` olarak ana tabloya eklenir. Başka hiçbir yerden bölünmez.

## Son ileti

Değişen ve eklenen dosyalar; temel ve son test sayıları ve komut; canlı sayımın iki konudaki sayıları (ve 304 ile 23'lük ek sayımlar); S2 parti uç noktasının ve Crossref alanlarının belgeden nasıl doğrulandığı; yazıldığı gibi yapılamayan her şey ve seçilen her sapma; fikstürüne özet eklenmek zorunda kalınan mevcut `sw` testleri (beklentisi değişen test olmamalı); yapılmayanlar; dokunulan kanıt sınırları (beklenen: özetin kökeni iki yeni değer kazanır; iş birleşmeleri kütüphane genelindedir ve `legacy` araştırmada da görünür, D72'deki gibi; tarama modeline giden liste `sw`'de daralır); canlı servise dokunulmadığı; commit özeti.

## Açık noktalar

- **Karar (plan sohbeti, 21 Eylül 2026; dilim 02'nin "dilim 05'te sahibe sorulacak" dediği soru): başlık derlemesi özet aşamasında `unresolved` alır**, kod `survey_title_word`, sonraki adım `seed_pool`. `candidate` olamaz (SW "aday listesinden çıkar" der); `out_of_scope` olamaz: seçimde `excluded` görünürdü, akış sayılarında konu içi bir derlemeyi kapsam dışı sayardı ve SW5.4 "yönlendirme etiketidir, silme değildir; derleme özgün bir model de önerebilir" der. Sahip başka türlü isterse değişiklik `reason_codes.py`'de tek satırdır, ama yazılmış karar satırları eski kodu taşır.
- **Ekleme (SW metninde yok):** sorunun kendi sözcüğü olan güçlü sözcük o araştırmada listeden düşer. Alan-bağımsız bir listenin "review" ya da "tutorial" sözcüğünü konu edinen bir soruda bütün konuyu taramadan çıkarmasını önler. Ölçülmedi.
- **Yorum:** SW5.5 "kayıt" der; sorgu iş başlarını önce sorar ama her sürümü sorar, çünkü tarama başın **kendi** özetini okur. Başka sürümünde özet olan işi taramadan tutmak bir kayıptır (kayıt `pending` bekler, silinmez); dilim 09 özeti iş düzeyinde okuyunca kalkar.
- **Yorum:** ikinci kaynaklara yalnızca araştırmanın kapsamındaysalar sorulur (`_count_probe` ile aynı kural). Kullanıcı Crossref'i kapattıysa DOI'ler Crossref'e gitmez; bedeli, o araştırmada doldurma oranının düşmesidir.
- **Yorum:** sorgu istekleri `provider_requests`'e değil kendi sayacına girer. Arayüzde görünmez (dilim 08 / 20).
- Tek bir S2 partisinin başarısızlığı 200 kaydı birden `failed` bırakır. Parti küçültmek istek sayısını ve 429 olasılığını artırır; canlı sayım hangisinin baskın olduğunu gösterecek, değer ona göre **bu dilimde değişmez**.

## İnceleme türü: neden "tam"

Ana tablo 05'i `toplu` sayıyordu. Üç nedenle `tam` öneriliyor ve satıra öyle yazıldı: (1) `stage_decisions`'a yazan **ilk** dilimdir; yanlış kod ya da yinelenen satır sessizce birikir ve sonraki her dilim (09, 12, 16) bu satırların üstüne kurar. (2) Birleştirme yoluna dokunur ve işler kütüphane genelindedir: yanlış bir dış bağlantı birleşmesi `legacy` araştırmalarda da görünür. (3) Tarama modeline giden listeyi değiştirir; burada bir hata kaydı görünmez kılmaz ama sessizce taranmadan bırakır. Sahibin kuralı da aynı yere varıyor: "yanlış kararın sessizce kanıtı bozduğu dilimler" tam incelenir. İnceleyen özellikle şunlara baksın: ikinci keşif koşusunda satır sayıları, kullanıcının seçtiği kayıtlar, `undone` çiftler, parça ortasında sürdürme, ve `legacy` isteğinin bayt bayt aynı kaldığı.
