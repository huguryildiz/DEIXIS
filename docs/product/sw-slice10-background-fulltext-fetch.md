# SW dilim 10 — Arka planda tam metin getirme: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): **SW10** madde 1–3 (madde 2'nin yalnızca "metin gelir gelmez kod çıkarır ve kimliği denetler" yarısı; kod kapısı ve model okuması dilim 12 / 23). **Önkoşul:** 03, 07, 09 (kapandı). **Tür:** Kur. **İnceleme:** toplu, ama dilim 12 başlamadan önce (`gpt-5.6-sol` · high).

**Sahibin kararları (21 Eylül 2026, plan sohbeti):**

1. **"Arka plan" ayrı bir koşudur ve kendiliğinden başlar.** İşçi aynı anda tek koşu yürütür ve bir araştırmada iki etkin koşu açılamaz; ikinci bir işçi bu dilimde kurulmaz. `sw` keşif koşusu `completed` olunca `fulltext_fetch` türünde bir koşu kuyruğa girer. Kullanıcı bu sırada listeyle çalışır (dahil etme, dışlama, PDF açma bir koşu değildir); yanıt ya da yeni keşif başlatmak isterse getirmeyi duraklatır ya da iptal eder, getirilenler kalır. **SW10.1'den adıyla sapma:** getirme "kod aşamasından hemen sonra" değil, keşif koşusu (model taraması dâhil) bittikten sonra başlar.
2. **Koşu başına iş sınırı 40 / 100 / 300** (quick / standard / detailed; K3 ile aynı sayılar). Elle seçildi, **ölçülmedi**. SW10'un tek konudaki ölçümü iş başına yaklaşık 5 sn ve 5 istek veriyor (tek makine, tek ağ), yani kabaca 3 / 8 / 25 dakika. Sınırın dışındaki iş silinmez, "getirilmedi" diye sayılır ve sonraki getirme koşusu oradan sürer.
3. **Yalnızca başka sürümün kopyası açıksa kod o sürüm için satır açar.** DOI'si doğrulanmış ama sürümü kayıttan farklı bir kopya (çoğunlukla yayımlanmış kaydın `submittedVersion` kopyası) bugün kullanıcı onayı bekler. `fulltext_fetch` koşusunda kod aynı işin altında o sürüm etiketini taşıyan bir sürüm satırı açar ve PDF'i **ona** bağlar; pasajlar o etiketi taşır. D4 korunur: PDF ait olduğu sürüme bağlanır, yayımlanmış kayda değil (D48 kalıbı). Sürümü bilinmeyen (`uncertain`) kopya bugünkü gibi kullanıcıyı bekler.
4. **arXiv başlık araması ve Europe PMC kurulmaz.** İkisi de üründe yok, yalnızca `.local/quantum-fulltext-timing-2026-09-18/` betiklerinde. Ölçülen verim: onarılmış başlık araması 116 işte 2, Europe PMC 118 istekte 3 (tek konu). Europe PMC dilim 14'e (kaynak yönlendirme) not düşülür.

**Goal:** Bugün tam metin yalnızca kullanıcının dahil ettiği işler için, yanıt ya da `pdf_collection` koşusunda getirilir. `sw` araştırmasında özetten hiçbir iş dahil edilmediği için (D81) dilim 12'nin okuyacağı metin hiç gelmez. Bu dilimden sonra `sw` keşif koşusunu bir getirme koşusu izler: (1) kod, getirilecek işleri sıraya koyar ve planı dondurur; (2) iş başına **tek** getirme denemesi yapılır ve okunan sürüm saklanır; (3) metin gelir gelmez kod çıkarır (PyMuPDF, bugünkü yol) ve kimliğini denetler; (4) her iş tam metin aşamasında bir gerekçe kodu alır: metni var → `not_read_yet`, metin katmanı yok → `text_unreadable`, hiçbir yol vermedi → `no_fulltext`. **Hiçbir iş bu dilimde `included` ya da `excluded` olmaz**; metni olmayan iş `unresolved` kalır. `legacy` akış, `answer` ve `pdf_collection` koşuları olduğu gibi kalır.

