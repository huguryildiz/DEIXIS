# DEIXIS — buradan devam

Tarih: 14 Eylül 2026. Bu dosya, Miscellaneous görevindeki görüşmenin derlenmiş
devam kaydıdır; konuşmanın kelimesi kelimesine dökümü değildir.
Güncel belge yerleşimi için [dokümantasyon haritasına](../README.md) bakın.

> Ürün adı DEIXIS olarak seçildi. Bu tasarım paketi Quaestio’dan ayrı bir
> klasöre taşındı; aşağıdaki Quaestio sürüm bilgileri tarihsel skill bağlamıdır.

## Amaç ve bugünkü durum

Kullanıcı, her gün açıp araştırma yapabileceği, Consensus/Elicit tarzında bir
araştırma çalışma alanı istiyor. Doğal dilde soru, PDF kütüphanesi, literatür
taraması, kaynaklı sohbet, karşılaştırılabilir kanıt tablosu ve raporlar aynı
arayüzde bulunmalı. Skill seçmek, komut yazmak ve dosyalar arasında elle bağlam
taşımak günlük kullanımın parçası olmamalı.

Hedef alan bağımsızdır. Moleküler haberleşme, algae, WSN/UWSN ve OR/MILP yalnızca
örnek kullanım konularıdır. Kullanıcı bir ilgi alanı, keyword'ler, mevcut fikir
veya “X yöntemi Y probleminde kullanılabilir mi?” sorusuyla başlayabilir.

İncelenen Quaestio sürümü `037972d5add41d8a62cff45e09785beebc61bb01` idi;
görüşmede yerel HEAD ile GitHub HEAD eşleşti. Güncel durum yeniden kontrol edilmeli.
Mevcut repo tek girişli, modüler bir skill içeriyor. Beş sağlayıcıya ait çalışan
arama kodu, masaüstü uygulaması, standart kanıt CSV'leri ve HTML rapor üreticisi
henüz uygulanmış değil. Bu aktarım bunları uygulamaz.

## Dosyalar

