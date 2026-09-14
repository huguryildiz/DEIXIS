# Araştırma yöntemi: literatür karşılaştırması ve ürün tasarımı

**Tarih:** 14 Eylül 2026. **Kapsam:** araştırma sorusundan literatür keşfi,
sentez, aday geliştirme ve iddia denetimine kadar odaklı yöntem incelemesi.
Bu belge, yöntemlerin ürün içindeki karşılığını ve henüz yapılmamış işleri kaydeder.
Tam bir sistematik derleme, atıf sıralaması veya Quaestio etkinlik deneyi değildir.

## 1. Karar ve öneri ayrımı

**Kullanıcının seçtiği çekirdek:** Alan haritasını araştırmanın gelişim çizgileriyle
oluşturmak; adayları **amaç–mekanizma–değerlendirme** üzerinden somutlaştırmak;
ardından **her adayın belirli iddiasına kill-search** uygulamak.
Chain of Ideas (CoI) sentez temeli, Scideator aday ifade biçimi için referanstır.
Bu birleşimin kendisi Quaestio uyarlamasıdır; literatürde doğrulanmış tek bir
uçtan uca protokol olarak sunulamaz.

**Bu incelemenin önerisi:** yeni kullanıcı skill'leri eklemek yerine mevcut
akışta üç soru üretme yolunu belirginleştirmek: sonuçları etkileyen varsayımı
sorgulamak, karşılaştırılabilir bulgular arasındaki uyuşmazlığı açıklamak ve
ayrı literatürler arasında gerekçeli bir ilişki kurmak. Her aday için güçlü
mevcut açıklama ve ayırt edici sonraki kontrol görünür olmalı. Bunların çoğunun
metodolojik temeli mevcut skill'de bulunuyor; eksik olan ürün sözleşmesi ve
uygulama davranışına bağlanmaları.

**Mimari önerisi:** tek Quaestio girişi, dört iç sorumluluk: keşif/kapsam,
sentez, aday geliştirme, kill-search. Bu dört ayrı ajan, dört kurulum veya kesinleşmiş
dosya düzeni değildir. Kullanıcı soru ve araştırma yönüyle çalışır; yöntem seçimini
normal kullanımda yönetmek zorunda kalmaz. Çalışan modüller ve gerekçeleri ayrıntıda
görülebilir. Yöntemler her oturumda zorunlu sırayla çalıştırılmaz.

**Son kullanıcı kısıtı:** çok ajanlı bir yapı istenmiyor. Buna göre ilk sürümün
varsayılanı **tek ana ajan** olmalı; bu ajan gerekli yöntem dosyalarını ve araçları
aşamaya göre kullanır. Dört iç sorumluluk dört ajan anlamına gelmez. Sürekli
“fikir üretici–hakem” konuşması veya ajan turnuvası kurulmaz. Kullanıcı ayrıca
istediğinde tek bir ek eleştirel inceleme yapılabilir; akışın tamamlanması buna
bağlı olmamalı. Aynı ajanın öz eleştirisi bağımsız doğrulama sayılmaz. İkinci bir
ajanın görüşü de kaynak doğrulamasının yerine geçmez.

Bu kısıtı uygulamak için önerilen düzenlemeler:

- **Kısa fizibilite kontrolü aday geliştirmenin içindedir:** soru ve iddia açık mı,
  gerekli veri/araçlar erişilebilir mi, hangi kanıtla sınanabilir? Matematiksel
  formülasyon yalnız ilgili katkı türlerinde aranır. Ayrıntılı model kurmadan önce
  yakın öncüller kontrol edilir; kill-search sonrasında fizibilite yeniden ele alınabilir.
- **Önce kısa alan haritası, sonra hedeflenen yönde derin sentez:** bütün literatürü
  tek anlatıda eritmek de başlangıçta alternatifleri dışlamak da amaç değildir.
- **İnsan karar noktaları:** araştırma yönü, önemli kapsam değişikliği ve
  deney/maliyet kararları. Rutin kaynak okuma ve her ara çıktı için tekrar onay yok.
- **Döngü sınırlıdır:** yeni kanıtla iddia revize edilir; elenen her fikir
  kurtarılmaya çalışılmaz. Kapatma ve erteleme geçerli sonuçlardır.
- **Yapısal PDF okuma:** kritik denklem, tablo ve algoritmalar orijinal sayfaya
  bağlanır. Ayrıştırıcının çıkardığı yapı, matematiksel anlama veya doğruluk kanıtı
  değildir; belirleyici tanımlar ve varsayımlar asıl kaynakla karşılaştırılır.

Arama, ayrıştırma, kayıt ve deterministik kontroller araç/uygulama işlevleridir;
ayrı araştırmacı ajanlar olarak modellenmeleri gerekmez.

### İsteğe bağlı başka modelle inceleme

Kullanıcının son önerisi, ana akışı tek ajanla korurken talep üzerine başka bir
modelden değerlendirme raporu almaktır. **Önerilen arayüz eylemi:** “Başka modelle
incele”. Bu bir sürekli ajan ekibi değil, seçilmiş çalışma için ayrı ve sınırlı
bir inceleme oturumudur; model seçimi ile incelemeci rolü ayrı kavramlardır.

