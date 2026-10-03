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

A ve A2 birlikte şunu gösterir: RF'in yama şeması canlı API'de reddediliyordu, RF2'den sonra bir istekte kabul edildi ve yama bir bölümü geçerli yaptı. Rapor bu kez başka bir yerde, boş bölümde durdu; bu duruş için ürün tarafında düzeltme (RF3) koordinatör tarafından açıldı. Kol B'nin sonucu ayrı yazılacak.
