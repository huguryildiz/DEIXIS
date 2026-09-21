# SW dilim 04b — Veriden genişleme ve terim başına verim: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): SW2 madde 4, SW1 madde 3 (son cümle), SW3 Context'teki genişleme ölçümü. **Önkoşul:** 04a (D73), 04c (D75), 04d (D74) kapandı. **Tür:** Kur (ölçülmedi): eşikler tek bir sondadan alınmıştır, ölçüm dilim 24'tedir.

**Goal:** `sw` akışının ilk araması yalnızca sorudaki sözcüklerle yapılır (04a); kullanıcı alanın yaygın terimini yazmadıysa sorgu dardır. SW2.4 genişlemenin önce veriden gelmesini ister: ilk turda bulunan kayıtların yazar anahtar sözcükleri ve başlık n-gramları. Bu dilim, ilk tur bittikten sonra ve taramadan önce, kodla aday ifadeler çıkarır, her birini sayım isteğiyle "bu alanda kullanılıyor mu" diye sınar, kabul edilenlerle **yalnızca ek getiren** ikinci bir arama turu atar ve her terimin kaç kayıt getirdiğini saklar. Model çağrısı yoktur. `legacy` araştırmada hiçbir şey değişmez.

**Dayanak ölçüm** (`.local/quantum-source-comparison-2026-09-18/expand_from_data.py`, `round2-expansion.json`; SW3 Context): bulunan 23 pozitifin başlık ve özetlerinden 2–3 sözcüklü n-gramlar, belge sıklığı ≥ 3, OpenAlex sayım sınaması `count(ifade AND ortam bloğu) ≥ 20` ve bunun `count(ifade)`'nin en az %20'si olması; 17 ifadeden 3'ü kabul edildi, 119 ek kayıt için elde tutulan 8 kaçıktan 1'i geri geldi. **Fark:** o sonda *doğrulanmış pozitiflerden* öğrendi; ürün ilk turda doğrulanmış kayıt tanımaz ve bütün adaylardan (çoğu konu dışı) öğrenir. Eşikler oradan alınır ama bu koşulda hiç ölçülmemiştir.

**Architecture:** Sağlayıcı kaydı `author_keywords` alanı kazanır; yalnızca **yazarın verdiği** anahtar sözcükleri taşıyan sağlayıcılar doldurur. Aday çıkarma saf koddur (`domain/expansion.py`), sınama ve karar `workflow/expansion.py`'dedir (04a'daki `domain/vocabulary.py` / `workflow/vocabulary.py` ayrımının aynısı). `flow._discovery`, `sw` dalında ilk tur arama döngüsünden sonra `vocabulary_expansion` kod adımını koşar; adımın saklı çıktısı sürdürülen koşuda yeniden kullanılır, sayım istekleri tekrarlanmaz. Kabul edilen terim varsa ikinci tur sorguları derlenir, protokol `data_expansion` gerekçesiyle **yeni revizyon** olarak dondurulur (ilk kayıt düzenlenmez, SW14.2) ve sorgular 04c'nin `_search_pages`'iyle, ilk turun ardından gelen indekslerle okunur. `vocabulary` adımının saklı çıktısı **değiştirilmez**; genişleme kendi adımında durur.

**Tech stack:** Python 3.12. Yeni bağımlılık yok.

## Global constraints

- `apps/web/`, `contracts/research/`, `methods/deixis-research/`, `backend/deixis/workflow/links.py` ve mevcut migration dosyalarına dokunma. `skill_package_hash` değişmez.
- `legacy` araştırmanın davranışı ve mevcut test beklentileri değişmez: `vocabulary_expansion` adımı `legacy`'de açılmaz; `author_keywords` alanı her iki akışta da saklanır ama `legacy`'de hiçbir şey onu okumaz.
- `sw` keşif koşusunda bu dilim **model çağrısı eklemez**. Model her çağrıda hata verirken de genişleme koşar.
- Ürün koduna konuya özgü sözcük girmez. Durak sözcükleri için yalnızca `domain/vocabulary_words.py`'deki mevcut listeler kullanılır; yeni liste açılmaz.
- Genişleme kayıt silmez ve ilk turun sorgusunu değiştirmez; yalnızca ek bir kol ekler.
- Tarama kesimine (`max_candidates`) dokunma (dilim 09).
- Testlerde ağ yok; sayım sınaması sahte `count` ya da mock taşıyıcıyla sınanır.
- Son migration `0041`, son karar `D75`'tir; bu dilim `0042` ve `D76`'yı kullanır. Başlamadan önce kontrol et.

