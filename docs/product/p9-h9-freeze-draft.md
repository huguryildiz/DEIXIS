# P9 H9: rapor ölçümü için dondurma taslağı

**Tarih:** 3 Ekim 2026. **Durum:** TASLAK; DONDU değil, H9 başlamadı. Hazırlama ağacı: `a4deebfd511993335dda4992e6e39151f40e3644`. Bu dosya sahip kararlarını ve sonraki dondurma işlemini hazırlıyor; gerçek model çağrısına izin vermiyor. H8 başka batch'te sürüyor bilgisi bu görevin başlangıç koşuludur. Bu ağacın planında D168 kapanış kaydı bulunsa da buradan H8'in güncel kapanışını veya inceleme borcunun kapandığını çıkarmıyoruz.

**Dayanak:** [P9 planı](p9-hardening-plan.md) §5 H9, §6 bağımlılık satırı, §7 H9 kuralları 1-7, §4 R01 ve §9 S2/S10; [D124, D126, D128, D129 ve D141](../decisions.md); [ilk beklentiler](p6-slice1-report-expectations.md), [ek 1](p6-slice1-report-expectations-addendum.md), [ek 2](p6-slice1-report-expectations-addendum-2.md) ve [ilk](p6-slice1-report-results.md), [ikinci](p6-slice1-report-results-run2.md), [üçüncü](p6-slice1-report-results-run3.md) sonuçlar. Yürütme istemi: [p9-h9-prompt-draft.md](p9-h9-prompt-draft.md).

## 0. Tek sahip onayı ve iki dondurma noktası

Planın §7 kural 1'i konu ve hazırlık kurallarını keşiften önce; kural 4'ü gerçekleşmiş tabloyu, çiftleri ve okuyucuları ilk rapor isteğinden önce dondurur. Henüz keşif yapılmadığından kaynak kimlikleri ve tablo hash'i bugün yazılamaz.

1. Sahip aşağıdaki K01-K12 alanlarını tek karar kaydında kapatır. H8 kapanışı ayrıca kanıtıyla kaydedilir. Seçimlerin açıklanmış varsayılanları kabul edilebilir; sessizlik kabul değildir.
2. Sahip veya yetkilendirdiği ana oturum, planın adlandırdığı `docs/product/p9r-report-freeze.md` dosyasına onaylı kuralları geçirir. Keşif öncesi dondurma commit'i ve `gpt-6.1-sol` incelemesi kaydedilmeden hazırlık başlamaz. Bu görev o dosyayı oluşturmaz, commit atmaz, inceleme çağrısı yapmaz.
3. Onaylı, sınırlı hazırlık gerçekleşirse kaynak kümesi, tablo ve R9 çiftlerinin kimlik/hash ekleri aynı nihai dondurma belgesine girer. İlk rapor isteğinden önce ikinci belge commit'i ve güncel ekleri kapsayan `gpt-6.1-sol` incelemesi kaydedilir. İlk kurallar değişmez. İnceleme sonucunun gerektirdiği kural değişikliği otomatik yetki değildir.
4. Sahip onayı, bu iki kapı geçince istemdeki tek koşuyu yürütme yetkisini de açıkça içerirse yeni bir rutin izin sorusu gerekmez. Açık seçim, kapanış veya inceleme eksikse yürütücü durur. Onay kapsamını aşan yeni model, konu, bütçe ya da canlı veri kullanımı ayrı sahip kararı ister.

İki belge commit'i bu taslağın önerdiği uygulama düzenidir; plan commit sayısını belirtmez. Böylece keşiften önce dondurulabilecek kurallar ile ancak hazırlıktan sonra oluşan kayıtlar ayrılır. Son dondurma commit'inin ürün commit'inden farkı yalnız izin verilen ölçüm belgeleri olur.

## 1. Konu, seçim ve hazırlık kuralları (plan §7, kural 1)

### 1.1 Aday sorular

Aşağıdakiler arama yapılmadan hazırlanmış adaylardır. Bugünkü kodun konuya özgü terimlerden sorgu kurması, özet taraması, tam metin getirmesi/okuması ve insan kuyruğu bulunması önerileri gerekçelendirir (`CLAUDE.md`, D96/D97). Her adayın gerçekten yeterli metinli kaynak getireceği bilinmiyor; açık PDF sayısı veya literatür büyüklüğü doğrulanmış gibi yazılmaz.

| Aday / alan | Dondurulabilecek soru metni | Bugünkü keşif akışı için gerekçe ve risk |
|---|---|---|
| Q1 / elektrik enerjisi sistemleri, önerilen ilk seçim | Elektrikli araçların şarj zamanlaması için hangi matematiksel optimizasyon modelleri önerilmiştir? Karar değişkenlerini, amaç fonksiyonlarını, şarj ve şebeke kısıtlarını, belirsizliğin ele alınışını ve raporlanan değerlendirme koşullarını karşılaştırın. | `electric vehicle charging scheduling` ve `optimization` gibi konuya bağlı terimler bir genel alan adı yerine somut bir görevi tarif eder. Değişken/amaç/kısıt sütunları aynı tür kayıtları karşılaştırabilir. Bu bir tasarım çıkarımıdır; şebeke modeli, batarya modeli ve fiyat tahmini gibi komşu konular taramada dışlanmalıdır. PDF erişimi ve otomatik dahil etme verimi bilinmiyor. |
| Q2 / robotik ve kontrol | Mobil robotların engelden kaçınan yörünge planlamasında model öngörülü kontrol nasıl formüle edilmiştir? Dinamik modeli, karar değişkenlerini, amaç fonksiyonunu, engel ve hareket kısıtlarını ve değerlendirme koşullarını karşılaştırın. | `mobile robot`, `obstacle avoidance`, `model predictive control` belirgin görev/yöntem terimleridir. Bu özgüllük özet üzerinden konu sınırını değerlendirmeyi kolaylaştırabilir; denklem sütunu ancak getirilen metinde görülen formülasyonu alır. Otonom otomobil ve genel yol planlama sonuçları karışabilir; donmuş kapsam bunları ayırmalıdır. Yeterli açık tam metin henüz doğrulanmadı. |
| Q3 / su dağıtım sistemleri | Su dağıtım ağlarında pompa zamanlaması için hangi optimizasyon modelleri kullanılmıştır? Karar değişkenlerini, enerji maliyeti amacını, hidrolik ve depo kısıtlarını, talep belirsizliğini ve değerlendirme koşullarını karşılaştırın. | `water distribution pump scheduling` somut bir sistem ve karar problemini adlandırır; genel `operations research` sorgusuna dayanmayı gerektirmez. Formülasyon eksenleri rapor sütunlarına uygundur. Pompa tasarımı ve bakım çalışmalarının dışlanması gerekir. Özetlerin ayrıntı düzeyi ve açık PDF erişimi bilinmiyor. |

**D141 uyarısı:** NLP sorusunun varsayılan `sw` keşfi 99 tekil işten 1'ini dahil etti, 29'unu dışladı, 69'unu beklemede bıraktı; 25'i PDF bekleyen inceleme kuyruğundaydı. Bulunan işler dahil edilmiş işler değildir. Bu tek gözlem bir genel başarısızlık oranı vermez, fakat soru seçiminin tek başına rapora hazır korpus sağlayacağını varsaymayı engeller. H9 hazırlığı bu nedenle aşağıdaki sınırlı kuyruk adımını önceden tanımlar; başarılı sonuç görünene kadar konu değiştirmez.

### 1.2 Dahil etme, dışlama ve sıralama

