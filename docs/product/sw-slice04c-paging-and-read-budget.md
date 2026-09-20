# SW dilim 04c — `sw` aramasında sayfalama ve okuma bütçesi: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir; özellikle §2.4, §2.5, §2.7). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): SW7 bağlamı (ilk tur havuzu 1.369 kayıt), SW2 madde 3. **Önkoşul:** dilim 04a (D73) kapandı. **Tür:** Kur. Okuma sınırı elle seçilmiştir; ölçümü dilim 24'tedir.

**Dilim 04d:** uygulandı (`d42beda`, D74), tam incelemesi bekliyor; `flow.py`'de `_vocabulary` ve yeni `_vocabulary_labels` çevresine, `protocol.py`'de terim alanlarına dokundu. İnceleme sohbeti aynı yerlere düzeltme commit'i atabilir. Bu dilim `flow.py`'de yalnızca üç yere dokunur (aşağıda "Dokunma haritası"); `_vocabulary`, `_vocabulary_labels`, `_count_probe`, `_searchable`, `_model_step` ve `_step_input`'a dokunmaz. Başlamadan önce ve commit'ten hemen önce `git pull --ff-only` yapılır.

**Goal:** `sw` akışı sağlayıcı başına tek geniş sorgu atar (04a), ama `_search` sorgu başına en çok `results_per_query` (≤ 25) kayıt okur. OpenAlex geçit sorgusu 5.000 kayda kadar "yönetilebilir" sayılırken bunun 25'ini okumak geniş sorguyu anlamsız kılar; SW7'nin sıraladığı ilk tur havuzu 1.369 kayıttı. Bu dilim, yalnızca `sw` araştırmalarında, bir sorgunun sonuçlarını sayfa sayfa okur, okumayı tek bir adlı sınırla durdurur ve okunmayanı sayar. `legacy` araştırmada hiçbir şey değişmez.

**Architecture:** Bugün hiçbir sağlayıcı işlevi sayfalamaz: hepsi tek istek atar ve ilk `limit` kaydı döndürür. Her sağlayıcının arama işlevi isteğe bağlı bir `cursor` argümanı alır ve `SearchOutcome.next_cursor` döndürür; `cursor=None` bugünkü isteği **bayt bayt aynı** üretir (`legacy` yolu). `flow._discovery`'nin arama döngüsü `sw` araştırmasında `_search` yerine yeni `_search_pages`'i çağırır; o da her sayfa için `_search`'ü bir `Page` ile çağırır. Her sayfa kendi `run_steps` satırıdır: ilk sayfa bugünkü anahtarı (`search:{index}`), sonrakiler `search:{index}:page:{n}` anahtarını taşır; tür hep `provider_search:{provider}`'dır, böylece D18'in `searched()` denetimi ve "Search again" yeniden denemesi değişmeden çalışır. Bir sonraki sayfanın imleci, önceki sayfanın **saklı adım çıktısından** okunur: sürdürülen koşu okunmuş sayfayı yeniden istemez. Her sayfa kendi `search_runs` satırını, kendi ham yük dosyasını ve kendi `record_search` işlemini yazar.

**Tech stack:** Python 3.12. Yeni bağımlılık yok.

## Global constraints

