# SW dilim 06 — Ölçüt, parçaları ve ipucu ifadeleri önerisi: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): **SW15** madde 1, 2, 7 ve 21 Eylül eki; SW14 madde 1–2; SW11 madde 10. **Önkoşul:** dilim 01 (D70); 04a ve 04d kapandı (akışta yeri onlardan sonra). **Tür:** Kur (ölçülmedi); bilinen kusur kurulmadan önce düzeltildi. **İnceleme:** toplu.

**Goal:** Bir araştırmanın dahil etme ölçütü, parçaları, ipucu ifadeleri ve dışlama başlık sözcükleri bugün hiçbir yerde üretilmiyor; protokol gövdesinde dört alan `None` duruyor ve pasaj sıralaması elle yazılmış, tek konuya özgü `FORMULATION_TERMS`'e bakıyor. Bu dilim, modelin bunları **yalnızca sorudan** önerdiği adımı kurar: üç koşu, en az ikisinde geçen ifadeler kalır, sonuç ilk sağlayıcı isteğinden önce protokole girer. Bu dilimde ifadeler **hiçbir şeyi sıralamaz ve hiçbir kararı vermez**; kullanan dilimler 08 (onay ekranı), 09 (dışlama sözcükleri), 11 (ölçüt pasajları) ve 12'dir. Model kapalıysa dört alan `None` kalır ve akış sürer.

**Kurmadan önce yapılan düzeltme (plan sohbeti, 21 Eylül 2026):** `.local/sw-criterion-prompt-fix-2026-09-21/` (`protocol.md`, `run.py`, `result.md`). Eski istem "konu ve ortam bloklara bırakılır" dediği için model aranan şeyin kendisini de atıyordu (paket boyutu sorusunda kalan 40 ifadenin hiçbiri paket boyutunu adlandırmıyordu). Yeni istem (**RULES3**) ortamı aranan şeyden ayırıyor: ortam bloklarda kalır, aranan şey ölçüt cümlesinde adlandırılır ve kendi parçasını, kendi ifadelerini alır. Beş soruda (ikisi daha önce hiç denenmemiş) 15 koşunun 15'i ve beş uzlaşı listesinin beşi aranan şeyi taşıyor. **Bedeli:** kuantum konusundaki tek sıralama referansında kalan ifadeler 53 makalenin 37'sinde doğrulanmış alıntıyı ilk 6'ya getiriyor (eski istem 48, el listesi 49; beklenti en az 42 idi, tutmadı). İzin verilen tek ek düzeltme (RULES4) kusuru yine gideriyor ama sıralamayı 27'ye düşürüyor; ürüne **RULES3** girer. Sıralama bu dilimde kullanılmadığı için dilim durmaz; bulgu dilim 11'in başlangıç noktasıdır ve dilim 24'te iki konuda ölçülür.

**Architecture:** `flow._discovery`'nin `sw` dalında, `_vocabulary` döndükten sonra ve `protocol` adımından önce yeni `_criterion` çalışır. Önce araştırmanın kendi protokol kayıtlarına bakar: aynı soru ve yönlendirmeyle dondurulmuş bir ölçüt varsa onu alır, model çağrılmaz. Yoksa `criterion_proposal_1..3` adlı üç `optional` model adımı koşar; `workflow/criterion.py::consensus` üç çıktıyı birleştirir; sonuç `code:criterion` adımının çıktısında saklanır ve `build_protocol`'a verilir. `_freeze_expansion` aynı ölçütü ikinci protokol revizyonuna taşır.

**Tech stack:** Python 3.12. Yeni bağımlılık ve migration yok. Yeni sözleşme şeması ve yeni yöntem paketi dosyası var; `skill_package_hash` **değişir**.

## Global constraints