1. Kullanıcı bir aday, kill-search sonucu veya raporu seçer; mevcut ve kullanılabilir
   bağlantılardan inceleme modelini belirler. Aynı model de seçilebilir; farklı model
   kullanmak otomatik bağımsızlık veya daha yüksek doğruluk sağlamaz.
2. İnceleme amacı seçilir veya yazılır: örneğin kaynak desteği, varsayım/fizibilite
   veya prior-art karşılaştırması. Gönderilecek içerik, dış sağlayıcı ve varsa
   maliyet tahmini/bütçe görünür olur. Kullanıcının başlatma eylemi bu incelemeyi
   yetkilendirir; rutin alt adımlar için yeniden onay istenmez.
3. İncelemeci, seçimin sürümlü bir anlık kopyasını, ilgili kaynak pasajlarını,
   kapsamı ve bilinen erişim sınırlarını alır. Varsayılan inceleme eldeki kanıtla
   sınırlıdır; yeni dış arama ayrıca seçilebilir ve bütçelendirilir. Ana çalışmaya
   yazma yetkisi verilmez; ana ajanla otomatik karşılıklı tartışma başlatılmaz.
4. Ayrı raporda her bulgunun ilgili iddiası, dayanağı, gerekçesi, olası etkisi,
   önerilen düzeltmesi ve belirsizliği gösterilir. Kaynak/bağlam yetersizse bu
   belirtilir; incelemeciden zorla kusur bulması veya ikili yenilik kararı vermesi
   beklenmez. Desteklenen ve itiraz edilmeyen noktalar da raporlanabilir.
5. Kullanıcı bulguları ana çalışmaya geri besleyebilir, revizyon isteyebilir veya
   gerekçesiyle uygulamayabilir. Aktarılan öneriler yeni sürümde izlenir; rapor
   mevcut adayları sessizce değiştirmez. Kaynak iddia değişmişse incelemenin eski
   sürüme ait olduğu gösterilir. Yeni inceleme ayrı kullanıcı talebi gerektirir.