Önerilen kural K03 ile onaylanır. Araştırma yeni, boş, izole veri dizininde `sw` olarak açılır; eski araştırma kopyalanmaz. `source_scope=academic`, `seed_mode=question_only`, keşif eforu `standard`, dil `tr`; protokol `ask` kartının önerisi değiştirilmeden onaylanır. Ürünün etkin tam metin getirme/okuma ve zincirleme ayarları keşif öncesi protokole yazılır; varsayılan dışında bir yol sessizce seçilmez.

1. Seçilen sorunun görevine doğrudan uygulanan, kendi modelini/yöntemini ve değerlendirmesini sunan çalışmalar uygundur. Genel derlemeler, yalnız atıf listesinden gelen adaylar, ilgisiz uygulamalar ve salt metaveri kayıtları tabloya alınmaz. Soyut düzeyde görülen ayrıntı tam metin ayrıntısı gibi yazılmaz.
2. Otomatik keşif/getirme/okuma bittikten sonra, her hazırlık denemesinde bir kuyruk inceleme geçişi yapılabilir: en çok 30 henüz karara bağlanmamış iş, normalize başlık sonra eser kimliği sırasıyla. K03 varsayılanında kararı sahip verir. Saklı metin soru kapsamını doğrudan karşılıyorsa ürünün mevcut seçim yoluyla dahil edilir; gerekçe, karar veren, okuyan ve okuma derinliği kaydedilir. K03 ayrıca modelin karar vermesini açıkça onaylarsa bu kararlar insan kararlarından ayrı sayılır; sonuç, D96/D101 gereği ürünün bu satırlar için sakladığı "person"/insan etiketinin yanlış olduğunu belirtir. Bu satırlar insan doğrulaması veya kişinin doğruladığı probe kayıtları diye okunmaz. PDF bekleyen ama metni olmayan satır dahil edilmez. Otomatik dışlamalar yalnız sayıyı artırmak için tersine çevrilmez.
3. Uygun metinli işler arasından tam metni saklı olanlar önce, sonra özet metni saklı olanlar; her grupta yıl artan, normalize başlık, eser kimliği sırasıyla en çok 10 ayrı eser alınır. Aynı eserin sürümleri tek eser sayılır; kullanılan sürüm ayrıca kaydedilir. Seçilmeyen uygun işler ve nedenleri de korunur. Hedef 10, asgari 6 metinli kaynak önerilir; en az 3 saklı tam metin hedefi R6/R9'u mümkün kılmak içindir, gerçekleşmemesi bu iki satırı ölçülemedi bırakabilir. Asgari 6, planın getirmediği ek bir tasarım tercihidir; temsil gücü garantisi değildir.
4. İlk tablo doldurması bir hazırlık denemesine dahildir. İkinci ve son deneme yalnız hazırlık tamamlanmadığında veya tablo hazır olmadığında açılabilir: aynı izole veri dizininde yeni bir `sw` araştırması açılır; aynı soru, sütunlar, seçim sırası ve onaylı ayarlar kullanılır. İlk denemenin bütün kayıtları korunur. Başarısız doldurma satırları dışlanıp sıradaki uygun metinli işlerle değiştirilebilir; değişim nedeni ve önce/sonra kümeleri yazılır. Başarısızlığı veya kaynağı silmek, hücreyi elle tamamlamak, farklı soruya geçmek yoktur. Kota/yük duruşundan sonraki yeni deneme §5 koşullarına da bağlıdır. İkinci denemede de hazır değilse sonuç `korpus hazırlanamadı` olur. Sayaçlar sıfırlanmaz.
5. Bu taslakta sahip PDF tohumu, DOI'den harici avlama, tarayıcıdan PDF edinme veya canlı kütüphaneden kopyalama önerilmiyor. Bu yollar mevcut yetkiye sonradan eklenmez. Kapsam içi sağlayıcı/API hataları ayrı kaydedilir; web aramasıyla telafi edilmez.

### 1.3 Tablo sütunları, keşiften önce donacak metin

Yedi sütunun tamamı `answer_format=text`. K03 bunları kelimesi kelimesine onaylar; modelle sütun önerisi istenmez. D124'te ilk iki sütun çoklu seçimli `choice` idi. H9'da yeni alanların çalışma ortamı ve yöntem ayrıntılarını eski seçeneklere zorlamamak için bu ikisi de `text` önerilir; format değişimi kontrollü karşılaştırmayı sınırlar ve K03 ile keşiften önce donar. D124'ün konuya özgü WSN sütunları yeni alanlara taşınmadığından aşağıdaki içerik uyarlaması gerekir; ölçütlerin sayısal eşikleri değişmez. R9 çiftleri `Denklem` sütunundan §4.4 kuralıyla çıkarılır; kit bir sütunu bu adla tanımaz.

| Sütun | Yönerge |
|---|---|
| Sistem ve çalışma ortamı | Kaynağın ele aldığı sistemi, uygulama kapsamını ve çalışma ortamını yalnız verilen metne dayanarak kaydedin; belirtilmeyen ayrıntıyı açıkça belirtin. |
| Yöntem | Kaynağın kullandığı modelleme, çözüm veya kontrol yöntemini ve analitik, simülasyon ya da deney değerlendirmesini kaydedin; belirtilmemişse bunu yazın. |
| Karar değişkenleri | Kaynakta seçilen veya optimize edilen değişkenleri ve verilen anlamlarını kaydedin; metinde verilmemişse bunu belirtin. |
| Amaç fonksiyonu | Kaynakta açıkça verilen amaç fonksiyonunu veya değerlendirilen hedefi kaydedin; birden fazla amaç varsa hepsini yazın; açıkça verilmemişse bunu belirtin. |
| Denklem | Verilen metinde görüntülenen ana optimizasyon veya kontrol formülasyonunu LaTeX ile aktarın; verilmiş değişken, amaç ve kısıt parçalarını koruyun; görüntülenen denklem yoksa bunu belirtin; eksik parçayı tamamlamayın. |
| Kısıtlar ve belirsizlik varsayımları | Metinde verilen sistem kısıtlarını ve belirsizliğin nasıl ele alındığını kaydedin; görülmeyen varsayımı eklemeyin. |
| Değerlendirme ve sonuç | Açıkça raporlanan değerlendirme koşullarını, karşılaştırma yöntemini ve başlıca sonucu kaydedin; sayı veya karşılaştırma belirtilmemişse bunu yazın. |

## 2. Korpus bağımsızlığı (plan §7, kural 2)

Depo belgelerinden çıkarılan dışlama envanteri aşağıdadır. Bu konu listesi kimlik düzeyinde tam bir eski-korpus manifesti değildir.

| Dışlanan konu/korpus | Depodaki dayanak |
|---|---|
| Kablosuz/su altı sensör ağları, veri paketi boyutu; `res_IXBsnzhYZsKByEdTpSJo`, `res_jAMb1nXLwfrRdC3D8Miq`; Kurt 2017 kaynakları ve önceki WSN geliştirme kaynakları | D124-D129; P16 beklenti/sonuç dosyaları; [L9 beklentilerinin dışlama listesi](p6-slice2-expectations.md) |
| SW izi: kuantum ağlarında uçtan uca dolanıklık dağıtımının matematiksel optimizasyonu | [SW ölçüm protokolü](sw-slice24-measurement-campaign.md), Sorular q1; plan §7 kural 2 |
| SW izi: fazla kilolu/obez yetişkinlerde zaman kısıtlı beslenme ve vücut ağırlığı, randomize çalışmalar | Aynı protokol, q-tre; [SW sonuçları](sw-slice24-results.md), [son tıp ölçümü](sw-slice30-results.md) |
| Moleküler haberleşmede yöneylem araştırması/optimizasyon, beş satırlık alternatif tablo | P16 beklentileri, yol A; D57'nin `res_ZQM2gRxSIqCj6hnTj58q` geliştirme kaydı (`decisions.md`) |
| NLP'de önceden eğitilmiş dil temsillerinin gelişimi, ELMo/BERT/ALBERT/RoBERTa zinciri | D141; [L9 beklentileri](p6-slice2-expectations.md) ve [sonuçları](p6-slice2-results.md). D124-D129 dışına eklenmiştir: artık gözlenmiş ve yanmış korpustur. |

