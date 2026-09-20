# SW dilim 04a — Kodla sözcük dağarcığı ve kavram blokları: uygulama planı

**Tarih:** 20 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): SW2 madde 1–3 ve 7, SW1 madde 3, SW3 madde 5. **Önkoşul:** dilim 01 (D70) kapandı. **Tür:** Kur (ölçülmedi): SW2 "uygulanmadı ve ölçülmedi" der; eşikler geçicidir, ölçüm dilim 24'tedir.

**Bölme:** ana plandaki dilim 04 ikiye ayrıldı. **04a** (bu dosya): dil, ifade çıkarma, sayım sınaması, bloklar, kök sözcükten öbeğe daraltma, blok sorgusu derleme ve `sw` keşif koşusuna bağlama. **04b**: ilk tur adaylarından genişleme (yazar anahtar sözcükleri, başlık n-gramları; SW2.4) ve terim başına verim kaydı (SW1.3 son cümle). 04b, sağlayıcı kaydına yeni alan ister ve ayrı bir oturumdur.

**Goal:** Bugün arama sözcüklerini `search_plan` model adımı üretir (D44) ve kod yalnızca sorguyu derler. Model kapalıyken arama koşmaz, aynı soru iki koşuda başka sözcükler verebilir ve sınanan iddianın sözcükleri sorguya girebilir. SW2, ilk aramanın sözcüklerini kodun sorudan çıkarmasını, her ifadeyi bir sayım isteğiyle sınamasını, iddia ve dışlama sözcüklerini sorgunun dışında tutmasını ve sorguyu bloklardan derlemesini ister. Bu dilim bunu yalnızca `sw` araştırmaları için kurar; `legacy` araştırmada `search_plan` adımı aynen kalır.

**Architecture:** Çıkarma saf koddur: `domain/vocabulary.py` sorudan (ya da kullanıcının İngilizce anahtar terimlerinden) ifadeleri, konumlarına göre geçici blokları, iddia ve dışlama listelerini üretir; ağa ve veritabanına bakmaz. Sayım sınaması `providers/openalex.py::count_works`'tür. `workflow/vocabulary.py` ikisini birleştirir: sayımlara göre kök sözcükle başlar, sonuç kümesi yönetilemezse öbeğe daraltır. `providers/query_compiler.py::compile_block_queries` blokları sağlayıcı sözdizimine derler. `flow._discovery`, `sw` araştırmasında `search_plan` model adımı yerine `vocabulary` kod adımını koşar; adımın saklı çıktısı sürdürülen koşuda yeniden kullanılır, sayım istekleri tekrarlanmaz. Blok ataması kuralla yapılır ve **geçicidir**: SW2 bunun güvenilmez olduğunu söyler, kullanıcı onayı dilim 08'dedir.

**Tech stack:** Python 3.12. Yeni bağımlılık yok (NLP kütüphanesi, sözcük sıklığı paketi, dil tespit paketi yok).

## Global constraints