- `apps/web/` ve mevcut migration dosyalarına dokunma. Şema değişikliği yok: her şey adım çıktısında ve protokol gövdesinde durur.
- `legacy` araştırmada adım açılmaz, protokol gövdesi ve özeti aynı kalır (dört alan `None`). Mevcut hiçbir testin beklentisi değişmez; istisna, `sw` koşusunun adım sırasını sayan testlerdir (04d'de olduğu gibi) ve her biri son iletide adlandırılır.
- **Hiçbir zorunlu model çağrısı yok** (04a / 04d kabul koşulu): model her çağrıda hata verirken `sw` keşif koşusu yine arar.
- **Tek koşunun sonucu hiçbir yerde kullanılmaz** (SW15.2): ikiden az geçerli koşu varsa dört alan `None` kalır.
- Modelin "güçlü" işareti istenmez ve sözleşmede alanı yoktur (SW15.7).
- Ölçüt ve ifadeler bu dilimde hiçbir sıralamaya, karara, `stage_decisions` satırına ya da `selections`'a dokunmaz. `FORMULATION_TERMS` ve pasaj sıralaması olduğu gibi kalır.
- Ürün koduna ve yöntem dosyasına konuya özgü sözcük girmez. Denemenin beş sorusu (`run.py::Q`) ve 04d'nin ölçüm soruları yöntem dosyasına **örnek olarak yazılmaz**; örnek gerekiyorsa alan-bağımsız ve uydurma olur.
- Testlerde ağ yok; model `tests/fakes.py::FakeAdapter` ile sürülür. Fikstürler SYNTHETIC ve en az iki alandan.
- Başlamadan kontrol et: son karar `D77`, son migration `0043`. Bu dilim `D78` alır, migration almaz.

## Dosya yapısı

Yeni: `contracts/research/criterion-proposal.schema.json`, `methods/deixis-research/references/criterion-proposal.md`, `backend/deixis/workflow/criterion.py`, `tests/test_criterion_proposal.py`, `tests/test_criterion_flow.py`.

Değişecek: `contracts/research/step-input.schema.json` (`task_type` enum), `backend/deixis/domain/contracts.py`, `backend/deixis/domain/skill.py` (`RUNTIME_FILES`), `backend/deixis/domain/rules.py` (`LITERATURE_TASKS`), `backend/deixis/workflow/flow.py`, `backend/deixis/workflow/protocol.py`, `backend/deixis/workflow/store.py` (`frozen_criterion`), `methods/deixis-research/SKILL.md` ve `provenance.json`, `tests/fixtures/research/{step-inputs,fake-outputs}.json`, `tests/fakes.py::valid_response`, `tests/determinism_stages.py`, `docs/decisions.md`, SW belgesi (SW15 durum satırı), `docs/product/sw-status.md`.

## Task 1: sözleşme

`contracts/research/criterion-proposal.schema.json`, `schema_version = "deixis.criterion_proposal.v1"`. Dört zarf alanı (`vocabulary-labels.schema.json` ile aynı) artı:

```json
{"criterion": "…",
 "parts": [{"name": "…", "definition": "…", "phrases": ["…"]}],
 "exclusion_title_words": ["…"]}
```

`additionalProperties: false`. Sınırlar: `criterion` 1–600 karakter; `parts` 2–5; `name` 1–60, `definition` 1–400; `phrases` parça başına 6–15, her biri 1–80 karakter; `exclusion_title_words` 0–30, her biri 1–40 karakter. Katı model şeması dizi sınırlarını taşıyamıyorsa (bkz. `step_output_schema`'nın mevcut davranışı) sınırlar anlam denetimine iner. Gerekçe alanı ve `strong` alanı yoktur.

Adım girdisi yeni bir hedef **almaz**: `question` ve `user_steering` zaten adım girdisindedir (SW15.1: "yalnızca sorudan"). Sözcük dağarcığı ve bloklar modele gösterilmez. `step-input.schema.json`'da yalnızca `task_type` enum'una `criterion_proposal` eklenir.

`domain/contracts.py`: görev → çıktı türü eşlemesi, `step_output_schema("criterion_proposal")`, ve `_check_criterion_proposal` — hepsi **hata**: parça sayısı 2–5 dışında; bir parçada 6'dan az ya da 15'ten çok ifade; 4 sözcükten uzun ifade; normalleştirilince (`criterion.norm`) boş kalan ifade; aynı parçada yinelenen ifade; normalleştirilmiş adı yinelenen parça. Bir ifadenin iki parçada geçmesi hata **değildir**. `rules.LITERATURE_TASKS`'e `criterion_proposal` eklenir (yazın modeli koşar). Şema onarımı bu adımda **açıktır** (`NO_REPAIR_TASKS`'e girmez): izin listesi yok, onarımın uydurabileceği bir kimlik yok.

- [ ] **Tests first:** geçerli çıktı geçer; tek parça, 16 ifade, 5 sözcüklü ifade, yinelenen parça adı ayrı ayrı reddedilir; `valid_response` yeni görevi üretir; iki fikstür dosyasına giriş eklenir.

## Task 2: yöntem paketi

`methods/deixis-research/references/criterion-proposal.md`, İngilizce, paketin üslubuyla, `vocabulary-labels.md` kalıbında (Goal, numaralı adımlar, zarf alanları satırı, "Hard cases"). İçerik, denemede ölçülen **RULES3**'ün kurallarıdır ve anlamı değiştirilmeden taşınır (`.local/sw-criterion-prompt-fix-2026-09-21/run.py::RULES3`; alan adı orada da `exclusion_title_words`):

1. Soru ve `user_steering` okunur; bir okurun tam metinde denetleyebileceği dahil etme ölçütü yazılır.
2. 2–5 parça; her parça makalenin kendisinin yaptığı ya da söylediği bir şeydir, andığı bir konu değil. Parça başına 6–15 ifade, 1–4 sözcük, küçük harf, yazarın metinde gerçekten yazacağı biçimde ya da standart kısaltma / gösterim olarak.
3. **Ortam** (sorunun sorulduğu nüfus, sistem, alan, malzeme, çevre) aramanın bloklarında kalır: ortamdan parça yapılmaz, yalnızca ortamı adlandıran ifade verilmez.
4. **Aranan şey** (varlığı bir makaleyi soruya yanıt yapan belirli müdahale, yöntem, nicelik, nesne ya da sonuç türü) ortam değildir, alanın yaygın bir terimi olsa bile: ölçüt cümlesinde adlandırılır, kendi parçasını alır, o parça yazarların onu anlatırken kullandığı ifadeleri (eş anlamlılar ve standart kısaltmalar dâhil) taşır.
5. Sorunun karşılaştırılmasını ya da raporlanmasını istediği yönler parça değildir. Kalan parçalar makalenin ne tür bir çalışma ya da içerik taşıması gerektiğini söyler.
6. `exclusion_title_words`: konuyla ilgili olup bu türden birincil çalışma olmayan makalelerin başlık sözcükleri.

RULES4'ün iki cümlesi (birincil çalışma parçası yok; hiçbir makalede eksik olmayan ifade yok) **eklenmez**: denemede sıralamayı düşürdü. `domain/skill.py::RUNTIME_FILES`'a `"criterion_proposal": ("SKILL.md", "references/criterion-proposal.md")`; `SKILL.md`'de göreli bağlantı; `provenance.json`'a giriş (DEIXIS için yazıldı, üst kaynaktan uyarlanmadı; ölçüm klasörü adıyla; beş sorunun dosyada geçmediği).

- [ ] **Tests first:** paket bütünlük denetimi geçer; yeni görevin dosyaları yüklenir; `package_hash` değişir ve testlerde sabit bir beklenen özet varsa güncellenir.

## Task 3: `workflow/criterion.py`

```python
PROPOSAL_RUNS = 3        # SW15.2
PROPOSAL_MAJORITY = 2
THRESHOLDS = {"proposal_runs": PROPOSAL_RUNS, "proposal_majority": PROPOSAL_MAJORITY}

def norm(text: str) -> str: ...            # lower case, whitespace collapsed, surrounding punctuation stripped
def consensus(question: str, runs: dict[int, dict[str, Any]]) -> dict[str, Any] | None: ...
```

`runs`, koşu numarası (1–3) → geçerli çıktının `result`'ıdır; başarısız koşu sözlükte yoktur. Kural, denemede kodla uygulanan kuralın aynısıdır:

- `len(runs) < PROPOSAL_MAJORITY` ise `None` döner.
- Bir koşunun ifade kümesi, bütün parçalarındaki ifadelerin `norm` hâlidir. En az `PROPOSAL_MAJORITY` koşunun kümesinde geçen ifade **kalır**.
- **Taban koşu:** kalan kümeyle en çok ifade paylaşan koşu; eşitlikte en küçük koşu numarası. Ölçüt cümlesi ve parçalar (ad, tanım) taban koşunundur: serbest metin oylanamaz, bu yüzden "tek koşu kullanılmaz" kuralı ifadeler, dışlama sözcükleri ve "en az iki geçerli koşu" koşulu için geçerlidir; bu bir plan kararıdır ve D kaydında adıyla yazılır.
- Kalan her ifade taban koşuda geçtiği **ilk** parçanın adını alır; taban koşuda geçmiyorsa `part = None` olur (ileride sıralar, hiçbir parça için sayılmaz). Hiç ifadesi kalmayan parça ifadesiz olarak durur; tek koşunun ifadeleri geri konmaz.
- Dışlama başlık sözcükleri aynı oyla kalır. Normalleştirilmiş sözcüklerinin hepsi soru metninde geçen dışlama sözcüğü düşer ve `dropped_exclusion_title_words`'e yazılır (SW5.1'in aynı koruması: soru derlemeleri soruyorsa "survey" dışlama sözcüğü olamaz).
- Çıktı sırası belirlenimlidir: parçalar taban koşunun sırasıyla, ifadeler ve sözcükler alfabetik; hiçbir yerde küme yinelemesi ya da koşuların geliş sırası sonucu belirlemez.

