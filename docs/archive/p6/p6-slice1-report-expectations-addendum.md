# P6 dilim 1 rapor ölçümü: beklentilere ek (ikinci deneme, koşudan önce donar)

**Tarih:** 30 Eylül 2026. **Durum:** DONDU, ikinci P16 denemesinden önce, hiçbir rapor koşusu başlamadan. İki gözden geçirme turu (gpt-6.1-sol, high; ek ve koşu istemi birlikte) yapıldı; ikinci tur "hazır" dedi. Bu ek, ikinci P16 denemesinden
önce, hiçbir rapor koşusu başlamadan donar. Donma anı, bu dosyanın tek bir commit'e girdiği andır (donma commit'i); ikinci deneme
o commit'ten sonra başlar. Rapor okunmadan önce bu dosyada hiçbir şey değişmez.

**Ana kural.** `p6-slice1-report-expectations.md` (sha256 `31f2666e…b25c7`, commit `cdf79ba`) **olduğu gibi durur ve düzenlenmez**.
Onun R1–R11 aralıkları, okur düzeni, durma kuralları ve okuma kuralı bu ekte **değiştirilmeden** taşınır. D124'ün sonucu da
(doldurma bitti, tablo `report_ready` değildi, rapor başlamadı, R1–R11 ölçülmedi) olduğu gibi durur. Değişen tek şey **başlangıç
koşuludur**: tablo tam dolu olmayacak; üç satırı kayıtlı bir başarısızlıkla eksik olan tabloyla, açık bir seçimle rapor yazılacak.
Bu, beklentileri sonuç bilindikten sonra oynamak değildir, çünkü **hiçbir rapor sonucu bilinmiyor**; bilinen şey doldurma sonucudur ve
aşağıda açıkça yazılıdır. Bilinen doldurma sonucuna göre hiçbir aralık ayarlanmadı; bir aralığın anlamının kaydığı yerler
"Aralıkların D125'e göre karşılaştırılması" bölümünde tek tek sayılır, hiçbir sayı değişmez.

## Ne ölçülür (değişen çerçeve)

Bugünkü `main`'in (`97faf6d`, D125 dahil) bir gerçek modelle (`gpt-5.6-luna`), bir araştırma (`res_IXBsnzhYZsKByEdTpSJo`) ve **bilinen doldurma
sonucuyla bir tablo** (`tbl_x8xnc1S4b7ha3WtIJDVU`) üzerinde yazdığı **tek** rapor. Sonuç şöyle sunulur: **"doldurma sonucu bilinen bir
tabloya koşullu ölçüm"**. Bu bir örnek üzerinde bir betimlemedir; "rapor türü geçti" ya da "kaldı" diye bir hüküm yoktur. Sonuç,
eksik satırlarla yazılmış bir raporun kalitesini ve genel olarak rapor türünü kanıtlamaz; tabloyu tam dolu ele alan bir ölçümün yerine geçmez.
Beklentilerin "Ne ölçülmez" bölümü aynen geçerlidir. Ek olarak ölçülmeyenler: başka bir eksik-satır örüntüsü, eksik satırların
rapora ne kadar zarar verdiği (rapor bu satırların dışındaki 22 satırla yazılır; dışlanan satırlar tabloda **kalır** ama içerik kanıtı olmaz).

## Bilinen doldurma sonucu (D124, ilk deneme; bu ekten önce bilinir)

- 25 dahil kaynak, yedi dondurulmuş sütun, 175 hücre; tek gerçek model doldurması (`run_snTalN2CcypRgMSK8SVc`, `gpt-5.6-luna`, 36 oturum,
  arka uç tamamlanmasına 3,3 dakika); 22 tamamlanmış satır, **3 başarısız satır**, **175 hücrenin 21'i eksik**.
- Üç başarısız kaynak ve nedenleri:
  1. `Nandi12` (`srv_f50KBd51bx2a3WXc4O9N`): saklı metin yok, erişim düzeyi `metadata`; 7 hücre `inaccessible` (`no_stored_text`).
  2. `Zaman20` (`srv_4e2Ih9Uf2SOJMGCpwr2u`): saklı metin yok, erişim düzeyi `metadata`; 7 hücre `inaccessible` (`no_stored_text`).
  3. `Sankarasub03` (`srv_IUBsxswhzFoCRiacU9Mn`): çıkarım adımı şema onarımından sonra başarısız; saklanan adım kodu ve D125'in `failed_rows.reason` değeri `invalid_model_output`, iç doğrulama nedeni `anchor_not_in_passage`; yedi hücrenin hiçbirinde revizyon yoktur.
