# SW dilim 09 — Özet taraması v2: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): **SW9** madde 1–4, **SW1** madde 1, 2, 6, **SW11** madde 1, 3, 4, SW6 madde 2, SW5 madde 5. **Önkoşul:** 02, 04a–d, 05, 07, 08a (hepsi kapandı). **Tür:** Kur. **İnceleme:** tam (Fable · high), dilim 10 başlamadan önce.

**K3 kararı (sahip, 21 Eylül 2026; ölçüm `.local/sw-abstract-batch-2026-09-21/result.md`):** özet aşamasında model, sıranın başındaki **N iş**i okur; N efora göre **40 / 100 / 300** (quick / standard / detailed). Çağrı başına **20 kayıt**, **iki bağımsız koşu**, çağrılar mevcut `ModelCallLimiter` üzerinden eşzamanlı. Okunmayan kayıt silinmez: `abstract_not_read` ile `unresolved` kalır ve aynı soruda sonraki keşif koşusu kaldığı yerden okur. Ölçülen: 20'li parti iki konuda tek kayıtlı çağrıyla aynı sonucu verdi (100'de 96, 60'ta 54 eşleşme), süre yarıya indi; dört eşzamanlı çağrıyla 100 kayıt × iki koşu 71 sn sürdü. Ölçülmeyen: etiketlerin doğruluğu (insan etiketi yok).

**Goal:** Bugün bir `sw` keşif koşusu sıralamadan sonra eski `screening` sözleşmesiyle tarar: model `include` / `exclude` önerir, öneri doğrudan `selections`'a yazılır ve liste `max_candidates` ile kesilir. Bu dilimden sonra `sw` koşusunda (1) kod her kaydı sınıflar ve gerekçe koduyla `stage_decisions`'a yazar; (2) kodun kapatamadığı işlerin ilk N'i için model tek etiket + özetten birebir alıntı önerir, iki koşu hâlinde; (3) kod alıntıyı özette arar, iki koşuyu birleştirir ve kararı yazar; (4) sonuç iş düzeyinde birleşip `selections`'ı türetir. **Özetten `included` çıkmaz.** `legacy` akış olduğu gibi kalır.