Dönen sözlük: `{"criterion", "parts": [{"name", "definition"}], "cue_phrases": [{"phrase", "part", "runs": [1, 3]}], "exclusion_title_words", "dropped_exclusion_title_words", "base_run", "runs_ok": [1, 2, 3], "sought_term_in_criterion"}`.

`sought_term_in_criterion` bilinen kusurun ürün içi izidir, yalnızca kayıttır ve hiçbir şeyi değiştirmez: `consensus`'a isteğe bağlı üçüncü argüman olarak sözcük dağarcığının `task` bloğundaki sorgulanan terimleri (öbek ve kök biçimleri) verilir; biri ölçüt cümlesinde, bir parça adında ya da tanımında alt dizi olarak geçiyorsa `True`, hiçbiri geçmiyorsa `False`, terim yoksa `None`. Dilim 08 bunu uyarı olarak gösterebilir; dilim 24 sayar.

- [ ] **Tests first:** 3/3 ve 2/3 ifade kalır, 1/3 kalmaz; tek geçerli koşu `None`; taban koşu seçimi ve eşitlikte küçük numara; taban koşuda olmayan ifade `part = None`; ifadesi kalmayan parça durur; soruda geçen dışlama sözcüğü düşer; koşu sözlüğünün kuruluş sırası değişince çıktı bayt bayt aynı; `sought_term_in_criterion` üç değeri de alır.