- [İngilizce tasarım ve devam prompt'u](design-prompt.md)
- [API, kanıt ve yerel veri sözleşmesi taslağı](../product/api-and-data.md)
- [Kullanıcının alan örneği: baseline ve evidence matrix](../methods/domain-example.md)
- [Kaynaklar ve aktarılan dosyaların dizini](reference-index.md)
- [Değersiz ortam değişkeni örneği](../product/providers.env.example)
- [Yerel referans paketi](../../local-reference/2026-09-14/README.md)

`local-reference/` Finder'da görünür, ancak Git tarafından yok sayılır.
Ekran görüntülerindeki hesap/masaüstü
bilgileri, üçüncü taraf PDF'ler ve ham araştırma çıktıları yalnızca yerel devam
için saklanır. GitHub'dan yeni klon alan biri bu ekleri otomatik edinmez.

## Kullanıcının belirttiği ihtiyaçlar

- Kurulup bilgisayarda açılan, günlük kullanıma uygun arayüz; macOS ve Windows
  olasılıkları görüşüldü. Kullanıcı özellikle localhost/masaüstü kullanımını sordu.
- Kullanılabilir model/agent bağlantılarını tespit etme ve sohbet alanından seçme.
  Claude Code, Codex, DeepSeek ve yerel modeller örnek olarak anıldı.
- PDF içeri aktarma, koleksiyonlar, kaynak seçimi, önceki oturumlara devam etme.
- Solda araştırmalar/raporlar; ortada sohbet ve sonuçlar; kanıttan kaynağa erişim.
- Verilen akademik API'lerle literatür bulma; makalelerin yöntem, sonuç, sınırlılık
  ve gelecek çalışma önerilerini CSV'ye çıkarma.
- Keşif istendiğinde 3–4 aday araştırma sorusu geliştirme; mevcut çalışmalarla
  bunları çürütmeye veya kapsamlarını daraltmaya çalışma.
- İnsan tarafından anlaşılabilir sonuçlar; eksik kanıtı uydurmama.

## Son kullanıcı kararı — 14 Eylül, 12:46 mesajı

**Ürün ve araştırma sistemi adı Quaestio olarak kalacak. Kendi arayüzümüz
geliştirilecek. İlk sürüm lokalde çalışan web uygulaması olacak.** Yerel backend
başlatılacak; arayüz tarayıcıda localhost üzerinden açılacak. Kullanıcı önce
terminalden başlatabilmeyi kabul ediyor; “Start Quaestio” başlatıcısıyla tarayıcının
otomatik açılması hedeflenen sonraki kullanım kolaylığıdır.

```text
Quaestio
  Browser UI
  Local backend
  Local PDF/library storage
  API connectors
  Local/cloud model connectors
```

**İkinci aşama Tauri ile masaüstü paketleme.** Bu, aynı arayüzün yeniden kullanımını
hedefler; backend'i paketleme, süreç yönetimi, işletim sistemi izinleri, testler ve
imzalama ayrıca tasarlanacaktır. Yalnızca web arayüzünü sarmak bunları çözmez.

shadcn/ui aday olarak anıldı, kesin seçilmedi. Frontend/backend dili, framework,
ilk model bağlantısı, başlatıcı ve veri şemasının ayrıntıları açık. Araştırma motoru
arayüzden bağımsız tutulacak. Model ve akademik API bağlantıları backend'de yönetilecek.

## Karar geçmişi ve açık ayrıntılar

### Sonraki görüşmede netleşen kapsam — 14 Eylül 2026

- Semantic Scholar, Crossref, arXiv, OpenAlex, Scopus, IEEE Xplore ve SerpApi'nin
  tamamı ürün kapsamındadır. Kullanıcı başka akademik kaynaklar da ekleyebilmeli.
  Desteklenen bağlantıların uygulanması aşamalı olabilir; bu, kapsamdan kaynak
  çıkarılması anlamına gelmez. Her aramada bütün kaynakların kullanılması gerekmez.
- Kullanıcı kendi Claude Code/Codex abonelik bağlantısını veya kendi sağlayıcı API
  anahtarını kullanır. Uygulama desteklenen yerel kurulumları ve servisleri algılar;
  kurulum, oturum ve kullanılabilirlik durumlarını ayrı kontrol eder. Entegrasyonlar
  henüz uygulanmadı; abonelik üzerinden erişim bağlantı bazında doğrulanacak.
- Ollama isteğe bağlıdır. Kurulu/çalışır durumdaysa algılanıp yüklü modelleri
  listelenebilir; kullanıcıya zorunlu model kurulumu veya servis yönetimi yüklenmez.
- Model listeleri bağlantıdan güncellenir; listeleme yoksa elle model kimliği girme
  yolu bulunur. Kullanıcının model seçimi korunur. Kimi ve GLM gibi model aileleri,
  onları sunan bağlantı altında gösterilir.
- LangChain orkestrasyon/erişim bileşenleri ve ChromaDB yerel vektör indeksi için
  teknik adaylardır; henüz seçilmiş veya kurulmuş bağımlılıklar değildir.
  `llama3`, `mistral` ve `nomic-embed-text` örneklerdir, sabit model seçimleri değildir.
  Yanıt modeli ve embedding bağlantısı bağımsız seçilebilir.

Ayrıntılar [API ve veri taslağında](../product/api-and-data.md) tutulur. Bu güncelleme yalnızca
ürün kararlarını ve teknik adayları kaydeder; çalışan uygulama oluşturmaz.

**İsim:** Quaestio adı son kullanıcı mesajıyla seçildi. “Research Workspace”
açıklaması öneri olarak duruyor.
Indago, Quaero, Investigatio, Vestigium ve research-evidence alternatifleri
konuşuldu; son kararla alternatif isim arayışı kapandı. Rapor başlığı araştırma
konusu olmalı, ürün adı küçük üretim bilgisi olarak kalabilir.

**Mimari:** Kullanıcı çok ajanlı yapı istemiyor. İlk sürüm tek kullanıcı girişi,
tek ana ajan ve ihtiyaca göre kullanılan yöntem dosyaları/araçlarla tasarlanmalı.
Ek ajan yalnız kullanıcının ayrıca istediği sınırlı inceleme için düşünülebilir;
işin tamamlanması buna bağlı olmaz. Deterministik kontroller ayrı ajan değildir.
Başlangıçtaki “orchestrator + dört skill” önerisi sonradan sadeleştirildi.
Mevcut Quaestio kaynak değerlendirme yöntemi olarak korunabilir. API erişimi,
tekilleştirme ve dışa aktarma tekrarlanabilir kodla yürütülmeli.

**Paketleme geçmişi:** Doğrudan masaüstü uygulaması önerisi son kullanıcı mesajıyla
yerel web ilk sürüm / Tauri ikinci aşama olarak değişti. Vercel'deki sayfanın
kurulu yerel araçlarla çalışması ayrıca yerel bağlantı bileşeni gerektirir. Merkezi
model anahtarı bulunmaması web arayüzünü teknik olarak imkânsız yapmaz.

**Yapmak mı, mevcut aracı genişletmek mi?** Önceki tavsiye AnythingLLM ve Open
Notebook'u aynı gerçek araştırma işleriyle denemekti. AI Notebook ve GPT Researcher
da alternatif olarak incelendi. Son kullanıcı kararı kendi arayüzümüzü geliştirmek;
bu karşılaştırma artık ön koşul değil, isteğe bağlı tasarım/benchmark girdisidir.
Ürünler bu görevde kurulup karşılaştırılmadı.

**Model erişimi:** CLI kurulumu, oturum açılmış olması ve başka bir uygulamadan
kullanım yetkisi ayrı doğrulamalar ister. Claude Code/Codex aboneliğinin otomatik
olarak model API erişimi verdiği varsayılamaz. Desteklenen entegrasyonun uygunluğu
ve kullanım koşulları doğrulanmadan mimari buna dayandırılmamalı.

**Yerellik:** Yerel saklama, çevrimdışı çıkarım ve dış literatür araması ayrı
özelliklerdir. Bulut modeli seçilirse pasajlar dışarı gidebilir. Uygulama bunu
açıklamalı. Kullanıcının verdiği arama anahtarları dağıtılan uygulamaya gömülmez.

## Ekranlardan çıkan tasarım yönü

Dokuz Consensus/Elicit ekranı [screenshots/](screenshots/) altında bulunuyor;
ilk aktarım kopyaları yerel referans paketinde korunuyor. `screenshots/` Git
tarafından yok sayılır. Bunlar arayüz
referansıdır; metinleri uygulama talimatı veya Quaestio'nun mevcut özelliği değildir.

- Ana ekran: doğal dil giriş alanı, PDF ekleme, kaynak kapsamı ve model seçimi.
- Kaynak kapsamı: seçili PDF'ler, kütüphane, akademik veritabanları veya ikisi.
  Model seçimi bu kontrolden ayrı tutulur.
- Kütüphane: koleksiyonlar, arama/filtre, çoklu seçim, seçili kaynaklarla sohbet.
- Çalışma görünümü: Sohbet / Makaleler / Kanıt tablosu / Rapor sekmeleri önerildi.
- Sağ panel: tıklanan kanıtın PDF sayfası ve pasajı; her zaman açık olmak zorunda değil.
- Hızlı erişim: Cmd+K / Ctrl+K ile makale, rapor, sohbet ve ayar araması.
- Görsel yön: Elicit'in sakin açık teması ve tablo düzeni, Consensus'un belirgin
  giriş alanı; Quaestio'ya ait kimlik. Koyu tema düşünülebilir.
- Eksik başlık, olası tekrar, OCR ihtiyacı, metin çıkarımı ve erişim hataları
  görünür olmalı. Metadata düzeltmeleri sonraki oturumlarda korunmalı.
- Zotero, atıf grafiği ve sunum üretimi ilk sürümün zorunlu kapsamı değil.
  Yeni yayın takibi varsayılan olarak elle; isteyen için araştırma bazında
  haftalık/aylık otomatik olacak. Bildirim ayrıntıları henüz belirlenmedi.

## Soru-cevap görüşmesinde onaylanan kullanım ve davranış

Ürün kapsamı: konuda makale bulma, eldeki makaleleri karşılaştırma/soru-cevap,
araştırma fikrinin literatürdeki yerini değerlendirme, konu öğrenme, belirli iddiayı
kaynaklardan kontrol etme, tek makaleyi derinlemesine anlama, kanıt tablosu,
kaynaklı literatür/related work taslağı, araştırma tasarımı ve yeni yayın takibi.
Hepsi kapsamda; geliştirme sırası ayrıca belirlenecek. Araştırma tasarımı desteği,
kendiliğinden deney başlatma yetkisi değildir.

- Açık istekte doğrudan başla; cevabı önemli ölçüde etkileyen belirsizlikte kısa
  soruları tek tek sor. Kullanıcı bilmiyorsa kapsam öner ve varsayımı görünür kıl.
- Rutin arama ve ön elemede ilerle. Kısa listeyi ve eleme gerekçelerini görünür,
  düzenlenebilir tut; onayı her seferinde zorunlu kılma. Kullanıcı müdahale edebilir.
- Kullanıcının belirlediği maliyet sınırı aşılacaksa veya kapsam önemli ölçüde
  değişecekse durup sor. Sistematik derleme gibi işler için onaylı eleme seçeneği sun.
- Bulguları araştırma sürerken ön değerlendirme olarak göster ve kapsamını belirt.
  Yeni kanıt önceki bulguyu değiştirirse değişikliği açıkça işaretle.

Onaylanan ilerleme arayüzü: sohbeti tekrar eden durum mesajlarıyla doldurmak yerine
yanıtın üzerinde aynı yerde güncellenen küçük bir durum kartı. Kart bulunan ve
benzersiz yayınları, ön seçimi, hazır PDF'leri ve incelenen kaynakları gerçek işlem
durumlarından gösterir. PDF indirme, metin çıkarma ve bölüm inceleme ayrıdır;
temelsiz tamamlanma yüzdesi gösterilmez. Kaynakları inceleme ve duraklatma erişimi olur.

Makaleler görünümü seçim/erişim/inceleme durumlarını; kanıt tablosu inceleniyor,
kaynakta bulunamadı ve erişilemedi durumlarını; yanıt/rapor da kanıt kapsamını gösterir.
Atıf veya hücre seçilince sağ panelde ilgili PDF sayfası/pasajı açılır. Kullanıcı
düzeltmeleri sonraki otomatik güncellemelerde korunur. Tamamlanma kartı incelenen
kaynak sayısını ve erişilemeyenleri bildirir. Görüşmedeki sayılar temsiliydi.

Son eklenen iki ekranın [referans dizini](reference-index.md), Elicit'in sohbet ve
çıktı alanını, Consensus'un yan yana yanıt/kaynak panelini tasarım girdisi olarak
kaydeder. Ekranlardaki bilimsel sonuçlar doğrulanmış kabul edilmez.

## Sonraki soru-cevap kararları — 14 Eylül 2026

- Ortak kütüphaneye bağlı ayrı araştırma alanları olacak. Bir araştırma birden
  fazla sohbet, kaynak seçimi, kanıt tablosu ve rapor içerebilir. PDF'ler paylaşılır;
  RAG varsayılan olarak sadece aktif araştırmanın corpus'unda arar. Sohbette kaynak
  seçimi kapsamı daha da daraltabilir. Diğer araştırmaların kaynakları karışmaz.
- Düzenlenebilir tablo sütunları arama API'sinin alanlarından ayrıdır. Yeni sütun
  için corpus içindeki ilgili pasajlar kodla/metin veya vektör aramasıyla bulunur;
  anlamlandırma gerektiren hücreleri seçilen LLM çıkarır. Yapılandırılmış metadata
  ve daha önce çıkarılmış bilgi için gereksiz model çağrısı yapılmaz.
- Kullanıcı düzenlemeleri korunur; yeni bulgu hücreyi ezmek yerine kaynaklı
  değişiklik önerisi üretir. Hücrelerde kısa kaynak alıntısı ve pasaj bağlantısı
  bulunur; yazarın açık ifadesi ve modelin çıkarımı ayrılır. PDF yoksa mevcut
  özet/metadata kaynağına bağlanılır, PDF konumu uydurulmaz.
- Araştırma bazında API harcama veya kullanım sınırı belirlenebilir. Bağlam
  kapasitesi ve sağlayıcının bildirdiği günlük/haftalık ya da başka dönemsel kota
  durumları araştırma sırasında izlenir. Bildirilmeyen değerler bilinmiyor olarak
  gösterilir; çalışma içi ölçümler hesap genelindeki kullanım yerine geçirilmez.
- Kota dolarsa veya model bağlantısı kesilirse ilerleme kaydedilip duraklanır;
  başka modele geçmeden önce kullanıcıya sorulur. Önceden otomatik yedek model
  seçme önerisi henüz ayrıca onaylanmadı.
- Yeni yayın kontrolü varsayılan olarak elle, isteğe bağlı araştırma bazında
  haftalık/aylık otomatik olacak. Bu ürün özelliğidir; mevcut görüşmede gerçek bir
  otomasyon oluşturulması istenmedi.
- Arayüzün varsayılan dili İngilizce, Türkçe de desteklenecek. Yanıt/rapor dilini
  arayüzden bağımsız seçmek onaylandı: yanıt varsayılan olarak sorunun dilinde,
  rapor dili ayrıca seçilebilir.
- Önce localhost web uygulaması; sonra macOS ve Windows masaüstü paketlemesi.
- Dışa aktarma: rapor Markdown/PDF, tablo CSV/Excel, kaynakça BibTeX/RIS.
- PDF erişimi olmayan yayınlar korunur; özet temelli bilgi etiketlenir. Kullanıcı
  sonradan PDF ekleyebilir. Tam metin gerektiren hücreler bu ihtiyacı gösterir.
- Bağlam sınırına yaklaşınca tamamlanan işler ve kaynak bağlantıları korunarak
  devam özetiyle yeni bağlama otomatik geçilir; geçiş arayüzde belirtilir. Özetin
  dışındaki ayrıntılar gerektiğinde kayıtlı kaynaklardan yeniden getirilir.
- Rapor uygulama içinde düzenlenebilir; kullanıcı metni korunur, sonraki
  otomatik güncellemeler değişiklik önerisi olarak sunulur.
- Silinenler önce çöp kutusuna gider. Bir makaleyi araştırmadan çıkarmak ortak
  kütüphanedeki PDF'yi silmez.
- Tarayıcı kapansa da backend çalışıyorsa araştırma sürer. Backend/bilgisayar
  kapanırsa tamamlanan adımlar korunur; yeniden açılışta devam seçeneği sunulur.
- Açık/koyu tema desteklenir; başlangıçta sistem teması izlenir, tercih korunur.
- Tam araştırma paketiyle bilgisayarlar arası taşıma sonraya bırakıldı. İlk
  sürümde rapor/tablo/kaynakça dışa aktarma var; sabit kimlikler korunmalı.
- PDF pasaj işaretleme ve kişisel notlar desteklenir; kullanıcı yorumu kaynak
  kanıtından ayrı tutulur.
- Elicit benzeri ana ekran yerleşimi onaylandı: solda gezinme ve son araştırmalar,
  ortada büyük soru alanı, altında görev kısa yolları ve devam kartları. Kaynak
  kapsamı ve model seçimi görünür; ayrıntılı bağlantı/kota bilgileri seçicide olur.
- Soru yazarak başlamak esastır; PDF zorunlu değildir. İsteğe bağlı dosyalar
  artı düğmesi veya sürükle-bırakla eklenir, göndermeden önce kaldırılabilir.
  "Eklenen dosyalar" / "Eklenen dosyalar + akademik arama" kapsamı görünürdür.
- Normal metin çıkarımı yetersizse OCR otomatik denenir; sorunlu sayfalar
  kontrol gerekli olarak işaretlenir.
- Preprint ve yayımlanmış sürüm aynı yayın altında ayrı sürümler olarak tutulur;
  yeni sürüm eski kanıtları otomatik değiştirmez.
- Quick / Standard / Detailed derinlik seçimi olur; varsayılan Standard.
  Bunlar işlem derinliğidir, doğruluk garantisi değildir.
- Araştırma sürerken aynı sohbetten yönlendirme yapılabilir; tamamlanan iş korunur,
  kalan adımlar düzenlenir ve kapsam değişikliğinden etkilenen bulgular işaretlenir.
- Çelişen bulgular kaynakları ve koşullarıyla yan yana sunulur; farklı deney
  koşulları kendiliğinden çelişki sayılmaz.
- Yetersiz sonuçta seçili kaynaklar ve bütçe içinde terim/atıf araması genişler;
  konu kapsamının önemli değişimi için kullanıcıya sorulur.

### Corpus büyüklüğü ve UI kararlarının dayanağı

Kullanıcıdan baştan makale sayısı istenmez. Soru, kapsam, derinlik ve bütçe esas
alınır; adaylar ön elenir, ilgili kaynaklar partiler halinde incelenir ve açık kalan
sorulara göre devam edilir. Belirli sayıya ulaşmak bilimsel yeterlilik ölçütü
değildir. Bütçe veya tarama sınırında durulduğunda neden ve incelenmeyenler açıklanır.
Bulunan, ön elemeden geçen, incelenen ve yanıtta kullanılan kaynak sayıları ayrı
gösterilir. Makale ve sürüm tekilleştirmesiyle sayımın birimi açık tutulur.

Rutin UI kararlarında Elicit/Consensus'un ilgili ekranları kullanıcının Chrome
oturumunda incelenerek somut öneri geliştirilmesi istendi. Kişisel tercih veya
araştırma biçimini etkileyen kararlar kullanıcıya sorulur. Ekranda gözlemlenen
davranış ve Quaestio önerisi ayrı belirtilir. İlk canlı inceleme notları
[referans dizininde](reference-index.md#live-chrome-ui-inspection) kayıtlıdır;
ürünlerin bilimsel başarısı test edilmedi.

### Öncelikli gereksinim: hücre dayanağı ve tek hücreyi yeniden inceleme

Kullanıcı bu özelliğin önemli olduğunu özellikle belirtti. Kanıt tablosundaki
her hücreden "Bu sonucu nasıl çıkardın?" / "Show evidence" açılabilir. Panelde
kısa kaynak pasajı, kaynak/sürüm ve sayfa veya diğer mevcut konum bilgisi;
yazarın açık ifadesi ile modelin yorumu ayrımı; varsa gerçekten uygulanmış hesap,
girdi değerleri ve birimleri; belirsizlik veya eksik kanıt görünür.

Açıklama, kaydedilmiş kanıt ve işlemlere dayanır; sonradan üretilmiş bir gerekçe
doğrulama kaydı olarak sunulmaz. "Recheck this cell" yalnızca seçilen hücreyi,
aktif araştırma ve kaynak kapsamını koruyarak yeniden inceler. Kullanıcının
düzenlemesini ezmez; eski ve önerilen değeri dayanaklarıyla gösterir. Bir sonuç
değişirse ona bağlı rapor bulguları güncelleme gerektiği için işaretlenir.

## Araştırma yöntemi kararı — Chain of Ideas

14 Eylül 2026: Kullanıcı **Chain of Ideas yönteminin kullanılmasını** seçti.
Yöntem, literatürü araştırma gelişim zincirleriyle sentezlemek ve bu sentezden
aday araştırma soruları geliştirmek için Quaestio'ya uyarlanacak. Yöntem seçildi;
CoI-Agent henüz kurulmadı, entegre edilmedi veya değerlendirilmedi.

**Onaylanan tasarım: Alan haritasını araştırmanın gelişim çizgileriyle oluşturmak;
adayları amaç–mekanizma–değerlendirme üzerinden somutlaştırmak; ardından her
adayın belirli iddiasına kill-search uygulamak.** Gelişim çizgileri için Chain of
Ideas, adayları bu üç boyutta ifade etmek için Scideator'ın facet yaklaşımı
uyarlanır. Amaç araştırılacak soruyu veya hedef sonucu, mekanizma önerilen
açıklamayı/yöntemi, değerlendirme ise karşılaştırıcıyı ve iddiayı sınayacak kanıtı
belirtir. Bu birleşik akış Quaestio'nun tasarım kararıdır.

Başlangıç yine doğal dilde sorudur; PDF veya önceden seçilmiş makaleler zorunlu
değildir. Temel çalışmalar, survey/review'lar ve yakın güncel özgün çalışmalar
üzerinden birden fazla gelişim çizgisi oluşturulur. Her çalışmanın çözdüğü problem,
getirdiği sonuç ve sonraki çalışmayla ilişkisi kaynakla gösterilir. Tarih sırası
veya atıf bağlantısı tek başına bir gelişim ilişkisini kanıtlamaz; rakip açıklamalar,
dallanmalar ve henüz kapanmamış sorular korunur.

Kullanıcı yönlendirmesiyle daraltılan yönde somut aday iddialar geliştirilir.
**Kill-search ayrı ve temel bir adımdır:** alan içindeki en yakın çalışma, aynı
yapının başka adla bulunduğu yöntem literatürü ve komşu uygulamalar incelenir.
Karar bütün fikre otomatik uygulanmaz; hangi iddianın örtüştüğü ve neyin kaldığı
belirtilir. Taranan kapsamda eşleşme bulunmaması özgünlüğü kanıtlamaz. Sonraki çıktı
koşullu hipotez, varsayımlar ve doğrulama planıdır; otomatik deney yetkisi değildir.
Zincir/aday sayıları soruya ve bütçeye göre belirlenir. Yeni kanıtla önceki
zincirlere ve adaylara dönülebilir.

Yöntem, kitap ve AI sistem/değerlendirme referansları, katkı ve inceleme
sınırlarıyla [kök README'de](../../README.md#research-workspace-methodological-references)
tutulur. [Seçilen akış](../../README.md#selected-synthesis-method-chain-of-ideas)
Quaestio uyarlamasıdır; Scideator ve diğer sistemler tamamlayıcı tasarım
referanslarıdır. Mevcut skill kaynak denetimi temeli olarak korunur.

### Tamamlayıcı yöntem incelemesi

14 Eylül 2026 tarihli [ayrıntılı yöntem karşılaştırması](../methods/research-methods.md),
literatürün ne önerdiğini mevcut repo modülleri ve ürün işleriyle eşler.
Kaynak listesi, okuma düzeyleri, arama izi, elenen adayların ele alınması,
skill/kod/insan sorumlulukları ve ileride yapılacak değerlendirme burada tutulur.
Kullanıcının son eklediği iki patent makalesi Luna tarafından ayrıca incelendi.

**Öneri, henüz yeni uygulama veya kabul edilmiş ek mimari kararı değil:** tek giriş
ve dört iç sorumluluk (keşif/kapsam, sentez, aday geliştirme, kill-search).
Kavram matrisi, varsayım sorgulama, gerekçeli literatürler arası köprü, rakip açıklama
ve ayırt edici kontrol bu sorumlulukların içinde çalışabilir. Kill-search'e iddia
öğesi–kaynak pasajı matrisi önerildi; patent sınıflandırması aynen aktarılmayacak.
Geçici hipotez kill-search öncesinde yazılabilir; sonraki kanıt iddiayı daraltır,
değiştirir veya kapatır. Yeni kullanıcı skill'leri ve otomatik yenilik skoru önerilmedi.

Son mimari sadeleştirmesine göre bu işlerin tamamı tek ana ajanla yürütülebilmeli.
Kısa fizibilite kontrolü aday geliştirmenin içinde yer alır; her adaydan matematiksel
model istenmez. Önce kısa alan haritası, sonra seçilen yönde derin sentez yapılır.
Yeni kanıtla geri dönülebilir; aday kapatma/erteleme de geçerli sonuçtur. Kullanıcı
araştırma yönü ve önemli kapsam/deney/maliyet kararlarında devreye girer.
Kritik denklem ve algoritmalar orijinal sayfayla denetlenir; ayrıştırma başarısı
bilimsel doğruluk sayılmaz. Ayrıntılar yöntem dokümanının ilk bölümündedir.

**Son kullanıcı önerisi — isteğe bağlı model seçerek inceleme:** kullanıcı bir
aday/sonucu/raporu seçip “Başka modelle incele” eylemiyle ayrı değerlendirme
başlatabilir. İncelemeci eldeki kaynaklarla sürümlü bir kopyayı okur ve kaynaklı
bulgular içeren ayrı rapor döndürür. Yeni dış arama isteğe bağlıdır; gönderilecek
içerik ve bütçe görünür olmalıdır. Rapor ana çalışmayı otomatik değiştirmez;
kullanıcı bulguları geri besleyip revizyon isteyebilir. Farklı model görüşü
bilimsel doğrulama sayılmaz. Ayrıntılı akış [yöntem belgesindedir](../methods/research-methods.md#isteğe-bağlı-başka-modelle-inceleme);
etkileşimli [UI demosu](../../prototypes/shadcn-ui/README.md#optional-model-review-prototype)
eklendi. Demo model seçimi, ayrı örnek rapor ve bulgu geri aktarımı çalışır;
gerçek model çağrısı, kaynak değerlendirmesi ve kalıcı inceleme geçmişi yoktur.

## Sıradaki anlamlı çalışma

Yerel web uygulamasının küçük teknik planını çıkarıp ilk model bağlantısını
doğrulayın. Son kullanıcı düzeltmesine göre ilk prototip soruyla başlar: akademik
arama, kaynak seçimi, erişilebilir kaynakları inceleme, kaynaklı yanıt ve oturum
kalıcılığı. PDF ekleme isteğe bağlı paralel bir yoldur; başlamak için zorunlu adım
değildir. Kanıt tablosu bu temelin üzerine eklenir. Yedi sağlayıcının tamamı ürün
kapsamında kalır; uygulama sırası kapsamdan çıkarma anlamına gelmez.

15–20 tanıdık makaleyle kaynaklı soru-cevap, yöntem/sınırlılık tablosu ve en yakın
çalışma karşılaştırması değerlendirme örnekleri olarak kullanılabilir. Yanlış atıf,
kaçırılan kanıt, düzeltme süresi ve kalıcılık ölçülmeli. Mevcut araçlarla karşılaştırma
isteğe bağlıdır ve gerçekleştirilmiş değildir.

Başarı ölçütü özellik sayısı veya güzel ekranlar değil, günlük araştırmada daha az
elle doğrulama/bağlam taşıma ve daha güvenilir kaynak takibidir. Mevcut Quaestio'nun
dokuz geliştirme örneği bu ürünün etkinliğini veya canlı arama başarısını kanıtlamaz;
[mevcut değerlendirme sınırları](../../../quaestio/evaluations/README.md) geçerlidir.

## Dosya görünürlüğü olayı

Finder'da repo boş görünüyordu. `Documents/GitHub/quaestio` ile iCloud Documents
yolu aynı inode'a çıktı; yanlış klon değildi. Normal dosyalarda BSD `hidden`
bayrağı vardı. İlk `chflags nohidden` değişikliği bazı dosyalarda geri döndü.
NSFileCoordinator ve URLResourceValues.isHidden=false ile görünürlük güncellendi;
son iki dosyada `.contentIndependentMetadataOnly` kullanıldı. Finder görüntüsü,
tüm normal dosyaların bayrakları ve 20 saniye sonraki kontrol doğrulandı; içerik
hash'leri değişmedi. Bayrağı ilk koyan süreç kesin olarak belirlenmedi.

Tekrar ederse önce görünürlük ve File Provider durumunu inceleyin; kayıp sanıp
repoyu silmeyin, yeniden klonlamayın veya iCloud ayarlarını geniş kapsamlı değiştirmeyin.
`.git` ve diğer nokta dosyaları normal olarak gizli kalabilir.

## Devam ederken kapsam

Bu tur yalnızca dosya aktarımı ve devam kaydıdır. Uygulama/entegrasyon
geliştirilmedi; hiçbir API anahtarı kaydedilmedi; mevcut SKILL.md değiştirilmedi.
Kaynak dosyalar kopyalandı, taşınıp silinmedi. Commit, push, yayın ve yeni uygulama
kurulumu yapılmadı. Eski evaluation continuation prompt'u tarihsel ayrı bir iştir;
bu ürün görüşmesi onu otomatik olarak başlatmaz.