Yürütücü onaydan sonra, keşiften önce yalnız depo belgelerini ve sahibi tarafından bu iş için ayrıca sağlanmış izole eski manifestleri tarayarak envanteri tamamlar; canlı kütüphaneyi okumaz. Eski korpusların her kaynak/sürümü için normalize DOI (`doi`, `published_doi`, `linked_doi` dahil; URL öneki temizlenmiş, küçük harf), sağlayıcı/eser kimliği, arXiv sürüm ilişkisi ve diğer kayıtlı sürüm bağları, yüklenmiş dosyanın SHA-256 değeri ayrı tutulur. Yalnız başlık benzerliği kimlik doğrulaması sayılmaz.

İlk rapor isteğinden önce yeni korpusun bütün dahil kaynakları ve bunların kayıtlı sürüm ilişkileri bu envanterle kesiştirilir. Boş kesişim, ancak karşılaştırma envanterinin kapsadığı kimlikler için `bağımsız (kimlik düzeyinde)` sonucudur. Bir kaynağın DOI'si yok ve başka kimliği/sürüm ilişkisi de doğrulanamıyorsa o kaynak `bağımsızlık doğrulanmadı` alır. Eski korpusların tam kimlikleri veya yüklenmiş dosya hash'leri erişilebilir değilse ilgili boyutun denetlenmediği yazılır; yalnız konu farklı diye tüm bağımsızlık doğrulandı denmez. Önerilen güvenli başlangıç: eksik eski envanter tamamlanmadan hazırlık açılmaz (K03); sahibin bağımsızlık sınırıyla ilerleme seçimi varsa nihai sonuçta açıkça korunur.

Kesişimli kaynak rapor korpusuna giremez. Hazırlık tavanı içinde kurala uygun değişim yapılırsa kayda girer; eski gözlemler silinmez. Yeni korpus ilk gözlemden sonra yanmış sayılır; aynı kümenin ikinci rapor ölçümü bağımsız ölçüm olarak sunulamaz.

## 3. Rapora hazır tablo kapısı (plan §7, kural 3)

Tabloda 6-10 ayrı eser, yedi etkin sütun ve her satırda saklı metin bulunmalı; ürünün `report_ready.ready` değeri `true` olmalı, eksik/başarısız hücre kalmamalıdır. `continue_with_failed` kullanılmaz. Metni olması doldurmanın başarılı olacağını kanıtlamaz. `not_found_in_inspected_scope` kaynakta genel yokluk demek değildir; `inaccessible` veya başarısız hücreyi kabul edilebilir kanıta çevirmeyin. Metinli satır, bulundu/tekil/tarandı/dahil/incelendi/modele verildi/atıf yapıldı sayımlarını birleştirmeye izin vermez.

Kapı geçmez ve hazırlık hakkı kalmazsa rapor POST'u yapılmaz: `başlatılan rapor=0`, R1-R11 ve P19 `ölçülmedi: rapor başlamadı`, okur yok. D124'teki gibi 0/1 tamamlanma yazılmaz; payda hiç oluşmamıştır.

## 4. Rapor öncesi dondurma (plan §7, kural 4)

### 4.1 Açık sahip kararları

Her boş seçim açıkça **SAHİP KARARI**dır. Öneri karar değildir. K01-K12 birlikte tek onay kaydında kapatılabilir; hazırlıktan türeyen kimlikler aşağıdaki ayrı kayıt tablosuna girer.

| Alan | Açık slot | Önerilen varsayılan ve gerekçe |
|---|---|---|
| K01 / yürütme yetkisi | SAHİP KARARI: H8 kapanışı ve incelemelerden sonra H9 hazırlığını ve tek rapor koşusunu açıkça yetkilendir | Şimdi yalnız taslak; kapanış ve dondurma incelemesi olmadan başlatma. H8'in güncel kapanış kanıtı aynı onay kaydına bağlanır. |
| K02 / konu | SAHİP KARARI: Q1, Q2, Q3 veya sahibin kendi alanından §2 dışlama listesi dışında bir soru; değişmez soru metni | Plan S10 sahibin kendi alanından seçim yapmasına da izin verir. Q1 aday varsayılanıdır; görev, değişken, amaç ve kısıt eksenleri açık. Sağlayıcı verimi doğrulanmadı. İkinci hazırlık farklı konuya geçmez. |
| K03 / korpus ve sütunlar | SAHİP KARARI: §1.2, §1.3 ve §2'nin seçim, kuyruk, bağımsızlık ve sütun kuralları; kuyruk kararını veren | Yazıldığı gibi; en çok 10, asgari 6 metinli eser, sahip kararlı bir sınırlı kuyruk geçişi; kimlik envanteri eksikse bekle. Model kararı ayrıca açık onay ve yanlış insan etiketi açıklaması ister. Bunlar seçilim yaratır; varsayılan keşfin otomatik verimiyle karıştırılmaz. |
| K04 / hazırlık bütçesi | SAHİP KARARI: birleşik oturum/süre tavanı, doldurma tavanı ve deneme sayısı | Toplam en çok 2 keşif+doldurma denemesi; ikisi birlikte 300 uygulama model oturumu / 240 dk; her doldurma en çok 60 oturum / 60 dk, birleşik tavana dahil. Kuyruk, PDF ve 10 dk timeout beklemesi süreye dahil; kota beklemesinde saat durdurulmaz. 300/240 planın sayısal şartı değildir; L9'un ölçeğine dayanan muhafazakâr öneridir. |
| K05 / bağlantı, model ve sunucu ortamı | SAHİP KARARI: hazırlık ve rapor bağlantı/modeli, aşağıdaki sunucu ortamının kesin değerleri, Codex oturum kaynağı, sağlayıcı anahtarlarının kaynağı ve kesin `serve` komutu | `codex` / `gpt-5.6-luna`; plan §7 kural 4 ve S10, D124-D128 ile aynı. Varsayılan: sahibin önceden hazırladığı, canlı dizinden ayrı ve oturum açılmış Codex home. Yalnız canlı `codex-home` için açık sahip istisnası alternatif olabilir; otomatik yetki değildir. Kota/yük hazırlıkta §5 ile, raporda durma kuralıyla ele alınır; sessiz alternatif yok. |
| K06 / efor | SAHİP KARARI: model reasoning effort ve keşif effort | Model `medium`; keşif `standard`. Bunlar ayrı ayarlardır. Rapor modeliyle birlikte kaydedilir. |
| K07 / rapor bütçesi | SAHİP KARARI: oturum/süre üst sınırı | 60 uygulama model oturumu / POST'tan itibaren 90 dk, bekleme dahil; tek rapor koşusu. Plan ve D128 ile aynı. Ürünün 50 çağrılık tabanı izleme sınırıyla karıştırılmaz. |
| K08 / durdurma | SAHİP KARARI: §5'in kök neden, tek sürdürme ve sabitleme kuralı | Yazıldığı gibi; yalnız bütün kök nedenler `client_timeout` ise aynı koşuya 10 dk sonra bir sürdürme; başka/karışık neden, ikinci timeout, sayaç hatası veya tavan dolması durdurur. |
| K09 / okurlar ve örnekleme | SAHİP KARARI: ilk ve ikinci okurun kimliği, türü, kesin model/efor varsa, tohum ve okunamadı kuralı | D124 düzeni: ilk okur yürütücü analist (model, kör değil); ikinci okur ayrı ve kör Claude Sonnet oturumu. Kesin Sonnet model kimliği/eforu onayda adlandırılmalıdır; bir aile adıyla çağrı başlatılmaz. Her ikisi kayıtlı model değerlendirmesi. Tohum `20261003`; §4.3 okunamadı kuralı. |
| K10 / okuma bütçesi | SAHİP KARARI: rapor dışı okur çağrılarının tavanı | En çok 4 ayrı okur model isteği / toplam 60 dk; uygulama oturumlarına katılmaz, ayrı defterde sayılır. Eksik okuma varsa tavan artırılmaz, ilgili satır ölçülemedi kalır. Böylece hazırlık+rapor için 360 uygulama oturumu, ayrıca en çok 4 okur isteği yetkilendirilir; toplam parasal maliyet bilinmez. |
| K11 / ürün | SAHİP KARARI: H8 kapanışı sonrası ölçülecek ürün commit'i | H8'in kabul edilmiş kapanışını ve gerekli düzeltmelerini içeren sabit commit. `a4deebf` yalnız taslak dayanağıdır, otomatik nihai seçim değildir. Yeni commit seçilirse hash'ler yeniden hesaplanır. |
| K12 / belge commit'i ve inceleme | SAHİP KARARI: belge commit'lerini kimin atacağı, inceleme bütçesi | Sahip/ana oturum atar; yürütücü Git durumunu değiştirmez. Her dondurma noktasında `gpt-6.1-sol` / `high`, en çok 3 inceleme turu; tur, yanıt ve çözülmemiş bulgular kayıtlı. Hazır hükmü alınamazsa bekle; model değiştirme yok. Bu bütçe H9'un uygulama/okur bütçesinden ayrı, ön kapı maliyetidir. |