**Architecture:** yeni saf modül `workflow/abstract_stage.py` (kod aşaması, okuma planı, alıntı doğrulama, birleştirme kuralı). `flow._discovery`'nin `sw` dalında `_ranking`'den sonra `_abstract_stage` çalışır; eski tarama döngüsü yalnızca `legacy` dalında kalır. Adımlar: `code:abstract_stage` (anahtar `abstract_stage`; kod kararları + dondurulmuş okuma planı), `model:abstract_screening` (anahtar `abstract_screening:{parti}:{koşu}`, koşu ∈ 1, 2), görev türü `abstract_screening`. Yeni sözleşme ve yöntem dosyası; **migration yok** (`stage_decisions` ve `model_proposals` dilim 02'de geldi).

**Tech stack:** Python 3.12. `skill_package_hash` **değişir**. `apps/web`'de yalnızca Task 7'nin iki satırlık faz eşlemesi.

## Global constraints

- `legacy` araştırmada adım açılmaz, `screening` sözleşmesi, `max_candidates` kesmesi, protokol gövdesi ve özeti aynı kalır.
- **Karar yetkisi koddadır** (SW1.1): model yalnızca etiket + alıntı + bir cümle gerekçe önerir; güven puanı yok. Model kapalıyken kod aşaması yine yazılır.
- **Özet hiçbir kaydı dahil etmez** (SW1.2): `sw` koşusunda `apply_screening_proposal` çağrılmaz; hiçbir seçim bu dilimde `included` olmaz.
- **Kayıt silinmez, gizlenmez.** Kullanıcının kararı (`decided_by = human`, `selections.origin = user`) her şeyin üstündedir; `HumanDecisionStands` yutulmaz, o kayıt atlanır.
- **Özeti olmayan kayıt hiçbir yoldan `out_of_scope` olmaz** (SW5.5). Dilim 05'in kodlarına (`no_abstract`, `abstract_not_found`, `survey_title_word`) bu dilim dokunmaz.
- **Tek eşleyici:** blok varlığı `ranking.block_scores`'un kullandığı biçim eşlemesiyle (sözcük başı) aranır; ortak bir yardımcıya çıkarılır, ikincisi yazılmaz. Bloklar `ranking.query_vocabulary`'nin döndürdüğü `blocks`'tur (onaylanmış dağarcık + kabul edilen genişleme terimleri), yani sıralamanın okuduğuyla aynı.
- **Tek alıntı bulucu:** `contracts.locate_anchor`. Doğrulanmış sayılan: `exact` ya da `normalized` eşleşme **ve** alıntı en az `ABSTRACT_QUOTE_MIN_CHARS = 12` karakter. `fuzzy` doğrulanmış sayılmaz (SW1.1 "birebir").
- Elle seçilen her sayı adlı sabittir ve protokolün `thresholds.abstract_screening` alanına yazılır: `ABSTRACT_READ_LIMIT = {"quick": 40, "standard": 100, "detailed": 300}`, `ABSTRACT_BATCH = 20`, `ABSTRACT_RUNS = 2`, `ABSTRACT_QUOTE_MIN_CHARS = 12` (`domain/rules.py`).
- Testlerde ağ yok. Fikstürler SYNTHETIC ve en az iki alandan. Ürün koduna ve yöntem dosyasına konuya özgü sözcük girmez.
- Başlamadan kontrol et: son karar `D80`, son migration `0044`. Bu dilim `D81` alır, migration almaz.

## Dosya yapısı

Yeni: `contracts/research/abstract-screening.schema.json`, `methods/deixis-research/references/abstract-screening.md`, `backend/deixis/workflow/abstract_stage.py`, `tests/test_abstract_stage.py` (saf), `tests/test_abstract_flow.py` (`create_app` ile).

Değişecek: `contracts/research/step-input.schema.json` (`task_type` enum, isteğe bağlı `screening_target`), `domain/contracts.py`, `domain/skill.py`, `domain/rules.py`, `domain/reason_codes.py`, `workflow/flow.py`, `workflow/ranking.py` (yalnızca eşleyicinin ortak yardımcıya çıkarılması), `workflow/protocol.py`, `api/app.py` (bütçe), `methods/deixis-research/SKILL.md` ve `provenance.json`, `tests/fixtures/research/{step-inputs,fake-outputs}.json`, `tests/fakes.py::valid_response`, `tests/acceptance/fixture_server.py` (betikli model yeni görevi yanıtlar), `tests/determinism_stages.py`, `apps/web/src/Transcript.tsx`, `labels.ts`, `i18n.ts`, `docs/decisions.md`, SW belgesi (SW9 ve SW11 durum satırları), `sw-status.md`.

## Task 1: gerekçe kodları ve kod aşaması (saf)

`domain/reason_codes.py`'ye dört kod; var olan hiçbir kodun anlamı değişmez:

| kod | aşama | sonuç | karar veren | sonraki adım |
|---|---|---|---|---|
| `abstract_not_read` | abstract | unresolved | code | abstract_model |
| `runs_agree_unresolved` | abstract | unresolved | model_agreement | fulltext_fetch |
| `notice_record` | abstract | out_of_scope | code | none |
| `artifact_of_paper` | abstract | out_of_scope | code | none |

`abstract_stage.code_outcome(record, blocks, links) -> str | None`, **kayıt başına** (işin her sürümü için; havuz `ranking._versions` ile tek sorguda okunur), sırayla:

1. `record_kind == "notice"` → `notice_record`.
2. `record_kind == "artifact"` **ve** kaydın saklı, geri alınmamış bir `artifact_of` bağlantısı var → `artifact_of_paper`. **Bağlantısı olmayan ek ürün normal kayıt gibi sürer** (adıyla sapma, SW6.2'den dar: Zenodo / figshare DOI'si bir makalenin tek kopyası olabilir; dilim 03'te 127 çiftin 85'i bağlantı almayan ek üründü).
3. Kaydın güncel özet kararı `survey_title_word`, `no_abstract` ya da `abstract_not_found` ise → `None`, karar yerinde kalır.
4. İki geçit bloğu da **başlıkta** → `blocks_in_title`.
5. Kaydın kendi özeti var ve iki bloğun **ikisi de** başlık + özette yok → `both_blocks_missing`. Biri eksikse kod kapatmaz (SW9.2).
6. Aksi hâlde `None`: model okuyabilir.

- [ ] **Tests first:** altı dalın her biri; özeti olmayan kayıt hiçbir girdiyle `both_blocks_missing` almaz; bağlantısız ek ürün 4–6'dan geçer; çoğul biçim kök biçimle eşleşir, sözcük ortası eşleşmez (`ranking` ile aynı beklenti); tablo doğrulaması yeni kodları kabul eder.

## Task 2: sözleşme ve yöntem paketi

`abstract-screening.schema.json`, `schema_version = "deixis.abstract_screening.v1"`, dört zarf alanı (`vocabulary-labels` ile aynı) artı `{"records": [{"candidate_id", "label": "candidate" | "out_of_scope" | "unresolved", "quote", "rationale"}]}`; `quote` 0–600, `rationale` 1–300 karakter; `additionalProperties: false`.

Adım girdisi: `candidates` bugünkü biçimde (başlık, yıl, yer, `MAX_ABSTRACT_CHARS`'a kesilmiş özet); yeni isteğe bağlı alan `screening_target: {"runs": 2, "run": 1 | 2}`. **Ölçüt cümlesi, parçalar, ifadeler ve bloklar modele gösterilmez:** ölçümde ölçüt cümlesini gören model onu özetten yargıladı (aday sayısı 82 → 48). Model `candidate_id` yerine kısa tutamak görür (`cnd_C0000001`; D12 kalıbı: `citation_handles` bu görev için adayları da numaralar, çıktı doğrulamadan önce geri çözülür); saklanan adım girdisi gerçek kimlikleri tutar. Eski `screening` görevi tutamaksız kalır.

`domain/contracts.py`: görev → çıktı türü, `step_output_schema`, `_check_abstract_screening`. **Kayıt düzeyindeki kusur çıktıyı geçersiz kılmaz, uyarıdır:** izin listesinde olmayan kimlik, yinelenen kimlik, `candidate` / `out_of_scope` etiketinde boş alıntı. Böyle bir giriş için o koşuda öneri **yok** sayılır (yinelenende ilki de atılır); eksik kayıt da öyle. Şemaya uymayan çıktı geçersizdir. `rules.LITERATURE_TASKS`'e ve **`NO_REPAIR_TASKS`'e** eklenir: onarım çağrısı yok, çünkü geçersiz partinin kayıtları kaybolmaz, okunmamış sayılır.

Yöntem dosyası `references/abstract-screening.md`, İngilizce, `vocabulary-labels.md` kalıbında. İçerik ölçülen **`GENERIC2`**'nin kurallarıdır, anlamı değiştirilmeden (`.local/sw-abstract-batch-2026-09-21/run_generic.py`): yalnızca tam metin okumaya değer mi diye bakılır, dahil etme kararı verilmez; `candidate` = özet, işin sorunun adlandırdığı ortamda ve sorduğu görev / sorun / olgu üzerinde çalıştığını gösteriyor, sorunun aradığı belirli şeyin (yöntem, model, sonuç, karşılaştırma) varlığı burada **yargılanmaz**; `out_of_scope` = başka ortam, başka sorun ya da konuyu yalnızca anıyor; `unresolved` = özetten anlaşılmıyor; etiketi destekleyen **tek** alıntı o kaydın kendi özetinden birebir kopyalanır (yalnızca `unresolved`'da boş olabilir); her kayıt kendi başına yargılanır, listedeki öbür kayıtlar kanıt değildir; her kayıt için verilen sırayla tek giriş. `RUNTIME_FILES`'a `"abstract_screening": ("SKILL.md", "references/abstract-screening.md")`; `SKILL.md`'de göreli bağlantı; `provenance.json`'a giriş (DEIXIS için yazıldı; ölçüm klasörü adıyla; **bilinen kusur:** konudan bağımsız istem, elle yazılmış kuantum istemine göre daha dar ve daha kararsız okuyor — 100 kayıtta 77 eşleşme, 17 koşu anlaşmazlığı; iki deneme sorusu dosyada geçmez).

- [ ] **Tests first:** geçerli çıktı geçer; bilinmeyen ve yinelenen kimlik uyarı olur, çıktı geçerli kalır; şema dışı etiket geçersizdir; tutamaklar geri çözülür; `valid_response` yeni görevde her kayda `candidate` ve o kaydın özetinin ilk 60 karakterini alıntı verir (özet yoksa `unresolved`, boş alıntı); iki fikstür dosyasına giriş; paket bütünlük denetimi geçer, `package_hash` değişir.

## Task 3: okuma planı ve birleştirme (saf)

`abstract_stage.read_plan(order, works, limit, batch) -> {"batches": [[svid, …], …], "not_read": [svid, …]}`. Birim **iş**tir (SW9.4). Bir iş okuma listesine girer, eğer: hiçbir sürümü `blocks_in_title` değil ve hiçbir sürümünde insan kararı yok; **okunacak sürümü** var (aşağıda); o sürümün güncel özet kararı yok ya da `abstract_not_proposed` / `abstract_not_read` ya da **eskimiş** (`DecisionStore.is_stale`). Eskimemiş bir model kararı (`runs_agree_*`, `runs_disagree_kept_as_candidate`, `quote_not_found_kept_as_candidate`) taşıyan iş yeniden okunmaz: "ikinci koşu kaldığı yerden okur" budur ve aynı kayıt için model ikinci kez sorulmaz.

**Okunacak sürüm:** işin, kendi özeti olan ve Task 1'in 1–3. ve 5. dallarına düşmeyen sürümlerinden işin başı; baş uygun değilse en küçük kimlikli olan. Modele o sürümün başlığı ve özeti gider; öneri ve karar o sürüme yazılır. (Dilim 05'in açığı kapanır: kendi özeti olmayan baş, başka sürümünün özetiyle okunur.) Sıra, `order`'daki baş kimliğinin yeridir; `order`'da olmayan iş sonda, kimlik sırasıyla. İlk `limit` iş `batch`'lik partilere bölünür, gerisi `not_read`.

