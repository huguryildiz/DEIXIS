# SW dilim 13e — Getirme ve aramanın paralelliği: uygulama planı

**Tarih:** 22 Eylül 2026. **Durum:** Task 1 ve 3 uygulandı (22 Eylül 2026); Task 2 sahip kararıyla çıkarıldı, gerekçe [sw-status.md](sw-status.md) satır 13e. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir; bu dilim ana planda yoktur). **Karar:** yok (davranış değişmez); gerekçe D88'in ölçümü ([sw-measure-2026-09-22.md](sw-measure-2026-09-22.md)). **Önkoşul:** 13ö (koşuldu). **Tür:** Kur. **Uygulayan:** Opus · high. **İnceleme:** tam (Fable); yazım sırası kanıtın sırasıdır.

**Goal:** Ölçüm, 13c'nin toplama sınırlarıyla hedeflere (5 / 10 / 15 dk) varılamayacağını gösterdi. Duvar saati üç yerde: (1) `code:fulltext_work` işleri **tek tek sırayla** indiriyor, paralellik 1,0; `detailed`'da 300 adım 16,4 dk, getirme aşamasının tamamı. (2) Keşifte sağlayıcı aramaları sorgu sorgu sırayla gidiyor, paralellik 1,6–1,9 (yalnız sayfa okumaları üst üste biniyor). (3) Tek bir okuma çağrısı adaptörün 300 sn tur sınırını aşınca (`client_timeout`) bütün okuma aşaması `model_call_failed` ile duraklıyor; 152 oturumun 151'i sorunsuzdu. Bu dilimden sonra: getirme aşaması **konak başına tek istek, konaklar arası en çok 4 iş** ile koşar; keşif aramaları **sağlayıcılar arası paralel, sağlayıcı içinde sıralı** gider ve kayıtlar **eskisiyle aynı sırada** yazılır; zaman aşımına düşen bir okuma çağrısı aynı `operation_key` ile **bir kez** yeniden denenir, ikinci kez düşerse bugünkü gibi duraklar. Aynı girdiyle aynı `stage_decisions`, `selections`, adım çıktıları, kayıt birleştirmesi ve olaylar.

