# P6 dilim 1 rapor ölçümü: beklentilere ikinci ek (üçüncü ve son deneme, koşudan önce donar)

**Tarih:** 30 Eylül 2026. **Durum:** DONDU (dört gözden geçirme turu, gpt-6.1-sol high; 4. tur "hazır"). Donma anı, bu dosyanın tek bir commit'e girdiği andır (donma commit'i); üçüncü deneme o commit'ten sonra
başlar. Bu ek, üçüncü P16 denemesinden önce, hiçbir yeni rapor koşusu başlamadan donar. Rapor okunmadan önce bu dosyada hiçbir şey değişmez.

**Ana kural.** Üç dosya **olduğu gibi durur ve düzenlenmez**: `p6-slice1-report-expectations.md` (sha256 `31f2666e…b25c7`, commit `cdf79ba`),
`p6-slice1-report-expectations-addendum.md` (sha256 `4770f1a6…58ce9`, donma commit'i `15bb131`) ve iki sonuç dosyası (`p6-slice1-report-results.md`, D124;
`p6-slice1-report-results-run2.md`, D126). R1–R11 aralıkları, okur düzeni, durma kuralları, okuma kuralı, başarısız satırlarla yazma seçimi ve ilk ekin
D125 karşılaştırma tablosu bu ekte **değiştirilmeden** taşınır. Bu ek yalnız dört şeyi yazar: üçüncü denemenin **son** olduğu kuralı, değişen ürün (`14a6e6f`, D127),
yeni başlangıç karmaları ve D127'nin bir aralığın anlamını kaydırdığı yerler. **Hiçbir aralık, payda ya da eşik değişmedi.**

## Neden üçüncü deneme, ve sonuç zaten bilindiği için ne değişmemeli

İkinci deneme (D126) bölüm IV'te durdu: model bir pasaj kimliğini iki karakter eksik kopyaladı, tek şema onarımından sonra da aynı hata sürdü (`unknown_passage_id`).
Yalnız R1 (0/3, 2/3, 0/1) ve R7 (3,7 dakika, 7 çağrı) ölçüldü; R2–R6, R8, R9, R11 "ölçülemedi" kaldı. Bu sonuç **bilinir** ve bu ekin yazılmasına yol açtı.
Ürün, sonuç görüldükten sonra değişti: `14a6e6f` (D127) dört rapor adımında uzun kimlikler yerine adım başına kısa tutamaçlar gösterir ve model çıktısındaki kimlikleri doğrulamadan önce
gerçek kimliğe çevirir. Bu, beklentileri sonuç bilindikten sonra oynamak **olmamalıdır**; bu yüzden:

- Hiçbir aralık, payda, eşik, okuma kuralı ya da sert satır tanımı D126'nın sonucuna göre ayarlanmadı. R1a'nın "7 ile 10" aralığı, ikinci denemenin 0/3 sonucundan sonra da aynıdır.
- Ürün değişikliğinin hangi aralığın anlamını kaydırdığı aşağıda tek tek yazılır; kaydırmayan satır "kayma yok" diye yazılır.
- Önceden açık bir karar olması (Claude ve gpt-6.1-sol, `/Users/huguryildiz/.claude/plans/p18-report-handles-sol-scope.md`) gerekçeyi güçlendirir, ama sonuç görüldükten sonra ürünü
  değiştirme riskini ortadan kaldırmaz: bu ölçüm bağımsız bir ileriye dönük sınama değildir.
- D124 ve D126 aynen kalır. Sonuç sunulurken önceki duruşlar gizlenmez; üç deneme yan yana yazılır (aşağıda "Okuma kuralı ve sonuç sunumu").

## Son deneme kuralı (kelimesi kelimesine)

> **Üçüncü P16 girişimi bu ölçüm dizisinin son girişimidir; yalnız bir yeni rapor koşusu açılır. Yalnız `client_timeout` için mevcut tek sürdürme hakkı uygulanır. Başka duruşta müdahale veya dördüncü girişim yapılmaz; tamamlanmaya bağlı ölçütler ‘ölçülemedi’ olarak kapanır, elde edilen R1/R7 korunur.**

