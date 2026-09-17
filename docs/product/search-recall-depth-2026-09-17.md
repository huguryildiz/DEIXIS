# Bilinen eserlerin bulunma oranı: arama derinliği: tasarım notu

**Tarih:** 17 Eylül 2026. **Durum:** Taslak. §6'daki sorular sahibin yanıtını bekliyor. Uygulama kodu değişmedi; yalnız OpenAlex'e modelsiz bir yoklama yapıldı (§2).

**Kısaca:** P5 kapanış ölçümünde (D55) tutulmuş S2 sorusunda k-bağlantılılık eserlerinin yalnız 4/15'i bulundu, S1'de (Kurt) 9/17. Yoklama sorunun büyük kısmının sorgu biçiminde değil **derinlikte** olduğunu gösteriyor. Çekirdek terimle tek bir OpenAlex sorgusunun ilk 100 sonucu S1'de 11/17, S2'de 6/15 bilinen eseri içeriyor; DEIXIS ise sekiz sağlayıcıya dağılan sorguların her birinden yalnız ilk 25'i okuyor. OpenAlex tek istekte 200 sonuç verebildiği için derinlik ek sağlayıcı isteği gerektirmez; maliyet tarama tarafındadır: daha çok aday, daha çok tarama çağrısı. Bu not, çekirdek sorgunun OpenAlex'te derin okunmasını ve tarama bütçesinin buna göre ayarlanmasını önerir.

## 1. Kodda bugün olan

17 Eylül 2026'da `main` (60b8504) üzerinden okundu.

| Parça | Davranış |
|---|---|
| `search_plan` (D44) | Model kavramlar, tek bir çekirdek kavram ve sağlayıcı listesi verir; sorguları `providers/query_compiler.py` yazar. Her sorgu `çekirdek grubu AND aile grubu` biçimindedir; ailesi olmayan plan yalnız çekirdek sorgusu alır. |
| `domain/rules.py`, `standard` | 8 sağlayıcı isteği, sorgu başına 25 sonuç, en çok 150 aday, 12 model çağrısı; tarama 40'lık gruplarla (`SCREENING_BATCH`). |
| `providers/openalex.py` | `search.title_and_abstract`, `MAX_RESULTS = 200`: tek istek 200'e kadar sonuç getirebilir; bugün 25 istenir. |
| `flow._discovery` | Sorgular sırayla aranır; adaylar tekilleştirilir ve ilk `max_candidates` kadarı taranır. |

D55'te iki sorunun her biri 8 sorguyla 103 ve 127 tekil kayıt verdi. S2'de OpenAlex sorgusu `k-connectivity AND underwater…` biçimindeydi ve yalnız 6 sonuç döndü.

## 2. Yoklama (modelsiz, 17 Eylül 2026)

Betikler ve çıktılar `.local/recall-probe-2026-09-17/` altında, depoya girmedi. Yalnız OpenAlex, DEIXIS'in kullandığı `search.title_and_abstract` parametresiyle; bilinen kümeler `scripts/p4_eval/sets/` altındaki dondurulmuş dosyalar (hedef makalenin kendisi sayılmadı).

**Derinliğe göre bulunan bilinen eser:**

| Sorgu | Toplam eşleşme | İlk 25 | İlk 50 | İlk 100 | İlk 200 |
|---|---|---|---|---|---|
| S1 çekirdek: `"packet size optimization" OR "packet length optimization" OR "optimal packet size"` | 261 | 7 | 7 | 11 | 12 |
| S1 geniş: `("packet size" OR "packet length" OR "frame length") AND ("sensor network" OR "sensor networks")` | 740 | 6 | 8 | 9 | 10 |
| S2 çekirdek: `"k-connectivity" OR "k-connectedness"` | 2.426 | 2 | 3 | 7 | 8 |
| S2 çekirdek + ağ: `(…) AND ("wireless sensor network" OR "sensor networks" OR "ad hoc")` | 313 | 3 | 5 | 6 | 7 |

Karşılaştırma için D55'teki çalışma (8 sağlayıcı, sorgu başına 25): S1 9/17, S2 4/15 k-bağlantılılık + 0/7 su altı bağlamı. S2'nin çekirdek sorgusunda ilk 100'e giren 7 eserin biri su altı bağlam katmanındandır.