K05'in **sunucu ortamı**, ilk keşiften önce kesin yolları/değerleri ve anahtarların yalnız kaynak bilgisini `protocol.md`'ye geçirir. Adlar ve aşağıdaki yükleme varsayılanları `backend/deixis/config.py` ile doğrulandı:

| Ortam alanı | Dondurulacak değer / önerilen varsayılan |
|---|---|
| `DEIXIS_DATA_DIR`, `DEIXIS_HOST`, `DEIXIS_PORT` | Yeni, boş, gerçek yola çözümlenmiş izole veri dizini; `127.0.0.1`; boş ve 8765 dışında kesin port. |
| `DEIXIS_CODEX_HOME` | Sahibin bu iş için önceden oturum açtığı ayrı dizinin kesin yolu. Boş veri dizininin varsayılan `data_dir/codex-home` yolu mevcut bir giriş sağlamaz. Adapter bu yolu `CODEX_HOME` olarak kullanır. P16 run 3'ün canlı home kullanımı buraya kendiliğinden taşınmaz. Alternatif yalnız sahibin ayrıca onayladığı `~/Library/Application Support/DEIXIS/codex-home` istisnasıdır; izin bu alt dizine ve Codex adapter kullanımına sınırlıdır, canlı kütüphaneye veya port 8765'e erişim vermez. Bu taslak düzenleme görevi istisnayı yetkilendirmez. |
| `DEIXIS_PROTOCOL_APPROVAL` | `ask`; kart onayı ayrıca kaydedilir (`as_proposed` ancak açık seçimle). |
| `DEIXIS_FULLTEXT_FETCH`, `DEIXIS_FULLTEXT_ADJUDICATION` | İkisi de `auto`; alternatif `off` açıkça dondurulur. |
| `DEIXIS_CITATION_CHAINING`, `DEIXIS_SEARCH_QUERY` | `auto`, `model`; alternatifler sırasıyla `off`, `code`. |
| `DEIXIS_ARXIV_SOURCE`, `DEIXIS_QUERY_STRATEGY` | `off`, `legacy`; alternatifler `auto`, `compact_openalex_v1`. Bunlar `config.py` yükleme varsayılanlarıdır; `sw` araştırma seçimi ayrı kaydedilir. |
| `DEIXIS_MODEL_CONCURRENCY`, `DEIXIS_CONTACT_EMAIL`, `PATH` | `6`; iletişim e-postası ayarlı/ayarsız durumu; kullanılacak Codex yürütülebilirini belirleyen kesin `PATH`. |
| Sağlayıcı anahtarlarının kaynağı | Varsayılan sahibin sunucu sürecine sağladığı ortam değişkenleri; `OPENALEX_API_KEY` dahil kullanılan her anahtarın adı, ayarlı/ayarsız durumu ve `environment` / `dotenv` / `keychain` kaynağı kaydedilir, değeri kaydedilmez. `credentials.py` diğer kaynak anahtarlarını `S2_API_KEY`, `NCBI_API_KEY`, `IEEE_API_KEY`, `SCOPUS_API_KEY`, `CORE_API_KEY`, `SERPAPI_API_KEY` olarak tanımlar. Gerçek launcher ortamda eksik değişkenleri depo `.env` dosyasından, sonra anahtarları `DEIXIS` keychain servisinden yükler; bu yollar kullanılacaksa sahip K05'te açıkça adlandırır. Codex girişi bir sağlayıcı API anahtarıyla varsayılmaz. |

Bu alanlar süreç ortamında açıkça ayarlanır; varsayılanı seçilen değer bile yazılır. Kaynak, eksik giriş veya farklı ortam nedeniyle hazır değilse başka home/anahtar/model denenmez. Sahip girişi yürütme öncesinde hazırlar; yürütücü credential kopyalamaz veya login başlatmaz. Dondurulan kesin `serve` komutu, onaylı ölçüm ağacının kökünde aşağıdakidir; `DEIXIS_PORT` ve tüm yollar protokolde yer tutucu olmadan kaydedilir. Bu komut şimdi çalıştırılmaz; §6.2'nin modelsiz sağlık bloğu gerçek-model yürütme sunucusunun başlangıç kaydı değildir.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. .venv/bin/python -m deixis serve \
  --port "$DEIXIS_PORT" --no-browser
