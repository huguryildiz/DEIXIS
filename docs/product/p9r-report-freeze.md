# P9 H9 (P9-R serisi): rapor ölçümü dondurma belgesi

**Tarih:** 3 Ekim 2026. **Durum:** 1. dondurma noktası (keşif öncesi kurallar) yazıldı; K01-K12 [D171](../decisions.md) ile kapandı. İnceleme: `gpt-6.1-sol` high ilk 3 turda “hazır değil” dedi, bulguların hepsi işlendi; K12 uzatmalarıyla (D171) 4.-7. turlar. 4.-7. turlar da “hazır değil” dedi; ardından port 8765 yolu koordinatör talimatı ve Sol medium onayıyla sadeleştirildi (§4.1.1) ve yalnız o kapsamda yapılan 8. tur üç orta bulgu verdi; hepsi işlendi. `gpt-6.1-sol` medium iki dar doğrulamada ikisini çözülmüş buldu, üçüncüsünü (zaman aşımında port denetimi çıktısının kaybı) koordinatörün düzeltmesinden sonra çözülmüş buldu ve “hazır” dedi (`/tmp/h9-verify8.md`, `/tmp/h9-verify9.md`). **1. kapı geçti** (3 Ekim 2026). Bu commit'te model çağrısı yapılmadı, sunucu başlatılmadı. 2. dondurma noktası (kaynak kümesi, tablo, R9 çiftleri) bu belgenin sonuna tarihli ek olarak ayrı bir commit'le girer; aşağıdaki kurallar o ekte değişmez. Önceki adı `p9-h9-freeze-draft.md` idi (taslak ağacı `a4deebf`); istem `p9-h9-prompt-draft.md` adından [p9r-report-prompt.md](p9r-report-prompt.md) adına taşındı.

**Dayanak:** [P9 planı](p9-hardening-plan.md) §5 H9, §6 bağımlılık satırı, §7 H9 kuralları 1-7, §4 R01 ve §9 S2/S10; [D124, D126, D128, D129 ve D141](../decisions.md); [ilk beklentiler](p6-slice1-report-expectations.md), [ek 1](p6-slice1-report-expectations-addendum.md), [ek 2](p6-slice1-report-expectations-addendum-2.md) ve [ilk](p6-slice1-report-results.md), [ikinci](p6-slice1-report-results-run2.md), [üçüncü](p6-slice1-report-results-run3.md) sonuçlar. Yürütme istemi: [p9r-report-prompt.md](p9r-report-prompt.md).

## 0. Yetki, H8 istisnası ve iki dondurma noktası

Planın §7 kural 1'i konu ve hazırlık kurallarını keşiften önce; kural 4'ü gerçekleşmiş tabloyu, çiftleri ve okuyucuları ilk rapor isteğinden önce dondurur. Keşif yapılmadığından kaynak kimlikleri ve tablo hash'i bu commit'te yazılamaz.

1. **Yetki (K01).** Sahibin 3 Ekim 2026 kampanya talimatı: “benden bir şey bekleme. Faz 10'a gelene kadar (macOS uygulaması yapılacağı zamana kadar) kodu getir, her şey tamamlansın.” (kaynak `~/.claude/plans/deixis-p10-campaign.md`). Aynı gün yinelenen sürekli talimat: “bana onay sorma; gpt 6.1 sol medium'a sor.” K01-K12 bu talimatlar uyarınca sahip adına Claude Opus 5.5 ve `gpt-6.1-sol` medium tarafından ortak kararlaştırıldı ([D171](../decisions.md)); sahip tek tek onaylamadı. Yetki yalnız §4.1'deki değerleri kapsar.
2. **H8 bağımlılığı için açık istisna.** Plan §6 ve §7, H9'u H8 kapanışına bağlar. Kanıt: [D168](../decisions.md) (H8 matrisi; kayıt [p9-acceptance-record.md](p9-acceptance-record.md)), D169 (RR-A, Sol yeniden incelemesinin depolama/yedek/başlangıç/API düzeltmeleri), D170 (RR-B, H2/H5/H8'in Sol yeniden incelemesi; son iki tur “hazır”); üçü de `3215b3a`'da. Bunlar uygulama ve inceleme kanıtıdır, tamamlanmış H8/P9 kabulü değildir: D170'e göre boş makinede iki temiz matris koşusu hâlâ borçtur ve K02b'nin yük altındaki başarısızlığı açıklanmamıştır. H9 bu açık istisnayla ilerler. Koşullar: H9 hazırlık/rapor yürütmesi ile matris çifti aynı anda koşmaz (koordinatör sıralar); matris çifti engelleyici bir güvenlik ya da kanıt bütünlüğü kusuru gösterirse H9 karar verilene kadar durur; bunun getirdiği ürün değişikliği K11'i yeniden açar.
3. **1. dondurma noktası (bu belge).** §1-§8 ve §4.1'in değerleri keşiften önce donar. Bu commit Claude tarafından H9 worktree'sinde atılır, `gpt-6.1-sol` high incelemesinden geçer (K12) ve yalnız koordinatörce push edilir. Push edilmiş commit ve “hazır” kaydı yoksa hazırlık başlamaz.
4. **2. dondurma noktası.** Hazırlık rapora hazır tablo verirse kaynak kümesi, tablo ve R9 çiftlerinin kimlik/hash kayıtları bu belgenin sonuna tarihli ek olarak girer (§4.4 tablosu). İlk rapor isteğinden önce ikinci belge commit'i ve ekleri kapsayan `gpt-6.1-sol` high incelemesi “hazır” demiş ve koordinatör push etmiş olmalıdır. Donmuş kurallar ekte değişmez. İncelemenin gerektirdiği bir kural değişikliği otomatik yetki değildir; yeni Claude+Sol medium kararı ve yeni high inceleme ister.
5. İki kapı geçince istemdeki tek koşu için yeni izin sorusu gerekmez. Bir kapı, kayıt veya inceleme eksikse yürütücü durur. §4.1 dışındaki her yeni model, konu, bütçe ya da canlı veri kullanımı yeni, kayıtlı Claude+Sol medium kararı ister.

İki belge commit'i bu serinin uygulama düzenidir; plan commit sayısını belirtmez. Böylece keşiften önce dondurulabilen kurallar ile hazırlıktan sonra oluşan kayıtlar ayrılır. **Ölçülen ürün sabittir:** sabitlenen ürün commit'inden (K11, `87cee0b`) sonra main'e giren batch'ler ölçülen ürünün parçası değildir; koşu, sabitlenen commit'teki ayrı, detached bir worktree'de (`/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run`) yürür, böylece sonraki push'lar koşu sırasında ürünü değiştiremez. Dondurma belgeleri ayrı belge worktree'sinde (`/Users/huguryildiz/Documents/GitHub/DEIXIS-h9`) yazılır, main'e rebase edilir ve push edilmiş dondurma commit'inden okunur.

## 1. Konu, seçim ve hazırlık kuralları (plan §7, kural 1)

### 1.1 Aday sorular

**Seçilen soru (K02): Q1, aşağıdaki metin kelimesi kelimesine.** Q2 ve Q3 seçilmedi; gerekçe kaydı için tabloda kalır. Aşağıdakiler arama yapılmadan hazırlanmış adaylardır. Bugünkü kodun konuya özgü terimlerden sorgu kurması, özet taraması, tam metin getirmesi/okuması ve insan kuyruğu bulunması önerileri gerekçelendirir (`CLAUDE.md`, D96/D97). Her adayın gerçekten yeterli metinli kaynak getireceği bilinmiyor; açık PDF sayısı veya literatür büyüklüğü doğrulanmış gibi yazılmaz.

| Aday / alan | Dondurulabilecek soru metni | Bugünkü keşif akışı için gerekçe ve risk |
|---|---|---|
| Q1 / elektrik enerjisi sistemleri, **SEÇİLDİ** | Elektrikli araçların şarj zamanlaması için hangi matematiksel optimizasyon modelleri önerilmiştir? Karar değişkenlerini, amaç fonksiyonlarını, şarj ve şebeke kısıtlarını, belirsizliğin ele alınışını ve raporlanan değerlendirme koşullarını karşılaştırın. | `electric vehicle charging scheduling` ve `optimization` gibi konuya bağlı terimler bir genel alan adı yerine somut bir görevi tarif eder. Değişken/amaç/kısıt sütunları aynı tür kayıtları karşılaştırabilir. Bu bir tasarım çıkarımıdır; şebeke modeli, batarya modeli ve fiyat tahmini gibi komşu konular taramada dışlanmalıdır. PDF erişimi ve otomatik dahil etme verimi bilinmiyor. |
| Q2 / robotik ve kontrol | Mobil robotların engelden kaçınan yörünge planlamasında model öngörülü kontrol nasıl formüle edilmiştir? Dinamik modeli, karar değişkenlerini, amaç fonksiyonunu, engel ve hareket kısıtlarını ve değerlendirme koşullarını karşılaştırın. | `mobile robot`, `obstacle avoidance`, `model predictive control` belirgin görev/yöntem terimleridir. Bu özgüllük özet üzerinden konu sınırını değerlendirmeyi kolaylaştırabilir; denklem sütunu ancak getirilen metinde görülen formülasyonu alır. Otonom otomobil ve genel yol planlama sonuçları karışabilir; donmuş kapsam bunları ayırmalıdır. Yeterli açık tam metin henüz doğrulanmadı. |
| Q3 / su dağıtım sistemleri | Su dağıtım ağlarında pompa zamanlaması için hangi optimizasyon modelleri kullanılmıştır? Karar değişkenlerini, enerji maliyeti amacını, hidrolik ve depo kısıtlarını, talep belirsizliğini ve değerlendirme koşullarını karşılaştırın. | `water distribution pump scheduling` somut bir sistem ve karar problemini adlandırır; genel `operations research` sorgusuna dayanmayı gerektirmez. Formülasyon eksenleri rapor sütunlarına uygundur. Pompa tasarımı ve bakım çalışmalarının dışlanması gerekir. Özetlerin ayrıntı düzeyi ve açık PDF erişimi bilinmiyor. |

**D141 uyarısı:** NLP sorusunun varsayılan `sw` keşfi 99 tekil işten 1'ini dahil etti, 29'unu dışladı, 69'unu beklemede bıraktı; 25'i PDF bekleyen inceleme kuyruğundaydı. Bulunan işler dahil edilmiş işler değildir. Bu tek gözlem bir genel başarısızlık oranı vermez, fakat soru seçiminin tek başına rapora hazır korpus sağlayacağını varsaymayı engeller. H9 hazırlığı bu nedenle aşağıdaki sınırlı kuyruk adımını önceden tanımlar; başarılı sonuç görünene kadar konu değiştirmez.

### 1.2 Dahil etme, dışlama ve sıralama

Kural K03 ile dondu. Araştırma yeni, boş, izole veri dizininde `sw` olarak açılır; eski araştırma kopyalanmaz. `source_scope=academic`, `seed_mode=question_only`, keşif eforu `standard`, dil `tr`; protokol `ask` kartının önerisi değiştirilmeden yürütücü tarafından onaylanır (K01). Ürün bu onayı `mode=ask`, `approved_by=user` olarak saklar (`workflow/flow.py`); bu alanlar korunur ve sonuç, onaylayanın sahip değil yürütücü model (`claude-opus-5-5`) olduğunu açıkça yazar. `as_proposed` ayarı kullanılmaz. Ürünün etkin tam metin getirme/okuma ve zincirleme ayarları keşif öncesi protokole yazılır; varsayılan dışında bir yol sessizce seçilmez.

1. Seçilen sorunun görevine doğrudan uygulanan, kendi modelini/yöntemini ve değerlendirmesini sunan çalışmalar uygundur. Genel derlemeler, yalnız atıf listesinden gelen adaylar, ilgisiz uygulamalar ve salt metaveri kayıtları tabloya alınmaz. Soyut düzeyde görülen ayrıntı tam metin ayrıntısı gibi yazılmaz.
2. Otomatik keşif/getirme/okuma bittikten sonra, her hazırlık denemesinde bir kuyruk inceleme geçişi yapılabilir: en çok 30 henüz karara bağlanmamış iş, normalize başlık sonra eser kimliği sırasıyla. **Kararı veren (K03):** yürütücü model `claude-opus-5-5`, efor `medium`; yalnız üründe saklı metni okur, ek getirme yapmaz. Deneme başına en çok bir ayrı kuyruk okuma isteği; toplam en çok iki istek ve 30 dk. Bu istekler uygulama oturumlarından ayrı defterde sayılır, 240 dk hazırlık saatine dahildir. Bir istek seçilen işlerin hepsini değerlendiremezse okunmayanlar karara bağlanmamış kalır; yerine yeni istek açılmaz. Saklı metin soru kapsamını doğrudan karşılıyorsa iş ürünün mevcut seçim yoluyla dahil edilir; gerekçe, karar veren model, okuma derinliği kaydedilir. Ürün bu satırları "person"/insan etiketiyle saklar; sonuç, D96/D101 gereği bu etiketin bu satırlar için yanlış olduğunu açıkça yazar. Bu kararlar otomatik kararlardan ayrı sayılır; insan doğrulaması veya kişinin doğruladığı probe kaydı diye okunmaz ve varsayılan keşfin verimi gibi sunulmaz (seçilim etkisi). PDF bekleyen ama metni olmayan satır dahil edilmez. Otomatik dışlamalar yalnız sayıyı artırmak için tersine çevrilmez.
3. Uygun metinli işler arasından tam metni saklı olanlar önce, sonra özet metni saklı olanlar; her grupta yıl artan, normalize başlık, eser kimliği sırasıyla en çok 10 ayrı eser alınır. Aynı eserin sürümleri tek eser sayılır; kullanılan sürüm ayrıca kaydedilir. Seçilmeyen uygun işler ve nedenleri de korunur. Hedef 10, asgari 6 metinli kaynaktır (K03); en az 3 saklı tam metin hedefi R6/R9'u mümkün kılmak içindir, gerçekleşmemesi bu iki satırı ölçülemedi bırakabilir. Asgari 6, planın getirmediği ek bir tasarım tercihidir; temsil gücü garantisi değildir.
4. İlk tablo doldurması bir hazırlık denemesine dahildir. İkinci ve son deneme yalnız hazırlık tamamlanmadığında veya tablo hazır olmadığında açılabilir: aynı izole veri dizininde yeni bir `sw` araştırması açılır; aynı soru, sütunlar, seçim sırası ve onaylı ayarlar kullanılır. İlk denemenin bütün kayıtları korunur. Başarısız doldurma satırları dışlanıp sıradaki uygun metinli işlerle değiştirilebilir; değişim nedeni ve önce/sonra kümeleri yazılır. Başarısızlığı veya kaynağı silmek, hücreyi elle tamamlamak, farklı soruya geçmek yoktur. Kota/yük duruşundan sonraki yeni deneme §5 koşullarına da bağlıdır. İkinci denemede de hazır değilse sonuç `korpus hazırlanamadı` olur. Sayaçlar sıfırlanmaz.
5. Sahip PDF tohumu, DOI'den harici avlama, tarayıcıdan PDF edinme ve canlı kütüphaneden kopyalama kullanılmaz. Bu yollar yetkiye sonradan eklenmez. Kapsam içi sağlayıcı/API hataları ayrı kaydedilir; web aramasıyla telafi edilmez.

### 1.3 Tablo sütunları, keşiften önce donacak metin

Yedi sütunun tamamı `answer_format=text`. K03 ile kelimesi kelimesine dondular; modelle sütun önerisi istenmez. D124'te ilk iki sütun çoklu seçimli `choice` idi. H9'da yeni alanların çalışma ortamı ve yöntem ayrıntılarını eski seçeneklere zorlamamak için bu ikisi de `text` önerilir; format değişimi kontrollü karşılaştırmayı sınırlar ve K03 ile keşiften önce donar. D124'ün konuya özgü WSN sütunları yeni alanlara taşınmadığından aşağıdaki içerik uyarlaması gerekir; ölçütlerin sayısal eşikleri değişmez. R9 çiftleri `Denklem` sütunundan §4.4 kuralıyla çıkarılır; kit bir sütunu bu adla tanımaz.

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

Yürütücü keşiften önce yalnız izlenen depo belgelerini tarayarak envanteri tamamlar (K03); canlı kütüphaneyi ve ana checkout'un `.local` dizinini okumaz. Eski korpusların her kaynak/sürümü için normalize DOI (`doi`, `published_doi`, `linked_doi` dahil; URL öneki temizlenmiş, küçük harf), sağlayıcı/eser kimliği, arXiv sürüm ilişkisi ve diğer kayıtlı sürüm bağları, yüklenmiş dosyanın SHA-256 değeri ayrı tutulur. Yalnız başlık benzerliği kimlik doğrulaması sayılmaz.

İlk rapor isteğinden önce yeni korpusun bütün dahil kaynakları ve bunların kayıtlı sürüm ilişkileri bu envanterle kesiştirilir. Boş kesişim, ancak karşılaştırma envanterinin kapsadığı kimlikler için `bağımsız (kimlik düzeyinde)` sonucudur. Bir kaynağın DOI'si yok ve başka kimliği/sürüm ilişkisi de doğrulanamıyorsa o kaynak `bağımsızlık doğrulanmadı` alır. Eski korpusların tam kimlikleri veya yüklenmiş dosya hash'leri erişilebilir değilse ilgili boyutun denetlenmediği yazılır; yalnız konu farklı diye tüm bağımsızlık doğrulandı denmez. **K03 kararı:** H9 eksiksiz bir eski-korpus manifestini beklemez; sahip böyle bir manifest sağlamayacağı için beklemek H9'u süresiz durdururdu. Envanter yalnız izlenen depo belgelerinden kurulur (canlı kütüphane ve ana checkout'un `.local` dizini okunmaz). Bilinen kimlik/sürüm örtüşmesi kaynağı dışlar. Envanterin kapsamadığı boyutlar (ör. eski yüklenmiş dosyaların SHA-256 değerleri, belgelerde yazılmamış eski kimlikler) `denetlenmedi` yazılır; eşleştirilemeyen yeni kaynak `bağımsızlık doğrulanmadı` alır. Bu, kabul edilmiş bir ölçüm sınırıdır ve nihai sonuçta korunur.

Kesişimli kaynak rapor korpusuna giremez. Hazırlık tavanı içinde kurala uygun değişim yapılırsa kayda girer; eski gözlemler silinmez. Yeni korpus ilk gözlemden sonra yanmış sayılır; aynı kümenin ikinci rapor ölçümü bağımsız ölçüm olarak sunulamaz.

## 3. Rapora hazır tablo kapısı (plan §7, kural 3)

Tabloda 6-10 ayrı eser, yedi etkin sütun ve her satırda saklı metin bulunmalı; ürünün `report_ready.ready` değeri `true` olmalı, eksik/başarısız hücre kalmamalıdır. `continue_with_failed` kullanılmaz. Metni olması doldurmanın başarılı olacağını kanıtlamaz. `not_found_in_inspected_scope` kaynakta genel yokluk demek değildir; `inaccessible` veya başarısız hücreyi kabul edilebilir kanıta çevirmeyin. Metinli satır, bulundu/tekil/tarandı/dahil/incelendi/modele verildi/atıf yapıldı sayımlarını birleştirmeye izin vermez.

Kapı geçmez ve hazırlık hakkı kalmazsa rapor POST'u yapılmaz: `başlatılan rapor=0`, R1-R11 ve P19 `ölçülmedi: rapor başlamadı`, okur yok. D124'teki gibi 0/1 tamamlanma yazılmaz; payda hiç oluşmamıştır.

## 4. Rapor öncesi dondurma (plan §7, kural 4)

### 4.1 K01-K12 kararları

Her satır **Claude Opus 5.5 + gpt-6.1-sol medium tarafından, 3 Ekim sürekli talimatı uyarınca sahip adına** kararlaştırıldı (Sol medium, salt okunur, tek tur: K02, K04, K06-K08, K10-K12 aynen; K01, K03, K05, K09 ve H8 istisnası değişiklikle; sonuç “hazır”). Sahip tek tek onaylamadı. Kayıt: [D171](../decisions.md). Hazırlıktan türeyen kimlikler §4.4'teki ayrı kayıt tablosuna girer.

| Alan | Karar | Gerekçe ve sınır |
|---|---|---|
| K01 / yürütme yetkisi | §0'da alıntılanan kampanya ve sürekli talimatlar, K02-K12 içinde sınırlı H9 hazırlığını ve tek rapor koşusunu yetkilendirir; değiştirilmemiş protokol kartını yürütücünün onaylaması dahil. Keşiften önce: ortak kararlar (D171), §0'daki H8 istisnası, 1. dondurma commit'i ve “hazır” incelemesi. Rapordan önce: 2. dondurma commit'i ve “hazır” incelemesi. | Devredilmiş yetki rutin sahip onayını kaldırır; planın H8 ön koşulunu kendiliğinden kaldırmaz, bu yüzden istisna ayrıca yazıldı. Ek model, konu, bütçe ya da canlı veri erişimi yeni kayıtlı Claude+Sol medium kararı ister. |
| K02 / konu | Q1, §1.1'deki metin kelimesi kelimesine; iki hazırlık denemesinde de aynı. | §2 dışlama listesinin dışında; sahibin alanına (enerji sistemleri, optimizasyon) yakın; formülasyon eksenleri yedi sütuna uyuyor. Yeterli erişilebilir kaynak bulunacağı doğrulanmadı. |
| K03 / korpus ve sütunlar | §1.2, §1.3 ve §2 yazıldığı gibi: en çok 10, asgari 6 metinli eser; yedi `text` sütunu; seçim sırası; deneme başına en çok 30 işlik bir kuyruk geçişi. Kuyruk kararını `claude-opus-5-5` (`medium`) yalnız saklı metinden verir: deneme başına en çok bir istek, toplam en çok 2 istek / 30 dk, ayrı defter, 240 dk hazırlık saatine dahil; okunamayan iş karara bağlanmamış kalır, yerine istek açılmaz. Eski-korpus envanteri yalnız depo belgelerinden; eksik boyut `denetlenmedi`, eşleşmeyen kaynak `bağımsızlık doğrulanmadı`. | Sahip kuyruğu okuyamaz ve manifest sağlamaz; beklemek H9'u süresiz durdururdu. Yanlış “person” etiketi ve seçilim etkisi sonuçta açıkça yazılır (§1.2). Ek istek sınırı kuyruk seçiminin model çağrısı bütçesini kapatır. |
| K04 / hazırlık bütçesi | Toplam en çok 2 keşif+doldurma denemesi; ikisi birlikte 300 uygulama model oturumu / 240 dk; her doldurma en çok 60 oturum / 60 dk, birleşik tavana dahil. Kuyruk, PDF ve 10 dk timeout beklemesi süreye dahil; kota beklemesinde saat durmaz. | 300/240 planın sayısal şartı değildir; L9 ölçeğine dayanan muhafazakâr değer. K03 kuyruk istekleri uygulama oturumu sayılmaz ama saate dahildir. |
| K05 / bağlantı, model ve sunucu ortamı | Hazırlık ve rapor: `codex` / `gpt-5.6-luna`. Sunucu ortamı ve kesin komut aşağıdaki tabloda. Codex home: canlı `codex-home` için dar istisna (aşağıda). Sağlayıcı anahtarları: yalnız anahtarsız kaynaklar; null keyring, `.env` yok. | Plan §7 kural 4, S10 ve D124-D128 ile aynı model. Makinede ayrı, oturum açılmış bir DEIXIS Codex home'u bulunamadı (D171). Kota/yük hazırlıkta §5 ile, raporda durma kuralıyla ele alınır; sessiz alternatif yok. |
| K06 / efor | Uygulama modeli reasoning effort `medium`; keşif eforu `standard`. | Ayrı ayarlardır; rapor modeliyle birlikte kaydedilir. Kuyruk ve okur eforları K03/K09'da. |
| K07 / rapor bütçesi | Tek rapor koşusu; 60 uygulama model oturumu / POST'tan itibaren 90 dk, bekleme dahil. | Plan ve D128 ile aynı. Durma tavanıdır, beklenti veya parasal üst sınır değildir; ürünün 50 çağrılık tabanı izleme sınırıyla karıştırılmaz. |
| K08 / durdurma | §5 yazıldığı gibi: saklı kök neden kuralı; hazırlıktaki her uygulama koşusunda ve raporda en çok bir `client_timeout` sürdürmesi (10 dk sonra); 120 s kapanış gözlemi. | Başka/karışık neden, ikinci timeout, sayaç hatası veya dolan tavan durdurur. İptal etkili olmadan önce izlenen tavanı aşan uçuştaki çağrılar ayrıca yazılır. |
| K09 / okurlar ve örnekleme | İlk okur: yürütücü analist `claude-opus-5-5`, efor `medium`, kör değil; okuması K10'a sayılır. İkinci okur: `claude-sonnet-5-5`, efor `medium`, ayrı ve yeni oturum: depo dışı boş dizinde `claude -p --model claude-sonnet-5-5 --effort medium --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence` (önceki konuşma, araç, MCP ve proje talimatı yok; ayrıntı [istem](p9r-report-prompt.md) §5); yalnız kitin kör paketi ve izinli kaynak ekleri, paket §4.3'ün eşitlik denetiminden geçtikten sonra; ilk okur hükümleri, kontrol etiketleri veya beklentiler verilmez. Tohum `20261003` (R2 örneği ve kontrol seçimi), karıştırma tohumu `20261004`; §4.3 okunamadı kuralı. İstenen ve dönen model kimlikleri kaydedilir; model yoksa veya uyuşmazsa ilgili okuma yerine model konmadan durur. | Her ikisi kayıtlı model değerlendirmesidir, bağımsız insan doğrulaması değildir. Okur şirketi (Anthropic) rapor modelinin şirketinden (OpenAI) farklıdır. Körlük yalnız verilen malzeme ilk okur hükümlerini dışlarsa geçerlidir. |
| K10 / okuma bütçesi | Rapor dışı okur model istekleri en çok 4 / toplam 60 dk; uygulama oturumlarından ve K03 kuyruk isteklerinden ayrı defter. | Eksik okuma varsa tavan artırılmaz, ilgili satır ölçülemedi kalır. Böylece hazırlık+rapor için 360 uygulama oturumu, en çok 2 kuyruk isteği ve en çok 4 okur isteği yetkilidir; toplam parasal maliyet bilinmez. |
| K11 / ürün | `87cee0ba4e566ef311c07007d8b50ce7eb0a5086` (rebase bittiği anda `origin/main` başı; D129, D168-D170, D183, D192, D193 içinde; ilk sabitleme `3215b3a` idi, koordinatör kararıyla yeniden sabitlendi). Runtime `skill_package_hash` `sha256:5ba2d214bd1122f9544aaa537226b6234123bf6be82b3e6e1c6d9ff99dcf75ff`, bütünlük sorunları `[]` (§6). İki kapıda yeniden hesaplanır ve eşit olmalıdır. | Sabitlenen commit'ten sonra main'e giren batch'ler ölçülen ürünün parçası değildir; koşu bu commit'teki detached ölçüm worktree'sinde yürür, sonraki push'lar onu değiştiremez. Main yeniden kovalanmaz. Dondurma commit'i bu commit'in torunu olmalı ve bu commit'i adlandırmalıdır (§6.1). `3215b3a`'dan bu commit'e hash'ler, kit, şemalar, yöntem paketi ve K05'in okuduğu dosyalar (`config.py`, `credentials.py`, `paths.py`, `models/`, `uv.lock`, `pyproject.toml`) değişmedi. |
| K12 / belge commit'i ve inceleme | Dondurma belgelerini Claude (Opus 5.5) yazar; her dondurma noktası için belge worktree'sinde (`DEIXIS-h9`) bir commit, push yalnız koordinatörce. **Uzatma (yalnız 1. nokta):** 3. turdan sonra Claude Opus 5.5 + gpt-6.1-sol medium ortak kararıyla en çok 2 ek high tur (4. ve 5.), aynı kurallarla; 5. turda da “hazır” yoksa yeni ortak karar olmadan uzatma yok; 2. nokta 3 tur sınırını korur. Her noktada `gpt-6.1-sol` / `high`, salt okunur, en çok 3 tur; her high/medium bulgu işlenir ve yeniden incelenir; turlar, hükümler ve çözülmemiş bulgular kayda. | Yazan ve inceleyen farklı şirketin modeli. 3 turda “hazır” yoksa o kapı bekler; ne yürütme yetkisi doğar ne model değişimi. İnceleme maliyeti H9 bütçelerinin dışındadır. |

**K05 sunucu ortamı.** Değerler `backend/deixis/config.py`, `credentials.py`, `paths.py` ve `models/adapter.py` ile doğrulandı. Süreç `env -i` ile yalnız aşağıdaki değişkenlerle başlatılır; varsayılanı seçilen değer bile açıkça yazılır. Ölçüm ağacı `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run` worktree'sidir: 2. aşamanın başında `git -C /Users/huguryildiz/Documents/GitHub/DEIXIS worktree add --detach ../DEIXIS-h9run 87cee0ba4e566ef311c07007d8b50ce7eb0a5086` ile kurulur, HEAD koşu boyunca sabitlenen ürün commit'idir; içinde commit atılmaz, checkout yapılmaz. Belge commit'leri yalnız `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9` worktree'sinde atılır.

| Ortam alanı | Dondurulan değer |
|---|---|
| `DEIXIS_DATA_DIR` | `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.local/p9r-h9/data`: ilk başlatmadan önce yok ya da boş; gerçek yolu aynı olmalı, canlı dizine sembolik/sabit bağlantı yok. |
| `DEIXIS_HOST`, `DEIXIS_PORT` | `127.0.0.1`; `8873`. 8873'ü bilinmeyen bir süreç tutuyorsa yalnız önceden bildirilmiş `8874` kullanılır; bilinmeyen süreç durdurulmaz; ikisi de doluysa H9 başlamaz. İkisi de 8765, Playwright 8777-8824, fixture 8820-8822 ve kapasite 8900+ aralıkları dışında. |
| `DEIXIS_REPO_ROOT`, `PYTHONPATH`, `PYTHONDONTWRITEBYTECODE` | `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run`; `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/backend:/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run`; `1`. |
| `DEIXIS_CODEX_HOME` | `/Users/huguryildiz/Library/Application Support/DEIXIS/codex-home`. **Dar istisna (K05, Claude+Sol medium):** yalnız bu alt dizin ve yalnız izole sunucunun Codex adapter'ı için; olağan CLI kimlik doğrulaması ile oturum/durum dosyası yazımı dahil. Yürütücü canlı veri dizininde başka hiçbir şeyi listelemez, okumaz, kopyalamaz, yazmaz; port 8765'e dokunmaz. Başlamadan önce yalnız dizinin var olduğu denetlenir (`test -d`); kimlik bilgisi okunmaz, kopyalanmaz, login başlatılmaz. Bağlantı hazır değilse `H9 başlamadı: Codex girişi yok` yazılır ve başka home denenmez. Koordinatör H9 sırasında başka bir Luna işinin (ör. P8 B4) koşmadığını teyit eder; kota sahibin canlı DEIXIS kullanımıyla paylaşılır. **H9 sunucusu, bu home'u kullanan port 8765'teki hiçbir şeyle (canlı DEIXIS sunucusu) aynı anda çalışmaz;** başlangıç ön koşulu, koordinatör kuralı ve sonraki denetimler §4.1.1'dedir. `~/Library/Application Support/DEIXIS` altında `codex-home` dışında hiçbir şey okunmaz ve yazılmaz. |
| `DEIXIS_PROTOCOL_APPROVAL` | `ask`; kart yürütücü tarafından değiştirilmeden onaylanır. Ürünün kaydı `mode=ask`, `approved_by=user`; onaylayanın yürütücü model olduğu sonuçta açıklanır (§1.2). |
| `DEIXIS_FULLTEXT_FETCH`, `DEIXIS_FULLTEXT_ADJUDICATION` | `auto`, `auto`. |
| `DEIXIS_CITATION_CHAINING`, `DEIXIS_SEARCH_QUERY` | `auto`, `model`. |
| `DEIXIS_ARXIV_SOURCE`, `DEIXIS_QUERY_STRATEGY` | `off`, `legacy` (`config.py` yükleme değerleri); `sw` araştırma seçimi ayrıca kaydedilir. |
| `DEIXIS_MODEL_CONCURRENCY` | `6`; sunucunun bildirdiği değer kaydedilir. |
| `DEIXIS_CONTACT_EMAIL` | Ayarlanmaz (kişinin adresi yeni bir yere açılmaz). |
| `PATH`, `HOME`, `USER`, `LOGNAME`, `LANG` | `/opt/homebrew/bin:/usr/bin:/bin` (Codex: `/opt/homebrew/bin/codex`, codex-cli 0.160.0, Mach-O arm64; sürüm başlangıçta yeniden kaydedilir); `/Users/huguryildiz`; `huguryildiz`; `huguryildiz`; `en_US.UTF-8`. |
| Sağlayıcı anahtarları | **Yalnız anahtarsız.** `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` (keychain okunmaz); `OPENALEX_API_KEY`, `S2_API_KEY`, `NCBI_API_KEY`, `IEEE_API_KEY`, `SCOPUS_API_KEY`, `CORE_API_KEY`, `SERPAPI_API_KEY` ve model anahtarları ayarlanmaz. `load_settings` önce etkin depo kökünün `.env` dosyasını yüklediği için her başlatmadan önce `DEIXIS_REPO_ROOT`'un bu worktree olduğu ve `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.env` dosyasının bulunmadığı (`test ! -e`) denetlenir; varsa dosya okunmadan durulur. Sonuç: OpenAlex, Semantic Scholar, PubMed, OpenAlex üzerinden bioRxiv ve diğer anahtarsız kaynaklar anahtarsız sınırlarla çalışır; IEEE Xplore, Scopus, CORE ve SerpApi `not_configured` olur. Sağlayıcı hataları kaydedilir, telafi edilmez. Codex girişi bir API anahtarından çıkarılmaz. |

