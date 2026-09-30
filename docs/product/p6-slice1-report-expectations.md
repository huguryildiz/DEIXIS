# P6 dilim 1 rapor ölçümü: beklentiler (koşudan önce donar)

**Tarih:** 30 Eylül 2026. **Durum:** DONDU, gerçek model koşusundan önce. Beş gözden geçirme turu (gpt-6.1-sol, high; kit ve koşu
istemi dahil) yapıldı; beşinci turun düzeltmeleri (okuma paketinde karakter kesmesinin kaldırılması, `snapshot` için koşunun kendi
`--report` kimliğinin zorunlu tutulması, R5 ve R11'de eksik okumanın "ölçüldü" sayılmaması) altıncı bir tur yapılmadan uygulandı.
Donma anı, bu dosyanın ve kararların tek bir commit'e girdiği andır; gerçek model koşusu o commit'ten sonra başlar. Sonuç bu
beklentilere göre yorumlanır, tersi yapılmaz; koşudan sonra hiçbir aralık değişmez.

**Ne ölçülür:** bugünkü `main`'in (`760d351`, P6–P14, D118 rapor incelemesi, D120 Markdown dışa aktarma, D119 sonrası
her araştırma `sw`) bir gerçek modelle, bir araştırma ve bir tablo üzerinde yazdığı **tek** rapor. Plan: `p6-slice1-report-run.md`
bölüm 1n; metrik tanımları: `p6-report-design.md` §13. Bir araştırma, bir tablo, bir koşu, bir model: sonuç bir örnek
üzerinde bir betimlemedir, rapor türünün genel kalitesi değildir.

**Ne ölçülmez:** başka bir kaynak kümesinde ya da başka bir modelde davranış; korpusun geri çağırması (D55'teki
sorunlar rapora aynen yansır); matematiksel doğruluk (R6 yalnız sayfayla karşılaştırır); ikinci bir koşu. Bu ölçüm
`gpt-5.6-luna` ile yapılır; sonuç başka bir modele taşınmaz.

## Kararlar (Claude ve gpt-6.1-sol tarafından, sahibin talimatıyla, 30 Eylül 2026)

Sahip üç seçimi Claude ile Sol'a bıraktı; ikisi de aşağıdaki karara vardı. Bu bölümde boş alan yoktur.

