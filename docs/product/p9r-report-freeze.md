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