- Hücre durumları: değer 129, `not_found_in_inspected_scope` 24, `unknown` 1, `inaccessible` 14, değersiz 7.
- Bu doldurmanın süresi ve oturum sayısı (36 oturum, 3,3 dakika) rapor rakamı **değildir**; R7'ye girmez.

## Başlangıç koşulu: ne değişir, ne değişmez

1. **Aynı 25 kaynak ve aynı yedi sütun.** Sütun adları ve yönergeleri, expectations dosyasındaki "Kararlar" madde 1'in kelimesi
   kelimesine aynısıdır; tabloya dokunulmaz.
2. **Yeniden doldurma yok, yeniden deneme yok.** Başarısız satırlar için ikinci bir çıkarım, PDF ekleme, kaynak çıkarma ya da hücre düzenleme
   yapılmaz. Tablo 25 kaynak, 3 başarısız satır, 21 eksik hücre olarak kalır. Doldurma tavanı yoktur, çünkü doldurma çalışmaz; kopyada
   yeni bir `table_fill` ya da `table_columns` koşusu ya da rapor koşusu dışında bir model çağrısı görünmesi ölçümün durmasıdır.
3. **Açık seçim.** Rapor `POST /api/researches/{id}/reports` ile `{"table_id": "tbl_x8xnc1S4b7ha3WtIJDVU", "continue_with_failed": true}`
   gövdesiyle başlatılır (D125; kod commit'i `97faf6d`). Bu alan varsayılan olarak `false`'tır; seçim, kullanıcının "Eksik satırlarla rapor yaz"
   demesinin API karşılığıdır. Ürün bunu yalnız bütün eksik hücreler kayıtlı bir başarısızlıktan geliyorsa ve en az bir satır tamamsa kabul eder;
   bu tablo iki koşulu da sağlar (`can_continue_with_failed` başlangıçta `true` görünmelidir). Ürün seçimi reddederse ölçüm başlamaz ve
   bu ekte tarif edilmeyen bir yol denenmez.
4. **Çalışma kopyası.** İkinci deneme, birinci denemenin doldurulmuş kütüphane kopyasının ([.local/p6-eval-2026-09-30/data/](../local-runs.md#run-p6-eval-2026-09-30)) **bir
   kopyası** üzerinde yürür; birinci denemenin klasörü ve verisi hiç değiştirilmez. Doldurulmuş durum korunur (aşağıdaki özet
   değerleriyle doğrulanır); bu kopyada hiçbir rapor, anlık görüntü ya da rapor koşusu yoktur.
5. **Kod farkı.** Ölçülen ürün `97faf6d`'dir (D125). Doldurma ve çapa anlamı D125'te değişmedi (`methods/` ve göç dosyaları aynı: `skill_package_hash`
   değişmez; göç 57'de kalır); değişen şey rapor yolu, anlık görüntü, II ve VIII ile ekrandır. Bu yüzden saklı hücre kanıtı yeniden üretilmeden
   kullanılır ve raporun kendi anlık görüntüsü yeni kodla alınır.
6. **Kit.** `scripts/p6_eval/measure_report.py` ve `tests/test_p6_measure_report.py` `cdf79ba`'dan beri değişmedi (sha256 önekleri
   `db203420e4b1`, `7f7d2f0d5004`) ve değişmeyecek; kit D125'in `failed_rows` alanını okumaz, bu yüzden aşağıdaki ek denetimler (dışlama sayısı, ürün notu, başarısızlık bildirimlerinin denetimi) elle yapılır.

## Başlangıç denetimleri (koşu istemi uygular; biri tutmazsa rapor başlamaz)

Denetimler bir `protocol2.md`'ye tarihli olarak yazılır, **rapor başlamadan önce**.

1. Kopya, birinci denemenin verisiyle aynıdır. Aşağıdaki özetler, kopyaya `python3` ile ve **salt okunur** açılarak (`mode=ro&immutable=1`) hesaplanır
   (betik koşu isteminde sabittir) ve birinci denemenin dosyasından bu ek yazılırken hesaplananlarla karşılaştırılır:
   - `library.sqlite` sha256 (sunucu başlamadan önce, kopya bayt bayt aynı olmalı) ve aşağıdaki özetler (`n` = satır sayısı, `sha256` = sıralı satırların JSON dökümü):

     | Özet | n | sha256 |
     |---|---|---|
     | `library.sqlite` (dosya) | | `d8c83eee2b008b50e7d3e1c379ce5d3d9779d494bc7511b766d7c2c542236db8` |
     | `quick_check` | 1 (`ok`) | `c96f5cb5ad0cbd290505f8ecd1ae9bdf0728327c6fdea7538371cbe606487d20` |
     | tablo satırları | 25 | `5be6979cb894744040cc030c2969befbb0a0f736a3bd1c273d78fd2ef8557c7f` |
     | sütunlar (ad, yönerge, biçim, seçenekler, güncel revizyon) | 7 | `7c1ea661f2747e4fe509d459a3c2b5b5bd69059327529c5d60077320531f6264` |
     | hücreler ve güncel revizyonları (durum, değer, okuma derinliği) | 175 | `d8c075b6ea26560669311af0408d5efc130ad10e9e1f4eb54e1b1dd3febc4253` |
     | hücre kanıt bağları | 219 | `8dea34edc3e6f9db997d10ff17e3384fdd86c9e6fcf33904c61df75f4c83a09f` |
     | tablodaki kaynakların pasajları | 1417 | `719699a815baf984857e82ad087c61682349503013048b056d5fc71f874aa3ba` |
     | dahil kaynaklar | 25 | `028a1aaa8e839c94f04c93b98d98e7fd72d27491c12e4c4139ae407b49e32e31` |

     Betik koşu isteminde sabittir (`digest.py`); göç sürümü 57, `reports` 0, araştırmanın `report` koşusu 0, etkin koşu 0 çıkmalıdır.
2. Sıfır rapor: `reports` tablosu 0 satır, araştırmanın `report` türü koşusu 0; etkin koşu (`queued`, `running`, `pause_requested`, `paused`) 0;
   bekleyen `person_pdf_requests` 0; `running` adım 0; etkin bir koşuya bağlı `pending` adım 0. Terminal koşulara bağlı 11 `pending` adım beklenendir (ikisi iptal edilmiş koşularda, dokuzu tamamlanmış doldurmada `read_equations`); bunlar listelenir ve dokunulmaz, kopya temizlenmez (işçi yalnız `queued` koşuları alır). Kopyadaki koşu sayıları türe göre yazılır; ölçümün sonunda tek fark bir `report` koşusudur.
3. Araştırma kapsamı `codex` / `gpt-5.6-luna` (`effort` medium), sunucu başladıktan sonra `GET /api/researches/{id}` ile de okunur.
4. `GET .../tables` tablo için şunu göstermelidir: `report_ready.ready` false, `cells_left` 21, `failed_rows` 3, `failed_cells` 21, `included_rows` 25,
   `can_continue_with_failed` true. Sayılardan biri farklıysa rapor başlamaz.
5. **Karma değerleri.** Koşu başında yazılır ve şunlarla karşılaştırılır: `skill_package_hash` `sha256:08f1bdeadc63b809bdf6d123a1e77889cada14d64d3e851c3d9fe25bfb2704ee`
   (kuru sunucu başlatmasından, boş veri klasörüyle; `methods/` D125'te değişmedi, birinci denemedekiyle aynı olmalı). `contracts/research/*.schema.json` dosyalarının
   sha256'sı `shasum -a 256` ile yazılır; tüm listenin sha256'sı `65df8e3cee9d755b295331614d66f659eaa1107ad830523eabe2f98a3891af32`
   olmalıdır (D125 `step-input.schema.json`'ı genişletti; bu liste D125 sonrasıdır, birinci denemedekiyle aynı değildir). İkisinden biri farklıysa rapor başlamaz.
6. Çalışma ağacı donma commit'ine sabitlenir; `git diff --stat 97faf6d <donma commit'i> -- backend apps/web contracts methods scripts tests` boş olmalı ve
   koşu boyunca ve sonunda boş kalmalıdır.
7. Rapor için R9 çiftleri (aşağıya bakın) `pairs.json`'a yazılmış olmalıdır.

## Rapor koşusu: sınırlar ve kurallar (taşınır)

- **Rapor: 60 model oturumu ve rapor isteğinden itibaren 90 dakika**, tıpkı beklentilerin "Oturum sınırı" maddesindeki gibi (bütçe 50, 60'lık sınır payı taşır;
  izleme sert sınır değildir; aşan oturumlar sayılır ve kaydedilir). Doldurma tavanı yoktur.
- **Bir rapor koşusu.** Birinci denemede hiçbir rapor koşusu başlamadığı için sayaç sıfırdan başlar ve **bir** rapor koşusu yapılır; sonuç beğenilmezse ya da bir sağlayıcı
  hata verirse ikinci koşu yapılmaz. Aynı koşunun kesinti sonrası sürdürülmesi ikinci koşu sayılmaz, kayıt edilir.
- **Durma kuralları aynen geçerli:** kota ya da yük nedeniyle durursa dur, dışarıdan yeniden başlatma ya da başka bir modele geçiş yok; `client_timeout` bir kez 10 dakika sonra
  sürdürülür, ikincisinde dur; başka her `model_call_failed` durdurur; sayaç okunamazsa dur. Durmuş koşu yalnız R1 ve R7'ye girer (`snapshot --stopped`).
  Ara müdahale yok: hücre düzenlenmez, PDF eklenmez, satır çıkarılmaz, bölüm yeniden yazdırılmaz.
- **Okurlar:** ilk okur koşuyu yürüten analist (kör değil; ikinci denemenin analisti birincinin analistinden farklı bir oturumdur, ama D125'i ve doldurma sonucunu bilir),
  ikinci okur bu eki, ilk kararları ve beklentileri görmeyen ayrı bir Claude Sonnet oturumudur. Sahip okumaz. Bütün okumalar "model okuması"dır.
  Kontrol örneği, çift işaret ve eksik okuma kuralları expectations'taki gibidir.

## R9 çiftleri (rapordan önce)

Koşu isteminin R9 adımı gereği çiftler, rapor başlamadan **önce** tablonun "Denklem" sütunundan işaretlenir ve bir daha değişmez (`pairs.json`,
`[{"source_key","formulation"}]`). Yeni kural: çift yalnız **tamamlanmış** 22 satırdan seçilir; `Nandi12`, `Zaman20` ve `Sankarasub03` çift olamaz
(bu satırların hücreleri rapor girdisine verilmez, R9 ölçümü bu kaynaklar için zaten anlamsız olur). Çift bulunmazsa R9 "ölçülemedi"dir, expectations'taki gibi.

## Aralıkların D125'e göre karşılaştırılması

Her satır expectations'taki aralıkla **aynıdır**. "Aynı sayı, aynı anlam" olmayan yerler burada, koşudan önce yazılır. Hiçbir sayı değişmedi.

| # | D125'in etkisi | Aralık | Anlam kayması ve ek kural |
|---|---|---|---|
| R1a, R1b, R1c | II kod yazımıdır (R1'in 10 model bölümüne girmez). VIII'in girdisine sekizinci madde eklenir (başarısız kaynaklar, nedenleriyle) | aynı | Sayı ve payda aynı. VIII bölümünün `draft` olma riski bir madde kadar artmış olabilir; VIII `draft` ya da `failed` olursa nedeni (sekizinci madde ile ilgili mi) kayda yazılır. Aralık gevşetilmez |
| R2 | Başarısız satırların hücreleri anlık görüntüde yoktur, iddiaların atıfları bu satırlara gidemez | aynı | Aralık ve payda aynı. **Ek denetim (aralık değil):** raporun herhangi bir iddiasının, atıf bağının, kaynakçasının, boşluk dayanağının ya da denklem kökeninin üç başarısız kaynaktan birinin pasajını ya da hücresini içerik kanıtı, atıf, toplulaştırma üyesi veya boşluk dayanağı olarak kullanması D125'in dışlamasında bir kural hatasıdır; sayısı ayrıca yazılır, R2'ye girmez (R4a gibi: ölçüm sonucu değil, hata kaydı). Bu sayıma girmeyenler: Tablo I'de üç satırın `failed` işaretiyle görünmesi (anlık görüntü hepsini `rows`ta tutar), II ve VIII'in operasyonel başarısızlık bildirimleri ve `missing_rows` listesi |
| R3 | II ve VIII'in kodla yazılan `draft.text` bildirimlerini (II'nin eksik-satır cümlesi, VIII'in sekizinci maddesi) kit taramaz; kit yalnız iddiaları ve `insufficient_evidence` kayıtlarını tarar. Başarısız satırların hücreleri anlık görüntüde olmadığından, salt başarısızlığı anlatan bir birimin hücre temeli yoktur | aynı: U ≤ max(1, ⌊0,10 × N⌋) | **Anlam kayması yok, ana hesap donmuş tanımla aynıdır:** hücre temeli olmayan (`no_evidence_given`) birimler N ve U'ya girmez; kitin çıktısı değiştirilmez, hücre kimliği ya da değeri uydurulmaz. **Ek denetim (aralık değil):** salt doldurma başarısızlığını anlatan bildirimler, saklı `failed_rows` kayıtlarına karşı ayrı bir ürün denetiminde değerlendirilir (`manual_checks.md`): satırın tamamlanmadığını ve dışlandığını söyleyen bildirim uygundur; başarısızlığı kaynakta yokluk iddiasına çeviren (“belirtilmemiş”, “kaynak ele almadı”, “bulunamadı” gibi) bildirim hata olarak ayrıca yazılır. Bu ek denetim R3'ün paydasını ya da aralık hükmünü değiştirmez |
| R4a, R4b | II'nin ek cümlesi ve VIII'in sekizinci maddesi kodla yazılan `draft.text` bildirimleridir; `claim_key` kimlikleri yoktur, doğrudan `body_refs` hedefi olmazlar ve gövde iddiası özetlerine girmezler | aynı | R4a ve R4b, saklanmış gerçek iddialar ve onların `body_refs` bağları üzerinden, eski tanım ve paydalarla ölçülür; payda küçük kalır, sayı olarak da yazılır |
| R5 | Sözlük planı 22 tamamlanmış satırdan; başarısız satırların pasajları plan girdisine girmez | aynı | Anlam aynı; terim başına ortalama, aynı sözlükle |
| R6 | Başarısız satırların denklem hücreleri model girdisine verilmez | aynı | Anlam aynı. Kitin ham denklem listesi değiştirilmez ve başarısız kaynağa göre süzülmez. Başarısız kaynağa bağlanan bir denklem görülürse D125 dışlama hatası olarak ayrıca kaydedilir; denklem sessizce R6 paydasından çıkarılarak yeni bir aralık hükmü üretilmez |
| R7 | `freeze_plan` kaynak sayısı olarak 25 yerine 22 alır; ikisi de en az 10 olduğundan toplam kelime bütçesi (5500) ve bölüm bütçeleri değişmez; çağrı zinciri aynı | aynı | **Anlam kayması yok, ama ayrım kuralı:** R7, yalnız rapor koşusunun süresi ve çağrısıdır. Birinci denemedeki doldurmanın 36 oturumu ve 3,3 dakikası R7'ye **eklenmez**, ayrı bir “bağlam” satırında yazılır. Rapor koşusunun süresi koşunun kendi `created_at`/`updated_at` alanlarından okunur |
| R8 | III–VII model yazımıdır; II ve VIII'in sekizinci maddesi kod ve girdi yazımıdır, kalıp sayımına girmez | aynı | Anlam aynı |
| R9 | Yalnız tamamlanmış satırlardan çift | aynı | Yukarıdaki "R9 çiftleri" kuralı; başka kayma yok |
| R10 | Yok | ölçülmez | Hâlâ "ölçülmedi" (`p15_behavior_is_not_r10`); P15 yardımcı bağlamdır ve R10 aralığıyla karşılaştırılmaz |
| R11 | Başarısız satırların pasajları ve hücreleri bölümlere hiç verilmez | aynı | **Anlam kayması:** başlangıçta bilinen üç eksik satır bağlam **kesilmesi sayılmaz**: `truncated` kayıtları yalnız kesilme kaydından okunur, eksik satırlar hem "kesilen" hem "verilen" paydasından dışta kalır. 25 kaynaklı tablo sınıfı (kesilenin verilen+kesilene oranı en çok %20) uygulanır, çünkü dahil kaynak 25'tir; payda tamamlanmış 22 satırın kayıtlarıdır. "Bölümde olması gerekirdi" sayacında inceleyen, üç başarısız kaynağın pasajlarını **saymaz** (bunlar bilerek verilmemiştir); onun dışındaki eksik pasaj sayılır. `insufficient_evidence` kayıtlarının tamamı kitin ham sayımında korunur ve aynı 0–3 aralığıyla karşılaştırılır. Başarısızlığın bildirilmesi tek başına D125 dışlama hatası değildir (VIII bu bilgiyi özellikle alır); başarısız kaynağın pasajının ya da hücresinin içerik kanıtı, atıf, toplulaştırma üyesi ya da boşluk dayanağı olarak kullanılması ihlaldir ve R2 satırındaki ek denetimde sayılır |

Ürün notu (aralık değil, yalnız kayıt): raporun görünümünde `missing_rows` ve Markdown dışa aktarımında başlık ve rapor sürümü satırının hemen ardından eksik-satır notu var mı, VIII'in sekizinci maddesi üç
kaynağı adıyla ve nedenleriyle sayıyor mu, II 25 dahil, 22 tamamlanmış, 3 başarısız ve 21/175 eksik hücreyi ayrı yazıyor mu: "evet/hayır" olarak sonuç dosyasında yazılır,
bir ölçüt satırı değildir.

## Okuma kuralı ve sonuç sunumu (taşınır)

Expectations'taki "Okuma kuralı" aynen geçerlidir: her satır "aralıkta", "aralık dışında" ya da "ölçülemedi"; sert satırlar R2, R3, R4a; her satırda değer, payda, örnek ve
okuyan; modeller hakkındaki hiçbir cümle bu tek rapora dışında genellenmez. Sonuç dosyası ilk paragrafta üç şeyi söyler: bu bir tek araştırma, tek tablo, tek koşu, tek
model ölçümüdür; tablonun doldurma sonucu (3 başarısız satır) rapor başlamadan önce bilinirdi ve rapor bu satırlar dışlanarak yazıldı; sonuç "doldurma sonucu bilinen bir
tabloya koşullu ölçüm"dür. Sonuç, birinci denemenin sonucunun (D124) yerine geçmez; yanına yazılır.

## Bu ekin sınırları

- Bu ek, D125'in çalıştığını göstermez; D125 sentetik sahte ve betikli modellerle sınandı. Bu ölçüm, gerçek model altında tek bir kez, ürünün eksik satırlı yolunu görecek,
  ama başka bir tabloda ya da başka bir model altında ne olacağını söylemeyecektir.
- Analist, D125'in tasarımını ve doldurma sonucunu bilir; kör değildir. Bu, ilk okurun tarafsızlığını sınırlar; ikinci okurun körlüğü bunu yalnız kontrol örneğinde dengeler.
- Kitin ürettiği R2–R11 çıktıları D125'in yeni alanlarını okumaz; ek denetimler (dışlama hatası sayısı, ürün notu, başarısızlık bildirimlerinin `failed_rows`'a karşı denetimi) elle yapılır, kit dışıdır ve ana R-satırlarının paydasını değiştirmez.
- Birinci denemenin klasörü ([.local/p6-eval-2026-09-30/](../local-runs.md#run-p6-eval-2026-09-30)) ve bu ekin ölçüm araçları değişmez; ikinci deneme kendi klasörünü ([.local/p6-eval-2026-09-30-run2/](../local-runs.md#run-p6-eval-2026-09-30-run2)) kullanır.

## Gözden geçirme kaydı

- **Tur 1** (gpt-6.1-sol, high, salt okunur; ek ve koşu istemi): 3 high, 4 medium, 2 low; hükmü "hazır değil". High bulgular: R3'ün ana paydasına kitin taramadığı ve hücre temeli olmayan başarısızlık bildirimlerini katmak donmuş tanımı değiştirirdi (düzeltme: ana R3 hesabı donmuş kit tanımıyla kalır, başarısızlık bildirimleri `failed_rows`'a karşı ayrı denetimdir); doğrulanmış kopyada 11 `pending` adım vardı (terminal koşulara bağlı), "sıfır bekleyen adım" koşulu kopyayı reddederdi (düzeltme: bunlar beklenen, listelenir, dokunulmaz); kopya hedefinin yeni ve bağımsız olduğu doğrulanmıyordu (düzeltme: `$RUN2` var olmamalı, `mkdir` `-p`siz, sembolik bağ ve SQLite yan dosyası denetimi). Medium: R4 satırı (II ve VIII bildirimleri `body_refs` hedefi değildir), R6 (ham liste süzülmez), R11 (başarısızlığı bildirmek ihlal değildir), erken durma yolu (`not_readable`, `snapshot --stopped`); low: R7 kelime bütçesi 22 ve 25 için aynı (5500), Sankarasub03'ün saklanan hata kodu `invalid_model_output`. Dokuz bulgunun hepsi uygulandı.
- **Tur 2**: 0 high, 1 medium (sonuç commit'i ana kopyada yapılır, ölçüm ağacı detached kalır ve `main`de tutulduğu doğrulanmadan kaldırılmaz), 1 low (Markdown notu başlık ve sürüm satırından sonra gelir); ikisi de uygulandı. Hüküm: "hazır". Kod, bütün özetler ve karmalar, Sol tarafından yeniden hesaplanarak doğrulandı.