1. **Ölçülen araştırma ve tablo: yol B.** Araştırma `res_IXBsnzhYZsKByEdTpSJo` (kablosuz sensör ağlarında veri paketi boyutu, `tr`,
   25 dahil kaynak, kapsam modeli `codex` / `gpt-5.6-luna` / `medium`). Kopyada yeni bir tablo kurulur ve doldurulur; tablo kimliği
   tablo kurulunca doğar ve rapordan önceki tarihli `protocol.md` ekine yazılır (bu dosyaya girmez).
   - **Neden B:** 25 kaynaklı bir tablo R2'nin 30 iddiasını, R3'ün olumsuz cümlelerini ve R11'in kesilme kaydını anlamlı bir
     örnekle ölçer. Moleküler tablo (yol A, 5 satır, 35 hücre dolu) hazırdı ama küçüktür; onunla R2 tüm iddiaları okur ve payda
     küçük kalır. A'nın ölçümü değersiz olduğu söylenemez: küçük tabloda sıfır kesilme R11 için geçerli bir bulgudur. R6 ve R9
     her iki yolda da satırlarda PDF ve görüntülenen denklem bulunmasına bağlıdır; ikisi de "ölçülemedi" çıkabilir.
   - **Seçim kuralı (yukarıdaki genel kural):** 10–25 aktif satır, her aktif sütun dolu (`report_ready`), tam metni olan en az üç
     satır (yoksa R6 ve R9 baştan "ölçülemedi" kabul), seçim rapor çıktısı görülmeden yapıldı.
   - **Sütunlar, doldurmadan önce burada donar (8'den fazla olamaz; dokuzuncu sütun doldurma tavanını geçersiz kılar).**
     Sütun adları ve yönergeleri (Türkçe, `answer_format` parantezde) bu dosyanın donma commit'inde sabitlenir; koşu bunları
     kelimesi kelimesine kurar, sonradan değiştirmez:
     1. **Çalışma ortamı** (`choice`, çoklu seçim): "Kaynağın çalıştığı ortamı seçin; birden fazla ortam varsa hepsini işaretleyin;
        pasajlarda belirtilmemişse 'Belirtilmemiş' seçeneğini kullanın." Seçenekler: Karasal; Su altı; Yer altı; Vücut alanı;
        Akıllı şebeke; Diğer; Belirtilmemiş.
     2. **Yöntem** (`choice`, çoklu seçim): "Kaynağın kullandığı temel yöntemi seçin; birden fazla varsa hepsini işaretleyin;
        belirtilmemişse 'Belirtilmemiş' seçeneğini kullanın." Seçenekler: Analitik model; MIP/LP; Simülasyon; Deney; Diğer;
        Belirtilmemiş.
     3. **Karar değişkenleri** (`text`): "Modelde seçimi veya optimizasyonu yapılan karar değişkenlerini ve anlamlarını kaydedin;
        kaynak belirtmiyorsa bunu yazın."
     4. **Amaç fonksiyonu** (`text`): "Optimize edilen ya da değerlendirilen amacı kaydedin (ağ ömrü, enerji verimliliği, veri
        paketi boyutu vb.); birden fazla amaç varsa hepsini yazın; açıkça verilmemişse bunu belirtin."
     5. **Denklem** (`text`): "Kaynakta görüntülenen ana optimizasyon denklemini ya da amaç fonksiyonunu, pasajda verildiği
        gibi LaTeX ile yazın; pasajda görüntülenen denklem yoksa bunu belirtin."
     6. **İletim gücü ve ACK/yeniden iletim varsayımı** (`text`): "Kaynağın iletim gücüyle ortak optimizasyonu yapıp yapmadığını
        ve ACK ya da yeniden iletimle ilgili varsayımını kaydedin; pasajlarda yer almıyorsa bunu belirtin."
     7. **Paket boyutu sonucu** (`text`): "Kaynağın veri paketi boyutu için açıkça raporladığı başlıca sonucu ya da önerdiği değeri
        kısaca kaydedin; sonuç verilmemişse bunu belirtin."
     Sütun 5'in adında "Denklem" geçer; `measure.py` bu adı sayı ve denklem hücresi diye tanır.

2. **Kim işaretler: yalnız model okuması.** Koşu oturumundaki analist ilk okurdur (kör değil); ilk kararları ve bu dosyayı
   görmeyen ayrı bir Claude Sonnet oturumu ikinci okurdur. Sahip okumaz. Sonuç dosyasında her satır "model okuması" diye
   etiketlenir; "insan denetimi" diye anılmaz. İkinci okur şunları okur: (i) ilk okurun desteklemeyen bir işaret koyduğu her birim (R2 için `Kısmen` ve `Desteklemez`; R3, R4b, R6 ve R9 için olumsuz işaretler), (ii) kontrol örneği. **Kontrol örneği her ölçüt sayfası (R2, R3, R4b, R6, R9) için ayrı ayrı en çok 5 birimdir** (toplam 5 değil); ilk okurun destekleyen işaret koyduğu birimlerden (R2 için `Destekler`) sabit tohumla çekilir; bir sayfada 5'ten az varsa hepsi alınır. İkinci okur sayfasında iki tür birim, ayrı bir tohumla karıştırılmış tek sırada durur; hangisinin kontrol olduğunu ya da kaç kontrol bulunduğunu sayfa söylemez (kontrol kimlikleri ayrı bir dosyada tutulur). Birim, iki okurdan biri ciddi derse ciddidir; uyuşmazlık sayısı raporlanır. Bu düzen ilk okurun
   kaçırdığı hataları yalnız küçük bir kontrol örneğinde arar; bağımsız ve kapsamlı bir doğrulama değildir. İlk ya da ikinci
   okuma eksikse (işaretsiz birim, çift işaret, ilk okuma sayfasından silinmiş birim ya da kutu, ikinci sayfa yok ya da birim kimlikleri uyuşmuyor) kit sonuç üretmez. Koşu yarıda kaldıysa (durma, sınır, sayaç okunamadı) hiçbir okuma gerekmez: yalnız R1 ve R7 ölçülür (aşağıdaki durma kuralı).

