# Arama ve tarama iş akışı (SW1–SW16): uygulama ana planı

**Tarih:** 20 Eylül 2026. **Durum:** plan; hiçbir dilim uygulanmadı. **Kaynak:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md) (SW1–SW16). **Ana dosya ve ilerleme:** [sw-status.md](sw-status.md).

**Kısaca:** SW1–SW16, sahibin kabul ettiği tasarım yönüdür; ürün kodunda hiçbiri yoktur. Bu belge o kararları 24 dilime böler, sırasını ve bağımlılıklarını verir, her dilimin kapsamını ve kabul koşulunu yazar. Her dilim ayrı bir sohbette uygulanır; ayrıntılı dilim dosyası dilimden hemen önce yazılır (neden: §7). Bu belge yeni tasarım getirmez: SW metni ile çelişirse SW metni geçerlidir, fark sahibe sorulur.

Bu plan, 17–18 Eylül tarihli dört arama tasarım belgesinin (`prisma-s-hybrid-search-design`, `prisma-s-design-review`, `search-query-structure-design`, `search-strategy-critical-review`) yerine geçer; o belgeler SW1–SW16'dan öncedir ve arka plan olarak kalır.

## 1. Bugünkü ürün ile SW arasındaki fark

Kod 20 Eylül 2026'da okundu (`flow.py`, `store.py`, `providers/`, `documents/`, `contracts/`, migration 0001–0036).