Bu kural ilk ekin "bir rapor koşusu" ve "durma kuralları" maddelerinin yerine geçmez, onları **sıkılaştırmadan tamamlar**: bölüm başarısızlığı, `section_failed` duraklaması, kota ya da
yük duruşu, sayaç hatası ve başka her `model_call_failed` için ürünün kendi sürdürmesi de kullanılmaz (ürünün sürdürmesi saklı adımı yeniden oynatır; bu, ara müdahaledir). **Durma nedeni, dış `pause_reason` koduna değil,
saklı adım ve oturum hata kayıtlarının kök nedenine göre belirlenir:** bir bölüm çağrısındaki zaman aşımı önce `model_call_failed` olarak kaydedilir, sonra koşu dışarıdan `section_failed` ile duraklar. Dış kod `section_failed` olsa da bütün
durma nedenleri yalnız `client_timeout` ise, sürdürme hakkı kullanılmamışsa ve oturum ve süre tavanları aşılmamışsa aynı koşu 10 dakika sonra bir kez sürdürülür; başka ya da karışık neden varsa (örneğin `unknown_passage_id`) sürdürülmez.
**İzleme yalnız koşunun üst durumuna bakmaz:** her poll'da ve son değerlendirmede rapor koşusunun adım ve oturum hata kayıtları, bölüm doğrulamaları ve `review.reason` da okunur; durma kuralına giren bir çağrı hatası (kalıp onarımı ya da son inceleme adımında
ürün durmayıp devam etmiş ya da tamamlanmış olsa bile) `snapshot --stopped <neden>` ile değerlendirilir ve okurlar başlatılmaz; izinli şema onarımları ve yapısal kalıp istisnaları sağlayıcı çağrı hatasıyla karıştırılmaz. **Kayıtların sabitlenmesi:** izinli `client_timeout` sürdürmesinin dışında bir durma nedeni saptandığında koşu hâlâ çalışıyorsa, yalnız ölçümü sonlandırmak için API üzerinden iptal edilir (zaten duraklamış ya da terminal bir koşunun durumu korunur). Bu iptal onarım, yeniden deneme ya da bölümü yeniden yazdırma değildir. **Sabitlenme, saklı adımların `running` etiketinden çıkmasıyla tanımlanmaz** (hız sınırı ya da iptal yolunda ürün bir adımı `running` bırakabilir). Koşu başlamadan kurulan ve ürün dosyalarını değiştirmeyen ölçüm gözlemcisi (koşu betiği) rapor yürütmesinin durduğunu ve dönüş anını kaydeder; bu kayıt ve `model_sessions.status='started'` sayısının sıfır olması doğrulandıktan sonra nihai sayaç ve hata kayıtları yeniden okunur ve tek `snapshot --stopped <neden>` ile `score` alınır; okurlar başlatılmaz. Kalıcı `running` adım ya da bölüm kayıtları değiştirilmeden ayrıca kaydedilir. Yürütmenin bittiği doğrulanamıyorsa (örneğin başlamış oturum sınırlı bir beklemeden sonra da sürüyorsa) "nihai durum" iddiası kurulmaz ve R1/R7 "kayıt anındaki durum" diye etiketlenir. R7'nin ana süresi donmuş tanımla `created_at`/`updated_at` üzerinden korunur; iptal yolunda bu, iptal kaydına kadar olan süredir; durma nedeninin saptanması, iptal ve son oturumun bitişi ek kayıtta ayrı gösterilir ve kapanış beklemesi ana R7'ye eklenmez.
Koşu durursa `snapshot --stopped <neden>` ve `score` çalışır, hiçbir okur başlamaz, R2–R6, R8, R9, R11 "ölçülemedi" yazılır, R1 ve R7 elde edilen değerle korunur, sonuç ve neden karar kaydına
yazılır. Dördüncü girişim, sonuç beğenilmese bile, bu ekle kapalıdır; yeni bir girişim ancak sahibin ayrı ve açık bir kararıyla, yeni bir ekle ve yeni bir ölçüm olarak açılabilir.

## Ne ölçülür (değişen çerçeve)

`14a6e6f`'nin (D127 dahil) bir gerçek modelle (`gpt-5.6-luna`), bir araştırma (`res_IXBsnzhYZsKByEdTpSJo`) ve bilinen doldurma sonucuyla bir tablo
(`tbl_x8xnc1S4b7ha3WtIJDVU`) üzerinde, `continue_with_failed` seçimiyle yazdığı **tek yeni** rapor. Sonuç şöyle kaydedilir ve başka türlü anılmaz:
**"gözlenen başarısızlık sonrası düzeltilmiş üründe, aynı bilinen korpusa koşullu geliştirme ölçümü"**. Bu bir örnek üzerinde bir betimlemedir; "rapor türü geçti" ya da "kaldı"
diye bir hüküm yoktur. Ek sınırlar:

- **Üç girişim üç rapor koşusu değildir.** İlk girişimde rapor hiç başlamadı (D124), ikincide bir rapor koşusu üç bölümde durdu (D126), üçüncüde ikinci bir rapor koşusu açılır. Sonuç
  dosyası "üç rapor koşusu" ya da "üç denemede bir tane geçti" gibi bir sayım yazmaz; üç girişimi ayrı ayrı, ne olduysa o biçimde yazar.
- **Başarı görülürse** yalnız şu gösterilmiş olur: bu örnekte, bu tabloda, bu modelle, düzeltilmiş ürün raporu sonuna kadar yazabildi. Bu, tutamaçların nedensel etkisini (ikinci
  koşudaki hatanın tutamaç yüzünden kalkıp kalkmadığını: model çıktısı her koşuda değişir) **göstermez**, raporun genel kalitesini ya da başka bir korpusta, modelde ya da tabloda davranışı
  göstermez. Bunlar bağımsız bir korpusta ayrıca sınanmalıdır.
