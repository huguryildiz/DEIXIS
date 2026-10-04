# P9 H9 sonuçları: yeni korpusta tek rapor koşusu

**Tarih:** 3 Ekim 2026. **Dondurma:** [p9r-report-freeze.md](p9r-report-freeze.md), 1. nokta `6b06866`, 2. nokta `7a34e3e` (Ek A). **Ürün:** `87cee0b`, ayrık ölçüm worktree'si. **Karar:** [D171](../decisions.md) sonuç bölümü.

## Sonuç

Rapor koşusu yarıda durdu. IV. bölüm, bir onarım denemesinden sonra da geçersiz çıktı verdi. Bu yüzden R2, R3, R4, R5, R6, R8, R9 ve R11 ölçülemedi (`run_incomplete`). R10 tasarım gereği ölçülmedi. Okur çalışmadı. Yalnız R1, R7 ve P19 kayıtlı. Bu bir rapor kalitesi hükmü değildir: tek koşu, tek rapor modeli (`codex`/`gpt-5.6-luna`/`medium`), geliştirme sonrası yeni korpus ve rapora hazır tablo koşuluyla sınırlıdır.

Durma nedeni saklı kayıtlardan okundu. IV. bölümün ilk çıktısında bir hücre çapası hücre kanıtında bulunamadı (`anchor_not_in_cell_evidence`). Ürün tek çapa onarımı gönderdi. Onarım çıktısında iki ayrı sorun vardı: model `skill_package_hash` değerini bir karakter yanlış kopyaladı (`envelope_mismatch`), ve 21 atıf çapasının her biri hem `passage_id` hem `cell_id` taşıyordu; şema tam birini istiyor (`citation_anchor_target_count`). *(3 Ekim düzeltmesi, D198/D202: bu cümlenin ilk sürümü “hiçbirinde ne `passage_id` ne `cell_id` vardı” diyordu; saklı onarım çıktısı ikisinin de dolu olduğunu gösteriyor.)* Hata `client_timeout` değildi; freeze §5 gereği koşu sürdürülmedi. Koşu zaten `paused` (`section_failed`) durumundaydı; durumu korundu, iptal gönderilmedi.

Aynı hash kopyalama hatası hazırlıkta iki oturumda daha görüldü: bir özet tarama oturumu (`mss_h5nfepCU8lHyzXZ1W3qz`, adım başarısız) ve bir tam metin kararı oturumu (`mss_IEbEtej7GQuNAUvyNukU`, adım onarımla başarılı). 52 oturumda üç gözlem bir hata oranı vermez. *(3 Ekim düzeltmesi, D198: ilk sürüm yalnız özet tarama adımını sayıyordu.)*

## Kimlikler

| Kayıt | Değer |
|---|---|
| Araştırma | `res_5ZrJQgVQ5unqqCRpMbrr` (`sw`, akademik, yalnız soru, keşif eforu `standard`, dil `tr`) |
| Tablo | `tbl_pQukBcMTicxNo3QPGaf9`: 7 eser, 7 `text` sütunu, `report_ready=true` |
| Rapor koşusu / rapor | `run_YHPhlrH3yeRdPIQwCdoI` / `rpt_qSCmtEmodD6qn2WRStC4` |
| POST | 07:40:51.677Z, yanıt 202; gövde `{"table_id": "tbl_pQukBcMTicxNo3QPGaf9", "continue_with_failed": false}` |
| Duruş | 07:43:49.934Z, `section_failed`; IV adımı `stp_UyGp5loXvWFn2VCh16zK` |
| Rapor öncesi kapı | §6.1 `7a34e3e` ile rc 0, regresyon testleri 257 geçti, 8765 boş (07:40:43Z) |
| Kit çıktıları (SHA-256) | `results.json` `1baefc078e1931a2a411eb80c79279c7c6d7201cc70665ca0ef8cb483795dcc9`; `snapshot.json` `fb37eb761061ddd01f053cbade8aa1b135a739cae0e059383b7fb6273a667c91`; `automated.json` `37706b9ea1243328ff2fff684d89f2c06a71cb5b278dce27f871365227dc24ef` |
| Kit komutu | `snapshot ... --seed 20261003 --sample 30 --pairs r9/pairs.json --stopped section_failed_invalid_model_output`, sonra `score`; `--crossref`/`--seeded` yok |

## Sayılar