```

### 4.2 Beklenti tablosu

Kaynak, D124'ün dondurulmuş beklenti tablosudur. Sayısal aralıklar ve sert satırlar değişmez. Aşağıdaki tablo kısaltılmış aktarımıdır; özgün tablonun “Şunu görürsem varsayımım yanlış” sütunu da, R11'in yalnız ≤10 kaynak dalı uygulanarak, aynen bağlayıcıdır. Beklenti ile bu uyarı eşikleri farklıdır: örneğin R2 kısmen ≤8 beklentisi, >12 uyarısını ≤12 kabul sınırına çevirmek için kullanılamaz.

| Ölçüt | Dondurulacak tanım ve beklenti | H9 uyarlaması / değişiklik gerekçesi |
|---|---|---|
| R1a | İlk model çıktısında şema/cümle onarımı olmadan geçerli bölüm: 10 model bölümünden 7-10; II kod yazımıdır, sayılmaz | Eşik ve bölüm kümesi aynı. Yarım koşuda gerçek okunabilir/yazılan payda ayrıca verilir, 10 yazılmış varsayılmaz. |
| R1b | Onarım sonrası 10 bölümün en az 9'u `valid` | Aynı. D129 yeni onarım turu eklemez; kullanılan onarımlar ayrıca sayılır. |
| R1c | Geçerli ve `report_version` almış rapor / başlatılan rapor: beklenti 1/1 | Aynı; tek koşuda yalnız 1/1 veya 0/1, oran yorumu yok. Rapor başlamazsa ölçülmedi. |
| R2, sert | Bölüm × destek türü × okuma derinliği katmanlarından tohumlu 30 iddia; her iddia-kayıt bağı ayrı okunur. En az bir desteklemeyen bağı olan iddia 0-3; kısmen bağı olan iddia en çok 8. Bağ paydası ve yanlış bağı olan iddia sayısı ayrı | Eşik aynı. 30'dan azsa tümü okunur; küçük örneğin oranı genellenmez. Çapa eşleşmesi anlam desteği değildir. |
| R3, sert | Bütün olumsuz/yokluk birimleri; okur kitin kaçırdıklarını ekler. N hüküm verilmiş birimler (`no_evidence_given` hariç), U uygunsuzlar; U ≤ max(1, ⌊0,10 × N⌋) | Aynı. D125'in başarısız satır bildirimi yolu kullanılmaz; operasyonel başarısızlık kaynakta yokluk sayılmaz. N=0 ölçülemedi. |
| R4a, sert | Abstract/I/IX'te `body_refs` olmayan iddia: 0 | Aynı; pozitif değer kural hatası olarak ayrıca kaydedilir. |
| R4b | Abstract/I/IX'in gövdeden güçlü iddiaları / bu bölümlerin bütün iddiaları: en çok %10 | Aynı; payda ve sayı da verilir, payda 0 ölçülemedi. |
| R5 | Sözlük terimi başına başka adla anıldığı yerlerin ortalaması en çok 1 | Aynı. Yeni alanın kendi sözlüğü okunur; eksik okuma sonuç sayılmaz. |
| R6 | Görüntülenen 0-6 denklem; en az 3 varsa en az yarısı özgün PDF sayfasıyla örtüşür. Eşdeğer LaTeX hata değildir | Aynı; sayfa açılamazsa hüküm verilmez. Tam metin hedefi aktarım doğruluğunu garanti etmez. Matematiksel doğruluk ölçülmez. |
| R7 | Yalnız rapor: 10-30 dk, 15-46 çağrı, 7-13 ardışık çağrı; kuyruk/kota beklemesi, onarım/başarısız çağrı ve token sayısı ayrı; token beklentisi yok | Aynı. Hazırlık ve okur giderleri R7'ye eklenmez. 60/90 bir durma tavanıdır, beklenti aralığı değildir. Nested token alanı kitte eksikse saklı kayıttan ayrı hesap ve kapsam yazılır, kit değiştirilmez. |
| R8 | III-VII özgün cümle kimliklerinde ilk uyumsuzluk %30-%70; onarım sonrası kalıpsız (istisna dahil) en çok %25; `reverted_exception` 0-2 | Aynı; kaynak sayısına göre eşik gevşetilmez. |
| R9 | Önceden işaretli (kaynak, formülasyon) çiftlerinden modele verilen girdide görüntülenen denklemi bulunanların en az yarısı raporda, verilen parçaları eksiksiz | Eşik aynı, çiftler yeni korpustan §4.4 ile seçilir. Eski yedi çift taşınmaz. Uygun çift/girdi denklemi yoksa ölçülemedi. |
| R10 | Aralık yok; her zaman ölçülmedi, `p15_behavior_is_not_r10` | Aynı; P15 `flagged` sonucu yakalama oranı değildir. H9 hata ekme deneyi başlatmaz. |
| R11 | ≤10 kaynaklı tabloda kesilen kayıt 0; `insufficient_evidence` 0-3; okurun girdiye verilmemiş ama bölümde olması gerekirdi dediği pasaj en çok 2 | Özgün tablonun küçük-korpus dalı, sayı değişikliği yok. 25 kaynak için %20 dalı H9'a uygulanmaz; sonuç dosyalarındaki kısa %20 aktarımı küçük tablo için kullanılmaz. 0 kesilme ölçülmüş olabilir; eksik okuma ölçülmüş sayılmaz. |
| P19, yardımcı (D129) | `report_section` adımları için (a) ilk çıktısında en az bir `anchor_not_in_cell_evidence` bulunan adım sayısı; (b) saklı `step_inputs.user_message` içinde `Cell anchor repair pairs:` bulunan ve model oturumu olan çapa-onarım denemesi sayısı; (c) bunlardan onarım doğrulamasında bu kod kalmayan ve bölümü `valid` olanlar; (d) onarımdan sonra aynı çapa hatasıyla hâlâ `failed` bölümler, sayı ve kimlikleri; (e) onarımda çıkarılan ve `claim_key` adıyla bir `insufficient_evidence` kaydında görünür kalan iddialar | İlk keşiften önce donar. Aralık/eşik yok; yalnız sayılar ve bölüm listeleri, oran olarak okunmaz. Gönderilmeyen `message_too_large`, `anchor_not_in_passage` ve diğer kodlar ayrı sayılır; diğer hata kodları D129'un hücre çapa yönergesini almaz. Kit değişmez; §4.2.1 salt okunur kayıt hesabı kullanılır. Yarım raporda da ölçülür; rapor başlamazsa `ölçülmedi: rapor başlamadı`. (c) D129'un nedensel etkisini göstermez; onarılmış çapa anlam desteği değildir, R2 ayrı okunur. |

Sütunların konu uyarlaması, küçük korpus seçimi, hazırlıkta kuyruk kullanımı, yeni ürün/yöntem hash'i ve yeni R9 çiftleri çerçeveyi değiştirir; eski koşularla kontrollü karşılaştırma üretmez. D127'nin gösterilmiş kanıt üyeliği ve D129'un aynı hücreye bağlı tek onarım sınırı yürürlükte kalır. Üç sert satırdan biri aralık dışındaysa sonuç bunu ilk cümlede söyler; rapora olduğu gibi kullanılabilir denmez. Bütün metrikler ölçülmeden tek bir “rapor geçti” hükmü kurulmaz.

#### 4.2.1 P19'un saklı kayıt hesabı

Kaynak adları migration 0001/0035/0036, `workflow/flow.py`, `workflow/report/sections.py`, `workflow/report/store.py` ve `models/prompt.py` ile doğrulandı. İzole `library.sqlite` yalnız `mode=ro` bağlantısı ve `PRAGMA query_only=ON` ile okunur; kitin dosyaları ve çıktıları yeniden yazılmaz. Aşağıdaki parametreli sorgu, sorgunun SHA-256 değeri ve JSON ayrıştırma/sayma kuralı ilk keşiften önce `protocol.md`'ye yazılıp dondurulur. Gerçek rapor kimliği ve sorgu çıktısının hash'i sonuç alınırken ayrıca kaydedilir; ham çıktı özel kanıt dizininde kalır.

```sql
SELECT rs.id AS report_section_id, rs.section_id, rs.status AS section_status,
       rs.draft_json AS section_draft_json,
       rs.validation_json AS section_validation_json,
       st.id AS step_id, st.status AS step_status, st.error_code, st.error_json,
       st.output_json,
       si.id AS step_input_id, si.rowid AS input_order, si.attempt,
       si.user_message, si.payload_json,
       ms.id AS session_id, ms.rowid AS session_order, ms.status AS session_status,
       ms.raw_output, ms.validation_json AS session_validation_json
