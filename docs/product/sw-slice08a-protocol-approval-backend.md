# SW dilim 08a — Protokol onayı, arka uç: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): **SW2** madde 6, **SW15** madde 3, **SW14** madde 1–2, SW17 madde 2 (kullanıcının düzeltmesi modelin üstündedir), SW11 madde 10. **Önkoşul:** 04a, 04b, 04d, 06, 07 (hepsi kapandı). **Tür:** Kur. **İnceleme:** toplu (08b ile birlikte, 08b başlamadan önce).

Plandaki dilim 08 üçe bölündü (21 Eylül 2026): **08a** bu dosya, arayüzsüz; **08b** ekran ve Playwright ([sw-slice08b-protocol-approval-ui.md](sw-slice08b-protocol-approval-ui.md)); **08c** koşullu model terim önerisi (SW2.5), yeni sözleşme ve yöntem dosyası ister, ayrı yazılacak. Gerekçe: onay adımı kanıtın hangi protokol altında toplandığını belirler ve akış, depo, görünüm ve API'yi birlikte değiştirir; ekranla aynı sohbete sığmaz.

**Goal:** Bugün bir `sw` keşif koşusu sözcük dağarcığını ve ölçütü üretir, kimseye göstermeden dondurur ve arar. Bu dilimden sonra koşu, ölçüt adımı bittikten sonra ve protokol dondurulmadan **önce** `protocol_approval_needed` nedeniyle durur; görünüm öneriyi (terimler, blokları, kökenleri, sayıları, ölçüt, parçalar, ifadeler, dışlama sözcükleri) taşır; kullanıcı olduğu gibi onaylar ya da düzeltir; düzeltilmiş hâl protokole girer ve koşu sürer. Onaysız hiçbir sağlayıcı **arama** isteği çıkmaz.

**Kabul koşulunun daraltılması (adıyla):** ana plan "onaysız hiçbir sağlayıcı isteği çıkmaz" diyor. Sayım sınamaları (`_count_probe`, kayıt okumayan `per_page=1` istekleri) onaydan **önce** koşmaya devam eder, çünkü ekranın göstereceği sayılar onlardır ve terimin kök mü öbek mi gireceğine onlar karar verir. Onaydan önce hiçbir `provider_search` adımı açılmaz ve hiçbir aday yazılmaz.

**Architecture:** `flow._discovery`'nin `sw` dalında `_criterion`'dan sonra, `protocol` adımından önce yeni `_approval` çalışır. Durumu `code:protocol_approval` adımı (`operation_key = "protocol_approval"`) taşır; migration yoktur. Yeni rota `POST /api/runs/{run_id}/protocol-approval` kullanıcının düzeltmelerini adımın çıktısına yazar ve koşuyu kuyruğa alır; **ağ işi rotada değil işçide yapılır**: sürdürülen koşu düzeltmeleri okur, eklenen terimleri sayım sınamasından geçirir, sorguları yeniden derler, adımı `succeeded` yapar ve protokolü dondurur. `views.research_view` koşu satırına `approval` alanını ekler.

**Tech stack:** Python 3.12. Migration, sözleşme ve yöntem paketi değişikliği **yok**; `skill_package_hash` aynı kalır. `apps/web/`'e dokunulmaz.

## Global constraints