**Neden bulunamıyor (S2, 15 k-bağlantılılık eseri):**
- 7 eser çekirdek sorgunun ilk 400 sonucunda da yok. Bunlardan en az dördünün başlığında çekirdek terim yok ("Coverage and Connectivity in WSNs: A Survey", "Minimum Range Assignment Problem for Two Connectivity", "Design and Evaluation of Algorithms for … Critical Nodes", "Connectivity restoration in a partitioned WSN"). Bunlar sorgu terimiyle bulunamaz; ancak alıntı zinciri ya da farklı kavram ailesiyle bulunur.
- 7 eserin OpenAlex'te özeti yok; arama bunlar için yalnız başlığa bakar.
- İlk 400'e giren 8 eserin yalnız 1'i ilk 25'te; kalanlar 25'in ötesinde.

**Yerel yeniden sıralama işe yaramadı:** OpenAlex'in tam metin `search` parametresiyle 600 kaydı çekip başlık ve özeti soru terimleriyle BM25'le sıralamak ilk 50'de S1'de 7 (sağlayıcı sırası 8), S2'de 5 (4) bilinen eser verdi. Fark küçük ve yöne göre değişiyor; gömme (embedding) sıralaması denenmedi.

**Sınırlar:** Tek sağlayıcı, iki soru, tek gün. OpenAlex sıralaması zamanla değişebilir. S2'nin katmanları başlıklardan Claude'ca atandı. İlk 100'deki bilinen eserlerin taramada dahil edilip edilmeyeceği ölçülmedi; tarama modeli bugün bulunan bilinen eserlerin S1'de 6/9'unu, S2'de 4/4'ünü dahil etti.

## 3. Öneri

**Derin çekirdek sorgu:** Plan derlendiğinde, OpenAlex etkinse, listenin başına bir sorgu daha eklenir: **yalnız çekirdek grubu**, tek istekte 100 sonuç. Öbür sorgular bugünkü gibi `çekirdek AND aile`, 25 sonuç. İstek sayısı değişmez; mevcut 8 isteğin biri bu sorguya gider.

- **Aday sınırı ve tarama:** Derin sorgu yaklaşık 100 kayıt ekler. `standard` için aday sınırı 150 → 250, model çağrısı 12 → 15 (en çok 7 tarama grubu, plan ve onarımlar). Bu yaklaşık 3 tarama çağrısı ekler; D55'te bütün keşif çalışması 5–6 model çağrısıyla 212 ve 291 s sürmüştü, ek süre ölçülmedi.
- **Aday sırası:** Sınır aşılırsa kesilecek kayıtlar rastgele değil, sağlayıcı sırasına göre belirlenir: her sorgunun ilk kayıtları önce. Böylece derin sorgunun sondaki kayıtları öbür sorguların en iyilerini dışarıda bırakmaz.
- **Görünürlük:** Sorgu satırı bugün `dönen / sağlayıcı toplamı` gösteriyor. Derin sorgu "Çekirdek terim, 100 sonuç" gerekçesiyle ayrı görünür.
- **Kapsam dışı:** Alıntı zinciri (kaynakçadan geri, alıntılayanlardan ileri) bu notta yok. Ayrı dilim olarak önerilir, çünkü çekirdek sorgunun ilk 400'ünde olmayan 7 eserin bir kısmını ancak o bulabilir. Ama bugünkü bilinen kümeler bir makalenin kaynakçasından alındığı için ölçümü dairesel olur (hedef makale bulunursa kaynakçası tümüyle gelir). Önce kaynakçadan türetilmemiş bir bilinen küme gerekir.

**Etkisi yanıt notuyla bağlı:** Daha çok aday, daha çok dahil kaynak demektir. Yanıt girdisindeki PDF sayfası sorunu (`answer-pdf-pages-2026-09-17.md`) dahil kaynak sayısı arttıkça büyür. Sıra önerim: önce yanıt notu, sonra bu not.

## 4. Seçenekler