Kaynak, eksik giriş veya farklı ortam nedeniyle hazır değilse başka home/anahtar/model denenmez; yürütücü credential kopyalamaz, login başlatmaz. Kesin başlatma komutu (port yalnız 8874 ile değişebilir; protokole yer tutucusuz yazılır). Bu commit'te çalıştırılmadı; §6.2'nin modelsiz sağlık bloğu bu sunucunun başlangıç kaydı değildir.

```sh
cd /Users/huguryildiz/Documents/GitHub/DEIXIS-h9run || exit 1
: "${H9_FREEZE_COMMIT:?Push edilmiş dondurma commit'i gerekli}"
test "$(git rev-parse HEAD)" = 87cee0ba4e566ef311c07007d8b50ce7eb0a5086 || exit 1
git merge-base --is-ancestor 87cee0ba4e566ef311c07007d8b50ce7eb0a5086 "$H9_FREEZE_COMMIT" || exit 1
test ! -e /Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.env || exit 1
test -d "/Users/huguryildiz/Library/Application Support/DEIXIS/codex-home" || exit 1
test -x /Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.venv/bin/python && test ! -L /Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.venv || exit 1
h9_port_8765_free() {
  /Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.venv/bin/python -c 'import datetime, json, subprocess, sys
rec = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat()}
try:
    r = subprocess.run(["/usr/sbin/lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN", "-Fp"],
                       capture_output=True, timeout=10)
    rec.update(returncode=r.returncode, stdout=r.stdout.decode(errors="replace"),
               stderr=r.stderr.decode(errors="replace"))
    ok = r.returncode == 1 and not r.stdout and not r.stderr
except Exception as exc:
    rec.update(exception=repr(exc)); ok = False
    for k in ("stdout", "stderr"):
        v = getattr(exc, k, None)
        if v is not None:
            rec[k] = v.decode(errors="replace") if isinstance(v, bytes) else str(v)
rec["free"] = ok
print(json.dumps(rec))
sys.exit(0 if ok else 1)'
}
mkdir -p /Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.local/p9r-h9/evidence || exit 1
h9_check=/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.local/p9r-h9/evidence/port-8765-$(date -u +%Y%m%dT%H%M%SZ).json
h9_port_8765_free > "$h9_check"; h9_free=$?
test -s "$h9_check" || exit 1
test "$h9_free" -eq 0 || exit 1
exec env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/huguryildiz USER=huguryildiz \
  LOGNAME=huguryildiz LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/backend:/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run DEIXIS_REPO_ROOT=/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run \
  PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring \
  DEIXIS_DATA_DIR=/Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.local/p9r-h9/data DEIXIS_HOST=127.0.0.1 DEIXIS_PORT=8873 \
  DEIXIS_CODEX_HOME="/Users/huguryildiz/Library/Application Support/DEIXIS/codex-home" \
  DEIXIS_PROTOCOL_APPROVAL=ask DEIXIS_FULLTEXT_FETCH=auto DEIXIS_FULLTEXT_ADJUDICATION=auto \
  DEIXIS_CITATION_CHAINING=auto DEIXIS_SEARCH_QUERY=model DEIXIS_ARXIV_SOURCE=off \
  DEIXIS_QUERY_STRATEGY=legacy DEIXIS_MODEL_CONCURRENCY=6 \
  /Users/huguryildiz/Documents/GitHub/DEIXIS-h9run/.venv/bin/python -m deixis serve --port 8873 --no-browser
```

Her ön koşul başarısızlıkta kabuğu sonlandırır; sunucu yalnız hepsi geçerse `exec` ile başlar. `h9_port_8765_free` sonucunun zamanı, çıkış kodu ve çıktıları `protocol.md`'ye yazılır (§4.1.1). Bu blok, §6.1 betiğinin ölçüm worktree'sinde aynı `H9_FREEZE_COMMIT` ile geçtiği kaydedildikten sonra çalıştırılır. 8874 kullanılırsa `DEIXIS_PORT` ve `--port` değeri `8874` olur.

#### 4.1.1 Port 8765: başlangıç ön koşulu ve koordinatör kuralı

Bu alt bölüm, H9 sunucusunun canlı `codex-home`'u port 8765'teki canlı sunucuyla aynı anda kullanmaması için tek ve bağlayıcı yoldur. Otomatik nöbet, gözetmen, sinyal veya yeniden başlatma mantığı yoktur.

1. **Başlangıç ön koşulu (kapalıya düşer).** Sunucu başlatılmadan hemen önce başlatma bloğundaki `h9_port_8765_free` çalışır: `/usr/sbin/lsof -nP -iTCP:8765 -sTCP:LISTEN -Fp`, ölçüm worktree'sinin Python'u içinden `subprocess.run(capture_output=True, timeout=10)` ile. Yalnız sürecin kendi çıkış kodu 1, boş standart çıktı ve boş hata çıktısı "dinleyici yok" sayılır. Dinleyici görülmesi, `lsof`'un bulunmaması, başlatma hatası, zaman aşımı, başka çıkış kodu veya herhangi bir hata çıktısı başlatmayı reddeder. Port 8765'e bağlanılmaz. İşlev zamanı, `lsof`'un kendi çıkış kodunu veya istisnayı, iki çıktı akışını ve kararı tek bir JSON kaydı olarak basar; başlatma bloğu bunu `exec`'ten önce `.local/p9r-h9/evidence/port-8765-<UTC zaman>.json` dosyasına yazar, dosya boşsa veya karar "serbest" değilse başlatmaz. Kaydın yolu `protocol.md`'ye geçirilir. Sonraki denetimler aynı işlevi aynı biçimde kaydeder.
2. **Koşu boyunca kural.** Otomatik izleyici yoktur. Sunucu başladıktan sonra, sunucu PID'si ve o anda `pgrep -P <sunucu PID>` ile görülen `codex app-server` alt süreçleri `ps -o pid=,lstart=,command=` ile kaydedilir; her hazırlık denemesinin başında, rapor POST'undan önce ve herhangi bir durdurmadan hemen önce (sunucu hâlâ canlıyken) bu envanter yenilenir. Çıkış doğrulaması yalnız bu kayıtlı kimliklere bakar; boş bir `pgrep -P` sonucu tek başına çıkış kanıtı değildir. Koordinatör oturumu, H9 sunucusu başlatıldığı andan sunucunun ve Codex adapter alt süreçlerinin (`pgrep -P <sunucu PID>` ile görülen `codex app-server` süreçleri) çıktığı doğrulanana kadar kimsenin port 8765'te sunucu başlatmamasını güvence altına alır; çıkış doğrulanamazsa dışlama koordinatör karar verene kadar sürer ve yeniden başlatma yoktur; sahip uzakta ve beklenmemesini istedi. Kural koordinasyon dosyasında (`/tmp/deixis-coordination.md`, 3 Ekim 09:40 satırı) yazılıdır ve 2. aşama başında tarihli olarak `protocol.md`'ye alınır.
3. **Sonraki denetimler.** Aynı `h9_port_8765_free` denetimi, salt okunur olarak, her hazırlık denemesinin başında, rapor POST'undan hemen önce ve nihai snapshot'tan önce yinelenir ve kaydedilir. Bu denetimlerden biri "dinleyici yok" vermezse (dinleyici ya da başarısız denetim) koşu elle durdurulur: etkin koşunun kendi API'siyle iptali en çok 10 s süreli bir denemedir; başarısızlığı veya zaman aşımı, yürütücünün başlattığı H9 sunucu sürecine SIGTERM gönderilmesini engellemez. SIGTERM bir istektir, sonlandırma kanıtı değildir: en çok 120 s boyunca, her biri en çok 5 s süreli `ps -p <pid> -o lstart=` yoklamalarıyla, sunucunun ve SIGTERM'den önce kaydedilmiş alt süreçlerin (aynı PID ve aynı başlangıç zamanıyla) artık görünmediği doğrulanır ve kaydedilir. Süre dolarsa, bir yoklama başarısız olursa, envanter eksikse veya sunucu durdurmadan önce beklenmedik biçimde çıkmışsa sonuç `çıkış doğrulanmadı` olur: dışlama koordinatör karar verene kadar sürer, yeniden başlatma yoktur, SIGKILL veya başka otomatik sinyal gönderilmez. Ölçüm **geçersiz** diye kaydedilir ve onarılmaz: sunucu bu ölçüm için yeniden başlatılmaz, hazırlık sürdürülmez, rapor alınmaz; bütün R-satırları ve P19 `ölçülemedi: geçersiz (8765 dinleyicisi veya başarısız denetim)` olur. O ana kadarki kayıtlar silinmez.
4. **Sınır.** Bu denetimler bir algılamadır, kesin karşılıklı dışlama değildir: iki denetim arasında başlayıp biten bir canlı sunucu görülmez. Dışlamayı koordinatör kuralı sağlar; ölçüm bunun kanıtını içermez, yalnız denetim kayıtlarını içerir.

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

**İlk okurun yazabileceği alanlar.** İlk okur `review.md`'de yalnız şunları değiştirir: `Reader:` satırı (`claude-opus-5-5 · medium · model okuması`); birimlerdeki `- [ ]` kutuları (`- [x]`); kitin istediği sayı alanları, R5 `Other names found: <n>` ve R11 `Missing passage count: <n>`; ve kitin şablonuyla eklenen R3 `#### M<n> · <bölüm> · <cümle> · cells: <...>` birimleri, yalnız başlık satırı ve kitin R3 kutu listesiyle. R6'nın `Page examined:` ve `Error kinds:` alanları kitçe okunmaz ve ikinci pakete kopyalanır; boş bırakılır, içerikleri notlara yazılır. Gerekçe, not veya başka metin `review.md`'ye eklenmez; `.local/p9r-h9/evidence/reader1-notes.md` dosyasına yazılır. Kitin `second` adımı birim gövdesini yalnız işaretleri temizleyerek kopyaladığı için (`measure_report.py`, `second`), ilk okumadan önce `review.md`'nin değişmemiş kopyası `review.orig.md` olarak saklanır. İkinci paket verilmeden önce salt okunur bir betik şunu denetler: `second.md`'deki her birim `review.orig.md`'de varsa gövdesi, kitin kendi serileştirmesiyle, yani sondaki boşluk ve satır sonları atılmış (`rstrip`) hâliyle oradaki gövdenin `rstrip` hâline bayt bayt eşittir; başlık, kanıt ve kutu metni dahil başka hiçbir fark kabul edilmez. Yoksa (eklenen R3 `M<n>`) gövdesinin `rstrip` hâli yalnız başlık satırı, boş satırlar ve kitin işaretsiz R3 kutu listesinden oluşur ve `review.md`'deki aynı birimin kutuları temizlenmiş, `rstrip` uygulanmış hâline eşittir. Eşit değilse ikinci okuma başlamaz ve fark kaydedilir.

**İkinci okurun yanıtının aktarımı.** Kör paket, `second.md`'nin işaretsiz kopyası (`second.blank.md` olarak saklanır) ve şu yönergedir: her birim için tek satır JSON, `{"group": "<R2|R3|R4b|R6|R9>", "unit": "<birim kimliği>", "choice": "<o grubun kutu metinlerinden biri, aynen>"}`; başka yorum serbesttir ama aktarılmaz. Ham yanıt `reading2-raw.md` olarak saklanır. Deterministik bir betik `second.blank.md`'den yeni `second.md` üretir: `Reader:` satırına `claude-sonnet-5-5 · medium · model okuması` yazar, her geçerli satır için o birimde yalnız seçilen kutuyu `- [x]` yapar; başka hiçbir metni değiştirmez. Bilinmeyen birim, gruptan olmayan seçim, aynı birime iki farklı seçim veya eksik birim aktarılmaz ve listelenir. R6'nın `Page could not be opened (no verdict)` seçimi kitin izinli seçimidir ve aktarılır (yukarıdaki okuma-anı istisnası); diğer gruplarda hükümsüz bir seçim yoktur. Eksik ya da geçersiz birimler için K10 bütçesi içinde, yeni ve ayrı bir oturumda yalnız o birimleri içeren tek bir tamamlama isteği yapılabilir. Hâlâ eksik varsa ikinci okuma `ölçülemedi: eksik yanıt` olur; kit bu durumda `score` adımını reddeder ve okura bağlı satırlar (R2, R3, R4b, R6, R9) `ölçülemedi` yazılır, otomatik satırlar korunur. Aktarımdan sonra `score` öncesi birim kimlikleri ve kanıt metninin `second.blank.md` ile aynı kaldığı yeniden denetlenir.

İkinci okur R2/R3/R4b/R6/R9'un ilk okurca olumsuz işaretlenmiş bütün birimlerini ve **her ölçüt sayfası için ayrı** en çok 5 destekleyen kontrol birimini görür. Kit kontrol seçimi için aynı tohumu, karıştırma için `20261004` kullanır; olumsuz/kontrol kimliği ve ilk hükümler ikinci pakette görünmez. R5 ve R11 D124'teki gibi ilk okurun tam okumasıdır, ikinci okuma yapıldı varsayılmaz. Birim iki okurdan biri ciddi diyorsa ciddidir; anlaşmazlık sayısı yazılır.

**Okunamadı yolu, kitle uyumlu.** Kitin içindeki tek okunamadı yolu snapshot anında kitin yazdığı durumdur: R2/R9 için `Status: not_readable · <neden>` (R9 ayrıca `no_input_equation`), R6 için `page_not_openable`. Bu birimler hükümsüz kalır, ikinci çekiliş ve değerlendirme paydasından çıkar, ayrı sayılır (kit `manifest.json` muafiyeti). Tek okuma-anı istisnası kitin kendi R6 kutusudur: denklemin PDF sayfası okuma sırasında açılmazsa her iki okur da `Page could not be opened (no verdict)` kutusunu seçebilir; kit bunu paydadan çıkarır ve ayrı sayar (`measure_report.py`, `_human_metric`), bu seçimlerin sayısı sonuçta R6 yanında yazılır. Bunun dışında okur, kitin okunabilir saydığı zorunlu bir birimi okuma sırasında değerlendiremezse (gösterilen metin yetersiz vb.) kutu işaretlemez, uydurma hüküm vermez, `review.md`'ye durum satırı eklemez ve manifesti değiştirmez; birimi grup, kimlik ve nedeniyle `.local/p9r-h9/evidence/reading-exceptions.json` dosyasına yazar. Kit bu durumda `second`/`score` adımını reddeder; ret korunur. O zaman okura bağlı bütün satırlar (R2, R3, R4b, R6, R9 ve ikinci okuma) `ölçülemedi: okuma istisnası (N birim)` yazılır; otomatik satırlar (R1, R4a, R7, R8, R11'in kesilme sayısı, P19) korunur. Kit dışında yedek bir puanlama yapılmaz. Sıfır payda ölçülemedi; erişilemeyen kayıt sıfır hata değildir. Eksik/çift işaret, silinmiş birim/kutu veya ikinci kimlik uyuşmazlığı varsa kitin ret yolu korunur. R5/R11 eksik okuması sonuç üretmez. Okur veya bütçe bulunamazsa eksik metrikler ölçülemedi kalır; eşik, okur veya model sonradan değiştirilmez.

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

Yalnız bütün terminal kök nedenler `client_timeout`, tek sürdürme hakkı kullanılmamış ve bütün tavanlarda yer varsa aynı koşu 10 dk sonra bir kez sürdürülür. Bu bekleme süre bütçesine dahildir. Kota/yük, model uyuşmazlığı, araç ihlali, başka veya karışık hata, ikinci timeout, `budget_exhausted`, okunamayan sayaç veya dolan tavan durdurur. K08: hazırlıktaki her uygulama koşusunda da en çok bir timeout sürdürmesi; hazırlık denemesi ve birleşik sayaç bu sürdürmeyle sıfırlanmaz. Hazırlık sırasında kota/yük duruşu o denemeyi bitirir; aynı deneme kota için sürdürülmez. Kalan deneme hakkı yalnız birleşik 300 oturum/240 dk tavanı içinde ve ana oturum bağlantının geri geldiğini tarihli kayda geçirdikten sonra kullanılabilir. Beklemede saat durmaz; deneme hakkı veya bütçe kalmazsa sonuç `korpus hazırlanamadı` olur. Yeni deneme §1.2'deki aynı veri dizini/yeni `sw` kuralına uyar; sessiz model değişimi yoktur. Rapor sırasında kota/yük duruşu tek rapor koşusunu bitirir.

Başka kök nedenle durması gereken koşu hâlâ çalışıyorsa yalnız ölçümü sonlandırmak için kendi API iptal yolu kullanılır. Zaten duraklamış/terminal koşunun durumu korunur. Hücre, kaynak, bölüm, plan, ürün, yöntem, şema veya doğrulayıcı değişmez. Düzeltme ayrı slice'a gider; sonraki ölçüm başka yeni korpus ister.

Nihai snapshot, yürütücünün döndüğü zaman kaydı ve **sıfır `started` model oturumu** birlikte doğrulanınca alınır. Kalıcı `running` adım etiketi sabitlenme kanıtı değildir. Kapanış gözlem süresi en çok 120 s (K08); bitiş doğrulanamazsa nihai durum iddiası kurulmaz, R1/R7/P19 kayıt anındaki durum diye etiketlenir. Tavan iki poll arasında aşılırsa uçuşta aşan çağrılar ayrıca sayılır; izleme sert üst sınır garantisi değildir.

Rapor durduysa yalnız R1, R7 ve P19 korunur (§4.1.1 madde 3 ile geçersiz sayılan ölçümde hiçbiri korunmaz); R2-R6/R8/R9/R11 `ölçülemedi: run_incomplete`, R10 tasarım gereği ölçülmedi olur. R7 ana süre `created_at`/`updated_at` tanımını korur; saptama, iptal, son oturum ve kapanış beklemesi ayrı kaydedilir. Durmuş koşunun kısa süresi hız/maliyet kanıtı değildir. Kapanış doğrulanmamışsa P19 da kayıt anındaki sayım diye etiketlenir.

## 6. Model-free ön koşullar: çalıştırılabilir komutlar (plan §5 H9; §7 kural 4-5 sonrası kuru başlangıç şartı)

Bu komutlar sunucu başlatma yetkisi vermez; kaynak/hash kontrolü uygulamayı açmaz. Her iki dondurma noktasında, ölçüm worktree'sinde (`DEIXIS-h9run`, HEAD = sabitlenen ürün commit'i) ve onun kendi native arm64 Python 3.12 ortamında çalıştırılır; `H9_FREEZE_COMMIT` o noktanın push edilmiş belge commit'idir. `.venv` ölçüm worktree'sinde `UV_CACHE_DIR=/tmp/deixis-uv-cache uv sync --frozen` ile kurulur (başka bir checkout'un `.venv`'ine bağlantı kullanılmaz, çünkü o ortam ölçüm sırasında değişebilir); `.venv/bin/python -c "import platform; print(platform.machine())"` `arm64` vermelidir.

### 6.1 Commit, D129 çağrı yolu, yöntem ve kit

Donmuş değerler: `H9_PRODUCT_COMMIT=87cee0ba4e566ef311c07007d8b50ce7eb0a5086`, `H9_SKILL_HASH=sha256:5ba2d214bd1122f9544aaa537226b6234123bf6be82b3e6e1c6d9ff99dcf75ff`, 22 dosyalık şema manifestinin SHA-256 değeri `7ac32dcdd77ab06b135a54596387cdfa6213237f27ecce923728f95948adcc52` (her satır `<dosya adı> <sha256>`, ada göre sıralı, `\n` ile biten). `H9_FREEZE_COMMIT` o noktanın push edilmiş belge commit'idir; ürün commit'inin torunu olmalı, `origin/main`'de bulunmalı ve freeze belgesi bu ürün commit'ini adlandırmalıdır. Dondurma commit'i ile ürün commit'i arasındaki başka batch'lerin değişiklikleri ölçülmez (§0). Ölçüm worktree'sinde HEAD ürün commit'idir; izlenen dosyalarda fark, izlenmeyen dosya veya izinli kümenin dışında yok sayılan dosya kabul edilmez.

```sh
: "${H9_FREEZE_COMMIT:?Push edilmiş dondurma commit'i gerekli}"
export H9_FREEZE_COMMIT
export H9_PRODUCT_COMMIT=87cee0ba4e566ef311c07007d8b50ce7eb0a5086
export H9_SKILL_HASH=sha256:5ba2d214bd1122f9544aaa537226b6234123bf6be82b3e6e1c6d9ff99dcf75ff
export H9_SCHEMA_MANIFEST=7ac32dcdd77ab06b135a54596387cdfa6213237f27ecce923728f95948adcc52
test -x .venv/bin/python && test ! -L .venv || exit 1
test "$(.venv/bin/python -c 'import platform; print(platform.machine())')" = arm64 || exit 1
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python - <<'PY' || exit 1
import os, subprocess, hashlib
from pathlib import Path
from deixis.domain.skill import package_hash, integrity_issues
def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()
product, freeze = os.environ['H9_PRODUCT_COMMIT'], os.environ['H9_FREEZE_COMMIT']
assert git('rev-parse', 'HEAD') == git('rev-parse', product)
subprocess.run(['git', 'fetch', '-q', 'origin'], check=True)
subprocess.run(['git', 'merge-base', '--is-ancestor', '06fa1b6', product], check=True)
subprocess.run(['git', 'merge-base', '--is-ancestor', product, freeze], check=True)
subprocess.run(['git', 'merge-base', '--is-ancestor', freeze, 'origin/main'], check=True)
frozen_doc = git('show', f'{freeze}:docs/product/p9r-report-freeze.md')
assert git('rev-parse', product) in frozen_doc
assert '## D171' in git('show', f'{freeze}:docs/decisions.md')
paths = ['backend', 'apps/web', 'contracts', 'methods', 'scripts', 'tests', 'pyproject.toml', 'uv.lock']
assert not git('diff', '--name-only', product, '--', *paths)
assert not git('ls-files', '--others', '--exclude-standard', '--', *paths)
# Whole tree: tracked files equal HEAD (the pinned product), no untracked file anywhere,
# and ignored entries only from the permitted runtime set (a stray .env or .py fails here).
status = subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=all'], text=True)
assert not status.strip(), status
allowed = ('.venv/', '.local/', 'apps/web/node_modules/', 'apps/web/dist/', '.pytest_cache/',
           'apps/web/test-results/', 'apps/web/playwright-report/')
ignored = git('ls-files', '--others', '--ignored', '--exclude-standard', '--directory').splitlines()
stray = [p for p in ignored if not (p.startswith(allowed) or p.endswith('__pycache__/')
                                     or p.rsplit('/', 1)[-1] == '.DS_Store')]
assert not stray, stray
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
lines = [f'{p.name} {hashlib.sha256(p.read_bytes()).hexdigest()}'
         for p in sorted(Path('contracts/research').glob('*.schema.json'))]
digest = hashlib.sha256(('\n'.join(lines) + '\n').encode()).hexdigest()
print('\n'.join(lines))
print('schema_manifest', len(lines), digest)
assert digest == os.environ['H9_SCHEMA_MANIFEST'], digest
print('product', git('rev-parse', product), 'freeze', git('rev-parse', freeze))
print('skill_package_hash', package_hash())
PY
```

Atalık ve metin varlığı tek başına D129 davranışını kanıtlamaz; aşağıdaki regresyon testleri çağrı sınırını, hücrenin kendi alıntılarını ve kayıtları denetler. Şema manifesti yukarıdaki donmuş değerle karşılaştırılır; eski P16 şema hash'i taşınmaz.

```sh
test -x .venv/bin/python
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. .venv/bin/python -m pytest -q -n 0 \
  -p no:cacheprovider --basetemp=/tmp/p9-h9-preflight-tests \
  tests/test_report_anchor_repair.py tests/test_report_handles.py \
  tests/test_report_failed_rows.py tests/test_report_api.py \
  tests/test_p6_measure_report.py
```

### 6.2 İzole, modelsiz gerçek port sağlık kontrolü

Bu blok 1. kapıdan sonra, gerçek sunucu başlatılmadan önce çalıştırılır ve sonucu `protocol.md`'ye yazılır. Yeni geçici dizin, OS'nin verdiği ayrı loopback portu, boş adapter haritası, kapalı worker ve dış HTTP'yi reddeden transport kullanır. `.env`/keychain yüklenmez. Üretim CLI bağlantı sağlığı veya gerçek model hazır olma durumunu ölçmez. Port 8765'e bağlanmaz, canlı dizini okumaz.

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

**1. dondurma yazılırken (3 Ekim 2026, ilk `3215b3a`, yeniden sabitlemeden sonra `87cee0b` üzerinde, sunucusuz ve modelsiz) doğrulananlar:** `06fa1b6` (D129) ürün commit'inin atası; çağrı bağlamı, akış bağlantısı ve sabit destek yönergesi kaynakta var; kit ve kit testi yukarıdaki SHA-256 değerlerinde, `cdf79ba` ile farkları boş; runtime hash `sha256:5ba2d214…f75ff`, paket bütünlük sorunları `[]` (taslaktaki `a4deebf` hash'i `8e1e4a84…` ve D129 tarihindeki `cef7c086…` artık geçersiz); 22 şema dosyasının manifesti yukarıdaki değerde; §4.2.1 P19 sorgusu `87cee0b`'nin 66 migration'lık şemasında hatasız hazırlanıyor (boş geçici veritabanında `EXPLAIN QUERY PLAN`) ve UTF-8 baytlarının SHA-256 değeri `6d53789f…acd1` ile eşit. Bu kontroller ana checkout'un `.venv`'ine bağlantıyla yapıldı; §6.1'in kendi `.venv` şartı 2. aşamada sağlanır. §6.1 testleri aynı ortamda `87cee0b` + bu belgeler üzerinde 257/257 geçti (sentetik veri, model yok; ürün davranışını gösterir, model kalitesini değil). §6.1 betiği ve §6.2 sağlık bloğu henüz çalıştırılmadı (betik push edilmiş dondurma commit'ini ister); bu bir kuru sunucu başlangıcı kaydı değildir.

## 7. Okuma, sonuç dili ve P9 kaydı (plan §7, kurallar 6-7; R01)

Ham model çıktısı, okuma gerekçeleri, ledger, protocol, poll ve özel kaynak içeriği bu worktree'nin `.local/p9r-h9/` dizininde izlenmeden kalır; runtime kütüphanesi aynı yerdeki `data/` dizinindedir (K05). Sonuç belgesi planın yolu `docs/product/p9r-report-results.md` olur; temizlenmiş özet, commit/hash, tarih, komutlar, sapmalar, değer/payda/örnek/tohum/okur ve ölçülemeyenler içerir. O belge ve sonuç kararı 2. aşamada yazılır.

Sonuç dili: **geliştirme sonrası yeni korpus, tek koşu, tek rapor modeli, rapora hazır tablo koşuluna bağlı**. Okur modelleri ayrıca adlandırılır. Bulunan, tekil, taranan, dahil edilen, incelenen, modele verilen ve atıf yapılan sayıları ayrı verilir. Hazırlıkta yapılan seçimin koşulluluğu açıkça yazılır. D124/D126/D128 kapanmış seri olarak korunur; H9 onun dördüncü denemesi değildir.

R01 isteğe bağlı, gerçek-model satırıdır; R1-R11'in ölçüm durumunu özetler, R10 ölçülmedi kalır. P19 ayrı yardımcı kayıt olarak eklenir, R01'in başarı eşiğine dönüştürülmez. Başarı/başarısızlık yeni bir `decisions.md` kararıyla kaydedilir. P9 bilinen sınır kaydına geçti/geçmedi/kısmen tek satırı eklenir; ayrıntı sonuç dosyasına bağlanır. Sert satırlar okunamadıysa R01'e koşulsuz geçti yazılmaz. H8'in model-free kapanışı H9 sonucuna bağlı değildir (S2). Belge/karar güncellemeleri [istemin](p9r-report-prompt.md) kapsamındadır; commit H9 worktree'sinde, push yalnız koordinatörce (K12).

## 8. H9'un gösteremeyecekleri (plan §5 H9; §7 kurallar 2, 4, 6-7)

H9 başka korpusa/model/efora genellenemez; başarı veya hata oranı, hız ya da maliyet karşılaştırması üretmez. Kayıtlı süre/token sayısı sağlayıcı faturası değildir. D129'un veya tutamaçların nedensel etkisini sınamaz; kontrollü eski/yeni ürün karşılaştırması yoktur. Model okuması bağımsız insan doğrulaması değildir; `structurally_valid` ve bulunan çapa bilimsel anlam desteği sağlamaz.

Keşfin geri çağırımı, literatürün tamamlığı, yenilik/araştırma boşluğu, matematiksel doğruluk, R10 yakalama oranı, lineage L9, kill-search K6, düzenleme ölçümleri R18/R19/R21 ve H10'un gerçek çağrı tekrarları bu işte ölçülmez. Hazır korpus kurmak için yapılan kuyruk seçimi varsayılan keşfin başarısı gibi sunulmaz. Rapor tamamlanırsa diğer borçlar kendiliğinden kapanmaz; her biri ayrı dondurma ve sahip yetkisi ister.

**Sonraki işlem:** koordinatör bu commit'i push eder; 2. aşama ölçüm worktree'sini sabitlenen commit'te kurar ve §6 kuru kontrolünü push edilmiş dondurma commit'iyle çalıştırır, sonra hazırlık başlar. Matris çifti, başka bir Luna işi ve port 8765'teki canlı sunucu ile çakışmaz (§0, §4.1).