- **Başarısızlık görülürse** o da tek koşudur; oran değildir ve önceki duruş (D126) ile birleştirilip bir "hata oranı" yazılmaz.
- Beklentilerin "Ne ölçülmez" bölümü ve ilk ekin "Ne ölçülür" bölümündeki ölçülmeyenler aynen geçerlidir. Bu koşu ayrıca **aynı bilinen korpusa** koşulludur: kaynaklar, tablo, üç başarısız satır ve
  ikinci koşudaki III ile V bölümlerinin içeriği analistçe bilinir (kör değil).

## Bilinen sonuçlar (bu ekten önce bilinir)

- D124, ilk deneme: 25 dahil kaynak, yedi sütun, 175 hücre; 22 tamamlanmış satır, 3 başarısız satır (`Nandi12`, `Zaman20`, `Sankarasub03`), 21 eksik hücre; rapor başlamadı. Ayrıntı: ilk ekin "Bilinen doldurma sonucu" bölümü.
- D126, ikinci deneme: `continue_with_failed` ile bir rapor koşusu (`run_wODL7ceeQPzODt2ncqnh`, `rpt_ZV6m44jBsiIlIUHoE7Hy`), `97faf6d` ürünüyle; 3,7 dakika, 7 oturum; III ve V geçerli (her biri bir cümle onarımıyla), IV `unknown_passage_id` (iki karakter eksik kopyalanmış pasaj kimliği, şema onarımından sonra da) ile başarısız; koşu `section_failed` ile duraklamış, sürdürülmedi. R1 0/3, 2/3, 0/1; R7 3,71 dakika, 7 çağrı, 189.969 jeton (kısmi koşu); R2–R6, R8, R9, R11 ölçülemedi; D125 dışlama sayısı (III ve V'te 18 iddia, 35 bağ) 0.
- Bu değerler üçüncü koşuya **ön bilgi** olarak girmez: hiçbir aralık onlara göre ayarlanmadı, D126'nın R7 jeton sayısı (kısmi koşu) üçüncü koşunun jeton sayısıyla karşılaştırılmaz.

## Ürün farkı (dondurulur)

Ölçülen ürün `14a6e6f`'dir (`main`, D127, P18). İkinci denemenin ürünü `97faf6d` ve donma commit'i `15bb131` idi. `git diff --stat 15bb131 14a6e6f -- backend apps/web contracts methods scripts tests` yalnız şu
sekiz dosyayı gösterir (başka dosya yok; `apps/web`, `contracts`, `scripts` ve göç dosyaları **boş fark**); bu farkın `git diff 15bb131 14a6e6f -- backend apps/web contracts methods scripts tests | shasum -a 256`
değeri `4185cb2db05d79bc0566cbbfb330f29836fb98ffa4c27eb8490001f863e95413`'tür:

| Dosya | Fark |
|---|---|
| `backend/deixis/domain/contracts.py` | 135 satır değişti, rapor görevleri için alan bazlı tutamaç eşlemesi, çıktı kimliği çözme, bölüm çıktısı kimlik üyelik denetimi |
| `backend/deixis/workflow/flow.py` | 6 satır: `HANDLE_TASKS` ve çıktı çözme yoluna `REPORT_TASKS` |
| `methods/deixis-research/references/report.md` | +3 satır: tam kopyalama ve izinli kimlik kuralı |
| `methods/deixis-research/provenance.json` | 1 satır: P18 kaydı |
| `tests/test_report_handles.py` (yeni), `tests/test_contracts.py`, `tests/test_report_step_input.py`, `tests/test_report_failed_rows.py` | test eklemeleri ve üç var olan testin beklentisi |

- **`skill_package_hash`:** `sha256:52775258f530aa6a51513488f2aea37d0b7e609ffebe23d06451fd8ef0ae81ac` (önceki: `sha256:08f1bdeadc63b809bdf6d123a1e77889cada14d64d3e851c3d9fe25bfb2704ee`; `report.md` değiştiği için hareket etti). Bu ek yazılırken
  `14a6e6f` ağacında `deixis.domain.skill.package_hash()` ile yeniden hesaplandı ve eşleşti; koşu yine boş veri klasörüyle kuru bir sunucu başlatmasından okur ve karşılaştırır.
- **Şema ve kit:** `contracts/research/*.schema.json` dosyalarında fark yok; `shasum -a 256` listesinin sha256'sı **`65df8e3cee9d755b295331614d66f659eaa1107ad830523eabe2f98a3891af32`** (ikinci denemedekiyle aynı). `scripts/p6_eval/measure_report.py` (`db203420e4b1…`)
  ve `tests/test_p6_measure_report.py` (`7f7d2f0d5004…`) `cdf79ba`'dan beri değişmedi ve değişmeyecek; kit D127'nin yeni davranışını okumaz (tutamaçlı ham mesajlar ve ham çıktı kit dışıdır).
- **Göç:** yok, 57'de kalır.
- **Beklenti dosyası:** sha256 `31f2666e8f3b15b4b627a6e400f9b983759ae71be484ee6731b55281826b25c7`; ilk ek: `4770f1a6c4da61ff7055e1f00c2e91847f1533c4bb072b47be43f4a97c658ce9`.
- Çalışma ağacı donma commit'ine sabitlenir; `git diff --stat 14a6e6f <donma commit'i> -- backend apps/web contracts methods scripts tests` **boş** olmalı ve koşu boyunca ve sonunda boş kalmalıdır.
  Donma commit'i yalnız dokümantasyondur ve `14a6e6f`'nin torunudur (`git merge-base --is-ancestor 14a6e6f <donma commit'i>`).

## Başlangıç koşulu: ne değişir, ne değişmez

1. **Aynı 25 kaynak, aynı yedi sütun, aynı tablo.** Sütun adları ve yönergeleri beklentilerin "Kararlar" madde 1'inin kelimesi kelimesine aynısıdır.
2. **Yeniden doldurma yok, yeniden deneme yok.** İlk ekin başlangıç koşulu madde 2 aynen geçerlidir: tablo 25 kaynak, 3 başarısız satır, 21 eksik hücre olarak kalır; kopyada yeni bir `table_fill` ya da
   `table_columns` koşusu ya da rapor koşusu dışında bir model çağrısı ölçümün durmasıdır.
3. **Açık seçim:** `POST /api/researches/{id}/reports` gövdesi `{"table_id": "tbl_x8xnc1S4b7ha3WtIJDVU", "continue_with_failed": true}`; `can_continue_with_failed` başlangıçta `true` görünmelidir. Ürün reddederse ölçüm başlamaz.
4. **Yeni, bağımsız kopya, birinci denemenin raporsuz kopyasından.** Kaynak, birinci denemenin doldurulmuş kütüphane kopyasıdır: [.local/p6-eval-2026-09-30/data/](../local-runs.md#run-p6-eval-2026-09-30) (sha256 `library.sqlite` = `d8c83eee2b008b50e7d3e1c379ce5d3d9779d494bc7511b766d7c2c542236db8`;
   bu dosyada hiçbir rapor, anlık görüntü ya da rapor koşusu yoktur). Hedef [.local/p6-eval-2026-09-30-run3/data/](../local-runs.md#run-p6-eval-2026-09-30-run3)'dır. **İkinci denemenin klasörü ([.local/p6-eval-2026-09-30-run2/](../local-runs.md#run-p6-eval-2026-09-30-run2)) ve verisi kaynak değildir**: içinde D126'nın `paused` rapor
   koşusu, taslak bölümler ve bir anlık görüntü vardır; temizlenmez, yeniden kullanılmaz, yazılmaz. İkinci denemeden yalnız bir dosya **salt okunur** alınır: `pairs.json` (aşağıdaki R9 kuralı).
   Birinci denemenin klasörüne yazılmaz.
5. **Kod farkı.** Doldurma ve çapa anlamı D127'de değişmedi; değişen şey rapor adımlarının model mesajı, çıktı çözme ve çıktı kimliği üyelik denetimidir. Saklı hücre kanıtı yeniden üretilmeden kullanılır; raporun anlık görüntüsü yeni kodla alınır.
6. **Kit** değişmez (yukarıda), ve D127'nin yeni alanlarını okumaz; bu yüzden ek denetimler (dışlama sayısı, ürün notu, başarısızlık bildirimleri, kimlik hata kaydı) elle yapılır.

## Başlangıç denetimleri (koşu istemi uygular; biri tutmazsa rapor başlamaz)

Denetimler `protocol3.md`'ye tarihli olarak yazılır, **rapor başlamadan önce**. İlk ekin "Başlangıç denetimleri" 1–4 ve 7. maddeleri, kaynak ve hedef klasör adı dışında **aynen** geçerlidir (aynı özet tablosu: dosya sha256, `quick_check`,
25 satır, 7 sütun, 175 hücre, 219 bağ, 1417 pasaj, 25 dahil kaynak, `reports` 0, araştırmanın `report` koşusu 0, etkin koşu 0, göç 57; tablo yanıtında `report_ready.ready` false, `cells_left` 21, `failed_rows` 3, `failed_cells` 21, `included_rows` 25,
`can_continue_with_failed` true; kopyada 11 `pending` adım terminal koşulara bağlı, dokunulmaz). Bu ek yazılırken `digest.py` ile birinci denemenin dosyası yeniden, salt okunur hesaplandı ve ilk ekin tablosuyla birebir aynı çıktı (özetlerin sha256 önekleri dahil). Değişen ya da eklenen denetimler:

1. **Karmalar:** `skill_package_hash` `sha256:52775258f530aa6a51513488f2aea37d0b7e609ffebe23d06451fd8ef0ae81ac`; şema listesinin sha256'sı `65df8e3c…af32` (aynı); kit dosyaları `db203420e4b1…` ve `7f7d2f0d5004…`; beklenti dosyası ve ilk ek
   yukarıdaki karmalarda. Biri farklıysa rapor başlamaz.
2. **Fark:** `git diff --stat 14a6e6f <donma commit'i> -- backend apps/web contracts methods scripts tests` boş; `git diff 15bb131 14a6e6f -- backend apps/web contracts methods scripts tests | shasum -a 256` `4185cb2d…5413`.
3. **Yeni klasör:** `$RUN3` ([.local/p6-eval-2026-09-30-run3](../local-runs.md#run-p6-eval-2026-09-30-run3)) yok ve sembolik bağ da değil; `mkdir` `-p`siz; yalnız `data/tools` sembolik bağdır; SQLite yan dosyası yok. `$RUN1` ve `$RUN2` hiçbir sunucu tarafından açık değil (`lsof +D` boş); port 8866 boş (ikinci denemenin sunucusu durmuş olmalıdır; çalışıyorsa dur, kapatma).
4. **R9 çiftleri:** aşağıdaki kurala göre (bayt bayt kopya, sha256, tamamlanmış satır ve Denklem hücresi kaydı) doğrulanmış olmalı.

## Rapor koşusu: sınırlar ve kurallar (taşınır, son deneme kuralıyla)

- **Model:** `gpt-5.6-luna`, açıkça; araştırma kapsamı `codex` / `gpt-5.6-luna` / `medium`. **Rapor: 60 model oturumu ve rapor isteğinden itibaren 90 dakika** (beklentilerin "Oturum sınırı"; bütçe 50, sayaç 15 saniyede bir, aşan oturumlar `over_cap_in_flight` yazılır). Doldurma tavanı yoktur.
- **Bir yeni rapor koşusu**, yukarıdaki son deneme kuralıyla. Kota ya da yük duruşunda dur; `client_timeout` yalnız bir kez, 10 dakika sonra sürdürülür (bu hak kullanıldıktan sonra ikinci `client_timeout`'ta dur); başka her `model_call_failed`, `section_failed`, `budget_exhausted` ve sayaç okunamaması koşuyu durdurur ve **müdahale yapılmaz**;
  başka bir modele geçilmez. Ara müdahale yok: hücre düzenlenmez, PDF eklenmez, satır çıkarılmaz, bölüm yeniden yazdırılmaz, ürünün sürdürmesi (saklı adımı yeniden oynatma) `client_timeout` dışında kullanılmaz.
- **Okurlar:** ilk okur koşuyu yürüten analist (kör değil; üçüncü denemenin analisti D124, D126 ve D127'yi ve ikinci koşudaki III ile V'in içeriğini bilir), ikinci okur bu ekleri, ilk kararları ve beklentileri görmeyen ayrı bir Claude Sonnet oturumudur. Sahip okumaz. Bütün okumalar "model okuması"dır. Kontrol örneği, çift işaret ve eksik okuma kuralları expectations'taki gibidir.

## R9 çiftleri (rapordan önce, ikinci denemeninkiyle aynı)

R9 çiftleri **yeniden seçilmez**: ikinci denemenin `pairs.json` dosyası (sha256 `2037d99376c0d341b75b0e39dbe3f179a09ed121863d0ed567ca4970231c7b96`; yedi çift: Dong14, Vuran08, Akbas14, Noda13, Oto12, Kurt16, Yaakob10) o denemede
bir rapor metni var olmadan, tablonun "Denklem" sütunundan işaretlenmişti. Aynı dosya, **bayt bayt**, `$RUN3/pairs.json` olarak kopyalanır ve rapor başlamadan önce sha256'sı doğrulanır. `formulation` alanı, ikinci denemede dondurulmuş **açıklayıcı bir etikettir**; tablo hücresinde birebir metin eşleşmesi **aranmaz**
(etiketler hücrelerin LaTeX ya da metin gösteriminden farklıdır; kopyada yedisinin hiçbiri hücrede birebir geçmez). Doğrulama şudur: her çiftin `source_key`'i tamamlanmış 22 satırdan biridir (`Nandi12`, `Zaman20` ve `Sankarasub03` çift olamaz) ve o kaynağın "Denklem" hücresinin kimliği, güncel revizyonu ve değeri `protocol3.md`'ye kaydedilir.
Biri tamamlanmış satırlardan değilse rapor başlamaz ve bu ekte tarif edilmeyen bir yol denenmez. Çiftler sonradan değiştirilmez, eklenmez. R9 uygunluğu, değişmeyen kit kuralıyla belirlenir: çiftin kaynağının **modele gerçekten verilen girdide görüntülenen bir denklemi** olup olmadığı; çift bulunamazsa ya da hiçbirinde girdi denklemi yoksa R9 "ölçülemedi"dir.
Aynı dosyanın korunması, üçüncü girişim için sonuç sonrası yeniden seçim serbestliğini kaldırır. İlk çift seçiminin temsil gücü ve bilinen korpus üzerinde geliştirme yapılmasının yarattığı yanlılık riski sürer; R9 bağımsız korpusta genellenebilirlik ölçümü değildir. (Bu, sahibin talimatındaki "R9 çiftleri rapordan önce" şartını sağlar.)

## Aralıkların D127'ye göre karşılaştırılması

Her satır expectations'taki aralıkla **aynıdır** (ilk ekin tablosundaki ek kurallar da aynen geçerlidir). Aşağıdaki sütun yalnız D127'nin **yeni** bir anlam kayması getirdiği yerleri yazar; hiçbir sayı değişmedi.

D127'nin davranışı, aralık anlamı bakımından üç cümleyle: (1) model dört rapor adımında psg/srv/cel/col tutamaçlarını görür, çıktısındaki tutamaçlar doğrulamadan önce gerçek kimliğe çevrilir; saklanan girdi, sonuç ve kanıt bağları gerçek kimlikle kalır.
(2) Bir bölüm çıktısındaki her kimlik alanı (atıf çapaları, iddia pasaj ve hücre kimlikleri, sayım üyeleri, boşluk dayanakları, en yakın eşleşme, denklem kökeni) o adımın **gösterilen** kanıtına karşı denetlenir; sözlükte görünüp izinli olmayan pasaj ile başarısız satırın kaynağı gösterilir ama kullanım hakkı vermez.
(3) Raporlarda D56 kurtarması yoktur: bilinmeyen kimlik bir kez onarılır, sonra adım başarısız olur.

| # | D127'nin etkisi | Aralık | Anlam kayması ve ek kural |
|---|---|---|---|
| R1a, R1b, R1c | (1) kopya hatası sınıfını (kısa kimlik) hedefler; (2) bir bölümü artık sayım üyesi, en yakın eşleşme ve boşluk dayanağı kimlikleri de `unknown_*_id` ile düşürebilir; (3) onarımdan sonra da hata sürerse bölüm yine `failed` olur | aynı | **Anlam kayması var, sayı yok:** bir bölümün ilk denemede geçerli olmaması ya da hiç geçerli olmaması için **yeni bir neden** (gösterilmeyen kaynağı sayım üyesi, en yakın eşleşme ya da boşluk dayanağı yazmak ya da gösterilmeyen bir pasaj ya da hücreye çapa vermek) eklendi. Aralıklar gevşetilmez. R1a, R1b ya da R1c aralık dışındaysa ya da koşu bir bölüm yüzünden durduysa, her bölüm için saklı adımın sorun kodları ve alan yolları (`unknown_passage_id`, `unknown_cell_id`, `unknown_source_id`, `unknown_column_id` ve planın mevcut üyelik hata kodları; liste sınırlayıcı değildir) salt okunur okunup `manual_checks.md`'ye yazılır. Eski/yeni sınıf, hata kodu ve alan yolu birlikte kullanılarak `15bb131` davranışıyla karşılaştırılır: iddia pasaj ve hücre üyeliği ile denklem kökeni pasaj üyeliği **önceden de vardı**; atıf çapalarının, sayım alanlarının, boşluk dayanaklarının ve en yakın eşleşme alanlarının bölüm düzeyindeki üyelik denetimleri **yenidir**. Bu kayıt betimleyicidir, tutamaçların etkisi hakkında hüküm değildir |
| R2 | Atıf bağları gerçek kimlikle saklanır; okur sayfaları gerçek pasaj metnini gösterir. Sözlük-yalnız pasajlara atıf artık bağ olarak değil sorun olarak görünür | aynı | Kayma yok. Ölçüt, saklı iddia-kayıt bağlarıdır; model mesajındaki tutamaç gösterimi R2'nin sayımına girmez. Ek denetim (dışlama sayısı, ilk ekin R2 satırı) aynen geçerli, yalnız aşağıdaki "Ek denetimler"deki saklı girdi kuralı güncellenir |
| R3 | (2) bir sayım ya da "kaynak X'i ele almadı" türü iddia, adımın göstermediği bir anlık görüntü kaynağını numerator/denominator üyesi yazamaz | aynı: U ≤ max(1, ⌊0,10 × N⌋) | **Anlam kayması var, sayı yok:** yeni üyelik denetimi uygunsuz sayımı bölüm doğrulamasında **reddeder**, sessizce düşürmez. Onarım başarılıysa nihai metnin N'si değişebilir; hata onarımdan sonra sürerse bölüm başarısız olur, koşu durur ve R3 ölçülemez (son deneme kuralı). Kit sayım üyelerini ya da olumsuz birimleri bu nedenle süzmez; N ya da U'yu aralığa sokmak için sayım yeniden yazılmaz. "Olumsuz cümle yok" ise R3 "ölçülemedi"dir (beklentilerdeki kural). Kitin tanımı, `no_evidence_given` dışlaması ve ilk ekin başarısızlık-bildirimi ayrı denetimi aynen korunur |
| R4a, R4b | `body_refs` montaj kuralı (`_check_body_refs`) değişmedi; Abstract, I ve IX iddialarının sayım üyeleri ve kimlik alanları aynı (2) denetimine girer | aynı | Kayma yok; R4a'nın kural hatası tanımı aynıdır |
| R5 | Sözlük planı, gösterilen pasaj kimlikleri tutamaçlı; sözlük-yalnız pasajlar atıf hakkı vermez | aynı | Kayma yok. Terim başına başka ad sayımı metinden okunur; tutamaç gösterimi bunu etkilemez |
| R6 | Denklem kökeninin izinli ve gösterilen pasajda olması D127'den önce de denetleniyordu (`unknown_passage_id`); şimdi aynı denetim kimlik alanı yolunda yapılır | aynı | Kayma yok. Kitin ham denklem listesi ve ilk ekin R6 kuralı (başarısız kaynağa bağlanan denklem = D125 dışlama hatası) aynen geçerli |
| R7 | Tutamaçlar girdi metnini kısaltır: aynı kanıt için **girdi jetonu değişebilir**; çağrı zinciri ve bütçe aynı | aynı (10–30 dakika, 15–46 çağrı, 7–13 ardışık) | **Anlam kayması yok, ama ayrım kuralı:** jeton için beklenti yoktur; ikinci denemenin 189.969 jetonu kısmi bir koşudur ve üçüncü koşunun sayısıyla karşılaştırılmaz. İlk ekin R7 ayrımı (doldurmanın 36 oturumu ve 3,3 dakikası R7'ye girmez; ikinci denemenin 7 oturumu ve 3,7 dakikası da girmez) aynen geçerli. Rapor koşusunun süresi koşunun kendi `created_at`/`updated_at` alanlarından okunur. `client_timeout` sürdürmesi kullanılırsa R7 süresi, bekleme dahil, koşunun kendi zamanlarından okunur ve sürdürme kaydedilir |
| R8 | Kalıp onarımı (`report_phrase_repair`) yeni bir kanıt almaz (D127); yalnız kimlik gösterimi tutamaçlıdır | aynı | Kayma yok |
| R9 | Çiftler ikinci denemeninkiyle aynı dosya; girdide görüntülenen denklem koşulu değişmedi | aynı | Kayma yok; yukarıdaki R9 kuralı |
| R10 | Yok | ölçülmez | Hâlâ "ölçülmedi" (`p15_behavior_is_not_r10`) |
| R11 | Başarısız satırların kaynakları bazı adımlarda gösterilir (VIII'in `failed_rows` girdisi, inceleme sayım kaynakları); D127 bu kimliklere tutamaç verir, kullanım hakkı vermez | aynı | **D127'ye özgü anlam kayması yoktur.** Başarısız satırların VIII'de operasyonel bilgi olarak gösterilmesi D125'ten beri geçerlidir. İkinci denemedeki "hiçbir model girdisi başarısız kaynağı anmadı" bulgusu yalnız ulaşılan adımların kapsamıdır (VIII hiç yazılmadı); VIII yazılırsa başarısız kaynaklar yasal olarak girdide görünür. İlk ekin ihlal tanımı (başarısız kaynağın pasajının ya da hücresinin içerik kanıtı, atıf, toplulaştırma üyesi ya da boşluk dayanağı olarak kullanılması) değişmez; kural "anılma"ya değil "kullanım"a bağlıdır. "Bölümde olması gerekirdi" sayacında üç başarısız kaynağın pasajları sayılmaz (ilk ek). `truncated` kayıtları ve 25 kaynaklı sınıf eşiği aynen |

## Ek denetimler (aralık değil, kayıt; kit dışı, elle)

İlk ekin ek denetimleri (D125 dışlama sayısı, ürün notu, başarısızlık bildirimleri, R3'ün ayrı denetimi) aynen yapılır. D127 için yalnız şu değişiklikler ve eklemeler vardır:

1. **Dışlama denetiminin saklı girdi kuralı:** ikinci denemenin "yedi saklı girdinin hiçbiri üç başarısız kaynağın kimliğini anmıyor" kuralı bu koşuya **taşınmaz**. Yerine: üç kaynağın kaynak-sürümü kimlikleri ve onların 101 pasaj kimliği hiçbir saklı adım girdisinin `passages`, `sources`, `allowlist`,
   `report_target.cells`, `report_target.gap_candidates`, `report_target.plan` ya da `report_target.columns` alanında bulunamaz; yalnız `report_target.limitations_core.failed_rows` ile gösterim amaçlı inceleme alanlarında bulunabilir. Ayrıca ilk ekin tanımındaki dışlama sayısı (iddia, atıf bağı, kaynakça, boşluk dayanağı, denklem kökeni, sayım üyesi) aynen sayılır. Saklı girdi okunamazsa `not_readable` yazılır.
2. **Kimlik hata kaydı (betimleyici):** her rapor adımı (plan, III–IX, özet, dizin terimleri, kalıp onarımı, inceleme) için saklı oturumlardan: kaç kimlik sorunu kodu çıktı, hangi alanda (iddia, çapa, sayım, boşluk, denklem kökeni, plan), onarımdan sonra sürdü mü. Ham model çıktısı tutamaç taşır; saklı sonuç gerçek kimlik taşır; ikisi birbirine karıştırılmaz ve okunan sayı hangisinden geldiği yazılarak kaydedilir.
   Bu kayıt R-satırı değildir ve "tutamaçlar hatayı azalttı/azaltmadı" diye yorumlanmaz: tek koşu, rastgele bir model çıktısıdır.
3. **Ürün notu** (ilk ek) ve **Markdown dışa aktarım notu, VIII'in sekizinci maddesi**: koşu tamamlanırsa okunur; durursa `not_readable`.

## Okuma kuralı ve sonuç sunumu (taşınır)

Expectations'taki "Okuma kuralı" ve ilk ekin "Okuma kuralı ve sonuç sunumu" bölümü aynen geçerlidir. Sonuç dosyası (`p6-slice1-report-results-run3.md`, önceki iki dosya düzenlenmez) ilk paragrafta şunu söyler: bu bir tek araştırma, tek tablo, tek yeni koşu, tek model ölçümüdür; 
**gözlenen başarısızlık sonrası düzeltilmiş üründe, aynı bilinen korpusa koşullu geliştirme ölçümüdür**; doldurma sonucu (3 başarısız satır) ve D126'nın durma noktası bilinirdi; bu, son girişimdi. Hemen ardından **üç girişimin kaydı** yan yana gelir (D124: rapor başlamadı; D126: bir koşu, bölüm IV'te durdu; bu koşu:
ne olduysa), "üç rapor koşusu" diye sayılmaz. D124 ve D126 ile çelişen ya da onları "geçersiz kılan" bir cümle yazılmaz. Başlangıçta durulduysa ya da rapor koşusu oluşturulamadıysa sonuç "üçüncü girişimde rapor başlamadı; yeni rapor koşusu 0; okur yok; R1–R11 ölçülmedi" der; "bir yeni koşu" ifadesi yalnız koşu gerçekten oluşturulduğunda, "rapor yazıldı" ifadesi yalnız oluşan içerik kapsamında kullanılır. Başarıda yalnız "bu örnekte tamamlandı" yazılır; tutamaçların nedensel etkisi, genel rapor kalitesi ve başka korpus
sonucu **yazılmaz**, "bağımsız korpusta ayrıca sınanmalıdır" yazılır. Durmada R1 ve R7 korunur, geri kalan "ölçülemedi"dir ve dördüncü girişim önerilmez; önerilecek bir şey varsa yalnız "açık soru, sahibe" olarak yazılır.

## Bu ekin sınırları

- Bu ek, D127'nin çalıştığını göstermez; D127 sentetik sahte ve betikli modellerle sınandı, bir gerçek model çağrısı yoktu. Bu ölçüm, gerçek model altında tek bir kez, düzeltilmiş ürünün rapor yolunu görecektir; başka tabloda ya da modelde ne olacağını söylemeyecektir.
- Analist D127'nin tasarımını, ikinci koşunun durma noktasını ve III ile V'in içeriğini bilir; kör değildir. Bu, ilk okurun tarafsızlığını sınırlar; ikinci okurun körlüğü bunu yalnız kontrol örneğinde dengeler.
- Kit D127'nin yeni alanlarını okumaz; ek denetimler elle yapılır ve ana R-satırlarının paydasını değiştirmez.
- Birinci ve ikinci denemelerin klasörleri değişmez; üçüncü deneme kendi klasörünü ([.local/p6-eval-2026-09-30-run3/](../local-runs.md#run-p6-eval-2026-09-30-run3)) kullanır.

## Gözden geçirme kaydı

- **Tur 1** (gpt-6.1-sol, high, salt okunur; ek ve koşu istemi): 2 high, 5 medium, 2 low; hüküm "hazır değil". High: R9 `formulation` metninin hücrede birebir geçmesi şartı sağlanamıyordu (yedisi de açıklayıcı etiket); `section_failed` yasağı, bölüm çağrısındaki `client_timeout`'un dış kodunu da kapsıyordu. Dokuz bulgunun hepsi uygulandı.
- **Tur 2**: 1 high (çalışan koşuda hata saptanınca kayıtların sabitlenmesi), 1 medium (rapor başlamadı dalının sonuç ifadesi); hüküm "hazır değil"; ikisi de uygulandı.
- **Tur 3**: 1 high (sabitleme, saklı `running` adım etiketine bağlanamaz; ürün hız sınırı ya da iptal yolunda adımı `running` bırakabilir), 2 medium (R7 süre sonu, iptal yasağının kendi istisnasıyla çelişmesi), 1 low (rapor oluşmadı dalında ortak kapanış); hüküm "hazır değil". Dördü de uygulandı. Üç tur sınırı doldu; son düzeltmeler yeniden gözden geçirilmedi. Bu yüzden durum TASLAK kalır (DONDU değil).
- **Tur 4**: 0 high, hüküm "hazır"; üçüncü turun düzeltmesi (sürücü dönüş kaydı + sıfır `started` oturum) bulguyu kapatıyor.