**Architecture:** yeni saf modül `workflow/fulltext.py` (plan, sonuç kodu). `flow._fulltext_fetch` yeni koşu türünü yürütür ve mevcut `_acquire_pdf` / `_fetch_pdf` / `_find_other_copy` yolunu yeniden kullanır; ikinci bir indirme ya da arama yolu yazılmaz. Adımlar: `code:fulltext_plan` (anahtar `fulltext_plan`), iş başına `code:fulltext_work` (anahtar `fulltext_work:{baş kimliği}`), altında bugünkü `fetch_pdf` ve `pdf_other_copy` adımları, sonda `code:fulltext_summary`. Model çağrısı yok, sözleşme ve yöntem paketi değişmez. **Migration `0045`** (koşu türü `CHECK`'i).

**Tech stack:** Python 3.12. `skill_package_hash` **değişmez**. `apps/web`'de yalnızca Task 8.

## Global constraints

- `legacy` araştırmada koşu kuyruğa girmez; `answer` ve `pdf_collection` koşularının adımları, indirme sınırı (`MAX_DOWNLOADS_PER_RUN`) ve `acquire_for_source`'un varsayılan davranışı **bayt bayt** aynı kalır. Yeni davranış yalnızca `fulltext_fetch` koşusunun verdiği bir argümanla açılır.
- **D4, D22, D35 korunur:** PDF yalnızca ait olduğu sürüme bağlanır; her aday ve her deneme saklanır; reddeden bağlantı (`pdf_link_refusal`) yeniden istenmez, zaman aşımı ve kopan bağlantı istenir; iş başına en çok **bir** başka-kopya araması yapılır (tetiği Task 5'te, D35'ten geniş). Web araması (`web_search`) bu koşuda **kapalıdır** (SW10.4: son çare, kullanıcının eylemi).
- **Hiçbir seçim değişmez.** Bu dilimin yazdığı üç kod `unresolved`'dur ve `pending`'e türer; kullanıcının kararı (`decided_by = human`, `selections.origin = user`) üstündür, `HumanDecisionStands` yutulmaz, o iş atlanır. Kayıt silinmez, gizlenmez.
- **Ders 1 (dilim 09 incelemesi): sürdürülen koşuda depodan geri okunan iş bütçeye ve sayaca yazılmaz.** İş sınırı, `downloads` kullanımı ve özet sayıları yalnızca **bu çağrıda gerçekten yapılan** işi sayar. Saklı adımı `succeeded` ya da `failed` olan iş atlanır ve hiçbir canlı sayacı artırmaz; özet adımı sayılarını canlı sayaçtan değil **saklı adım çıktılarından** toplar. Sınaması zorunlu: plan boyu sınıra tam eşitken ortasında duraklatılıp sürdürülen koşu planın **tamamını** bitirir ve `completed` olur (09'daki hata tam bu durumda, bütçe "yetiyorken" ortaya çıkmıştı; bütçeyi geniş bırakan sürdürme testi onu görmedi).
- **Ders 2 (dilim 09, Task 5): eşzamanlı gönderim için ikinci düzenek yazılmaz.** Bu dilim işleri **sırayla** getirir: `deps.limiter` model çağrıları için ayarlanmıştır (`reduce()` model hız sınırına bağlı) ve tek bir yayıncıya ya da arXiv'e altı eşzamanlı indirme göndermek kabul edilebilir değildir. Uygulayan eşzamanlılık eklemek isterse tek yol `flow._send_through_limiter`'dır (iş birimi = iş, anahtar = adım anahtarı); `asyncio.gather`, kendi semaforu ya da yeni bir döngü **yazılmaz**. Sıralı getirmenin süresi **ölçülmedi** (dilim 24).
- **Plan dondurulur** (dilim 07 ve 09 incelemelerinin dersi): `fulltext_plan` adımı `succeeded` ise saklı çıktı okunur, plan yeniden hesaplanmaz; adım anahtarları baş kimliğine bağlıdır, sıradaki yere değil.
- Elle seçilen sayı adlı sabittir ve protokolün `thresholds.fulltext_fetch` alanına yazılır: `FULLTEXT_WORK_LIMIT = {"quick": 40, "standard": 100, "detailed": 300}` (`domain/rules.py`).
- Araştırma genelindeki okumalar birkaç sorguda yapılır, kayıt başına sorguyla değil (dilim 05 ve 07 incelemeleri: 2.000 kayıtta 1 sn, olay döngüsü iş parçacığında). PDF çıkarma bugünkü gibi `asyncio.to_thread`'de.
- Testlerde ağ yok: sahte `fetcher` ve sahte `httpx` taşıyıcısı `create_app` ile verilir. Fikstürler SYNTHETIC ve en az iki alandan. Ürün koduna konuya özgü sözcük girmez.
- Başlamadan kontrol et: son karar `D82`, son migration `0044`. Bu dilim `D83` ve `0045` alır.

## Dosya yapısı

Yeni: `backend/deixis/storage/migrations/0045_fulltext_fetch_run_kind.sql`, `backend/deixis/workflow/fulltext.py`, `backend/deixis/documents/identity.py`, `tests/test_fulltext_plan.py` (saf), `tests/test_fulltext_flow.py` (`create_app` ile).

Değişecek: `domain/rules.py`, `backend/deixis/config.py` (`Settings.fulltext_fetch`), `workflow/flow.py`, `workflow/store.py` (koşu aşaması eşlemesi, sürüm satırı), `documents/acquisition.py` (tek yeni argüman), `workflow/protocol.py`, `api/app.py` (`StartRun.kind`, bütçe, `match_pdf_to_source` taşınır ve oradan içe aktarılır), `tests/determinism_stages.py`, `tests/acceptance/fixture_server.py`, `apps/web/src/api.ts`, `labels.ts`, `i18n.ts`, `Transcript.tsx`, `BackgroundJobs.tsx`, `ResearchView.tsx` (yalnızca koşu türü süzgeci), `docs/decisions.md`, SW belgesi (SW10 durum satırı), `sw-status.md`.

## Task 1: koşu türü, ayar, bütçe

- Migration `0045`: `runs.kind` `CHECK`'ine `fulltext_fetch` eklenir; tablo `0035`'teki kalıpla yeniden kurulur (`-- deixis:foreign-keys-off`, satırlar korunur, dizin yeniden açılır). Başka şema değişikliği yok.
- `store.create_run`'ın aşama eşlemesi: `fulltext_fetch` → `inspection`.
- `Settings.fulltext_fetch`: `auto` | `off`, ortam değişkeni `DEIXIS_FULLTEXT_FETCH`, varsayılan `auto` (yalnızca `sw` araştırmalarını etkiler; `sw` bayrak arkasında). **Mevcut bütün `sw` test kurulumları ve Playwright H'nin fikstür sunucusu `off`'a çevrilir** (dilim 08a'nın `as_proposed` kalıbı): o testler keşif koşusu bitince ikinci bir koşunun açılmamasına dayanıyor. Beklentileri değişmez.
- `api/app.py`: `StartRun.kind`'a `fulltext_fetch`; yalnızca `sw` araştırmasında kabul edilir (`legacy`'de 422). Bütçe: `{"max_model_calls": 0, "max_provider_requests": 0, "max_fulltext_works": FULLTEXT_WORK_LIMIT[effort]}`. `TEST_EFFORT_BUDGETS`'a dokunulmaz (dilim 06 incelemesinin bulgusu).

- [ ] **Tests first:** migration eski satırları korur ve yeni türü kabul eder; `legacy` araştırmada tür 422 alır; bütçe efora göre 40 / 100 / 300; ön ayar tablosu aynı.

## Task 2: plan ve sonuç kodu (saf)

`fulltext.fetch_plan(works, order, limit) -> {"works": [baş, …], "not_reached": [baş, …], "already_text": [baş, …]}`. Birim **iş**tir. `works` satırı: baş kimliği, sürümleri, her sürümün PDF metni var mı, işin güncel özet sonucu ve kodu, güncel tam metin kararı (varsa, eskimiş mi), seçimin durumu ve kökeni, insan kararı var mı.

Bir iş **uygun**dur, eğer üç gruptan birindeyse; sıra da budur:

1. **Kullanıcının adlandırdığı:** seçimi `included` ve kökeni `user` (kullanıcının yüklediği PDF zaten metindir, `already_text`'e düşer).
2. **Kod adayları:** iş düzeyindeki özet sonucu `candidate` (`DecisionStore.work_outcome` kuralıyla: bir sürümü aday olan iş adaydır).
3. **`unresolved`:** iş düzeyindeki özet sonucu `unresolved` **ve** kodunun `next_step`'i `fulltext_fetch` (`runs_agree_unresolved`, `abstract_not_found`). Gerekçe tablosu bunu zaten söylüyor; ikinci bir liste tutulmaz.

Grup içi sıra `order`'daki (dilim 07'nin birleşik sırası, `latest_ranking`) baş kimliğinin yeridir; `order`'da olmayan iş grubunun sonunda, kimlik sırasıyla. **Uygun olmayanlar:** `out_of_scope` işler; kullanıcının dışladığı işler; tam metin aşamasında insan kararı taşıyan işler; `next_step`'i `abstract_model` / `abstract_lookup` / `seed_pool` olan işler (`abstract_not_read`, `abstract_not_proposed`, `no_abstract`, `survey_title_word`). **SW10.1'den adıyla sapma:** "sonra `unresolved` kayıtlar" özeti henüz okunmamış işi kapsamaz — okunmamış işe bugün tam metin kararı yazmak, özeti sonradan okunup kapsam dışı çıktığında işi `pending`'de tutardı (`work_outcome` tam metin aşamasına öncelik verir). SW10'un "açık erişimlide özeti atla" fikri dilim 24'te.

Uygun işlerden: herhangi bir sürümünün PDF metni olan → `already_text` (getirilmez, kodu yazılır). Bu dilimin sahip olduğu **eskimemiş** bir tam metin kodu (`no_fulltext`, `text_unreadable`, `not_read_yet`) taşıyan iş plana girmez: "sonraki koşu kaldığı yerden sürer" budur ve aynı bağlantılar ikinci kez istenmez. Kalanların ilk `limit`'i `works`, gerisi `not_reached`.

`fulltext.settled_code(attempt) -> str | None`:

| durum | kod |
|---|---|
| bir sürümün PDF metni var (pasaj sayısı > 0) | `not_read_yet` |
| PDF bağlandı, hiçbir sürümde pasaj yok (metin katmanı yok / çıkarma başarısız) | `text_unreadable` |
| denenecek her yol yanıt verdi (ret, 404, sonuçsuz arama, bağlantı yok) ve metin yok | `no_fulltext` |
| yollardan en az biri yanıt **vermedi** (zaman aşımı, kopan bağlantı, 429, 5xx) ve metin yok | `None` — karar yazılmaz, iş sonraki koşuda yeniden denenir (D35 ile aynı ayrım) |

Yeni gerekçe kodu **yok**; üçü de dilim 02'den beri tabloda.

- [ ] **Tests first:** üç grubun sırası; grup içinde birleşik sıra; `abstract_not_read` iş plana girmez; kullanıcının dışladığı ve insan kararlı iş girmez; metni olan iş `already_text`; taze `no_fulltext` girmez, eskimiş girer; `limit`'te keser ve hiçbir işi düşürmez (`works` ∪ `not_reached` ∪ `already_text` = uygun işler); plan iki hash tohumunda aynı; `settled_code` tablosunun her satırı.

## Task 3: kimlik denetimi

`api/app.py::match_pdf_to_source` ve sabitleri (`DOI_IN_TEXT`, `ARXIV_IN_TEXT`, `MATCH_TEXT_CHARS`) `documents/identity.py`'ye **taşınır** (akış `api`'den içe aktaramaz); `app.py` oradan alır, davranışı ve testleri değişmez. İkinci bir eşleyici yazılmaz.

Yeni `identity.check(text, versions) -> "doi" | "title" | "unconfirmed"`: `versions` işin bütün sürümleridir; metnin başı onlardan birinin DOI'sini / arXiv kimliğini ya da (en az dört sözcüklü) başlığını taşıyorsa doğrulanır. `unconfirmed` metni **ayırmaz ve silmez**: ilk sayfada DOI taşımayan çok PDF var ve aday zaten DOI ile doğrulanmış bir kaynaktan geldi. Sonuç iş adımının çıktısına yazılır ve özet adımında sayılır; onunla ne yapılacağı dilim 12'nin kararıdır. Yanlış PDF'i yakalama gücü **ölçülmedi**.

- [ ] **Tests first:** DOI, arXiv kimliği, başlık, hiçbiri; kardeş sürümün DOI'si de doğrular; taşıma sonrası `uploads/match` testleri dokunulmadan geçer.

## Task 4: başka sürümün kopyası için sürüm satırı

`acquisition.acquire_for_source(..., other_versions: bool = False)`. `False` iken işlev **bayt bayt** bugünkü gibidir. `True` iken, aynı sürümün adayları denendikten sonra hâlâ PDF yoksa: `identity_status == "doi_verified"`, `version_status == "different"` ve `version_label` dolu adaylar etiket sırasıyla denenir: `publishedVersion`, `acceptedVersion`, `submittedVersion` (eşitlikte aday kimliği). **Sapma, adıyla:** SW10.3'ün sırası barındıran türüne göre (yayıncı, ön baskı, yazar / kurum kopyası); aday satırları barındıran türünü taşımıyor, yalnızca sürüm etiketini. Etiket sırasının verimi **ölçülmedi**.

İlk başarılı indirme için `store.open_lookup_version(research_id, svid, version_label, landing_url)`: aynı `work_id` altında yeni `source_versions` satırı, `_insert_other_version`'ın kalıbıyla (başlık ve yazarlar kopyalanır, **DOI ve özet kopyalanmaz**, `origin = 'provider'`), `identifier_mappings`'te `scheme = "pdf_lookup_version"`, `value = "{svid}:{version_label}"` — aynı çağrı ikinci kez satır açmaz, var olanı döndürür. Satır, sağlayıcının öbür sürümleri araştırmaya nasıl üye oluyorsa öyle üye olur (`store.py` ~1457; ayrı aday olarak **taranmaz**). İşin başı değişmez (`_settle_work_head` kuralı: yayımlanmış kayıt). PDF bu yeni satıra `_attach_pdf` ile bağlanır; deneme `record_pdf_attempt` ile saklanır. `uncertain` aday hiçbir durumda kendiliğinden bağlanmaz.

- [ ] **Tests first:** varsayılan çağrı bugünkü sonucu verir (mevcut `acquisition` testleri dokunulmadan geçer); `True` iken farklı sürümlü doğrulanmış aday yeni satıra bağlanır, yayımlanmış kaydın kendisi PDF almaz, pasajlar yeni satırın etiketini taşır, `answer_version` onu seçer; tekrarlanan çağrı ikinci satır açmaz; `uncertain` ve `mismatch` aday bağlanmaz; yeni satır aday listesinde ayrı kayıt olarak görünmez.

## Task 5: akış

`flow._fulltext_fetch(run, scope)`; `execute`'ta yeni dal.

1. **`code:fulltext_plan` adımı.** `succeeded` ise saklı çıktı okunur. Değilse: `works` satırları birkaç sorguda kurulur (`ranking._versions` kalıbı), sıra `DecisionStore.latest_ranking(rid, revision)` (yoksa boş: gruplar kimlik sırasına düşer), `limit = run["budget"]["max_fulltext_works"]`. `already_text` işleri için kod hemen yazılır (`not_read_yet`, okunan sürüm = `store.answer_version`'ın seçtiği). Çıktı: `{"limit", "works": […], "not_reached": n, "already_text": n, "groups": {"user": n, "candidate": n, "unresolved": n}}`.
2. **İş başına `code:fulltext_work` adımı**, plan sırasıyla, her birinden önce `_checkpoint(run_id, scope_revision)`. Saklı adımı `succeeded` ya da `failed` olan iş **atlanır ve hiçbir sayaca yazılmaz** (Ders 1). Yoksa: baş için `_acquire_pdf(run, baş, 0, None)`; baş metinsiz kaldıysa `_inspect`'teki sırayla işin öbür sürümleri (`work_versions`); hâlâ metin yoksa ve başın DOI'si varsa, bu iş için başka-kopya araması **henüz yapılmadıysa** (`store.pdf_discoveries` boş) `acquire_for_source(..., web_search=False, other_versions=True)` — `_find_other_copy`'nin adımı ve saklama biçimiyle (`pdf_other_copy`), ikinci bir adım türü açmadan. **D35'ten geniş, adıyla:** `_needs_other_copy` aramayı yalnızca 403 / 404 almış bir bağlantıdan sonra açar; burada hiç açık bağlantısı olmayan iş de (kapalı yayıncı kayıtlarının çoğu) bir kez aranır — yoksa SW10.5'in "önce ikiz, sonra yazar kopyası" yolu hiç denenmez. `answer` ve `pdf_collection`'da tetik aynı kalır. Sonra `identity.check`, `settled_code`, `DecisionStore.record(kod, step_id=<iş adımı>)` (okunan sürüme; metin yoksa başa), `derive_selection`. Yazma kuralı dilim 05 / 09'un `should_write` ruhunda: güncel karar aynı kodsa ve eskimemişse yazılmaz; bu dilimin sahip olmadığı taze bir tam metin kodu (dilim 12'ninkiler, insan) varsa yazılmaz. Adım çıktısı: `{"work_id", "head", "read_version", "version_label", "asset_id", "route": "record_link" | "work_version" | "other_copy" | "lookup_version" | null, "identity", "code", "requests_unanswered": n}`. Kod `None` ise adım `failed` + `error_code = "fetch_not_settled"` kapanır (bu koşuda yeniden denenmez; sonraki koşunun planına girer).
3. Bir işin hatası koşuyu **durdurmaz** (D18'in ruhu): beklenmeyen istisna o işin adımını `failed` kapatır, sıradaki iş sürer. Koşu yalnızca `_checkpoint`'in gördüğü duraklatma, iptal ya da kapsam revizyonuyla durur.
4. **`code:fulltext_summary` adımı.** Sayılar bu koşunun **saklı iş adımlarından** toplanır: `{"fetched": n, "unreadable": n, "no_fulltext": n, "not_settled": n, "already_text": n, "not_reached": n, "identity": {"doi": n, "title": n, "unconfirmed": n}, "routes": {…}}`. §2.5'in "tam metni okunan" ve "PDF bekleyen" sayılarının kaynağı budur.

**Kendiliğinden kuyruğa girme:** `execute`, bir `discovery` koşusunu `completed` yaptıktan hemen sonra, araştırma `sw` ise, `Settings.fulltext_fetch == "auto"` ise ve `fetch_plan` en az bir iş veriyorsa `store.create_run(rid, "fulltext_fetch", bütçe, idempotency_key=f"fulltext_fetch:after:{run_id}")` çağırır. Duraklamış, iptal edilmiş ya da başarısız keşif koşusu hiçbir şey kuyruğa sokmaz; anahtar sayesinde aynı keşif koşusu iki getirme koşusu açmaz. Bütçe hesabı `api/app.py` ile **tek** işlevden gelir (ikisi de onu çağırır).

- [ ] **Tests first** (`tests/test_fulltext_flow.py`): `auto` iken tamamlanan `sw` keşif koşusunu bir `fulltext_fetch` koşusu izler, `off` iken ve `legacy`'de izlemez; duraklayan keşif koşusu izlenmez; koşu sonunda hiçbir seçim `included` / `excluded` olmadı ve hiçbir model oturumu açılmadı; aday iş getirilir ve `not_read_yet` alır, okunan sürüm saklıdır; yayımlanmış başı kapalı, ön baskı sürümü açık iş ön baskıdan okunur (D48) ve karar o sürüme yazılır; her yolu reddedilen iş `no_fulltext` + `pending`; zaman aşımına uğrayan iş karar almaz ve **sonraki** getirme koşusunda yeniden denenir; taze `no_fulltext` iş sonraki koşuda istenmez (sahte `fetcher` çağrı sayısıyla); reddeden bağlantı ikinci koşuda istenmez (D35); sınırın dışındaki iş `not_reached` sayılır ve ikinci koşu onu getirir; **plan boyu sınıra eşitken ortada duraklatılıp sürdürülen koşu planın tamamını bitirir, hiçbir bağlantıyı iki kez istemez ve özet sayıları kesintisiz koşununkiyle aynıdır** (Ders 1); iki iş arasında ve bir işin `fetch_pdf` adımından sonra duraklatma; kullanıcının dışladığı iş plana girmez, kullanıcının dahil ettiği iş en önde gelir; kapsam revizyonu koşuyu iptal eder ve eski karar eskir; bir işin istisnası öbürlerini durdurmaz; getirme koşusu etkinken `answer` koşusu açılamaz, duraklatılınca açılır; `answer` ve `pdf_collection` koşuları bu dilimden önceki adımları verir.

## Task 6: protokol ve tekrar aşaması

`protocol.py`: `sw` gövdesinde `thresholds.fulltext_fetch = {"work_limit": N}` (N kapsamın eforundan). `legacy` gövdesi aynı. `tests/determinism_stages.py`'ye `fulltext_plan` aşaması: sabit havuz + sıra + kararlar → planın ve `settled_code` sonuçlarının tek özeti; iki hash tohumu.

## Task 7: görünüm

Koşu görünümü `fulltext_fetch` koşusunun üç adım türünün çıktısını taşır: `store.STEP_OUTPUT_KINDS`'e `code:fulltext_plan`, `code:fulltext_work`, `code:fulltext_summary` eklenir. Yeni uç nokta ve `views.py`'de yeni alan yok.

## Task 8: arayüz (en az)

Önce [.impeccable.md](../../.impeccable.md). `api.ts`: `RunKind`'a `fulltext_fetch`. `labels.ts` + `i18n.ts` (EN + TR): koşu türü "Full-text retrieval" / "Tam metin getirme"; adımlar "Retrieval plan (code)" / "Getirme planı (kod)", "Full text of one work" / "Bir işin tam metni", "Retrieval summary (code)" / "Getirme özeti (kod)". `Transcript.tsx`: üç adım türü → `'pdf'` fazı; koşunun faz sırası `['pdf']`; plan cümlesi "Retrieve the open full text of the candidate works in rank order; nothing is included or excluded by this." (TR karşılığıyla). `ResearchView.tsx`: koşu türü süzgecine eklenir. `BackgroundJobs.tsx`: `JOB_KINDS`'e eklenir ki duraklat / sürdür görünür olsun. **`PdfReadiness.tsx`'e dokunulmaz**; "getirilmedi" ve "PDF bekleyen" sayılarının ekranı dilim 18 / 20'dir. Yeni Playwright senaryosu yok; A–H geçer (H'nin sunucusu `off`).

## Task 9: dilimi kapat

- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı (bilinen tek başarısızlık aynı). `cd apps/web && npm run build && npm run lint`, sonra Playwright A–H. `git diff --check`. Canlı istek, indirme, kuru çalıştırma **yok**.
- [ ] `docs/decisions.md` en üste `## D83 — Follow an sw discovery run with a full-text retrieval run that fetches once per work in rank order, records the version read, and leaves a work without text unresolved`. Limits adıyla söylemeli: yalnızca `sw`; "arka plan" tek işçide sıradaki koşudur, başka bir koşu başlatmak için duraklatmak gerekir ve getirme SW10.1'in dediği gibi kod aşamasından hemen sonra değil keşif koşusundan sonra başlar; iş sınırı elle seçildi; **süre, erişim oranı, etiket sırası, kimlik denetiminin gücü ve sıralı getirmenin bedeli ölçülmedi** (dilim 24; SW10'un sayıları tek konudan ve ürün dışı betiklerden); arXiv başlık araması ve Europe PMC kurulmadı (ölçülen verim 2 / 116 ve 3 / 118); `unconfirmed` kimlik metni ayırmaz; özeti okunmamış iş getirilmez; başka-kopya aramalarının istekleri `provider_requests` sayacına girmiyor (`pdf_collection` ile aynı); taze `no_fulltext` yeniden denenmez (kullanıcının **Find PDF** ve yükleme yolları kalır); kodun açtığı sürüm satırının etiketi sağlayıcının beyanıdır, metinle doğrulanmaz; kapı ve model okuması yok (dilim 12 / 23).
- [ ] SW belgesinde SW10 **Status** satırına bir cümle. `sw-status.md` satır 10: `uygulandı, inceleme bekliyor` + açık kalanlar. Tek commit, `git push origin main`.

## Güncellenecek mevcut testler (adıyla izinli)

Yalnızca **kurulum** değişir, beklenti değişmez: `sw` araştırması açan her mevcut test dosyasının uygulama kurulumu `fulltext_fetch="off"` alır (`test_vocabulary_flow.py`, `test_vocabulary_labels.py`, `test_expansion_flow.py`, `test_ranking_flow.py`, `test_lookup_flow.py`, `test_search_paging.py`, `test_criterion_flow.py`, `test_approval_flow.py`, `test_abstract_flow.py`, `test_abstract_concurrency.py`, `test_suggestion_flow.py` ve kurulumu ödünç alan öbürleri) ve `tests/acceptance/fixture_server.py`. `test_only_an_sw_protocol_carries_the_record_identity_thresholds` `sw` gövdesinde `thresholds.fulltext_fetch` kazanır (`legacy` beklentisi aynı). Bunların dışında bir mevcut test kırılırsa dur ve bildir.

## Son ileti

Eklenen ve değişen dosyalar; temel ve son test sayıları, komut, Playwright sonucu; `skill_package_hash` önce / sonra (beklenen: aynı); "hiçbir seçim değişmez", "sürdürülen koşu planın tamamını bitirir ve hiçbir şeyi iki kez saymaz", "sonraki koşu kaldığı yerden sürer", "başka sürümün kopyası kendi satırına bağlanır" ve "`legacy` / `answer` / `pdf_collection` aynı" testlerinin adları; kurulumu `off`'a çevrilen her dosya; eşzamanlılık eklendiyse `_send_through_limiter` ile eklendiği; yazıldığı gibi yapılamayan her şey ve her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: kod, kullanıcı onayı olmadan bir işin altına sürüm satırı açıp PDF bağlayabilir — yalnızca DOI'si doğrulanmış ve sürümü beyan edilmiş kopya için; tam metin aşamasına ilk kez karar yazılıyor ve hepsi `unresolved`); canlı servise ve ürün veritabanına dokunulmadığı; commit özeti.

## Açık noktalar

- **Sahip görmeli:** getirme koşusu sürerken o araştırmada yanıt, keşif ve tablo koşusu açılamaz; işçi tek olduğu için başka araştırmaların kuyruktaki koşuları da bekler. `detailed` eforda bu kabaca 25 dakikadır (ölçülmedi). Çıkış: duraklat. Başka bir koşu istenince getirmenin kendiliğinden yol vermesi bu dilimde yok.
- **Eskimiş tam metin kararı:** `work_outcome` tam metin aşamasına öncelik verir ve eskimişliğe bakmaz. Soru revize edilip özet yeniden okunduğunda kapsam dışı çıkan bir iş, eski `not_read_yet` yüzünden `pending` kalır. Dilim 12 tam metin aşamasının sahibi olduğu için düzeltme oraya yazılmalı; bu dilim durumu bir testle **belgeler**, düzeltmez.
- **"Sonraki koşu"yu başlatan ekran yok:** ikinci getirme koşusu ya sonraki keşif koşusundan sonra kendiliğinden ya da API ile başlar (dilim 18).
- **İstek sayısı:** iş başına en çok bir indirme + dört DOI araması + sürüm başına bir indirme. Unpaywall `contact_email` ister; yoksa o yol `auth_required` döner ve `no_fulltext`'in "her yol yanıt verdi" koşulunu sağlar — ayar eksikliği yüzünden `no_fulltext` yazılan iş, ayar geldikten sonra da yeniden denenmez. Özet adımı bunu `routes`'ta saymalı; dilim 18 göstermeli.
- **Açık erişim payı konuya bağlı:** kuantum konusunda işlerin yaklaşık yarısı metin verdi ve çoğu arXiv'dendi; tıp ya da mühendislikte oran ve kaynak karışımı başka olur (SW10 Limits). Ölçülmedi.