FROM reports r
JOIN run_steps st ON st.run_id = r.run_id AND st.kind = 'model:report_section'
LEFT JOIN report_sections rs ON rs.report_id = r.id AND rs.step_id = st.id
LEFT JOIN step_inputs si ON si.step_id = st.id AND si.task_type = 'report_section'
LEFT JOIN model_sessions ms ON ms.step_input_id = si.id AND ms.step_id = st.id
WHERE r.id = ?
ORDER BY st.id, si.rowid, ms.rowid;
```

Yukarıdaki sorgunun UTF-8 baytları, son satırsonu dahil, SHA-256: `6d53789f7a1b898a4833bb993eaac222b29e5fa0cb209519fe020c3106e6acd1`. Protokole aktarırken aynı baytlar yeniden doğrulanır.

(a) Her adımda kayıt sırasına göre ilk çıktı veren oturumun `validation_json.issues[].code` alanı okunur; aynı kodun birden çok geçmesi adımı tekrar saydırmaz. İlk çıktı/doğrulama yoksa sıfır hata varsayılmaz, kayıt eksikliği ayrıca yazılır. (b) İşaretli her farklı `step_input_id`, en az bir `session_id` varsa bir denemedir; çoklu oturumlar ve kimlikleri ayrıca listelenir. İşaretli ama oturumsuz girdi `error_code=message_too_large` ise gönderilmedi diye ayrı sayılır; diğer oturumsuz veya uçuşta kalan girdiler de ayrı gösterilir. (c) Bu denemenin doğrulaması mevcut olmalı, `ok=true` olmalı, ilgili kod kalmamalı ve bölüm durumu `valid` olmalıdır; bölüm kimliği ve oturum kimliği yazılır. (d) Onarım gönderilmiş, bölüm hâlâ `failed` ve bölümün `validation_json.issues` kaydında `anchor_not_in_cell_evidence` kalan bölümler tekilleştirilir; `report_section_id`, `section_id`, `step_id` listelenir. Diğer çapa kodları ve hata sınıfları ayrı sayılır; durma nedeniyle terminal bölüm kaydı oluşmamışsa bu belirsizlik gizlenmez.

(e) Onarım öncesi ve onarım çıktısının saklı `raw_output` JSON'larındaki `claims[].claim_key` kümeleri karşılaştırılır; çıkarılan anahtarın bölümün `draft_json.insufficient_evidence` kaydında açıkça adlandırıldığı doğrulanır. Şemada bu kaydın alanları `context` ve `reason`dır, ayrı bir `claim_key` alanı yoktur; anahtar bu metinlerden birinde tam kimliğiyle bulunmalıdır. Çıkarılan ama adıyla görünür bırakılmayanlar ve ayrıştırılamayan çıktılar ayrı listelenir; eksiklik sıfır diye yazılmaz. Görünürlük saklı bölüm kaydı içindir: Markdown dışa aktarımı, bölümde iddia kaldığında bu kayıtları her durumda göstermiyor; dışa aktarımda görünürlük garantisi verilmez. Sonuçta a-e sayıları ile bölüm/iddia kimlik listeleri vardır; başarı yüzdesi, eşik veya D129 etkisi hükmü yoktur.

### 4.3 Okuma ve okunamadı kuralları

R2: 30 iddia, tohum `20261003`. R3 bütün olumsuz birimler; R4b ilgili bölümlerin bütün iddiaları; R5 bütün sözlük terimleri; R6 bütün görüntülenen denklemler; R9 donmuş bütün çiftler; R11 kesilme ve eksik pasaj okuması. K09 her satır için okur adı/türü ve varsa model/eforu kaydeder.

İkinci okur R2/R3/R4b/R6/R9'un ilk okurca olumsuz işaretlenmiş bütün birimlerini ve **her ölçüt sayfası için ayrı** en çok 5 destekleyen kontrol birimini görür. Kit kontrol seçimi için aynı tohumu, karıştırma için `20261004` kullanır; olumsuz/kontrol kimliği ve ilk hükümler ikinci pakette görünmez. R5 ve R11 D124'teki gibi ilk okurun tam okumasıdır, ikinci okuma yapıldı varsayılmaz. Birim iki okurdan biri ciddi diyorsa ciddidir; anlaşmazlık sayısı yazılır.

R2 kaynak metni okunamazsa bağ `okunamadı: neden` olur, destek hükmü verilmez; ikinci çekiliş ve değerlendirme paydasından çıkar, ayrı sayılır. R6 sayfası açılamazsa denklem için hüküm verilmez. Sıfır payda ölçülemedi; erişilemeyen kayıt sıfır hata değildir. Eksik/çift işaret, silinmiş birim/kutu veya ikinci kimlik uyuşmazlığı varsa kitin ret yolu korunur. R5/R11 eksik okuması sonuç üretmez. Okur veya bütçe bulunamazsa eksik metrikler ölçülemedi kalır; eşik, okur veya model sonradan değiştirilmez.

### 4.4 R9 çiftlerinin seçim kuralı ve zorunlu kayıtlar

Hazırlık sonunda, rapor çıktısı görülmeden, Denklem sütunundaki güncel hücreler kaynak/satır kimliği sonra hücre kimliği sırasıyla okunur. Verilen metinde açıkça görüntülenen ve hücrede kökeni kaydedilmiş her ayrı formülasyon seçilir; aynı hücrede birden çok varsa hücredeki sırasıyla alınır. Sözle tarif edilen veya analistin tamamladığı formülasyon seçilmez. Tüm uygun çiftler alınır; sonuç iyi görünsün diye alt örnek seçilmez.

Kitin `pairs.json` biçimi `[{"source_key": "...", "formulation": "..."}]` olarak korunur. `formulation` açıklayıcı etikettir; hücre değeriyle birebir aynı metin olmak zorunda değildir (ek 2). Ayrı `pairs-provenance.json` kaydı gerçek kaynak-sürümü, eser, satır, hücre, hücre revizyonu, değer hash'i ve köken pasajını tutar. Aynı kısa kaynak anahtarı birden çok satırı belirsiz eşliyorsa kitin tek-anlamlı okuması sağlanmadan R9 başlatılmaz; kit değiştirilmez, R9 ölçülemedi kalır. İki dosyanın SHA-256 değeri rapor öncesi belge ekine girer. Sonradan çift eklenmez/değişmez. Modele gerçekten verilen denklem koşulu ayrıca saklı StepInput'tan sınanır.

| Hazırlık/inceleme sonrası kayıt, sahip seçimi değildir | Ne zaman / içerik |
|---|---|
| Ürün ve dondurma kimlikleri | İlk keşif öncesi ürün commit'i, ilk belge commit'i ve inceleme; ilk rapor öncesi nihai belge commit'i, ürünün atalık denetimi, inceleme turları ve sonuçları |
| Hash'ler | Runtime `skill_package_hash`, yöntem/şema dosya manifesti, kit ve kit testinin tam SHA-256 değerleri, dondurma belgesi ve istem dosyaları |
| Korpus ve tablo | Her denemenin soru/protokol, bulunan/tekil/taranan/dahil/incelenen sayıları; kaynak/sürüm/DOI/hash envanteri; seçim nedenleri; araştırma/tablo kimliği; sıralı satır, sütun, güncel hücre revizyon/değer/kanıt JSON'larının SHA-256 değeri; `report_ready` yanıtı |
| R9 | Çift ve köken dosyaları, hash'leri, seçim zamanı; uygun çift yoksa boş dosya ve gerekçe |
| İzolasyon, sunucu ortamı ve gözlemci | K05'in kesin ortam/başlatma kaydı ve Codex/anahtar kaynakları; yeni veri dizini ve port, sıfır eski rapor/aktif yabancı koşu/`started` oturum; gözlemci sürümü/hash'i, sonlandırma ve yürütücü dönüş kaydının nasıl alınacağı; P19 sorgusu/sayma kuralı/hash'i |

## 5. Tek koşu ve durdurma (plan §7, kural 5)

Her 15 saniyelik kontrolde saklı adım ve oturum hataları, bölüm doğrulamaları ve `review.reason` okunur. `running` görünümüne veya dış `pause_reason` koduna güvenilmez. İzinli şema onarımında görülen geçersiz ilk çıktı, onarım sonrası terminal başarısızlıkla karıştırılmaz.

Yalnız bütün terminal kök nedenler `client_timeout`, tek sürdürme hakkı kullanılmamış ve bütün tavanlarda yer varsa aynı koşu 10 dk sonra bir kez sürdürülür. Bu bekleme süre bütçesine dahildir. Kota/yük, model uyuşmazlığı, araç ihlali, başka veya karışık hata, ikinci timeout, `budget_exhausted`, okunamayan sayaç veya dolan tavan durdurur. K08 için öneri: hazırlıktaki her uygulama koşusunda da en çok bir timeout sürdürmesi; hazırlık denemesi ve birleşik sayaç bu sürdürmeyle sıfırlanmaz. Hazırlık sırasında kota/yük duruşu o denemeyi bitirir; aynı deneme kota için sürdürülmez. Kalan deneme hakkı yalnız birleşik 300 oturum/240 dk tavanı içinde ve ana oturum bağlantının geri geldiğini tarihli kayda geçirdikten sonra kullanılabilir. Beklemede saat durmaz; deneme hakkı veya bütçe kalmazsa sonuç `korpus hazırlanamadı` olur. Yeni deneme §1.2'deki aynı veri dizini/yeni `sw` kuralına uyar; sessiz model değişimi yoktur. Rapor sırasında kota/yük duruşu tek rapor koşusunu bitirir.

Başka kök nedenle durması gereken koşu hâlâ çalışıyorsa yalnız ölçümü sonlandırmak için kendi API iptal yolu kullanılır. Zaten duraklamış/terminal koşunun durumu korunur. Hücre, kaynak, bölüm, plan, ürün, yöntem, şema veya doğrulayıcı değişmez. Düzeltme ayrı slice'a gider; sonraki ölçüm başka yeni korpus ister.

Nihai snapshot, yürütücünün döndüğü zaman kaydı ve **sıfır `started` model oturumu** birlikte doğrulanınca alınır. Kalıcı `running` adım etiketi sabitlenme kanıtı değildir. Kapanış için önerilen gözlem süresi en çok 120 s; bitiş doğrulanamazsa nihai durum iddiası kurulmaz, R1/R7/P19 kayıt anındaki durum diye etiketlenir. Tavan iki poll arasında aşılırsa uçuşta aşan çağrılar ayrıca sayılır; izleme sert üst sınır garantisi değildir.

Rapor durduysa yalnız R1, R7 ve P19 korunur; R2-R6/R8/R9/R11 `ölçülemedi: run_incomplete`, R10 tasarım gereği ölçülmedi olur. R7 ana süre `created_at`/`updated_at` tanımını korur; saptama, iptal, son oturum ve kapanış beklemesi ayrı kaydedilir. Durmuş koşunun kısa süresi hız/maliyet kanıtı değildir. Kapanış doğrulanmamışsa P19 da kayıt anındaki sayım diye etiketlenir.

## 6. Model-free ön koşullar: çalıştırılabilir komutlar (plan §5 H9; §7 kural 4-5 sonrası kuru başlangıç şartı)

Bu komutlar taslak hazırlığında sunucu başlatma yetkisi vermez. Aşağıdaki kaynak/hash kontrolü uygulamayı açmaz. Test ve gerçek loopback sağlık kontrolü, gelecekte onaylı dondurma ağacında ve hazır native arm64 Python 3.12 ortamında çalıştırılır. Bu worktree'de `.venv` yok; kurulum ve bu iki çalışma yapılmadı.

### 6.1 Commit, D129 çağrı yolu, yöntem ve kit

Onaylı değerler ortam değişkenlerine girer; eksik değer komutu durdurur. `H9_ALLOWED_DOCS` nihai belge commit'inin izinli ölçüm belge yollarının boşlukla ayrılmış kesin listesidir; öneri bu iki taslak/istem, `docs/product/p9r-report-freeze.md`, K01-K12 kaydı için `docs/decisions.md` ve push durum güncellemesi için `STATUS.md`. Bunların listede olması commit/push yetkisi vermez. Ürün commit'inden sonra başka dosya farkı kabul edilmez.

```sh
: "${H9_PRODUCT_COMMIT:?Onaylı ürün commit gerekli}"
: "${H9_FREEZE_COMMIT:?Onaylı dondurma commit gerekli}"
: "${H9_SKILL_HASH:?Dondurulmuş runtime hash gerekli}"
: "${H9_ALLOWED_DOCS:?İzinli ölçüm belge yolları gerekli}"
test -x .venv/bin/python
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python - <<'PY'
import os, subprocess, hashlib
from pathlib import Path
from deixis.domain.skill import package_hash, integrity_issues
def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()
product, freeze = os.environ['H9_PRODUCT_COMMIT'], os.environ['H9_FREEZE_COMMIT']
assert git('rev-parse', 'HEAD') == git('rev-parse', freeze)
subprocess.run(['git', 'merge-base', '--is-ancestor', '06fa1b6', product], check=True)
subprocess.run(['git', 'merge-base', '--is-ancestor', product, freeze], check=True)
allowed = set(os.environ['H9_ALLOWED_DOCS'].split())
assert all((p.startswith('docs/product/') and p.endswith('.md'))
           or p in {'docs/decisions.md', 'STATUS.md'} for p in allowed)