- `legacy` araştırmada adım açılmaz, koşu durmaz, protokol gövdesi ve özeti aynı kalır.
- **Yeni model çağrısı yok.** Aynı araştırmada model yeniden sorulmaz (SW2.6): onay, ölçüt adımını yeniden koşturmaz.
- **Kullanıcının düzeltmesi modelin ve kuralın üstündedir** (SW17.2, AGENTS.md "User Authority"): kullanıcının taşıdığı terimin blok kökeni `user` olur ve hiçbir sonraki adım onu geri almaz.
- **Hiçbir şey yerinde düzenlenmez** (SW14.2): öneri adım çıktısında olduğu gibi kalır, onaylanan hâl yanına yazılır; dondurulmuş protokol kaydı değişmez.
- Kullanıcının eklediği her terim, soru terimleriyle **aynı** sayım sınamasından geçer (SW2.1, SW2.5'in kuralı); sıfır sonuçlu terim `zero_results` ile düşer ve kayıtta kalır.
- Katılımsız koşu mümkün kalmalıdır (mevcut testler, dilim 13 ve 24): `Settings.protocol_approval` (`ask` | `as_proposed`, ortam değişkeni `DEIXIS_PROTOCOL_APPROVAL`, varsayılan `ask`). `as_proposed` durmadan öneriyi onaylar ve bunu protokole **adıyla** yazar; kullanıcı onayı gibi görünmez.
- Mevcut hiçbir testin **beklentisi** değişmez. `sw` koşusunu sonuna kadar süren mevcut test dosyaları kurulumlarında `Settings(..., protocol_approval="as_proposed")` alır; bu bir kurulum değişikliğidir ve dokunulan her dosya son iletide adlandırılır. Adım sırasını sayan testler yeni adımı görür; her biri adlandırılır.
- Testlerde ağ yok. Fikstürler SYNTHETIC ve en az iki alandan. Ürün koduna konuya özgü sözcük girmez.
- Başlamadan kontrol et: son karar `D79`, son migration `0044`. Bu dilim `D80` alır, migration almaz.

## Dosya yapısı

Yeni: `backend/deixis/workflow/approval.py`, `tests/test_protocol_approval.py` (saf), `tests/test_approval_flow.py` (`create_app` ile).

Değişecek: `backend/deixis/config.py`, `backend/deixis/domain/vocabulary.py` (`Extraction.origins`), `backend/deixis/workflow/vocabulary.py`, `workflow/flow.py`, `workflow/protocol.py`, `workflow/store.py`, `workflow/views.py`, `api/app.py`, `tests/acceptance/fixture_server.py` (yalnızca `search_workflow` ve `protocol_approval`'ı ortamdan okuması; 08b kullanır), `tests/determinism_stages.py`, `sw` koşusu süren mevcut test dosyalarının kurulumu, `docs/decisions.md`, SW belgesi (SW2 ve SW15 durum satırları), `docs/product/sw-status.md`.

## Task 1: düzeltmelerin biçimi ve denetimi (`workflow/approval.py`)

Bir düzeltme paketi:

```json
{"terms": [{"op": "remove", "phrase": "…"},
           {"op": "move", "phrase": "…", "block": "task"},
           {"op": "add", "phrase": "…", "block": "setting"}],
 "criterion": null,
 "note": "…"}
```

- `block` ∈ `setting`, `task`, `outcome`, `claim`, `exclusion` (`vocabulary.LABELS` eksi `not_a_term`; "terim değil" demek `remove`'dur). `phrase` `norm` edilmiş hâliyle karşılaştırılır; 1–80 karakter, en çok 6 sözcük. En çok `MAX_TERM_EDITS = 40` işlem (adlı sabit). Aynı ifadeye iki işlem, var olmayan ifadeye `remove` / `move`, var olan ifadeye `add` **hatadır** (422), sessizce atlanmaz.
- `criterion` ya `null` (öneri olduğu gibi kalır) ya da **tam** yerine geçen nesnedir, `criterion.consensus`'un çıktı biçiminde: `{"criterion", "parts": [{"name", "definition"}], "cue_phrases": [{"phrase", "part"}], "exclusion_title_words"}`. Sınırlar `criterion-proposal` sözleşmesinin sınırlarıdır (ölçüt 1–600 karakter; 2–5 parça, adları `norm` sonrası tekil; ifade 1–80 karakter ve en çok 4 sözcük; `part` bir parça adı ya da `null`; dışlama sözcüğü 0–30). Parça başına 6–15 ifade sınırı **uygulanmaz**: uzlaşı zaten bunu tutmuyor ve kullanıcı ifade silebilmelidir. Model kapalıyken (öneri `null`) kullanıcı ölçütü sıfırdan yazabilir.
- `note` isteğe bağlı, en çok 1.000 karakter; protokol revizyonunun gerekçesine girer.

Saf işlevler: `check_edits(proposal, edits) -> list[str]` (hata listesi; boşsa geçerli), `apply_criterion(proposed, edited) -> dict | None`, `edited_extraction(vocabulary, term_edits) -> Extraction`.

`apply_criterion`: `edited` `None` ise `proposed` döner. Değilse düzeltilmiş nesne döner; öneride de geçen ifade kendi `runs` listesini korur, kullanıcının eklediği ifade `runs: []` alır; `base_run`, `runs_ok`, `dropped_exclusion_title_words`, `sought_term_in_criterion` öneriden taşınır (öneri yoksa `None`). Soruda geçen dışlama sözcüğünü düşürme kuralı (SW5.1, `consensus`'taki) kullanıcının listesine **uygulanmaz**: kullanıcı yazdıysa bilerek yazmıştır; yalnızca `approval` kaydında `exclusion_word_in_question` olarak işaretlenir (08b uyarı gösterir).

- [ ] **Tests first:** her hata türü ayrı ayrı 422 metni üretir; işlem sırası sonucu değiştirmez (kanonik sıra); `apply_criterion` `runs`'ı korur ve yeni ifadeye boş liste verir; `null` ölçüt öneriyi bayt bayt geri verir.

## Task 2: düzeltilmiş dağarcık tek yoldan kurulur

Düzeltme, terim sözlüklerini elle yamamaz. `edited_extraction` önerinin terimlerinden ve yan listelerinden (`claim_words`, `exclusion_words`, `outcome_terms`) yeni bir `Extraction` kurar, işlemleri uygular ve **aynı** `vocabulary.build_vocabulary`'yi çağırır; kök / öbek kararı, `and_only`, geçit daraltması ve `too_broad` böylece tek kod yolundan gelir.

- **Sayımlar yeniden sorulmaz:** `build_vocabulary`'ye verilen `count`, önce önerinin `probes` listesine (`query → count`) bakan, yalnızca orada olmayan sorgu için ağa giden bir sarmalayıcıdır (`approval.cached_count(probes, count)`). Hiç terim eklenmediyse ve hiçbir terim geçit bloğuna taşınmadıysa ağ isteği **sıfırdır** (testi zorunlu). `MAX_PROBES` yeni sorgular için de geçerlidir; önbellekten yanıtlanan sorgu bütçe harcamaz (sarmalayıcı `build_vocabulary`'nin sayacını şişirmemeli; gerekiyorsa `build_vocabulary` `known: dict[str, int | None]` alır ve bilinen sorguyu `probes`'a yazıp sayaca katmaz — ikisinden hangisi seçildiyse son iletide yazılır).
- **Terim başına köken:** `Extraction` isteğe bağlı `origins: dict[str, str]` alanı kazanır (varsayılan boş; boşken `build_vocabulary` bugünkü tek kökeni yazar, yani mevcut çıktı bayt bayt aynıdır). Önerideki terim kökenini korur (`question` | `key_terms`), kullanıcının eklediği terim `user` alır. `TERM_FIELDS` değişmez.
- **Blok kökeni:** kullanıcının eklediği ya da taşıdığı ifadenin `block_origin`'i `user`'dır; dokunmadığı ifade önerideki kökenini (`rule` | `model`) korur. `vocabulary["labelling"]` kaydı silinmez; düzeltilmiş dağarcığa `user_edits` (kanonik sıralı işlem listesi) eklenir ve `protocol.build_protocol`'ün `block_origin` hesabı bunu okur.
- Sorgular `_vocabulary`'nin kullandığı derleyiciyle yeniden derlenir; düzeltme yoksa öneri sorguları **aynı nesne** olarak kullanılır (yeniden derlenmez).
- Düzeltilmiş dağarcık boş ya da fazla geniş çıkarsa mevcut `_searchable` yolu koşuyu `vocabulary_empty` / `vocabulary_too_broad` ile durdurur. Bu durumda onay adımı `succeeded` **olmaz**: kullanıcı yeni bir düzeltme gönderebilir (aşağıda "yeniden gönderme").

- [ ] **Tests first:** terim silmek o terimi hiçbir sorguda bırakmaz; `claim`'e taşınan terim sorgudan çıkar ve `claim_words`'e girer; `claim`'den `task`'e taşınan ifade sınanır ve sorguya girer; eklenen sıfır sonuçlu terim `zero_results` ile düşer ve kayıtta kalır; düzeltmesiz onayda sayım isteği sıfır ve sorgular önerininkiyle bayt bayt aynı; yalnızca ölçüt düzeltilince dağarcık yeniden kurulmaz; kökenler (`question` / `user`, `rule` / `model` / `user`) protokol gövdesinde doğru görünür.

## Task 3: akış

`flow._approval(run, scope, vocabulary, queries, criterion) -> tuple[vocabulary, queries, criterion]`:

1. Adım `succeeded` ise saklı `approved` döner (sürdürülen koşu hiçbir şeyi yeniden sormaz, yeniden sınamaz).
2. Adımın çıktısı yoksa öneri yazılır (`store.set_step_output`): `{"proposal": {"vocabulary", "queries", "criterion", "criterion_failures"}, "proposal_hash", "asked_for": {"question", "steering", "key_terms"}, "submitted": null}`. `proposal_hash`, ifadeler + bloklar + ölçüt alanlarının kanonik özetidir; **sayımlar girmez** (sayımlar zamanla değişir).
3. **Önceki onay:** araştırmada, `asked_for`'u bu kapsamınkine eşit olan `succeeded` bir `protocol_approval` adımı varsa (en yenisi) koşu **durmaz**: o adımın `edits.terms` işlemleri bu koşunun taze dağarcığına yeniden uygulanır (artık var olmayan ifadeye dokunan işlem atlanır ve `skipped_edits`'e yazılır; burada hata değildir), ölçüt `frozen_criterion`'dan zaten onaylanmış hâliyle gelmiştir ve yeniden düzeltilmez. Adım `approved_by = "earlier_approval"` ve o adımın kimliğiyle kapanır. Aynı kapsamda ikinci keşif koşusu ve sorusu aynı kalan yeni kapsam revizyonu böylece yeniden sormaz; sorusu, yönlendirmesi ya da `key_terms`'i değişen revizyon sorar.
4. `settings.protocol_approval == "as_proposed"` ise düzeltmesiz onaylanır, `approved_by = "setting"`.
5. `submitted` doluysa: Task 1–2 uygulanır (sayım istekleri burada, işçide, `_checkpoint`'ten sonra), adım `succeeded` olur: `{"…öneri alanları…", "edits", "approved": {"vocabulary", "queries", "criterion"}, "approved_by": "user", "edited": bool, "skipped_edits": []}`.
6. Hiçbiri değilse `_pause(run_id, "protocol_approval_needed")`. Adım `pending` kalır (başlatılmaz), böylece `worker.recover` onu `outcome_unknown` saymaz.

**Yeniden gönderme:** adım `succeeded` olana kadar rota yeni bir `submitted` kabul eder ve öncekinin üstüne yazar (öneri değişmez). `succeeded` olduktan sonra 409 döner: o koşunun protokolü dondurulmuştur; değişiklik yeni bir kapsam revizyonu ister.

`protocol` adımı ve `_freeze_expansion` **onaylanmış** dağarcığı, sorguları ve ölçütü alır (dilim 06 ve 07'nin tuzağının üçüncü kez aynısı: `_freeze_expansion` öneriyi alırsa genişleme revizyonu kullanıcının düzeltmesini geri alır ve her kararı eskitir; testi zorunlu). `_expansion`, `_second_sources` ve `_ranking` de onaylanmış dağarcığı okur.

Protokol gövdesi (`sw`'de) yeni alan: `"approval": {"mode": "ask" | "as_proposed", "approved_by": "user" | "setting" | "earlier_approval", "edited": bool, "proposal_hash", "term_edits": n, "criterion_edited": bool, "exclusion_word_in_question": [...]}`. `criterion_origin.origin`, ölçüt düzeltildiyse `"user"` olur. İlk dondurma hâlâ gerekçesizdir (öneri hiç dondurulmadı, düzeltilmiş hâl ilk kayıttır); `note` varsa `approval.note` olarak gövdeye girer. `CRITERION_FIELDS` değişmez.

- [ ] **Tests first** (`tests/test_approval_flow.py`): `ask` modunda koşu `protocol_approval_needed` ile durur, o anda **hiçbir** `provider_search` adımı, hiçbir aday ve hiçbir protokol kaydı yoktur, sahte sağlayıcı yalnızca sayım isteği görmüştür; düzeltmesiz onaydan sonra koşu önerinin sorgularıyla arar; terim ve ölçüt düzeltmesi protokole ve gerçekten gönderilen sorgu metnine yansır; onaydan sonra duraklatılıp sürdürülen koşu yeniden durmaz ve sayım istemez; aynı kapsamda ikinci keşif koşusu durmaz ve aynı düzeltmeleri taşır; sorusu aynı kalan kapsam revizyonu durmaz, sorusu değişen durur; genişleme revizyonu düzeltilmiş dağarcığı ve ölçütü taşır, ölçüt alanlarının özeti iki revizyonda aynıdır; model her çağrıda hata verirken koşu yine onay için durur (ölçüt `null`) ve onaydan sonra arar; `as_proposed` hiç durmaz ve gövde `approved_by = "setting"` der; `legacy` hiç durmaz, adım açmaz, protokol özeti bu dilimden önceki değerle aynıdır; onay beklerken gelen yeni kapsam revizyonu koşuyu `scope_revised` ile iptal eder (mevcut `_checkpoint` davranışı) ve yeni koşu yeniden sorar; `vocabulary_empty` ile duran düzeltme yeniden gönderilebilir.

## Task 4: rota ve görünüm

`POST /api/runs/{run_id}/protocol-approval`, gövde Task 1'in paketi (boş paket = olduğu gibi onay). Koşu `paused` ve nedeni `protocol_approval_needed`, `vocabulary_empty` ya da `vocabulary_too_broad` değilse 409; `check_edits` hata verirse 422 ve hata listesi; geçerliyse **tek işlemde** `submitted` yazılır ve koşu `queued` olur (`control_run`'ın `resume` dalındaki güncellemenin aynısı, olay `run_resumed`), sonra `worker.wake()`. Düz `POST /api/runs/{id}/resume` onay bekleyen koşuda 409 döner ve nedenini söyler: onaysız sürdürme yoktur. CSRF ve Host / Origin denetimi mevcut ara katmandan gelir.

`views.research_view`: koşu satırına `approval` alanı — adım yoksa `None`; varsa `{"status": "waiting" | "submitted" | "approved", "approved_by", "edited", "proposal": {"terms": [TERM_FIELDS + "block_origin"], "claim_words", "exclusion_words", "outcome_terms", "gate_count", "too_broad", "criterion": <consensus biçimi ya da null>, "criterion_available": bool, "sought_term_in_criterion"}, "approved": <aynı biçim ya da null>, "skipped_edits"}`. `probes` ve `queries` görünüme **girmez** (büyük ve ekranın işi değil); derlenmiş sorgu metinleri `approved.queries` olarak yalnızca sağlayıcı ve metinle girer. Bu, 04a'nın "`sw` koşusunda `plan` `None`" açığını kapatır; `plan` alanına dokunulmaz.

- [ ] **Tests first:** rota üç 409 durumunu ve 422'yi ayrı ayrı verir; CSRF'siz istek reddedilir; görünüm `waiting` → `submitted` → `approved` geçişini taşır; onaylanmış koşuda `proposal` ve `approved` ikisi de durur (kullanıcı neyi değiştirdiğini görebilir); `legacy` koşusunda alan `None`.

## Task 5: tekrar aşaması ve fikstür sunucusu

- `tests/determinism_stages.py`'ye `protocol_approval` aşaması: sabit öneri + karışık sırayla verilmiş işlem listesi, sabit sayım tablosu, iki hash tohumu; onaylanmış dağarcığın, sorguların ve ölçütün tek özeti.
- `tests/acceptance/fixture_server.py`: `Settings(...)` kurulurken `search_workflow` ve `protocol_approval` ortamdan okunur (`DEIXIS_SEARCH_WORKFLOW`, `DEIXIS_PROTOCOL_APPROVAL`); verilmezse bugünkü değerler, yani mevcut Playwright koşusu aynıdır. Sahte OpenAlex'in sayım isteğini (`per_page=1`, `select=id`) yanıtlayıp yanıtlamadığı denetlenir; yanıtlamıyorsa sabit bir sayı döndüren dal eklenir. 08b bunu kullanır; bu dilim Playwright koşmaz.

## Task 6: dilimi kapat

- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `git diff --check`. Canlı istek, model çağrısı ya da kuru çalıştırma **yok**.
- [ ] `docs/decisions.md` en üste `## D80 — Stop an sw discovery run before its first search until the user has approved or corrected the vocabulary and the criterion, and freeze what was approved`. Limits adıyla söylemeli: yalnızca `sw`; sayım sınamaları onaydan önce koşar; ekran yok (08b), yani `ask` modunda bir `sw` araştırması bugün yalnızca API ile sürdürülebilir; onay soru + yönlendirme + `key_terms` başına bir kez sorulur ve onayı yeniden açmanın yolu yoktur; yeniden uygulanan düzeltme artık var olmayan ifadeyi sessizce atlar (kayıtta durur); kullanıcının eklediği terimin doğruluğunu yalnızca sayım sınar; kullanıcının yazdığı ifadeler hiçbir koşuda oylanmadı; koşullu model terim önerisi (SW2.5) yok (08c); `as_proposed` modu ölçüm ve test içindir ve protokolde kullanıcı onayı olarak görünmez; düzeltmelerin kaliteye etkisi ölçülmedi.
- [ ] SW belgesinde SW2 ve SW15 **Status** satırlarına birer cümle. `sw-status.md` satır 08a: `uygulandı, inceleme bekliyor` + açık kalanlar. Tek commit, `git push origin main`.

## Son ileti

Eklenen ve değişen dosyalar; temel ve son test sayıları ve komut; `skill_package_hash`'in değişmediği; onaydan önce hiçbir arama isteği çıkmadığını, düzeltmesiz onayın sayım istemediğini ve genişleme revizyonunun düzeltmeyi taşıdığını gösteren testlerin adları; kurulumu `as_proposed`'a çevrilen her mevcut test dosyası ve adım sırası yüzünden güncellenen her test; sayım önbelleği için seçilen yol; yazıldığı gibi yapılamayan her şey ve seçilen her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: `sw` protokol gövdesi `approval` kazanır; bir `sw` koşusu artık kullanıcı onayı olmadan aramaz); canlı servise ve ürün veritabanına dokunulmadığı; commit özeti.

## Açık noktalar

- **Onayı yeniden açmak:** kullanıcı onayladıktan sonra fikrini değiştirirse tek yol soruyu ya da `key_terms`'i değiştiren bir kapsam revizyonudur. "Protokolü yeniden gözden geçir" eylemi (gerekçeli yeni protokol revizyonu, eskimiş kararlarla birlikte) dilim 16'nın insan döngüsüyle birlikte düşünülmeli.
- **Onay bekleyen koşu işçiyi tutmaz** (koşu `paused`'dır), ama araştırma başına tek etkin koşu kuralı sürdüğü için kullanıcı onay vermeden o araştırmada başka keşif başlatamaz; istenen davranış budur.
- **Süre:** ölçüt adımı aramadan önce 1–2 dakika sürüyor (dilim 06); kullanıcı artık bu sürenin sonunda bir ekranla karşılaşacak. Bekleme sırasında ne gösterileceği 08b'nin işidir.
- **`key_terms` ile ilişki:** `key_terms` veren kullanıcının blokları zaten `user` kökenlidir; onay ekranı onlara da aynı düzeltmeleri sunar. İngilizce olmayan soruda `key_terms_needed` duraklaması onaydan **önce** gelir ve ayrı kalır.