İnceleme kaydında kapsam, girdi sürümleri, zaman, seçilen/gerçekleşen model,
erişilen kanıt, kullanılan araçlar ve mevcutsa kullanım/maliyet saklanır. Rapor
bir **ek model değerlendirmesi** olarak etiketlenir; hakem onayı veya bağımsız
bilimsel doğrulama olarak sunulmaz. [Etkileşimli UI prototipi](../../prototypes/shadcn-ui/README.md#optional-model-review-prototype)
model/odak seçimi, örnek rapor ve bulgu geri aktarımını gösteriyor. Model adları
yer tutucu, rapor sabit örnek içeriktir; gerçek model/arama çağrısı yapılmaz.
İnceleme durumu yalnız bellekte, oturum başına son rapor olarak tutulur. Gerçek
kanıt değerlendirmesi, kalıcı sürümlü kayıt ve revizyon yürütme henüz uygulanmadı.

**Uygulama durumu:** bu çalışma dokümantasyondur. CoI-Agent entegrasyonu,
yeni çalışır guardrail'ler, deney yürütücüsü ve yöntem karşılaştırma benchmark'ı
tamamlanmış değildir. Mevcut SKILL.md ve references/ modülleri bu turda değiştirilmedi.

## 2. İnsanların kullandığı yöntemler ve bizim karşılığımız

Buradaki “yerleşik”, uzun süredir yayımlanan yöntem kaynakları ve kitaplara
işaret eder. Disiplinler arasında ölçülmüş “en popüler yöntemler” listesi
oluşturulmadı. Kitapların yayınevi tanıtımı ve içindekilerinin incelenmesi,
kitapların tamamının okunması anlamına gelmez. Kaynak ve okuma düzeyi §7'dedir.

| Yöntem ailesi | Literatürün sunduğu yaklaşım | Quaestio'da karşılığı ve önerilen karar | Sınır |
|---|---|---|---|
| Soruyu ve önemini kurma [M1] | Konudan araştırılabilir soruya ve anlamlı probleme ilerleme | **Koru/uyarla:** keşifte “neyi bilmiyoruz, öğrenmek neyi değiştirecek?”; mevcut question-discovery modülüne dayanır | Sırf yeni olması soruyu değerli yapmaz; bütün kullanıcı soruları yeni hipotez istemez |
| Kapsamlı alan yönelimi ve snowballing [R1] | Kapsamı tanımlama, kaynak seçimi, ileri/geri atıf araması | **Koru:** temel çalışmalar, survey'ler, yakın güncel çalışmalar; sorguları bulgularla daralt | Çok atıf doğrudan uygunluk veya doğruluk ölçütü değildir; sadece atıf ağına bağlı arama dışarıdaki çalışmaları kaçırabilir |
| Kavram merkezli sentez [M2] | Makale sıralamak yerine kavramlara göre karşılaştırma | **Belirginleştir:** CoI çizgilerini ortak bir karşılaştırma matrisiyle yan yana getir | Boş hücre gap değildir; bilinmeyen ve uygulanamaz ayrı tutulmalı |
| Araştırma gelişim çizgileri [R2] | Önceki çalışmalardan sonraki fikirlerin gelişimini düzenleme | **Seçildi:** CoI; problem, sonuç ve değişen varsayımı kanıtla bağla | Kronoloji/atıf tek başına düşünsel bağı kanıtlamaz; bağımsız dallar korunmalı |
| Varsayım sorgulama / problematization [M3–M4] | Yerleşik açıklamaların dayandığı varsayımları açığa çıkarma | **Belirginleştir:** aday geliştirmede varsayım, dayanak, alternatif ve beklenen bilgi farkı | Her varsayımı gevşetmek katkı değildir; yönetim kuramındaki yaklaşım mühendisliğe uyarlanır |
| Kanıt boşluğunu tanımlama [R1] | Yetersiz, tutarsız, yanlı veya soruya uygun olmayan kanıtı ayırma | **Koru/uyarla:** eksik özellik listesi yerine hangi sonucun neden kurulamadığını yaz | Farklı koşullarda elde edilen sonuçlar gerçek çelişki olmayabilir; sağlık çerçeveleri aynen taşınmaz |
| Literatürler arası keşif [M5] | Ayrı literatürlerdeki ilişkilerden incelenecek bağlantı önerme | **İhtiyaç halinde kullan:** CoI dalları arasında mekanizma köprüsü; iki terminolojide ve kesişimde arama | A–B ve B–C ilişkileri A–C'yi kanıtlamaz; yön, bağlam ve ölçek kontrolü gerekir |
| Yapısal analoji [M6] | Yüzey benzerliği yerine ilişkiler sistemini eşleme | **Uyarlama önerisi:** köprü adayında eşlenen nesne/işlem/koşul ve taşınamayan kısmı yaz | Eşleme hipotez üretir; fiziksel geçerlilik veya matematiksel garanti devretmez |
| Facet recombination [R2] | Amaç, mekanizma ve değerlendirme unsurlarını yeniden birleştirme | **Seçilen akışta:** Scideator referansı; somut aday kartı | Yeni kombinasyon tek başına yeni bilgi değildir; yapay kombinasyon çoğalması önlenmeli |
| Morfolojik analiz [M7] | Problem boyutlarını açma ve uyumsuz kombinasyonları eleme | **İsteğe bağlı:** adayların kombinasyon alanı karmaşıksa facet tutarlılığı için kullan | Ayrı varsayılan aşama gerekmiyor; ikili uyumluluk bütün kombinasyonun geçerliliğini kanıtlamaz |
| Rakip hipotezler ve ayırt edici kontrol [M8–M9] | Alternatif açıklamaları ayırabilecek sonuçları önceden düşünme | **Belirginleştir:** aday kartında güçlü rakip açıklama ve iddiayı zayıflatacak gözlem/karşıörnek | Tek deney kesin eleme sağlamayabilir; ölçüm ve yardımcı varsayımlar değerlendirilir; her katkı deneysel değildir |
| İddia düzeyinde prior-art incelemesi [R2, mevcut skill] | En yakın sonuçla varsayım, kapsam ve garanti karşılaştırması | **Temel adım:** ayrı kill-search; iddia bazında örtüşme ve kalan fark | Kill-search adı bir evrensel standart iddiası değildir; taramada eşleşme bulunmaması yenilik kanıtı değildir |

Bu karşılaştırmadan çıkan tercih, CoI'yi bir fikir üretme yöntemi kataloğuyla
şişirmek yerine **gelişim çizgisi + kavram matrisi + gerektiğinde farklı soru
üretme yolları** kullanmaktır. Genel yaratıcılık teknikleri bu incelemede kapsamlı
karşılaştırılmadı; TRIZ/SCAMPER gibi isimlerin burada bulunmaması etkisiz oldukları
sonucunu vermez. Bunları kaynak temelli çekirdeğe eklemek için ayrı bir ihtiyaç
ve değerlendirme gerekir.

## 3. AI sistemlerinden ne alınmalı?

Önceki [AI kaynak tablosu](../../README.md#ai-research-systems-and-evaluation-references)
ve [CoI kod incelemesi](../../README.md#coi-agent-implementation-inspection) korunur.
PaperLens, AI-Scientist, AI-Researcher ve CoI için önceki sınırlı kod okumaları
çalıştırma testi değildir. Diğer çalışmaların model puanları da bizim sistemimizin
başarı ölçümü olamaz.

| Sistem / çalışma | Buradaki tasarım kararı | Alınmayan varsayım veya ertelenen iş |
|---|---|---|
| CoI + Scideator [R2] | Seçilen sentez ve aday ifade temeli | Upstream ikili novelty çıktısını miras almak; sabit zincir ve fikir sayıları |
| ResearchAgent + SciMON [R2] | Literatüre geri dönerek adayın gerekçesini geliştirme örnekleri | Aynı model ailesinin fikir ve eleştiri üretmesinden bağımsız doğrulama sonucu çıkarma |
| PaperLens [R2] | Kaynak keşfi, karşılaştırma ve ağda gezinme | Abstract analiziyle esas modelin bulunmadığına karar verme |
| AI-Researcher + AI Scientist [R2] | İşler arası açık girdi/çıktı ve inceleme/deney/rapor ayrımı | Bu aşamada otomatik deney, kod üretimi ve makale yazım hattı |
| Co-Scientist [M10] | Üret–eleştir–revize döngüsü, kullanıcı amacı ve eleştiri gerekçeleri | Varsayılan büyük ajan turnuvası ve sınırsız hesap bütçesi; biyomedikal doğrulamaları alanlar üstü garantiye çevirme |
| HypoGeniC / HypoRefine [M11] | Veri varsa literatürden gelen hipotezi veriyle ilişkilendiren ileriki mod için referans | Veri yokken çalıştırmak; örüntü tahminini nedensel açıklama saymak; keşif verisinde doğrulamayı bağımsız test diye sunmak |
| HypoBench [M12] | Bilinen ilişkili sentetik örnekler ile gerçek veri görevlerini ayrı değerlendirme fikri | Veri örüntüsü benchmark'ını literatür yeniliğinin doğrudan testi saymak |
| Si ve arkadaşlarının fikir/uygulama çalışmaları [M13, R2] | İkna edici fikir puanı ile gerçekleştirilen araştırma sonucunu ayrı ölçmek | Bir fikrin beğenilmesini uygulanabilirlik veya bilimsel katkı kanıtı saymak |
| Patent istemi–pasaj karşılaştırması [M14] | Kill-search içinde iddia öğelerini belirli pasajlarla eşleme | Patent bağlamındaki sınıflandırmayı genel bilimsel yenilik kararı olarak kullanma |
| Embedding/FAISS patent prototipi [M15] | Yardımcı semantik kaynak getirme örneği olarak kaydet | Kalibre edilmemiş “yenilik skoru” ve doğrulanmamış güvenilirlik iddiası |

**Sürüm notu:** Co-Scientist'in ilk 2025 preprint'i ile 29 Haziran 2026 tarihli
v2 aynı çalışma ailesindedir. Güncel arXiv kaydı başlığı *Accelerating scientific
discovery with Co-Scientist* olarak verir ve Nature DOI'sine bağlanır. Bunları
iki bağımsız doğrulama çalışması olarak saymıyoruz [M10].

## 4. Önerilen çalışma akışı ve somut çıktılar

| İç sorumluluk | İş | İncelenebilir çıktı | Sonraki adıma geçiş |
|---|---|---|---|
| Keşif/kapsam | Kullanıcı sorusu, amacı, sınırları; uygun sorgular ve kaynaklar | Kapsam kaydı, kaynak listesi, arama/erişim günlüğü | Sentez için kullanılan kanıt ve eksikleri açık; hata başarı olarak gösterilmez |
| Sentez | CoI gelişim çizgileri + kavram matrisi; uygun olduğunda varsayım/uyuşmazlık/köprü incelemesi | Kaynak pasajına bağlı zincirler ve karşılaştırma hücreleri | Her temel ilişkinin kaynak desteği veya çıkarım etiketi var |
| Aday geliştirme | Kullanıcının yönüyle amaç–mekanizma–değerlendirme; değer ve rakip açıklama | Sürümlenen aday kartı; karşılaştırılabilir belirli iddialar | İddia belli, kapsamı ve en yakın açıklaması incelenebilir; hipotez geçici olabilir |
| Kill-search | Adayın belirli iddiasını çürütebilecek/önceden çözmüş çalışmaları ara ve oku | İddia bazında prior-art karşılaştırması, örtüşme/kalan fark, kapsam ve erişim sınırları | Bulguyla daralt, kapat, ertele veya ileri inceleme öner; otomatik “özgün” rozeti yok |

Akış döngüseldir. **Geçici hipotez kill-search öncesinde yazılabilir**; aksi halde
neye karşı arama yapılacağı belirsiz kalır. Kill-search sonrasında yalnızca
dayanağı olan kısmı korumak, hipotezi değiştirmek veya araştırmayı durdurmak mümkündür.

### Aday kartı: önerilen içerik

- Soru, neden önemli olduğu ve amaç–mekanizma–değerlendirme.
- İddia kimliği/sürümü, geçerli olduğu koşullar ve beklenen yeni bilgi.
- Oluşma yolu: varsayım, uyuşmazlık, transfer, yöntem iyileştirmesi veya diğer
  gerekçeli yol; bu etiketler kabul için zorunlu sınıflar değildir.
- En yakın çalışma ve güçlü basit açıklama; kaynak/pasaj dayanakları.
- Kritik varsayım; alternatif varsayım veya açıklama; veri ve araç gereksinimi.
- Hangi kontrolün hangi sonucu iddiayı destekler, daraltır veya zayıflatır;
  belirsiz sonuç halinde neyin söylenemeyeceği.
- Kill-search durumu ve kalan belirsizlik; sonraki iş ve tahmini kaynak ihtiyacı.

Literatürde aynı iddianın bulunması **öncelik/örtüşme** bulgusudur. İddiaya aykırı
bir deney veya karşıörnek **geçerlilik** bulgusudur. Sorunun önemli olmaması
**değer** değerlendirmesidir. Bunlar tek bir “kill” puanına indirgenmemeli.
Olumsuz veya eşdeğerlik sonucu da gerekçeli bir araştırma çıktısı olabilir.

### Kill-search içinde iddia–pasaj matrisi

Kullanıcının eklediği iki makaleyi Luna ayrıca inceledi. Ikoma–Mitamura [M14]
bilinen atıf pasajlarıyla istem öğelerini karşılaştırıyor; açık uçlu kaynak keşfini
değerlendirmiyor. Dar teknik alan ve tarih kapsamı, küçük insan karşılaştırması
ve zımni içerik hataları aktarımı sınırlar. Yararlı ek, aşağıdaki **Quaestio
uyarlaması**; ayrı bir skill veya otomatik yenilik sınıflandırıcısı değildir.

| İddia öğesi / ilişkisi | Kaynak ve sürüm | Pasaj konumu | İlişki ve gerekçe | İnceleme sınırı / sonraki kontrol |
|---|---|---|---|---|
| İncelenen belirli koşul veya sonuç | İncelenmiş asıl kaynak | Sayfa, bölüm, denklem vb. | Açık destek, gerekçeli çıkarım, kısmi eşleşme veya belirsizlik | Okunmayan kısım, gerekli uzmanlık veya ek kaynak |

Öğeleri ayırırken aralarındaki ilişki, nicelik ve koşullar korunmalı. Her öğenin
başka bir yerde bulunması, birleşik iddianın zaten kurulmuş olduğunu göstermez;
tek kaynaktaki yüzeysel benzerlik de yeterli değildir. Öte yandan bilimsel
karşılaştırma birden çok çalışmanın birlikte neyi kurduğunu inceleyebilir.
Kaynakta açıkça yazılan ile analistin çıkardığı sonuç ayrı tutulmalı. Kod,
tablonun bağlantılarını ve alanlarını kontrol edebilir; eşleşmenin bilimsel
doğruluğu semantik inceleme gerektirir.

Jeevan–Manjunatha [M15] semantik retrieval ve rapor üreten bir prototip sunuyor.
Veri kapsamı, etiketli doğruluk değerlendirmesi ve skor kalibrasyonu eksik olduğu
için çekirdek yöntem dayanağı olarak alınmıyor. Dergi ismi üzerinden değil,
sunulan deneysel kanıt üzerinden bu sınıra varıldı.

### Elenen adayları ele alma

“Bu fikir zaten var” kararı bütün aday ailesini otomatik silmez. Hangi iddianın
hangi kaynakla örtüştüğü kaydedilir. Kalan koşul farkı anlamlıysa yeni sürüm
oluşturulup yeniden incelenir; salt isim/veri seti değişikliğiyle fikir kurtarılmaz.
İddia yanlışsa önce yanlışlığın koşulları açıklanır. Kaynak erişimi yetersizse
aday reddedilmiş değil, **karar verilememiş** olur. Yeni kanıt gelince yeniden
açılabilmesi için gerekçe, kapsam ve eski sürüm korunur.

## 5. Skill, deterministik kontrol ve insan kararı

| Katman | Sorumluluk | Yapamayacağı şey |
|---|---|---|
| Skill / yöntem yönergesi | Nasıl soru sorulacağı, kaynakların nasıl karşılaştırılacağı ve sonuçların nasıl sınırlandırılacağı | Her çalıştırmada uyumu tek başına garanti etmek |
| Kod / durum yönetimi | Şema, kimlik/sürüm, kayıtlı pasaj konumu, kaynak bağlantıları, arama durumu, bütçe ve tekrar sayısı | Pasajın iddiayı semantik olarak desteklediğini veya fikrin özgün olduğunu kesinleştirmek |
| Model değerlendirmesi | Açıklama, eşleme, karşılaştırma, aday ve karşı kanıt önerisi | Kendi oylamasını bilimsel doğrulama saymak |
| Araştırmacı | Amaç, değer, önemli kapsam değişimi, kaynak/deney tercihi ve sonuçların yorumu | Kaynaksız model çıktısını doğrulanmış kanıta dönüştürmek |

**Önerilen teknik kurallar:**

1. Kaynak kaydı; sürüm, erişim tarihi, okuma düzeyi ve kullanılan konumu taşımalı.
   Abstract-only kayıt keşifte kullanılabilir; tam metin gerektiren bir yokluk
   iddiasını desteklemek için yeterli sayılmaz.
2. Retrieval durumları `completed`, `partial`, `failed`, `not_run` olarak ayrılmalı.
   Sıfır sonuç, timeout ve parse hatası aynı anlama gelmemeli. `completed` yalnızca
   planlanan isteğin tamamlandığını söyler; literatürün eksiksiz olduğunu söylemez.
3. İddia incelemesinin ayrı durumları `overlap`, `partial_overlap`,
   `no_match_within_scope`, `insufficient_evidence` olabilir. Bunlar tüm fikrin
   bilimsel geçerliliğinin tek boyutlu durumları değildir.
4. Bozuk çıktı şeması veya kopuk kanıt bağlantısı, ilgili bulgunun kanıtlı olarak
   yayımlanmasını durdurmalı; ham not veya açıkça işaretli taslak saklanabilir.
   Model gerekçesiyle bu kontrol atlanmamalı.
5. İddia/sürüm değişince önceki kill-search sonucu yeni iddiaya otomatik aktarılmamalı;
   bağımlı bulgular yeniden inceleme gerektirir. Aynı çalışma ailesi birden çok
   bağımsız kanıt gibi sayılmamalı.
6. Arama ve revizyon bütçesi sonlu olmalı. Bütçe dolunca kalan belirsizlikle durmalı;
   mutlaka “hayatta kalan” fikir üretme zorunluluğu olmamalı. Yeni karşı kanıt
   gelmemesi tek başına doygunluk/özgünlük sertifikası değildir.

Bu kurallar **tasarım önerisidir, çalışan kod beyanı değildir**. Nihai alan adları
[veri sözleşmesiyle](../product/api-and-data.md#proposed-output-contract) uygulama sırasında
uyumlandırılmalı. Kullanıcıya her kaynak eklemesinde onay sorulması önerilmiyor;
anlamlı yön, kapsam, maliyet veya deney değişiklikleri görünür kılınmalı.

## 6. Repo karşılığı ve yapılacak iş

| Mevcut dosya | Şimdiki içerik | Önerilen ürün işi |
|---|---|---|
| [SKILL.md](../../../quaestio/SKILL.md) | Tek giriş ve ihtiyaca göre yöntem seçimi | Ürün bunu yönlendirme temeli olarak kullanabilir; sırf yöntem sayısı arttı diye parçalama |
| [search-methods.md](../../../quaestio/references/search-methods.md) | Sorgu kalibrasyonu, atıf araması, izlenebilirlik | Arama günlüğü, erişim/hata ayrımı ve bütçeyi kodla uygulama |
| [question-discovery.md](../../../quaestio/references/question-discovery.md) | Soru, değer, güçlü açıklama, küçük ayırt edici kontrol | Aday kartına ve kullanıcı yönlendirmesine bağlama |
| [synthesis-and-checks.md](../../../quaestio/references/synthesis-and-checks.md) | Kavram matrisi, varsayım analizi, mekanizma köprüsü, iddiaya uygun kontrol | CoI zincirleriyle birleştirme; yeni sorunun gerekçesini görünür yapma |
| [source-audit.md](../../../quaestio/references/source-audit.md) | Orijinal pasaj, sürüm, varsayım ve garanti karşılaştırması | İddia bazında kill-search çıktı/bağımlılık durumları |
| [evidence-base.md](../../../quaestio/references/evidence-base.md) | E1–E12 yöntem kaynakları ve geçmiş okuma kapsamı | Bu yeni ürün incelemesini geçmiş kaynak kaydıyla karıştırmadan bağlama |
| [api-and-data.md](../product/api-and-data.md) | Önerilen kaynak/kanıt/veri sözleşmesi | Uygulama planında bu belgedeki taslak durumları tek sözleşmede netleştirme |

Önce en küçük soru→kaynak→kanıtlı yanıt akışı; sonra zincir/matris ve aday kartı;
ardından claim-specific kill-search bağlantısı. Yöntem açıklaması bulunması, bunların
uygulamada çalıştığı anlamına gelmez. Bu iş sırası öneridir; daha önce seçilen
yerel web ilk sürüm ve sonraki Tauri paketleme kararını değiştirmez.

### İleride nasıl değerlendireceğiz?

Önce süreç doğruluğu, sonra araştırma faydası ölçülmeli. Aşağıdakiler **henüz
koşulmamış değerlendirme tasarımıdır**:

| Örnek durum | Beklenen gözlenebilir davranış |
|---|---|
| Aynı sonuç farklı terminolojiyle daha önce var | En yakın kaynağı gösterir; katkı iddiasını daraltır/kapatır |
| Sorgu sıfır sonuç / servis hatası / erişilemeyen kritik PDF | Üçünü ayırır; hiçbirinden otomatik özgünlük çıkarmaz |
| Atıf var, gerçek gelişim ilişkisi belirsiz | Bağı kanıtlı gelişim ilişkisi olarak çizmez |
| İki kaynak farklı koşullarda ters sonuç veriyor | Koşulları hizalamadan çelişki/gap ilan etmez |
| Uzak literatürden çekici fakat geçersiz analoji | Eşlemenin kırıldığı koşulu gösterir; garantiyi taşımaz |
| Örtüşen tek iddiası olan çok iddialı aday | Bulguyu doğru iddiaya uygular; tüm fikri gerekçesiz reddetmez |
| Kaynak sürümü veya kullanıcı iddiası değişiyor | Bağımlı bulguları yeniden incelemeye işaretler |
| Aday güçlü basit açıklamayı aşmıyor | Gereksiz mekanizma eklemek yerine karakterizasyon, olumsuz sonuç veya kapanış önerir |

Fayda karşılaştırmasında aynı soru/kaynak erişimi/model/hesap bütçesi altında
temel arama+özetleme, CoI uyarlaması ve ek yöntemlerle akış karşılaştırılabilir.
Kaynak desteği, yanlış örtüşme/yanlış özgünlük, soru açıklığı, değer, uygulanabilirlik,
araştırmacının düzeltme yükü ve harcanan zaman ayrı raporlanmalı. Tek toplam puan
veya fikir sayısı yeterli değildir. Hakemler mümkünse üretim koşulunu bilmemeli;
kaynak ve geçmiş model bilgisi sızıntısı değerlendirilmelidir. Gerçek araştırma
sonucu için daha uzun takip gerekir [M12–M13]. Repodaki mevcut geliştirme örnekleri
bu karşılaştırmanın veya etkinlik doğrulamasının yerine geçmez.

## 7. Kaynak ve okuma kaydı

R1, kök README'deki [metodolojik kaynaklar](../../README.md#research-workspace-methodological-references)
(Levac, Wohlin, Robinson/AHRQ, Grant–Booth, Nyanchoka) grubudur.
R2, aynı dosyadaki [AI sistemleri](../../README.md#ai-research-systems-and-evaluation-references)
grubudur. Bunların önceki inceleme sınırları korunur; bu turda hepsinin yeniden tam
metin okunduğu ileri sürülmez. Aşağıdaki kitap ve yöntem kaynakları kök README'de
de listelenir. Aynı çalışma/kitap ailesinin farklı sürümleri bağımsız kanıt değildir.

| Kimlik | Kaynak | Bu turdaki inceleme ve sınır |
|---|---|---|
| M1 | Booth, Colomb, Williams, Bizup ve FitzGerald (2024). *The Craft of Research*, 5. baskı. [University of Chicago Press](https://press.uchicago.edu/ucp/books/book/chicago/C/bo215874008.html) | Resmî yayınevi kaydı ve içindekiler; kitabın tamamı okunmadı. Soru/önem çerçevesi için, karşılaştırmalı etkinlik kanıtı olarak değil |
| M2 | Webster ve Watson (2002). *Analyzing the Past to Prepare for the Future: Writing a Literature Review*. MISQ 26(2), xiii–xxiii. [Resmî kayıt](https://aisel.aisnet.org/misq/vol26/iss2/3/) | Kayıt kontrolü; güncel PDF erişimi başarısız. Matris ayrıntısı için repodaki E5'in açıkça tarihli geçmiş okuma kaydı kullanıldı; yeni tam metin okuması değil |
| M3 | Alvesson ve Sandberg (2011). *Generating Research Questions Through Problematization*. AMR 36(2), 247–271. [DOI](https://doi.org/10.5465/amr.2009.0188), [orijinal PDF](https://fenix.iseg.ulisboa.pt/downloadFile/563083097454984/4.pdf) | Seçili yöntem bölümleri, özellikle basılı s. 254–255; varsayımlar ve yinelemeli süreç. Kavramsal yöntem makalesi |
| M4 | Alvesson ve Sandberg (2024). *Constructing Research Questions: Doing Interesting Research*, 2. baskı. [SAGE](https://in.sagepub.com/en-in/ind/constructing-research-questions/book286538) | Yayınevi bilgisi ve içindekiler; tam kitap okunmadı. M3 ile aynı yöntem ailesi |
| M5 | Swanson ve Smalheiser (1996). *Undiscovered Public Knowledge: a Ten-Year Update*. KDD, 295–298. [Orijinal bildiri](https://cdn.aaai.org/KDD/1996/KDD96-051.pdf) | s. 295–296 ilişki köprüsü ve arama mekanizması; örneklerden genel transfer garantisi çıkarılmadı |
| M6 | Gentner (1983). *Structure-Mapping: A Theoretical Framework for Analogy*. Cognitive Science 7(2), 155–170. [DOI](https://doi.org/10.1207/s15516709cog0702_3), [yazarın kurumundaki PDF](https://groups.psych.northwestern.edu/gentner/papers/Gentner83.2b.pdf) | Özellikle s. 155–159 ve sistematiklik bölümü; ilişki/özellik ayrımı. Quaestio performans deneyi değil |
| M7 | Ritchey (2018). *General morphological analysis as a basic scientific modelling method*. TFSC 126, 81–91. [Yazarın PDF'si](https://www.swemorph.com/pdf/tfsc-gma-basic.pdf) | Özet ve s. 83–85 çapraz tutarlılık açıklaması; yöntem örneklemesi. Yenilik sertifikası değil |
| M8 | Platt (1964). *Strong Inference*. Science 146(3642), 347–353. [DOI](https://doi.org/10.1126/science.146.3642.347), [orijinal makale taraması](https://worthylab.org/wp-content/uploads/2019/05/platt1964.pdf) | Özellikle s. 347–348 alternatif hipotez/test döngüsü. Tarihsel yöntem savunusu; evrensel üstünlük iddiasını benimsemiyoruz |
| M9 | Shaw (2003). *Writing Good Software Engineering Research Papers*. ICSE, 726–736. [Yazarın PDF'si](https://www.cs.cmu.edu/~Compose/shaw-icse03.pdf) | Bu turda yeni tam metin incelemesi yok; mevcut E11 kaynak/okuma kaydı ve karşılaştırma tablosu kullanıldı |
| M10 | Gottweis ve arkadaşları (2026 sürümü). *Accelerating scientific discovery with Co-Scientist*. [arXiv v2](https://arxiv.org/abs/2502.18864v2), [kayıttaki Nature DOI](https://doi.org/10.1038/s41586-026-10644-y) | Güncel arXiv özet/sürüm kaydı ve resmî sistem tanıtımı; tam deney denetimi yapılmadı. Bildirilen doğrulama üç biyomedikal uygulamaya odaklı |
| M11 | Liu, Zhou, Li, Yuan ve Tan (2025 sürümü). *Literature Meets Data: A Synergistic Approach to Hypothesis Generation*. [arXiv v3](https://arxiv.org/abs/2410.17309v3), [HypoGeniC/HypoRefine resmî repo](https://github.com/ChicagoHAI/hypothesis-generation) | Özet ve README; kod/deney denetlenmedi. Veriyle desteklenen hipotez üretimi, genel nedensel keşif kanıtı değil |
| M12 | Liu, Huang, Hu, Zhou ve Tan (2026 sürümü). *HypoBench: Towards Systematic and Principled Benchmarking for Hypothesis Generation*. [arXiv v2](https://arxiv.org/abs/2504.11524v2) | Özet ve sürüm kaydı; veri görevleri/sentetik gerçek ilişkiler ayrımı. Sayısal sonuçlar yeniden hesaplanmadı |
| M13 | Si, Hashimoto ve Yang (2025). *The Ideation–Execution Gap: Execution Outcomes of LLM-Generated versus Human Research Ideas*. [arXiv v1](https://arxiv.org/abs/2506.20803v1) | Güncel özet/sürüm kontrolü; ayrıntılı önceki okuma sınırları E12'de. Fikir puanı ile icra sonucunu ayırma gerekçesi; tüm disiplin/model ailelerine genellenmez |
| M14 | Ikoma ve Mitamura (2025). *Can AI Examine Novelty of Patents?: Novelty Evaluation Based on the Correspondence between Patent Claim and Prior Art*. [arXiv v1](https://arxiv.org/abs/2502.06316v1), [PDF](https://arxiv.org/pdf/2502.06316) | Luna: 11 sayfa ve ekler; ana ajan: kimlik, görev ve seçili yöntem/sonuç kontrolü. Çalıştırma yapılmadı |
| M15 | Jeevan M. ve Manjunatha B. N. (2026). *AI-Based Patent Novelty Checker and Prior-Art Analysis Using Transformer Embeddings and FAISS*. IJSREM 10(07). [PDF](https://ijsrem.com/uploads/articles/1785000922694-05d18bacb5dd-Research-Paper-Pdf.pdf) | Luna: 5 sayfanın tamamı; ana ajan: kimlik ve seçili yöntem/sonuç kontrolü. PDF'de makale DOI alanı boş; DOI uydurulmadı |

## 8. Arama izi ve kapsam sınırları

14 Eylül 2026'da web araması, yayınevi/yazar/konferans sayfaları, arXiv kayıtları
ve resmî GitHub README'leri kullanıldı. Bu yöntem karşılaştırması için akademik
API üzerinden tam bir corpus taraması yapılmadı. Erişilebilir asıl metinler ile
özet/metadata düzeyindeki kaynaklar yukarıda ayrıldı. Arama sonuçlarındaki üçüncü
taraf özetleri bilimsel sonuçların dayanağı yapılmadı.

M14–M15 kullanıcı tarafından doğrudan sağlandı; Luna (`gpt-5.6-luna`, high)
ayrı kaynak incelemesi yaptı. Ajan değerlendirmesi kaynakların yerine geçmez;
raporlanan sayısal performanslar Quaestio sonucu olarak aktarılmadı.

Başlıca sorgular aşağıdadır; bunlar sonuç sayısı veya kapsamlı tarama sertifikası
değil, izlenebilir sorgu kaydıdır. Sonuçlardan yukarıdaki asıl kaynaklara gidildi:

```text
site.press.uchicago.edu The Craft of Research fifth edition questions problems significance
site.uk.sagepub.com Constructing Research Questions Doing Interesting Research Alvesson Sandberg problematization
site.sciencedirect.com literature based discovery hypothesis generation systematic review Swanson 2024 2025
site.arxiv.org scientific hypothesis generation literature review survey LLM 2025 2026
Generating Research Questions Through Problematization Alvesson Sandberg 2011
Structure Mapping A Theoretical Framework for Analogy Gentner 1983
Strong Inference Platt 1964
Towards an AI co-scientist 2025
"Strong Inference" "Platt" pdf university
"Constructing Research Questions" Alvesson Sandberg site:sagepub.com
"HypoGeniC" hypothesis generation paper
"The Ideation–Execution Gap" Si Hashimoto Yang
site.swemorph.com general morphological analysis Ritchey cross consistency assessment
site.aisel.aisnet.org Webster Watson 2002 concept matrix literature review
```

İkinci sorgu grubunda AOM, Wiley/Northwestern, Science ve Google Research/arXiv
alan filtreleri kullanıldı. DOI sayfalarındaki 403 ve bazı kurum PDF'lerindeki
erişim hataları “kaynak yok” diye yorumlanmadı; erişilebilen orijinal makale
kopyaları kullanıldı. M2 ve M9 için geçmiş repo okuma kaydına dayanıldığı özellikle
işaretlendi. Kitap ve makale sayısından bağımsız çalışmaların sayısı çıkarılmamalı.

Durma gerekçesi: seçilen çekirdeğin eksiklerini açıklayacak tamamlayıcı yöntemler,
alternatif AI yaklaşımları ve değerlendirme sınırları karşılaştırıldı. Bu sınırlı
ürün tasarımı incelemesi burada kapanabilir; belirli bir bilimsel konuda yeni
araştırma başlatıldığında o alanın literatürü ayrıca taranmalıdır.