- `apps/web/`, `contracts/research/`, `methods/deixis-research/` ve mevcut migration dosyalarına dokunma. `skill_package_hash` değişmez.
- `legacy` araştırmanın davranışı ve mevcut test beklentileri değişmez. `flow._discovery`'deki değişiklik tek bir `sw` dalıdır; `legacy` yolu satır satır aynı kalır.
- `sw` keşif koşusunda **hiçbir model çağrısı yoktur** (tarama hâlâ `legacy` sözleşmesiyle modele gider; o dilim 09'dur). Model bağlantısı kapalı ya da bozukken ilk arama koşar.
- Ürün koduna konuya özgü sözcük girmez. Bu dilimdeki listeler yalnızca İngilizce işlev sözcükleri, soru kalıpları, edatlar ve alan-bağımsız genel sözcüklerdir; bir alanın terimi listeye girerse dur.
- Testlerde ağ yok: `count_works` mock `httpx` taşıyıcısıyla sınanır.
- Migration numarası bu not yazılırken `0040`, karar numarası `D73`'tür; başlamadan önce kontrol et.

## Dosya yapısı

Yeni: `backend/deixis/domain/vocabulary.py`, `backend/deixis/domain/vocabulary_words.py` (yalnızca listeler), `backend/deixis/workflow/vocabulary.py`, `backend/deixis/storage/migrations/0040_scope_key_terms.sql`, `tests/test_vocabulary.py`, `tests/test_vocabulary_flow.py`.

Değişecek: `providers/openalex.py` (`count_works`), `providers/query_compiler.py` (`compile_block_queries`), `workflow/flow.py` (`_discovery`'de `sw` dalı; pasaj sıralamasının terim okuyan yeri ~714), `workflow/protocol.py`, `workflow/store.py` (`create_research`, `revise_scope`, `scope`: `key_terms`), `api/app.py` (yalnızca istek gövdesine isteğe bağlı `key_terms`), `tests/determinism_stages.py`, `tests/test_protocol_record.py`, `docs/decisions.md`, SW belgesi (SW2 durum satırı), `docs/product/sw-status.md`.

## Task 1: `domain/vocabulary.py` — sorudan ifadeler ve geçici bloklar

```python
ENGLISH_FUNCTION_WORD_SHARE = 0.2   # a question is read as English at or above this share of function words

@dataclass(frozen=True)
class Phrase:
    text: str            # normalised, lower case, single spaces
    position: str        # setting | task | method | outcome | excluded
    origin: str          # question | key_terms

@dataclass(frozen=True)
class Extraction:
    language: str                        # "en" | "other"
    blocks: dict[str, list[str]]         # "setting", "task", "outcome": phrases in the order they appeared
    claim_words: list[str]               # method-position phrases: never queried (SW1.3)
    exclusion_words: list[str]
    block_assignment: str                # "rule" | "user"

def detect_language(question: str, language_hint: str | None) -> str: ...
def parse_key_terms(key_terms: str) -> Extraction: ...
def extract(question: str, language_hint: str | None = None, key_terms: str | None = None) -> Extraction | None: ...
```

Kurallar:

- `detect_language`: `language_hint` varsa o belirler (`en` ile başlıyorsa `en`, değilse `other`). Yoksa soru, aksi görülmedikçe İngilizcedir: Latin dışı harf → `other`; aksanlı harf varsa ve `ENGLISH_FUNCTION_WORDS` payı eşiğin altındaysa → `other`; sekiz ya da daha çok sözcük olup tek bir İngilizce işlev sözcüğü yoksa → `other`. (İncelemede değişti: ilk kural yalnızca paya bakıyordu ve içerik sözcüğü yoğun düz bir İngilizce soruyu `other` sayıyordu.)
- `key_terms` doluysa soru ayrıştırılmaz: `parse_key_terms` noktalı virgülle ayrılmış grupları sırayla `setting`, `task`, `outcome` bloklarına koyar; grup içinde virgül eş anlamlıları ayırır; `claim:` ve `not:` ile başlayan grup `claim_words` ve `exclusion_words`'e gider; `block_assignment = "user"`. Biçim bozuksa `ValueError`. Bu alan hem İngilizce olmayan sorunun yolu (SW2.1) hem de çıkarmayı elle düzeltmenin tek yoludur (arayüzü dilim 08).
- Dil `other` ve `key_terms` boşsa `extract` `None` döner (kod çeviri yapmaz).
- İngilizce soruda sıra: (1) soru kalıbı atılır (`QUESTION_FRAMES`: "what is the effect of", "how does", "which papers", "is there evidence that", sondaki soru işareti…); (2) metin işlev sözcüklerinde, noktalamada ve `CUE_WORDS`'te bölünür; ardışık içerik sözcükleri bir ifadedir (RAKE'in aday üretimi); (3) yalnızca `GENERAL_WORDS`'ten oluşan ifade atılır, ifadenin başındaki ve sonundaki genel sözcük kırpılır (SW2.2 "genel dilde sık geçen"); (4) konum, ifadeden hemen önceki işaret sözcüğünden gelir:

| İşaret (`CUE_WORDS`) | Konum |
|---|---|
| `in`, `on`, `for`, `within`, `across`, `among`, `over`, `under` | `setting` |
| `using`, `via`, `with`, `by`, `through`, `based on`, `formulated as`, `modeled as`, `modelled as`, `as a`, `as an` | `method` |
| `to minimize`, `to maximize`, `to reduce`, `to improve`, `to increase`, `effect on`, `impact on`, `in terms of` | `outcome` |
| `not`, `without`, `excluding`, `except`, `other than`, `rather than` | `excluded` |
| işaret yok, ya da `of` | `task` |

- Birden çok `setting` ifadesi varsa hepsi `setting` bloğuna girer (blok içi OR). `method` konumu sorguya **hiçbir yoldan** girmez: `claim_words`'e gider. Gerekçe: kod, "ILP"den "optimization"ı türetemez; SW1.3'ün geniş yöntem bloğunu ancak kullanıcı (dilim 08) ya da koşullu model adımı (SW2.5) doldurur. Bu dilimde yöntem bloğu boştur ve geçit yalnızca `setting` ve `task`'tır.
- `outcome` bloğu saklanır ama sorguya girmez (SW1.3: "isteğe bağlı, aksi halde sıralama desteği"; sıralama dilim 07).
- Aynı ifade iki konumda çıkarsa ilk geçtiği konum kalır. Çıktı sırası sorudaki sıradır; hiçbir yerde küme yinelemesi sonucu belirlemez.

- [ ] **Tests first.** En az üç alandan SYNTHETIC sorular (iletişim ağları, klinik, malzeme; hiçbiri ürün kodundaki bir listeye sözcük eklemeyi gerektirmemeli): "X of Y in Z" → `task` ve `setting`; "… using ILP" → `ILP` yalnızca `claim_words`'te; "… not surveys" → `exclusion_words`; yalnızca genel sözcüklerden oluşan ifade atılır; Türkçe soru ve boş `key_terms` → `None`; Türkçe soru ve `key_terms` → bloklar kullanıcıdan; bozuk `key_terms` → `ValueError`; aynı girdi iki hash tohumunda aynı çıktı (Task 6 bunu süreçler arası sınar).

## Task 2: `count_works`

`providers/openalex.py`: `async def count_works(client, query: str, *, api_key, mailto) -> int | None`. `search_works` ile aynı arama parametresi (`SEARCH_PARAM`), aynı kimlik ve hata işleme; `select=id` ve en küçük sayfa boyu. Ana plan `per_page=0` der; OpenAlex en az 1 ister, bu yüzden `per_page=1` kullanılır ve `meta.count` okunur. Hata, zaman aşımı ya da hız sınırı `None` döndürür ve çağıranı durdurmaz (D18'in ruhu: bir başarısız istek diğerlerini durdurmaz). İstek açıklaması sır içermez (`redact`).

- [ ] **Tests first** (mock taşıyıcı): sayım okunur; 429 ve zaman aşımı `None`; istekte `per_page=1` ve `select=id` vardır; anahtar açıklamada görünmez.

## Task 3: `workflow/vocabulary.py` — sayımla sınama ve daraltma

```python
MAX_PROBES = 40                 # count requests one vocabulary step may send
VERY_LARGE_COUNT = 1_000_000    # SW2.2: a term this frequent is usable only inside an AND
MANAGEABLE_TOTAL = 5_000        # SW3.5: above this the gate query is narrowed from a root word to its phrase
THRESHOLDS = {...}              # the three above plus ENGLISH_FUNCTION_WORD_SHARE

async def build_vocabulary(extraction: Extraction, count: Callable[[str], Awaitable[int | None]]) -> dict[str, Any]: ...
```

Çıktı (adım çıktısı olarak saklanır, kanonik sıralı):

```json
{"language": "en", "block_assignment": "rule",
 "terms": [{"phrase": "...", "block": "setting", "origin": "question", "root": "...", "in_query": "root" | "phrase",
            "phrase_count": 1234, "root_count": 56789, "and_only": false, "dropped": null | "zero_results"}],
 "claim_words": [...], "exclusion_words": [...], "outcome_terms": [...],
 "gate_count": 3210, "probes": [{"query": "...", "count": 1234}], "probes_skipped": 0}
```

Algoritma:

1. Her `setting` ve `task` ifadesi ve çok sözcüklü ifadenin `GENERAL_WORDS` dışındaki her sözcüğü sınanır. Sayımı 0 olan ifade `dropped = "zero_results"` olur (SW2.2). Sayımı bilinmeyen (`None`) ifade kalır ve **öbek olarak** sorguya girer (dar ve güvenli taraf).
2. Kök: çok sözcüklü ifadenin, sayımı sıfırdan büyük ve **en küçük** olan genel olmayan sözcüğü (en ayırt edici sözcük); eşitlikte ifadedeki sıra. Tek sözcüklü ifade kendi köküdür. Başlangıçta her terim kökle sorguya girer (SW3.5).
3. Geçit sorgusu (`setting` OR grubu AND `task` OR grubu, OpenAlex sözdizimi) sayılır. Sayım `MANAGEABLE_TOTAL`'ı aşıyorsa ve hâlâ kökle duran çok sözcüklü bir terim varsa, **kök sayımı en büyük olan** terim öbeğine çevrilir ve yeniden sayılır; koşul düşene ya da çevrilecek terim kalmayana kadar. Kararı sayımlar verir, başka hiçbir şey (SW3.5).
4. `and_only`: sorguya giren biçiminin sayımı `VERY_LARGE_COUNT`'u aşan terim. Tek bloklu bir dağarcıkta sorguya girecek bütün terimler `and_only` ise sonuç `{"too_broad": true}` taşır.
5. `MAX_PROBES` dolunca kalan sınamalar atlanır (`probes_skipped`), sınanmamış terimler öbek olarak girer. Sınama sırası sabittir: ifadeler sorudaki sırayla, sonra sözcükleri, sonra geçit sorguları.

- [ ] **Tests first** (sahte `count`): sıfır sayımlı ifade düşer; kök en küçük sayımlı sözcüktür; geçit büyükken en büyük köklü terim öbeğe döner ve sıra budur; geçit küçükken hiçbir kök değişmez; `None` sayım öbeğe düşürür; `MAX_PROBES` aşılmaz; her sınama `probes`'ta durur; `too_broad`.

## Task 4: `compile_block_queries`

`providers/query_compiler.py`: `BLOCKS_VERSION = "deixis.query_compiler.v4.blocks"` ve `compile_block_queries(vocabulary, enabled_providers, limit) -> list[dict]`. Sağlayıcı başına **bir** sorgu: blok içi OR, bloklar arası AND (SW2.7); mevcut `_quoted`, `_group`, `_render` / `_fit` ve `query_rules` yeniden kullanılır; `PLAIN_PROVIDERS` düz metin alır; SerpApi'ye en çok bir sorgu kuralı durur. `MAX_QUERY_CHARS` ya da `OPENALEX_MAX_OPERATORS` aşılıyorsa blok içinde sondaki terimler atılır, her bloğun en az bir terimi kalır; atılan terimler sorgu sözlüğünde `dropped_terms` olarak yazılır. Tek bloklu dağarcık tek gruplu sorgu verir. Dönen sözlükler `compile_queries`'inkilerle aynı anahtarları taşır ki `_search` değişmeden çalışsın. `claim_words`, `exclusion_words` ve `outcome_terms` hiçbir sorguda yer almaz.

- [ ] **Tests first:** iki blok → `(a OR b) AND (c)`; her sağlayıcı sözdizimi için bir beklenti (mevcut derleyici testlerinin kalıbı); iddia sözcüğü hiçbir sağlayıcının sorgusunda yok (acceptance); uzun blok kırpılır ve kırpılan yazılır; `compile_queries`'in mevcut testleri aynen geçer.

## Task 5: `key_terms` alanı ve akışa bağlama

- Migration `0040_scope_key_terms.sql`: `ALTER TABLE scope_revisions ADD COLUMN key_terms TEXT;`. `Store.create_research` ve `revise_scope` isteğe bağlı `key_terms` alır, `scope()` döndürür; `api/app.py`'de araştırma açma ve kapsam düzeltme gövdelerine isteğe bağlı `key_terms` (en çok 500 karakter) eklenir. Arayüz değişmez.
- `flow._discovery`: `scope["search_workflow"] == "sw"` ise `search_plan` model adımı yerine `vocabulary` adımı (`store.step(run_id, "vocabulary", "code:vocabulary")`). Adım `succeeded` ise saklı çıktı kullanılır; değilse `extract` → `build_vocabulary` (`count`, `self.deps`'teki http istemcisi ve OpenAlex anahtarıyla `count_works`'tür; OpenAlex sağlayıcısı kapsamda yoksa ya da anahtarsız erişim de kapalıysa sayım yapılmaz ve her terim öbek olarak girer) → `compile_block_queries` → çıktı, sorgular ve `BLOCKS_VERSION` adıma yazılır. `await` işlem dışında kalır.
- Duraklatma nedenleri: `extract` `None` → `key_terms_needed`; hiç `setting` / `task` terimi kalmadı → `vocabulary_empty`; `too_broad` → `vocabulary_too_broad`. Üçü de `_pause` ile; koşu, kapsam düzeltilince (yeni revizyon, `key_terms` ile) yeniden başlar. `uploaded_seed` kipinde tohum bu adımı beslemez (tohumlar dilim 15).
- Protokol: `build_protocol` yeni isteğe bağlı `vocabulary` argümanı alır; `sw` için `concept_blocks` (blok → sorguya giren terimler), `claim_words`, `exclusion_words`, `vocabulary` (terim, köken, blok, sayımlar, `in_query`) dolar, `thresholds.vocabulary = THRESHOLDS`, `arms` aynı kalır. `legacy` gövdesi ve özeti değişmez. Sayımlar zamanla değişir: protokole **ilk koşuda okunan** sayımlar girer ve o koşunun saklı adım çıktısından gelir, yeniden sayılmaz.
- Pasaj sıralamasının terim okuyan yeri (`flow.py` ~714): `search_plan` çıktısı yoksa `vocabulary` adımının sorguya giren terimleri ve `outcome_terms` aynı biçimde eklenir; `claim_words` eklenmez (o, dilim 11'in ölçüt pasajlarıdır).

- [ ] **Tests first** (`tests/test_vocabulary_flow.py`, `create_app` ile, sahte model ve mock OpenAlex): `sw` araştırmada model bağdaştırıcısı **her çağrıda hata verirken** keşif koşusu aramayı yapar (acceptance: model kapalıyken ilk arama koşar; tarama adımının başarısızlığı ayrı bir sonuçtur, arama adımları `succeeded`'dır); kaydedilen hiçbir `search_runs.query_text` iddia sözcüğünü içermez; duraklatılıp sürdürülen koşu sayım isteklerini tekrarlamaz (istek sayacı); İngilizce olmayan soru `key_terms_needed` ile durur, `key_terms`'li yeni revizyon arar; dondurulan protokolde `concept_blocks` dolu ve özeti, aynı saklı çıktıyla ikinci kez kurulunca aynı; `legacy` araştırma `search_plan` adımını koşar ve `vocabulary` adımı açılmaz.

## Task 6: tekrar aşaması

`tests/determinism_stages.py`'ye `vocabulary`: sabit bir SYNTHETIC soru, sabit bir sayım sözlüğü (sahte `count`) ve karıştırılmış sağlayıcı listesiyle `extract` → `build_vocabulary` → `compile_block_queries`; çıktı kanonik özetlenir. İki hash tohumu ve iki karışımda tek özet.

## Task 7: dilimi kapat

- [ ] İki konunun sorusuyla (kuantum dolanıklık dağıtımı; KAA'da paket boyutu — metinler `.local/` altındaki protokol dosyalarında) **ağsız** bir kuru çalıştırma: `extract` çıktısını son iletiye yaz (bloklar, iddia ve dışlama listeleri). Bu ölçüm değildir; atamanın nerede yanıldığını sahibin görmesi içindir. İstersen tek bir canlı `count_works` isteğiyle istek biçimini doğrula ve söyle; başka canlı istek yok.
- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; beklenen temel `1 failed, 855 passed`, bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `git diff --check`.
- [ ] `docs/decisions.md` en üste `## D<NN> — Take the first search's vocabulary from the question by code, probe each term by count, and keep claim words out of the query`. Limits adıyla söylemeli: yalnızca `sw`; ölçülmedi (dilim 24); blok ataması edat kurallarıyla yapılır, güvenilmezdir ve onay ekranı yoktur (dilim 08); çıkarma yalnızca İngilizce soruyu okur, diğer dillerde kullanıcının İngilizce terimleri gerekir ve bunu isteyen bir ekran yoktur; yöntem bloğu boştur, yöntem konumundaki her ifade iddia sayılır; genel sözcük listesi elle yazılmış kısa bir listedir; `MANAGEABLE_TOTAL`, `VERY_LARGE_COUNT`, `MAX_PROBES` ve dil eşiği elle seçildi; sayım, terimin yazında geçtiğini gösterir, doğru terim olduğunu değil; veriden genişleme ve terim verimi yok (04b); koşullu model adımı yok (SW2.5, dilim 08); sorgu başına okunan sonuç sayısı hâlâ `legacy` bütçesidir (aşağıda); testler SYNTHETIC ve ağsız.
- [ ] SW belgesinde SW2 **Status** satırına bir cümle. `sw-status.md` satır 04a: `uygulandı, inceleme bekliyor` + açık kalanlar.
- [ ] Tek commit, `git push origin main` (ana plan §2.11).

## Son ileti

Değişen ve eklenen dosyalar; temel ve son test sayıları ve komut; iki sorunun kuru çalıştırma çıktısı; `vocabulary_words.py`'deki listelerin boyutu ve hiçbirinin alan terimi içermediğinin nasıl denetlendiği; yazıldığı gibi yapılamayan her şey ve seçilen her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: yok — arama sözcükleri kanıt sınırı değildir; protokol kaydının içeriği değişir); canlı servise dokunulmadığı; commit özeti.

## Açık noktalar

- **Dilim 04c'ye atandı (20 Eylül 2026):** `sw` akışı sağlayıcı başına tek geniş sorgu atar, ama `_search` sorgu başına en çok `results_per_query` (≤ 25) kayıt okur. SW7'nin ölçtüğü ilk tur havuzu 1.369 kayıttı; geniş sorgunun anlamı olması için sayfalama ve `sw`'ye özgü bir okuma bütçesi gerekir. Bu dilim ona dokunmaz; dilim 04c kurar ve dilim 07'nin önkoşuludur.
- **Yorum:** SW1.3'ün yöntem bloğu "geniş sorgulanır" der; kod geniş terimi iddia sözcüğünden türetemediği için bu dilimde blok boştur ve yöntem konumundaki ifadelerin hepsi sorgu dışında kalır. Böylece kabul koşulu ("iddia sözcüğü sorguya girmez") kuralla değil yapıyla sağlanır; bedeli, yöntem sorunun konusuysa ("routing" gibi) onu da `using` / `with` arkasında kaybetmektir. Kullanıcı `key_terms` ile düzeltebilir.
- **Yorum:** kök, ifadenin en az geçen sözcüğüdür. SW3.5 "kök sözcük ya da geniş terim" der ve nasıl seçileceğini söylemez.
- Duraklatma nedenleri (`key_terms_needed`, `vocabulary_empty`, `vocabulary_too_broad`) arayüzde ham metin olarak görünebilir; etiketleri dilim 08'de gelir.