## Dosya yapısı

Yeni: `backend/deixis/domain/expansion.py`, `backend/deixis/workflow/expansion.py`, `backend/deixis/storage/migrations/0042_author_keywords.sql`, `tests/test_expansion.py`, `tests/test_expansion_flow.py`.

Değişecek: `providers/common.py` (`ProviderRecord.author_keywords`), `providers/ieee_xplore.py`, `providers/pubmed.py`, `workflow/store.py` (`upsert_provider_source`: alanı yaz), `workflow/flow.py` (`_discovery`'de ilk tur döngüsünden sonra tek `sw` bloğu; yeni `_expansion` yöntemi `_search_pages`'in altına), `workflow/protocol.py`, `tests/test_providers.py`, `tests/test_protocol_record.py`, `tests/determinism_stages.py`, `docs/decisions.md`, SW belgesi (SW2 durum satırı), `docs/product/sw-status.md`.

## Task 1: `author_keywords`

`ProviderRecord.author_keywords: list[str] = field(default_factory=list)`. Yalnızca yazarın kendi verdiği sözcükler:

| Sağlayıcı | Alan | Not |
|---|---|---|
| `ieee_xplore` | `index_terms.author_terms.terms` | `ieee_terms` dizinleyicinindir, alınmaz |
| `pubmed` | `MedlineCitation/KeywordList/Keyword` | MeSH başlıkları dizinleyicinindir, alınmaz |
| diğerleri | — | boş liste |

OpenAlex'in `keywords` alanı yazarın değil, OpenAlex'in konu modelinin atadığı sözcüklerdir; Scopus `authkeywords`'ü yalnızca `COMPLETE` görünümünde verir ve ürün `STANDARD` kullanır. İkisi de **alınmaz** (Açık noktalar). Uygulayan iki satırı sağlayıcının belgesinden ve mevcut test fikstürlerindeki ham kayıttan doğrular; alan adı farklıysa belge kazanır ve son iletide söylenir.

Migration: `ALTER TABLE source_versions ADD COLUMN author_keywords_json TEXT;`. `upsert_provider_source` alanı yeni kayıtta yazar; var olan kayıtta yalnızca sütun boşsa doldurur (eksik özetin doldurulma kalıbı). Sözcükler kırpılır, boşlar ve yinelenenler atılır, sağlayıcının sırası korunur.

- [ ] **Tests first:** IEEE ve PubMed kayıtları yazar sözcüklerini taşır, dizinleyici terimlerini taşımaz; alanı olmayan kayıt boş liste verir; sütun yazılır, ikinci sağlayıcı dolu sütunu ezmez; mevcut sağlayıcı testleri dokunulmadan geçer.

## Task 2: `domain/expansion.py` — aday ifadeler

```python
MIN_DOCUMENT_FREQUENCY = 3   # a phrase must occur in at least this many first-round records
MAX_PROBED_PHRASES = 20      # candidates that reach the count probe, most frequent first

@dataclass(frozen=True)
class Candidate:
    phrase: str                 # normalised as domain/vocabulary.py normalises a phrase
    document_frequency: int
    sources: tuple[str, ...]    # "title", "author_keyword", in that order when both

def candidates(records: list[dict[str, Any]], queried_forms: list[str], side_words: list[str]) -> list[Candidate]: ...
```

Kurallar:

- Girdi kayıtları: bu kapsam revizyonunun adaylarının **iş başları** (`work_heads`), her biri `title` ve `author_keywords` ile. Bir iş bir kez sayılır.
- Başlık n-gramları: 2 ve 3 sözcüklü; ilk ve son sözcük `ENGLISH_FUNCTION_WORDS` ya da `GENERAL_WORDS`'te olamaz, her sözcük en az 3 harftir (sondanın kuralı, ürünün listeleriyle). Yazar anahtar sözcüğü, 1–4 sözcüklüyse bütün olarak adaydır; tek sözcüklüsü `GENERAL_WORDS`'te olamaz.
- **Kapsanmış ifade atılır:** sorguya girmiş herhangi bir geçit teriminin sorgudaki biçimini (`in_query == "root"` ise kök sözcük, değilse öbek) sözcük sınırında içeren ifade. Gerekçe: kökü içeren ifadeyi ilk sorgu zaten getirir; ortam bloğunun sözcüğünü içeren ifadede ise alan sınaması kendiliğinden geçer ve hiçbir şey sınamaz.
- `claim_words` ve `exclusion_words`'ten birini içeren ifade atılır (SW1.3: iddia sözcüğü sorguya hiçbir yoldan girmez).
- Belge sıklığı `MIN_DOCUMENT_FREQUENCY`'nin altında olan atılır. Sıra: belge sıklığı azalan, eşitlikte ifade alfabetik; ilk `MAX_PROBED_PHRASES` döner. Hiçbir yerde küme yinelemesi sonucu belirlemez.

- [ ] **Tests first** (en az iki alandan SYNTHETIC başlıklar): n-gram uçlarında işlev sözcüğü olmaz; kökü içeren ifade atılır; iddia sözcüğü içeren ifade atılır; sıklık eşiği; bir işin iki sürümü bir kez sayılır; yazar sözcüğü ile başlık aynı ifadeyi verirse tek aday, `sources` ikisini de taşır; sıra kararlı (iki hash tohumu, karışık girdi).

## Task 3: `workflow/expansion.py` — alan sınaması ve karar

```python
MIN_FIELD_COUNT = 20      # records that hold the phrase together with the setting block
MIN_FIELD_SHARE = 0.2     # and that must be at least this share of all records holding the phrase
MAX_EXPANSION_TERMS = 8   # accepted phrases that enter the second round, in probe order
THRESHOLDS = {...}        # the three above plus MIN_DOCUMENT_FREQUENCY and MAX_PROBED_PHRASES

async def expand(vocabulary: dict[str, Any], found: list[Candidate], count) -> dict[str, Any]: ...
```