- `apps/web/`, `contracts/research/`, `methods/deixis-research/`, `backend/deixis/workflow/links.py` ve mevcut migration dosyalarına dokunma. `skill_package_hash` değişmez.
- `legacy` araştırmanın davranışı, bütçeleri (`results_per_query`, `max_provider_requests`, `core_depth`) ve mevcut test beklentileri değişmez. Sağlayıcıya `cursor` verilmediğinde istek parametreleri ve `request_description` bugünküyle aynıdır; mevcut sağlayıcı testleri buna tanıktır.
- Tarama hâlâ `budget["max_candidates"]` ile kesilir (`_discovery`'deki `[: budget["max_candidates"]]`). Onu `sw` için kaldıran dilim 09'dur (K3). **Dokunma.** Sonuç: bu dilimden sonra bir `sw` koşusu 1.500 aday bulur ama en çok 250'sini tarar; bu bilinen ve kayda geçen bir ara durumdur.
- Okuma sınırı **kayıt silmez**: sınır yalnızca daha fazla sayfa istememektir. Okunan her kayıt aday olur; okunmayanlar sayılır.
- Testlerde ağ yok (mock `httpx` taşıyıcısı) ve testler gerçek beklemez (`page_gap` testte 0 ya da `asyncio.sleep` yamalı).
- Son migration `0040`, son karar `D74`'tür (04d); bu dilim `0041` ve `D75`'i kullanır. Başlamadan önce kontrol et.

## Sağlayıcı sayfalama tablosu

Kod okundu (21 Eylül 2026): bugün hiçbiri sayfalamıyor. API'lerin sayfalama kuralı aşağıdadır; uygulayan her satırı sağlayıcının kendi belgesinden doğrular ve modülün docstring'ine kaynağıyla yazar. Belgeyle çelişen satır varsa **belge kazanır** ve son iletide söylenir.

| Sağlayıcı | Sayfa boyu (`MAX_RESULTS`) | Kip | İstek | Sonraki imleç | Erişilebilir üst sınır |
|---|---|---|---|---|---|
| `openalex`, `biorxiv` (OpenAlex üzerinden) | 200 | `cursor` | `cursor=*`, sonra `cursor=<meta.next_cursor>` | `meta.next_cursor` (`null` → bitti) | yok |
| `crossref` | 100 | `offset` | `offset=N` | `N + okunan` | 10.000 |
| `semantic_scholar` | 100 | `offset` | `offset=N` | yanıttaki `next`; yoksa bitti | **1.000** (`offset + limit`) |
| `arxiv` | 100 | `offset` | `start=N` (bugün sabit `0`) | `N + okunan` | sınırın üstünde |
| `pubmed` | 100 | `offset` | `esearch`'te `retstart=N` | `N + okunan` | 9.999 |
| `ieee_xplore` | 200 | `offset` | `start_record=N+1` (1 tabanlı; bugün sabit `1`) | `N + okunan` | sınırın üstünde |
| `scopus` | 25 | `offset` | `start=N` | `N + okunan` | 5.000 |
| `core` | 100 | `offset` | `offset=N` | `N + okunan` | 10.000 |
| `serpapi` | 20 | `single_page` | değişmez | hep `None` | — |

- Crossref imleç de sunar, ama imleci birkaç dakikada eskir; duraklatılıp saatler sonra sürdürülen koşu eskimiş imleçle başarısız olurdu. Bu yüzden Crossref `offset` ile okunur.
- SerpApi sayfalamayı destekler ama her sayfa ücretlidir ve tamamlayıcı kaynaktır (D13); tek sayfa okur ve bu `stop_reason = "single_page"` olarak kaydedilir. Plandaki "sayfalamayı desteklemeyen sağlayıcı tek sayfa okur" kuralının tek uygulaması budur.
- `offset` kipinde sayfa, `okunan < istenen` olduğunda ya da `N + okunan ≥ provider_total` olduğunda biter (`next_cursor = None`).
- arXiv istekler arasında 3 saniye ister ve 15 Eylül'de art arda istekleri reddetti (D18 bağlamı). Sayfalar arası bekleme `Connector.page_gap`'tir: arXiv `3.0`, diğerleri `0.0`. Semantic Scholar'ın kendi hız düzenleyicisi (`SEMANTIC_SCHOLAR_PACER`) zaten `send` içindedir.

## Dosya yapısı

Yeni: `backend/deixis/storage/migrations/0041_search_run_pages.sql`, `tests/test_search_paging.py`, `scripts/probes/time_link_records.py`.

Değişecek: `providers/common.py` (`FIRST_PAGE`, `SearchOutcome.next_cursor`), dokuz sağlayıcı modülü (`cursor` argümanı), `providers/registry.py` (`Connector.paging`, `max_reachable`, `page_gap`), `domain/rules.py` (`SW_READ_LIMIT`), `workflow/flow.py` (dokunma haritası), `workflow/store.py` (`record_search`: `first_rank`), `workflow/protocol.py` (`thresholds.search_read`), `workflow/views.py` (arama satırının yeni alanları, `counts["unread"]`), `tests/test_providers.py`, `tests/test_protocol_record.py`, `docs/decisions.md`, `docs/product/sw-status.md`.

### `flow.py` dokunma haritası

1. `_discovery`'deki arama döngüsünün gövdesi: `sw` ise `_search_pages`, değilse bugünkü `_search` çağrısı. Başka satır değişmez; `per_query` hesabı, `searched()`, `retry_failed` ve duraklatma kuralı aynen kalır.
2. `_search`: yeni, varsayılanı `None` olan `page` argümanı ve ona bağlı dört yer (adım anahtarı, istek izni, `connector.search` çağrısı, `search_fields` / adım çıktısı). `page is None` iken yürüyen kod bugünküyle aynıdır.
3. Yeni `_search_pages`, `_search`'ün **hemen altına** yazılır.

## Task 1: sağlayıcılara `cursor`

`providers/common.py`:

```python
FIRST_PAGE = "*"   # asks a provider for the first page of a paged read; an offset provider reads it as offset 0

@dataclass
class SearchOutcome:
    ...
    next_cursor: str | None = None   # what to pass for the next page; None when the provider has no more
```

Her arama işlevi (`openalex.search_works`, `biorxiv.search`, diğerlerinin `search`'ü) sona anahtar-sözcük argümanı `cursor: str | None = None` alır. `None`: bugünkü istek, `next_cursor` hep `None`. `FIRST_PAGE` ya da önceki sayfanın `next_cursor`'ı: tablodaki istek. `offset` kipinde imleç, ondalık yazılmış tamsayıdır; `FIRST_PAGE` sıfırdır; başka bir şey gelirse `ValueError` (kod hatasıdır, ağ hatası değil). `request_description` sayfalı istekte imleci ya da ofseti de taşır, sır taşımaz (`redact`). `registry.Connector` üç alan kazanır: `paging: str = "offset"` (`cursor` | `offset` | `single_page`), `max_reachable: int | None = None` (yalnızca Semantic Scholar: `1000`), `page_gap: float = 0.0` (yalnızca arXiv: `3.0`).

- [ ] **Tests first** (`tests/test_providers.py`, mock taşıyıcı; sağlayıcı başına): `cursor` verilmeyince istek parametreleri bugünküyle aynı (mevcut testler dokunulmadan geçer); `FIRST_PAGE` ilk sayfayı ister ve `next_cursor` döner; ikinci sayfa isteği tablodaki parametreyi taşır (IEEE'de `start_record = N + 1`); son sayfada `next_cursor is None`; OpenAlex `next_cursor: null` → `None`; Semantic Scholar'da `next` yoksa `None`; SerpApi her durumda `None`; bozuk `offset` imleci `ValueError`; anahtar açıklamada görünmez.

## Task 2: okuma sınırı, migration, `record_search`

`domain/rules.py`, `EffortBudget`'ın altına:

```python
# How many records one sw query reads across its pages. Hand-picked: above the 1,369-record first round SW7 ranked,
# below the vocabulary step's MANAGEABLE_TOTAL. It never drops a record that was read; what it leaves unread is counted.
SW_READ_LIMIT = 2_000
```

Tek sabittir; efor düzeyine göre değişmez ve `EffortBudget`'a alan eklenmez (koşunun saklı `budget` sözlüğü `legacy` ile aynı biçimde kalır).

Migration:

```sql
-- One sw query is read page by page (slice 04c). NULL on every legacy row.
ALTER TABLE search_runs ADD COLUMN page_number INTEGER;   -- 0 for the first page
ALTER TABLE search_runs ADD COLUMN read_limit INTEGER;    -- SW_READ_LIMIT as it was when the page was read
ALTER TABLE search_runs ADD COLUMN read_total INTEGER;    -- records read for this query up to and including this page
ALTER TABLE search_runs ADD COLUMN stop_reason TEXT;      -- NULL while another page follows
ALTER TABLE search_runs ADD COLUMN unread_count INTEGER;  -- set with stop_reason; NULL when the provider gave no total
```

`stop_reason`: `exhausted` (sağlayıcıda başka kayıt yok) · `read_limit` · `provider_cap` (`max_reachable`'a ulaşıldı) · `single_page` · `page_failed`. `unread_count = max(0, provider_total − read_total)`; `provider_total` bu sayfada yoksa önceki sayfanınki kullanılır; hiç bilinmiyorsa `NULL` kalır (**bilinmiyor, sıfır değil**). `exhausted`'ta da yazılır (çoğunlukla 0; sağlayıcının toplamı tahminse 0 olmayabilir ve bu görünmelidir).

`Store.record_search` isteğe bağlı `first_rank: int = 0` alır ve adayın sırasını `first_rank + rank` yazar: sayfalı okumada sıra sorgu içi sıradır, sayfa içi değil. Varsayılan bugünkü davranıştır.

- [ ] **Tests first:** migration uygulanır ve eski satırlar `NULL` taşır; `first_rank=200` ile yazılan ilk kaydın sırası 200'dür; `first_rank` verilmeyince bugünkü sıra.

## Task 3: `_search` ve `_search_pages`

```python
@dataclass(frozen=True)
class Page:
    number: int              # 0 for the first page
    cursor: str              # FIRST_PAGE or the previous page's next_cursor
    read_before: int         # records this query read on earlier pages
    known_total: int | None  # the provider total an earlier page reported
    extra_requests: int      # requests the read limit allows this run beyond max_provider_requests
```

`_search(..., page: Page | None = None)`; `page` verildiğinde:

- adım anahtarı: `number == 0` → `search:{index}`, değilse `search:{index}:page:{number}`; tür aynı.
- istek izni: bugünkü `allowance + page.extra_requests`. `extra_requests`, `_search_pages`'te bir kez hesaplanır: koşunun her sorgusu için `ceil(min(SW_READ_LIMIT, max_reachable or SW_READ_LIMIT) / connector.max_results)` toplamı (`single_page` için 1) eksi sorgu sayısı. Yeni bütçe sabiti yoktur: izin, okuma sınırından türetilir. `max_provider_requests`'in kendisi ve `compile_block_queries`'e verilişi değişmez.
- `ceiling = min(SW_READ_LIMIT, connector.max_reachable or SW_READ_LIMIT)`; `limit = min(connector.max_results, ceiling − read_before)`; `connector.search(..., cursor=page.cursor)`. Son sayfa böylece sınırı aşmaz.
- `search_fields`'e `page_number`, `read_limit`, `read_total`, `stop_reason`, `unread_count`; `page_limit` o sayfanın `limit`'idir. `stop_reason` aynı işlemde hesaplanır: başarısız sayfa → `page_failed`; `connector.paging == "single_page"` → `single_page`; `next_cursor is None` → `exhausted`; `read_total ≥ SW_READ_LIMIT` → `read_limit`; `read_total ≥ max_reachable` → `provider_cap`; aksi halde `NULL`. Sıfır kayıt dönen sayfa `exhausted`'tır (sonsuz döngü olmaz).
- `record_search(..., first_rank=page.read_before)`; adım çıktısı `{"status", "result_count", "page", "next_cursor", "read_total", "provider_total", "stop_reason"}`.

`_search_pages(run, index, query, retry_failed)`:

1. `cursor = FIRST_PAGE`, `read = 0`, `n = 0`.
2. `self._checkpoint(...)` (duraklatma sayfalar arasında da çalışır); `n > 0` ve `connector.page_gap` varsa `await asyncio.sleep(page_gap)` — yalnızca gerçekten istek atılacaksa, saklı sayfa atlanırken değil.
3. `failure = await self._search(..., page=Page(...))`. Sonra adım okunur. `succeeded` değilse (yeni başarısız oldu ya da önceden başarısızdı ve `retry_failed` yanlış) sorgunun okuması **bu koşuda biter**, `failure` döner.
4. Başarılıysa saklı çıktıdan `read`, `cursor`, `known_total` güncellenir; `stop_reason` doluysa biter; değilse `n += 1` ve 2'ye dön.

**Başarısız sayfa kuralı (D18'in sayfaya uzanışı):** başarısız sayfa kendi satırı ve adımıyla kaydedilir, o sorgunun daha önce okunmuş sayfaları ve **diğer bütün sorgular** etkilenmez; ama aynı sorgunun sonraki sayfaları bu koşuda istenmez. Gerekçe: imleçli sağlayıcıda başarısız sayfanın ardındaki imleç bilinmez; hız sınırına takılmış bir sağlayıcıya sıradaki ofseti göndermek de aynı yanıtı alır. Kural her iki kipte aynıdır. Yeniden deneme D18'deki gibidir: en az bir araması başarılı olan koşu sürdürülünce başarısız sayfayı kendiliğinden denemez; "Search again" (`retry_failed_searches_only`) dener ve başarılı olursa okuma o sayfadan devam eder. Koşu, yalnızca hiçbir sayfası başarılı olmadıysa duraklar (`searched()` aynen).

- [ ] **Tests first** (`tests/test_search_paging.py`, `create_app` ile, `tests/test_vocabulary_flow.py`'nin kalıbı; mock OpenAlex sayfaları imleçle, ikinci bir `offset` sağlayıcısı):
  - **Kabul 1:** sağlayıcı toplamı sınırın altındaysa (ör. 450 kayıt, üç sayfa) her kayıt adaydır; son satır `exhausted`, `unread_count = 0`; aday sıraları 0…449.
  - **Kabul 2:** toplam sınırın üstündeyse (test, `SW_READ_LIMIT`'i küçük bir değere yamalar) tam sınır kadar kayıt okunur, okunan hiçbir kayıt atılmaz, son satır `read_limit` ve `unread_count = toplam − okunan`.
  - **Kabul 3:** ikinci sayfadan sonra duraklatılıp sürdürülen koşu hiçbir sayfayı iki kez istemez (mock taşıyıcıda imleç/ofset başına istek sayacı) ve üçüncü sayfayı ikinci sayfanın saklı imleciyle ister.
  - ikinci sayfası 429 dönen sorgu: ilk sayfanın adayları durur, satır `page_failed`, öbür sağlayıcının bütün sayfaları okunur, koşu duraklamaz; normal sürdürme başarısız sayfayı istemez; `retry_failed_searches_only` ister ve üçüncü sayfaya geçer.
  - Semantic Scholar 1.000'de `provider_cap` ile durur ve okunmayanı sayar; SerpApi tek istek atar, `single_page`.
  - `sw` koşusu `max_provider_requests`'ten çok istek atabilir ve `budget_exhausted` ile durmaz; `legacy` koşusunda izin bugünkü sayıdır.
  - `legacy` araştırma tek istek atar, `cursor` göndermez, `search_runs`'ın yeni sütunları `NULL`'dır, hiçbir `:page:` adımı açılmaz.
  - sıfır kayıtlı ilk sayfa `zero_results` + `exhausted`; `provider_total` vermeyen sağlayıcıda `unread_count` `NULL`.

## Task 4: protokol ve görünüm

- `protocol.build_protocol`: `sw` için `thresholds.search_read = {"read_limit_per_query": SW_READ_LIMIT}`; `legacy` gövdesi ve özeti **aynı** kalır (mevcut `record_identity` satırının kalıbı). 04d aynı dosyada terim alanlarına dokundu; bu dilim yalnızca `thresholds` sözlüğüne tek satır ekler.
- `views.research_view`: `search_runs` satırlarına beş yeni alan; `counts["unread"]`: her `(run_id, provider, query_text)` için `stop_reason`'ı dolu **son** satırın (`page_number`, `retrieved_at`, `id` sırasıyla) `unread_count`'larının toplamı, `NULL`'lar atlanır. `counts["found"]` zaten sayfaları toplar. Arayüz değişmez; `api.ts` tipleri dilim 08'de.

- [ ] **Tests first:** `sw` protokolünde `search_read` var, `legacy` protokol özeti bu dilimden önceki değerle aynı (`tests/test_protocol_record.py`'deki sabit); görünümde `unread`, yeniden denenen sayfa iki kez sayılmaz.

## Task 5: `link_records` süresini ölç

`record_search` her sayfada `links.link_records` çalıştırır (dilim 03) ve o, her çağrıda araştırmanın **bütün** adaylarını yükleyip başlık trigramlarını yeniden kurar. Sayfalama bunu sorgu başına 1 çağrıdan 10–80 çağrıya çıkarır; işlem olay döngüsü iş parçacığında koşar ve sürerken API'yi de bekletir.

`scripts/probes/time_link_records.py`: geçici bir `DEIXIS_DATA_DIR`'de (canlı kütüphane değil, ağ yok) bir `sw` araştırması açar ve 200'lük sayfalarla **1.500 aday** olana kadar `record_search` çağırır. Kayıtlar, varsa `.local/quantum-rank-fusion-2026-09-18/round.json`'daki gerçek ilk tur kayıtlarıdır (gerçek başlık komşulukları; dosyanın biçimini oku), yoksa tohumlu SYNTHETIC kayıtlardır; hangisinin kullanıldığı çıktıya yazılır. Çıktı `.local/sw-paging-timing-2026-09-21/timing.json`: sayfa başına `record_search` süresi, bunun `link_records` payı, toplam, son sayfadaki aday sayısı, makine.

- [ ] Sayıları son iletiye ve `sw-status.md` satırına yaz. **`links.py`'yi değiştirme**: o, tam incelenmiş dilim 03'ün kodudur. 1.500 adayda tek bir sayfanın işlemi 1 saniyeyi aşıyorsa bunu son iletinin başında söyle; düzeltme ayrı bir karardır.

## Task 6: dilimi kapat

- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `git diff --check`.
- [ ] `docs/decisions.md` en üste `## D<NN> — Read an sw query page by page up to one named read limit, and count what was not read`. Limits adıyla söylemeli: yalnızca `sw`; `SW_READ_LIMIT = 2.000` elle seçildi, ölçülmedi (dilim 24); **tarama hâlâ `max_candidates` ile kesilir**, okunan adayların çoğu bu dilimden sonra taranmaz (dilim 09, K3); sıra kesmez kuralı (§2.4) ancak dilim 07 ve 09'la tamamlanır; sağlayıcı toplamları kesin değildir (Semantic Scholar ve SerpApi tahmin verir), `unread_count` o toplamın doğruluğu kadardır; Semantic Scholar 1.000'de, SerpApi tek sayfada durur; başarısız sayfa o sorgunun okumasını o koşuda bitirir; OpenAlex imlecinin ne kadar geçerli kaldığı ölçülmedi, eskimiş imleç `page_failed` olarak görünür ve bugün tek çıkışı yeni bir keşif koşusudur; sayfalar arası kayıt tekrarı ve sağlayıcı sırasının sayfalar arasında kayması ölçülmedi; sayım istekleri gibi sayfa istekleri de `max_provider_requests`'e değil türetilmiş bir izne sayılır; `unread` hiçbir ekranda görünmez (dilim 08 / 20); `link_records` süresi Task 5'in sayısıyla; testler SYNTHETIC ve ağsız, canlı sağlayıcı sayfalaması sınanmadı.
- [ ] `sw-status.md` satır 04c: `uygulandı, inceleme bekliyor` + açık kalanlar + Task 5'in sayıları.
- [ ] `git pull --ff-only`, çakışma varsa (04d'nin inceleme düzeltmesi) elle çöz ve testleri yeniden koş; tek commit, `git push origin main` (ana plan §2.11).

## Son ileti

Değişen ve eklenen dosyalar; temel ve son test sayıları ve komut; sağlayıcı tablosunda belgeyle doğrulanan ve düzeltilen satırlar; Task 5'in sayıları (hangi kayıtlarla); yazıldığı gibi yapılamayan her şey ve seçilen her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: yok — aday havuzu büyür, `search_runs` ve protokol gövdesinin içeriği değişir); pull'un getirdiği bir commit'le çakışma olup olmadığı; canlı servise dokunulmadığı; commit özeti.

## Açık noktalar

- **Yorum:** plan "başarısız sayfa diğerlerini durdurmaz" der. Burada "diğerleri", öbür sorgular ve o sorgunun okunmuş sayfalarıdır; aynı sorgunun sonraki sayfaları o koşuda istenmez (Task 3). İmleçli sağlayıcıda başka yol yoktur; `offset` sağlayıcısında atlanıp devam edilebilirdi, tek kural için vazgeçildi.
- **Yorum:** SerpApi "sayfalamayı desteklemeyen" değil, sayfası ücretli olandır; tek sayfa okuması bir maliyet kararıdır.
- `SW_READ_LIMIT`'in efor düzeyine bağlanması (`quick` için daha küçük) bilerek yapılmadı: plan "tek adlı sabit" der. Dilim 24 ölçümü gösterirse değişir.
- Bu dilimden sonra `sw` koşusu binlerce aday bulup 250'sini tarar ve tarananlar sağlayıcı geliş sırasıyla seçilir. Bayrak arkasındadır; dilim 07 (sıra) ve 09 (kesimin kalkması) gelene kadar `sw` ile gerçek iş yapılmaz.
- Eskimiş imleçten kurtulma (sorguyu baştan okuyup bilinen kayıtları atlama) yapılmadı; canlıda görülürse ayrı dilim.