## Ek A — 2. dondurma noktası (3 Ekim 2026, hazırlık sonrası, rapor öncesi)

Bu ek §4.4 kayıt tablosunu doldurur. Donmuş kurallar değişmedi. Hazırlıkta donmuş metnin öngörmediği bir ürün duruşu oldu (A.3); yeni ve kayıtlı Claude+Sol medium kararıyla çözüldü, bu inceleme açıkça hüküm vermelidir. Rapor isteği yapılmadı; rapor yalnız bu ekin `gpt-6.1-sol` high incelemesi “hazır” dedikten ve koordinatör push ettikten sonra, §6.1 kuru kontrolü yeni dondurma commit'iyle yeniden geçerse başlar. Özel kanıt `DEIXIS-h9run/.local/p9r-h9/` altında, izlenmeden kalır (`protocol.md`, `evidence/`, `r9/`).

### A.1 Ürün ve dondurma kimlikleri

| Kayıt | Değer |
|---|---|
| Ürün (ölçüm worktree'si, ayrık) | `87cee0ba4e566ef311c07007d8b50ce7eb0a5086`, `DEIXIS-h9run`; commit/checkout yok |
| 1. dondurma commit'i | `6b06866b38cd268a59a673b1d4fca68e9305c7b2` (origin/main); bu ekten önceki belge SHA-256: freeze `a0292076f45789f6b3e5de703d9dfdd26109ac33be96546cc6428a8958fbef17`, istem `a4fd4de259dc9cff27e77734b7c3c71a8f5847403800f4ef8c7d38e649c851af` (istem bu commit'te değişmedi) |
| §6.1 kuru kontrol (1. dondurma ile) | betik SHA-256 `1f23c45c14c844b7fd7227fe9b86f48172fb951a4e9fc148862baed8b0b9717a`, rc 0; testler 257 geçti; §6.2 sağlık `ok`, `not_owner`, hash eşit |
| Runtime `skill_package_hash` | `sha256:5ba2d214bd1122f9544aaa537226b6234123bf6be82b3e6e1c6d9ff99dcf75ff` |
| Şema manifesti (22 dosya) | `7ac32dcdd77ab06b135a54596387cdfa6213237f27ecce923728f95948adcc52` |
| Yöntem dosya manifesti | `methods/deixis-research`, `skill._package_files` kuralıyla 17 dosya; dosya başına SHA-256 `evidence/method-manifest.json` içinde (dosya SHA-256 `a1f3afb07ce697dee52b879e76707be83a5f65e4cb4254079e33a7a086364b2d`); toplam (`<yol>\0<sha256>\n` satırlarının SHA-256'sı) `422314a616290481779df999f02dd3ad01cad38b26b9490b1afb610de2cf0bb4` |
| Kit / kit testi | `measure_report.py` `db203420e4b1ade5ab45cfa3b1636cc239bd3efa251554bb8dc1b15912251848`; `test_p6_measure_report.py` `7f7d2f0d500401f30bafe3cee7a4c4bdffd96454a600817158a1aa765d63bdf8` |
| P19 sorgusu | §4.2.1 baytları `p19.sql` olarak çıkarıldı, SHA-256 `6d53789f7a1b898a4833bb993eaac222b29e5fa0cb209519fe020c3106e6acd1` yeniden doğrulandı |

### A.2 Sunucu, izolasyon ve gözlemci

Sunucu §4.1'in donmuş başlatıcısıyla (`launch.sh`, SHA-256 `8cc600c4b5b33c35cd5f99e6c421941cb649c70ef4dc9d151740051416ef05fd`, dondurma commit'inden aynen çıkarıldı) 06:52:18Z'de başladı: PID 38083, `127.0.0.1:8873`, yeni veri dizini `DEIXIS-h9run/.local/p9r-h9/data`, `.env` yok, null keyring, sağlayıcı anahtarı yok. Codex `codex-cli 0.160.0`, bağlantı `ready`/`signed_in`; `DEIXIS_CODEX_HOME` yalnız `test -d` ile denetlendi (K05 dar istisnası). Alt süreç envanteri: `codex app-server` PID 38865 (09:52:30 yerel). Port 8765 denetimi başlangıçta (`port-8765-20261003T065218Z.json`, `free: true`) ve 07:16Z'de (`lsof` rc 1, dinleyici yok) temiz. 07:16Z durumu: rapor 0, aktif koşu 0, `started` oturum 0.

Rapor gözlemcisi `poll_report.py`, SHA-256 `df97882af8076ec3affa4dde121a4546ad89049c8eae3ae8940b9402c603e6fe`. Salt okunur; her 15 s'de bir JSON satırı yazar, hiçbir şeye müdahale etmez. Satır kısaltılmamış olarak şunları taşır: rapor koşusunun her model oturumu (kimlik, adım, girdi ve deneme numarası, durum, istenen/çözülen model, `validation_json`, araç öğeleri, zamanlar), her `failed`/`outcome_unknown` adımın `error_code` ve tam `error_json` değeri, `report_sections` durumları ve tam doğrulamaları, tam `review_json` ve `reason`, oturum sayıları ve K07 tavan işaretleri (60 oturum / POST'tan 90 dk). Böylece yalnız `client_timeout` kökenli bir duruş karışık nedenden, onarımla düzelen geçersiz ilk çıktı da terminal başarısızlıktan ayrılır. `ps` denetimi üç durumu ayırır: süreç var, süreç temiz biçimde yok (çıkış kodu 1, hata akışı boş) ve denetim başarısız (canlılık bilinmiyor; çıkış kodu ve akışlar yazılır); hata gözlemciyi durdurmaz. **Yürütücü dönüş kaydı:** işçi her turun başında `worker_owner.heartbeat_at` yazar ve yeni tur ancak önceki `flow.execute()` döndükten sonra başlar (`workflow/worker.py::_turn`). Bu yüzden koşu terminal durumdayken son terminal olayından sonra yazılmış bir heartbeat, yürütücünün döndüğünü gösterir (tek işçi, yeniden başlatma yok). Her (koşu, terminal olay kimliği) çifti için ayrı bir 120 s kapanış penceresi vardır; o terminal olayı gören ilk satır pencereyi başlatır. Sürdürülen koşu iki poll arasında yeniden biterse yeni terminal olay kimliği yeni pencere açar. Satırlar pencerenin başlangıcını, geçen saniyeyi, sürenin dolup dolmadığını, `verified` (dönüş kaydı ve sıfır `started` oturum birlikte) ve `snapshot_eligible` (pencere içinde doğrulandı) değerlerini taşır. Nihai snapshot yalnız `snapshot_eligible` doğruyken alınır; pencere dolarsa nihai durum iddiası kurulmaz (§5). Hazırlık gözlemcisi `poll.py` `33dbdde3a75598f6350ba81d4bffad407c1e1e461a5e297429642e2005f66f7e`, istemci `api.py` `7c9bc47913cf5ff4e6b8dc51c6aef2a37ea11e961b98f82a051ddc52cc56d28d`.

### A.3 Sapma 1: `key_terms_needed` duruşu (inceleme hükmü gerekir)

Araştırma `res_5ZrJQgVQ5unqqCRpMbrr` donduğu gibi açıldı (`sw`, `academic`, `question_only`, `standard`, `tr`, `codex`/`gpt-5.6-luna`/`medium`, Q1 metni aynen, anahtar terim yok). İlk keşif koşusu `run_gColvwp6pK4UCZTjDwHL`, 06:53:14Z'de hiçbir model oturumu veya sağlayıcı isteği olmadan `key_terms_needed` ile durdu: ürün İngilizce olmayan soruyu çevirmez ve kullanıcıdan İngilizce anahtar terim bekler (`domain/vocabulary.py::extract`, SW2.1). Donmuş metin bu duruşu öngörmedi; 1. dondurma incelemesi de yakalamadı. Soru metni dondurulduğu için İngilizceye çevrilemez.

**Karar (Claude Opus 5.5 + `gpt-6.1-sol` medium, salt okunur, tek çağrı, uygulamadan önce `protocol.md`'ye yazıldı):** sorunun başının yalnız düz karşılığı, eşanlamlı eklenmeden, `claim:`/`not:` grubu olmadan verilir: `electric vehicle, electric vehicles; charging scheduling; optimization` (ayrıştırıcı: setting, task, outcome). 06:57:05Z'de `POST /scope` ile soru değişmeden kapsam revizyonu 2 açıldı; yeni keşif koşusu `run_inu6W7FeiklGWvBs3U7m`. İlk koşu kayıt olarak durur. Bu ikinci deneme veya timeout sürdürmesi değildir; saat 06:53:14Z'den işlemeye devam etti, sayaçlar birikimli. Sonuç belgesi bunu donmamış bir yürütücü girdisi olarak yazacak: arama ve korpusu biçimlendirdi, sorunun tam çevirisi değildir, kısaltma/eşanlamlı eksikliği geri çağırımı düşürebilir, sonuç yalnız bu terimlerle kurulan korpus içindir ve varsayılan Türkçe keşif başarımı veya literatür tamlığı hakkında bir şey söylemez. İlk duruşun süresi (yaklaşık 4 dk) raporlanır.

### A.4 Protokol, korpus ve tablo (deneme 1; ikinci deneme açılmadı)

Protokol kartı 3 `criterion_proposal` oturumundan sonra beklemeye geçti; öneri hash'i `72083c244f484f4a432214d28f5b8b382377190f89e667011277bf6482c0eeea`; terimler yukarıdaki üç blok, kapı sayımı 2178, `too_broad=false`, dışlama/iddia kelimesi yok. Ürün ayarları keşiften önce kayıtlı: atıf zinciri `auto`, tam metin getirme `overlap` kipinde (en çok 100 eser), `DEIXIS_FULLTEXT_ADJUDICATION=auto`, `max_model_calls 39`, `max_provider_requests 8`. Kart 06:58:35Z'de boş gövdeyle, değiştirilmeden yürütücü (`claude-opus-5-5`) tarafından onaylandı; ürün `approved_by=user` saklar.

Sayılar: 4.925 satır döndü (925'i zincirden), 3.167 tekil eser, 150 özet model tarafından okundu; tam metin 112 eser için arandı, 103'ü getirilemedi, 9'u okundu (ürünün `inspected=0` sayısı yanıt incelemesini sayar, tam metin okumasını değil); otomatik dahil 3 (iki model okumasının uyumu, tam metin), kapsam dışı 18 (model 13, kod 5), PDF bekleyen 103 (yalnız özet; kuyruk satırı yok, §1.2 adım 2 gereği dahil edilemez), kuyruk 6. Saklı bitişler: keşif `run_inu6W7FeiklGWvBs3U7m` 07:03:36.565Z, tam metin karar koşusu `run_B3jDme04LX0ccsjf0rKO` 07:05:12.206Z (07:05:22Z gözlem anıdır).

**K03 kuyruk geçişi:** 6 açık satırın hepsi (normalize başlık, sonra eser kimliği sırası), yalnız saklı metin. İstek 1/2: `claude-opus-5-5` medium, 07:07:18Z-07:07:41Z, ayrı defter (`queue-ledger.jsonl`); paket SHA-256 `d9cd2c45caf3019d5be2d2fe994adf8e6d94d7a9205ed901941579cec6cc5b9a`, yanıt `ffa5fab5da54b4a9fa525dd75c74c678faed882ffd832fcc1696640af2c6b965`. 07:07:05Z'deki ilk başlatma, model çağrılmadan kabukta `timeout` olmadığı için düştü; istek sayılmadı. Karar: 4 dahil (hepsi tam metinden), 2 `criterion_not_met`. Yalnız dahil kararları ürünün kuyruk yoluyla yazıldı (07:11:31-32Z; not karar veren modeli, okuma derinliğini, sayfaları ve gerekçeyi taşır). Ürün bu 4 satırı `user`/`human_include` olarak saklar; D96/D101 gereği bu etiket bu satırlar için yanlıştır ve sonuçta öyle yazılacak. Dışlama kararları ürüne yazılmadı, böylece başka yanlış “person” satırı oluşmadı. Bu 4 eser varsayılan keşfin verimi sayılmaz (seçilim etkisi).

**Gözlem: seçim eserin baş sürümüne yazılıyor.** Ürün her eserin seçimini baş sürüme koyar ve `report_ready` dahil baş sürümleri arar; tablo satırları bu yüzden ürünün varsayılan yolu olan baş sürümlerdir (`rows=None`). 7 eserin 5'inde baş sürüm yalnız özet taşıyan yayımlanmış kayıttır; tam metin kardeş sürümdedir (gönderilmiş/kabul edilmiş). Satır düzeyinde saklı tam metin 2, özet 5. §1.2'deki “en az 3 saklı tam metin” hedefi satır düzeyinde tutmadı; R6/R9 buna göre sınırlı kalabilir. Seçim düzenlenmedi, ürün değişmedi.

| Anahtar | Satır (baş sürüm) | Tam metnin durduğu sürüm | DOI | Giriş | Satır okuma derinliği |
|---|---|---|---|---|---|
| Tang16 | `srv_oNUsUxevbSKDEpKe5BTX` | `srv_6c8q6CLkp57dmv98hlJj` (arXiv 1502.01456) | 10.1109/tpwrs.2016.2585202 | kuyruk | özet |
| Latifi18 | `srv_6K8oGH3IDlVqc2rbplyf` | `srv_Lg6z6iacHpJNXwB3FlnR` | 10.1109/tie.2018.2853609 | kuyruk | özet |
| Sulthan22 | `srv_EHdqhEzLrupt3TgGRlCA` | `srv_te3kjMIH3NHCVz8zommw` | 10.3390/su14063498 | kuyruk | özet |
| Qi23 | `srv_JepNQswFq2Quh27XDtRs` | aynı | 10.35833/mpce.2022.000456 | otomatik | seçili bölümler |
| Hadian20 | `srv_bOvBMnzdvfPiDACsvSDz` | aynı | 10.1109/access.2020.3033662 | kuyruk | seçili bölümler |
| ClementNyn09 | `srv_JxOi4KJMLaAucvzklHpQ` | `srv_c60Y8NVq5ELa8ZMdVb9x` | 10.1109/tpwrs.2009.2036481 | otomatik | özet |
| Sarabi16 | `srv_tgvkQdyF08om6B8mPrCV` | `srv_I8zewVotZ4HyhjcxFbRT` | 10.1109/energycon.2016.7513989 | otomatik | özet |

Seçilmeyen uygun iş yok (7 < 10). Kaynak/sürüm/DOI/dosya envanteri: 7 eserin bütün sürümleri, DOI'leri, sürüm etiketleri, kullanılan PDF'lerin `source_assets` kimliği, SHA-256 değeri, bayt boyu ve çıkarım durumu `evidence/source-inventory.json` içinde (SHA-256 `c5479f4c2e47634887f88845510ffd70b15e5234a76e64c0d8fff83c1efbbe26`); yedi tam metin PDF'i (her eser için bir) `succeeded` çıkarım taşır. **Bağımsızlık:** 7 eserin bütün sürümlerinin DOI/arXiv/OpenAlex kimlikleri izlenen belge envanteriyle kesiştirildi; örtüşme yok, hepsi `bağımsız (kimlik düzeyinde)`. Eski yüklenmiş dosya hash'leri ve belgelerde yazılmamış kimlikler `denetlenmedi`.

**Tablo:** `tbl_pQukBcMTicxNo3QPGaf9`, 07:13:14Z, 7 satır, §1.3'ün yedi `text` sütunu aynen. Doldurma `run_m31qpPY68NBbMjBh6CZi` 07:13:30Z-07:14:23Z, 7 `cell_extraction` oturumu. 49 hücre `structurally_valid`: değer 39, `not_found_in_inspected_scope` 9 (Denklem 5, Karar değişkenleri 3, Kısıtlar 1), `unknown` 1. `report_ready`: `ready=true`, `cells_left=0`, `cells_total=49`, `failed_rows=0`, `failed_cells=0`, `included_rows=7`. SHA-256 (sıralı, `sort_keys`, ayırıcısız JSON): satırlar `add8755655933c4599e9a28b58e88df5425cdb5fc8bf4ccb9da56bfad6c4f34d`, sütunlar `3fe1c95aa6fe984e95598c1062c83781c1c5496748ae94cc7c74ac15c15c16e9`, hücre revizyonları `8febd20ce4487543c12c6cb70ee20244eb470dde4ce5a1692384b51c1bd61bd9`, değerler `2b73e6c2057c977aaf99911554e9dd141b72a014be7a94d98450c0036c14dfbe`, kanıt `3f0c5c4915449b761d762b63f9d6d5d6be67c18e211f1a2cbcc3166d2d219332`.

Hazırlık 07:14:23Z'de bitti: saatin 21,1 dk'sı, 2 denemenin 1'i, 300 uygulama oturumunun 45'i (keşif 19, tam metin kararı 19, doldurma 7), 2 kuyruk isteğinin 1'i. Hazırlıkta tek duruş A.3'teki ilk `key_terms_needed` duruşudur; sonraki koşuların hiçbiri durmadı; timeout, kota/yük, model uyuşmazlığı veya araç ihlali yok. Saklı adım hataları: bir `model:abstract_screening` adımı `invalid_model_output` ile bitti (model `skill_package_hash` değerini bir karakter yanlış kopyaladı, `envelope_mismatch`; adımda 1 girdi ve 1 oturum var, onarım gönderimi yok), keşif koşusu tamamlandı; PDF getirme 21 (`fetch_http_error` 19, `fetch_not_pdf` 2) ve başka kopya araması 101 (`no_other_copy`) başarısız adım. 45 oturumun hepsi `completed`.

### A.5 R9 çiftleri (§4.4, rapordan önce)

Denklem sütununun yedi güncel hücresi kaynak-sürümü sonra hücre kimliği sırasıyla okundu. Beşi `not_found_in_inspected_scope` (beşi de yalnız özet okudu), çift vermez. Seçim 07:15:30.565Z'de, rapordan önce yapıldı. İki değer hücresinden, metinde görüntülenen ve kökeni hücrede kayıtlı her ayrı formülasyon hücre sırasıyla alındı; sözle tanımlanan MSE alınmadı:

| # | `source_key` | Formülasyon etiketi | Hücre / revizyon |
|---|---|---|---|
| 1 | Qi23 | OPF: min \|ΔP\| = ∫\|P_sub − P_obj\| dt (denk. 9), rampa, gerilim ve güç sınırlarıyla | `cel_KweKW4pTcVCg9rs22yqW` / `crv_5EFjd6rUc3hlWsTKXo8X` |
| 2 | Qi23 | İkinci aşama EV şarj gücü denetimi P_EV,k(t) | aynı |
| 3 | Hadian20 | OF1 = a × … + b × … + (c × MSE), metin katmanında görüldüğü kadar | `cel_CoSPTBL2QLgTSTMXU8FX` / `crv_M8NL2aRyCBvuX5R73LyU` |
| 4 | Hadian20 | BDSO = Bload_total + Bloss_total + BENS_total | aynı |
| 5 | Hadian20 | BEVCS = Bdischarge_total + Bcharge_total − Cinv_total | aynı |

`pairs.json` SHA-256 `706ae813cfc8bc9e34f0ab981f0ddc21d7d811c34003e8bad8471d72162f547d`; `pairs-provenance.json` (kaynak-sürümü, eser, satır, hücre, revizyon, değer hash'i, köken pasajları ve çapaları) `7e5a080f7b32a37f89caf65eeaf897a69647c1e7e230ffc5adafe50c4b10898b`. Yedi satırın kısa anahtarları tekil; eşleme tek anlamlı. Sonradan çift eklenmez veya değişmez. Modele verilen denklem koşulu rapordan sonra saklı StepInput'tan sınanır.

### A.6 Sonraki adım

İnceleme “hazır” derse koordinatör bu commit'i push eder. Yürütücü push edilmiş hash ile §6.1'i yeniden çalıştırır, 8765 denetimini ve alt süreç envanterini yeniler, gözlemciyi POST zamanıyla başlatır ve tek isteği gönderir: `POST /api/researches/res_5ZrJQgVQ5unqqCRpMbrr/reports`, gövde `{"table_id": "tbl_pQukBcMTicxNo3QPGaf9", "continue_with_failed": false}`.

## Ek B — H9b: RF sonrası rapor yolunun yeniden ölçümü (3 Ekim 2026, koşudan önce dondu)

**Dayanak.** Koordinatör görevi (3 Ekim): RF düzeltmesinden ([D198](../decisions.md), `682ba1f`) sonra rapor yolunu gerçek modelle kısa bir yeniden ölçüm. Açık noktalar Claude Opus 5.5 + `gpt-6.1-sol` medium tarafından, salt okunur ortak kararla, sahip adına kararlaştırıldı ([D202](../decisions.md)). Bu ekte yazılmayan her kural H9'dakiyle aynıdır (§1-§7, Ek A): K05 canlı `codex-home` dar istisnası, port 8765 ön koşulu ve koordinatör kuralı, `env -i` başlatma, null keyring, `.env` yok, `codex`/`gpt-5.6-luna`/`medium`, izole veri dizini ve 8873, ayrık ölçüm worktree'si, yazan ve inceleyen farklı şirketin modeli. H9'un donmuş metni ve Ek A değişmez.

### B.1 Ürün ve donmuş değerler

| Kayıt | Değer |
|---|---|
| Ürün | `682ba1f0fcd0259b743aa4e14294d33851fe81d4` (RF, D198; ortak karar anında `origin/main`; bu ek yazılırken main `03422d7`'ye, D197'ye ilerledi), ayrık worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run`, kendi `.venv`'i (`uv sync --frozen`, arm64, Python 3.12.13). Main ilerlese de yeniden sabitlenmez. Bu commit H9'dan sonra gelen başka işleri de içerir (87cee0b'den sonra: D184, D185, D186, D194, D195, D196, D199); H9 ile karşılaştırma RF'nin nedensel etkisini ayıramaz. |
| Runtime `skill_package_hash` | `sha256:1a7e67137173f49fc2acca70edc940a5f0589cf216cf20a2d8f5f606b3b93c4e` (D198 ile aynı) |
| Şema manifesti (23 dosya) | `73fd58185ee36da262ee2d405c1ad9116f5dd9385d8a2b457c8d9a8df25f1797` |
| Yöntem dosya manifesti | 17 dosya, toplam `027153692672b923f6f932d2e2eb988cdc4f92cf4323e8571cb70899d20b93b4` (`evidence/method-manifest.json`, `a416e1b2cd3a54d11e68b8842936b754680eccb74d83fe9548617e8f7d9be1f7`) |
| Kit / kit testi | değişmedi: `db203420e4b1ade5ab45cfa3b1636cc239bd3efa251554bb8dc1b15912251848` / `7f7d2f0d500401f30bafe3cee7a4c4bdffd96454a600817158a1aa765d63bdf8` |
| P19 sorgusu | §4.2.1 baytları aynen (`p19.sql`, `6d53789f7a1b898a4833bb993eaac222b29e5fa0cb209519fe020c3106e6acd1`) |

Özel kanıt `DEIXIS-h9b-run/.local/p9r-h9b/` altında izlenmeden kalır. Yürütücü dosyaları:

- `gate_b.sh`: §6.1'in H9b sürümü. Ürün/dondurma atalığı, `## D202` varlığı, RF kod imleri, bütünlük, paket hash'i, kit pinleri, şema manifesti, tüm ağacın temizliği; ayrıca aşağıdaki `h9b-files` bloğunu push edilmiş dondurma belgesinden okur ve listelenen her dosyanın SHA-256 değerini denetler (kendisi dahil).
- `launch_b.sh`: §4.1 başlatıcısının H9b sürümü. `H9B_ARM` (`a`/`b`) ve `H9B_FREEZE_COMMIT` ister; A için kopya veri dizini var olmalı, B için yok olmalı; başka bir H9b sunucusu varsa veya `pgrep` temiz bir “eşleşme yok” (çıkış 1, boş çıktı) vermezse başlamaz; 8765 denetimi H9'daki işlevle aynı.
- `poll_b.py`: hazırlık gözlemcisi (H9 `poll.py` + kol/PID argümanı + `ps`'in üç durumu).
- `poll_report_b.py`: rapor gözlemcisi. Ek A.2'nin mantığı; yalnız bu kolun rapor koşusunu izler; her poll'un bütün okumaları tek SQLite okuma işleminde yapılır, böylece duraklamış durum ile sürdürme sonrası heartbeat/oturum karışmaz; `ps` ancak çıkış kodu 0, dolu stdout ve boş stderr ile “canlı” der.
- `api.py`: istemci (H9 ile aynı).
- `h9b_counts.py`, `p19_count.py`: B.5'in sayımları. `logical_table.py`: A tablosunun mantıksal hash'i. `manifest.py`: dosya manifesti. Üç sayım betiği veritabanını yalnız `mode=ro` ile ve tek okuma işleminde açar; açamazsa durur (`immutable` yedeği yoktur).

```h9b-files
d38ff84c7db98926cc00d302cf7bdc09b3367ed4eecd95e7ff524f14b3fe91c0  .local/p9r-h9b/gate_b.sh
783e7bd42cd80ab7437bdb46210636a9b1bcb1890de775f369a08ade91b76c95  .local/p9r-h9b/launch_b.sh
841d46ce67479636e37fbf26ce81d17327b306ab343d390e2b6cd350e0217239  .local/p9r-h9b/poll_b.py
c9d60768bbde2ef70ed3de52905b71f0cc79ec16e2efbfa05f3c418770181803  .local/p9r-h9b/poll_report_b.py
7c9bc47913cf5ff4e6b8dc51c6aef2a37ea11e961b98f82a051ddc52cc56d28d  .local/p9r-h9b/api.py
b44a93835b3b7bfd17bf4d5c10731304ab62a436e5729132ccf2bae80654a08e  .local/p9r-h9b/h9b_counts.py
58219952459a2e2bedc25722b5d7e5e158e04cbbe02d9d6a205e401f63136993  .local/p9r-h9b/p19_count.py
6d53789f7a1b898a4833bb993eaac222b29e5fa0cb209519fe020c3106e6acd1  .local/p9r-h9b/p19.sql
e3307b794ff24f4a93fb2abca701dac2e34a7992491036b68df05a08cec4210f  .local/p9r-h9b/logical_table.py
e1c375b4e8aecf61906472a0c60caa5932a3c0f2f5e201e2da0424a0cca97183  .local/p9r-h9b/manifest.py
a416e1b2cd3a54d11e68b8842936b754680eccb74d83fe9548617e8f7d9be1f7  .local/p9r-h9b/evidence/method-manifest.json
f83d25b490fc1c29b6fc0799085a5e1ec93f8387c980ec9d2cf5eac138a7d939  .local/p9r-h9b/evidence/a-source-manifest.json
f83d25b490fc1c29b6fc0799085a5e1ec93f8387c980ec9d2cf5eac138a7d939  .local/p9r-h9b/evidence/a-copy-manifest.json
5ed7ef4ec5843dcd3451cdbadb5adbfd245c3bede4cac269ee4f731e0296d8d1  .local/p9r-h9b/evidence/a-logical-table-before.json
706ae813cfc8bc9e34f0ab981f0ddc21d7d811c34003e8bad8471d72162f547d  .local/p9r-h9b/r9/a-pairs.json
7e5a080f7b32a37f89caf65eeaf897a69647c1e7e230ffc5adafe50c4b10898b  .local/p9r-h9b/r9/a-pairs-provenance.json
```

`h9b_counts.py` ve `p19_count.py` H9 verisinde denendi: H9'un P19 satır hash'ini (`b325ed94…8422`) ve a-e sayılarını aynen verdiler; H9'un 52 oturumunda üç `envelope_mismatch` buldular (D198 ile aynı), hazırlık aralığında (POST'tan önce) 45 oturumda iki. Kuru `gate_b.sh` (dondurma belgesi denetimleri dışarıda) rc 0; kuru regresyon testleri (§6.1 listesi + `tests/test_report_path_fix.py`, `tests/test_report_path_fix_contracts.py`) 331 geçti. Bunlar modelsiz denetimlerdir.

### B.2 İki kol: A önce, B ondan bağımsız

İki kolun sunucusu aynı anda çalışmaz; ikisi de 8873'tedir. Kollardan biri durursa öteki yine koşar.

**Kol A: H9 tablosu, geliştirme korpusu.** H9'un durdurulmuş veri dizini (`DEIXIS-h9run/.local/p9r-h9/data`) `cp -Rp` ile `DEIXIS-h9b-run/.local/p9r-h9b/a/data` dizinine kopyalandı; SQLite yan dosyaları dahil 65 dosya, sert bağ yok (`nlink` en çok 1), kaynak ve kopya manifesti aynı: `80764df489b155375c3a4e0ed91d4185c68f66df9ee60fdd69719e2a4a2ded1f` (`evidence/a-source-manifest.json`, `f83d25b4…a7d939`). Asıl H9 dizinine yazılmaz. Araştırma `res_5ZrJQgVQ5unqqCRpMbrr`, tablo `tbl_pQukBcMTicxNo3QPGaf9`. Tablonun mantıksal hash'leri (`logical_table.py`, kopyalamadan önce; kopyada da, sunucu başlamadan, bayt bayt aynı çıktı; `evidence/a-logical-table-before.json`): satırlar 7, sütunlar 7, sütun revizyonları 7, hücreler 49, güncel revizyonlar 49, kanıt bağları 101. Migration 0067-0068 ilk başlangıçta uygulanır. **A'nın POST kapısı:** başlangıçtan sonra ve POST'tan önce mantıksal hash'lerin altısı da aynı olmalı, tablo listesinde `report_ready.ready=true`, aktif koşu 0, `started` oturum 0. H9'un duraklamış eski rapor koşusu ve raporu tarihsel kayıt olarak kalır; “sıfır eski rapor” şartından muaf tutulur, hiçbir zaman sürdürülmez veya iptal edilmez. Kapı geçmezse A `ölçülemedi` yazılır; tablo onarılmaz. **A'nın ikinci kapısı** (Claude + Sol medium ortak kararı, `evidence/decide2-out.md`): A'nın korpus, tablo ve R9 kayıtları H9b'de hazırlanmaz; Ek A'da incelenmiş ve burada hash'leriyle donmuş H9 kayıtlarıdır. Bu yüzden Sol high'ın onayladığı ve push edilen Ek B A'nın ikinci kapısıdır; POST öncesi mekanik denetimlerin sonucu `protocol.md`'ye ve sonuca yazılır, herhangi bir uyuşmazlık yürütücü takdiri olmadan `ölçülemedi` verir. R9 çiftleri H9'unkilerdir (`r9/a-pairs.json` `706ae813cfc8bc9e34f0ab981f0ddc21d7d811c34003e8bad8471d72162f547d`, köken `r9/a-pairs-provenance.json` `7e5a080f…898b`); sonradan değişmez. A'nın sonucu bağımsız kanıt değildir: RF, H9'un saklı çıktıları üzerinde geliştirildi.

**Kol B: yeni hazırlık, Q3.** Soru §1.1'deki Q3 metni, kelimesi kelimesine: “Su dağıtım ağlarında pompa zamanlaması için hangi optimizasyon modelleri kullanılmıştır? Karar değişkenlerini, enerji maliyeti amacını, hidrolik ve depo kısıtlarını, talep belirsizliğini ve değerlendirme koşullarını karşılaştırın.” İngilizce anahtar terimler Ek A.3'ün kuralıyla (sorunun başının düz karşılığı, tekil/çoğul dışında eşanlamlı yok, `claim:`/`not:` grubu yok) şimdi dondu ve araştırma oluşturulurken verilir: `water distribution network, water distribution networks; pump scheduling; optimization`. Bu sınırlı sözcük dağarcığı geri çağırımı düşürebilir. Geri kalan her hazırlık kuralı H9'daki gibidir: yeni ve boş veri dizini `DEIXIS-h9b-run/.local/p9r-h9b/b/data`, `sw`, akademik, yalnız soru, keşif eforu `standard`, dil `tr`; protokol kartı değiştirilmeden yürütücü tarafından onaylanır; §1.2 seçim kuralları ve K03 kuyruk geçişi (`claude-opus-5-5` medium, yalnız saklı metin); §1.3'ün yedi `text` sütunu aynen; §1.2'nin 6-10 eser kuralı. Bağımsızlık H9'un belge envanteri (`old-corpus-inventory.json` `b428c970…423a`) ve H9 korpusunun 7 eserlik kaynak envanteri (`source-inventory.json` `c5479f4c…be26`) ile, Ek A'daki yöntemle denetlenir. **B'nin ikinci kapısı:** B'nin korpus, tablo ve R9 kayıtları (Ek A.4/A.5 biçiminde) B'nin POST'undan önce tarihli **Ek C** olarak yazılır; `gpt-6.1-sol` high en çok 3 tur inceler, koordinatör push eder, `gate_b.sh` push edilmiş hash ile yeniden geçer. B'nin hazırlığı bu kapıyı beklemeden başlayabilir.

### B.3 Bütçe

H9 360 uygulama oturumunun 52'sini kullandı; 308 kaldı. H9b: A raporu 60 oturum / POST'tan 90 dk; B hazırlığı en çok 2 deneme, birlikte 180 oturum / 240 dk (her doldurma 60 / 60 içinde; saat B'nin ilk keşif koşusunun kuyruğa girdiği anda başlar); B raporu 60 / 90. Toplam 300; kalan 8 oturum yalnız gözlenen tavan aşımı içindir, yeni deneme değildir. Her yeni oturum sayılır (onarım, yeniden gönderim, hazırlık denemeleri dahil); A'ya kopyalanan H9 oturumları tarihsel kayıttır, sayılmaz. K03 kuyruk istekleri: deneme başına en çok 1, B'de toplam en çok 2, 30 dk, ayrı defter. Okurlar (K09) yalnız tamamlanan rapor için: rapor başına en çok 4 istek / 60 dk, H9b toplamında en çok 8 / 120 dk (H9'un okur iznine açık ek); ayrı defter.

### B.4 Durdurma

Her kolda tek rapor koşusu; sonuç beğenilmedi diye ikinci rapor yok. §5'in kuralları her rapor koşusu için aynen: yalnız bütün terminal kök nedenler `client_timeout` ise 10 dk sonra bir kez sürdürme; kota/yük, model uyuşmazlığı, araç ihlali, başka veya karışık hata, ikinci timeout, bütçe dolması veya okunamayan sayaç o kolun raporunu durdurur. Hâlâ çalışan koşu yalnız ölçümü bitirmek için kendi API'siyle iptal edilir; duraklamış koşu iptal edilmez. Kapanış: Ek A.2'nin yürütücü dönüş kaydı ve 120 s penceresi (`snapshot_eligible`). Nihai snapshot'tan hemen önce gözlemcinin en yeni satırı aynı terminal olay kimliği için `snapshot_eligible=true` göstermelidir; göstermezse nihai durum iddiası kurulmaz. Durmuş raporda kit `snapshot ... --stopped <neden>` ve `score` çalışır, okur çalışmaz; yalnız R1, R7, P19 ve B.5 sayıları korunur. Hazırlıkta K08 ve §5'in hazırlık kuralları aynen. Port 8765 denetimi (Ek A.2 / §4.1.1 biçiminde, `launch_b.sh` içindeki aynı işlev) her sunucu başlangıcında, B'nin her hazırlık denemesinin başında, her POST'tan hemen önce ve her nihai snapshot'tan önce yapılır; dinleyici veya başarısız denetim §4.1.1 madde 3'ü tetikler.

### B.5 Sayılanlar (her rapor koşusu için, salt okunur)

`h9b_counts.py <library> <report_id> <başlangıç> [<bitiş>]`; sınırlar saat dilimli ISO zamanlarıdır ve UTC anı olarak karşılaştırılır, saat dilimsiz veya ters sınır reddedilir. Çağrılar: A'da `<sunucu başlangıcı> <POST zamanı>` (beklenen 0 oturum) ve `<POST zamanı>`; B'de `<ilk keşif koşusunun created_at değeri> <POST zamanı>` (hazırlık) ve `<POST zamanı>` (rapor). Sayılanlar:

- **Yama girdileri:** taşıma şeması `properties.schema_version.const = "deixis.report_section_anchor_repair.v1"` olan `report_section` girdileri. Ayrı sayılar: oluşturulan girdi, oturumu olan deneme, doğrulanıp uygulanan yama (`validation_json.anchor_patch` var), birleşik taslağı `ok=true` olan, bölümü `valid` yayımlanan. Her girdi bölüm, adım, deneme ve sorunlarıyla listelenir.
- **Yamayla çıkarılan iddialar:** `anchor_patch.changes` içinde `claim_key` ve `removed` taşıyan her öğe; bölüm yayımlandı mı, son taslağın `insufficient_evidence` kaydında bağlamı tam `<claim_key>: ` ile başlayıp boş olmayan açıklama süren bir giriş var mı.
- **Bırakılan iddia/belirsizlik:** `repair_dropped_claim` ve `repair_dropped_insufficient_evidence` sorunlarının geçiş sayısı ve etkilenen ayrı oturumlar. Doğrulaması olmayan `report_section` oturumları ayrıca listelenir; sayıları bilinmez, sıfır sayılmaz.
- **Hash:** `başlangıç <= started_at < bitiş` aralığındaki her oturumda `envelope_mismatch` geçişi ve oturum kimlikleri (beklenen 0), doğrulaması olmayan oturumlar ve yama oturumları ayrı listelenir; damga paydası doğrudan sayılır: doğrulaması olan, yama olmayan oturumlar; pay: bunlardan `skill_package_hash` damgası taşıyanlar. Yama birleşimleri yeniden bağlanır, damgalanmaz. Aşamalar ayrı çağrılarla verilir: A'da [sunucu başlangıcı, POST) ve [POST, -); B'de [ilk keşif koşusu, POST) hazırlık ve [POST, -) rapor.
- **P19 a-e** (`p19_count.py`): §4.2.1 sorgusu ve kuralları aynen. (e) tam onarımda §4.2.1 gibi: çıkarılan anahtar `insufficient_evidence` kaydının `context` veya `reason` metninde tam kimliğiyle geçmelidir (`V.1`, `V.10` ile eşleşmez). Yama denemesinde yama çıktısı tam iddia kümesi taşımadığı için başarısız temel taslak ile adımın doğrulanmış birleşik sonucu karşılaştırılır ve görünürlük için katı kural uygulanır: bağlam tam `<claim_key>: ` ile başlar ve boş olmayan açıklama sürer. İki tür ayrı listelenir. Okunamayan taslak, eksik iddia listesi veya eksik onarım doğrulaması `not_readable`/eksik diye ayrıca yazılır, sıfır sayılmaz.
- R1/R7 ve rapor tamamlanırsa kitin bütün satırları ile K09 okurları (§4.3 aynen), H9'daki gibi.

Maruz kalma olmadan sıfır, etkinlik kanıtı değildir: yama yoluna hiç girilmezse “yama ölçülmedi” yazılır.

### B.6 Komutlar

```sh
# her kol için ayrı ayrı, push edilmiş H9b dondurma hash'iyle
cd /Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run
H9B_FREEZE_COMMIT=<hash> zsh .local/p9r-h9b/gate_b.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider \
  --basetemp=/tmp/p9-h9b-preflight-tests tests/test_report_anchor_repair.py tests/test_report_handles.py \
  tests/test_report_failed_rows.py tests/test_report_api.py tests/test_p6_measure_report.py \
  tests/test_report_path_fix.py tests/test_report_path_fix_contracts.py
H9B_ARM=a H9B_FREEZE_COMMIT=<hash> nohup zsh .local/p9r-h9b/launch_b.sh > .local/p9r-h9b/evidence/server-a.log 2>&1 &
# rapor: POST /api/researches/<id>/reports {"table_id": "<tablo>", "continue_with_failed": false}
.venv/bin/python .local/p9r-h9b/poll_report_b.py a <sunucu PID> <araştırma> <rapor koşusu> <POST zamanı>
PYTHONPATH=backend:. .venv/bin/python scripts/p6_eval/measure_report.py snapshot --base http://127.0.0.1:8873 \
  --research <araştırma> --report <rapor> --db .local/p9r-h9b/<kol>/data/library.sqlite \
  --out .local/p9r-h9b/evidence/<kol>/report --seed 20261003 --sample 30 --pairs .local/p9r-h9b/r9/<kol>-pairs.json
```

`gate_b.sh` her kolun sunucusu başlamadan önce yeniden çalışır. Sunucu bir kolun işi bitince SIGTERM ile durdurulur; sunucunun ve kayıtlı `codex app-server` alt süreçlerinin çıkışı 120 s içinde ≤5 s aralıklı `ps` okumalarıyla doğrulanır.

### B.7 Sonuç dili

Her kol ayrı yazılır: A “geliştirme korpusunda yeniden ölçüm (bağımsız değil)”, B “yeni korpus, tek koşu”. İkisi de tek rapor modeline ve rapora hazır tablo koşuluna bağlıdır. Hata oranı, hız/maliyet karşılaştırması, D198'in nedensel etkisi veya genel rapor kalitesi yazılmaz. Sonuçlar `p9r-report-results.md`'ye tarihli H9b bölümü olarak eklenir; karar D202'ye yazılır.

## Ek C — H9b: RF2 sonrası yeniden sabitleme, kol A2 ve kol B (3 Ekim 2026, koşudan önce dondu)

**Dayanak.** Kol A (`682ba1f`) ilk yama isteğinde durdu: canlı API RF'in yama taşıma şemasını `invalid_json_schema` ile reddetti (`$ref` yanında başka anahtar). Düzeltme RF2'dir ([D204](../decisions.md), `7cc1168`). Koordinatör emri: yeniden sabitle, H9 verisinin taze ve doğrulanmış kopyasında A2'yi koş, sonra B; bütçe kalan 293 oturumdan; durdurma kuralları aynı. Açık noktalar Claude Opus 5.5 + `gpt-6.1-sol` medium tarafından salt okunur ortak kararla, sahip adına kararlaştırıldı (`evidence/decide3.md`, `evidence/decide3-out.md`; Sol dokuz önerinin dördünü olduğu gibi kabul etti, beşini değiştirdi; değişikliklerin hepsi buraya alındı). **Öncelik:** Ek C, Ek B ile çeliştiği her noktada onun yerine geçer. Çelişmeyen her kural (H9 §1-§7, Ek A, Ek B) aynen sürer: K05 canlı `codex-home` dar istisnası, port 8765 ön koşulu ve koordinatör kuralı, `env -i`, null keyring, `.env` yok, `codex`/`gpt-5.6-luna`/`medium`, izole veri dizini ve 8873, yürütücü dönüş kaydı ve 120 s kapanış penceresi, snapshot öncesi `snapshot_eligible` şartı, yazan ve inceleyen farklı şirketin modeli. Ek B'nin metni değişmez; tarihsel kayıttır.

### C.1 Kol A'nın kaydı

Kol A şöyle yazılır: “yama modeli çıktı vermeden önce ürünün taşıma şeması reddedildi; yedi uygulama oturumu harcandı.” POST 11:27:17Z, rapor koşusu `run_wFL8CbQfBndgdeikEA2c`, rapor `rpt_cutHS27r5ILqZZBEWwSe`; V. bölümün ilk çıktısında `anchor_not_in_cell_evidence` vardı, ürün yama yolunu seçti (girdi `sti_MSGsJTIMFoL76Fu0QX4n`, oturum `mss_ZCfs0bP64HWgkESpi3r7`), istek reddedildi; III'ün tam onarımı iptalle kesildi; IV onarımdan sonra geçerli. İptal 11:29:43Z, kapanış 11:29:49Z doğrulandı (terminal olay 1581). Sayılar korunur: R1 0/1, ilk denemede geçerli 0/3, R7 145,6 s ve 7 çağrı, `envelope_mismatch` 0/7, damga 5/5, `repair_dropped_*` 0, P19 a=[V], b=1, c=0, d=0. D198 için A'da yönlendirme ve reddedilen istek gözlendi; yama modeli çıktısı ve onarımın işe yaradığı gözlenmedi. A'nın veri dizini ve kapanış kanıtı olduğu gibi kalır, yeniden kullanılmaz.

### C.2 Ürün ve donmuş değerler

| Kayıt | Değer |
|---|---|
| Ürün | `7cc116803cf63949c89e8c6b264aee2ff544b168` (RF2, D204; ortak karar anında `origin/main`), bir kez sabitlenir. Aynı ayrık worktree `DEIXIS-h9b-run` bu commit'e ayrık olarak geçirildi; izlenmeyen `.local/` kanıtı yerinde kaldı. `uv.lock`, `pyproject.toml`, `methods/`, `apps/web/`, `scripts/p6_eval/` ve kit testi `682ba1f`'ten beri değişmedi; `uv sync --frozen --dry-run` “Would make no changes” dedi, `.venv` arm64. |
| Bu commit'te RF2 dışında | D197 R3 (migration 0069, çıkarma girdisi gözlemleri, `passage_freshness`, rapor görünüm ve dışa aktarma değişiklikleri), D201 G1-F1 (arama dışı sorgular ve OpenAlex atıf zinciri bağlı yetenekler üzerinden; B'nin keşfini etkiler, rapor yolunu etkilemez), D205 (belge). A→A2 de H9→B de RF2'nin nedensel etkisini ayıramaz. |
| Runtime `skill_package_hash` | `sha256:1a7e67137173f49fc2acca70edc940a5f0589cf216cf20a2d8f5f606b3b93c4e` (değişmedi) |
| Şema manifesti (23 dosya) | `eb0becdee18e9fe49d1d819006cbf22b1b171c6bfb706b254c446631a0528366` (Ek B ile aynı yöntem; bir dosya değişti) |
| Modele giden şemalar | `contracts.model_transport_schemas()`: tam 41 anahtar; sıralı anahtar listesinin `json.dumps` SHA-256'sı `1a76b85cc1be334dae09da00a8129dc3577e948ace098466205b57c620d182a0`; her biri için `strict_compatibility_issues` boş |
| Yama taşıma şeması | `contracts.report_section_anchor_patch_schema()` (argümansız), kanonik JSON (`sort_keys`, ayırıcılar `(',', ':')`, `ensure_ascii=False`, UTF-8) SHA-256'sı `f30984c2f2680b294b47822ba3c01f0f8c16bf89d69f6e0c0f9b3134911a9739`. A'nın saklı reddedilmiş şemasından farkı yalnız `reason` alanı ve artık kullanılmayan `$defs.short_text`. |
| Yöntem dosyaları | 17 dosya, `evidence/method-manifest.json` dosya dosya aynı (toplam `027153692672…b93b4`) |
| Kit / kit testi | değişmedi: `db203420…251848` / `7f7d2f0d…bdf8` |
| P19 sorgusu | değişmedi (`p19.sql`, `6d53789f…acd1`) |

Yürütücü dosyaları (`DEIXIS-h9b-run/.local/p9r-h9b/`, izlenmez):

- `gate_c.sh`: `gate_b.sh`'nin C sürümü. `H9B_FREEZE_COMMIT` ve `H9B_STAGE` (`a2`, `b-prep`, `b-post`) ister. Ürün pini `7cc1168`; dondurma belgesinde `## Ek C`, kararlarda `## D202`, `## D204` ve “Ek C”; aşağıdaki `h9b-c-files` bloğu (ve varsa Ek D'nin `h9b-d-files` bloğu) dosya dosya; tüm ağacın temizliği, RF imleri, paket hash'i, kit pinleri, yeni şema manifesti; ayrıca RF2: sözleşmedeki `reason` biçimi, 41 anahtar ve liste hash'i, boş denetim sonuçları, yama şeması hash'i. `682ba1f` atalık denetimi kalktı (yeni ürün onun torunudur). `b-post` aşamasında ayrıca C.6'daki B koruması çalışır.
- `launch_c.sh`: `launch_b.sh` ile aynı; yalnız kollar `a2`/`b` ve ürün pini `7cc1168`. A2 için `a2/data/library.sqlite` var olmalı, B için `b/data` yok olmalı.
- `c_checks.py` (yeni): bir zaman penceresinde (1) her yama girdisinin saklı taşıma şemasının kanonik hash'i, donmuş değere eşitliği ve C.4'ün kanıt basamakları; ayrıca her `report_section` girdisinin şeması okunabilir olmalı ve sürüm sabiti yama kimliği ya da `deixis.report_section_draft.v2` olmalıdır, değilse girdi “tanınmayan” diye listelenir ve bütünlük hatası sayılır (işareti silen bozulma da yakalanır); (2) hata kaydı (`error_json`, `error_code` ya da `failed`/`outcome_unknown` durumu) olan her adımın C.4'teki sabit kuralla sınıfı; (3) bayraklar `patch_schema_integrity_ok`, `b_report_veto`, `coordinator_classification_needed`. `mode=ro`, tek okuma işlemi.
- `c_checks_cases.py` (yeni): `c_checks.py`'yi geçici SQLite dosyalarında on sentetik durumla sınar: başka kodlu ve başka mesajlı istek hatası (`400 Bad Request: response_format must be an object`), 300 karakterde kesilmiş mesaj, okunamayan hata metni, metinsiz yalnız `error_code` (`budget_exhausted`), zaman aşımı, uygulama doğrulaması, iptal olayıyla eşleşen ve eşleşmeyen kesinti (olay yok, olay adımdan sonra, başka koşunun olayı), donmuş değerden farklı, okunamayan ve işareti değiştirilmiş yama şeması, temiz bölüm taslağı girdisi, gönderilmemiş yama oturumu.
- Değişmeyenler: `poll_b.py`, `poll_report_b.py` (kol adı argümandır; `a2` için `a2/data`, `report-polls-a2.jsonl`, `report-poll-a2.stop`; tavan 60 / 90), `api.py`, `h9b_counts.py`, `p19_count.py`, `p19.sql`, `logical_table.py`, `manifest.py`. `gate_b.sh` ve `launch_b.sh` C'de çağrılmaz (eski pini taşırlar).

```h9b-c-files
0fb48152a27084c0c1aed347934da712c0f0f0332e1c5f62d591cb7aa78fefd7  .local/p9r-h9b/gate_c.sh
9d17d67676cabe6a508fa8a9559faf10adb61d78ccd901c83dcdb2ba13b21f27  .local/p9r-h9b/launch_c.sh
841d46ce67479636e37fbf26ce81d17327b306ab343d390e2b6cd350e0217239  .local/p9r-h9b/poll_b.py
c9d60768bbde2ef70ed3de52905b71f0cc79ec16e2efbfa05f3c418770181803  .local/p9r-h9b/poll_report_b.py
7c9bc47913cf5ff4e6b8dc51c6aef2a37ea11e961b98f82a051ddc52cc56d28d  .local/p9r-h9b/api.py
b44a93835b3b7bfd17bf4d5c10731304ab62a436e5729132ccf2bae80654a08e  .local/p9r-h9b/h9b_counts.py
58219952459a2e2bedc25722b5d7e5e158e04cbbe02d9d6a205e401f63136993  .local/p9r-h9b/p19_count.py
6d53789f7a1b898a4833bb993eaac222b29e5fa0cb209519fe020c3106e6acd1  .local/p9r-h9b/p19.sql
e3307b794ff24f4a93fb2abca701dac2e34a7992491036b68df05a08cec4210f  .local/p9r-h9b/logical_table.py
e1c375b4e8aecf61906472a0c60caa5932a3c0f2f5e201e2da0424a0cca97183  .local/p9r-h9b/manifest.py
45b0b72f9a26bd0df2e187ba0ca517ebff4905149efc357a0052d36a2536dab7  .local/p9r-h9b/c_checks.py
1f0011f7f4b286d42c31d5e488b6e994cc339c591cfd7daf41566344a96db4cf  .local/p9r-h9b/c_checks_cases.py
a416e1b2cd3a54d11e68b8842936b754680eccb74d83fe9548617e8f7d9be1f7  .local/p9r-h9b/evidence/method-manifest.json
f83d25b490fc1c29b6fc0799085a5e1ec93f8387c980ec9d2cf5eac138a7d939  .local/p9r-h9b/evidence/a2-source-manifest.json
f83d25b490fc1c29b6fc0799085a5e1ec93f8387c980ec9d2cf5eac138a7d939  .local/p9r-h9b/evidence/a2-copy-manifest.json
5ed7ef4ec5843dcd3451cdbadb5adbfd245c3bede4cac269ee4f731e0296d8d1  .local/p9r-h9b/evidence/a-logical-table-before.json
5ed7ef4ec5843dcd3451cdbadb5adbfd245c3bede4cac269ee4f731e0296d8d1  .local/p9r-h9b/evidence/a2-logical-table-before.json
706ae813cfc8bc9e34f0ab981f0ddc21d7d811c34003e8bad8471d72162f547d  .local/p9r-h9b/r9/a-pairs.json
7e5a080f7b32a37f89caf65eeaf897a69647c1e7e230ffc5adafe50c4b10898b  .local/p9r-h9b/r9/a-pairs-provenance.json
```

**Kuru denetimler (modelsiz, `7cc1168` üzerinde):** dondurma belgesi denetimleri çıkarılmış `gate_c.sh` rc 0 (`evidence/gate-c-dry*.txt`, `evidence/gate_c_dry*.sh`; aşama denetimleri için bkz. C.6). Ön koşul testleri: Ek B listesi + `tests/test_strict_schema_rules.py`, `tests/test_migrations.py`, `tests/test_reextract_r3_views.py`, `tests/test_report_export.py`, `tests/test_capability_binding.py`, `tests/test_connector_dispatch.py`: 1.428 geçti, 6 uyarı (SWIG ve anyio kullanımdan kalkma uyarıları) ve kapanışta bir SWIG uyarısı daha (`evidence/preflight-tests-c-dry.txt`). Sayım betikleri kayıtlı kimlik ve kayıtlı sınırlarla yeniden koşuldu: H9 verisinde P19 satır hash'i `b325ed94…8422`, a=[IV, V], b=2, c=1, d=0, 52 oturumda 3 `envelope_mismatch` (Ek B ile aynı); A verisinde `p19.json`, rapor sayıları (`[11:27:17.437368Z, -)`) ve POST öncesi sayıları (`[11:26:00.131180Z, 11:27:17.437368Z)`) kayıtlı dosyalarla JSON olarak eşit (`evidence/c-dry-*.json`). `c_checks_cases.py`: 10 durum geçti. `c_checks.py` A verisinde (`[11:27:17.437368Z, -)`) 1 yama girdisi (hash `e638e01d…`, donmuş değere eşit değil, beklenen; basamaklar: kuruldu, uygulama denemesi var, gönderim doğrulandı, sağlayıcı kabulü yok), V için `confirmed_schema_rejection` (300 karakterde kesik), III için `cancel_interrupt` (`run_cancelled` olayı 11:29:43.153Z, adım 11:29:43.158Z'de bitti), `b_report_veto=true`; H9 verisinde 0 yama girdisi, 0 tanınmayan bölüm girdisi, 122 `non_model`, 2 `application_validation`, veto yok, sınıflandırma gerekmez (`evidence/c-checks-dry-*.json`).