- Dağarcıkta sorguya giren hem `setting` hem `task` terimi yoksa sınama yapılmaz: `{"skipped": "single_block", ...}`. Ölçülen tek kural "ortam bloğuna karşı sına, görev bloğunu genişlet"tir; tek bloklu dağarcık için kural uydurulmaz.
- Her aday için iki sayım: `count(öbek)` ve `count(öbek AND ortam OR-grubu)`; ortam grubu, `vocabulary["terms"]`'teki sorguya giren biçimlerle, `workflow/vocabulary.py`'nin `_or_group` / `quoted` yardımcılarıyla kurulur. Kabul: ikinci sayım `≥ MIN_FIELD_COUNT` **ve** `≥ MIN_FIELD_SHARE × birinci sayım`. Sayımlardan biri `None` ise ifade **kabul edilmez** ve nedeni `count_unknown` yazılır. (04a'da bilinmeyen sayım öbeği sorguya sokuyordu, çünkü öbek kullanıcının sorusundan geliyordu; burada ifade veriden gelir ve bilinmeyen kanıt değildir.)
- `MAX_EXPANSION_TERMS` dolunca kalan adaylar sınanmaz (`not_probed`).
- Çıktı (adım çıktısı, kanonik sıralı): `{"skipped": null, "candidates": [{"phrase", "document_frequency", "sources", "phrase_count", "field_count", "accepted": bool, "reason": null | "below_field_count" | "below_field_share" | "count_unknown" | "not_probed"}], "terms": [kabul edilen öbekler, sınama sırasıyla], "probes": [...]}`.

- [ ] **Tests first** (sahte `count`): iki eşiğin her biri tek başına reddeder; `None` reddeder; tek bloklu dağarcık atlanır ve hiç sayım istemez; en çok `MAX_EXPANSION_TERMS` kabul edilir; her sınama `probes`'ta durur.

## Task 4: akışa bağlama, ikinci tur, protokol

`flow._discovery`, `sw` dalı, ilk tur arama döngüsü ile `failure and not searched()` denetimi bittikten **sonra**, `stage="screening"`'den önce:

1. `more = await self._expansion(run, scope, vocabulary, queries)`. `_expansion`: `store.step(run_id, "vocabulary_expansion", "code:vocabulary_expansion")`; `succeeded` ise saklı çıktıdaki ikinci tur sorgularını döndürür. Değilse aday kayıtlarını okur, `candidates` → `expand` (`self._count_probe(scope)`) → kabul edilen terim varsa ikinci tur sorgularını derler → çıktı ve sorgular adıma yazılır. `await` işlem dışında kalır; sayımlardan sonra `_checkpoint`.
2. İkinci tur sorgusu **yalnızca ek getiren koldur**: `ortam bloğu AND (kabul edilen öbekler)`. Derleme için yeni derleyici yazılmaz: görev bloğu yalnızca kabul edilen öbeklerden oluşan (`in_query = "phrase"`) bir dağarcık sözlüğü kurulur ve `compile_block_queries` ona çağrılır. İlk turun sorgusu yeniden atılmaz; böylece ikinci tur ilk turun kayıtlarını baştan okumaz ve genişlemenin getirdiği kayıtlar ayrı `search_runs` satırlarında sayılır.
3. Kabul edilen terim varsa protokol, ikinci turun ilk sağlayıcı isteğinden **önce** yeniden dondurulur: `freeze_protocol(..., reason="data_expansion")`, gövdede `expansion` (adaylar, sayımlar, kabul/ret nedeni), `compiled_queries` (ilk + ikinci tur), `arms: ["keyword_search", "data_expansion"]`, `thresholds.expansion = THRESHOLDS`. Kendi `protocol:expansion` adımıyla; adım `succeeded` ise yeniden dondurulmaz. Terim yoksa yeni revizyon yazılmaz ve gövde 04d'deki ile aynı kalır. `legacy` gövdesi ve özeti değişmez.
4. İkinci tur sorguları ilk turun ardından gelen indekslerle (`len(queries) + i`) `_search_pages`'ten geçer; `extra_page_requests` ilk + ikinci tur sorgularının tamamı üzerinden hesaplanır; D18 kuralları aynıdır (ikinci turda başarısız sağlayıcı koşuyu durdurmaz; koşunun zaten başarılı araması vardır).
5. `uploaded_seed` kipinde de aynı koşar. `source_scope == "attached"` zaten `_discovery`'den erken döner.

- [ ] **Tests first** (`tests/test_expansion_flow.py`, `tests/test_search_paging.py`'nin kalıbı; mock OpenAlex hem arama sayfalarını hem sayımları sunar):
  - **Kabul 1:** ilk tur başlıklarında sık geçen ve alan sınamasını geçen bir öbek, soruda geçmediği halde ikinci tur sorgusuna girer; ikinci turun getirdiği kayıtlar adaydır ve kendi `search_runs` satırlarındadır.
  - **Kabul 2:** model her çağrıda hata verirken genişleme ve ikinci tur koşar.
  - **Kabul 3:** genişleme adımından sonra duraklatılıp sürdürülen koşu hiçbir sayım isteğini ve hiçbir sayfayı tekrarlamaz.
  - iddia sözcüğü içeren aday hiçbir sorguda yok; hiç terim kabul edilmezse ikinci tur ve ikinci protokol revizyonu yok; kabul edilirse protokolün iki revizyonu var, ikincisinin gerekçesi `data_expansion`, ilki değişmemiş; aynı saklı çıktıyla ikinci kez kurulan gövdenin özeti aynı; sayım erişimi yoksa (`openalex` kapsam dışı) adım `count_unknown`'larla biter ve koşu sürer; `legacy` araştırmada adım açılmaz.
- [ ] `tests/determinism_stages.py`'ye `expansion` aşaması: sabit SYNTHETIC kayıtlar ve sabit sayım sözlüğüyle `candidates` → `expand`; iki hash tohumu ve iki karışımda tek özet.

## Task 5: terim başına verim

SW1.3'ün son cümlesi ve SW2.5 ("doğrulanmış bir pozitifte geçmeyen terim kalmaz") bir terimin ne getirdiğinin bilinmesini ister. Dahil edilme zamanla değişir, bu yüzden verim **saklanmaz, türetilir**:

`workflow/expansion.py::term_yields(store, research_id, scope_revision) -> list[dict]`: dağarcığın sorguya giren her terimi ve her genişleme terimi için `{"phrase", "origin": "question" | "key_terms" | "data", "block", "records": başlığında, özetinde ya da yazar sözcüklerinde terimin sorgudaki biçimi sözcük sınırında geçen aday iş sayısı, "included": bunlardan `selections.state == "included"` olanlar}`. Genişleme adımı, bittiği andaki `records` sayılarını kendi çıktısına `yield_at_expansion` olarak da yazar (o anın fotoğrafı). Görünüm ve arayüz dilim 08'dedir; bu dilim yalnızca işlevi ve testini kurar.

- [ ] **Tests first:** kök biçimiyle giren terim kökle, öbekle giren öbekle eşleşir; bir işin iki sürümü bir kez sayılır; kullanıcı bir kaydı dahil edince `included` artar; hiçbir kayıtta geçmeyen terim 0 ile listede kalır.

## Task 6: dilimi kapat

- [ ] **Ağsız kuru çalıştırma:** `.local/quantum-rank-fusion-2026-09-18/round.json`'daki ilk tur kayıtları (1.369) ve kuantum sorusunun `extract` çıktısıyla `candidates`'ın döndürdüğü 20 adayı, belge sıklıklarıyla, son iletiye yaz. Dosya yoksa söyle ve atla. Bu ölçüm değildir; gürültülü bir havuzdan ne tür ifadeler çıktığını sahibin görmesi içindir. **Ardından bu 20 aday için canlı sayım sınamasını bir kez koş** (en çok 40 OpenAlex sayım isteği, anahtarsız da çalışır) ve her adayın iki sayımını, kabul/ret nedenini son iletiye ve `.local/sw-expansion-dry-run-2026-09-21/` altına yaz. Zorunludur (karar, 21 Eylül 2026): eşikler doğrulanmış pozitiflerden öğrenen bir sondadan geliyor ve gürültülü havuzda hiç denenmedi; bu, inceleme sırasında elde olacak tek gerçek kanıttır. Ağ yoksa söyle ve dilimi yine bitir. Başka canlı istek yok. Eşikleri bu sonuca göre **değiştirme**; sonuç kötüyse son iletinin başında söyle.
- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `git diff --check`.
- [ ] `docs/decisions.md` en üste `## D<NN> — Widen the sw search from the first round's own titles and author keywords, probed by count, as a second arm that only adds`. Limits adıyla söylemeli: yalnızca `sw`; ölçülmedi (dilim 24); eşikler doğrulanmış pozitiflerden öğrenen tek konuluk bir sondadan alındı, ürün ise bütün adaylardan öğrenir ve bu koşul hiç ölçülmedi; alan sınaması ifadenin alanda kullanıldığını gösterir, görev bloğunun eş anlamlısı olduğunu değil; yazar anahtar sözcüğü yalnızca IEEE ve PubMed'den gelir, IEEE anahtarı olmayan bir mühendislik araştırmasında genişleme fiilen yalnızca başlık n-gramlarıdır, bu yüzden kullanıcıya ücretsiz bir IEEE Xplore anahtarı alması tavsiye edilir (tavsiyeyi gösteren ekran yok, dilim 08); OpenAlex'in atanmış sözcükleri ve Scopus `COMPLETE` alınmadı; tek bloklu dağarcıkta genişleme yok; terimler kullanıcıya gösterilmeden sorguya girer, onay ve düzeltme ekranı yok (dilim 08, SW2.6); özet n-gramları kullanılmadı; ikinci tur en çok bir kez koşar, üçüncü tur yok; verim türetilir ve hiçbir ekranda görünmez; koşullu model adımı yok (SW2.5, dilim 08); tarama hâlâ `max_candidates` ile kesilir; testler SYNTHETIC ve ağsız.
- [ ] SW belgesinde SW2 **Status** satırına bir cümle (madde 4 uygulandı, ölçülmedi). `sw-status.md` satır 04b: `uygulandı, inceleme bekliyor` + açık kalanlar + kuru çalıştırmanın özeti.
- [ ] `git pull --ff-only`, tek commit, `git push origin main` (ana plan §2.11).

## Son ileti

Değişen ve eklenen dosyalar; temel ve son test sayıları ve komut; kuru çalıştırmanın 20 adayı (ve koşulduysa canlı sınamanın sonucu); IEEE ve PubMed alanlarının nasıl doğrulandığı; yazıldığı gibi yapılamayan her şey ve seçilen her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: yok — aday havuzu büyür, protokol ikinci bir revizyon kazanabilir); canlı servise dokunulmadığı; commit özeti.

## Açık noktalar

- **Karar (21 Eylül 2026, sahip plan sohbetine bıraktı): OpenAlex'in `keywords` alanı alınmaz.** Bunlar yazarın değil, OpenAlex'in konu modelinin atadığı, denetimli bir listeden gelen genel sözcüklerdir; SW2.4 "yazar anahtar sözcükleri" der. Ayrıca alanı istemek OpenAlex'in `select` parametresini, yani `legacy` isteğini ve saklı yük özetlerini değiştirirdi. Bedeli: IEEE ya da PubMed kaydı gelmeyen araştırmada genişleme yalnızca başlık n-gramlarıyla çalışır. Sahibin bunun için önerisi (21 Eylül 2026): kullanıcıya ücretsiz bir IEEE Xplore anahtarı alması tavsiye edilir; yazar anahtar sözcüklerinin mühendislik konularındaki asıl kaynağı odur (yaşam bilimlerinde PubMed anahtarsız da verir). Bu dilim arayüze dokunmaz: tavsiye D kaydının Limits bölümüne yazılır, Ayarlar'daki metni dilim 08'dedir. Dilim 24 başlık n-gramlarının zayıf kaldığını gösterirse ayrı köken etiketiyle (`provider_keyword`) ve yalnızca `sw` isteğinde alınması yeniden açılır.
- **Yorum:** SW2.4 genişlemenin ne zaman sorguya gireceğini söylemez; SW2.6 dağarcığın kullanıcıya gösterilip dondurulmasını ister. Onay ekranı dilim 08'de olduğu için bu dilimde kabul edilen terimler doğrudan ikinci tura girer (04a'da ilk sorgunun onaysız koşması gibi). Bayrak arkasındadır; dilim 08 araya onayı koyar.
- **Yorum:** ikinci tur "ortam AND yeni terimler"dir, genişletilmiş bütün sorgu değil. Sonuç kümesi aynıdır (ilk tur ∪ ikinci tur), ama ilk turun 2.000 kaydı yeniden okunmaz ve terimin getirdiği ayrı sayılır.
- İfade seçimi yalnızca belge sıklığına bakar; gürültülü havuzda sık geçen ama ayırt etmeyen ifadeler öne geçebilir. Ayırt edicilik ölçüsü (ör. sıklığın `phrase_count`'a oranı) bilerek eklenmedi: ölçülmemiş ikinci bir sezgi olurdu. Kuru çalıştırma bunun gerekip gerekmediğini gösterecek.