| Konu | Üründe bugün | SW'nin istediği | SW |
|---|---|---|---|
| Arama sözcükleri | `search_plan` model adımı kavram + eş anlamlı üretir (D44), kod sorguyu derler | Kod üretir, sayım sorgusuyla sınar; model yalnızca koşullu terim önerir | SW2 |
| Kavram yapısı | Düz rol listesi (`core`, `method`, …); iddia ve dışlama sözcüğü yok | Dört blok (ortam, görev, yöntem, sonuç); iddia ve dışlama sözcükleri sorgu dışında | SW1.3 |
| Kaynak seçimi | Anahtarı olan her sağlayıcı açık, model alt küme seçer | OpenAlex omurga; alan kaynağı kodla eklenir; Scopus kapalı | SW3 |
| Atıf zinciri | Yok (yalnızca `scripts/isolated_hybrid_search.py`) | Kodla seçilen 15–25 tohum, referanslar ve atıf yapanlar | SW4, SW3.6 |
| Derleme tespiti | Yok | Başlık, özet ifadesi, 150+ referans; tohum havuzuna | SW5, SW9.3 |
| Eksik özet | Yalnızca aynı DOI başka kaynaktan gelirse dolar | DOI ile ikinci kaynaktan sorulur | SW5.5 |
| Kayıt birleştirme | DOI eşleşmesi; tam başlık eşleşmesi yalnızca işaretler | Kayıt türü, başlık + yazar + özet benzerliği, dış bağlantı, geri alınabilir | SW6 |
| Kayıt sıralama | Yok (geliş sırası, `max_candidates` kesimi) | Dört sinyal + gömme, RRF; sıra kesmez | SW7, SW8 |
| Özet taraması | Model `include/exclude/uncertain` der, alıntı yok, tek koşu, 40'lık partiler | Önce kod; model tek etiket + birebir alıntı; iki koşu; özetten `include` çıkmaz | SW9, SW1.2 |
| Tam metin | Yalnızca yanıt koşusunda, dahil edilenler için, en çok 8 indirme | Kod aşamasından hemen sonra arka planda, sıraya göre | SW10 |
| Tam metin kararı | Yok; dahil etme özetten gelir | Ölçütün her parçası için doğrulanmış alıntı; `include` / `criterion_not_met` / `unresolved` + neden kodu | SW1, SW11 |
| Ölçüt ve ipucu ifadeleri | `FORMULATION_TERMS` elle yazılmış, tek konuya özgü (`flow.py:60`) | Model sorudan önerir (3 koşu, 2'de geçen kalır), kullanıcı onaylar | SW15 |
| Ölçüt pasajları | Soru sözcükleriyle BM25 + gömme; formülasyon kotası sabit liste | İki ayrı kota: konu pasajları ve ölçüt pasajları (ipucu ifadeleriyle) | SW12 |
| İnsan kuyruğu | Yok; `uncertain` → `pending` süzgeci | Yalnızca gerçek kararsızlık; tek soru, alıntı, sayfa | SW11 |
| Protokol kaydı | Yok; adımda yalnızca `skill_package_hash` | İlk aramadan önce dondurulmuş, özetlenmiş kayıt; her adım özeti taşır | SW14 |
| Belirlenimcilik | `fuse_rankings` eşitliği argüman sırasıyla bozar | Eşitlik kalıcı kimlikle bozulur; tekrar testi | SW14.6–7 |
| Ölçüm tablosu | Yok | Kol ve sinyal başına prob tablosu; kol türüne göre durma | SW13 |
| Kod kapısı | Yok | Varsayılan kapalı; yalnızca kullanıcının onayladığı kural | SW16 |
| Yerleşik gömme | Yok (`pyproject.toml`'da `fastembed` yok) | Anahtarsız "This computer · built-in" seçeneği | SW8.3–6 |
| LaTeX kaynağı | Yok | arXiv kaynağından metin + denklem, PDF sayfasına eşlenerek | SW10.6–8 |

## 2. Tüm dilimler için geçerli kurallar

1. **Yeni akış bayrak arkasında büyür.** `Settings.search_workflow` (`legacy` | `sw`, ortam değişkeni `DEIXIS_SEARCH_WORKFLOW`, varsayılan `legacy`) dilim 01'de eklenir; bir araştırma hangi akışla açıldıysa kapsam revizyonunda saklanır ve öyle kalır. Dilim 24'e kadar varsayılan değişmez; `main` her dilimden sonra çalışır durumda kalır. Eski araştırmalar `legacy` ile açılmaya devam eder.
2. **Yanıtın okuduğu tek şey `selections.state` olmaya devam eder.** Yeni aşama kararları kendi tablolarına yazılır ve `selections`'ı türetir; kullanıcının dahil etme / dışlama seçimi her zaman üstündür ([AGENTS.md](../../AGENTS.md), "User Authority").
3. **Karar yetkisi koddadır.** Model yalnızca önerir; modelin güven puanı kullanılmaz; model kapalıyken akış çalışır, yalnızca `unresolved` büyür (SW1.1).
4. **Hiçbir sıralama kayıt silmez.** Sıra, inceleme sırasıdır (SW7.2, SW8.2).
5. **Sayılar ayrı tutulur:** bulunan, tekil, taranan, aday, tam metni okunan, dahil edilen, ölçütü karşılamayan, PDF bekleyen, kuyrukta, okunmamış.
6. **Genelleme:** kuantum tek örnektir. Ürün koduna konuya özgü sözcük, desen ya da eşik girmez. Ölçüm isteyen her dilim en az iki konuda koşar: kuantum dolanıklık dağıtımı ve KAA'da paket boyutu (`.local/second-topic-packet-size-2026-09-20/`).
7. **Ölçüm en sonda, toplu yapılır** (sahibin kararı, 20 Eylül 2026). Yeni akış bayrak arkasında büyüdüğü için ölçülmemiş hiçbir şey kullanıcıya ya da canlı kütüphaneye ulaşmaz; bu yüzden dilimler ölçüm için durmaz. SW'nin "uygulanmadı" ya da "ölçülmedi" dediği parçalar doğrudan kurulur, karar kaydının Limits bölümüne "ölçülmedi; dilim 24 kampanyasında bakılacak" yazılır. Elle seçilmiş her eşik tek bir adlı sabitte durur ve protokol kaydının `thresholds` alanına yazılır ki kampanyadan sonra değiştirmek ucuz olsun. İki istisna: dilim 06'daki bilinen kusur kurulmadan önce düzeltilir ve birkaç model çağrısıyla sınanır; dilim 13 tek soruluk bir duman testidir. Ölçüm modeli `deepseek-flash`, DeepSeek bağlantısı, efor `high` (Luna kotası bitti); ölçüm canlı kütüphaneye değil ayrı bir `DEIXIS_DATA_DIR` ve 8765 dışı bir porta karşı koşar; çıktı `.local/` altına yazılır; beklenti koşudan önce ayrı bir dosyada dondurulur.
8. **Şema ve sözleşme:** her kalıcı değişiklik yeni numaralı migration'dır (son: `0036`); eski migration düzenlenmez. Sözleşme değişikliği aynı dilimde şema sürümünü, yöntem paketini, `tests/fixtures/research/*.json` ve `tests/fakes.py::valid_response`'u günceller. Model adımı araç almaz, sınırlı onarım dışında döngü yoktur.
9. **Test:** önce başarısız test. Dilim, `PYTHONPATH=backend:. uv run pytest` tamamen yeşilken ve arayüze dokunduysa `npm run build && npm run lint` ile Playwright A–G geçerken biter. `scripts/` içe aktaran testler depo kökünü yolda ister, bu yüzden `backend:.`. `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit` bu makinede dilim 01'den önce de başarısızdı (bellek sınırı yerine zaman aşımı döner); temel sayıda beklenen tek başarısızlıktır. Geçen test iş akışı davranışını gösterir, model kalitesini değil.
10. **Karar kaydı:** dilim kapanırken ilgili SW maddeleri `docs/decisions.md`'ye `D` numarasıyla taşınır (numara o an `grep -n '^## D' docs/decisions.md | head -3` ile kontrol edilir; son: D69). SW belgesindeki giriş silinmez, durum satırı güncellenir.
11. **İş bitince commit'lenir** (sahibin kararı, 20 Eylül 2026). Uygulayan sohbet, dilimin bütün görevleri bittiğinde ve tam test koşusu bilinen tek başarısızlık dışında yeşil olduğunda değişikliklerini tek commit olarak `main`'e işler ve iter (`git push origin main`; dal ve PR yok; commit iletisinde yapay zekâ atfı yok). Yarım kalan dilim commit'lenmez: ağaç geçer durumda bırakılır ve kalan iş `sw-status.md`'ye yazılır. Stash, reset, rebase ve dosya geri alma yine yasaktır. İnceleme sohbeti bulduğunu ayrı bir düzeltme commit'iyle işler; dilim ancak inceleme bitince `kapandı` olur.

## 3. Dilimler

Tür: **Kur** = doğrudan uygulanır. **Kur (ölçülmedi)** = SW'nin "Limits" bölümü uygulanmamış ya da ölçülmemiş diyor; §2.7 gereği yine doğrudan kurulur, eşikleri geçicidir ve dilim 24 kampanyasında sınanır. **Duman** = tek soruluk çalışıyor-mu kontrolü. **Ölç** = ölçüm kampanyası.

### Faz A — Temel

**01 · Protokol kaydı ve belirlenimcilik** — SW14 (tümü). Kur. Önkoşul: yok.
Kapsam: `search_workflow` bayrağı; `protocol_records` tablosu (kanonik JSON + SHA-256, değiştirilemez, revizyonlu); ilk sağlayıcı isteğinden önce `protocol` adımı; `run_steps.protocol_hash`; adım girdisi, model çıktısı ve sağlayıcı yükü için özet sütunları; `domain/canonical.py`; `fuse_rankings` ve `answer_source_order` eşitlik bozma; iki hash tohumu + karışık satır sırasıyla tekrar testi. Arayüz yok.
Kabul: aynı saklı yükle iki koşu aynı kanonik özeti verir; protokol kaydı güncellenemez; `legacy` davranışı sıra eşitlikleri dışında değişmez. Ayrıntı: [sw-slice01-protocol-and-determinism.md](sw-slice01-protocol-and-determinism.md).

**02 · Aşama kararlarının saklanması** — SW9.5, SW11.1, SW11.10 (saklama), SW7.3 (saklama). Kur. Önkoşul: 01.
Kapsam: kayıt × aşama karar satırı (sonuç, neden kodu, kim karar verdi, sonraki adım, protokol özeti, kapsam revizyonu); model önerisi satırı (etiket, alıntı, doğrulandı mı, koşu no); sinyal sırası satırı; insan kararı satırı; iş düzeyinde birleştirme kuralı (SW9.4); `selections`'ı türeten tek işlev; neden kodu sözlüğü `domain/` altında. Yazan henüz yok; yalnızca tablo, depo işlevleri, türetme ve testleri.
Kabul: kullanıcı seçimi türetmeyi ezer; bir sürümdeki işaret işi düşürmez; geniş tek satırlık tablo yalnızca dışa aktarımdır.

**03 · Kayıt türü ve sürüm birleştirme** — SW6.1–3, 5–9. Kur. Önkoşul: 02.
Kapsam: DOI ve başlık önekinden kayıt türü (ön baskı, yayımlanmış, ek ürün, bildirim); başlık ve özet için karakter trigram Jaccard; soyadı karşılaştırması ("Soyad, Ad", ters ad, aksan, "Anonymous" = bilinmiyor); otomatik birleştirme kuralı (0,85 / 0,8 / türler), `extended_version`, `related_suspected`, `probable_version` bağlantıları; her birleştirme kural + puan + kaynakla saklanır ve geri alınır; ek ürün ve bildirimler ana makaleye bağlanır.
Kabul: iki yayımlanmış kayıt hiç birleşmez; yıl farkı 5'i aşarsa otomatik birleştirme olmaz; mevcut D46/D48 iş başı davranışı bozulmaz. Eşikler elle seçilmiştir ve tek konudandır; KAA konusundaki 127 başlık çifti bu dilimde gözle denetlenir.

### Faz B — Protokolün içeriği

**04 · Kodla sözcük dağarcığı ve kavram blokları** — SW2.1–4, 2.7, SW1.3, SW3.5. **Kur (ölçülmedi).** Önkoşul: 01.
Kapsam: soru dili tespiti ve İngilizce anahtar terim alanı (arka uç); soru çerçevesini atma, ad öbeği çıkarma (yeni NLP bağımlılığı olmadan), OpenAlex sayım sorgusu (`per_page=0`); dört blok; iddia ve dışlama sözcükleri yan listede; kök sözcükle başlama, sayıma göre öbeğe daraltma; blok içi OR, bloklar arası AND, sağlayıcı sözdizimine göre derleme; ilk tur adaylarının yazar anahtar sözcükleri ve başlık n-gramlarından genişleme; terim başına verim kaydı.
Ölçüm dilim 24'e kalır (iki konuda, D44 model planına karşı; bulunan pozitifler ve dönen satır sayısı). SW2 "uygulanmadı ve ölçülmedi" diyor; öbekleri bloklara kuralla atamak güvenilmezdir, bu yüzden 08'deki onay adımı zorunludur.
Kabul: model kapalıyken ilk arama koşar; sorudaki iddia sözcüğü sorguya girmez.
Bölündü (20 Eylül 2026): **04a** son iki madde dışındaki her şey ([sw-slice04a-code-vocabulary.md](sw-slice04a-code-vocabulary.md)); **04b** ilk tur adaylarından genişleme ve terim başına verim kaydı ([sw-slice04b-data-expansion.md](sw-slice04b-data-expansion.md)). Dilim 07'nin önkoşulu 04a ve 04c'dir.

**04c · `sw` aramasında sayfalama ve okuma bütçesi** — SW7 bağlamı (ilk tur havuzu 1.369 kayıt), SW2.3, §2.4. Kur. Önkoşul: 04a. (20 Eylül 2026'da eklendi: `sw` sağlayıcı başına tek geniş sorgu atar, ama `_search` sorgu başına en çok `results_per_query` (≤ 25) kayıt okur; geniş sorgu bu haliyle anlamsızdır.)
Kapsam: yalnızca `sw` araştırmalarında bir sorgunun sonuçları sayfa sayfa okunur (OpenAlex'te imleçle, diğer sağlayıcılarda kendi sayfalama kuralıyla; sayfalamayı desteklemeyen sağlayıcı tek sayfa okur ve bu kaydedilir); her sayfa kendi adımıdır (`operation_key`), böylece duraklatılan koşu okunmuş sayfayı yeniden istemez ve başarısız sayfa diğerlerini durdurmaz (D18); sorgu başına okuma sınırı tek bir adlı sabittir, protokolün `thresholds` alanına ve `search_runs`'a (okunan / sağlayıcının bildirdiği toplam) yazılır; sınır sağlayıcının toplamından küçükse okunmayan kayıt sayısı saklanır ve gösterilecek sayılar arasına girer (§2.5). `legacy` bütçeleri (`results_per_query`, `max_provider_requests`) değişmez.
Kabul: sınırın altındaki bir sorguda sağlayıcının bildirdiği her kayıt aday olur; okuma sınırı kayıt silmez, yalnızca okunmayanı sayar; sürdürülen koşu hiçbir sayfayı iki kez istemez. Açık kalan: tarama hâlâ `max_candidates` ile kesilir; onu `sw` için kaldıran dilim 09'dur (K3). Ayrıntı: [sw-slice04c-paging-and-read-budget.md](sw-slice04c-paging-and-read-budget.md).

**04d · Blok atamasını modele sordur, kararı kodda tut** — SW17 (tümü), SW2.2 ve 2.6, SW1.3. Kur. Önkoşul: 04a; 04b ve 04c'den bağımsız. (21 Eylül 2026'da eklendi: 04a'nın edat kuralı blokları ölçümde 28 ifadenin 9'unda yanlış atıyor ve iddia sayıp sorgudan düşürüyor; `.local/sw-block-labelling-2026-09-21/`.)
Kapsam: yeni `vocabulary_labels` model adımı ve sözleşmesi; model yalnızca kodun çıkardığı ifadeleri altı etiketten birine koyar, listeye ifade ekleyemez, bölemez, değiştiremez, atlayamaz ve izin listesi dışına çıkan çıktı reddedilir (onarılmaz); araştırma başına üç koşu, 2/3 çoğunluk, çoğunluk yoksa kuralın etiketi kalır ve ifade sorguya girmez; adım `optional`, model kapalıyken kurala düşülür; kuralın yöntem konumu ikinci veto olarak **tutulmaz** (ölçümde düzeltilen iki vakayı da geri bozuyordu); blok kökeni (`rule` | `model` | `user`) terim başına saklanır ve protokole girer; yeni yöntem paketi dosyası nedeniyle `skill_package_hash` değişir.
Kabul: model her çağrıda hata verirken `sw` keşif koşusu yine arar (04a kabul koşulu korunur, "hiçbir model çağrısı yok"tan "hiçbir zorunlu model çağrısı yok"a daralır); izin listesi dışı ifade dönen koşu düşer; sürdürülen koşu modeli yeniden çağırmaz; `legacy` ve `key_terms` yollarında adım açılmaz. Ayrıntı: [sw-slice04d-model-block-labelling.md](sw-slice04d-model-block-labelling.md).

**05 · Derleme işareti, eksik özet ve sürüm bağlantıları** — SW5.1–5, SW9.3, SW6.4. Kur. Önkoşul: 02, 03.
Kapsam: başlık güçlü sözcüğü / özetin kendini tanımlaması / 150+ referans; yalnızca başlık sözcüğü adaylıktan çıkarır, diğer ikisi işaret koyar ve tohum havuzuna ekler; OpenAlex `type` ve mekân adı kullanılmaz; özetsiz kayıt için DOI ile Semantic Scholar, sonra Crossref (D67 hız sınırı altında), nereden geldiği saklanır; S2 `externalIds`, arXiv DOI alanı ve Crossref ön baskı ilişkisi birleştirmeyi doğrular ya da engeller.
Kabul: özetsiz kayıt hiçbir zaman "kapsam dışı" olmaz. Ölçülmeyen: ikinci kaynağın kaç eksik özeti doldurduğu; dilim bunu iki konuda sayar ve yazar.

**06 · Ölçüt, parçaları ve ipucu ifadeleri önerisi** — SW15.1, 15.2, 15.7. **Kur (ölçülmedi); önce bilinen kusur düzeltilir.** Önkoşul: 01.
Kapsam: yeni `criterion_proposal` sözleşmesi ve yöntem dosyası; sorudan tek cümlelik ölçüt, parçalar, parça başına ifadeler, dışlama başlık sözcükleri; üç koşu, en az ikisinde geçen ifadeler kalır; modelin "güçlü" işareti kullanılmaz; sonuç protokol kaydının alanı olur.
Kurmadan önce düzeltme: ikinci konu koşusu (`.local/second-topic-packet-size-2026-09-20/result.md`) SW15.1'in yazıldığı haliyle genellemediğini gösterdi. "Konu ve ortam arama bloklarına bırakılır" cümlesi modelin aranan şeyin kendisini de atmasına yol açtı: ölçüt ve 40 ifadenin hepsi "packet size"ı kaybetti. Düzeltme yönü: ortam bloklarda kalır, ama aranan şey bir ölçüt parçası olarak kalır. İstem düzeltilir ve 2–3 soruda birkaç model çağrısıyla "aranan şey ölçütte kaldı mı" diye sınanır (bu bir ölçüm kampanyası değil, bilinen bir kusurun düzeltmesidir); sonuç SW15'e ek olarak yazılır, ürün kodu aynı dilimde gelir.
Kabul: tek koşu sonucu hiçbir yerde kullanılmaz; model kapalıysa ölçüt boş kalır ve akış sürer (sıralama konu düzenine düşer).
Düzeltme yapıldı (21 Eylül 2026, `.local/sw-criterion-prompt-fix-2026-09-21/`): yeni istem beş soruda aranan şeyi koruyor, ama kuantum referansında ifadelerin pasaj sıralaması 48'den 37'ye düştü; ifadeleri sıralamada ilk kullanan dilim 11 bu sonuçtan başlar. Ayrıntı: [sw-slice06-criterion-proposal.md](sw-slice06-criterion-proposal.md).

**07 · Kayıt düzeyinde sıralama** — SW7 (tümü), SW8.1–2. Kur. Önkoşul: 02, 04.
Kapsam: soru + dağarcıkla BM25; başlıkta blok kapsaması; atıf grafiği benzerliği (OpenAlex `referenced_works`, bibliyografik eşleşme + doğrudan atıf); yalnızca doğrulanmış ya da kullanıcı tohumlarıyla TF-IDF; RRF (k = 60), eşitlikte kalıcı kimlik; sinyal başına sıra ve "sinyal vardı mı" saklanır; eksik sinyal sonda; referans listesi olmayan kayıt oranı raporlanır; gömme beşinci sinyal ve kurtarma kolu (birleşik ilk 200 dışında, gömme ilk 50 içinde → "gömme kolundan" etiketiyle öne). Mevcut `_source_similarity` yeniden kullanılır.
Kabul: sıra kayıt silmez; gömme kapalıyken dört sinyal değişmeden koşar. Ayrıntı: [sw-slice07-record-ranking.md](sw-slice07-record-ranking.md).

**08 · Protokol onay adımı (arayüz)** — SW2.5–6, SW15.3, SW14.2, SW2.1 (alan). Kur. Önkoşul: 04, 06. Önce [.impeccable.md](../../.impeccable.md).
Kapsam: koşu "onay bekliyor" durumunda durur; dağarcık (her terimin kökeni: soru, veri, model), bloklar, ölçüt, parçalar ve ifadeler tek ekranda gösterilir, düzeltilir, dondurulur; değişiklik gerekçeli yeni protokol revizyonu açar; aynı araştırmada model yeniden sorulmaz; ilk tur zayıfsa ya da kullanıcı isterse model terim listesi önerir (sorgu değil), terimler aynı sayım sınamasından geçer.
Kabul: onaysız hiçbir sağlayıcı isteği çıkmaz (`sw` akışında); Playwright'ta yeni bir durum senaryosu.
Bölündü (21 Eylül 2026): **08a** arka uç ([sw-slice08a-protocol-approval-backend.md](sw-slice08a-protocol-approval-backend.md)); **08b** arayüz ve Playwright ([sw-slice08b-protocol-approval-ui.md](sw-slice08b-protocol-approval-ui.md)); **08c** koşullu model terim önerisi (SW2.5), ayrı yazılacak. Kabul koşulu 08a'da daraltıldı: onaysız hiçbir sağlayıcı **arama** isteği çıkmaz; sayım sınamaları onaydan önce koşar, çünkü ekranın gösterdiği sayılar onlardır.

### Faz C — Tarama omurgası

**09 · Özet taraması v2** — SW9.1–4, SW1.2, SW1.6, SW11.1 ve 11.4 (özet kısmı). Kur. Önkoşul: 02, 04, 05, 07.
Kapsam: kod aşaması (iki blok da yoksa kapsam dışı; başlıkta ikisi de varsa aday; biri eksikse modele); yeni tarama sözleşmesi (tek etiket + özetten birebir alıntı); alıntıyı kod doğrular (boşluk, bitişik harf, satır sonu tiresi normalleştirilir); iki bağımsız koşu; özet aşamasında anlaşmazlık ya da bulunamayan alıntı insana gitmez, kayıt aday sayılır; özetten `include` çıkmaz; sonuç iş düzeyinde birleşir. Ek ürün ve bildirim kayıtları (SW6.2; türü ve ana makale bağlantısını dilim 03 kurar) kod aşamasında kendi neden kodlarıyla adaylıktan çıkar; kayıt gizlenmez, kullanıcı ezebilir.
**Açık karar K3 burada uygulanır** (model çağrı bütçesi).
Kabul: eski `screening` sözleşmesi `legacy` için kalır; `sw` akışında hiçbir kayıt özetle `included` olmaz.

**10 · Arka planda tam metin getirme** — SW10.1–3. Kur. Önkoşul: 03, 07, 09.
Kapsam: yeni koşu türü; iş başına tek getirme, okunan sürüm saklanır; sıra: kullanıcının adlandırdığı ya da yüklediği, sonra birleşik sıraya göre kod adayları, sonra `unresolved`; kaynak sırası: yayıncının açık kopyası, ön baskı (arXiv ikizi; başlık araması onarılır, 406 alıyordu), yazar ya da kurum kopyası; Europe PMC yalnızca tıp ve yaşam bilimlerinde; küçük partiler, kullanıcı bu sırada listeyle çalışabilir; metin gelir gelmez kod çıkarır ve kimliği denetler.
Kabul: D4 sürüm kapısı ve D35 reddedilen bağlantı belleği korunur; metni olmayan iş `unresolved` kalır.
Plan kararları (21 Eylül 2026): getirme ayrı bir koşu türüdür ve `sw` keşif koşusu bitince kendiliğinden kuyruğa girer (işçi tek; SW10.1'in "kod aşamasından hemen sonra"sından sapma); koşu başına 40 / 100 / 300 iş; başka sürümün doğrulanmış kopyası kendi sürüm satırına bağlanır; arXiv başlık araması ve Europe PMC kurulmaz (Europe PMC dilim 14'e). Ayrıntı: [sw-slice10-background-fulltext-fetch.md](sw-slice10-background-fulltext-fetch.md).

**11 · Ölçüt pasajları** — SW12.1–5, SW15.4. Kur. Önkoşul: 06.
Kapsam: elle yazılmış `FORMULATION_TERMS` yerine protokoldeki onaylı ifadelerden derlenen düz desenler; iki ayrı kota (konu pasajları bugünkü gibi; ölçüt pasajları ifade sayımıyla); her kaynak iki listeden de pasaj verir; aynı sıra tam metin modelinin okuyacağı pasajları, kuyruktaki "hayır" satırlarının ipucu cümlelerini ve Marker'a gidecek sayfaları seçer; yeniden sıralayıcı eklenmez; parça boyu 1.400 kalır, ucuzsa küçük geriye örtüşme.
Kabul: ifade listesi boşsa ölçüt pasajları konu düzenine düşer; alıntı doğrulaması sayfa metninde koşmaya devam eder. Ölçülmeyen: iki kotanın 48 pasajlık çok kaynaklı girdideki etkisi; dilim 24 ölçer (§2 kural 7).
Plan kararları (21 Eylül 2026): dilim ölçmez (önceki "dilim bunu ölçer" cümlesi sahibin kararıyla düzeltildi); tek sıra işlevi kurulur ve yalnızca `sw` yanıt koşusunun pasaj seçimine bağlanır, tam metin okuması (dilim 12), kuyruk ipuçları (dilim 16) ve Marker sayfaları aynı işlevi sonra çağırır; `legacy` elle yazılmış listeyi dilim 24'e kadar korur; geriye örtüşme kurulmaz (ucuz değil: ortak pasajlar yeniden kesilir, kimlikleri değişir). Ayrıntı: [sw-slice11-criterion-passages.md](sw-slice11-criterion-passages.md).

**12 · Tam metin kararı** — SW1.1, 1.5–7, SW11.1–5, SW15.5, SW16.1, 16.5. Kur. Önkoşul: 02, 10, 11.
Kapsam: yeni `fulltext_adjudication` sözleşmesi (ölçüt parçası başına etiket + birebir alıntı); alıntı sayfa metninde doğrulanır, sayfa numarası saklanır; iki koşu; kural tablosu → `include` (her parça için doğrulanmış alıntı + sayfa), `criterion_not_met`, `unresolved` (nedenine göre ayrılır); kod kapısı kapalı; ön baskı ve model ailesi etikettir, kuyruk nedeni değildir; `include` → `selections.included`; model yalnızca seçilmiş pasajları görür; bütçe kapı tasarrufu olmadan planlanır.
Kabul: doğrulanamayan alıntıya dayanan `include` kuyruğa gider, dahil edilmez; model kapalıyken her şey `unresolved` bekler.
Plan kararları (22 Eylül 2026): okuma ayrı bir koşu türüdür (`fulltext_adjudication`) ve getirme koşusu bitince kendiliğinden kuyruğa girer; koşu başına 20 / 50 / 150 iş, iş başına iki çağrı; çağrı başına tek iş ve 12 seçilmiş pasaj; `abstract_promise_absent` ve kapı–model çelişkisi kurulmaz (kapı yok, özet aşaması ölçüt parçalarını yargılamıyor); uygulayan Grok 4.7, inceleyen Opus (sahibin kararı). Ayrıntı: [sw-slice12-fulltext-adjudication.md](sw-slice12-fulltext-adjudication.md).

**13 · Uçtan uca duman testi** — Duman. Önkoşul: 01–12.
Tek soruyla (kuantum), `sw` bayrağıyla, gerçek modelle, ayrı veri dizininde, sorudan kaynaklı yanıta kadar bir koşu. Amaç ölçmek değil, omurganın (tarama, tam metin, karar, `selections`, yanıt) ilk kez birleştiği yerde çalıştığını görmektir; bu akış bugüne kadar hiçbir yerde baştan sona koşmadı. Kaydedilenler: koşu bitti mi, nerede durdu, aşama başına sayılar, model çağrısı ve token, süre. Bulunan hata düzeltilir; kalite yargısı verilmez.

### Faz D — Keşif genişliği

**14 · Kaynak yönlendirme** — SW3.1–4, 3.7. **Kur (ölçülmedi).** Önkoşul: 04.
Kapsam: OpenAlex her zaman; alan kaynağı ilk OpenAlex turunun alan dağılımından kodla (IEEE, PubMed, arXiv); Scopus varsayılan kapalı; Semantic Scholar toplu arama ilk turla koşut, kazanç sayılmaz; her kaynak iki sayı raporlar. Alan dağılımı kuralı ölçülmedi; PubMed kolu ilk kez dilim 24'teki mühendislik dışı soruyla denenir (K5).

**15 · Atıf zinciri** — SW4 (tümü), SW3.6. Kur. Önkoşul: 03, 05, 07.
Kapsam: tohumlar kodla (başlıkta blok, sonra BM25), gömme ve konuya özgü başlık kapısı yok; 15–25 tohum, son beş tohum neredeyse hiç yeni iş eklemiyorsa erken durur; iş düzeyinde tekilleştirme; OpenAlex referanslar ve atıf yapanlar; geniş ortam-ya da-görev metin süzgeci; geçen her iş taramaya gider; bağlayan tohum sayısı yalnızca öncelik; kullanıcının adlandırdığı ya da yüklediği makale her zaman tohum; ikinci halka doğrulanmış işlerle, koşullu.

### Faz E — İnsan döngüsü

**16 · İnsan kuyruğu (arka uç)** — SW11.4–7, 11.10–11, 11.13. Kur. Önkoşul: 12.
Kapsam: kuyruğa giriş nedenleri (iki koşu anlaşmazlığı, kapı–model çelişkisi, doğrulanamayan alıntıya dayanan `include`, özetin vaat edip tam metnin içermediği, kanıtsız ölçüt parçası, SW5.4, SW6.6); satır başına tek soru, alıntı, sayfa, sürüm etiketi; "hayır" kararında ipucu cümleleri ve sayfaları; reddedilen alıntının yanında metindeki en yakın pasaj; karar kesindir, geri alınabilir, model o kayıt için bir daha sorulmaz; "emin değilim" ve "bu PDF yanlış ya da eksik"; karar, verildiği kapsam revizyonu ve ölçütle saklanır, ölçüt değişince "eski ölçütle verildi, yeniden bak" işareti; kuyruk birleşik sıraya göre dizilir.

**17 · İnsan kuyruğu (arayüz)** — SW11.6. Kur. Önkoşul: 16. Önce `.impeccable.md`.
Kapsam: kuyruk görünümü; satır seçilince PDF o sayfada açılır; üç sade durum, neden kodu süzgeçte ve açıklamada.

**18 · PDF bekleyenler ve kullanıcının eklediği PDF** — SW10.4–5, SW11.9. Kur. Önkoşul: 10, 12.
Kapsam: sıralı "PDF'inizi bekliyor" listesi; Ayarlar'da kurum vekil adresi, bağlantılar tarayıcıda açılır, toplu otomatik indirme yok; bırakılan dosya DOI ya da başlıkla eşlenir (mevcut `match_pdf_to_source`), hangi iş / sürüm / sayfa sayısı bulunduğu söylenir, eşleşme yoksa sorulur; iş okuma sırasının başına geçer; yanıt üç biçimden biridir; web araması son çaredir, otomatik ekleme yok (D4). Vekil akışı sahibin kurum girişi olmadan denenemez; dilim bunu "ölçülmedi" diye yazar.

### Faz F — Ölçüm ve rapor

**19 · Prob seti, kol ve sinyal tabloları, durma kuralı** — SW13 (tümü), SW1.8, SW7.6, SW8.7. Kur. Önkoşul: 15, 16.
Kapsam: prob seti (doğrulanmış pozitifler; türüyle saklanan negatifler); arama kolu: bulunan pozitif, yalnızca onun bulduğu, dönen satır; sıralama sinyali: aralığıyla katkı, otomatik kapatma yok (anahtar, model çağrısı ya da indirme gerektiren sinyal hariç); kol türüne göre durma; doğrulama gelene kadar geçici rakam, onunla durulmaz; hiçbir kolun bulmadığı problar kimlikle raporlanır.

**20 · Akış sayıları, denetim örneği, ezme sayısı, PRISMA-S dışa aktarımı** — SW11.8, 11.12, 11.13; PRISMA-S kısmı sahibin 20 Eylül 2026 isteğidir, SW belgesinde yoktur. Kur. Önkoşul: 16, 19.
Kapsam: yanıt yalnızca `include` işlere dayanır, kuyruk boşalmadan istenebilir; rapor akış sayılarını yazar; kuyruk dışı kararlardan küçük denetim örneği; kişinin kodu ya da modeli kaç kez ezdiği.
PRISMA-S dışa aktarımı: arama raporlaması için 16 maddelik PRISMA-S kontrol listesine eşlenmiş bir döküm (Markdown ve JSON), yalnızca saklı kayıtlardan üretilir, yeni istek ya da model çağrısı yapmaz. Kaynaklar: protokol kaydı (dilim 01: veritabanları, tam sorgu metinleri, sınırlar, eşikler, tarih), `search_runs` (kaynak başına istek, dönen ve toplam kayıt, başarısız aramalar), tekilleştirme kuralı ve sayıları (03), atıf zinciri kolu (15), model terim önerisi ve kullanıcı düzeltmeleri (08), akış sayıları. Karşılığı olmayan madde "uygulanmadı" ya da "kaydedilmedi" diye yazılır, boş bırakılmaz ve doldurulmuş gibi gösterilmez. Başlangıç noktası `scripts/isolated_hybrid_search.py` içindeki döküm (`:402-425`) ve [prisma-s-design-review-2026-09-18.md](prisma-s-design-review-2026-09-18.md)'deki bulgulardır; o betik ürün kodu değildir, kopyalanmaz, yeniden yazılır.
Kabul: dökümün her satırı bir saklı kayda izlenebilir; döküm "PRISMA uyumlu derleme" demez. Taramayı kod ve model yaptığı için PRISMA 2020 akışı `incomplete_no_human_screening` olarak işaretlenir (insan yalnızca kuyruktaki kayıtlara bakar); metin yalnızca "arama PRISMA-S maddelerine göre raporlandı" der.
Ölçülmeyen: dökümün bir dergi ya da kütüphaneci gözüyle yeterli olup olmadığı; dışarıdan doğrulanmadı.

### Faz G — Bağımsız dilimler (01'den sonra her an)

**21 · Yerleşik yerel gömme** — SW8.3–6. Kur. Önkoşul: 01.
Kapsam: `fastembed` + `BAAI/bge-small-en-v1.5`; Ayarlar → Semantic search'te sıra: Gemini (ücretsiz anahtar, nasıl alınır), "This computer · built-in", kapalı; onayla tek seferlik indirme, boyut gösterilir; yalnızca İngilizce, soru İngilizce değilse İngilizce cümle istenir (model bir kez önerebilir, kullanıcı onaylar, kapsam revizyonuyla saklanır); ücretsiz anahtarda Google'ın metni kullanabileceği uyarısı; HTTP 429'da bekle ve yeniden dene. Ölçülmeyen: `onnxruntime`'ın masaüstü paketinde davranışı; pasaj düzeyinde yerel modelle erişim.

**22 · arXiv LaTeX kaynağından okuma** — SW10.6–8. **Kur (ölçülmedi).** Önkoşul: 10.
Kapsam: kaynak indirme, makro açma, düzen komutlarını atma, sürüm kaydı; denklem ancak PDF sayfasına eşlenirse alıntılanır (numara metin katmanında bulunur, eşleme metin benzerliğiyle, sayarak değil); güvenilmezse o sayfa Marker'la okunur. Benzerlik eşlemesi hiç kurulmadı ve ölçülmedi; güvenilmez eşlemede Marker'a düşme kuralı bu yüzden zorunludur.

**23 · Kullanıcının onayladığı kod kapısı** — SW15.6, SW16.2–4. Kur, isteğe bağlı. Önkoşul: 16, 20.
Kapsam: kural kendiliğinden öğrenilmez ve açılmaz; kullanıcı kuralı görür ve onaylar; kural, yazımında kullanılmayan doğrulanmış kayıtlarda hiçbir kapsam içi negatifi kapatmamış olmalıdır; kural, sınandığı kayıtlar ve onay protokol revizyonuyla saklanır; kapının kapattığı işler denetim örneğine girer, tek yanlış kapatma kapıyı o araştırma için kapatır. Kapının hiç açılmaması olağan sonuçtur; bu dilim yapılmadan da akış tamdır.

### Faz H — Geçiş

**24 · Ölçüm kampanyası, varsayılanı değiştir ve kapat** — Ölç. Önkoşul: diğer bütün dilimler (23 hariç).
Kampanya üç parçadır: (a) kuantum sorusu yeniden, bu kez ürünün `sw` akışıyla, mevcut prob setine karşı; (b) sahibin seçeceği yeni bir soru, tercihen mühendislik dışından (tıp ya da yaşam bilimi), böylece PubMed ve Europe PMC kolları da denenir; (c) aynı sorular için sahibin vereceği Elicit raporlarıyla karşılaştırma: onların bulup bizim bulamadığımız, bizim bulup onların bulamadığı, ikisinin de dahil ettiği işler. Elicit doğruluk ölçütü değildir; karşılaştırma neyi kaçırdığımızı gösterir, kimin haklı olduğunu değil, ve prob setimizin kendi koşularımızdan türemiş olmasının yanlılığını (SW3 Limits) ilk kez dışarıdan sınar. Beklentiler koşudan önce dondurulur. Ölçülenler: "Kur (ölçülmedi)" diye giren her parça (04, 06, 14, 22), elle seçilmiş eşikler, K3'ün N değeri, SW10'un "açık erişimlide özet önerisini atla" fikri, toplam model maliyeti ve süre, kuyruk boyu.
Sonuç sahibe gösterilir; değişmesi gereken eşik ve kurallar yeni SW girişleri olarak yazılır ve ilgili dilime dönülür. Varsayılanın `sw` olması bu sonuca bağlıdır. Sonra: README, [CLAUDE.md](../../CLAUDE.md), `docs/README.md`, `implementation-plan.md` §9; kalan SW maddeleri için `D` girişleri; `legacy` yolunun ne zaman kaldırılacağı ayrı karar.

## 4. SW maddesi → dilim

| SW | Dilim | | SW | Dilim |
|---|---|---|---|---|
| SW1.1, 1.5–7 | 12 | | SW9.1–4 | 09 (9.3 ayrıca 05) |
| SW1.2 | 09 | | SW9.5 | 02 |
| SW1.3 | 04 | | SW10.1–3 | 10 |
| SW1.4 | 07 | | SW10.4–5 | 18 |
| SW1.8 | 19 | | SW10.6–8 | 22 |
| SW2.1–4, 2.7 | 04 | | SW11.1–5 | 02, 09, 12 |
| SW2.5–6 | 08 (2.5'i SW17 daraltır) | | SW11.4–7, 10, 11, 13 | 16, 17 |
| SW3.1–4, 3.7 | 14 | | SW11.8, 12, 13 | 20 (+ PRISMA-S dökümü, SW dışı) |
| SW3.5 | 04 | | SW11.9 | 18 |
| SW3.6 | 15 | | SW12 | 11 |
| SW4 | 15 | | SW13 | 19 (13.6: kurulacak bir şey yok) |
| SW5 | 05 | | SW14 | 01 (14.2 arayüzü 08) |
| SW6.1–3, 5–9 | 03 | | SW15.1, 2, 7 | 06 |
| SW6.4 | 05 | | SW15.3 | 08 |
| SW7 | 07 | | SW15.4 | 11 |
| SW8.1–2 | 07 | | SW15.5 | 12 |
| SW8.3–6 | 21 | | SW15.6, SW16.2–4 | 23 |
| SW8.7 | 19 | | SW16.1, 16.5 | 12 |
| SW17 | 04d | | | |

## 5. Sahibin vermesi gereken kararlar

Her biri için öneri yazılıdır; karar gelene kadar dilim 01 bunlardan etkilenmez.

- **K1 — Birlikte yaşama.** Öneri: §2.1'deki araştırma başına bayrak. *Bedeli:* dilim 24'e kadar iki yol birlikte bakılır. *Seçenek:* eski yolu yerinde değiştirmek; her dilim canlı kütüphaneyi etkiler.
- **K2 — `selections` ile ilişki.** Öneri: §2.2; `sw` akışında özet adayı `pending` kalır, yalnızca tam metin `include` kararı `included` yazar, yeni köken değeri `code_rule`. *Sonuç:* `sw` akışında tam metin aşaması en az bir işi dahil etmeden yanıt koşusu başlamaz. Yalnızca ekli PDF'le çalışan araştırmalar (`source_scope = attached`) bu akışa girmez.
- **K3 — Özet aşamasında model çağrı bütçesi.** Bugünkü bütçe 15–20 model çağrısıdır; SW9 tek turda yaklaşık 1.900 çağrı ölçtü. Öneri: model önerisi yalnızca birleşik sıranın başındaki N kayıt için (efora göre 60 / 150 / 300), gerisi "okunmadı" nedeniyle `unresolved`; SW10'un "açık erişimlide özeti atla" fikri dilim 24'te ölçülür. *Ölçülmeyen:* N'nin kaç pozitif kaybettirdiği. **Karar (21 Eylül 2026):** N = 40 / 100 / 300, çağrı başına 20 kayıt, iki koşu, eşzamanlı gönderim; okunmayan kayıt `abstract_not_read` ile kalır ve sonraki keşif koşusu kaldığı yerden okur. Tek konuda, modele bağlı 13 bilinen pozitifin 6'sı ilk 100'de, 11'i ilk 300'de okunuyor ([sw-slice09-abstract-screening.md](sw-slice09-abstract-screening.md)).
- **K4 — Ölçüm modeli.** Öneri: `deepseek-flash`, efor `high`. Luna kotası dönerse dilim 13 ve 24 Luna ile tekrarlanır.
- **K5 — Yeni soru.** Dilim 24 kampanyasında sahip seçer. Öneri: tıp ya da yaşam biliminden; yoksa PubMed ve Europe PMC kolları hiç denenmemiş olarak varsayılan olur.

## 6. Bir tur nasıl koşulur

1. **Dilim dosyası ve prompt.** Plan sohbetinde dilimden hemen önce yazılır: `docs/product/sw-sliceNN-<ad>.md` ve `sw-sliceNN-prompt.md`.
2. **Uygulama.** Yeni sohbet, Opus, efor medium. Her dilimin kendi promptu vardır (`docs/product/sw-sliceNN-prompt.md`: kurallar, önce okunacaklar, yordam, son ileti). İlk ileti yalnızca `docs/product/sw-sliceNN-prompt.md dosyasını uygula.` olur.
3. **İnceleme.** Ayrı yeni sohbet (Fable · high; uygulayandan farklı model). Ağırlığı dilime göre değişir: **tam** (dilim biter bitmez, tek başına: 02, 03, 05, 09, 12, 16, açılırsa 23) ya da **toplu** (iki üç dilim birlikte, doğal bir durakta; üst üste kurulan omurga dilimleri biriktirilmez). Hangi dilimin hangisi olduğu, kurallar ve **yapılan incelemelerin kaydı** [sw-status.md](sw-status.md)'dedir. Bulgular ayrı bir düzeltme commit'iyle işlenir ve itilir; dilim ancak o zaman `kapandı` olur.
4. Ölçüm için durulmaz (§2.7); "Kur (ölçülmedi)" dilimleri de tek turdur.

Dilim boyu 300K bağlam sınırına göre değil, "tek oturumda testler yeşil biter" ölçüsüne göre seçildi; hedef kullanım 100–150K'dır, böylece uygulayan sohbet özetlemeye girmeden biter. Bir dilim bunu aşacak gibi görünürse sohbet durur, kalan iş `sw-status.md`'ye yazılır ve dilim ikiye bölünür.

## 7. Ayrıntılı dilim dosyaları neden baştan yazılmadı

Dilim 02 ve sonrası, önceki dilimin gerçekten indirdiği şemaya (tablo ve sütun adları, işlev imzaları) ve K1–K3 kararlarına dayanır; 13'ten sonrası duman testinde çıkanlara dayanır. Hepsini bugün satır düzeyinde yazmak, ilk sapmada eskiyen 20 belge üretir. Bu yüzden her dilimin kapsamı ve kabul koşulu burada sabittir; satır düzeyindeki dosya bir dilim önden yazılır. Dilim 01'in dosyası hazırdır.

## 8. Bu planın ölçmediği ve bilmediği

- Dilim boyları tahmindir; hiçbiri denenmedi. 04, 09 ve 12 bölünmeye en yakın olanlardır.
- SW kararlarının çoğu tek konu, tek model ve insan onayı olmayan etiketlerle ölçüldü; plan bunu düzeltmez, yalnızca ikinci konuyu zorunlu kılar.
- KAA konusunda örneklenen 60 işin yalnızca 8'inin açık erişimli PDF'i vardı (IEEE ağırlıklı alan). Dilim 24 kampanyasının KAA gibi kapalı erişimli bir alanda anlamlı olması için sahibin kurum erişimiyle yaklaşık 40 tam metin sağlaması gerekir; yoksa o konuda yalnızca yön ölçülür.
- `sw` akışının toplam model maliyeti bilinmiyor (SW16 "ölçülmedi" diyor); ilk kaba rakam dilim 13'ten, gerçek rakam dilim 24'ten gelir.
- Ölçümü sona bırakmanın bedeli: elle seçilmiş eşikler ve hiç ölçülmemiş SW2 koda geçici olarak girer; kampanyadan sonra bazı dilimlere geri dönülmesi beklenir.
- Rapor yolu (`workflow/report/selection.py`) kendi pasaj seçimini kullanır; bu plan ona dokunmaz. Ölçüt pasajlarının rapora girip girmeyeceği açık sorudur.
- Kanıt tablosu (P5) dahil edilen kaynaklardan başlar; K2 sonrası davranışı ayrıca denenmedi.