| | Ne değişir | Artı | Eksi |
|---|---|---|---|
| **A. Derin çekirdek sorgu (öneri)** | OpenAlex'te yalnız çekirdek, 100 sonuç; öbürleri aynı | Yoklamada en çok kazanç; istek sayısı aynı | Tarama bütçesi büyür; çekirdek geniş seçilirse gürültü artar |
| B. Her sorguda derinlik | Bütün sorgularda 25 → 100 | Basit | 800 kayda kadar aday; tarama 20 çağrıya çıkar |
| C. Yerel yeniden sıralama | 600 kayıt çekilir, yerel sıralanır, ilk 150 taranır | Tarama sabit | Yoklamada BM25 fayda göstermedi; gömme maliyeti |
| D. Alıntı zinciri | Dahil en ilgili kaynakların kaynakçası ve alıntılayanları | Terim içermeyen eserleri bulur | Ayrı dilim; ölçümü için yeni bilinen küme gerekir |

## 5. Ölçüm planı

Kurallar D55'teki gibi: kopya kütüphane, commit'lenmiş kod, `gpt-5.6-luna` medium, beklentiler önce yazılır.

1. **Sorular:** S1 ve S2 (D55 kümeleri) + sahibin seçeceği, bilinen kümesi bir makalenin kaynakçasından türetilmemiş üçüncü bir soru (S3). S3, S1 ve S2'de ayar yapıldığı için tutulmuş soru sayılır.
2. **Çalışmalar:** Her soruda bugünkü kural ve A kuralıyla birer keşif çalışması. Taramanın rastgeleliği için S1'de kural başına 2 çalışma.
3. **Sayılar:** Katmana göre bulunan, dahil edilen bilinen eser; tekil kayıt; tarama çağrısı ve süresi; dahil kaynaklarda başlık düzeyinde ilgililik.

**Önceden yazılacak beklentiler (taslak):**
- S1 bulunan: 9 → 11–13. **Yanlış sayılır:** ≤ 9.
- S2 k-bağlantılılık bulunan: 4 → 6–8. **Yanlış sayılır:** ≤ 4.
- Dahil edilenlerin başlık düzeyinde ilgililiği D55'ten en çok 0,10 düşer (S1 0,81, S2 0,94).
- Keşif süresi en çok 3 dakika uzar; model çağrısı 15'i aşmaz.

## 6. Sahibe sorulanlar

Her soruda önerim ilk seçenek.

1. **Yöntem.** a. Derin çekirdek sorgu (A). b. Her sorguda derinlik (B). c. Yerel yeniden sıralama (C). d. Önce alıntı zinciri (D).
2. **Derinlik.** a. 100. b. 200 (yoklamada S1'de +1, S2'de +1 eser; tarama iki katı). c. 50.
3. **Tarama bütçesi (`standard`).** a. Aday 150 → 250, model çağrısı 12 → 15. b. Aday sınırı aynı kalır, kesilen kayıtlar "taranmadı" diye görünür. c. Yalnız `detailed` çaba derin sorgu alır.
4. **Sağlayıcı.** a. Yalnız OpenAlex (tek istekte 200'e kadar, anahtarsız). b. Sayfalama destekleyen başka sağlayıcılar da (Scopus, IEEE, CORE; kota harcar).
5. **Alıntı zinciri.** a. Ayrı dilim; önce kaynakçadan türetilmemiş bir bilinen küme hazırlanır. b. Bu notla birlikte yapılır. c. Yapılmaz.
6. **Üçüncü soru (S3).** a. Sahip bir soru ve 10–20 bilinen eser verir (kaynakçadan değil, kendi bildiğinden). b. Claude sahibin başka bir makalesinden hazırlar (kaynakçadan türetilir, dairesellik notuyla). c. S3 olmadan yalnız S1 ve S2.

## 7. Alt adımlar

1. **Beklentilerin ve S3 kümesinin dondurulması:** §5, sahibin yanıtlarıyla, commit.
2. **Derleyici:** `query_compiler` derin çekirdek sorguyu üretir (`deixis.query_compiler.v2`); saklı v1 sorguları olan eski çalışmalar değişmeden sürer. Testler önce kırmızı.
3. **Bütçe ve aday sırası:** `rules.py` ve `_discovery`; sorgu sırasına göre adil kesme; test.
4. **Görünürlük:** Sorgu gerekçesi ve sonuç sayısı; masaüstü ve dar ekranda tarayıcı denetimi.
5. **Ölçüm:** §5.
6. **Karar kaydı:** D-girdisi; beklenti karşılanmazsa değişiklik geri alınır ve bu yazılır.