3. **Oturum sınırı.**
   - **Rapor koşusu: 60 model oturumu ve 90 dakika.** Rapor koşusunun kendi çağrı bütçesi bugünkü kodda 50'dir
     (`REPORT_CALL_FLOOR`; formül `(1 + 10 + 1 + 10 + 1) × (1 + MAX_SCHEMA_REPAIRS)` = 46, 50 tabanı geçer). Bütçe her adımın
     başında denetlenir; aynı adımın hız sınırı yeniden gönderimleri denetimden sonra eklenir, yani 50 kesin bir üst sınır
     değildir ve oturum sayısı 50'yi biraz aşabilir (60'lık sınır bu payı taşır). Bütçe dolarsa koşu `budget_exhausted` ile
     durur.
   - **Doldurma koşusu: 60 model oturumu ve doldurma başlangıcından itibaren 60 dakika (bekleme ve kuyruk dahil), yalnız en
     çok 8 sütun için.** `tables.py` bütçeyi `2 × Σ ceil(sütun_sayısı / 8)` olarak hesaplar (`MAX_FILL_SOURCES = 25`,
     `MAX_COLUMNS_PER_CALL = 8`, `CALLS_PER_REQUEST = 2`): 25 metinli satır için 25 ilk çağrı ve 25 onarım, yani 50; 60 bu
     bütçeye yeniden gönderim payı ekler. Dokuzuncu sütun bütçeyi 100'e çıkarır; sütun sayısı 8'i geçerse bu sınır geçersizdir
     ve koşu başlamaz. Süre tavanı tamamlanma garantisi değildir (PDF işleme ya da eşzamanlılığın düşmesi süreyi uzatabilir);
     dolmuş bir tavan durmadır, yeniden başlatma değildir.
   - **İzleme bir sert sınır sağlamaz.** Oturum sayacı 15 saniyede bir okunur; iki okuma arasında uçuşta kalan çağrılar sınırı
     aşabilir. Bu yüzden sınırın aşılması durma sayılır, sonuç iptal edilmez, aşan oturumlar sayılır ve kaydedilir (koşu istemi).

## Durma kuralı ve koşu sayısı

- **Bir koşu.** Aynı araştırma ve tablo için bir rapor koşusu. Sonuç beğenilmediği ya da bir sağlayıcı hata verdiği için
  ikinci koşu yapılmaz. (Kesinti sonrası aynı koşunun sürdürülmesi ikinci koşu sayılmaz; kayıt edilir.)
- **Kota ya da yük.** Uygulama bir hız sınırı yanıtından sonra aynı adımı en çok iki kez kendisi yeniden gönderir
  (`MAX_RATE_LIMIT_MODEL_RETRIES`, eşzamanlılık sınırı düşürülerek); her gönderim ayrı bir model oturumudur ve oturum
  sınırına sayılır. Bu otomatik gönderimler tükendikten sonra koşu kota ya da yük nedeniyle durursa (`rate_limited`,
  `serverOverloaded`, duraklama nedeni kota): dur, dışarıdan yeniden başlatma ya da sürdürme yapılmaz. Başka bir modele ya da
  bağlantıya geçilmez. Kaç oturum yapıldığı, hangi bölümün bittiği kaydedilir.
- **`client_timeout`.** Bir kez, 10 dakika sonra sürdür (dilim 30 kuralı). İkinci kez olursa dur.
- **Başka her `model_call_failed`.** Dur.
- **Yarıda kalan koşu.** R1 (bitmiş bölüm sayısı) ve R7'ye (süre, çağrı) girer; R2–R6 ve R8–R11 ölçülmez, yarım metin üzerinden
  hesaplanmaz. Beklenti tablosunda "koşu yarıda kalırsa" ayrı bir sütun yoktur; yarıda kalma da bir sonuçtur ve karar kaydına
  nedeniyle yazılır.
- **Ara müdahale yok.** Koşu sürerken kimse hücre düzenlemez, PDF eklemez, bölüm yeniden yazdırmaz, planı düzeltmez.

## Okuma kuralı

Bu ölçüm bir kapı (gate) koymaz; "rapor geçti" ya da "kaldı" diye tek bir hüküm yoktur. Kural şudur:

1. Her satır üç durumdan birinde yazılır: **aralıkta**, **aralık dışında** ya da **ölçülemedi**. "Aralık dışında"
   beklentimin yanlış çıktığı anlamına gelir; ölçülen şeyin iyi ya da kötü olduğu ayrıca yorumlanır.
2. **Ölçülemedi**: payda sıfırsa ya da veri okunamadıysa (örneğin görüntülenen denklem yoksa R6, işaretlenmiş çift yoksa R9,
   olumsuz cümle yoksa R3). 0 ya da 1 yazılmaz. Bir sayı okunamıyorsa (arayüz ya da API göstermiyor) `okunamadı: <neden>`
   yazılır, tahmin yazılmaz.
3. Üç satır **sert** sayılır: R2 (yanlış atıf), R3 (yokluğun abartılması), R4a (`body_refs`'siz iddia). Bunlardan biri
   aralığın dışındaysa karar kaydı bunu ilk cümlede söyler ve raporun "olduğu gibi kullanılabilir" diye anılmaması gerektiğini
   yazar; sonraki dilimlerin (2, 3, 4) bu düzeltilmeden başlatılıp başlatılmayacağı sahibe bırakılır. Öbür satırların
   aralık dışına çıkması yorumlanır ama tek başına bu sonucu doğurmaz. (Bu sert-satır ayrımı benim kararımdır; planda
   yok.)
4. "Kısmen destekler" ve "yanlış" ayrı sayılır, toplanmaz. Örnek boyutu 30'dan küçükse (bütün iddialar okunmuşsa) payda
   yazılır ve oran yorumlanmaz, sayı yorumlanır.
5. Sonuç dosyası her satırda dört şeyi birlikte yazar: değer, payda, örnek (bütün mü, çekilmiş mi, tohum), okuyan.
6. Modeller hakkındaki hiçbir cümle, bu tek raporun dışına genellenmez.

## Beklenti tablosu

Aralıkların bir kısmı planın örnek sayılarıdır; hepsi bugünkü kodla karşılaştırıldı. Aşağıdaki "Kodla karşılaştırma"
sütunu neyin neden değiştiğini söyler. Deneyim olmayan yerde aralık geniş tutuldu.

| # | Ne ölçülür (kısa) | Beklenti | Kodla karşılaştırma | "Şunu görürsem varsayımım yanlış" |
|---|---|---|---|---|
| R1a | **İlk denemede geçerli bölüm / yazılan bölüm.** Yazılan: model adımı çalışan bölümler (III, IV, V, VI, VII, VIII, I, IX, abstract, index_terms = 10; II kod yazımıdır). İlk deneme: bölüm adımı ilk model çıktısında, şema onarım çağrısı ve cümle onarımı olmadan `valid` olmuş | 7 ile 10 arası, yani en az %70 (plan: en az %60) | Plan bunu kod yokken yazdı. Bugün bir bölüm yalnız iki nedenle `draft` olur: boş bölüm ya da VIII'in yasaklı iddiası; kalıp uyumsuzluğu bölümü düşürmez (istisna olur). Ölçüt gevşek olduğundan oran plandan yüksek beklenir. 18 Eylül ön koşularında (eski kod, 5 kaynak) 11 bölümün 9'u `valid`, ikisi `failed` çıktı | 5 ya da daha azı ilk denemede geçerliyse; ya da bölümlerin ikisinden fazlası `failed` (geçersiz model çıktısı) ise |
| R1b | Onarım ya da yeniden denemeden sonra geçerli / yazılan | Yazılan 10 bölümün en az 9'u `valid` | Bugünkü kodda bir bölümün kendi yeniden deneme döngüsü yoktur: şema onarımı adımın içindedir, cümle onarımı bir kez yapılır, `draft`/`failed` bölüm koşuyu durdurur ve sürdürme saklı adımı yeniden oynatır (P13, D121). Yani R1b bu ölçümde R1a'dan yalnız şema onarımı ve cümle onarımı kadar büyük olabilir | 8 ya da daha azı; ya da koşu bir bölüm yüzünden durduysa |
| R1c | Tamamlanmış (`valid`, `report_version` almış) rapor / başlatılan rapor | Tek koşu olduğundan bu bir oran değil, **1/1 ya da 0/1** olarak yazılır ve oran diye yorumlanmaz. Beklenti: 1/1 | 14 montaj kuralı bugün çalışıyor (P7, D116); 18 Eylül'ün ön koşuları A turundan sonra duraklamıştı. Rapor bu kez `valid` çıkabilir de çıkmayabilir de | Rapor `draft` ya da duraklamış kalırsa. Nedeni (hangi kural, hangi bölüm) kaydedilir |
| R2 | Yanlış atıf. Sabit tohumla, bölüm × destek türü × okuma derinliği katmanlarından çekilen 30 iddia; birim iddia-kayıt bağı (örneklenen iddianın her bağı ayrı işaretlenir); karar: destekler / kısmen / desteklemez. Payda: değerlendirilen bağ sayısı; ayrıca en az bir yanlış bağı olan iddia sayısı yazılır | En az bir yanlış (desteklemez) bağı olan iddia: 0 ile 3 arası (plan: 0–2); kısmen bağı olan iddia: en çok 8 | Atıf çapaları kod tarafından pasaj ya da hücre alıntısında birebir aranır (`anchor_match`); yanlış atıf ancak çapa yerinde ama cümle onu desteklemiyorsa çıkar. Örnek 30'dan küçükse hepsi okunur, payda yazılır | En az bir yanlış bağı olan iddia ≥ 4; ya da kısmen bağı olan iddia > 12; ya da desteklemeyen bir atıf `source_stated` türünde bir iddiada çıkarsa (kaynağın söylediği diye yazılıp kaynakta olmayan söz) |
| R3 | Yokluğun abartılması. Raporda olumsuz ve yokluk anlatan cümlelerin tümü (`not_found_in_inspected_scope`, "bildirmedi", "ele almadı", "incelenmedi", "yok", "no study", "did not" ve benzerleri; kit sözlükle bulur, okur eksik bulduğunu ekler); her biri dayandığı hücrelere karşı: kurala uygun / uygunsuz | N = "kurala uygun" ya da "uygunsuz" hükmü verilen olumsuz birim sayısı (kit bulguları ve okurun eklediği `M` birimleri; `no_evidence_given` hariç), U = uygunsuz sayısı. Aralıkta: U ≤ max(1, ⌊0,10 × N⌋) | §6 kuralını bugünkü montaj yalnız yapıda (`count`, üç-satır kuralı) denetler; anlamı `report_review` okur. Küçük bir tabloda olumsuz cümle sayısı az olabilir | U > max(1, ⌊0,10 × N⌋); ya da "hiçbir çalışma X'i ele almadı" biçiminde bir cümle VI ya da VII'de görünürse (bu cümle U'ya da girer); N = 0 ise ölçülemedi |
| R4a | Türetilmiş iddia, yapısal: `body_refs`'i olmayan Abstract/I/IX iddiası | 0 (kod tarafından zorunlu) | `assembly.py::_check_body_refs` (D116) bunu zaten zorlar | 0'dan fazlası: bu bir kural hatasıdır, ölçüm sonucu değil; ayrıca bir hata kaydı açılır |
| R4b | Anlamsal taşma: Abstract, I, IX iddialarından gövdeden güçlü yazılanlar / o bölümlerin bütün iddiaları | En çok %10 (payda küçük olacak: sayı olarak da yazılır) | Kod destek türü ve okuma derinliğini kalıtır, sözcük gücünü ("kanıtlar", "gösterir") denetlemez | %25'ten fazlası; ya da hiç iddia yoksa ölçülemedi |
| R5 | Terim tutarsızlığı: sözlük terimi başına metinde başka adla anıldığı yer sayısı; payda sözlük terimleri | Terim başına ortalama en çok 1 başka ad | Kod terimin geçişini arar, eşanlamlıyı bulamaz; kit yalnız kanonik terimin geçişlerini sayar, başka adı okur bulur | Terim başına ortalama ≥ 2; ya da bir terimde ≥ 4 başka ad |
| R6 | Denklem aktarımı: görüntülenen denklem başına özgün PDF sayfasıyla karşılaştırma (okur sayfayı açar; sayfa açılamıyorsa hüküm verilmez, `okunamadı`); hata türleri simge, indis, operatör, koşul/aralık, eksik parça; eşdeğer LaTeX yazımı hata değildir | Denklem sayısı 0 ile 6; en az 3 varsa yarısı (plan) sayfayla örtüşür. En olası sonuç: **ölçülemedi** (küçük tablo, az PDF, az `equation_origin`) | Denklem yalnız girdi pasajında görüntülenen denklem varsa yazılır, montaj köken pasajını ve iyi biçimi denetler; aktarım doğruluğunu denetlemez | En az 3 denklem var ve yarıdan azı örtüşüyorsa; ya da çoğunda simge/indis hatası varsa |
| R7 | Süre ve maliyet: uçtan uca süre; ardışık zincirin süresi; kuyruk ve kota beklemesi; çağrı ve token sayısı (onarım ve başarısız denemeler ayrı) | Süre 10 ile 30 dakika (plan aynı); model çağrısı 15 ile 46 (bütçe 50); ardışık çağrı 7 ile 13 | Bugünkü zincir: plan, tur 1 (III-IV-V eşzamanlı), VI, VII, VIII, tur 5 (I, IX, abstract, index_terms eşzamanlı), inceleme: en az 7 ardışık çağrı, her bölümde cümle onarımı çıkarsa 13'e kadar; başlık adımı yalnız araştırmanın başlığı yoksa çalışır. Bütçe formülü 46'yı verir, taban 50 olduğundan bütçe 50'dir. 1–3 dakikalık çağrı süresi D55'ten; rapor bölümleri hücre çıkarımından uzun girdi taşıyor, süre kestirimi belirsiz. Token için beklenti yok: yalnız kaydedilir | Süre 45 dakikayı geçerse; ya da 4 dakikanın altında biterse (bölümler hızla düşmüş demektir, R1'e bakılır); ya da çağrı sayısı 50'ye dayanırsa (`budget_exhausted`) |
| R8 | Kalıp: özgün cümle kimlikleri üzerinden ilk denemede uymayan / III–VII'nin bütün cümleleri; onarımdan sonra uyan; `reverted_exception` ve `unframed_exception` sayıları | İlk denemede uymayan: %30 ile %70 (plan: en çok %30); onarımdan sonra kalıpsız kalan (istisna dahil) en çok %25 (plan: %10); `reverted_exception` 0–2 | Plan, onarım kodu yokken yazıldı. 18 Eylül ön koşularında (onarımdan önce, 5 kaynak) bölüm başına 1–5 cümle kalıp dışıydı ve bölümler 2–8 cümleydi; bu, ilk denemede yarıya yakın uyumsuzluk demektir. Onarım en fazla bir kez yapılır, `unframed_exception` bölümü düşürmez | İlk denemede uymayan %20'nin altında (kalıp bankası sanılandan gevşek ya da model kalıba alışmış); ya da onarımdan sonra %40'tan fazlası kalıpsız (onarım işe yaramıyor); ya da `reverted_exception` ≥ 3 |
| R9 | Denklem kapsamı: koşudan önce işaretlenen (kaynak, formülasyon) çiftleri; girdide görüntülenen denklemi olan kaynaklar; her çift için raporda var mı ve pasajın verdiği parçalar (değişken, amaç, kısıt) eksiksiz mi | Çift işaretlenmişse: girdide denklemi olan çiftlerin en az yarısı raporda ve parçaları eksiksiz. Çift işaretlenmemişse ya da hiçbirinde girdi denklemi yoksa: **ölçülemedi** | Çiftler koşudan önce `protocol.md`'ye yazılır (tablodaki denklem sütunundan); rapor sonrası eklenemez. Denklem kuralı erişime değil girdide gözleme bağlıdır | Girdide denklemi olan çiftlerin yarısından azı raporda; ya da rapor tanımı olmayan bir simgeyi tamamlamışsa |
| R10 | İncelemenin yakalama oranı. **Bu dilimde ölçülmez.** Geçerli, saklanmış bir rapora hata ekilmedi ve ayrı inceleme/montaj sayımı yapılmadı. P15 önceden tamamlanmış sentetik davranış kanıtıdır; yardımcı bağlam olarak raporlanır (aşağıda). `flagged`, ekilen iddiada bulgu bulunduğunu gösterir; hatanın doğru teşhis edildiğini göstermez. P15 sonucu R10 beklenti aralığıyla karşılaştırılmaz | Aralık yok. Sonuç satırı her zaman "ölçülmedi" (`p15_behavior_is_not_r10`) yazılır | P15'in `results.json`'u (12 RS vakası, `report_review` adımı, keyword taraması) tek adım düzeyindedir; D123 bunun R10 olmadığını kaydeder. Gerçek çıktıda 12/12 `flagged`, 4 başka-iddia işareti, tüm `human_judgement` alanları boş ve montaj yakalaması ölçülmemiş | Yok: P15 sonucu koşudan önce biliniyordu ve ileriye dönük bir beklenti sınaması değildir |
| R11 | Sessiz eksik kanıt: kesilme kaydındaki kayıt sayısı ve `insufficient_evidence` sayısı; inceleyenin "bölümde olması gerekirdi" dediği, girdiye hiç verilmemiş pasaj sayısı | Kesilen kayıt: ≤ 10 kaynaklı tabloda 0, 25 kaynaklıda kesilenin verilen+kesilene oranı en çok %20; `insufficient_evidence`: 0 ile 3; "olması gerekirdi" en çok 2 | Kesilme kaydı bugün her bölümün `validation_json.truncated` alanındadır ve VIII'in sınırlamalar maddesinde sayı olarak görünür (P6, D115). Küçük tabloda kesilme olmayabilir; 0 bu durumda ölçülmüş bir sonuçtur, "ölçülemedi" değil | Herhangi bir bölümde kesilen oran %30'un üstündeyse; ya da inceleyen 3 ya da daha fazla "olması gerekirdi" bulursa |

Payda sıfırsa metrik "ölçülemedi" yazılır (§13). Yarıda kalan koşu R1 ve R7'ye girer, diğerlerine girmez.

## Okurun işi ve okunan örnek (kit ne üretir)

- `measure_report.py snapshot` bir `review.md` üretir: R2 için katmanlı 30 iddia (tohum sabit), R3 için bütün olumsuz cümleler,
  R4b için Abstract/I/IX iddiaları ve bağlı gövde iddiaları, R5 için sözlük terimleri, R6 için görüntülenen denklemler ve
  köken pasajı, R9 için çiftler, R11 için "olması gerekirdi" sayacı.
- `measure_report.py second` ilk okurun kararını göstermeden ikinci okurun sayfasını üretir (ilk okurun `desteklemez`,
  `kısmen`, `uygunsuz` dediği birimler ve tohumlu 5 diğer birim).
- `measure_report.py score` işaretlenmiş sayfaları ve, verilmişse, P15'in `results.json`'unu (gerçek biçim: `results` listesi, `case_id`, `automatic_checks.flagged`) ayrı bir `p15_behavior` kaydı olarak taşır; R10 satırı yine "ölçülmedi"dir; `results.json` içinde her satırın
  değerini, paydasını ve durumunu yazar. Aralıkları bu dosyadan almaz ve hüküm vermez; karşılaştırma sonuç dosyasında elle yapılır.
- Bir şeyi kodun bugün göstermediği yerde (örneğin bölüm başına şema onarımı sayısı) kit `okunamadı: <neden>` yazar.

## Kabul edilen sınırlar

- Tek araştırma, tek tablo, tek koşu, tek model; yeniden koşu yok.
- İki okur da modeldir (sahip okumazsa). R2 ve R3 için "insan denetimi" iddiası yoktur.
- R10 bu dilimde ölçülmez: geçerli, saklanmış bir rapora hata ekme ve ayrı inceleme/montaj sayımı yapılmamıştır. P15 önceden tamamlanmış sentetik davranış kanıtıdır; yardımcı bağlam olarak raporlanır. `flagged`, ekilen iddiada bulgu bulunmasını gösterir; hatanın doğru teşhis edildiğini göstermez. P15 sonucu R10 beklenti aralığıyla karşılaştırılmaz.
- Okunamayan kaynak metni: bir R2 bağının kaynak metni okunamıyorsa (ör. kütüphane kopyası okunamadı) o bağ `okunamadı` yazılır, destek hükmü istenmez, ikinci okumanın çekilişinden ve paydadan çıkar, ayrıca sayılır; bütün bağlar okunamıyorsa R2 `okunamadı`dır.
- Küçük örnekte (25 kaynak ve altı) kesilme, denklem ve çift ölçümleri boş çıkabilir; bu bir bulgudur, hata değil.