**Architecture:** Model çağrılarının gönderici döngüsü (`flow._send_through_limiter`: en çok N uçuşta, her gönderimden önce `_checkpoint`, durma gelince uçuştakiler bitip kaydedilir, yenisi gönderilmez) örnek alınır; indirmeler için **ayrı** bir sınırlayıcı yazılır, model sınırlayıcısı (`deps.limiter`) indirmelere kullanılmaz. Konak nezaketi tek yerde: `documents/fetch.py`'ye süreç geneli `host → asyncio.Lock` (istek yapılan URL'nin konak adı; `_acquire_pdf`'in açtığı bağlantı, sürüm ve DOI arama isteklerinin hepsi bu kapıdan geçer). Mevcut sağlayıcı pacer'ları (`providers/pacing.py`, Semantic Scholar) ve `MIN_INTERVAL_SECONDS` (arXiv) olduğu gibi kalır. Aramada ağ işi ile yazım ayrılır: her sorgunun sayfaları kendi görevinde okunur (sayfa N+1 sayfa N'in imlecine bağlıdır, mağazaya değil), sonuçlar **sorgu dizini sırasıyla** uygulanır; böylece DOI birleştirmesinde hangi sağlayıcının kaydının önce geldiği değişmez.

## Global constraints

- **Davranış değişmez:** aynı girdiyle aynı karar satırları, aynı seçimler, aynı adım çıktıları (`fulltext_work:<head>`, `fulltext_summary`, arama adımları), aynı `operation_key`'ler, aynı olaylar. Adımların **bitiş zamanı** ve `run_steps` satırlarının `started_at` sırası değişebilir; kayıtların birleştirilme sırası ve kararların yazılma sırası değişmez.
- Olay döngüsü kuralı: yazılar kısa eşzamanlı işlemler, işlem içinde `await` yok, `asyncio.to_thread` ile store işi yok. Paralellik yalnızca ağ beklemelerinde.
- "Bir iş için tek DOI araması" (D35, SW10.5) ve "arama satırları araştırmanın geçmişidir" kuralları aynen kalır. Uçuştaki iki işin aynı `source_version` satırını açabileceği bir yol (bir işin araması öbür işin sürümünü açıyor) görülürse **DUR VE BİLDİR**; paralellik o durumda o iki işi seri koşacak şekilde daraltılır, tahmin edilmez.
- Durma (`_checkpoint`: duraklat, iptal, yeni kapsam revizyonu) her gönderimden önce bakılır; durma gelince uçuştaki işler bitip adımlarını yazar, yeni iş başlamaz, `RunStopped` ondan sonra yükselir (model göndericisiyle aynı).
- Canlı kütüphane ve 8765 açılmaz; testlerde ağ yok.

## Dosya yapısı

Değişecek: `backend/deixis/workflow/flow.py` (`_fulltext_fetch`, `_discovery`'nin arama döngüleri, `_search_pages` / `_search`'in ağ–yazım ayrımı, `_model_step`'in `client_timeout` yolu), `backend/deixis/documents/fetch.py` (konak kapısı), gerekirse yeni `backend/deixis/workflow/downloads.py` (indirme göndericisi; `concurrency.py` kalıbı), `tests/test_fulltext_flow.py`, `tests/test_provider_flow.py`, `tests/test_search_paging.py`, `tests/test_adjudication_flow.py`, yeni `tests/test_retrieval_parallelism.py`, `sw-status.md`. Migration yok. Yöntem paketi ve sözleşmeler değişmez (`skill_package_hash` aynı).

## Task 1: getirme aşaması konak başına nazik, konaklar arası paralel

- Sabit: `FULLTEXT_FETCH_PARALLEL = 4` (`workflow/fulltext.py`), efordan bağımsız; efora bağlamak ölçümden sonra kararlaştırılır.
- `_fulltext_fetch`: plan dondurulmuş listeyi verir (değişmez); işler gönderici döngüsüyle en çok 4 uçuşta `_fulltext_work`'e verilir. `_fulltext_work`'ün kendisi ve `_fetch_work_text` değişmez (adım daha önce `succeeded` / `failed` ise atlanır; bir işin beklenmedik hatası kendi adımını kapatır, D18).
- Konak kapısı: `fetch.py`'de istek yapılmadan önce alınan, istek dönünce bırakılan konak başına kilit; süreç geneli. Aynı konağa iki iş sırayla gider, farklı konaklara aynı anda. Yönlendirme (3xx) yeni konağa gidiyorsa kapı yeni konak için alınır.
- `_fulltext_summary` aynı sayıları verir (adım çıktılarından sayıyor; sıra bağımsız olduğu test edilir).
- [ ] **Tests first (paralellikten önce, değişmemiş kodda yaz):** (a) *eşitlik*: sahte getirici ile 8 iş, 3 konak, birkaç sürümlü iş, DOI aramasıyla açılan başka kopya, 403 alan bağlantı, hiç açık bağlantısı olmayan kayıt; sıralı koşunun `run_steps` çıktıları (adım adına göre), `stage_decisions`, `selections`, `pdf_discoveries` satırları kaydedilir, paralel koşunun aynısını verdiği doğrulanır (`tests/determinism_stages.py` kalıbı). (b) *paralellik*: gecikmeli sahte getirici, aynı anda uçuşta en çok 1/konak ve toplamda >1 olduğu, 4'ün aşılmadığı. (c) *durma*: aşamanın ortasında duraklatma; uçuştaki işlerin adımları kaydedilir, yeni adım açılmaz, sürdürülen koşu kalan işleri bitirir ve sayıları aynı çıkar.

## Task 2: keşif aramaları sağlayıcılar arası paralel, yazım sırası aynı

- İlk tur ve genişletme turu (`_expansion` sonrası) için aynı düzen: sorgular sağlayıcıya göre gruplanır; **her sağlayıcının sorguları ve sayfaları sırayla**, **sağlayıcılar aynı anda** okunur. Ağ sonuçları (sayfa çıktıları) biriktirilir ve **sorgu dizini sırasıyla** mağazaya yazılır: kayıt birleştirmesi (DOI), `search_runs` satırları, adım çıktıları, `unread` sayımları bugünkü sırayla oluşur.
- `_skip_unsearchable`, `retry_failed`, `failure` toplama ve D18 duraklaması (hiçbir arama başarılı değilse) aynen; genişletme turunun başarısızlığı yine duraklatmaz. `extra_page_requests` ödeneği yine bütün sorgulara birlikte uygulanır — bir sağlayıcının okuması öbürünün ödeneğini tüketiyorsa bugün hangi sırada tüketiyorsa o sırada tüketmeli; ödenek sayacı sorgu dizini sırasıyla uygulanır, ağ sırasıyla değil. Bu kural uygulanamıyorsa (ödenek okuma sırasında karar veriyorsa) **DUR VE BİLDİR**.
- Sağlayıcının kendi hız sınırı beklemesi (D88 efor kuralı) değişmez; paralel okuma bir sağlayıcıya ikinci bir eşzamanlı istek açmaz.
- [ ] **Tests first:** (a) *eşitlik*: iki sağlayıcı, ikişer sorgu, sayfalı okuma; sıralı ve paralel koşunun `search_runs`, kayıt/sürüm satırları (aynı DOI'yi iki sağlayıcı verir; hangi kaydın baş olduğu aynı kalmalı) ve arama adımı çıktıları birebir. (b) *paralellik*: gecikmeli sahte taşıyıcı, iki sağlayıcının istekleri üst üste biner, aynı sağlayıcının istekleri binmez. (c) *D18*: bir sağlayıcı bütün sorgularda düşer, öbürü başarılı → duraklama yok; ikisi de düşer → `_pause`; mevcut `test_provider_flow.py` senaryoları geçer.

## Task 3: zaman aşımına düşen tek okuma çağrısı aşamayı durdurmaz

- `_model_step`'te `result.status == "client_timeout"` (adaptörün tur sınırı; `delivery_class` `after_send_unknown`) için: adım `outcome_unknown` ile kapanır (bugünkü gibi), sonra **aynı `operation_key` ile bir yeni deneme** gönderilir (yeni `attempt`, yeni `step_input` satırı, bütçeden bir çağrı daha düşer; bütçe kalmamışsa `budget_short` kuralı işler). İkinci deneme de `client_timeout` ise bugünkü gibi `model_call_failed` ile durur. Başka hata durumları (`unavailable`, `rate_limited`, `isolation_violation`, `model_mismatch`) değişmez.
- Kapsam: bütün model adımları için mi, yalnız `fulltext_adjudication` için mi? **Yalnız `fulltext_adjudication` ve `abstract_screening`** (parti çağrıları; tek yavaş çağrının aşamayı durdurduğu yerler). `search_plan`, `grounded_answer`, `answer_review` bugünkü gibi ilk zaman aşımında durur; oralarda bir çağrı bir aşamadır.
- [ ] **Tests first:** `FakeAdapter` bir kez `client_timeout` sonra `completed` → okuma aşaması tamamlanır, adımda iki deneme ve iki `step_input`, bütçe iki çağrı düşmüş; iki kez `client_timeout` → `model_call_failed` ile duraklar; `grounded_answer`'da tek `client_timeout` → bugünkü davranış.

## Task 4: kapanış

- Tam pytest; `git diff --check`; satır 13e; tek commit; push. Yeniden ölçüm bu dilimin işi değildir (13ö'nün ikinci koşusu; aynı konu, Luna, `campaign.py` yeniden).

## Ölçülmedi

Duvar saati kazancı (ağ olmadan ölçülemez; 13ö tekrarı ölçer); konak kilidinin gerçek yayıncılarda yeterli nezaket olup olmadığı (403 / 429 oranı ölçümde karşılaştırılır: 22 Eylül koşusundaki oranlar `.local/sw-measure-2026-09-22/` verisinden okunur); `FULLTEXT_FETCH_PARALLEL = 4`'ün doğru sayı olup olmadığı; arXiv 406'nın yeniden denemeyle geçip geçmediği.