`abstract_stage.combine(first, second) -> str` (her biri `{"label", "quote_verified"}` ya da `None`):

| durum | kod |
|---|---|
| biri `None` (parti başarısız, giriş atıldı, eksik) | `abstract_not_proposed` |
| ikisi `unresolved` | `runs_agree_unresolved` |
| etiketler farklı (her çift) | `runs_disagree_kept_as_candidate` (SW11.4) |
| aynı etiket (`candidate` / `out_of_scope`), alıntılardan biri doğrulanmadı | `quote_not_found_kept_as_candidate` |
| ikisi `candidate`, iki alıntı doğrulandı | `runs_agree_candidate` |
| ikisi `out_of_scope`, iki alıntı doğrulandı | `runs_agree_out_of_scope` |

Alıntı, modele **gösterilen** (kesilmiş) özette aranır.

- [ ] **Tests first:** tablonun her satırı ve simetrisi; plan sırayı izler, `limit`'te keser, hiçbir işi düşürmez (`batches` ∪ `not_read` = uygun işler); kod adayı olan iş, insan kararlı iş ve taze model kararlı iş listeye girmez; eskimiş kararlı iş girer; başı özetsiz iş kardeş sürümüyle girer; plan iki hash tohumunda aynıdır.

## Task 4: akış (önce sıralı)