changed = set(git('diff', '--name-only', product, freeze).splitlines())
assert changed <= allowed, changed - allowed
paths = ['backend', 'apps/web', 'contracts', 'methods', 'scripts', 'tests', 'pyproject.toml', 'uv.lock']
assert not git('diff', '--name-only', product, '--', *paths)
assert not git('ls-files', '--others', '--exclude-standard', '--', *paths)
context = Path('backend/deixis/domain/contracts.py').read_text()
flow = Path('backend/deixis/workflow/flow.py').read_text()
prompt = Path('backend/deixis/models/prompt.py').read_text()
assert 'def report_section_anchor_repair_context(' in context
assert 'contracts.report_section_anchor_repair_context(failed_input, output_text, repair_issues)' in flow
assert 'REPORT_SECTION_ANCHOR_REPAIR_GUIDANCE' in prompt
assert 'A found quote does not prove' in prompt
assert 'insufficient_evidence entry naming its claim_key' in prompt
assert not integrity_issues(), integrity_issues()
assert package_hash() == os.environ['H9_SKILL_HASH'], package_hash()
pins = {
 'scripts/p6_eval/measure_report.py': 'db203420e4b1ade5ab45cfa3b1636cc239bd3efa251554bb8dc1b15912251848',
 'tests/test_p6_measure_report.py': '7f7d2f0d500401f30bafe3cee7a4c4bdffd96454a600817158a1aa765d63bdf8',
}
for path, expected in pins.items():
    actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert actual == expected, (path, actual)
    print(path, actual)