## Task 4: akışa bağlama

`store.frozen_criterion(research_id, question, steering)`: araştırmanın `inclusion_criterion`'ı `None` olmayan ve gövdesindeki `question` ile `steering` verilenlere eşit olan **en yeni** protokol kaydının ölçüt alanlarını (ve `protocol_revision`'ını) döndürür, yoksa `None`. Kapsam revizyonuna bakmaz: sağlayıcı listesi değişen ama sorusu aynı kalan revizyon modeli yeniden sormaz; aksi hâlde ölçüt her revizyonda başka sözcüklerle gelir ve `decisions.is_stale` bütün kararları eskimiş sayardı (SW11.10, `CRITERION_FIELDS`).

`flow._criterion(run, scope, vocabulary) -> dict | None`, `sw` dalında `_vocabulary`'den sonra, `protocol` adımından önce:

- `code:criterion` adımı (`operation_key = "criterion"`) `succeeded` ise saklı çıktısı döner; sürdürülen koşu modeli yeniden çağırmaz.
- `frozen_criterion` bir kayıt veriyorsa o alınır, adım çıktısına `origin = "protocol"` ve alındığı `protocol_revision` yazılır, **model çağrılmaz**.
- Aksi hâlde `for index in range(PROPOSAL_RUNS)`: önce `_checkpoint`, sonra `_model_step(run, scope, f"criterion_proposal_{index + 1}", "criterion_proposal", optional=True)`. `OptionalStepFailed` ve `invalid` çıktı `failures`'a yazılır, koşu durmaz ve duraklamaz (`_vocabulary_labels` kalıbı). İlk iki koşu da başarısızsa üçüncü çağrı **atılmaz** (artık çoğunluk kuramaz; 04d incelemesinde görülüp bırakılan durumun burada baştan kapatılması).
- `consensus` çağrılır; adım çıktısı `{"origin": "model" | "protocol" | None, "criterion": <consensus sözlüğü ya da None>, "failures": [...]}` olur ve kanonik sıralıdır. `origin = None`, ölçütün kurulamadığı demektir; bu da `succeeded` bir adımdır, böylece sürdürme yeniden denemez. Aynı kapsamda **yeni** bir keşif koşusu ise yeniden dener (dondurulmuş ölçüt yoktur); bu istenen davranıştır.
- Bütçe: çağrılar `max_model_calls`'a sayılır; bütçe dolduysa `_model_step` zaten `OptionalStepFailed` atar. Tarama bütçesiyle ilişkisi dilim 09'un (K3) işidir, burada yalnızca not edilir.