### C.3 Kol A2: H9 tablosu, taze kopya

H9'un durdurulmuş veri dizini, açık dosyası olmadığı (`lsof +D` boş) ve hiçbir DEIXIS sunucusu çalışmadığı denetlendikten sonra, hedef yokken `cp -Rp` ile `DEIXIS-h9b-run/.local/p9r-h9b/a2/data` dizinine kopyalandı (`evidence/a2-copy-time.txt`). Yan dosyalar dahil 65 dosya, en büyük `nlink` 1, kaynak ve kopya manifesti `80764df489b155375c3a4e0ed91d4185c68f66df9ee60fdd69719e2a4a2ded1f` (Ek B'deki kaynakla bayt bayt aynı dosya). Kopyada, sunucu başlamadan, altı mantıksal hash `evidence/a-logical-table-before.json` ile bayt bayt aynı. Migration 0067-0069 yalnız kopyaya, ilk başlangıçta uygulanır. **POST kapısı:** Ek B'deki A kapısı aynen (`report_ready.ready=true`, aktif koşu 0, `started` oturum 0, H9'un duraklamış eski rapor koşusu tarihsel kayıt olarak muaf, hiç sürdürülmez veya iptal edilmez), ek olarak altı mantıksal hash başlangıçtan sonra ve POST'tan hemen önce yeniden alınır ve ikisi de `a-logical-table-before.json` ile aynı olmalıdır. Uyuşmazlık yürütücü takdiri olmadan `ölçülemedi` verir; tablo onarılmaz. **A2'nin ikinci kapısı:** korpus, tablo ve R9 kayıtları H9'unkilerdir (Ek A'da incelendi, Ek B ve burada hash'le dondu); bu yüzden Sol high'ın onayladığı ve push edilen Ek C A2'nin ikinci kapısıdır. R9 çiftleri açıkça `r9/a-pairs.json` dosyasıdır (`a2-pairs.json` yoktur). A2 geliştirme korpusudur, bağımsız kanıt değildir.

### C.4 Canlı şema kapısı ve B'nin rapor POST'u