`flow._abstract_stage(run, scope, vocabulary, order)`; `_discovery`'de `sw` dalı onu çağırır, eski döngü `else` dalında **bayt bayt** kalır. `held_from_screening` silinmez (`record_flags` çıktısı sayıyor), ama `sw` tarama listesi artık ondan değil plandan gelir.

1. **`code:abstract_stage` adımı.** `succeeded` ise saklı çıktı okunur ve **plan yeniden hesaplanmaz** (dilim 07 incelemesinin hatası: sürdürülen koşuda liste kayarsa parti anahtarları başka kayıtlara düşer). Değilse: her sürüm için `code_outcome`; yazma kuralı dilim 05'in `_should_write`'ıyla aynı ruhta — güncel karar aynı kodsa ya da bu dilimin sahip olmadığı taze bir kodsa yazılmaz; insan kararı atlanır. Bu dilimin sahip olduğu kodlar: `blocks_in_title`, `both_blocks_missing`, `notice_record`, `artifact_of_paper`, `abstract_not_read`, `abstract_not_proposed` ve dört model kodu + `runs_agree_unresolved`. Sonra `read_plan`; `not_read` için `abstract_not_read`. Çıktı: `{"decisions": {kod: n}, "limit", "batch", "runs", "batches": [[…]], "not_read": n, "works_needing_model": n}`. Dokunulan her iş için `derive_selection`.
2. **Model adımları.** Her parti için koşu 1 ve 2: `_model_step(…, "abstract_screening", candidate_rows=<partinin aday satırları>, …)`, anahtar `abstract_screening:{parti}:{koşu}`. İki koşunun girdisi `screening_target.run` dışında aynıdır. Geçersiz çıktı (`{"invalid": True}`) koşuyu **durdurmaz**; sürdürülen koşu `invalid_model_output` ile bitmiş adımı yeniden çağırmaz (`_extraction`'daki koruma kalıbı). Model bağlantısı yok / çağrı başarısız: bugünkü gibi koşu duraklar (`model_call_failed` vb.); kod kararları o ana kadar yazılmıştır.
3. **Partiyi kapat** (iki koşusu da bittiğinde, kodla): her kayıt ve koşu için `add_proposal(stage="abstract", run_no, label, quote, quote_verified)`; `combine`; `DecisionStore.record(kod, step_id=<2. koşunun adımı>)`; işin `derive_selection`'ı. Tekrarlanan çağrı satır eklemez (`add_proposal` ve `record` zaten öyle).
4. Bütçe biterse (`budget_exhausted`) kalan partilerin kayıtları `abstract_not_read` alır ve koşu **tamamlanır**; duraklamaz (okunmamış kayıt zaten beklenen bir durumdur).
5. `research_title` adımı `included_works` boş olduğu için koşmaz; buna dokunulmaz.

**Bütçe (`api/app.py`):** `sw` keşif koşusunda `max_model_calls = ön ayar + CRITERION_CALLS + ABSTRACT_RUNS × ceil(ABSTRACT_READ_LIMIT[effort] / ABSTRACT_BATCH)` (4 / 10 / 30 ek çağrı). Ön ayar tablosu (`TEST_EFFORT_BUDGETS`) **değişmez**: `legacy` ve yanıt koşuları ondan okuyor (dilim 06 incelemesinin bulgusu). `max_candidates` `sw` taramasını artık kesmez.

- [ ] **Tests first** (`tests/test_abstract_flow.py`): `sw` koşusu sonunda hiçbir seçim `included` değil, hiçbir `model:screening` adımı yok; başlıkta iki blok → `blocks_in_title`, model girdisinde yok; iki blok da yok → `excluded` + `code_rule`, kayıt listede duruyor; `limit`'in dışındaki iş `abstract_not_read` ve `pending`; aynı kapsamda ikinci keşif koşusu ilk koşunun okuduklarını **sormaz**, sıradaki işleri okur; iki parti arasında duraklatılıp sürdürülen koşu aynı planı okur ve hiçbir işi atlamaz; bir partinin bir koşusu geçersiz çıktı verince koşu sürer, o partinin kayıtları `abstract_not_proposed` alır, öbür partiler kararlanır, sürdürme o adımı yeniden çağırmaz; uydurma alıntı → `quote_not_found_kept_as_candidate`; iki koşu ayrışınca aday; kullanıcının dışladığı kayıt `excluded` + `user` kalır; soru revize edilince eski karar eskir ve kayıt yeniden okunur; ölü modelle koşu `model_call_failed` ile durur ve kod kararları yazılmıştır; `legacy` koşusu bu dilimden önceki adımları, seçimleri ve protokol özetini verir.

## Task 5: eşzamanlı gönderim

Task 4'ün 2. adımı `_table_fill`'in gönderim döngüsüyle (`deps.limiter`, gönderimden önce `_checkpoint`, durdurulunca uçuştaki çağrılar biter ve adımlarını yazar) aynı kalıba çevrilir; iş birimi (parti, koşu) çiftidir. İkinci bir eşzamanlılık düzeneği yazılmaz; döngüyü ortak bir yardımcıya çıkarmak serbesttir, `_table_fill`'in davranışı ve testleri değişmez. Parti kapatma (Task 4.3) yine olay döngüsünde, kısa işlemlerle, o partinin iki koşusu bittiğinde yapılır. Hız sınırı yanıtı `limiter.reduce()` yolundan geçer.

**Bölünme noktası:** Task 1–4 kendi başına doğru ve tam bir dilimdir (yalnızca yavaş). Sohbet Task 5'e yetmiyorsa Task 6–8 yapılır, commit'lenir ve Task 5 satır 09'a "açık kalan" diye yazılır.

- [ ] **Tests first:** aynı anda uçuşta en çok `limiter.limit` çağrı; sonuç sıralı yürütmeyle aynı kararları verir (aynı sahte çıktılar, karar tablosu eşit); duraklatma yeni gönderimi keser, uçuştakiler adımını yazar, sürdürme yalnızca eksikleri çağırır.

## Task 6: protokol ve tekrar aşaması

`protocol.py`: `sw` gövdesinde `thresholds.abstract_screening = {"read_limit": N, "batch", "runs", "quote_min_chars"}` (N kapsamın eforundan). `legacy` gövdesi aynı. `tests/determinism_stages.py`'ye `abstract_stage` aşaması: sabit havuz + bloklar + sabit iki koşuluk öneri kümesi → kod sonuçları, plan ve birleşik kodların tek özeti; iki hash tohumu.

## Task 7: zaman çizelgesi (tek arayüz değişikliği)

`Transcript.tsx::phaseOf`: `code:abstract_stage` ve `model:abstract_screening` → `'screen'`. `labels.ts` + `i18n.ts`: iki adım adı (EN + TR): "Abstract screening (code)" / "Özet taraması (kod)", "Abstract screening proposal (model)" / "Özet taraması önerisi (model)". Başka arayüz işi yok: sayılar, gerekçe kodları ve "okunmadı" dilim 20'de. `fixture_server.py`'nin betikli modeli yeni görevi yanıtlar (yoksa senaryo H'nin koşusu onaydan sonra taramada durur).

## Task 8: dilimi kapat

- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı (bilinen tek başarısızlık aynı). `cd apps/web && npm run build && npm run lint`, sonra Playwright A–H. `git diff --check`. Canlı istek, model çağrısı, kuru çalıştırma **yok**.
- [ ] `docs/decisions.md` en üste `## D81 — Screen abstracts in an sw run with a code stage, two batched model runs whose quotes code verifies, and a read limit that leaves the rest unread rather than dropped`. Limits adıyla söylemeli: yalnızca `sw`; N, parti boyu ve alıntı alt sınırı elle seçildi; parti boyu iki konuda ve tek modelde (`deepseek-flash`) ölçüldü, etiket doğruluğu ölçülmedi; **konudan bağımsız istem elle yazılmış isteme göre daha dar ve kararsız okuyor** (ölçüm klasörü, 77 / 100) ve üzerinde anlaşılmış bir `out_of_scope` seçimi `excluded` yapar — kullanıcı geri alabilir, ama bunu gösteren ekran yok; okunmayan kayıt sayısı hiçbir ekranda yok (dilim 20); bağlantısız ek ürün normal kayıt gibi taranır (SW6.2'den dar); bu dilimden dilim 12'ye kadar bir `sw` araştırması kendiliğinden hiçbir işi dahil etmez, yanıt için kullanıcının elle dahil etmesi gerekir; SW10'un "açık erişimlide özeti atla" fikri dilim 24'te.
- [ ] SW belgesinde SW9 ve SW11 **Status** satırlarına birer cümle. `sw-implementation-plan.md` §5 K3 satırına karar. `sw-status.md` satır 09: `uygulandı, inceleme bekliyor` + açık kalanlar. Tek commit, `git push origin main`.

## Güncellenecek mevcut testler (adıyla izinli)

Bir `sw` koşusunun **`screening` adımını adıyla** okuyan mevcut testler yeni adıma çevrilir; beklentinin kendisi (hangi kayıt modele gider, hangi sırayla, koşu nerede durur) aynı kalır ve her biri son iletide adlandırılır. Bilinenler: `tests/test_ranking_flow.py` (taramanın okuduğu sıra, iki parti arasında sürdürme, `source_similarity` < `ranking` < tarama), `tests/test_lookup_flow.py` (modele ulaşan kayıtlar, özetsiz kayıt, başlık sözcüğü derlemesi), `tests/test_vocabulary_flow.py::test_an_sw_discovery_searches_while_every_model_call_fails`. Aynı dosyalardaki `legacy` testlerine dokunulmaz. Bunların dışında bir mevcut test kırılırsa dur ve bildir.

## Son ileti

Eklenen ve değişen dosyalar; temel ve son test sayıları, komut, Playwright sonucu; `skill_package_hash` önce / sonra; "özetten `included` çıkmaz", "ikinci koşu kaldığı yerden okur", "sürdürülen koşu aynı planı okur" ve "`legacy` aynı" testlerinin adları; yeni adıma çevrilen her mevcut test; Task 5 yapıldı mı; yazıldığı gibi yapılamayan her şey ve her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: `sw` koşusunda model artık seçim yazmaz, kod yazar; `out_of_scope` kararı seçimi `excluded` + `code_rule` yapar; hiçbir iş özetle dahil edilmez); canlı servise ve ürün veritabanına dokunulmadığı; commit özeti.

## Açık noktalar

- **Sahip görmeli:** bu dilimle dilim 12 arasında `sw` araştırması kendiliğinden kaynak dahil etmez; yanıt koşusu için kullanıcı elle dahil eder (K2'nin bilinen sonucu).
- **İstem kalitesi:** konudan bağımsız istemin dar okuması biliniyor ve düzeltilmedi; ölçüt cümlesini göstermek daha da daraltıyor. Dilim 24, istemlerin ayrıştığı kayıtlarda insan etiketiyle bakmalı. Anlaşmazlık kaydı tuttuğu için kararsızlık "daha çok oku" yönüne düşer.
- **N'nin bedeli (tek konu):** modele bağlı 13 bilinen pozitifin 4'ü ilk 40'ta, 6'sı ilk 100'de, 11'i ilk 300'de okunuyor; 29 pozitif işin 16'sını kod başlıktan zaten aday yapıyor.
- **Genişleme terimleri görev bloğunda** (dilim 04b'nin zayıflığı): komşu konu terimi başlıkta geçen kayıt kodla aday olur. Aday ucuzdur (bir tam metin okuması), ama aday sayısını şişirebilir; ölçülmedi.
- **Sürümler:** okunan tek sürümdür; aynı işin iki sürümü ayrı özet taşıyorsa ikincisi okunmaz.