`protocol.build_protocol(..., criterion: dict | None = None)`: `inclusion_criterion` = cümle; `criterion_parts` = `[{name, definition}]`; `cue_phrases` = `[{phrase, part, runs}]`; `exclusion_title_words` = liste. Verilmezse dördü `None` kalır, yani `legacy` gövdesi aynıdır. Kaynak kaydı (`origin`, `base_run`, `runs_ok`, `dropped_exclusion_title_words`, `sought_term_in_criterion`) `criterion_origin` adlı **ayrı** bir alana, yalnızca `criterion` verildiğinde yazılır: `CRITERION_FIELDS` özetine girmemelidir, yoksa aynı ölçütün protokolden yeniden okunması kararları eskitirdi. `thresholds.criterion` = `THRESHOLDS`, yalnızca `sw`'de. `_discovery`'deki `protocol` adımı ve `_freeze_expansion` aynı `criterion`'ı verir; ikincisi vermezse genişleme revizyonu ölçütü `None`'a çevirir ve her kararı eskitir — bu dilimin en kolay kaçan hatasıdır ve testi zorunludur.

- [ ] **Tests first** (`tests/test_criterion_flow.py`, `create_app` ile): model her çağrıda hata verirken keşif koşusu arar, dört alan `None`, koşu duraklamaz; üç geçerli koşuda protokol dört alanı taşır ve ilk sağlayıcı isteğinden **önce** dondurulmuştur; iki koşu başarısızsa üçüncü çağrı atılmaz ve alanlar `None`; duraklatılıp sürdürülen koşu modeli yeniden çağırmaz; aynı kapsamda ikinci keşif koşusu ve sorusu aynı kalan yeni kapsam revizyonu modeli çağırmaz, ölçüt alanlarının özeti aynıdır; sorusu değişen revizyon yeniden sorar; genişleme revizyonu ölçütü taşır; `legacy` araştırmada adım açılmaz ve protokol özeti bu dilimden önceki değerle aynıdır; `vocabulary_empty` / `key_terms_needed` ile duran koşu ölçüt için model çağırmaz; hiçbir `stage_decisions` ve `selections` satırı değişmez.

## Task 5: tekrar aşaması

`tests/determinism_stages.py`'ye `criterion` aşaması: sabit üç koşuluk çıktı, karıştırılmış koşu ve ifade sırası, iki hash tohumu; tek özet.

## Task 6: dilimi kapat