for path in sorted(Path('contracts/research').glob('*.schema.json')):
    print(path, hashlib.sha256(path.read_bytes()).hexdigest())
print('product', git('rev-parse', product), 'freeze', git('rev-parse', freeze))
print('skill_package_hash', package_hash())
PY
```

Atalık ve metin varlığı tek başına D129 davranışını kanıtlamaz; aşağıdaki regresyon testleri çağrı sınırını, hücrenin kendi alıntılarını ve kayıtları denetler. Şema manifesti nihai dondurmadaki tam listeyle ayrıca karşılaştırılır; eski P16 şema hash'i otomatik taşınmaz.

```sh
test -x .venv/bin/python
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. .venv/bin/python -m pytest -q -n 0 \
  -p no:cacheprovider --basetemp=/tmp/p9-h9-preflight-tests \
  tests/test_report_anchor_repair.py tests/test_report_handles.py \
  tests/test_report_failed_rows.py tests/test_report_api.py \
  tests/test_p6_measure_report.py
```

### 6.2 İzole, modelsiz gerçek port sağlık kontrolü

Bu blok yalnız gelecekte kapılar geçince çalıştırılır. Yeni geçici dizin, OS'nin verdiği ayrı loopback portu, boş adapter haritası, kapalı worker ve dış HTTP'yi reddeden transport kullanır. `.env`/keychain yüklenmez. Üretim CLI bağlantı sağlığı veya gerçek model hazır olma durumunu ölçmez. Port 8765'e bağlanmaz, canlı dizini okumaz.

```sh
: "${H9_SKILL_HASH:?Dondurulmuş runtime hash gerekli}"
H9_REPO="$PWD"
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$H9_REPO/backend" PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
  H9_SKILL_HASH="$H9_SKILL_HASH" "$H9_REPO/.venv/bin/python" - <<'PY'
import asyncio, os, socket, tempfile, threading, time
from pathlib import Path
import httpx, uvicorn
from deixis.api.app import create_app
from deixis.config import Settings
def deny(request):
    raise RuntimeError('H9 dry check forbids outbound HTTP')
with tempfile.TemporaryDirectory(prefix='p9-h9-dry-', dir='/tmp') as root:
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    assert port != 8765
    listener.listen(128)
    http = httpx.AsyncClient(transport=httpx.MockTransport(deny), trust_env=False)
    app = create_app(Settings(data_dir=Path(root), port=port), adapters={},
                     http_client=http, start_worker=False)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        with httpx.Client(trust_env=False, timeout=1) as client:
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started, 'dry server did not start within 20 seconds'
            response = client.get(f'http://127.0.0.1:{port}/api/health')
            response.raise_for_status()
            health = response.json()
            assert health['status'] == 'ok'
            assert health['worker'] == 'not_owner'
            assert health['skill_package_hash'] == os.environ['H9_SKILL_HASH']
            print({'data_dir': root, 'port': port, 'health': health})
    finally:
        server.should_exit = True
        thread.join(20)
        assert not thread.is_alive(), 'dry server did not stop within 20 seconds'
        listener.close()
        asyncio.run(http.aclose())
PY
```

Taslak yazımında modelsiz ve sunucusuz doğrulananlar: `06fa1b6` (D129) HEAD'in atası; çağrı bağlamı, akış bağlantısı ve sabit destek yönergesi kaynakta var; kit ve kit testi yukarıdaki tam SHA-256 değerlerinde, `cdf79ba` ile farkları boş. Runtime hash `sha256:8e1e4a8453a286ac9da8628dd095dd7796f3a49ae374d7930cb3ef06c546ee76`, paket bütünlük sorunları `[]`. Bu D129 tarihindeki `cef7c086…` hash'i değildir; bugünkü hash yeniden hesaplandı. K11 seçilince yeniden dondurulmalıdır. Testler ve sağlık bloğu çalıştırılmadı; bu bir kuru sunucu başlangıcı kaydı değildir.

## 7. Okuma, sonuç dili ve P9 kaydı (plan §7, kurallar 6-7; R01)

Ham model çıktısı, okuma gerekçeleri, ledger, protocol, poll ve özel kaynak içeriği `.local/p9r-*/` altında izlenmeden kalır; runtime kütüphanesi yeni geçici uygulama-veri dizinindedir. Sonuç belgesi planın yolu `docs/product/p9r-report-results.md` olur; temizlenmiş özet, commit/hash, tarih, komutlar, sapmalar, değer/payda/örnek/tohum/okur ve ölçülemeyenler içerir. Bu taslak görevi o belgeyi veya karar kaydını yazmaz.

Sonuç dili: **geliştirme sonrası yeni korpus, tek koşu, tek rapor modeli, rapora hazır tablo koşuluna bağlı**. Okur modelleri ayrıca adlandırılır. Bulunan, tekil, taranan, dahil edilen, incelenen, modele verilen ve atıf yapılan sayıları ayrı verilir. Hazırlıkta yapılan seçimin koşulluluğu açıkça yazılır. D124/D126/D128 kapanmış seri olarak korunur; H9 onun dördüncü denemesi değildir.

R01 isteğe bağlı, gerçek-model satırıdır; R1-R11'in ölçüm durumunu özetler, R10 ölçülmedi kalır. P19 ayrı yardımcı kayıt olarak eklenir, R01'in başarı eşiğine dönüştürülmez. Başarı/başarısızlık yeni bir `decisions.md` kararıyla kaydedilir. P9 bilinen sınır kaydına geçti/geçmedi/kısmen tek satırı eklenir; ayrıntı sonuç dosyasına bağlanır. Sert satırlar okunamadıysa R01'e koşulsuz geçti yazılmaz. H8'in model-free kapanışı H9 sonucuna bağlı değildir (S2). Belge/karar güncellemelerinin yetkisi onaylı H9 isteminin kapsamıdır; commit/push ayrıca açık talimat ister.

## 8. H9'un gösteremeyecekleri (plan §5 H9; §7 kurallar 2, 4, 6-7)

H9 başka korpusa/model/efora genellenemez; başarı veya hata oranı, hız ya da maliyet karşılaştırması üretmez. Kayıtlı süre/token sayısı sağlayıcı faturası değildir. D129'un veya tutamaçların nedensel etkisini sınamaz; kontrollü eski/yeni ürün karşılaştırması yoktur. Model okuması bağımsız insan doğrulaması değildir; `structurally_valid` ve bulunan çapa bilimsel anlam desteği sağlamaz.

Keşfin geri çağırımı, literatürün tamamlığı, yenilik/araştırma boşluğu, matematiksel doğruluk, R10 yakalama oranı, lineage L9, kill-search K6, düzenleme ölçümleri R18/R19/R21 ve H10'un gerçek çağrı tekrarları bu işte ölçülmez. Hazır korpus kurmak için yapılan kuyruk seçimi varsayılan keşfin başarısı gibi sunulmaz. Rapor tamamlanırsa diğer borçlar kendiliğinden kapanmaz; her biri ayrı dondurma ve sahip yetkisi ister.

**Sonraki işlem:** sahip K01-K12'yi tek kayıtta kapatır; H8 kapanışı ve ilk dondurma incelemesi kanıtlanana kadar H9 bekler.