D204'ün ilk kapısı A2'dir. Her yama girdisi için kanıt basamakları `c_checks.py` ile ayrı yazılır: **kuruldu** (girdi ve saklı şemanın hash'i); **uygulama denemesi** (oturum satırı var; oturum adaptör çağrısından önce açıldığı için gönderimi kanıtlamaz); **gönderim** (`confirmed`: oturum model çıktısı sakladı ya da adımın hatası sağlayıcının şema reddidir; `not_sent`: adımın teslim sınıfı `before_send`; başka her durumda `unknown`); **sağlayıcı kabulü** (saklı model çıktısı var); **doğrulandı ve uygulandı** (oturumun doğrulamasında `anchor_patch` var); **yayımlandı** (raporun bölüm satırı bu adımı gösteriyor ve `valid`). Bir red başarısızlığı kanıtlar; reddin olmaması tek başına kabulü kanıtlamaz. “Yama şeması canlı API'de kabul edildi” yalnız sağlayıcı kabulü basamağı doğruysa ve o girdinin şema hash'i donmuş değere eşitse yazılır.

**Hata sınıfları** (sabit kural, `c_checks.py`): model dışı adım (`kind` `model` ile başlamıyor) `non_model`; hata metninde `invalid_json_schema` varsa `confirmed_schema_rejection`; `invalid_model_output` (uygulamanın aldığı bir çıktıyı reddetmesi) `application_validation`; saklı metni tam olarak `interrupted` olan `model_interrupted`, ancak aynı koşunun adımın bitişinden geç olmayan bir `run_cancelled` olayı varsa (koşunun kendi iptali) `cancel_interrupt`; başka her model adımı hatası (zaman aşımı, kota, bütçe, başka kodlu veya mesajlı istek hatası, okunamayan veya hiç saklanmamış metin, iptal olayıyla eşleşmeyen kesinti dahil) `model_error_needs_classification`. Adaptör hata metnini 300 karakterde keser (`backend/deixis/models/adapter.py`); A'nın saklı hatası da kesiktir ve tam hata metni ürün değiştirilmeden alınamaz. Ek C ürünü değiştirmez (Sol bunu bu ölçüm için kabul etti, belirsiz hatalar koordinatör kapısında kaldığı sürece); sınır sonuca yazılır ve tam hata yakalandığı iddia edilmez. `truncated` çözülen mesaj 300 karaktere ulaştıysa doğru, kısaysa yanlış, mesaj çözülemediyse veya sınıf `application_validation` ise boştur.

- A2'de bir `confirmed_schema_rejection` ya da yama şeması bütünlük hatası (okunamayan yama şeması, donmuş değerden farklı hash veya tanınmayan `report_section` girdisi; `patch_schema_integrity_ok=false`), yama yoluna girilmiş olsun olmasın, **B'nin rapor POST'unu engeller** (`b_report_veto=true`). Red aynı zamanda §5'in durdurma kuralıyla A2'yi durdurur; bütünlük hatasında canlı kabul iddiası kurulmaz. Sonraki adıma koordinatör karar verir.
- `model_error_needs_classification` sınıfında hata varsa B'nin POST'undan önce koordinatör sınıflandırır. Karar `evidence/a2/coordinator-classification.json` dosyasına `{"allow_b_report_post": true|false, "steps": {...}, "reason": "..."}` biçiminde, koordinatörün mesajı alıntılanarak yazılır ve Ek D'nin bloğunda donar.
- Veto ve sınıflandırma gereği yoksa ve A2 yama yoluna hiç girmediyse “A2'de yama maruz kalmadı; canlı kabul doğrulanmadı” yazılır ve B sürer.
- A2'nin başka her durması Ek B'nin kuralına bağlıdır: B yine koşar.

A2'nin nihai denetimi, sunucunun ve alt süreçlerinin çıkışı doğrulandıktan sonra `c_checks.py <a2 kütüphanesi> <sunucu başlangıcı>` ile alınır ve `evidence/a2/c-checks-final.json` olur; yürütücü koşu sırasında bilgi için ara çıktılar da alabilir (`c-checks-*.json`), karar yalnız nihai dosyadan çıkar. B'de hazırlık `[ilk keşif koşusunun created_at değeri, POST)` ve rapor `[POST, -)` pencereleri kullanılır (`evidence/b/c-checks-*.json`).

### C.5 Bütçe

Defter: H9'un izni 360 oturumdu; H9 52, A 7 kullandı; 301 kaldı. Koordinatörün yetkilendirdiği tavan 293'tür (Ek B'nin 300'lük tahsisi eksi A'nın 7'si); Ek B'nin tahsis dışında bıraktığı 8 oturum bu tavanın dışında kalır ve kullanılmaz. Tahsis: A2 raporu 60 oturum / POST'tan 90 dk; B hazırlığı en çok 2 deneme, birlikte 165 oturum / 240 dk (her doldurma 60 / 60 içinde; saat B'nin ilk keşif koşusunun kuyruğa girdiği anda başlar); B raporu 60 / 90. Toplam 285; 293'e kadar kalan 8 oturum yalnız gözlenen tavan aşımı içindir. Kollar arasında ödünç, sayaç sıfırlama ve devralınan uygunluk kuralı dışında yeniden deneme yoktur. H9'un hazırlığı tek denemede 45 oturum kullandı. K03 kuyruk istekleri ve okurlar Ek B'deki gibi (deneme başına 1, B'de toplam 2, 30 dk; okur rapor başına 4 istek / 60 dk, toplam 8 / 120 dk).

### C.6 Kol B ve Ek D

Ek B'nin “Ek C” dediği B kaydı (korpus, tablo ve R9, Ek A.4/A.5 biçiminde) bundan sonra **Ek D** adını alır; içerik ve inceleme aynı: `gpt-6.1-sol` high en çok 3 tur, dar Sol medium doğrulaması serbest, koordinatör push eder, `gate_c.sh` B'nin POST'undan önce Ek D'nin push edilmiş hash'iyle yeniden geçer. Ek D kendi `h9b-d-files` bloğunu taşır; blok `evidence/a2/c-checks-final.json` dosyasını ve, sınıflandırma gerektiyse, `evidence/a2/coordinator-classification.json` dosyasını içermek zorundadır. **B'nin POST koruması** `gate_c.sh` içinde `H9B_STAGE=b-post` ile çalışır: Ek D bloğu yoksa, nihai A2 denetimi blokta değilse, `b_report_veto=true` veya `patch_schema_integrity_ok=false` ise, sınıflandırma gerekip koordinatör kararı blokta yoksa ya da `allow_b_report_post` doğru değilse, ya da A2 veri dosyaları nihai denetimden sonra değişmişse (değişiklik zamanı) kapı geçmez. Kuru aşama sınaması (belge yerel dosyadan okunarak, geçici sentetik Ek D bloklarıyla): `a2` geçti; Ek D'siz `b-post`, aşamasız çağrı, veto, bütünlük hatası, eksik sınıflandırma ve ret veren sınıflandırma kapıyı kapadı; temiz durum ve izin veren sınıflandırma geçti (`evidence/gate-c-dry-stages.txt`). Değişiklik zamanı kuralı sınanmadı. B'nin hazırlığı A2 bittikten sonra başlar (iki kol 8873'tedir ve aynı anda çalışmaz). B'nin keşfi D201'in bağlı yetenekleri üzerinden yürür; bu H9'un keşfinden farklıdır.

### C.7 Kayıt ve D205 ile ilişki

Ek C, D202'nin içinde tarihli bir ek paragrafla kaydedilir (yeni karar numarası yok) ve STATUS'a bir satır eklenir. B.5 sayımları değişmez; `c_checks.py` onlara eklenir. A2 ve B veri dizinleri sunucu durdurulup çıkışı doğrulandıktan sonra olduğu gibi bırakılır (temizlenmez, yeniden kullanılmaz); D205'in dilim 4 maddesi tamamlanan bir raporu buradan kopyalayabilir. D205 ayrı kapılıdır: H9b sonucu push edilip koordinatör kaynakları bırakmadan hiçbir D205 maddesi koşmaz.

### C.8 Komutlar

```sh
cd /Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run
H9B_STAGE=a2 H9B_FREEZE_COMMIT=<Ek C hash> zsh .local/p9r-h9b/gate_c.sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .local/p9r-h9b/c_checks_cases.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. .venv/bin/python -m pytest -q -n 0 -p no:cacheprovider \
  --basetemp=/tmp/p9-h9c-preflight-tests tests/test_report_anchor_repair.py tests/test_report_handles.py \
  tests/test_report_failed_rows.py tests/test_report_api.py tests/test_p6_measure_report.py \
  tests/test_report_path_fix.py tests/test_report_path_fix_contracts.py tests/test_strict_schema_rules.py \
  tests/test_migrations.py tests/test_reextract_r3_views.py tests/test_report_export.py \
  tests/test_capability_binding.py tests/test_connector_dispatch.py
H9B_ARM=a2 H9B_FREEZE_COMMIT=<Ek C hash> nohup zsh .local/p9r-h9b/launch_c.sh > .local/p9r-h9b/evidence/server-a2.log 2>&1 &
.venv/bin/python .local/p9r-h9b/logical_table.py .local/p9r-h9b/a2/data/library.sqlite tbl_pQukBcMTicxNo3QPGaf9   # başlangıç sonrası ve POST'tan hemen önce
# rapor: POST /api/researches/res_5ZrJQgVQ5unqqCRpMbrr/reports {"table_id": "tbl_pQukBcMTicxNo3QPGaf9", "continue_with_failed": false}
.venv/bin/python .local/p9r-h9b/poll_report_b.py a2 <sunucu PID> res_5ZrJQgVQ5unqqCRpMbrr <rapor koşusu> <POST zamanı>
.venv/bin/python .local/p9r-h9b/h9b_counts.py .local/p9r-h9b/a2/data/library.sqlite <rapor> <sunucu başlangıcı> <POST zamanı>
.venv/bin/python .local/p9r-h9b/h9b_counts.py .local/p9r-h9b/a2/data/library.sqlite <rapor> <POST zamanı>
.venv/bin/python .local/p9r-h9b/p19_count.py .local/p9r-h9b/a2/data/library.sqlite <rapor>
.venv/bin/python .local/p9r-h9b/c_checks.py .local/p9r-h9b/a2/data/library.sqlite <sunucu başlangıcı> > .local/p9r-h9b/evidence/a2/c-checks-final.json   # sunucu çıkışı doğrulandıktan sonra
PYTHONPATH=backend:. .venv/bin/python scripts/p6_eval/measure_report.py snapshot --base http://127.0.0.1:8873 \
  --research res_5ZrJQgVQ5unqqCRpMbrr --report <rapor> --db .local/p9r-h9b/a2/data/library.sqlite \
  --out .local/p9r-h9b/evidence/a2/report --seed 20261003 --sample 30 --pairs .local/p9r-h9b/r9/a-pairs.json
```

B'nin komutları Ek B.6 ile aynıdır; `gate_b.sh`/`launch_b.sh` yerine `gate_c.sh`/`launch_c.sh`, `H9B_ARM=b`, hazırlık öncesi `H9B_STAGE=b-prep` ve Ek C hash'i, POST öncesi `H9B_STAGE=b-post` ve Ek D hash'i, R9 çiftleri Ek D'de donan `r9/b-pairs.json`. Sunucu her kolun işi bitince SIGTERM ile durdurulur; sunucunun ve kayıtlı `codex app-server` alt süreçlerinin çıkışı 120 s içinde ≤5 s aralıklı `ps` okumalarıyla doğrulanır.

### C.9 Sonuç dili

A “ürün şeması reddiyle durdu” diye ayrı yazılır. A2 “geliştirme korpusunda yeniden ölçüm (bağımsız değil)”, B “yeni korpus, tek koşu”. Her biri tek rapor modeline ve rapora hazır tablo koşuluna bağlıdır. Hata oranı, hız veya maliyet karşılaştırması, D198'in ya da RF2'nin nedensel etkisi, genel rapor kalitesi yazılmaz. Maruz kalma olmadan sıfır, etkinlik kanıtı değildir.

## Ek D — H9b kol B: korpus, tablo ve R9 (3 Ekim 2026, B'nin rapor POST'undan önce)

**Dayanak.** Ek B.2'nin “B'nin ikinci kapısı” (Ek C.6 ile adı Ek D oldu). B'nin hazırlığı Ek C push edildikten (`5c8cb98`) ve A2 bittikten sonra, `7cc1168` üzerinde, aynı ayrık worktree ve K05 ortamında koştu. Açık noktalar Claude Opus 5.5 + `gpt-6.1-sol` medium tarafından iki salt okunur ortak kararla, sahip adına kararlaştırıldı: başarısız satır, aynı eserin iki kaydı ve RF3 kesim kuralı (`evidence/decide4.md`, `decide4-out.md`); RF3 ile koşma, A2 verisi kuralındaki `-shm` istisnası ve B'nin POST yardımcısı (`evidence/decide5.md`, `decide5-out.md`, Sol high'ın 1. tur bulgularından sonra). Sol iki kararda da önerileri değiştirerek kabul etti; değişiklikler aşağıdadır. Bu ekte yazılmayan her kural Ek B ve Ek C'deki gibidir.

### D.1 A2'nin nihai denetimi (B'nin POST kapısı için)

A2 rapor koşusu (`run_Zjf9QhU911vTx2O7KmzX`, rapor `rpt_PHorhopCbIdENA1wFTdz`) 13:19:52Z'de `section_must_be_rewritten` ile duraklayıp durdu: VI. bölümün ilk çıktısı şemaya uygundu ama hiç iddia ve hiç `insufficient_evidence` girdisi taşımıyordu (`empty_section`); ürünün bunun için otomatik onarımı yok. Neden `client_timeout` değil, sürdürme yok, duraklamış koşu iptal edilmedi. Kapanış doğrulandı (terminal olay 1611, `snapshot_eligible`), sunucu ve `codex app-server` alt süreci çıktı, `c-checks-final.json` ondan sonra alındı. Nihai denetim: 1 yama girdisi, şema hash'i donmuş değere eşit; basamakların hepsi doğru (kuruldu, denendi, gönderildi, sağlayıcı kabul etti, doğrulandı ve uygulandı, IV `valid` yayımlandı); adım hatası yok; `patch_schema_integrity_ok=true`, `b_report_veto=false`, `coordinator_classification_needed=false`. Koordinatör sınıflandırması gerekmez. A2'nin sayıları sonuç belgesindedir.

### D.2 B'nin hazırlığı (deneme 1; ikinci deneme açılmadı)

- Sunucu B: `launch_c.sh`, 13:22:45.569Z, PID 60823, 8765 boş; sağlık `ok`, worker sahibi, kurtarılan 0. Gözlemci `poll_b.py b`.
- Araştırma `res_khW4MevleljQIeXvHsyl` (13:22:56.832Z): Q3 metni aynen, `academic`, `question_only`, `standard`, `codex`/`gpt-5.6-luna`/`medium`, `tr`; Ek B.2'nin anahtar terimleri oluşturma anında verildi, `key_terms_needed` duruşu olmadı.
- Hazırlık saati: ilk keşif koşusu `run_b3lxR1Ya9mpJwe2LJ9PH` 13:23:01.555Z'de kuyruğa girdi; tavan 165 oturum / 240 dk (17:23:01Z).
- Protokol kartı 13:24:01.937Z'de 3 ölçüt önerisi oturumundan sonra bekledi; öneri hash'i `8cf161418c8ed0fdb5a7b5ccd3a7d0d2db3c0de99c3eb83962394898711cad0f` (`evidence/b-research1-before-approval.json`). Terimler: ortam `water distribution network | water distribution networks` (ifade sayısı 9231), görev `pump scheduling` (1230, sorguda kök olarak), sonuç `optimization`; kapı sayısı 1148, `too_broad` yanlış; iddia veya dışlama sözcüğü yok. Kart değiştirilmeden, boş gövdeyle yürütücü (`claude-opus-5-5`) tarafından onaylandı; ürün `approved_by=user` saklar, onaylayan sahip değildir.
- Etkin ayarlar (keşif öncesi protokolde): `search_workflow=sw`, `query_strategy=legacy`, sağlayıcılar OpenAlex ve Semantic Scholar (kaynak yönlendirmesi; arXiv, bioRxiv ve PubMed alan payı düşük diye, IEEE kapsam dışı, Scopus/CORE/SerpApi `sw` aramasında yok), doğrulama sağlayıcısı Crossref; bütçe `max_model_calls` 39, `max_provider_requests` 8, `max_candidates` 250, `core_depth` 100, `results_per_query` 25, tam metin getirme `overlap` (`max_fulltext_works` 100), atıf zinciri açık (15 tohum, iki yön, 40 istek); ortam `DEIXIS_PROTOCOL_APPROVAL=ask`, `FULLTEXT_FETCH=auto`, `FULLTEXT_ADJUDICATION=auto`, `CITATION_CHAINING=auto`, `SEARCH_QUERY=model`, `ARXIV_SOURCE=off`, `MODEL_CONCURRENCY=6`. Varsayılan dışında yol seçilmedi.
- Protokol revizyonları (`evidence/b/protocol-records.json`): 1, onay anı, 13:24:43.844Z, `ae2b7c8584d8eb1fcf52ee8b0cedb27dded83e4bae046c302830a28d498587eb`; 2, ürünün kendi `data_expansion` kolu, 13:25:13.279Z, `30b8934457663bbc6d883bcdd1927ae3231b9fc38ec716ab4966aad72f3635d1`: 20 aday ifadeden yalnız `water distribution` kabul edildi ve iki sorgu eklendi (OpenAlex `"water distribution" AND pump`, Semantic Scholar `"water distribution" + pump`); toplam 4 derlenmiş sorgu. Bu genişlemeyi yürütücü değil ürün yaptı.
- Otomatik aşamalar: keşif 13:33:14Z, tam metin kararı `run_9Fx9AX8kOAwU5KybGq9D` 13:39:40Z'de tamamlandı; 53 uygulama oturumu (keşif 14, ölçüt önerisi 3 dahil; tam metin kararı 39). Model 100 özeti okudu.
- **Ara çağrı hataları:** 70 hazırlık oturumunun 66'sı `completed`, 4'ü `failed`: bir özet taraması (`mss_Gyapw7MTCq0IXhF4ikdL`) ve üç tam metin kararı (`mss_QrgbtcD5ciLhQ18CAIko`, `mss_QWKYs478VPooOrAb71QE`, `mss_PVOjlkyxiUv4sI78YZJG`). Her biri yaklaşık 5 dakika sonra `model_failed` / `outcome_unknown` ile bitti (olaylar 1123, 1306, 1310, 1313); ürün adımı otomatik yeniden gönderdi ve dört adım da sonunda başarılı oldu. Adım satırları sonradan başarılı olduğu için ilk hata metni üzerine yazıldı ve `c_checks.py` bunları göstermez; hata metninin içeriği bilinmez. Hazırlık koşuları duraklamadı; §5'in hazırlık kuralı tetiklenmedi. Sayılar (`evidence/b-research1-after-auto.json`): 2941 satır, 1867 tekil eser, otomatik dahil 11 (hepsi model uyuşması), kuyruk 7 (`fulltext_runs_disagree` 2, `include_quote_unverified` 3, `part_without_evidence` 2), PDF bekleyen 9; tam metin aranan 100, okunan 18, getirilemeyen 9. OpenAlex 20 istekte `rate_limited` döndü (19 atıf zinciri, 1 arama); §1.2 madde 5 gereği ayrı kayıttır, telafi edilmedi.
- **Aynı eserin iki kaydı.** `srv_vNsyqUVqApQJ5PT02sOV` (`wrk_5FVjlvQfdRf3gFQk0MgS`, DOI `10.4090/juee.2016.v10n1.135143`) ve `srv_EtW9BugJxdbJEJDwx2eW` (`wrk_gR8kakyx0OzvmGnxSMXx`, DOI `…135-143`) aynı makaledir: başlık, yazarlar, dergi ve yıl aynı, PDF baytları aynı (SHA-256 `76062cd5b149312b4e178c4aad038f4841ae0a230f4a54e5cff6784dcb41f2d7`, 442.390 bayt, aynı adres). Ürün birleştirmedi. §1.2 madde 3 gereği tek eser sayılır. Sol medium kararıyla iki satır da ürünün varsayılan yolunda kalır (`rows=None`, H9 gibi; `report_ready` her dahil kaynağı satır olarak ister ve seçim bu yüzden düzenlenmez). İkisi bağımsız tanık değildir; raporda bu makaleye fazla ağırlık verebilir; sonuçta açıkça yazılır. “Kimlik düzeyinde bağımsız” eski korpuslara göredir, bu iki satır arasında değildir.
- **Seçim (§1.2 madde 3):** 11 dahil kaynak 10 ayrı eser eder, yani hedef doldu. Satır sürümünde tam metni saklı 8 satır (7 eser), yalnız özeti olan 3 baş sürüm (kardeş sürümlerinde tam metin var: `srv_IN24K4El7eppuvOkaVSr`, `srv_hPN36ocoC5svt7J261FA`, `srv_S45jevZa9xm4SWeWYkME`). En az 3 tam metin hedefi karşılandı. Hedefe kuyruk geçişsiz ulaşıldığı için K03 kuyruk geçişi yapılmadı (madde 2 izin verir, zorunlu tutmaz); K03 isteği 0.
- **Bağımsızlık** (`independence_b.py`, `evidence/b/independence1.json`): 11 baş sürümün bütün sürümlerinin DOI, arXiv ve OpenAlex W kimlikleri izlenen belge envanteriyle (`b428c970…423a`) ve H9 korpusunun envanteriyle (`c5479f4c…be26`, DOI ve eser kimliği) kesiştirildi: 11'i de `bağımsız (kimlik düzeyinde)`. Eski dosya hash'leri ve belgelerde yazılmamış kimlikler `denetlenmedi`.
- **Tablo ve doldurma:** `tbl_ACVZv04QYr9024IW57mF` (13:42Z), 11 satır, §1.3'ün yedi `text` sütunu (H9'un sütun gövdelerinden aynen). Doldurma `run_ct9nJl0ZeQIIgn8qgpMh` 13:42:36.985Z – 13:45:19.495Z, 17 oturum (tavan 60 / 60 dk). Bir satır başarısız: `srv_EnueazJePWokccaWIXlh` (Lauricella22, “Water Distribution Network operation optimization: an industrial perspective”, tam metinli), `cell_extraction` bir onarımdan sonra `invalid_model_output` (`anchor_not_in_passage`, `unknown_passage_id`; adım `stp_u2lV9Cnu1TD15KjgI0rV`). `report_ready=false` (1 başarısız satır, 7 başarısız hücre).
- **Başarısız satır (Sol medium kararı, §1.2 madde 4):** madde 4 başarısız doldurma satırının dışlanmasına izin verir; asgari 6 korunduğu sürece hedef 10'a yeniden tamamlamak zorunlu değildir. Seçenek (a) uygulandı: yalnız o kaynağın seçimi ürünün seçim değişikliğiyle `excluded` yapıldı (`PATCH /selections/srv_EnueazJePWokccaWIXlh`, `expected_version` 3, gerekçe §1.2 madde 4'ü, başarısız adımı ve karar verenleri adlandırır); ürün bunu kişi kararı (`origin=user`) diye saklar, bu etiket bu satır için yanlıştır ve sonuçta yazılır. Yerine iş alınmadı, ikinci doldurma ve ikinci deneme açılmadı. Dışlama makale hakkında bilimsel bir hüküm değildir; başarısızlığa dayalı bir seçim etkisidir. Tablo satırı ve hücreleri dokunulmadan kaldı: mantıksal tablo hash'leri dışlamadan önce ve sonra aynı (`evidence/b/logical-table-*-exclusion.json`); seçim kümesi önce 11, sonra 10 (`evidence/b/selection-before-after.json`).
- **Rapora hazır tablo kapısı (§3):** dışlamadan sonra `report_ready` = hazır, `included_rows` 10, `cells_total` 70, `cells_left` 0, `failed_rows` 0, `failed_cells` 0 (`evidence/b/tables-list-after-exclusion.json`). 10 dahil satır 9 ayrı eser eder (6-10 aralığında). Dahil satırların 70 hücresi: `value` 63, `unknown` 4, `not_found_in_inspected_scope` 3; okuma derinliği `selected_sections` 49, `abstract` 21. Tablonun saklı satır sayısı 11 kalır.
- **Mantıksal tablo hash'leri** (dışlama sonrası, B'nin POST kapısının karşılaştırma değeri): satırlar 11 `7b9744862fbf3bd003a1b341028a64667261ea373f6c839c81dba865c9227ac3`, sütunlar 7 `9156396f3d0d93254356858d66e8323710c0d3a18e633f49f73fd64136e9c3bc`, sütun revizyonları 7 `ccab16efceca93190549aa00024b24060abc59e2ab354b3b11383120469b292f`, hücreler 77 `0c451f1a909181a83ef600e6d0e4e50df539b218cbca352da5c9bfc323c2b844`, güncel revizyonlar 70 `c990234df76801d41f331597047f19dee16efefb3a895d15dec42cc4347e9be6`, kanıt bağları 187 (`evidence/b/logical-table-after-exclusion.json`).
- **Hazırlık sonu:** dışlama 13:49:15.287Z, saatin 26. dakikası; 70 / 165 oturum (66 tamamlandı, 4 başarısız ve yeniden gönderildi), 1 / 2 deneme, 0 / 2 K03 isteği. Yalıtım: rapor 0, aktif koşu 0, `started` oturum 0. `c_checks.py` hazırlık penceresi (`[13:23:01.555Z, -)`): 0 yama girdisi, 1 `application_validation` (başarısız satır), 190 `non_model`, veto yok, sınıflandırma gerekmez (`evidence/b/c-checks-prep.json`). Kaynak, sürüm, DOI ve dosya hash'i envanteri: `evidence/b/source-inventory.json`.

### D.3 R9 çiftleri (§4.4, rapordan önce)

Seçim 13:50:28.194Z'de, B'nin hiçbir rapor çıktısı yokken yapıldı. Dahil satırların Denklem hücreleri kaynak sürümü sonra hücre kimliği sırasıyla okundu; metinde görüntülenen ve kökeni hücrede kayıtlı her ayrı formülasyon hücredeki sırasıyla alındı: 7 çift (Gencoglu16b 1, Menke16 1, Skworcow14 2, Candelieri18b 1, Gencoglu16 1, Rajabpour18 1). Seçilmeyenler gerekçesiyle köken dosyasındadır: Menke16'nın sözel “Minimise: Pumping cost subject to …” satırı ve formülü yazılmamış depo seviyesi kısıtı; Moller20'nin metin katmanında bozuk (4)-(7) denklemleri (hücre yalnız sembol adlarını sayar, formülasyon aktarmaz); Gencoglu16'nın sözle tarif edilen sınırları; özetten okunan üç satırın (`not_found_in_inspected_scope`) ve dışlanan satırın hücreleri. Kaynak anahtarları tektir (11 satır, 11 anahtar); aynı makalenin iki satırı ayrı anahtarlarla (Gencoglu16, Gencoglu16b) ikisi de çift verir. `value_sha256`, H9'daki gibi değer JSON'unun `sort_keys`, ayırıcılar `(',', ':')`, `ensure_ascii=False` SHA-256'sıdır. Dosyalar: `r9/b-pairs.json` `018dd36fd8aa3293aeab951aa725436c2187a953a442aed1356bf662192ca490`, `r9/b-pairs-provenance.json` `e9e4416ef1afeba965811df3d64c98a3fc1af1c53784c1e24dc495f6a362c1ff`. Sonradan değişmez.

### D.4 B'nin raporu hangi üründe koşar

RF3 ([D206](../decisions.md), `b90583b`) Ek D'nin ilk commit'i incelemeye gönderilmeden önce `origin/main`'e girdi; Sol medium'un kesim kuralına göre seçime açıktı. Ortak karar (`evidence/decide5-out.md`): **B'nin hazırlığı `7cc1168` üzerinde kayıtlı kalır; B'nin tek raporu `b90583b9d5e80b9680fd7142089da42b3466f5f5` üzerinde, B'nin durdurulmuş verisinin doğrulanmış kopyası `b2/data` ile koşar. Bu seçim Ek D'nin incelemeye gönderilen ilk commit'iyle donar; sonradan gelen ürün değişiklikleri onu yeniden açmaz.** Gerekçe: A2'yi durduran boş VI bölümü B'de de olasıdır (üç satır yalnız özetli, 21 hücre özet derinliğinde); RF3 tek bir sınırlı onarım fırsatı verir, tamamlanmayı garanti etmez ve eksik kanıtı sağlamaz. B'nin hücrelerine dokunulmaz, sınırlamalar sütunu zorlanmaz. A2 ile B'nin karşılaştırması RF3'ün etkisini ayıramaz (araya B6 girdi, korpus farklı). Aşağıdaki kapılardan biri geçmezse yürütme durur; bu, `7cc1168`'e kendiliğinden dönme izni vermez.

- **Durdurma ve kopya:** durdurmadan önce aktif koşu 0, `started` oturum 0, izleme 0, rapor 0 (`evidence/b/prestop-check.txt`). Sunucu 60823 14:09:28Z'de SIGTERM ile durdu, ~10 s içinde çıktı; kayıtlı `codex app-server` 61572 çıktı; gözlemci durdu; `lsof +D b/data` boş. Hedef yokken, sembolik bağ olmadan `cp -Rp b/data b2/data` (14:09:58Z): 55 dosya, en büyük `nlink` 1, kaynak ve kopya manifesti `9fe92b959940d270ae7f2ecf72a603d25fb80b70a05847a74e834d6bb4b9f6e5`. Kopyada altı mantıksal tablo hash'i D.2'deki değerlerle bayt bayt aynı (`evidence/b/b2-logical-table-before.json`); izleme 0. Bu salt okunur açılışlar `b2/data` içinde boş bir WAL ve bir `-shm` yan dosyası yarattı; `library.sqlite` içeriği değişmedi (`evidence/b/b2-manifest-after-reads.json`, 57 dosya, `be258e864da65f3c12d78219681dcad4938dedfae931d5b3f6a20f64c36e3236`). `b/data` hazırlık kaydı olarak dokunulmadan kalır.
- **Yeni ürün değerleri:** ölçüm worktree'si `b90583b`'ye ayrık olarak geçti (`uv sync --frozen --dry-run` değişiklik yok, arm64). `skill_package_hash` `sha256:031f5f09b272c4678861cd356624a0e40501961d465f55ea93a87fc6b0def16b`; şema manifesti değişmedi (`eb0becde…8366`, 23 dosya); 41 taşıma şeması, anahtar listesi `1a76b85c…82a0`, sıkı denetim sonuçları boş; yama şeması `f30984c2…9739` (değişmedi); kit ve kit testi pinleri değişmedi. Yöntem dosyaları için ayrı adlı yeni manifest `evidence/method-manifest-b90583b.json` (17 dosya, yalnız `references/report.md` değişti, toplam `a0e960502650b2c0c27fd28c256896bf0afd5032e871b9b37744ac4618f2f421`; toplam kuralı dosyada yazılı ve Ek B'nin manifestinden farklıdır). Ek C'nin manifesti tarihsel kayıttır.
- **Araya giren B6:** `7cc1168..b90583b` P8 B6'yı da taşır ([D187](../decisions.md)): migration 0070 ve 60 saniyede bir çalışan süreç içi izleme zamanlayıcısı. Migration yalnız `b2/data`'ya, ilk başlangıçta uygulanır; izleme sayısı migration öncesinde (0), başlangıçtan sonra ve POST'tan hemen önce 0 olmalıdır. Başlangıç doğrulaması yürütülebilir biçimde `b_prepost.py check` ile, sunucu başlar başlamaz alınır ve kaydedilir: en büyük uygulanmış migration 70, kurtarılan koşu/adım/oturum 0, izleme 0, altı mantıksal hash aynı; aynı denetimler POST'tan önce iki kez yinelenir. Değişmeyen tablo hash'leri tek başına migration başarısını göstermez.
- **Ön koşul testleri** (`b90583b`, modelsiz): Ek C listesi + `tests/test_report_empty_section.py`, `tests/test_report_flow.py`: 1.476 geçti, 6 uyarı (`evidence/b/preflight-tests-e-dry.txt`).

### D.5 B'nin rapor kapısı, POST yardımcısı ve komutlar

- **`gate_e.sh`** (`gate_c.sh`'nin kopyası, değişiklikler): ürün pini `b90583b`, paket hash'i `031f5f09…`, RF3 imi (`EMPTY_REPORT_SECTION_MESSAGE` ve `"empty_section"` `contracts.py` içinde), aşamalar `b2-start` ve `b-post`, iki aşamada da push edilmiş Ek D bloğu zorunlu; RF2 denetimleri, şema manifesti, `h9b-c-files` ve `h9b-d-files` blokları aynen. **A2 verisi kuralında `-shm` istisnası** (Sol medium onayı, `decide5-out.md` P2): kuru sınamada `gate_c.sh`'nin değişiklik zamanı kuralı A2 verisi değişmediği hâlde kapıyı kapadı, çünkü WAL kipindeki okuyucular `library.sqlite-shm` dosyasının zamanını salt okunur erişimde de değiştirir (nihai denetimden sonraki salt okunur sayımlar bunu yaptı; `evidence/b/gate-b-post-dry.txt`). `gate_e.sh` yalnız `-shm`'yi dışarıda bırakır; `library.sqlite` ve `library.sqlite-wal` var olmalı, zamanları `c-checks-final.json`'dan sonra olmamalı ve SHA-256 değerleri Ek D'de donan `evidence/a2/data-after-final.json` ile aynı olmalıdır (`library.sqlite` `77eec2ce4c9b9871fab0702fecdbef82dafe6161c3e0e6f1ce55858d935f7530`, WAL boş); eksik dosya veya uyuşmazlık kapıyı kapatır. Bu, saklı veritabanı ve WAL içeriğinin doğrulanmasıdır; geçmişte hiç yazma olmadığının kanıtı değildir ve A2'yi yeniden başlatma veya verisine yazma izni vermez. `gate_c.sh` değişmedi ve Ek C bloğundaki hash'iyle denetlenmeye devam eder. Kuru sınama (belge ve kararlar yerel dosyadan, dondurma atalığı dışarıda): `b2-start` ve `b-post` rc 0, 56 blok dosyası (`evidence/b/gate-e-dry-*.txt`, `evidence/b/gate_e_dry.sh`).
- **`launch_e.sh`**: `launch_c.sh` ile aynı; tek kol `b2` (`b2/data/library.sqlite` var olmalı), ürün pini `b90583b`.
- **`b_prepost.py`**, B'nin rapor POST'unun tek yolu (Sol medium P3). `check` ve `post` kipleri. Dondurma kapısı `gate_e.sh` (`b-post`, verilen dondurma commit'i) yalnız ilk geçişte bir kez çalışır ve çıkış 0 olmalıdır; canlı denetimler `post` kipinde iki kez yapılır (ikincisi POST'tan hemen önce). Canlı denetimler: PID'in komutu başlatıcının komutuyla birebir aynı; ortamında `DEIXIS_DATA_DIR=<b2/data>` tam bir öğe olarak var; 8873'teki tek dinleyici bu PID; veritabanındaki worker kirası (`worker_owner.pid`) bu PID; sağlık `ok`, worker sahibi, paket hash'i `031f5f09…`, kurtarılan koşu/adım/oturum 0; tek okuma işleminde `b2` üzerinde en büyük migration 70, altı mantıksal hash `evidence/b/logical-table-after-exclusion.json` ile aynı, dahil kaynak kümesi donmuş on kimlikle aynı, `queued`, `running` veya `pause_requested` koşu 0, `started` oturum 0, izleme 0, araştırmanın raporu 0; tablo listesinde `ready=true`, `included_rows` 10, `cells_total` 70, `cells_left` 0, `failed_rows` 0, `failed_cells` 0; kapsam `codex`/`gpt-5.6-luna`/`medium`; Codex bağlantısı hazır, oturum açık, Luna listede; 8765'te dinleyici yok. Başarısız okuma, bozuk yanıt veya bilinmeyen süreç/port durumu ret demektir (çıkış 2, istek yok). Gövde yalnız `{"table_id": "tbl_ACVZv04QYr9024IW57mF", "continue_with_failed": false}`. Yanıt 202 değilse ya da JSON'u `^run_[0-9A-Za-z]{8,40}$` biçiminde (tam eşleşme) dize kimlik, `kind="report"` ve bu araştırma kimliğini taşıyan bir nesne değilse sonuç belirsizdir: yeniden denenmez, araştırmanın rapor koşuları okunup kaydedilir, çıkış 3. Her çağrı zaman damgalı bir kayıt yazar (`evidence/b2/prepost-*.json`). Yürütücü bu sırada başka değişiklik yapmaz.
- **`b_prepost_cases.py`**: modelsiz 34 durum (taklit kapı, süreç, port ve API; veritabanı denetimleri `b2` veritabanının geçici kopyasında, kopyada migration 70 ve kira PID'i ayarlanarak): olumlu `check`; kapı hatası; başka süreç; tam olmayan komut; başka veya önek eşleşmeli veri dizini; 8873'te başka, iki veya bilinmeyen dinleyici; paket hash'i; worker sahibi değil; başlangıçta kurtarılan iş; hazır değil; 11 satır; kapsam; Codex oturumu kapalı; 8765 dinleyici veya bilinmiyor; API okuma hatası; dahil küme farkı; mantıksal hash farkı; `started` oturum; başka PID'in kirası; migration 70 yok; `pause_requested` koşuyla `post` reddi; altı bozuk veya uyuşmayan 202 yanıtı (sonda satır sonu taşıyan kimlik dahil) (tek gönderim, çıkış 3); tek POST ve donmuş gövde; 500 yanıtında yeniden denememe; denetim hatasında POST'suz ret. 34'ü geçti; `b2/data` değişmedi.
- **Komutlar** (çalışma dizini `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run`, Ek D push edildikten sonra):

```sh
cd /Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run
H9B_STAGE=b2-start H9B_FREEZE_COMMIT=<Ek D hash> zsh .local/p9r-h9b/gate_e.sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .local/p9r-h9b/c_checks_cases.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .local/p9r-h9b/b_prepost_cases.py
H9B_ARM=b2 H9B_FREEZE_COMMIT=<Ek D hash> nohup zsh .local/p9r-h9b/launch_e.sh > .local/p9r-h9b/evidence/server-b2.log 2>&1 &
.venv/bin/python .local/p9r-h9b/b_prepost.py check <Ek D hash> <PID>   # başlangıç doğrulaması
.venv/bin/python .local/p9r-h9b/b_prepost.py post <Ek D hash> <PID>    # tek POST yolu
.venv/bin/python .local/p9r-h9b/poll_report_b.py b2 <PID> res_khW4MevleljQIeXvHsyl <rapor koşusu> <POST zamanı>
```

- **Sayımlar ve pencereler:** hazırlık kanıtı `b/data` üzerindedir (`c-checks-prep.json` ve D.2'nin kayıtları). `h9b_counts.py` bir rapor kimliği ister ve rapor yalnız `b2`'de olacağı için hazırlık penceresi `b2/data` üzerinde sayılır: `.venv/bin/python .local/p9r-h9b/h9b_counts.py .local/p9r-h9b/b2/data/library.sqlite <rapor> 2026-10-03T13:23:01.555Z 2026-10-03T14:09:28Z`; `b2` o pencere için `b/data`'nın bayt kopyasıdır (manifest eşit), oturum satırları aynıdır. Rapor penceresi `b2/data` üzerindedir: `h9b_counts.py b2/data/library.sqlite <rapor> <b2 sunucu başlangıcı> <POST zamanı>` (beklenen 0 oturum) ve `<POST zamanı>`; `p19_count.py b2/data/library.sqlite <rapor>`; `c_checks.py b2/data/library.sqlite <b2 sunucu başlangıcı>`; kit `snapshot --db .local/p9r-h9b/b2/data/library.sqlite --pairs .local/p9r-h9b/r9/b-pairs.json --out .local/p9r-h9b/evidence/b2/report`. Migration ve başlangıç hazırlık sayaçlarını sıfırlamaz, ikinci rapor hakkı yaratmaz. B raporu 60 oturum / POST'tan 90 dk; rapor tamamlanırsa K09 okurları Ek B.3'ün sınırıyla.

```h9b-d-files
c955efe5efbb9fd4f3ce5d757bd4b72e6686bd5e18a2bce79157de1ab90c9477  .local/p9r-h9b/evidence/a2/c-checks-final.json
1b4b2c1841d59156244e1e957957a5d45f478dc16cdd0b4d50b4d700c81ded48  .local/p9r-h9b/evidence/a2/data-after-final.json
5efa5d82d9b84d59473b006d716961d163e55996e106a4fd6fdedc4d965070d9  .local/p9r-h9b/evidence/a2/counts-report.json
83e9498ea52c29e1317c5260d2a5ca2114beb4b973e4f427bfc3a23bbbb072e9  .local/p9r-h9b/evidence/a2/counts-pre.json
0080cdc7a21dadb27cfde1ad078eaa464d7a89f01f32ea0d78413199e16cbce0  .local/p9r-h9b/evidence/a2/p19.json
327e66dfdc6e49fcc5dc57968a25bc4e4c7a5bcd95175d984dd449c826b7f03d  .local/p9r-h9b/evidence/a2/report/results.json
dceab8bf3e3f115e7ce742c0efd52e0ac480e5877526b635978a01803bf6062e  .local/p9r-h9b/evidence/b-research1-before-approval.json
40953167cd75abc7dcec51009282fc26a51edaeaa9532f254a501c5f3fa31f38  .local/p9r-h9b/evidence/b-research1-after-auto.json
8b102a7325ae266f485f5c5beb785745104ad699d6475776aabe7bb423fa8433  .local/p9r-h9b/evidence/b/research1-before-exclusion.json
eb810343d0c428b45379493a3c30e7754c48427efece0b0e239348280afbbd36  .local/p9r-h9b/evidence/b/research1-after-exclusion.json
a6fc7f4ab7bf4769af2d6a7d89f0039c576ee6f9818a755b58888c18b460402b  .local/p9r-h9b/evidence/b/selection-before-after.json
89c8849e7121b77146f510693dccad3cfa7dbb4391bd9a6dd5b789aced8a5838  .local/p9r-h9b/evidence/b/table1-after-fill.json
3938307cd908c83694d0ab67a70d87564bb00288d1493a5551dc0c3d209708d3  .local/p9r-h9b/evidence/b/tables-list-after-fill.json
cf5ae83d13756241514aee3860680c4d3e3854892d426577e5f9fa3fd82c3bfb  .local/p9r-h9b/evidence/b/tables-list-after-exclusion.json
01d68412c9fab8cddb93cc58883638eaedcf4b57edbed0a3076fbbdbdad1c2c5  .local/p9r-h9b/evidence/b/logical-table-before-exclusion.json
01d68412c9fab8cddb93cc58883638eaedcf4b57edbed0a3076fbbdbdad1c2c5  .local/p9r-h9b/evidence/b/logical-table-after-exclusion.json
a19a8f37f3dfc9561bc458f2602ca9237abda32359a8919a05fad56bb887aaab  .local/p9r-h9b/evidence/b/source-inventory.json
3f28cb6730a23825c71966a3ad06db65c4c19c3984c2e3a478264bae32123ee5  .local/p9r-h9b/evidence/b/independence1.json
bf1d55585108552d23571007d86bdb1a019105946f2c19f8d01926f9663b042c  .local/p9r-h9b/evidence/b/c-checks-prep.json
33b6a90658f105d886945c532ef975298708eda54b2c699cff7a2b310b5c1223  .local/p9r-h9b/evidence/b/protocol-records.json
37b68862e0d9d0090e5c401709b4fff137eeb597a5dbbf85507bea37673c1568  .local/p9r-h9b/evidence/b/prestop-check.txt
a79cfc55143d490a464d24ec7a68289ee2216d288c3eec090ec31c3c7efc2054  .local/p9r-h9b/evidence/b/children-before-stop.txt
6d34894473c392e7b57ef3d113c875a129f6ca80be0eb19a20179d54f04a99d4  .local/p9r-h9b/evidence/b/b2-copy-time.txt
67584ed19c5c9d2dc42b11b1f5a8f8fc142c316685081c42f624d76da979b097  .local/p9r-h9b/evidence/b/b2-source-manifest.json
67584ed19c5c9d2dc42b11b1f5a8f8fc142c316685081c42f624d76da979b097  .local/p9r-h9b/evidence/b/b2-copy-manifest.json
01d68412c9fab8cddb93cc58883638eaedcf4b57edbed0a3076fbbdbdad1c2c5  .local/p9r-h9b/evidence/b/b2-logical-table-before.json
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/b/b2-manifest-after-reads.json
cd9a711320a2045645e65ef333f24e555d1c78ad1ded26b6a5ecb35275886f43  .local/p9r-h9b/evidence/method-manifest-b90583b.json
6fa7ecb40422270757586cc0201ab9f5bf10b287e0f98715bac94140a2b4d973  .local/p9r-h9b/independence_b.py
e25b256eb92c51488a035fb0dcc0f621a9fc21899c42cb022c0b346991ee0b83  .local/p9r-h9b/gate_e.sh
04d5a83810efc3e88eda441bd54a44a5da53e8abd41d3e9b922cb739e1197163  .local/p9r-h9b/launch_e.sh
d506f8467e0908368eab0930df3853a89c2623ff8d0b3ada1762e3fb33f161fe  .local/p9r-h9b/b_prepost.py
f2649c7b9ed28490fd9b6ddbe711ad0f401aa804b4ccb46383a1e4fc35e770e1  .local/p9r-h9b/b_prepost_cases.py
018dd36fd8aa3293aeab951aa725436c2187a953a442aed1356bf662192ca490  .local/p9r-h9b/r9/b-pairs.json
e9e4416ef1afeba965811df3d64c98a3fc1af1c53784c1e24dc495f6a362c1ff  .local/p9r-h9b/r9/b-pairs-provenance.json
72552cd3e64eda1512388dd8de23ae89aa832f8662af38b26aeecebdb4e043ec  .local/p9r-h9b/evidence/decide4-out.md
0337b271e0a42ced26dc1baf868a7a35f258334346197ced140a5352c6d33ecd  .local/p9r-h9b/evidence/decide5-out.md
```

## Ek E — H9c: B raporunun RF4 üzerinde yeniden koşusu (3 Ekim 2026, H9c rapor POST'undan önce)

**Dayanak.** Koordinatör görevi: RF4 ([D207](../decisions.md), `2b185a8`) üzerinde yalnız B'nin raporunu, B'nin durmuş hazırlık verisinin yeni ve doğrulanmış kopyasında yeniden koşmak; kalan 186 uygulama oturumundan tek rapor koşusu, aynı durdurma kuralları ve K09/K10 okurları. Açık noktalar Claude Opus 5.5 + `gpt-6.1-sol` medium tarafından, salt okunur ortak kararla, sahibin sürekli yetkisi kapsamında sahip adına kararlaştırıldı; sahipten ayrıca onay istenmedi. Karar D202'ye tarihli **Ek E amendment** olarak eklenir.

**Öncelik:** Ek E, H9c için önceki eklerle çelişen ürün/kit pinleri, veri yolu, bütçe ve ikinci okur komutu hükümlerinin yerine geçer. Önceki metinler ve sonuçlar tarihsel kayıt olarak değişmez. §5'in sonraki ölçüm için yeni korpus hükmüne bu koşuya özgü açık istisna verilir: H9c aynı hazırlanmış B korpusunu kullanır. Yeni keşif, kuyruk geçişi, seçim değişikliği, doldurma veya hücre düzeltmesi yapılmaz.

### E.1 B'nin önceki sonucu ve yeniden koşunun kapsamı

B'nin rapor koşusu `run_UriYrNZpRYuwcMd3d4kI`, `b90583b` üzerinde `b2/data` ile tamamlandı; 20 uygulama oturumu kullandı. On model bölümü geçerliydi, fakat birleştirme kontrolü raporu reddetti ve rapor `draft` kaldı. R1c `0/1`; sonuç raporun kabul edildiğini veya bilimsel olarak doğrulandığını göstermez. İkinci okur için bir istek kullanıldı. R9 kit kusuru nedeniyle ölçülemedi.

RF4, modelin oluşturabileceği engelleyici birleştirme sorunlarını bölüm doğrulamasına taşır; çapa yaması ve ifade onarımından sonra tam doğrulayıcıyı yeniden çalıştırır; sınırlı `validation_context` ve VII için kabul edilmiş VI boşluklarını taşır; R9 kaynak anahtarının boş değerle ezilmesini önler; Türkçe kaynakları anlatan çoğul “bu çalışmaların” gibi ifadeleri kendi çalışmasını anlatan tekil ifadeden ayırır. Gerçek modelde henüz ölçülmemiştir.

H9c yalnız yeni bir rapor koşusudur. `b2/data` önceki raporu içerdiğinden kaynak veya yürütme dizini olarak kullanılmaz; eski koşu sürdürülmez. B'nin sonuçları yeni kitle yeniden puanlanmaz.

### E.2 Ürün ve donmuş değerler

| Kayıt | Değer |
|---|---|
| Ürün | `2b185a8c1c2b463aca01a34ae23eda098d25f4b4`; ayrık worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run`, kendi arm64 `.venv`'i, `uv sync --frozen`. Main ilerlese de yeniden sabitlenmez. |
| Runtime `skill_package_hash` | `sha256:7389a1c722e396321ac5d8bacee9bb87cf71ac87b7be07c77a2235775a6f0dcb`; salt okunur hesaplandı, `integrity_issues()` boş. |
| Şema manifesti | 23 dosya, `df3acb7a3ec1199f0622f276212a1a72a1242db0bb1ff22ad569b058d5ec66a5`. Ek D'den farklıdır: RF4 `step-input.schema.json` dosyasını değiştirir. Hesap yöntemi Ek D ile aynıdır. |
| Modele giden şemalar | 41 anahtar; sıralı anahtar listesinin `json.dumps` SHA-256'sı `1a76b85cc1be334dae09da00a8129dc3577e948ace098466205b57c620d182a0`; bütün `strict_compatibility_issues` sonuçları boş. |
| Yama taşıma şeması | Değişmedi: `f30984c2f2680b294b47822ba3c01f0f8c16bf89d69f6e0c0f9b3134911a9739`; argümansız şemanın kanonik JSON SHA-256'sı. |
| Kit `scripts/p6_eval/measure_report.py` | `80662aa18fb6e24ae507799754bf36fdc463c466d7201e857aa4537600fbcff9` |
| Kit testi `tests/test_p6_measure_report.py` | `de523a167813ebb7bc592ebc9477c49e35d685c8bd0d492826446f9489f1659b` |
| Yöntem manifesti | Yeni `evidence/method-manifest-2b185a8.json`: 17 dosya; `aggregate_sha256` `fc2eee27dedc81f753647c25eadaae002e22b405ee3a17cbb9c0ae9381a44b6f`. Ek D'nin `method-manifest-b90583b.json` biçimi ve `sha256(json.dumps(files, sort_keys=True))` kuralı kullanılır. Manifest dosyasının kendi SHA-256'sı aşağıdaki blokta ayrıca donar. |

Paket hash'inin yeniden doğrulama komutu:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -c \
 'from deixis.domain.skill import package_hash, integrity_issues; print(package_hash()); print(integrity_issues())'
```

`git diff --name-only b90583b 2b185a8 -- backend/deixis/storage/migrations` salt okunur denetimde boş çıktı verdi. Migration dosyaları değişmedi. RF4'ün `validation_context` sınırı 262144 serileştirilmiş karakterdir; aşımda ürünün kayıtlı ret yolu korunur, yürütücü girdiyi küçültmez veya kesmez.

### E.3 Yeni veri kopyası ve hazırlık kayıtlarının korunması

Yeni yürütme dizini `.local/p9r-h9b/c/data`, kaynak yalnız `.local/p9r-h9b/b/data` olur. Araştırma `res_khW4MevleljQIeXvHsyl`, tablo `tbl_ACVZv04QYr9024IW57mF`; D.2'nin on dahil kaynak kimliği, 11 saklı tablo satırı, yedi sütunu, altı mantıksal hash'i ve D.3'ün yedi R9 çifti değişmez. On dahil satır dokuz ayrı eserdir; aynı PDF'yi taşıyan iki satır ve başarısız doldurma nedeniyle dışlanan satırın seçim etkisi korunur.

**Kaynak manifesti hakkında doğrulanan ayrıntı:** bu kararın salt okunur dosya denetiminde `b/data` 57 dosya içeriyor; sembolik bağ yok, en büyük `nlink` 1, manifest toplamı `be258e864da65f3c12d78219681dcad4938dedfae931d5b3f6a20f64c36e3236`. D.4'ün 55 dosyalık kaynak manifestindeki bütün dosyalar aynı; eklenenler yalnız sıfır baytlık `library.sqlite-wal` ve 32.768 baytlık `library.sqlite-shm` dizinidir; oluşma geçmişleri bilinmiyor. `library.sqlite` SHA-256'sı tarihsel kaynak manifestiyle aynı: `81840a445e8a653adbb7585846c9cc6bc6e846ec4f9a1a4329954bc32a2732f8`. Bu denetim yan dosyaların ne zaman veya hangi okuyucuyla oluştuğunu göstermez. Güncel kaynak manifesti açıkça kaydedilir; 55 dosyalık manifestle tam eşitlik iddia edilmez.

Kopya, D.4'ün doğrulanmış kopya yöntemiyle hazırlanır:

1. B/B2 sunucularının, kayıtlı `codex app-server` alt süreçlerinin ve gözlemcilerin kapalı olduğu doğrulanır. `lsof +D b/data` temiz boş sonuç vermeli; başarısız veya belirsiz süreç denetimi durdurur.
2. `c/data` mevcut olmamalı; kaynak/hedef yollarında sembolik bağ olmamalı. SQLite yan dosyaları dahil `cp -Rp b/data c/data` kullanılır; kopya zamanı kaydedilir.
3. `manifest.py` ile kaynak ve kopya manifestleri dış kanıt dizinine yazılır. İkisi dosya dosya eşit, kaynak yukarıdaki güncel manifestle eşit ve her ikisinde en büyük `nlink` 1 olmalıdır. Kaynaktaki tarihsel 55 dosyanın içerikleri ayrıca D.4 kaynak manifestiyle eşit kalmalıdır.
4. SQLite denetimleri yalnız yeni kopyada yapılır. Altı mantıksal tablo hash'i `evidence/b/logical-table-after-exclusion.json` ile aynı; dahil küme aynı; aktif koşu, `started` oturum, izleme ve araştırmanın raporu sıfır olmalıdır. Kopya pre-0070 şemasını taşımalıdır. Okumalardan sonra yeni bir kopya manifesti alınır; WAL/SHM yan dosyalarına etkisi ayrıca kaydedilir.

`b/data` ve `b2/data` üzerinde sunucu, SQLite okuyucusu, migration, onarım veya test çalıştırılmaz; dosyalar silinmez, değiştirilmez, yeniden adlandırılmaz. Kaynak doğrulaması dosya içeriklerini okuyarak yapılır.

**Kopya kaydı (bu ek yazılırken yapıldı):** süreç denetimi 16:52:55Z (`evidence/c/precopy-check.txt`): `serve` süreci, 8873 dinleyicisi ve `lsof +D b/data` çıktısı yok, `c/data` yoktu, sembolik bağ 0. `pgrep -f` desenine uyan tek süreç PID 36025 Codex masaüstü bildirimcisiydi (`CodexNotify`); argümanında bu ekin taslak isteminin metni vardı, sunucu veya gözlemci değildir. Bu yüzden yürütücü, launcher'ın `pgrep` desenini taşıyan metni Codex istemlerine koymaz; böyle bir bildirimci kalırsa launcher başlamayı reddeder ve bu ret korunur. `cp -Rp` 16:53:05Z; kaynak ve kopya manifestleri eşit (57 dosya, `be258e86…3236`, en büyük `nlink` 1), tarihsel 55 dosya değişmedi, fazlası yalnız sıfır baytlık `-wal` ve 32.768 baytlık `-shm`. Kopyada altı mantıksal hash `logical-table-after-exclusion.json` ile aynı; en büyük migration 69, aktif koşu 0, `started` oturum 0, rapor 0, izleme 0, dahil küme `c_prepost.py` sorgusuyla donmuş on kaynağa eşit (`copy-prestart-check.json`); okumalardan sonra manifest aynı (`manifest-after-reads.json`). `b/data/library.sqlite` ve `c/data/library.sqlite` SHA-256 değeri aynı: `81840a44…32f8`.

0070 yalnız `c/data` üzerinde ilk sunucu başlangıcında uygulanır. Başlangıçtan hemen sonra `c_prepost.py check` şu değerleri doğrular ve kaydeder: en büyük migration 70, kurtarılan koşu/adım/oturum sıfır, izleme sıfır, altı mantıksal hash aynı. Aynı canlı denetimler POST yardımcısının iki geçişinde yeniden yapılır.

### E.4 Executor kapıları ve yürütme

D.5'in bütün kontrolleri korunur. Yeni dosyalar: `gate_f.sh`, `launch_f.sh`, `c_prepost.py`, `c_prepost_cases.py`. Değişiklikler yalnız ürün/paket/şema/kit pinleri, yeni veri ve kanıt yolları, aşama adları ve Ek E/RF4 kontrolleridir. Port **8873** kalır; başka bir ölçüm sunucusu varken başlanmaz. `H9B_FREEZE_COMMIT` ve `H9B_ARM` değişken adları uyumluluk için korunur; kol `c`, aşamalar `c-start` ve `c-post` olur.

`gate_f.sh` push edilmiş Ek E'yi, D202'de Ek E kaydını, D207'yi, ürün/dondurma atalığını ve `h9c-e-files` bloğunu zorunlu tutar. Ek C/D bloklarının dosya hash'i kontrolleri, A2 veto/sınıflandırma koruması ve A2'nin veritabanı/WAL içerik-zaman kontrolleri aynen kalır; `-shm` istisnası değişmez. Eski gate ve launcher dosyaları değiştirilmez.

`c_prepost.py` tek rapor POST yoludur. D.5'in kesin süreç komutu, tam veri-dizini ortam öğesi, tek 8873 dinleyicisi, worker kira PID'i, sağlık/paket, migration, mantıksal hash, dahil küme, sıfır aktif iş/izleme/rapor, hazır tablo, Luna bağlantısı ve boş 8765 kontrollerinin hepsini korur. Donmuş POST gövdesi değişmez. Belirsiz yanıt yeniden gönderilmez; araştırmanın rapor koşuları okunup kaydedilir ve çıkış 3 korunur.

`c_prepost_cases.py` **sunucu başlamadan ve 0070 yeni kopyaya uygulanmadan önce** çalıştırılır. Yalnız `c/data` dosyalarının geçici kopyasını değiştirir; 34 durum ve beklenen çıkışlar korunur. Testteki migration satırı ekleme yalnız geçici kopyadadır.

Ek D'nin modelsiz ön koşul test listesine `tests/test_report_rf4.py`, `tests/test_report_step_input.py`, `tests/test_report_assembly.py` ve `tests/test_phrasebank.py` eklenir. Kuru denetimler (modelsiz, `2b185a8` üzerinde, sunucu başlamadan): `c_checks_cases.py` 10 durum geçti; `c_prepost_cases.py` 34 durum geçti (`evidence/c/prepost-cases.txt`); Ek D listesi ve bu dört dosya ile 1.743 test geçti, 6 uyarı (`evidence/c/preflight-tests-f.txt`). Kapı `gate_f.sh` Ek E push edilmeden çalışamaz; ilk çalışması `c-start` aşamasıdır. Ek E, mevcut K12 usulüyle Sol high incelemesinden geçip koordinatörce push edilmeden sunucu veya rapor başlatılmaz. Yeni pin başarısızsa eski ürüne otomatik dönüş yoktur.

```sh
cd /Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run
H9B_STAGE=c-start H9B_FREEZE_COMMIT=<Ek E hash> zsh .local/p9r-h9b/gate_f.sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .local/p9r-h9b/c_checks_cases.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .local/p9r-h9b/c_prepost_cases.py
H9B_ARM=c H9B_FREEZE_COMMIT=<Ek E hash> nohup zsh .local/p9r-h9b/launch_f.sh > .local/p9r-h9b/evidence/server-c.log 2>&1 &
.venv/bin/python .local/p9r-h9b/c_prepost.py check <Ek E hash> <PID>
.venv/bin/python .local/p9r-h9b/c_prepost.py post <Ek E hash> <PID>
.venv/bin/python .local/p9r-h9b/poll_report_b.py c <PID> res_khW4MevleljQIeXvHsyl <rapor koşusu> <POST zamanı>
```

### E.5 Bütçe ve durdurma

Koordinatörün bu görev için verdiği defter: A 7 + A2 10 + B hazırlık 70 + B rapor 20 = **107 / 293**, kalan **186 uygulama oturumu**. H9c'ye yalnız **bir rapor koşusu, 60 uygulama oturumu / POST'tan 90 dk** tahsis edilir. Kopyalanan 70 hazırlık oturumu tarihsel kayıttır; yeniden tüketim sayılmaz. Her yeni oturum, onarım ve izinli yeniden gönderim dahil sayılır. Kalan bütçe yeni hazırlık, ikinci rapor veya model değişikliği yetkisi vermez; 60 oturumluk rapor tavanı büyütülmez. Poll aralığında gözlenen aşım ayrıca kaydedilir; aşım payı yeni çağrı başlatma izni değildir.

K09/K10 okurları rapor başına en çok **4 istek / toplam 60 dk** kullanabilir. Ek B'nin **H9b toplam 8 istek / 120 dk** tavanı H9c'yi de kapsayan ortak tavan olarak korunur; sıfırlanmaz. **B'nin defteri düzeltilerek yazılır:** K09 ilk okurun okumasını K10'a sayar; B'nin sonuç kaydı yalnız ikinci okurun isteğini saymıştı. B'de iki okuma vardı: ilk okur (yürütücü, ayrı model isteği değil, bir istek sayılır) `review.orig.md`'nin saklandığı 14:52:12Z'den kitin `second` adımının çalıştığı 14:57:50Z'ye kadar, 5 dk 38 s (`second-manifest.json` oluşma zamanı; okuma `review.orig.md` saklandıktan sonra başladı, notların sonraki düzeltme eki 15:06Z civarındadır ve puanlamayı değiştirmedi); ikinci okur 14:59:28Z–15:00:01Z, 33 s (`evidence/b2/req1-start.txt`, `req1-end.txt`). B toplamı 2 istek, 6 dk 11 s; ortak defterde **6 istek ve yaklaşık 113 dk** kalır. H9c yine rapor başına 4 istek / 60 dk ile sınırlıdır; ilk okur da bu sayıma girer ve başlangıç/bitiş zamanı aynı biçimde kaydedilir. Her yeni ilk/ikinci okur veya tamamlama isteği K10'a sayılır. Bütçe veya okur yoksa ilgili metrikler ölçülemedi kalır.

§5 ve Ek B/C/D durdurma kuralları değişmez: 15 s gözlem, saklı terminal kök nedenler, yalnız bütün kök nedenler `client_timeout` ise bütçe içinde 10 dk sonra bir kez aynı koşuyu sürdürme; kota/yük, model uyuşmazlığı, araç ihlali, başka/karışık hata veya dolan tavanla durma. Bekleme saate dahildir. Duraklamış koşu iptal edilmez. Nihai snapshot için yürütücü dönüşü, sıfır `started` oturum ve 120 s kapanış penceresinde `snapshot_eligible` birlikte gerekir. Port 8765 kuralları ve geçersiz ölçüm yolu aynen sürer.

### E.6 Snapshot, okurlar ve sayımlar

D.5 ve istem §5'in sırası aynıdır; yalnız veri `c/data`, kanıt `evidence/c`, gözlemci dosyaları `report-polls-c.jsonl` / `report-poll-c.stop`, snapshot çıktısı `evidence/c/report` olur. R9 girdileri D.3'ün değişmeyen `r9/b-pairs.json` ve köken dosyasıdır. Yeni kit yalnız H9c için kullanılır; eski R9 sonucu değişmez.

D202'nin B sonucu için kayıtlı yorum korunur: durdurulmadan `completed` olan rapor koşusunda, birleştirme raporu `draft` bıraksa bile K09 okurları ve bütün kit satırları çalışır; R1c gerçek kabul durumunu gösterir. Durmuş koşuda `snapshot --stopped` ve okursuz `score` yolu uygulanır.

İlk okur `claude-opus-5-5`, `medium`, kör olmayan yürütücü analisttir. İkinci okur `claude-sonnet-5-5`, `medium`, yeni ve ayrı oturumdur. §4.3'ün izinli alanları, `review.orig.md`, ikinci paket eşitliği, R3 ek birim biçimi, okunamadı yolu, deterministik aktarım ve aktarım sonrası eşitlik kontrolü aynen uygulanır. Tohumlar `20261003` ve `20261004`; her ölçüt sayfasındaki destekleyen kontroller en çok beştir. İlk hükümler ve kontrol etiketleri ikinci okura verilmez.

B'de sapma olarak kaydedilen **`--output-format json` H9c için önceden donmuş komutun parçasıdır**. Depo dışındaki yeni ve boş `/tmp/p9r-h9c-reader2/` dizininde:

```sh
claude -p --model claude-sonnet-5-5 --effort medium --tools "" \
  --strict-mcp-config --setting-sources "" --no-session-persistence \
  --output-format json < packet.md > reading2-raw.json 2> reading2-err.txt
```

Ham JSON korunur; içindeki metin yanıtı kayıpsız olarak `reading2-raw.md` dosyasına çıkarılır, sonra §4.3'ün satır JSON aktarımı uygulanır. İstenen ve dönen model kimliği kaydedilir; kimlik yoksa veya uyuşmazsa okuma başka model konmadan durur. Yalnız istem §5'in model isteği yapılmadan gerçekleşen `--setting-sources ""` ayrıştırma hatası istisnası korunur; `--output-format json` çıkarılmaz.

`h9b_counts.py`, `p19_count.py`, `p19.sql` ve `c_checks.py` değişmez. H9c başlangıç–POST penceresi ve POST sonrası pencere ayrı sayılır; başlangıç–POST'ta beklenen yeni oturum sıfırdır. B hazırlığının 70 oturumu ayrı tarihsel kayıt olarak gösterilir. Yama basamakları, paket damgası, `envelope_mismatch`, çıkarılan iddialar ve P19 a–e aynı kuralla yazılır. RF4 doğrulama/context hataları saklı issue kodlarıyla ayrıca raporlanır; kit dışında puan üretilmez.

### E.7 Sonuç kaydı ve donmuş dosyalar

Sonuç `docs/product/p9r-report-results.md` içinde ayrı tarihli **H9c** bölümüne, karar ve sonuç D202'ye ayrı Ek E paragrafı olarak yazılır. Ürün/dondurma hash'leri, gerçek koşu/rapor kimlikleri, kopya ve migration kapıları, bütçe, durma/kapanış, bölüm ve birleştirme durumları, R1–R11/P19, okur kimlikleri, istekler, süreler ve sapmalar kaydedilir.

B ile karşılaştırma aynı hazırlanmış korpusta **bir koşuya karşı bir koşudur**. RF4 B'nin çıktılarından geliştirilmiştir; H9c bağımsız doğrulama değildir. Arada başka ürün değişiklikleri de vardır ve R9 kit sürümü değişmiştir. Tamamlanma, birleştirme kabulü veya metrik farkları RF4'ün nedensel etkisi, hata oranı, genel kalite, hız/maliyet üstünlüğü ya da genelleme kanıtı olarak sunulmaz. B'nin R9'u ölçülemedi kalır.

Aşağıdaki SHA-256 değerleri yürütücü dosyaları ve koşu öncesi kayıtlar oluşturulduktan sonra dolduruldu; `gate_f.sh` her birini denetler. Eski executor dosyaları Ek C/D bloklarıyla ayrıca denetlenir. Değişmeyen yardımcılar burada da açıkça listelenir. Bütçe defteri ve `protocol.md` gibi koşu sırasında ekleme yapılan kayıtlar dosya bloğuna alınmaz.

```h9c-e-files
f46f3b19ddd25eea80a3d4db6e4d14d1a7a766e5733ea6bc362eb1312e105651  .local/p9r-h9b/gate_f.sh
93b7ccc00cc273c0ba3ebaf029061701e9ee9e47a6c08c837e93ff582b6acd98  .local/p9r-h9b/launch_f.sh
3f3dcd4b2cc17a39c4b02bc5dbbeb11c7ddc1b23f429ffb1dd19158ad7c5b356  .local/p9r-h9b/c_prepost.py
c3a6ee969037a784c8f5288b66e4cacb34346790b6dc4f458b687477ffb4b6c5  .local/p9r-h9b/c_prepost_cases.py
c9d60768bbde2ef70ed3de52905b71f0cc79ec16e2efbfa05f3c418770181803  .local/p9r-h9b/poll_report_b.py
7c9bc47913cf5ff4e6b8dc51c6aef2a37ea11e961b98f82a051ddc52cc56d28d  .local/p9r-h9b/api.py
b44a93835b3b7bfd17bf4d5c10731304ab62a436e5729132ccf2bae80654a08e  .local/p9r-h9b/h9b_counts.py
58219952459a2e2bedc25722b5d7e5e158e04cbbe02d9d6a205e401f63136993  .local/p9r-h9b/p19_count.py
6d53789f7a1b898a4833bb993eaac222b29e5fa0cb209519fe020c3106e6acd1  .local/p9r-h9b/p19.sql
e3307b794ff24f4a93fb2abca701dac2e34a7992491036b68df05a08cec4210f  .local/p9r-h9b/logical_table.py
e1c375b4e8aecf61906472a0c60caa5932a3c0f2f5e201e2da0424a0cca97183  .local/p9r-h9b/manifest.py
45b0b72f9a26bd0df2e187ba0ca517ebff4905149efc357a0052d36a2536dab7  .local/p9r-h9b/c_checks.py
1f0011f7f4b286d42c31d5e488b6e994cc339c591cfd7daf41566344a96db4cf  .local/p9r-h9b/c_checks_cases.py
80662aa18fb6e24ae507799754bf36fdc463c466d7201e857aa4537600fbcff9  scripts/p6_eval/measure_report.py
de523a167813ebb7bc592ebc9477c49e35d685c8bd0d492826446f9489f1659b  tests/test_p6_measure_report.py
018dd36fd8aa3293aeab951aa725436c2187a953a442aed1356bf662192ca490  .local/p9r-h9b/r9/b-pairs.json
e9e4416ef1afeba965811df3d64c98a3fc1af1c53784c1e24dc495f6a362c1ff  .local/p9r-h9b/r9/b-pairs-provenance.json
a193073f303a59045ba27558b6f603b36d05cd635941a4944751af2937759730  .local/p9r-h9b/evidence/method-manifest-2b185a8.json
76d63f1a0f513e1209612429ba74a510d33ba35d94c0b8f8ddeb0891867acf8b  .local/p9r-h9b/evidence/c/precopy-check.txt
60e2b0126652a005be5e1455a858381f3883fdef416ea2f88c963988cea954ed  .local/p9r-h9b/evidence/c/copy-time.txt
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/c/source-manifest.json
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/c/copy-manifest.json
01d68412c9fab8cddb93cc58883638eaedcf4b57edbed0a3076fbbdbdad1c2c5  .local/p9r-h9b/evidence/c/logical-table-before.json
9b19cebd382b41466566ffb875dd0ffdd4c06834b080073af11a9389ea487624  .local/p9r-h9b/evidence/c/copy-prestart-check.json
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/c/manifest-after-reads.json
```

## Ek F — H9d: B raporunun RF5 üzerinde yeniden koşusu (3 Ekim 2026, H9d rapor POST'undan önce)

**Dayanak.** Koordinatör görevi: RF5 ([D209](../decisions.md), `1f4903f`) üzerinde yalnız B'nin raporunu, B'nin durmuş hazırlık verisinin yeni ve doğrulanmış kopyasında bir kez yeniden koşmak; kalan 162 uygulama oturumundan tek rapor koşusu, aynı durdurma kuralları ve K09/K10 okurları. Açık noktalar Claude Opus 5.5 + `gpt-6.1-sol` medium tarafından sahip adına kararlaştırılır. Karar D202'ye tarihli **Ek F amendment** olarak eklenir; RF5'in ürün kararı D209'dur.

**Öncelik:** Ek F, H9d için önceki eklerle çelişen ürün/yöntem pinleri, veri yolu ve bütçe hükümlerinin yerine geçer. Önceki metinler ve sonuçlar tarihsel kayıt olarak değişmez. §5'in sonraki ölçüm için yeni korpus hükmüne bu koşuya özgü açık istisna verilir: H9d aynı hazırlanmış B korpusunu kullanır. Yeni keşif, kuyruk geçişi, seçim değişikliği, doldurma veya hücre düzeltmesi yapılmaz.

### F.1 Önceki sonuçlar ve yeniden koşunun kapsamı

B'nin rapor koşusu `run_UriYrNZpRYuwcMd3d4kI`, `b90583b` üzerinde `b2/data` ile tamamlandı; 20 uygulama oturumu kullandı. On model bölümü geçerliydi, fakat birleştirme kontrolü raporu reddetti ve rapor `draft` kaldı. R1c `0/1`; R9 kit kusuru nedeniyle ölçülemedi. B'de iki okur isteği ve toplam 6 dk 11 s kullanıldı.

H9c, `2b185a8` üzerinde `c/data` ile koştu: `run_mWEug1ro09ZlJDBV5O5B`, rapor `rpt_85lvdp1HjlTnqUYXvjUG`. Koşu 309,1 s ve 24 çağrıdan sonra `section_failed` ile durakladı; dokuz model bölümü geçerli, özet başarısızdı. Özetin ilk taslağı geçerliydi; uyarılar için yapılan ifade onarımı `abstract.2#2` cümlesine “Bu çalışma” kalıbını getirdi. RF4'ün tam doğrulaması bunu `own_work_phrase_in_claim` olarak reddetti. Birleştirmeye gelinmedi, rapor `in_progress` kaldı. Neden zaman aşımı değildi; sürdürme ve duraklamış koşuya iptal yapılmadı. Kapanış doğrulandı; durmuş snapshot ve okursuz puanlama yolu uygulandı. H9c okur bütçesi tüketmedi.

RF5, uyarılar için yapılan ifade onarımının adayını tam bölüm girdisine karşı doğrular. Engelleyici hata varsa adayın tamamını reddeder ve modelin onarım öncesi taslağını korur; `phrase_repair_rejected`, `report_phrase_repair_rejected` ve kalan uyarılar için `unframed_exception` kayıtlarını üretir. RF4'ün son tam doğrulaması korunur. Bu davranış, korunan taslağın anlamsal veya bilimsel olarak doğru olduğunu göstermez.

H9d yeni bir rapor koşusudur. `b2/data` ve `c/data` önceki raporları içerdiğinden kaynak veya yürütme dizini olarak kullanılmaz; eski koşular sürdürülmez ve yeniden puanlanmaz.

### F.2 Ürün ve donmuş değerler

| Kayıt | Değer |
|---|---|
| Ürün | `1f4903f1fed1fd9cd44262a7a9e16e55f521d962`; ayrık worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run`, kendi arm64 `.venv`'i, `uv sync --frozen`. Main ilerlese de yeniden sabitlenmez. |
| Runtime `skill_package_hash` | `sha256:098f14114e12a515f7f32e3ccfe3bd3592e7e7c88d6a4d5bd13f4af6a9849da5`; salt okunur yeniden hesaplandı, `integrity_issues()` boş. |
| Şema manifesti | 23 dosya, `df3acb7a3ec1199f0622f276212a1a72a1242db0bb1ff22ad569b058d5ec66a5`; Ek E ile aynı. Sıralı `contracts/research/*.schema.json` dosyaları için `<dosya adı> <sha256>` satırları, sonda satır sonu dahil, SHA-256 ile özetlenir. |
| Modele giden şemalar | 41 anahtar; `sha256(json.dumps(sorted(transport)).encode())` değeri `1a76b85cc1be334dae09da00a8129dc3577e948ace098466205b57c620d182a0`; bütün `strict_compatibility_issues` sonuçları boş. |
| Yama taşıma şeması | `f30984c2f2680b294b47822ba3c01f0f8c16bf89d69f6e0c0f9b3134911a9739`; argümansız şemanın `json.dumps(..., sort_keys=True, separators=(',', ':'), ensure_ascii=False)` serileştirmesinin SHA-256'sı; Ek E ile aynı. |
| Kit `scripts/p6_eval/measure_report.py` | `80662aa18fb6e24ae507799754bf36fdc463c466d7201e857aa4537600fbcff9`; Ek E ile aynı. |
| Kit testi `tests/test_p6_measure_report.py` | `de523a167813ebb7bc592ebc9477c49e35d685c8bd0d492826446f9489f1659b`; Ek E ile aynı. |
| Yöntem manifesti | Yeni `evidence/method-manifest-1f4903f.json`: 17 dosya; `aggregate_sha256` `c01c6ad1842c13c706f04cf3362b65de524e6ac5e007bc76e2e96824d529f9b1`. Ek E'nin dosya sırası, biçimi ve `sha256(json.dumps(files, sort_keys=True))` kuralı korunur. |

Runtime/şema/kit pinleri arasında RF5 yalnız yöntem paket hash'ini değiştirir; yöntem dosyalarının manifest toplamı da buna bağlı olarak değişir. Manifestte değişen tek dosya `references/report.md` olup yeni SHA-256'sı `6cb7d2bd989999fd4be5f08b71f22e17058836f5dd42feeb189a590e2721c91e` değeridir.

Paket hash'inin yeniden doğrulama komutu:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -c \
 'from deixis.domain.skill import package_hash, integrity_issues; print(package_hash()); print(integrity_issues())'
```

Salt okunur `git diff --name-only 2b185a8 1f4903f -- backend methods contracts scripts/p6_eval tests/test_p6_measure_report.py` denetiminde yalnız şu dosyalar değişti:

```text
backend/deixis/workflow/report/phrasing.py
backend/deixis/workflow/report/sections.py
methods/deixis-research/references/report.md
```

`git diff --name-only 2b185a8 1f4903f -- backend/deixis/storage/migrations` boş çıktı verdi. Migration değişmedi. `1f4903f..66e2352` farkı P8 B8b kayıtları, `STATUS.md`, karar belgesi, betikler ve testlerden oluşur; ürün bu sonraki main commit'ine taşınmaz.

Yöntem manifesti yürütücü tarafından oluşturulur. Ek E manifestinin `files` girdileri aynı sırayla güncellenip aynı `aggregate_rule` korunarak `json.dumps(manifest, indent=1)` ile, sonda ek satır sonu olmadan yazılırsa dosyanın beklenen SHA-256'sı `58be99aad3a56e3dc8d6a9855c2b8819724b4ff2d515c87d89740ade4039a28f` olur. Dosya gerçekten yazıldıktan sonra hash'i ayrıca ölçülüp F.7 bloğuna konur; farklı serileştirme dosya hash'ini değiştirir, yöntem toplamını değiştirmez.

### F.3 Yeni veri kopyası ve hazırlık kayıtlarının korunması

Yeni yürütme dizini `.local/p9r-h9b/d/data`, kaynak yalnız `.local/p9r-h9b/b/data` olur. Araştırma `res_khW4MevleljQIeXvHsyl`, tablo `tbl_ACVZv04QYr9024IW57mF`; D.2'nin on dahil kaynak kimliği, 11 saklı tablo satırı, yedi sütunu, altı mantıksal hash'i ve D.3'ün yedi R9 çifti değişmez. On dahil satır dokuz ayrı eserdir; aynı PDF'yi taşıyan iki satır ve başarısız doldurma nedeniyle dışlanan satırın seçim etkisi korunur.

Ek E'de doğrulanan kaynak 57 dosyalıydı: manifest toplamı `be258e864da65f3c12d78219681dcad4938dedfae931d5b3f6a20f64c36e3236`, en büyük `nlink` 1; tarihsel 55 dosya değişmemişti. Ek dosyalar yalnız sıfır baytlık `library.sqlite-wal` ve 32.768 baytlık `library.sqlite-shm` idi. `library.sqlite` SHA-256'sı `81840a445e8a653adbb7585846c9cc6bc6e846ec4f9a1a4329954bc32a2732f8` değeriydi. Bunlar H9d'nin yeni kopya denetiminin beklenen değerleridir; yeni doğrulama yapılmadan güncel sonuç diye sunulmaz.

Kopya, Ek E.3 ve D.4'ün doğrulanmış kopya yöntemiyle hazırlanır:

1. B/B2/H9c sunucularının, kayıtlı `codex app-server` alt süreçlerinin ve gözlemcilerin kapalı olduğu doğrulanır. 8873 dinleyicisi ve `lsof +D b/data` sonucu denetlenir; temiz boş sonuç dışında başarısız veya belirsiz süreç denetimi durdurur. `d/data` henüz bulunmamalıdır. Kaynak/hedef yollarında sembolik bağ olmamalıdır.
2. SQLite yan dosyaları dahil `cp -Rp b/data d/data` kullanılır. Kopya zamanı `evidence/d/copy-time.txt` dosyasına yazılır. Önceden hazırlanmış `b2/data` veya `c/data` kopyalanmaz.
3. `manifest.py` ile kaynak ve kopya manifestleri `evidence/d/source-manifest.json` ve `copy-manifest.json` dosyalarına yazılır. Dosya dosya eşitlik, beklenen 57 dosyalık toplam, en büyük `nlink` 1 ve tarihsel 55 dosyanın D.4 kaynak manifestiyle içerik eşitliği doğrulanır. Fazla dosyalar yalnız yukarıdaki WAL/SHM olmalıdır. Uyuşmazlıkta kopya kabul edilmez.
4. SQLite denetimleri yürütücü tarafından yalnız yeni `d/data` kopyasında yapılır. Altı mantıksal tablo hash'i `evidence/b/logical-table-after-exclusion.json` ile aynı; dahil küme donmuş on kaynağa eşit; aktif koşu (`queued`, `running`, `pause_requested`), `started` oturum, izleme ve araştırmanın raporu sıfır; en büyük migration 69 olmalıdır. Sonuçlar `logical-table-before.json` ve `copy-prestart-check.json` dosyalarına yazılır. Okumalardan sonra `manifest-after-reads.json` alınır; WAL/SHM etkileri, özellikle SHM'nin salt okunur erişimde değişebilmesi, ayrı kaydedilir. Veritabanı/WAL uyuşmazlığı kabul edilmez; SHM farkı gizlenmez ve içerik değişmezliğinin kanıtı olarak kullanılmaz.

`b/data`, `b2/data` ve `c/data` üzerinde sunucu, SQLite okuyucusu, migration, onarım veya test çalıştırılmaz; dosyalar silinmez, değiştirilmez veya yeniden adlandırılmaz. Kaynak doğrulaması dosya içerikleriyle yapılır.

**Codex bildirimcisi uyarısı:** Ek E'deki süreç taramasına uyan `CodexNotify` süreci, taslak istem metnini argümanında taşıyan masaüstü bildirimcisiydi. Yürütücü launcher'ın `pgrep` desenini taşıyan metni Codex istemlerine koymaz. Yeni precopy kaydında böyle bir eşleşme varsa PID, komut ve neden açıkça kaydedilir; yalnız açıklamasız biçimde yok sayılmaz. Launcher böyle bir eşleşme nedeniyle başlamayı reddederse ret korunur; launcher filtresi gevşetilmez.

**H9d kopya kaydı (bu ek yazılırken yapıldı):** süreç denetimi 17:53:15Z (`evidence/d/precopy-check.txt`): `serve` süreci, `pgrep` eşleşmesi (CodexNotify dahil), gözlemci, 8873 ve 8765 dinleyicisi ve `lsof +D b/data` çıktısı yok; `d/data` yoktu; sembolik bağ 0. `cp -Rp` 17:53:22Z. Kaynak ve kopya manifestleri dosya dosya eşit: 57 dosya, `be258e86…3236`, en büyük `nlink` 1; tarihsel 55 dosya değişmedi; fazlası yalnız sıfır baytlık `library.sqlite-wal` ve 32.768 baytlık `library.sqlite-shm`. Kopyada altı mantıksal hash `logical-table-after-exclusion.json` ile aynı; en büyük migration 69, aktif koşu 0, `started` oturum 0, rapor 0, izleme 0, dahil küme `c_prepost.py`/`d_prepost.py` sorgusuyla donmuş on kaynağa eşit (`copy-prestart-check.json`). Okumalardan sonra manifest aynı (`manifest-after-reads.json`, `be258e86…3236`); `d/data/library.sqlite` SHA-256'sı `81840a44…32f8`.

0070 yalnız `d/data` üzerinde ilk sunucu başlangıcında uygulanır. Başlangıçtan hemen sonra `d_prepost.py check` en büyük migration 70, kurtarılan koşu/adım/oturum sıfır, izleme sıfır ve aynı altı mantıksal hash'i doğrular. Aynı canlı denetimler POST yardımcısının iki geçişinde yeniden yapılır.

### F.4 Executor kapıları ve yürütme

D.5 ve E.4'ün bütün kontrolleri korunur. Yeni dosyalar `gate_g.sh`, `launch_g.sh`, `d_prepost.py`, `d_prepost_cases.py` olur. Değişiklikler ürün/paket pinleri, yeni veri ve kanıt yolları, aşama adları ve eklenen Ek F/D209/RF5 kontrolleridir. Şema ve kit pinleri değişmez. Port **8873** kalır; başka bir ölçüm sunucusu varken başlanmaz. `H9B_FREEZE_COMMIT` ve `H9B_ARM` değişken adları korunur; kol `d`, aşamalar `d-start` ve `d-post` olur.

`gate_g.sh` push edilmiş Ek F'yi, D202'de Ek F kaydını, D209'u, ürün/dondurma atalığını ve `h9d-f-files` bloğunu zorunlu tutar. **Ek C/D/E blokları da zorunlu kalır ve bütün dosya hash'leri denetlenir.** A2 veto/sınıflandırma koruması, A2 veritabanı/WAL içerik-zaman kontrolleri ve yalnız `-shm` istisnası değişmez. RF4 marker kontrolleri korunur; RF5 için `phrasing.py` içinde `def rejected(issues:`, `"phrase_repair_rejected"` ve `"report_phrase_repair_rejected"` marker'ları ayrıca aranır. Marker denetimi davranış testi yerine geçmez. Eski executor dosyaları değiştirilmez.

`d_prepost.py` tek rapor POST yoludur. Kesin süreç komutu, tam veri-dizini ortam öğesi, tek 8873 dinleyicisi, worker kira PID'i, sağlık/paket, migration, mantıksal hash, dahil küme, sıfır aktif iş/izleme/rapor, hazır tablo, Luna bağlantısı ve boş 8765 kontrollerinin hepsi korunur. POST gövdesi değişmez:

```json
{"table_id": "tbl_ACVZv04QYr9024IW57mF", "continue_with_failed": false}
```

Belirsiz yanıt yeniden gönderilmez; araştırmanın rapor koşuları okunup kaydedilir ve çıkış 3 korunur.

`d_prepost_cases.py` **sunucu başlamadan ve 0070 yeni kopyaya uygulanmadan önce** çalıştırılır. Yalnız `d/data` dosyalarının geçici kopyasını değiştirir; 34 durum ve beklenen çıkışlar korunur. Migration satırı ekleme yalnız geçici test kopyasındadır.

Ek E'nin modelsiz ön koşul test listesi aynen korunur ve `tests/test_report_rf5.py` eklenir. Modelsiz denetimler `1f4903f` üzerinde yapılır: `c_checks_cases.py`, `d_prepost_cases.py`, ön koşul pytest listesi ve yeni dosyaların sözdizimi kontrolleri. SQLite açmayan salt okunur ortak-yazar denetiminde pinler yeniden hesaplandı ve önerilen gate Python gövdesi ile iki Python yardımcısının dönüşmüş metinleri AST ayrıştırmasından geçti; bu, 34 durumun veya pytest'in çalıştırıldığı anlamına gelmez.

**Kuru denetimler (modelsiz, `1f4903f` üzerinde, sunucu başlamadan):** `zsh -n` ile `gate_g.sh` ve `launch_g.sh` sözdizimi geçti; `c_checks_cases.py` 10 durum (`evidence/d/c-checks-cases.txt`); `d_prepost_cases.py` 34 durum (`evidence/d/prepost-cases.txt`); E listesi ve `tests/test_report_rf5.py` ile 1.750 test geçti, 6 uyarı (`evidence/d/preflight-tests-g.txt`). Yöntem manifesti dosyası beklenen SHA-256 ile yazıldı (`58be99aa…a28f`).

Bu alan gerçek komutları, ürün commit'ini, geçme/kalma sayılarını, uyarıları ve `evidence/d/prepost-cases.txt` / `evidence/d/preflight-tests-g.txt` kayıtlarını belirtir. Başarısız denetim varken başlanmaz. `gate_g.sh` Ek F push edilmeden geçemez; ilk gerçek çalışması `d-start` aşamasıdır. Ek F, mevcut K12 usulüyle Sol high incelemesinden geçip koordinatörce push edilmeden sunucu veya rapor başlatılmaz. Yeni pin başarısızsa eski ürüne otomatik dönüş yoktur.

```sh
cd /Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .local/p9r-h9b/c_checks_cases.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .local/p9r-h9b/d_prepost_cases.py
H9B_STAGE=d-start H9B_FREEZE_COMMIT=<Ek F hash> zsh .local/p9r-h9b/gate_g.sh
H9B_ARM=d H9B_FREEZE_COMMIT=<Ek F hash> nohup zsh .local/p9r-h9b/launch_g.sh > .local/p9r-h9b/evidence/server-d.log 2>&1 &
.venv/bin/python .local/p9r-h9b/d_prepost.py check <Ek F hash> <PID>
.venv/bin/python .local/p9r-h9b/d_prepost.py post <Ek F hash> <PID>
.venv/bin/python .local/p9r-h9b/poll_report_b.py d <PID> res_khW4MevleljQIeXvHsyl <rapor koşusu> <POST zamanı>
```

### F.5 Bütçe ve durdurma

Görev başlangıcı defteri: A 7 + A2 10 + B hazırlık 70 + B rapor 20 + H9c 24 = **131 / 293**, kalan **162 uygulama oturumu**. H9d'ye yalnız **bir rapor koşusu, 60 uygulama oturumu / POST'tan 90 dk** tahsis edilir. Kopyalanan 70 hazırlık oturumu tarihsel kayıttır; yeniden tüketim sayılmaz. Her yeni oturum, onarım ve izinli yeniden gönderim dahil sayılır. Başlangıç–POST penceresinde beklenen yeni oturum sıfırdır; sapma gizlenmez ve ortak deftere yazılır.

Kalan 162 oturum yeni hazırlık, ikinci rapor veya model değişikliği yetkisi vermez; 60 oturumluk rapor tavanı büyütülmez. Poll aralığında gözlenen aşım ayrıca kaydedilir; aşım payı yeni çağrı başlatma izni değildir.

K09/K10 okurları H9d için en çok **4 istek / toplam 60 dk** kullanabilir; Ek B'nin **H9b toplam 8 istek / 120 dk** ortak tavanı sıfırlanmaz. Başlangıçta kullanılan **2 istek / 6 dk 11 s**, kalan **6 istek / 113 dk 49 s** vardır. H9c okur kullanmadı. İlk yürütücü okuması da bir istek sayılır; ilk/ikinci okuma ve tamamlama isteklerinin başlangıç/bitiş zamanları aynı deftere yazılır. H9d'nin kullanılabilir okur bütçesi, kendi tavanıyla ortak defterdeki bakiye arasındaki küçük değerdir. Okur veya bütçe yoksa ilgili metrikler ölçülemedi kalır.

§5 ve Ek B/C/D/E durdurma kuralları değişmez: 15 s gözlem; saklı terminal kök nedenler; yalnız bütün kök nedenler `client_timeout` ise bütçe içinde 10 dk sonra bir kez aynı koşuyu sürdürme; kota/yük, model uyuşmazlığı, araç ihlali, başka/karışık hata, ikinci timeout, okunamayan sayaç veya dolan tavanla durma. Bekleme saate dahildir. Duraklamış veya terminal koşu iptal edilmez. Durması gereken koşu hâlâ çalışıyorsa yalnız ölçümü sonlandırmak için kendi API iptal yolu kullanılır.

Nihai snapshot için yürütücü dönüşü, sıfır `started` oturum ve 120 s kapanış penceresinde `snapshot_eligible` birlikte gerekir. Kapanış doğrulanmazsa nihai durum iddiası kurulmaz; ilgili sayımlar kayıt anındaki durum diye etiketlenir. Port 8765 dışlama, denetim, çıkış doğrulama ve geçersiz ölçüm yolu aynen sürer.

### F.6 Snapshot, okurlar ve sayımlar

D.5, E.6 ve istem §5'in sırası aynıdır; veri `d/data`, kanıt `evidence/d`, gözlemci dosyaları `report-polls-d.jsonl` / `report-poll-d.stop`, snapshot çıktısı `evidence/d/report` olur. R9 girdileri değişmeyen `r9/b-pairs.json` ve köken dosyasıdır. Ek E'deki R9 düzeltmeli kit aynı hash ile kullanılır; eski sonuçlar değişmez.

D202'nin B sonucu için kayıtlı yorum korunur: durdurulmadan `completed` olan rapor koşusunda, birleştirme raporu `draft` bıraksa bile K09 okurları ve bütün kit satırları çalışır; R1c gerçek kabul durumunu gösterir. Durmuş koşuda `snapshot --stopped` ve okursuz `score` yolu uygulanır: R1/R7/P19 korunur, R2–R6/R8/R9/R11 `ölçülemedi: run_incomplete`, R10 tasarım gereği ölçülmedi olur. Port 8765 nedeniyle geçersiz ölçüm yolu bu korumaya üstün gelir.

İlk okur `claude-opus-5-5`, `medium`, kör olmayan yürütücü analisttir. İkinci okur `claude-sonnet-5-5`, `medium`, yeni ve ayrı oturumdur. §4.3'ün izinli alanları, ilk okumadan önce `review.orig.md` saklanması, ikinci paket eşitliği, R3 ek birim biçimi, okunamadı yolu, deterministik aktarım ve aktarım sonrası eşitlik denetimi aynen uygulanır. Tohumlar `20261003` ve `20261004`; her ölçüt sayfasındaki destekleyen kontroller en çok beştir. İlk hükümler ve kontrol etiketleri ikinci okura verilmez. Okur notları ve okuma istisnaları `evidence/d` altında tutulur.

`--output-format json`, Ek E'deki gibi önceden donmuş ikinci okur komutunun parçasıdır. Depo dışındaki yeni ve boş `/tmp/p9r-h9d-reader2/` dizininde:

```sh
claude -p --model claude-sonnet-5-5 --effort medium --tools "" \
  --strict-mcp-config --setting-sources "" --no-session-persistence \
  --output-format json < packet.md > reading2-raw.json 2> reading2-err.txt
```

Ham JSON korunur; metin yanıtı kayıpsız olarak `reading2-raw.md` dosyasına çıkarılır, sonra §4.3'ün satır JSON aktarımı uygulanır. İstenen ve dönen model kimliği kaydedilir; kimlik yoksa veya uyuşmazsa başka model konmadan durulur. Yalnız istem §5'in model isteği yapılmadan gerçekleşen `--setting-sources ""` ayrıştırma hatası istisnası korunur; `--output-format json` çıkarılmaz.

`h9b_counts.py`, `p19_count.py`, `p19.sql` ve `c_checks.py` değişmez. H9d başlangıç–POST ve POST sonrası pencereleri ayrı sayılır. B hazırlığının 70 oturumu ayrı tarihsel kayıt olarak gösterilir. Yama basamakları, paket damgası, `envelope_mismatch`, çıkarılan iddialar ve P19 a–e aynı kuralla yazılır. RF4 doğrulama/context hataları ile RF5'in aday ret kodları ve olayları saklı kayıtlardan ayrıca raporlanır. RF5 ret olayı tek başına bölüm başarısızlığı veya tam onarım başarısı sayılmaz; gerçek bölüm ve birleştirme durumları ayrı yazılır. Kit dışında puan üretilmez.

### F.7 Sonuç kaydı ve donmuş dosyalar

Sonuç `docs/product/p9r-report-results.md` içinde ayrı tarihli **H9d** bölümüne, karar ve sonuç D202'ye ayrı Ek F paragrafı olarak yazılır. Ürün/dondurma hash'leri, gerçek koşu/rapor kimlikleri, kopya ve migration kapıları, bütçe, durma/kapanış, bölüm ve birleştirme durumları, R1–R11/P19, RF5 ret kayıtları, okur kimlikleri, istekler, süreler ve sapmalar kaydedilir.

B, H9c ve H9d aynı geliştirme korpusunda koşulardır. RF4 B'nin çıktılarından, RF5 H9c'nin başarısızlık kaydından geliştirilmiştir; H9d bağımsız doğrulama değildir. Her ikili karşılaştırma bir koşuya karşı bir koşudur. B ile sonraki koşular arasında başka ürün değişiklikleri ve R9 kit farkı bulunur; H9c ile H9d arasında doğrulanan dar RF5 değişikliği bulunması da model çıktılarındaki değişkenliği ortadan kaldırmaz. Tamamlanma, birleştirme kabulü veya metrik farkları RF5'in nedensel etkisi, hata oranı, genel kalite, hız/maliyet üstünlüğü ya da genelleme kanıtı olarak sunulmaz. B'nin R9'u ölçülemedi kalır.

Aşağıdaki SHA-256 değerleri yürütücü dosyaları, yöntem manifesti ve H9d kopya kayıtları oluşturulduktan sonra gerçek dosyalardan dolduruldu. `gate_g.sh` her dosyayı denetler; eski executor dosyaları Ek C/D/E bloklarıyla ayrıca denetlenir. Bütçe defteri ve `protocol.md` gibi koşu sırasında ekleme yapılan kayıtlar bloğa alınmaz.

```h9d-f-files
da0be34e8bc036620cbe6223ec5af2b69e3953624929713231cd1fe34dbe4967  .local/p9r-h9b/gate_g.sh
0d79c4cc74184a9e7bb506af7ff7d47c9065552635dcee2ccd930a0412f981d0  .local/p9r-h9b/launch_g.sh
dc4a8fb6d7a5af3ed6a1f12f540c849e69c6345934739d11c248dc97f995824c  .local/p9r-h9b/d_prepost.py
3c93395582dd65d6bcabc0ed3d58ccf15f47b8be34e95bf71b5d5e35932d55d7  .local/p9r-h9b/d_prepost_cases.py
c9d60768bbde2ef70ed3de52905b71f0cc79ec16e2efbfa05f3c418770181803  .local/p9r-h9b/poll_report_b.py
7c9bc47913cf5ff4e6b8dc51c6aef2a37ea11e961b98f82a051ddc52cc56d28d  .local/p9r-h9b/api.py
b44a93835b3b7bfd17bf4d5c10731304ab62a436e5729132ccf2bae80654a08e  .local/p9r-h9b/h9b_counts.py
58219952459a2e2bedc25722b5d7e5e158e04cbbe02d9d6a205e401f63136993  .local/p9r-h9b/p19_count.py
6d53789f7a1b898a4833bb993eaac222b29e5fa0cb209519fe020c3106e6acd1  .local/p9r-h9b/p19.sql
e3307b794ff24f4a93fb2abca701dac2e34a7992491036b68df05a08cec4210f  .local/p9r-h9b/logical_table.py
e1c375b4e8aecf61906472a0c60caa5932a3c0f2f5e201e2da0424a0cca97183  .local/p9r-h9b/manifest.py
45b0b72f9a26bd0df2e187ba0ca517ebff4905149efc357a0052d36a2536dab7  .local/p9r-h9b/c_checks.py
1f0011f7f4b286d42c31d5e488b6e994cc339c591cfd7daf41566344a96db4cf  .local/p9r-h9b/c_checks_cases.py
80662aa18fb6e24ae507799754bf36fdc463c466d7201e857aa4537600fbcff9  scripts/p6_eval/measure_report.py
de523a167813ebb7bc592ebc9477c49e35d685c8bd0d492826446f9489f1659b  tests/test_p6_measure_report.py
018dd36fd8aa3293aeab951aa725436c2187a953a442aed1356bf662192ca490  .local/p9r-h9b/r9/b-pairs.json
e9e4416ef1afeba965811df3d64c98a3fc1af1c53784c1e24dc495f6a362c1ff  .local/p9r-h9b/r9/b-pairs-provenance.json
58be99aad3a56e3dc8d6a9855c2b8819724b4ff2d515c87d89740ade4039a28f  .local/p9r-h9b/evidence/method-manifest-1f4903f.json
7f6b1a1f21b7401db8595e0eafd5a3ebe3f5d73111a23e55f2baa66c0b884467  .local/p9r-h9b/evidence/d/precopy-check.txt
05611f4d7d9bc203bedaa1db75e52155c2af654197227828b13c877fcbbc535f  .local/p9r-h9b/evidence/d/copy-time.txt
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/d/source-manifest.json
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/d/copy-manifest.json
01d68412c9fab8cddb93cc58883638eaedcf4b57edbed0a3076fbbdbdad1c2c5  .local/p9r-h9b/evidence/d/logical-table-before.json
ed99cf96cf4c056e44e3c8fe318f9383b7b514fa6f602a206f04065d8d50e561  .local/p9r-h9b/evidence/d/copy-prestart-check.json
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/d/manifest-after-reads.json
```

## Ek G — H9e: B raporunun RF6 üzerinde son yeniden koşusu (4 Ekim 2026, H9e rapor POST'undan önce)

**Dayanak.** Koordinatörün `/tmp/deixis-coordination.md` kaydındaki kararı: RF6 ([D211](../decisions.md), `7188ec8`) üzerinde, B'nin durmuş hazırlık verisinin yeni ve doğrulanmış kopyasında tam olarak bir H9e rapor koşusu yapılır. Sonuç ne olursa olsun H9 rapor zinciri burada biter; P10 öncesinde H9f yapılmaz. Başarısızlıkta rapor tamamlama ve D157'ye bağlı ölçüm borçları D205 kapsamında açık koordinatör kararıyla taşınır. Açık noktalar Claude Opus 5.5 + `gpt-6.1-sol` medium tarafından sahip adına kararlaştırılır. Bu amendment D202'ye tarihli **Ek G amendment** olarak eklenir; RF6'nın ürün kararı D211'dir.

**Öncelik:** Ek G, H9e için önceki eklerle çelişen ürün/yöntem pinleri, veri yolu, bütçe ve iptal yürütmesi hükümlerinin yerine geçer. Önceki metinler ve sonuçlar tarihsel kayıt olarak korunur. §5'in sonraki ölçüm için yeni korpus hükmüne yalnız bu koşu için açık istisna verilir: H9e aynı hazırlanmış B korpusunu kullanır. Yeni keşif, kuyruk geçişi, seçim değişikliği, doldurma veya hücre düzeltmesi yapılmaz.

### G.1 Önceki sonuçlar ve yeniden koşunun kapsamı

B'nin rapor koşusu `run_UriYrNZpRYuwcMd3d4kI`, `b90583b` üzerinde `b2/data` ile tamamlandı; 20 uygulama oturumu kullandı. On model bölümü geçerliydi, fakat birleştirme kontrolü raporu reddetti ve rapor `draft` kaldı. R1c `0/1`; R9 kit kusuru nedeniyle ölçülemedi. B'de iki okur isteği ve toplam 6 dk 11 s kullanıldı.

H9c, `2b185a8` üzerinde `c/data` ile koştu. Koşu 309,1 s ve 24 çağrıdan sonra `section_failed` ile durakladı; dokuz model bölümü geçerli, özet başarısızdı. Geçerli ilk taslağın ifade onarımı “Bu çalışma” kalıbını getirdi; RF4'ün tam doğrulaması bunu reddetti. Birleştirmeye gelinmedi. Sürdürme ve duraklamış koşuya iptal yapılmadı; okur çalışmadı.

H9d, `1f4903f` üzerinde `d/data` ile koştu: `run_DeedBWVc3F85JARn17rT`, rapor `rpt_ENDUxE7H3AhZujTmZCJA`. V'nin ilk çıktısındaki `anchor_not_in_cell_evidence` hatası tam onarımı başlattı. Onarım çıktısı onarım girdisinin kimliği yerine ilk denemenin `step_input_id` değerini taşıdı; `envelope_mismatch` nedeniyle V başarısız oldu. III ve IV geçerliydi; birleştirmeye gelinmedi. Koşu oluşturulmasından 169,3 s sonra durakladı, 9 çağrı kullandı. Yürütücü eski `running` okumasına dayanarak duraklamış koşuyu iptal etti; bu §5'e aykırı sapma nihai durumu `cancelled` yaptı. Yeni model oturumu başlamadı, fakat kitin 184,4 s'lik R7 değeri duraklamadan sonraki 15,1 s'yi de içerdi. H9d okur kullanmadı.

RF6, yeni adapter çıktılarında kodun bildiği `step_input_id` değerini damgalar; modelin farklı veya eksik yankısını normalizasyon kaydında, ham çıktıyı ise değiştirmeden saklar. Kabul ayrıca aktif model denemesi, oturum ve girdi kimliğine bağlanır; kapanmış veya yerini başka denemeye bırakmış çıktılar `model_attempt_inactive` olarak kaydedilip kullanılmaz. Saklı taslaklar yeniden damgalanmaz; `scope_revision` ve damgalama sonrası zarf denetimleri korunur. Bu bağlama, canlı adapter çağrısına yanlışlıkla başka bir isteğin metni dönerse onu ayırt etme garantisi vermez. D211'in H9d onarım fikstürü saklanmamış onarım çıktısını sentetik olarak kurar; gerçek onarım çıktısının yeniden oynatılması diye sunulmaz.

H9e yeni ve son bir rapor koşusudur. `b2/data`, `c/data` ve `d/data` önceki raporları içerdiğinden kaynak veya yürütme dizini olarak kullanılmaz. Eski koşular sürdürülmez ve yeniden puanlanmaz.

### G.2 Ürün ve donmuş değerler

| Kayıt | Değer |
|---|---|
| Ürün | `7188ec83c8922475719a30d4b466a386f74feec7`; ayrık worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run`, kendi arm64 `.venv`'i `uv sync --frozen` ile eşitlendi. Main ilerlese de yeniden sabitlenmez. |
| Runtime `skill_package_hash` | `sha256:ccff02a169ea72690a594b3277c09c0975537f45ed20f9a6203a364d0c2b132c`; yürütücü hesapladı, `integrity_issues()` boş. |
| Şema manifesti | 23 dosya, `df3acb7a3ec1199f0622f276212a1a72a1242db0bb1ff22ad569b058d5ec66a5`; ortak-yazar salt okunur yeniden hesapladı. Ek E/F ile aynı. Ada göre sıralı `contracts/research/*.schema.json` dosyaları için `<dosya adı> <sha256>` satırlarının, son satır sonu dahil, SHA-256'sıdır. |
| Modele giden şemalar | 41 anahtar; `sha256(json.dumps(sorted(transport)).encode())` değeri `1a76b85cc1be334dae09da00a8129dc3577e948ace098466205b57c620d182a0`; bütün `strict_compatibility_issues` sonuçları boş. Ortak-yazar yeniden hesapladı. |
| Yama taşıma şeması | `f30984c2f2680b294b47822ba3c01f0f8c16bf89d69f6e0c0f9b3134911a9739`; argümansız şemanın `json.dumps(..., sort_keys=True, separators=(',', ':'), ensure_ascii=False)` serileştirmesinin SHA-256'sı. Ortak-yazar yeniden hesapladı; değişmedi. |
| Kit `scripts/p6_eval/measure_report.py` | `80662aa18fb6e24ae507799754bf36fdc463c466d7201e857aa4537600fbcff9`; ortak-yazar yeniden hesapladı; değişmedi. |
| Kit testi `tests/test_p6_measure_report.py` | `de523a167813ebb7bc592ebc9477c49e35d685c8bd0d492826446f9489f1659b`; ortak-yazar yeniden hesapladı; değişmedi. |
| Yöntem manifesti | Yürütücü `evidence/method-manifest-7188ec8.json` dosyasını yazdı: 17 dosya; `aggregate_sha256` `c446cf8d82a8b4c27a7a9f4d87151ba70b5aeaa612e98d58a209fe1d54a2b34a`; dosyanın SHA-256'sı `81b2c5cfc0ada8a928e4871840cd36a4cfdfdcaea600d31683b2c94dcd6ecf65`. Ek F'nin sırası, biçimi ve `sha256(json.dumps(files, sort_keys=True))` kuralı korunur. |

Yöntem manifestinde değişen tek dosya `SKILL.md` olup yeni SHA-256'sı `9c13db1fe5fc9cba6f5eb60156a7f0b187c5181abee427d82a17302a36b4bb23` değeridir. Runtime/şema/kit pinleri arasında RF6 yalnız yöntem paket hash'ini değiştirir; yöntem manifestinin toplamı da değişir.

Yürütücünün `1f4903f..7188ec8` backend/yöntem/kontrat/kit denetiminde değişen dosyalar:

```text
backend/deixis/domain/contracts.py
backend/deixis/workflow/flow.py
backend/deixis/workflow/report/store.py
backend/deixis/workflow/store.py
methods/deixis-research/SKILL.md
```

Migration değişmedi; ortak-yazar da migration dosya farkının boş olduğunu doğruladı. D211'in taşıma şemalarının değişmediği hükmü yeniden hesaplanan pinlerle doğrulandı. D211'deki kısaltılmış `a6d4a9e1...` manifest ifadesi Ek E'nin burada kullanılan dosya-manifest kuralının sonucu değildir; G için yukarıdaki açık hesap kuralı ve tam değerler geçerlidir.

### G.3 Yeni veri kopyası ve hazırlık kayıtlarının korunması

Yeni yürütme dizini `.local/p9r-h9b/e/data`, kaynak yalnız `.local/p9r-h9b/b/data` olur. Araştırma `res_khW4MevleljQIeXvHsyl`, tablo `tbl_ACVZv04QYr9024IW57mF`; D.2'nin on dahil kaynak kimliği, 11 saklı tablo satırı, yedi sütunu, altı mantıksal hash'i ve D.3'ün yedi R9 çifti korunur. On dahil satır dokuz ayrı eserdir; aynı PDF'yi taşıyan iki satır ve başarısız doldurma nedeniyle dışlanan satırın seçim etkisi değişmez.

**H9e kopya kaydı tamamlandı.** Yürütücünün precopy denetimi 3 Ekim 2026 21:36:38Z'de yapıldı (`evidence/e/precopy-check.txt`): `serve` süreci, `pgrep` eşleşmesi ve gözlemci yok; `lsof +D b/data` boş; 8873 ve 8765 boş; `e/data` henüz yoktu; sembolik bağ sayısı 0. SQLite yan dosyaları dahil `cp -Rp` 21:36:39Z'de yapıldı (`copy-time.txt`).

Kaynak ve kopya manifestleri dosya dosya eşit: 57 dosya, toplam `be258e864da65f3c12d78219681dcad4938dedfae931d5b3f6a20f64c36e3236`, en büyük `nlink` 1. Tarihsel 55 dosya değişmedi; fazlası yalnız sıfır baytlık `library.sqlite-wal` ve 32.768 baytlık `library.sqlite-shm` dosyasıdır. Yan dosyaların oluşma geçmişi bu eşitlikten çıkarılmaz.

Yürütücü yalnız yeni `e/data` kopyasında mantıksal denetimleri yaptı. Altı mantıksal hash `evidence/b/logical-table-after-exclusion.json` ile aynı; en büyük migration 69, aktif koşu 0, `started` oturum 0, araştırmanın raporu 0, izleme 0. Dahil küme donmuş on kaynağa eşit (`logical-table-before.json`, `copy-prestart-check.json`). Okumalardan sonra dosya manifesti değişmedi (`manifest-after-reads.json`).

Bu tamamlanmış denetimler yeniden yapılması istenen işler değildir. Ortak-yazar hiçbir SQLite dosyasını açmadı; kopya ve mantıksal denetim sonuçları yürütücünün kayıtlarıdır.

`b/data`, `b2/data`, `c/data` ve `d/data` üzerinde sunucu, SQLite okuyucusu, migration, onarım veya test çalıştırılmaz; dosyalar silinmez, değiştirilmez veya yeniden adlandırılmaz. CodexNotify dahil launcher'ın süreç filtresine uyan eşleşmeler açıklamasız yok sayılmaz; filtre gevşetilmez.

0070 yalnız `e/data` üzerinde ilk sunucu başlangıcında uygulanır. Başlangıçtan hemen sonra `e_prepost.py check`, migration 70, kurtarılan koşu/adım/oturum sıfır, izleme sıfır ve aynı altı mantıksal hash'i doğrular. Aynı canlı denetimler POST yardımcısının iki geçişinde yeniden yapılır.

### G.4 Executor kapıları ve yürütme

D.5 ve E.4/F.4 kontrolleri korunur. Yeni dosyalar `gate_h.sh`, `launch_h.sh`, `e_prepost.py`, `e_prepost_cases.py` ve `cancel_e.py` olur. Port **8873**, değişken adları `H9B_FREEZE_COMMIT` ve `H9B_ARM` kalır; kol `e`, aşamalar `e-start` ve `e-post` olur. Başka ölçüm sunucusu varken başlanmaz.

`gate_h.sh`, push edilmiş Ek G'yi, D202'deki Ek G amendment kaydını, D211'i, ürün/dondurma atalığını ve `h9e-g-files` bloğunu zorunlu tutar. **Ek C/D/E/F blokları ve bütün dosya hash denetimleri korunur.** A2 veto/sınıflandırma koruması, A2 veritabanı/WAL içerik-zaman denetimleri ve yalnız `-shm` istisnası değişmez. RF4/RF5 marker'ları korunur. RF6 için `contracts.py` içinde `def stamp_step_input_id(`, `flow.py` içinde `contracts.stamp_step_input_id(task_type, payload, output_text)`, `self.store.model_attempt_active(` ve `"model_attempt_inactive"`, `workflow/store.py` içinde `def model_attempt_active(` aranır. Bunlar `7188ec8` üzerinde doğrulandı; marker denetimi davranış testi değildir. Eski executor dosyaları değiştirilmez.

`e_prepost.py` tek rapor POST yoludur. Kesin süreç komutu, tam veri-dizini ortam öğesi, tek 8873 dinleyicisi, worker kira PID'i, sağlık/paket, migration, mantıksal hash, dahil küme, sıfır aktif iş/izleme/rapor, hazır tablo, Luna bağlantısı ve boş 8765 denetimleri korunur. Gövde değişmez:

```json
{"table_id": "tbl_ACVZv04QYr9024IW57mF", "continue_with_failed": false}
```

Belirsiz yanıt yeniden gönderilmez; kayıt ve çıkış 3 korunur. `e_prepost_cases.py`, sunucu başlamadan ve 0070 uygulanmadan önce yalnız `e/data` dosyalarının geçici kopyasında çalıştırılır; 34 durum ve beklenen çıkışlar korunur.

Ek F'nin modelsiz ön koşul test listesine `tests/test_model_output_identity.py` eklenir. Ortak-yazarın SQLite açmayan denetiminde dört dönüşümün eşleşme sayıları doğrulandı; gate Python gövdesi, dönüştürülmüş iki Python yardımcısı ve `cancel_e.py` AST ayrıştırmasından geçti. Bu, shell denetimlerinin, 34 durumun veya pytest'in çalıştırıldığı anlamına gelmez.

**Kuru denetim kaydı:** modelsiz, `7188ec8` üzerinde (HEAD `7188ec83c8922475719a30d4b466a386f74feec7`), sunucu başlamadan, 21:55:14Z–21:57:02Z. Kesin komutlar, HEAD, başlangıç/bitiş zamanları, çıkış kodları (hepsi 0), ortam (`PYTHONDONTWRITEBYTECODE=1`; pytest için `PYTHONPATH=backend:.`) ve kayıt yolları `evidence/e/preflight-record.txt` dosyasındadır: `zsh -n` ile `gate_h.sh` ve `launch_h.sh`, AST ile `cancel_e.py`, `e_prepost.py` ve `e_prepost_cases.py` (`syntax-checks.txt`); `c_checks_cases.py` 10 durum (`c-checks-cases.txt`); `e_prepost_cases.py` 34 durum (`prepost-cases.txt`); F listesi ve `tests/test_model_output_identity.py` ile 1.779 test geçti, 6 uyarı (`preflight-tests-h.txt`). Aynı denetimlerin kayıtsız ilk çalıştırması aynı sonuçları verdi ve yerini bu kayıtlı çalıştırmaya bıraktı. `cancel_e.py` canlı sunucuya karşı çalıştırılmadı.

Bu kayıt gerçek komutları, `7188ec8` ürün pinini, geçme/kalma sayılarını, uyarıları ve `evidence/e/prepost-cases.txt` / `evidence/e/preflight-tests-h.txt` yollarını içerir. Başarısız denetim varken başlanmaz. Ek G mevcut K12 usulüyle Sol high incelemesinden geçip koordinatörce push edilmeden sunucu veya rapor başlatılmaz. Yeni pin başarısızsa eski ürüne otomatik dönüş yoktur.

```sh
cd /Users/huguryildiz/Documents/GitHub/DEIXIS-h9b-run
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .local/p9r-h9b/c_checks_cases.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python .local/p9r-h9b/e_prepost_cases.py
H9B_STAGE=e-start H9B_FREEZE_COMMIT=<Ek G hash> zsh .local/p9r-h9b/gate_h.sh
H9B_ARM=e H9B_FREEZE_COMMIT=<Ek G hash> nohup zsh .local/p9r-h9b/launch_h.sh > .local/p9r-h9b/evidence/server-e.log 2>&1 &
.venv/bin/python .local/p9r-h9b/e_prepost.py check <Ek G hash> <PID>
.venv/bin/python .local/p9r-h9b/e_prepost.py post <Ek G hash> <PID>
.venv/bin/python .local/p9r-h9b/poll_report_b.py e <PID> res_khW4MevleljQIeXvHsyl <rapor koşusu> <POST zamanı>
```

### G.5 Bütçe ve durdurma

Başlangıç defteri: A 7 + A2 10 + B hazırlık 70 + B rapor 20 + H9c 24 + H9d 9 = **140 / 293**, kalan **153 uygulama oturumu**. H9e'ye yalnız **bir rapor koşusu, 60 uygulama oturumu / POST'tan 90 dk** tahsis edilir. Kopyalanan hazırlık oturumları tarihsel kayıttır; yeniden tüketim sayılmaz. Her yeni oturum, onarım ve izinli yeniden gönderim dahil sayılır. Başlangıç–POST penceresinde beklenen yeni oturum sıfırdır; sapma ortak deftere yazılır.

Kalan 153 oturum yeni hazırlık, ikinci rapor veya model değişikliği yetkisi vermez; 60 oturumluk tavan büyütülmez. Poll aralığında aşım ayrıca kaydedilir; izleme sert üst sınır garantisi değildir.

K09/K10 okurları H9e için en çok **4 istek / toplam 60 dk** kullanabilir. Ortak H9b tavanı **8 istek / 120 dk** sıfırlanmaz: kullanılan **2 istek / 6 dk 11 s**, kalan **6 istek / 113 dk 49 s**. H9c/H9d okur kullanmadı. İlk yürütücü okuması da bir istektir; ilk/ikinci okuma ve tamamlama isteklerinin başlangıç/bitiş zamanları ortak deftere yazılır. Kullanılabilir bütçe H9e tavanıyla ortak bakiye arasındaki küçük değerdir.

§5 ve önceki eklerin durdurma kuralları korunur: 15 s gözlem; saklı terminal kök nedenler; yalnız bütün kök nedenler `client_timeout` ise bütçe içinde 10 dk sonra bir kez aynı koşuyu sürdürme. Kota/yük, model uyuşmazlığı, araç ihlali, başka/karışık hata, ikinci timeout, okunamayan sayaç veya dolan tavan durdurur. Bekleme saate dahildir.

**H9d'den çıkarılan zorunlu yürütücü kuralı:** her iptalden önce koşu durumu aynı işlem adımında yeniden okunur. Duraklamış veya terminal koşu iptal edilmez. `pause_requested` de iptal edilmez; mevcut duraklama isteğinin tamamlanması gözlenir. İptalin tek yolu:

```sh
.venv/bin/python .local/p9r-h9b/cancel_e.py <Ek G hash> <PID> <rapor koşusu>
```

Yardımcı iki canlı okumada da yalnız `queued` veya `running` kabul eder; ikinci okumadan hemen sonra en çok bir POST gönderir. Okuma, süreç veya dinleyici belirsizse çıkış 2 ile POST'suz reddeder. Gönderim sonrası ret, hata veya belirsizlik yeniden deneme yetkisi vermez.

**Sınır:** `7188ec8` API'si GET ve cancel POST'u atomik bir durum koşuluyla bağlamaz; cancel endpoint'i `paused` durumunu da kabul eder. Yardımcı son okumada duraklamış koşuya gönderimi engeller, fakat son GET ile POST arasında gerçekleşebilecek duraklamayı atomik olarak engelleyemez. Böyle bir yarış sapma olarak kaydedilir; yardımcının mutlak “duraklamış koşuyu hiçbir koşulda iptal edemez” garantisi olduğu ileri sürülmez.

Nihai snapshot için yürütücü dönüşü, sıfır `started` oturum ve 120 s kapanış penceresinde `snapshot_eligible` birlikte gerekir. Kapanış doğrulanmazsa nihai durum iddiası kurulmaz; sayımlar kayıt anındaki durum diye etiketlenir. Port 8765 dışlama ve geçersiz ölçüm yolu korunur.

**Zincir sonu:** tam olarak bir H9e rapor koşusu yapılır. İzinli timeout sürdürmesi aynı koşudur. Sonuç ne olursa olsun ardından H9 rapor zinciri durur; P10 öncesinde H9f yoktur. Başarısızlıkta rapor tamamlama ve D157'ye bağlı ölçüm borçları D205 kapsamında açık koordinatör kararıyla taşınır. Bu amendment borçları kapanmış veya ölçülmüş saymaz.

### G.6 Snapshot, okurlar ve sayımlar

D.5, E.6/F.6 ve istem §5'in sırası korunur; veri `e/data`, kanıt `evidence/e`, gözlemci dosyaları `report-polls-e.jsonl` / `report-poll-e.stop`, snapshot çıktısı `evidence/e/report` olur. R9 girdileri değişmeyen `r9/b-pairs.json` ve köken dosyasıdır. Ek E'nin R9 düzeltmeli kiti aynı hash ile kullanılır; eski sonuçlar değişmez.

Durdurulmadan `completed` olan koşuda, birleştirme raporu `draft` bıraksa bile K09 okurları ve bütün kit satırları çalışır; R1c gerçek kabul durumunu gösterir. Durmuş koşuda `snapshot --stopped` ve okursuz `score` yolu uygulanır: R1/R7/P19 korunur, R2–R6/R8/R9/R11 `ölçülemedi: run_incomplete`, R10 tasarım gereği ölçülmedi olur. Port 8765 nedeniyle geçersiz ölçüm yolu bu korumaya üstün gelir.

İlk okur `claude-opus-5-5`, `medium`, kör olmayan yürütücü analisttir. İkinci okur `claude-sonnet-5-5`, `medium`, yeni ve ayrı oturumdur. §4.3'ün izinli alanları, ilk okumadan önce `review.orig.md`, ikinci paket eşitliği, R3 ek birim biçimi, okunamadı yolu, deterministik aktarım ve aktarım sonrası eşitlik denetimi aynen uygulanır. Tohumlar `20261003` ve `20261004`; destekleyen kontroller her ölçüt sayfasında en çok beştir. İlk hükümler ve kontrol etiketleri ikinci okura verilmez. Notlar ve okuma istisnaları `evidence/e` altında tutulur.

Depo dışındaki yeni ve boş `/tmp/p9r-h9e-reader2/` dizininde donmuş komut:

```sh
claude -p --model claude-sonnet-5-5 --effort medium --tools "" \
  --strict-mcp-config --setting-sources "" --no-session-persistence \
  --output-format json < packet.md > reading2-raw.json 2> reading2-err.txt
```

Ham JSON korunur; metin yanıtı kayıpsız `reading2-raw.md` dosyasına çıkarılır, sonra §4.3 aktarımı uygulanır. İstenen/dönen model kimliği kaydedilir; kimlik yoksa veya uyuşmazsa başka model konmadan durulur. Yalnız model isteği yapılmadan gerçekleşen `--setting-sources ""` ayrıştırma hatası istisnası korunur; `--output-format json` çıkarılmaz.

`h9b_counts.py`, `p19_count.py`, `p19.sql` ve `c_checks.py` değişmez. Başlangıç–POST ve POST sonrası pencereler ayrı sayılır. Yama basamakları, paket damgası, `envelope_mismatch`, çıkarılan iddialar ve P19 aynı kuralla yazılır. RF5 aday retleri ile RF6'nın `step_input_id` normalizasyon ve `model_attempt_inactive` kayıtları ayrıca raporlanır. Damgalama kaydı anlamsal doğruluk veya başarılı onarım sayılmaz; bölüm ve birleştirme durumları ayrı yazılır. Kit dışında puan üretilmez.

### G.7 Sonuç kaydı ve yorum sınırı

Sonuç `docs/product/p9r-report-results.md` içinde ayrı tarihli **H9e** bölümüne; amendment ve sonuç D202'ye ayrı paragraflar olarak yazılır. Ürün/dondurma hash'leri, gerçek koşu/rapor kimlikleri, kopya ve migration kapıları, bütçe, durma/kapanış, bölüm/birleştirme durumları, R1–R11/P19, RF6 normalizasyon/discard kayıtları, iptalin iki okuması ve yanıtı, okur kimlikleri, süreler ve sapmalar kaydedilir. H9 zincirinin kapandığı açıkça yazılır; başarısızlıkta D205 kapsamındaki borç taşıma kararı ayrıca kaydedilir.

B, H9c, H9d ve H9e aynı geliştirme korpusunda koşulardır. RF4 B'nin çıktılarından, RF5 H9c'nin, RF6 H9d'nin başarısızlık kaydından geliştirilmiştir. H9e bağımsız doğrulama değildir. Her ikili karşılaştırma bir koşuya karşı bir koşudur; ürün değişiklikleri, model çıktılarının değişkenliği ve B'nin R9 kit farkı nedensel yorumları sınırlar. Tamamlanma, birleştirme kabulü veya metrik farkları RF6'nın nedensel etkisi, hata oranı, genel kalite, hız/maliyet üstünlüğü ya da genelleme kanıtı olarak sunulmaz. B'nin R9'u ölçülemedi kalır.

### G.8 Donmuş dosyalar

Aşağıdaki yer tutucular gerçek dosya SHA-256 değerleriyle doldurulur. `gate_h.sh` her dosyayı denetler; eski executor dosyaları Ek C/D/E/F bloklarıyla ayrıca denetlenir. Bütçe defteri, `protocol.md`, poll ve cancel çıktıları gibi koşu sırasında yazılan kayıtlar bu bloğa alınmaz.

```h9e-g-files
d6e867f3d3e2d06198e3ffae7435e99150f4910edb4ebef6bcca932463941b69  .local/p9r-h9b/gate_h.sh
c898c962051d5f064a0254198e68d4f45673046186b3cf5c0e429d7a48de0b97  .local/p9r-h9b/launch_h.sh
24d058ec06a423b64396360b261b3570abdd2a5a866d1de4cfef93300bae30bf  .local/p9r-h9b/e_prepost.py
66ddea44e5f2604287c58496d7916ee88aa71bf1207ffabd73768d5ee8c5f4a7  .local/p9r-h9b/e_prepost_cases.py
f3e3d4a6edf380c043a359b93c8e58fa196dc788401a56698bc55f3daf67db6e  .local/p9r-h9b/cancel_e.py
c9d60768bbde2ef70ed3de52905b71f0cc79ec16e2efbfa05f3c418770181803  .local/p9r-h9b/poll_report_b.py
7c9bc47913cf5ff4e6b8dc51c6aef2a37ea11e961b98f82a051ddc52cc56d28d  .local/p9r-h9b/api.py
b44a93835b3b7bfd17bf4d5c10731304ab62a436e5729132ccf2bae80654a08e  .local/p9r-h9b/h9b_counts.py
58219952459a2e2bedc25722b5d7e5e158e04cbbe02d9d6a205e401f63136993  .local/p9r-h9b/p19_count.py
6d53789f7a1b898a4833bb993eaac222b29e5fa0cb209519fe020c3106e6acd1  .local/p9r-h9b/p19.sql
e3307b794ff24f4a93fb2abca701dac2e34a7992491036b68df05a08cec4210f  .local/p9r-h9b/logical_table.py
e1c375b4e8aecf61906472a0c60caa5932a3c0f2f5e201e2da0424a0cca97183  .local/p9r-h9b/manifest.py
45b0b72f9a26bd0df2e187ba0ca517ebff4905149efc357a0052d36a2536dab7  .local/p9r-h9b/c_checks.py
1f0011f7f4b286d42c31d5e488b6e994cc339c591cfd7daf41566344a96db4cf  .local/p9r-h9b/c_checks_cases.py
80662aa18fb6e24ae507799754bf36fdc463c466d7201e857aa4537600fbcff9  scripts/p6_eval/measure_report.py
de523a167813ebb7bc592ebc9477c49e35d685c8bd0d492826446f9489f1659b  tests/test_p6_measure_report.py
018dd36fd8aa3293aeab951aa725436c2187a953a442aed1356bf662192ca490  .local/p9r-h9b/r9/b-pairs.json
e9e4416ef1afeba965811df3d64c98a3fc1af1c53784c1e24dc495f6a362c1ff  .local/p9r-h9b/r9/b-pairs-provenance.json
81b2c5cfc0ada8a928e4871840cd36a4cfdfdcaea600d31683b2c94dcd6ecf65  .local/p9r-h9b/evidence/method-manifest-7188ec8.json
f22fe4102778211776909ca1319c0f9c2adacb07672b257fddd9ecb5b9331f97  .local/p9r-h9b/evidence/e/precopy-check.txt
4ce9a3858bd8f4cacf290e576be82e52aa8f4bb4dbc469772b1e9591e9c9114d  .local/p9r-h9b/evidence/e/copy-time.txt
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/e/source-manifest.json
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/e/copy-manifest.json
01d68412c9fab8cddb93cc58883638eaedcf4b57edbed0a3076fbbdbdad1c2c5  .local/p9r-h9b/evidence/e/logical-table-before.json
0487e36f3d4fb40cbc0577f705a4247df7edd4827802df79a17434b5b05ecf83  .local/p9r-h9b/evidence/e/copy-prestart-check.json
d2e731b1c71fc1205fc903c3e66e7d0be61e9bc5c9f878b18cde0e1bf5fbe5cf  .local/p9r-h9b/evidence/e/manifest-after-reads.json
94a5a816bee16098f7017f2210a1be3a61aa8b797d9630c8c3c9cf89fbb2f3eb  .local/p9r-h9b/evidence/e/preflight-record.txt
1534ac3d7cbc403d3bd222d4a58aeba07188e06ed75e3908e178c64610539ad0  .local/p9r-h9b/evidence/e/syntax-checks.txt
4cd224595c844ad76cf313b7d94d55a26ab1711a5533b0a6323b9591ce6d3e12  .local/p9r-h9b/evidence/e/c-checks-cases.txt
d0abbaf9002ffa47c85f1b9fae8037382530475230f34b5e165bcb62c0fdc787  .local/p9r-h9b/evidence/e/prepost-cases.txt
441ec0e25b522a1a118fc6f946cc249ff01e5a504f8bb3cd162bba1ad52eaed9  .local/p9r-h9b/evidence/e/preflight-tests-h.txt
```