- [ ] **Canlı kuru çalıştırma (zorunlu, 6 model çağrısı):** iki konu sorusu (kuantum dolanıklık dağıtımı; KAA'da paket boyutu — metinleri `run.py::Q`'da) ürünün kendi adımından geçer: gerçek adım girdisi, katı şema, yöntem paketi, `deepseek-flash`, DeepSeek bağlantısı, efor `high`; ayrı bir `DEIXIS_DATA_DIR`, sağlayıcı isteği atılmadan (ölçüt adımı aramadan önce biter; koşu orada durdurulabilir ya da `_criterion` doğrudan sürülebilir). Çıktı `.local/sw-criterion-dry-run-2026-09-21/`'e yazılır. Son iletiye: iki sorunun ölçüt cümlesi, parçaları, kalan ifade sayısı, `sought_term_in_criterion`, kaç koşunun şemayı ilk denemede geçtiği, çağrı süreleri. Deneme çıplak bağdaştırıcıyla yapıldı; bu adım aynı kuralların ürün yolundan da aranan şeyi koruduğunu gösterir. İstem sonuca göre **ayarlanmaz**; aranan şey kayboluyorsa son iletinin ilk cümlesi bu olur. Canlı kütüphaneye ve 8765 portuna dokunulmaz.
- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `git diff --check`.
- [ ] `docs/decisions.md` en üste `## D78 — Let a model propose the inclusion criterion, its parts and cue phrases from the question alone, three times, and keep what two runs agree on`. Limits adıyla söylemeli: yalnızca `sw`; ifadeler henüz hiçbir şeyi sıralamıyor ve hiçbir kararı vermiyor; kusur düzeltmesi beş soruda, tek modelle, istemi yazanın kendi desenleriyle sınandı; **kuantum referansında sıralama 48'den 37'ye düştü** ve nedeni tam bilinmiyor (her makalede geçen ifadeler oyu en kolay kazanıyor); ölçüt cümlesi ve parçalar tek koşudan geliyor; ortam parçası olmadığı için aranan şeyi başka ortamda yapan makale bütün parçaları karşılar; dışlama sözcükleri denetlenmedi; onay ekranı yok (dilim 08); keşif başına en çok üç model çağrısı ve aramadan önce ölçülen süre; `skill_package_hash` değişti.
- [ ] SW belgesinde SW15 **Status** satırına bir cümle. `sw-status.md` satır 06: `uygulandı, inceleme bekliyor` + açık kalanlar. Tek commit, `git push origin main` (ana plan §2.11).

## Son ileti

Eklenen ve değişen dosyalar; temel ve son test sayıları ve komut; eski ve yeni `skill_package_hash`; kuru çalıştırmanın iki sorusu için yukarıdaki döküm; model kapalıyken aramanın koştuğunu gösteren testin adı; adım sırası yüzünden güncellenen her mevcut test; yazıldığı gibi yapılamayan her şey ve seçilen her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: yok; protokol gövdesi ve yöntem paketi özeti değişir, `sw` araştırmalarında ölçüt alanları dolunca `is_stale` ilk kez gerçek bir özetle karşılaştırır); canlı servise dokunulmadığı; commit özeti.

## Açık noktalar

- **Sıralama bedeli (sahip görmeli):** RULES3 kusuru gideriyor ama kuantumda ifadelerin pasaj sıralaması 48 → 37. Dilim 11 bu tablodan başlar; aday çareler (oyu her makalede geçen ifadelerin kazanması, parça başına ayrı sıralama, aranan şey parçasının sıralamadan çıkarılması) orada ölçülür, burada kurulmaz.
- **Ortam parçası yok:** SW15.1 böyle karar verdi. Tam metin kararında (dilim 12) ortamın nasıl denetleneceği orada yazılmalıdır; kapsam kuralı SW9'dadır ve yalnızca özet aşamasında koşar.
- **Süre:** üç çağrı sırayla koşar; denemede çağrı başına 16–37 sn, yani ilk aramadan önce 1–2 dakika. Dilim 08 koşuyu onay için zaten durduracağı için kabul edildi; kuru çalıştırma süreyi ürün yolunda ölçer. Eşzamanlı çağrı `ModelCallLimiter(1)` varsayılanıyla kazanç vermez.
- **Kullanıcının düzeltmesi** (SW15.3) ve "model yeniden sorulmaz"ın kullanıcı eliyle yeniden sordurma yolu dilim 08'dedir. Bu dilimde ölçütü yeniden ürettirmenin tek yolu soruyu değiştiren bir kapsam revizyonudur.
- `key_terms` veren kullanıcı için de adım koşar: ölçüt sorudan gelir, dağarcıktan değil. Soru İngilizce değilse de koşar; ifadelerin dili denetlenmez (ölçülmedi).