Bulunan 4.925 satır (925'i atıf zincirinden). Tekil eser 3.167. Model 150 özet okudu. Tam metin 112 eser için arandı: 103'ü getirilemedi, 9'u okundu. Dahil edilen 7 eser: 3'ü otomatik, 4'ü K03 kuyruk geçişinden. Tabloya ve rapor modeline 7 eser verildi. Ancak 5 satırda model yalnız özet okudu. Ürün seçimi eserin yayımlanmış sürümüne koyuyor; bu sürümde yalnız özet var, tam metin ise kardeş sürümde (Ek A.4). Saklı bölüm iddiaları 7 kaynağın hepsine atıf yapıyor. Rapor tamamlanmadığı için bu, son raporun atıf kümesi değildir.

Model oturumları: hazırlıkta 45 (keşif 19, tam metin kararı 19, doldurma 7), raporda 7, toplam 52. Hazırlık 21,1 dk sürdü; 2 denemenin 1'i ve 2 kuyruk isteğinin 1'i kullanıldı.

## Ölçülen satırlar

**R1 (tamamlanma):** tamamlanan rapor 0/1. Model bölümleri III, IV ve V'ye ulaşıldı. III ilk denemede geçerli. V bir onarımla geçerli. IV bir onarımdan sonra başarısız. İlk denemede geçerli 1/3, onarım sonrası geçerli 2/3. VI-IX, I, özet ve dizin terimleri adımları hiç başlamadı (`section_step_missing`). Kod üretimli II. bölüm geçerli.

**R7 (süre ve çağrı):** POST'tan duruşa 178,2 s; 7 model çağrısı. İlk çağrılar 2, onarım çağrıları 2, başarısız adım çağrıları 3. Kuyruk/kota bekleme aralıkları ayrı kaydedilmiyor (`not_readable`). Kesik bir koşunun kısa süresi hız veya maliyet kanıtı değildir.

**P19 (yardımcı, D129; §4.2.1 sorgusu, SHA-256 `6d53789f7a1b898a4833bb993eaac222b29e5fa0cb209519fe020c3106e6acd1`; satır çıktısı `b325ed944158e5492bbc82b69bdce7a3481b31ccbecadd974458bbe20ee38422`):**

| | Sayı | Kimlikler |
|---|---|---|
| (a) İlk çıktısında `anchor_not_in_cell_evidence` olan adım | 2 | IV, V |
| (b) Oturumlu çapa onarım denemesi | 2 | IV `sti_DlN8SoMvp1H71ATLrvC9` / `mss_xhk50S1g0GOlJmHgeH9a`; V `sti_cbCVaseW0mj8a4WqwpBJ` / `mss_c57ZHZgnqrGFdJNCZhv0` |
| (c) Onarım doğrulaması `ok=true`, kod kalmamış, bölüm `valid` | 1 | V |
| (d) Onarımdan sonra aynı çapa koduyla hâlâ `failed` | 0 | IV `failed`, ama çapa kodu yerine `envelope_mismatch` ve `citation_anchor_target_count` ile; bunlar ayrı sayılır |
| (e) Onarımda çıkarılıp `insufficient_evidence` kaydında adıyla görünen iddia | 0 | V'de `V.7`, `V.8` çıkarıldı; kayıt boş, ikisi de görünmüyor. IV'te iddia çıkarılmadı (onarım 18 iddiayı 19'a çıkardı); bölüm taslağı yok |

Oturumsuz onarım girdisi yok. P19 sayıları oran veya D129 etkisi diye okunmaz.

## Ölçülemeyenler

R2-R6, R8, R9, R11: `ölçülemedi: run_incomplete`. Okurlar (K09) başlatılmadı, okur isteği 0. R9 için dondurulan 5 çift (`pairs.json` `706ae813…547d`) kullanılmadı. R10 ölçülmedi.

## Sapmalar ve sınırlar

- **Anahtar terimler (Ek A.3).** Ürün Türkçe soruyu okumadı ve İngilizce anahtar terim istedi. Terimler (`electric vehicle, electric vehicles; charging scheduling; optimization`) Claude Opus 5.5 + `gpt-6.1-sol` medium kararıyla verildi. Bu donmamış bir yürütücü girdisidir. Arama ve korpusu biçimlendirdi. Varsayılan Türkçe keşif başarımı veya literatürün tamlığı hakkında bir şey söylemez.
- **Seçilim.** 4 eser, yürütücü modelin (`claude-opus-5-5` medium) saklı tam metinden verdiği kuyruk kararlarıyla dahil edildi. Ürün bunları `user`/`human_include` olarak saklıyor; bu satırlar için “person” etiketi yanlıştır (D96/D101). Bu kararlar insan doğrulaması değildir ve varsayılan keşfin verimi sayılmaz. Protokol kartını da yürütücü model değiştirmeden onayladı; ürün `approved_by=user` saklıyor.
- **Özet ağırlıklı tablo.** 7 satırın 5'i yalnız özetten dolduruldu. Freeze'deki en az 3 saklı tam metin hedefi satır düzeyinde tutmadı.
- **Tespit gecikmesi.** Gözlemci duruşu 07:43:52Z'de doğru kaydetti. Kapanış 120 s içinde doğrulandı: yürütücü dönüş kaydı vardı ve `started` oturum yoktu. Yürütücünün kendi izleme betiği gözlemci satırlarını yanlış ayrıştırdığı için duruş 07:50Z civarında fark edildi. Arada yapılacak bir işlem yoktu; koşu duraklamıştı.
- **Gözlemci.** Sol high'ın engelleyici saymadığı düşük bulgu düzeltilmedi: `ps` stdout doluyken çıkış kodu yok sayılıyor. Bu ölçümde sunucu hep canlı görüldü.

## Süreç kapanışı ve izolasyon

İzole sunucu (PID 38083, port 8873) 07:51Z'de SIGTERM ile durduruldu. Sunucu ve kayıtlı `codex app-server` alt süreci (38865) 5 s içinde çıktı. Gözlemciler durma dosyalarıyla kapandı. Sunucu yeniden başlatılmadı. Port 8765 hiç kullanılmadı ve her denetimde boştu (06:52Z, 07:16Z, 07:40Z, 07:50Z). `~/Library/Application Support/DEIXIS` altında yalnız `codex-home` kullanıldı, o da yalnız adaptör tarafından (K05 istisnası). Ölçüm worktree'si temiz, `87cee0b`'de; kit ve kit testi hash'leri değişmedi. Ham kanıt `DEIXIS-h9run/.local/p9r-h9/` altında izlenmeden duruyor.

## R01

R01 `ölçüldü, rapor tamamlanmadı`: tek koşu IV. bölümde geçersiz model çıktısıyla durdu. Yalnız R1, R7 ve P19 var.

## H9b (3 Ekim 2026): kol A ve kol A2

**Dondurma:** Ek B (`a093f6f`), Ek C (`5c8cb98`), Ek D (B kaydı). **Karar:** [D202](../decisions.md). İki kol da H9'un tablosunu kullandı (geliştirme korpusu, bağımsız değil). Burada yazılan her şey tek rapor modelinde ve tek koşudadır; hata oranı, hız karşılaştırması veya RF/RF2'nin nedensel etkisi değildir.

**Kol A (ürün `682ba1f`):** rapor koşusu ilk yama isteğinde durdu. V. bölümün ilk çıktısında hücre kanıtında bulunmayan çapalar vardı; ürün RF'in yama yolunu seçti ve canlı API isteği `invalid_json_schema` ile reddetti, çünkü yama şemasının `reason` alanında `$ref` yanında başka anahtarlar vardı. Bu ürün hatasıdır, model hatası değildir; yama modeli hiç çıktı vermedi. III'ün tam onarımı iptalle kesildi, IV onarımdan sonra geçerliydi. İptal 11:29:43Z, kapanış doğrulandı. R1 0/1 (ilk denemede geçerli 0/3, onarımla geçerli 1), R7 145,6 s ve 7 çağrı; `envelope_mismatch` 0/7, kodla damgalanan 5/5; çıkarılan iddia 0, `repair_dropped_*` 0; P19 a=[V], b=1, c=0, d=0. Düzeltme RF2'dir (D204).

**Kol A2 (ürün `7cc1168`, H9 verisinin taze ve doğrulanmış kopyası):** rapor koşusu 13:16:50Z'de başladı ve 13:19:52Z'de VI. bölümde durdu. VI'nın ilk çıktısı şemaya uygundu ama hiç iddia ve hiç yetersiz kanıt girdisi taşımıyordu (`empty_section`); ürün bunun için otomatik onarım yapmıyor, koşuyu yeniden yazım için duraklatıyor. Neden zaman aşımı değil, kural gereği sürdürülmedi ve iptal edilmedi. II-V geçerli, VI taslak, sonrakiler başlamadı. R1 0/1 (ilk denemede geçerli 0/4, onarımla geçerli 3), R7 181,8 s ve 10 çağrı. Okur çalışmadı.

- **Yama yolu (D198/D204):** IV'ün ilk çıktısı yama yoluna girdi. Gönderilen şema Ek C'de donan düzeltilmiş şemayla aynıydı (`f30984c2…`); canlı API kabul etti, model çıktı verdi, yama doğrulanıp uygulandı ve IV `valid` yayımlandı. Bu, düzeltilmiş şemanın tek bir istekte kabul edildiğini gösterir; genel güvenilirlik göstermez.
- **Sayımlar:** çıkarılan iddia 0; `repair_dropped_claim` ve `repair_dropped_insufficient_evidence` 0; `envelope_mismatch` 0/10; doğrulaması olan 9 yama dışı oturumun 9'u kodla damgalı; doğrulaması olmayan rapor oturumu 0. P19: a=[V, IV], b=2 (V tam onarım, IV yama), c=2, d=0. Adım hatası yok; şema reddi yok; B için veto yok.
- **Ölçülemeyenler:** rapor tamamlanmadığı için R2-R6, R8, R9, R11 ve okur satırları ölçülmedi.

A ve A2 birlikte şunu gösterir: RF'in yama şeması canlı API'de reddediliyordu, RF2'den sonra bir istekte kabul edildi ve yama bir bölümü geçerli yaptı. Rapor bu kez başka bir yerde, boş bölümde durdu; bu duruş için ürün tarafında düzeltme (RF3) koordinatör tarafından açıldı. Kol B'nin sonucu aşağıda.

## H9b (3 Ekim 2026): kol B

**Dondurma:** Ek D (`ead0b79`). **Karar:** [D202](../decisions.md). Ürün `b90583b` (RF3 dahil), B'nin durmuş hazırlık verisinin doğrulanmış kopyası (`b2/data`). Korpus Q3 için yenidir: 10 satır, 9 eser (iki kayıt aynı PDF). Tek rapor modeli, tek koşu; hata oranı veya RF/RF2/RF3'ün nedensel etkisi değildir. Okumalar kayıtlı model okumasıdır, insan doğrulaması değildir.

**Koşu:** rapor koşusu 14:45:00Z'de başladı, 14:49:11Z'de `completed` bitti (250,9 s, 20 çağrı); hiçbir durdurma kuralı tetiklenmedi. On model bölümünün onu da `valid`; H9 serisinde bütün bölümleri yazılan ilk rapor koşusu budur. Ama birleştirme kontrolü raporu reddetti ve rapor `draft` kaldı: VIII.5'te yasak sözcük ("araştırma boşluğu"), IV.8'in denklem kaynağı iddiada atıflı değil ve matematik taşımıyor, abstract.1, abstract.2 ve IX.3 "Bu çalışma" kalıbını kullanıyor. Bu yüzden R1c 0/1'dir. Koşunun bitmesi raporun kabul edildiği veya bilimsel olarak doğrulandığı anlamına gelmez. Okurlar, Sol medium ile ortak kararla (`evidence/decide6-out.md`) donmuş protokolün tamamlanan koşu yolundan çalıştı.

- **Yama yolu ve sayımlar:** IV'ün ilk çıktısı yama yoluna girdi; şema donmuş değerle aynıydı (`f30984c2…`), API kabul etti, yama uygulandı, IV `valid`. Çıkarılan iddia 0; `envelope_mismatch` 0/20; doğrulaması olan 19 yama dışı oturumun 19'u kodla damgalı; adım hatası yok. P19: a=[IV], b=1, c=1, d=0, e boş.
- **Okurlar:** ilk okur `claude-opus-5-5` medium (yürütücü, kör değil); ikinci okur `claude-sonnet-5-5` medium, boş dizinde tek istek (4 hakkın 1'i), dönen model aynı. Eşitlik denetimi geçti (51 birim). Donmuş komuta yalnız dönen model kimliğini kaydetmek için `--output-format json` eklendi; paket değişmedi.

| Satır | Beklenti | B sonucu | Aralıkta mı |
|---|---|---|---|
| R1a | ilk denemede geçerli 7-10/10 | 3/10 | hayır |
| R1b | onarımla geçerli ≥9/10 | 10/10 | evet |
| R1c | 1/1 | 0/1 (birleştirme reddi) | hayır |
| R2 | yanlış bağlı iddia 0-3; kısmen bağlı iddia ≤8 | 30 iddia, 42 bağ: yanlış bağlı 0; kısmen bağlı 21; okur anlaşmazlığı 2 | ilk koşul evet, ikinci hayır |
| R3 | U ≤ max(1, ⌊0,10 N⌋) | N=5, U=4; anlaşmazlık 4 | hayır |
| R4a | `body_refs`'siz iddia 0 | 0 | evet |
| R4b | gövdeden güçlü ≤%10 | 2/11 (%18; D3 iki okur, D4 yalnız ilk okur) | hayır |
| R5 | terim başına başka ad ≤1 | 7/5 = 1,4 (2, 3, 1, 0, 1) | hayır |
| R6 | 0-6 denklem; ≥3 ise yarısı sayfayla örtüşür | 1 denklem birimi; okurlar ayrıştı (ilk: formül raporda yok, örtüşmez; ikinci: örtüşür) | yarı kuralı uygulanmaz |
| R7 | 10-30 dk, 15-46 çağrı, 7-13 ardışık tur | 4,2 dk, 20 çağrı, 7 tur | süre hayır (kısa), diğerleri evet |
| R8 | ilk uyumsuzluk %30-70; onarım sonrası kalıpsız ≤%25; geri alınan 0-2 | 19/35 (%54); 12/35 (%34); 0 | ikinci koşul hayır |
| R9 | girdideki denklemlerin yarısı raporda | kit 7 çiftin kaynak anahtarını kaynak sürümüne eşleyemedi (aşağıda) | ölçülemedi |
| R10 | yok | `p15_behavior_is_not_r10` | ölçülmedi |
| R11 | kesilen kayıt 0; `insufficient_evidence` 0-3; eksik pasaj ≤2 | 117 hücre kesildi (IV 54, V 63); 3; 87 pasaj (IV 74, V 13) | birinci ve üçüncü hayır |

- **En büyük kayıp girdi kesilmesi:** 10 kaynaklı tabloda IV 70 hücrenin 16'sını, V 7'sini gördü. IV'ün düzyazısı 10 kaynaktan yalnız ikisine ([2], [3]) atıf yapıyor; V altı kaynağa. Okurun eksik pasaj sayısı kendi kuralıyla sayıldı: bölümün kapsadığı sütunlardaki donmuş hücrelerin, bölüm girdisine hiç verilmemiş kanıt pasajları (tablo dışındaki pasajlar okunmadı).
- **R3 ve R4b:** kitin sözlüğü Türkçe yokluk fiillerini ("belirtilmemiştir", "tanımlanmamıştır" vb.) bulmadı; beş birimin beşi ilk okurca eklendi. İlk okur hepsini hücreyle uyumlu saydı, ikinci okur özet düzeyindeki hücrelere dayanan dördünü yokluğu genişletiyor diye uygunsuz saydı; kural gereği biri ciddi derse ciddidir. R4b'de D3 "başka belirsizlik modelleri", D4 "enerji tüketimini iyileştirdi" ifadesi gövdede yok.
- **R9 kit eşlemesi:** IV girdisinde Candelieri18b ve Rajabpour18'in donmuş Denklem hücreleri vardı. Kit çiftin `source_key` değerini raporun kaynak listesinden okuyor, sonra donmuş anlık görüntünün satırlarıyla üzerine yazıyor; o satırlarda `source_key` alanı yok, bu yüzden her çiftin `source_version_ids` listesi boş kaldı ve kit her çifti `no_input_equation` yazdı. Freeze §4.4 gereği kit değiştirilmez ve kit dışında puan verilmez; R9 ölçülemedi kalır. Bu bir kit hatasıdır, girdide denklem olmadığı anlamına gelmez.
- **R2:** kısmen işaretlerinin çoğu, çok parçalı bir iddiaya tek parçayı taşıyan çapa alıntısından geliyor. Desteklemeyen bağ yok.

Bütçe: A 7 + A2 10 + B hazırlık 70 + B rapor 20 = 107 / 293 oturum; okur isteği 2 / 4, 6 dk 11 s (ilk okurun 5 dk 38 s'lik okuması dahil; ilk kayıt yalnız ikinci okuru saymıştı, Ek E'de düzeltildi). D129'un çapa onarımı A2'de iki bölümde (V tam onarım, IV yama), B'de bir bölümde (IV yama) görüldü ve sayıldı. Onarılan iddiaların anlam desteği ayrıca okunmadı; B'nin R2 okuması tohumlu 30 iddialık örneklem üzerindedir. Sunucu durduruldu, 8765'e dokunulmadı; kanıt `../DEIXIS-h9b-run/.local/p9r-h9b/evidence/b2/`.

## H9c (3 Ekim 2026): B raporu RF4 üzerinde

**Dondurma:** Ek E (`0e1600b`). **Karar:** [D202](../decisions.md). Ürün `2b185a8` (RF4), B'nin hazırlanmış verisinin yeni doğrulanmış kopyası `c/data`; korpus B'ninkiyle aynıdır. Tek koşu; B ile karşılaştırma bir koşuya karşı bir koşudur, RF4'ün nedensel etkisi değildir.

**Koşu:** başlangıç kapısı ve POST öncesi denetim geçti (en büyük migration 70, kurtarılan iş 0; `evidence/c/prepost-check-*.json`, `prepost-post-*.json`). POST 17:06:53Z, `run_mWEug1ro09ZlJDBV5O5B`, rapor `rpt_85lvdp1HjlTnqUYXvjUG`. Koşu 17:12:02.571Z'de `section_failed` ile duraklatıldı (terminal olay 1614; 309,1 s, 24 çağrı); gözlemci bunu 17:12:12.986Z'de saptadı. Rapor `in_progress` kaldı, inceleme yok; birleştirmeye gelinmedi. On model bölümünden dokuzu `valid`, özet `failed`. Neden zaman aşımı değil; kural gereği sürdürülmedi, duraklamış koşu iptal edilmedi. Kapanış doğrulandı (`snapshot_eligible`), snapshot `--stopped section_failed` ile alındı, okur çalışmadı.

- **Duruşun nedeni:** özetin ilk çıktısı doğrulamadan sorunsuz geçti (`ok=true`, hata yok; dört `sentence_without_phrasebank_frame` uyarısı cümle onarımını başlattı). Ardından gelen cümle onarımı `abstract.2#2` cümlesini "Temel amaç, …" yerine "Bu çalışma, temel amacın … olduğunu …" biçiminde yeniden yazdı. RF4'ün cümle onarımından sonra tam doğrulayıcıyı yeniden çalıştırması bunu `own_work_phrase_in_claim` olarak yakaladı (`/claims/1/text`); bu noktada ürünün başka onarım yolu yoktu ve bölüm başarısız oldu. Yani yasak kalıbı model ilk yazımda değil, ürünün cümle onarımı getirdi; RF4 bunu birleştirmeden önce yakaladı ama onaramadı.
- **Sayımlar:** POST öncesi 0 oturum; rapor 24 oturum, `envelope_mismatch` 0/24, 24/24 kodla damgalı; yama girdisi 0; çıkarılan iddia 0. P19: a=[V], b=1 (V tam onarım), c=1, d=0. Adım hatası yok, şema reddi yok.
- **Satırlar:** R1a ilk denemede geçerli 1/10, R1b onarımla geçerli 9/10, R1c 0/1; R7 5,2 dk ve 24 çağrı. Rapor tamamlanmadığı için R2-R6, R8, R9, R11 ölçülemedi (`run_incomplete`); R10 ölçülmedi.

Bütçe: 107 + 24 = 131 / 293 oturum; okur isteği yeni yok (ortak defterde 6 istek kalır). Sunucu durduruldu, 8765'e dokunulmadı; kanıt `../DEIXIS-h9b-run/.local/p9r-h9b/evidence/c/`.

## H9d (3 Ekim 2026): B raporu RF5 üzerinde

**Dondurma:** Ek F (`7f6e634`). **Karar:** [D202](../decisions.md). Ürün `1f4903f` (RF5), B'nin hazırlanmış verisinin yeni doğrulanmış kopyası `d/data`; korpus B ve H9c ile aynıdır. Tek koşu; önceki koşularla karşılaştırma bir koşuya karşı bir koşudur, RF5'in nedensel etkisi değildir.

**Koşu:** başlangıç kapısı ve POST öncesi denetim geçti (migration 70, kurtarılan iş 0). POST 20:25:19Z, `run_DeedBWVc3F85JARn17rT`, rapor `rpt_ENDUxE7H3AhZujTmZCJA`. Koşu V. bölümde durdu: oluşturmadan duraklamaya 169,3 s (olay 1504, 20:28:08.958Z), 9 çağrı; kitin R7 değeri 184,4 s, oluşturmadan iptale kadardır ve duraklamadan sonraki 15,1 s'yi içerir. III ve IV `valid`, V `failed`, sonraki bölümler başlamadı; rapor `in_progress` kaldı, birleştirmeye gelinmedi. Okur çalışmadı.

- **Duruşun nedeni:** V'nin ilk çıktısında hücre kanıtında bulunmayan bir çapa vardı (`anchor_not_in_cell_evidence`), ürün tam onarım istedi. Onarım çıktısı, onarım girdisinin kimliği yerine ilk denemenin `step_input_id` değerini taşıyordu (`envelope_mismatch`: beklenen `sti_pO3R…`, gelen `sti_S8OQ…`). Kod paket hash'ini damgalıyor ama girdi kimliğini hâlâ model kopyalıyor; bu hatanın onarımı yok, bölüm başarısız oldu. Zaman aşımı değil, kural gereği sürdürülmedi.
- **Sapma:** koşu 20:28:09Z civarında kendiliğinden `section_failed` ile duraklamıştı (terminal olay 1504). Yürütücü, yaklaşık 30 s önceki (20:27:54Z) "çalışıyor" okumasına dayanıp durumu yeniden denetlemeden 20:28:24Z'de iptal gönderdi; duraklamış koşu `cancelled` (`user_cancelled`, olay 1505) oldu. Bu, "duraklamış koşu iptal edilmez" kuralının ihlalidir. Duraklama ile iptal arasında yeni model oturumu başlamadı (iki okumada da 9 tamamlanmış, 0 başlamış); duruş nedeni ve oturum sayımları etkilenmedi; koşunun son durumu ve R7'nin süre değeri (15,1 s fazlası) değişti.
- **Sayımlar:** POST öncesi 0 oturum; rapor 9 oturum, `envelope_mismatch` 1/9, paket hash'i 9/9 kodla damgalı, yama girdisi 0, çıkarılan iddia 0. P19: a=[V, IV], b=[V, IV] (ikisi de tam onarım), c=[IV], d boş; V `envelope_mismatch` ile ayrıca sayıldı. `c_checks`: bir `application_validation` adım hatası, şema reddi yok.
- **Satırlar:** R1a 0/3 (yazılan bölümler), R1b 2/3, R1c 0/1; R7 184,4 s (oluşturmadan iptale; duraklamaya kadar 169,3 s) ve 9 çağrı. Rapor tamamlanmadığı için R2-R6, R8, R9, R11 ölçülemedi (`run_incomplete`); R10 ölçülmedi.

Bütçe: 131 + 9 = 140 / 293 oturum; okur isteği yeni yok (ortak defterde 6 istek kalır). Sunucu durduruldu, 8765'e dokunulmadı; kanıt `../DEIXIS-h9b-run/.local/p9r-h9b/evidence/d/`.

## H9e (3-4 Ekim 2026): B raporu RF6 üzerinde, zincirin son koşusu

**Sert satır aralık dışı:** R2 iki donmuş beklentinin de dışında: yanlış bağlı iddia 4 (en çok 3), kısmen bağlı iddia 18 (en çok 8). R3 ve R4a aralıkta.

**Dondurma:** Ek G (`b3fde0e`). **Karar:** [D202](../decisions.md). Ürün `7188ec8` (RF6), B'nin hazırlanmış verisinin yeni doğrulanmış kopyası `e/data`; korpus B, H9c ve H9d ile aynıdır. Tek koşu; önceki koşularla karşılaştırma bir koşuya karşı bir koşudur, RF4-RF6'nın nedensel etkisi değildir. Okumalar kayıtlı model okumasıdır, insan doğrulaması değildir.

**Koşu:** başlangıç kapısı ve POST öncesi denetim geçti (migration 70, kurtarılan iş 0). POST 22:04:05Z, `run_lkhniruMdgaHTjygyJKu`, rapor `rpt_Rmd2soa3YuCZBBSyQJCF`. Koşu 22:09:51.438Z'de `completed` bitti; gözlemci 22:09:58Z'de saptadı (terminal olay 1614); hiçbir durdurma kuralı tetiklenmedi, iptal gönderilmedi. On model bölümünün onu da `valid`; birleştirme kontrolü raporu kabul etti, rapor `valid`, ürünün kendi incelemesi `reviewed`. H9 serisinde birleştirmeden geçen ilk rapor budur, R1c 1/1. Bu, raporun bilimsel olarak doğru olduğu anlamına gelmez; aşağıdaki satırların çoğu aralık dışında.

- **Sayımlar:** POST öncesi 0 oturum; rapor 23 oturum, `envelope_mismatch` 0; yama dışı 22 oturumun 22'si kodla damgalı. V'nin çıktısı yama yoluna girdi; şema donmuş değerle aynıydı (`f30984c2…`), yama uygulandı, V `valid`. Çıkarılan veya düşürülen iddia 0. P19: a=[V], b=[V] (yama), c=[V], d boş. Adım hatası yok. III, IV, V ve VIII birer şema onarımıyla geçerli oldu (kitin 4 başarısız çağrısı bunlar). Ürünün inceleme adımı 8 bulgu yazdı: 7'si atıf ve çapa desteği, 1'i terim tutarsızlığı (IX.2, `terminology_inconsistent`); geri alınan cümle 0; VI, VII ve dizin terimlerinin iddiası olmadığı için incelenmedi.
- **Okurlar:** ilk okur `claude-opus-5-5` medium (yürütücü, kör değil), 22:11:24Z-22:16:55Z; ikinci okur `claude-sonnet-5-5` medium, boş dizinde donmuş komutla tek istek, 22:17:12Z-22:17:51Z, dönen model aynı, stderr boş. Eşitlik denetimi geçti (54 birim), aktarım 54/54. H9e okur defteri 2 istek, 6 dk 10 s (H9e sınırı 4 istek / 60 dk); ortak H9b defteri 8 isteğin 4'ü, 120 dakikanın 12 dk 21 s'si.

| Satır | Beklenti | H9e sonucu | Aralıkta mı |
|---|---|---|---|
| R1a | ilk denemede geçerli 7-10/10 | 2/10 (VI, dizin terimleri) | hayır |
| R1b | onarımla geçerli ≥9/10 | 10/10 | evet |
| R1c | 1/1 | 1/1 | evet |
| R2 | yanlış bağlı iddia 0-3; kısmen bağlı iddia ≤8 | 30 iddia, 44 bağ: yanlış bağlı iddia 4 (C15, C29 iki okur; C5, C11 yalnız ikinci okur); kısmen bağlı iddia 18; anlaşmazlık 7 | ikisi de hayır |
| R3 | U ≤ max(1, ⌊0,10 N⌋) | N=3, U=0 | evet |
| R4a | `body_refs`'siz iddia 0 | 0 | evet |
| R4b | gövdeden güçlü ≤%10 | 7/15 (%47; D2, D3, D8, D12, D13 iki okur, D9, D10 yalnız ilk okur) | hayır |
| R5 | terim başına ortalama başka ad ≤1 | 13/6 ≈ 2,17 (0, 7, 6, 0, 0, 0) | hayır |
| R6 | 0-6 denklem; ≥3 ise yarısı sayfayla örtüşür | denklem birimi yok | ölçülemedi |
| R7 | 10-30 dk, 15-46 çağrı, 7-13 ardışık tur | 5,8 dk (346,0 s), 23 çağrı, 7 tur | süre hayır (kısa), diğerleri evet |
| R8 | ilk uyumsuzluk %30-70; onarım sonrası kalıpsız ≤%25; geri alınan 0-2 | 33/42 (%79); 27/42 (%64); 0 | ilk iki koşul hayır |
| R9 | girdideki denklemlerin yarısı raporda | 7 çiftin hepsi `no_input_equation`, payda 0 | ölçülemedi |
| R10 | yok | `p15_behavior_is_not_r10` | ölçülmedi |
| R11 | kesilen kayıt 0; `insufficient_evidence` 0-3; eksik pasaj ≤2 | 107 hücre kesildi (IV 54, V 53); 3; 87 pasaj (IV 74, V 13) | birinci ve üçüncü hayır |

- **Girdi kesilmesi B'deki gibi:** IV 16, V 7 hücre gördü. Eksik pasaj sayısı B'deki okur kuralıyla sayıldı; aynı betik `b2/data` üzerinde B'nin 74 ve 13 değerini yeniden üretiyor, H9e bölüm girdileri aynı hücreleri seçtiği için sayılar eşit. VI yine hiç hücre almadı ve "kanıt yok" metni yazdı; VII de.
- **R2 ve R4b:** kısmen işaretlerinin çoğu, çok parçalı bir iddiaya tek parçayı taşıyan çapa alıntısından geliyor (ürünün kendi incelemesi de 7 iddiada atıf ve çapa desteği eksikliği buldu). C15'in alıntısı başka bir sonucu (en büyük hata 7), C29'unki bir kısıt listesini gösteriyor. R4b'de özet, giriş ve sonuç, gövdede olmayan karar değişkenleri (vana açıklığı, tank seviyesi), kısıtlar (enerji ve kütle dengesi, pompa işletim sınırları) ve "tipik talep" ekliyor.
- **R3:** kitin sözlüğü Türkçe yokluk fiillerini yine bulmadı; IV'teki üç yokluk cümlesi ilk okurca eklendi (M2-M4), iki okur da hücreyle uyumlu saydı.
- **R9:** kit bu kez 7 çiftin hepsini kaynak sürümüne eşledi. IV girdisinde Candelieri18b ve Rajabpour18'in donmuş Denklem hücreleri vardı, ama formül satır içi matematikle (`\(…\)`) yazılmıştı; kit, birleştirmeyle aynı ayrıştırıcıyla yalnız `$$` blok matematiğini girdi denklemi sayıyor. Uygun çift kalmadı, payda 0, satır ölçülemedi. Bu bir kit kuralıdır, girdide formül olmadığı anlamına gelmez.

Bütçe: 140 + 23 = 163 / 293 oturum. Sunucu 22:10:47Z'de durduruldu, 8765'e dokunulmadı; kanıt `../DEIXIS-h9b-run/.local/p9r-h9b/evidence/e/`.

**Zincir kapanışı (Ek G):** H9e zincirin tek ve son koşusuydu; H9 rapor ölçüm zinciri burada Ek G gereği kapanır, P10 öncesi H9f yok. Yalnız raporu tamamlama ön koşulu kapandı (R1c 1/1). D205 kararına devreden borçlar: aralık dışı kalite satırları R1a, R2, R4b, R5, R7 süresi, R8 ve R11 (girdi kesilmesi ve eksik pasaj); ölçülemeyen R6 ve R9; ölçülmeyen R10. D157'nin R18, R19 ve R21 ölçümleri yapılmadı ve borç olarak kalır. D205 dondurması B'nin raporunu, o yoksa A2'ninkini adlandırıyor; H9e raporunu (`rpt_Rmd2soa3YuCZBBSyQJCF`) bu ölçümlerde kullanmak açık bir koordinatör değişikliği ve maddeye özgü dondurma kapıları ister.
