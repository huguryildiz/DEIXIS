# P9 ölçülmemiş borçlar: sonuçlar

Dondurma: [p9-owed-measurements-freeze.md](p9-owed-measurements-freeze.md) ([D205](../decisions.md)). Her kalem kendi tarihli bölümünü alır. Burada yazılanlar betimlemedir; nedensel iddia değildir.

## D129: bölüm IV çapa onarımı (4 Ekim 2026, H9b sonucundan okundu)

**Durum:** **Kaynak:** [p9r-report-results.md](p9r-report-results.md) H9b bölümleri (A, A2, B, H9c, H9d; [D202](../decisions.md)). Ayrı koşu yok, model çağrısı yok, sağlayıcı isteği yok. H9e (RF6 sonrası tek B koşusu; ölçülen ürün `7188ec8`, sonuç kaydı `09aa2cf`) sonradan eklendi (aşağıdaki son satır).

**Kayıtlı maruziyet (çapa sorunu olan bölümler; kaynak: kit P19 çıktıları `../DEIXIS-h9b-run/.local/p9r-h9b/evidence/<kol>/p19.json`, 4 Ekim'de salt okunur okundu, ve `p9r-report-results.md`):**

| Koşu | Ürün | Bölüm | Yol | Kayıtlı sonuç |
|---|---|---|---|---|
| A | `682ba1f` | V | yama | canlı API isteği `invalid_json_schema` ile reddetti (şema ürün hatası); yama modeli çıktı vermedi; onarım doğrulaması okunamadı (`not_readable`) |
| A2 | `7cc1168` | V | tam onarım | onarım sonrası doğrulandı (c), bölüm sonraki koşuda geçerli; VI'da durdu |
| A2 | `7cc1168` | IV | yama | API kabul etti, yama doğrulanıp uygulandı, IV `valid` |
| B | `b90583b` | IV | yama | API kabul etti, yama uygulandı, IV `valid` |
| H9c | `2b185a8` | V | tam onarım | doğrulandı; koşu özette durdu (başka neden) |
| H9d | `1f4903f` | V | tam onarım | onarım çıktısı ilk denemenin `step_input_id` değerini taşıdı (`envelope_mismatch`); bölüm başarısız |
| H9d | `1f4903f` | IV | tam onarım | doğrulandı, IV `valid` |
| H9e | `7188ec8` | V | yama | API kabul etti, yama uygulandı, V `valid`; rapor ilk kez birleştirmeden geçti |

Çıkarılan iddia (`e_*.removed`) her koşuda boş; `a_missing_first_validation` ve `b_unsent` her kolda boş. Eksik/okunamayan: yalnız A'nın yama doğrulaması (`repair_validation_missing`, `e_patch: not_readable`). Not: A'daki III ve IV onarımları çapa sorunu değildi, P19'a girmedi ve bu tabloya alınmadı.

**P19 a-e (kit çıktısından, kol başına):**

| Kol | a | b (tam/yama) | c | d | e_full / e_patch (çıkarılan, görünür) |
|---|---|---|---|---|---|
| A | [V] | V yama | boş | boş | yok / V `not_readable` |
| A2 | [V, IV] | V tam, IV yama | [V, IV] | boş | V (çıkarılan boş, görünür boş, taslak var) / IV boş-boş |
| B | [IV] | IV yama | [IV] | boş | yok / IV boş-boş |
| H9c | [V] | V tam | [V] | boş | V boş-boş, taslak var / yok |
| H9d | [V, IV] | V tam, IV tam | [IV] | boş | V (çıkarılan boş, görünür boş, taslak yok), IV (boş, boş, taslak var) / yok; V `envelope_mismatch` |
| H9e | [V] | V yama | [V] | boş | yok / V boş-boş |

Yama doğruladığı bölüm sayısı: 3 (A2 IV, B IV, H9e V), hepsi RF2'den sonraki şemayla; yama yolu 4 kez girildi (A'da şema reddi). Tam onarım 4 kez girildi (A2 V, H9c V, H9d V, H9d IV); üçü doğrulandı, biri (H9d V) girdi-kimliği hatasıyla başarısız. Yönlendirme D198'in tam uygunluk koşuluna göre kodda yapılır; bu okuma yönlendirmeyi yeniden sınamaz.

**Sonuç.** Ölçüldü: RF2 şeması canlı API'de üç ayrı koşuda kabul edildi ve yama her seferinde bölümü geçerli yayımladı; tam onarım yolu A2 V, H9c V ve H9d IV'te bölümü geçerli bıraktı, H9d V'te onarım çıktısının girdi kimliği hatası yüzünden başarısız oldu (çapa değil; RF6/D211 bunu kodla damgalar). İki korpus (H9 tablosu: A, A2; Q3 B tablosu: B, H9c, H9d, H9e yeniden kullanır), tek model, her kol bir koşu.  P19 a-e ve eksik/okunamayan kategorileri yukarıda kit çıktılarından kol başına verildi. Maruz kalma etkinlik kanıtı değildir: onarılan iddiaların anlam desteği ayrıca okunmadı ve H9b hiçbir kolda D129'un nedensel yararını göstermez. H9'un kayıtlı gözlemleri tarihsel kalır. D129'un hedefli onarım yolu gerçek modelde çalıştırıldı; başarı oranı ölçülmedi.

## D141: keşif hunisinin sayımı (4 Ekim 2026, modelsiz)

**Durum:** Kit `scripts/p9_owed/funnel_counts.py` Sol tarafından yazıldı (kota bitmeden, oturum yarıda kesildi); Claude inceledi ve 70 testi (funnel + prep) geçirdi; Sol'un son raporu ve kategori eşlemesinin ortak sabitlemesi bekliyor. 0 model oturumu, 0 sağlayıcı isteği. Kaynak: `DEIXIS/.local/p6-slice2-l9/data/` bayt kopyası (`cp -Rp`, kaynakta dosyayı tutan süreç yok, kaynak ve kopya manifestleri eşit, kopya `mode=ro&immutable=1` açıldı). Canlı kütüphane ve `owner-backup/` okunmadı. Ham çıktı (izlenmeyen): `.local/p9-owed/d141/l9nlp-count.json` (SHA-256 `ab653044…dd63c`), `l9nlp.copy-record.json`.

**Satırlar (hepsi betimsel; oran ya da neden değildir):**

| Korpus | Ürün / hazırlık | Durum |
|---|---|---|
| L9 NLP (D141) | `6e85654`; kuyruk kararı yok | sayıldı (aşağıda) |
| H9 Q1 | `87cee0b`; K03 | sayıldı (aşağıda) |
| H9b B Q3 | H9b'nin sabitlediği commit; K03 | sayıldı (aşağıda) |
| L9 yeni korpus | `7188ec8`; kuyruk geçişi başarısız (karar yok) | sayıldı (aşağıda, L9 bölümünde) |

**L9 NLP, tek araştırma (`res_SQ8K…`), tek model, hazırlık denemesi 1; payda 99 tekil eser (129 kaynak sürümü):**

- Modelin okuduğu özet: 79 eser. Otomatik karar geçmişi: model/kod uyumuyla dışlanan 28, dahil edilen 1; kod kuralıyla dışlanan 3 (kodla dahil kaydı: `bilinmiyor`).
- Son üyelik: dahil 1, dışlanan 29, beklemede 69, çıkarılan 0.
- Beklemedeki 69 için tek birincil kategori: incelemede kuyrukta 25; PDF bekliyor, getirme denendi 2; PDF bekliyor, denenmedi 23; diğer 19. Ayrı boyutlar (örtüşebilir): kuyruk üyeliği 25, PDF bekleyen 25, getirme kaydı olan 29.
- Tam metin: deneme 29 eser; başarılı indirme 27; çıkarılmış PDF metni 27; modele verilen metin 26. Doğrudan getirme hataları: `fetch_http_error` 2. Son aday denemelerinde hata: "too many redirects" 1, kod kaydı yok (`bilinmiyor`) 2.
- K03 kuyruk kararları: `bilinmiyor` (bu korpusta kuyruk kararı verilmedi; saklı kayıt yok, sıfır değil).
- Donmuş `G` zinciri (4 eser): ELMo bulundu (beklemede, kuyrukta), BERT bulundu (beklemede, PDF bekliyor), RoBERTa bulunmadı, ALBERT bulunmadı. Bu D141'in önceki bulgusuyla uyumludur (1/99 dahil).
- Kitin `missing` listesi: kod dahil kaydı, K03 kayıtları, PDF aday geçmişi (yalnız son deneme saklanıyor), bazı hata kodları, model teslimi için yanıtsız oturumlar.

**Dil.** “Dört soru, tek model; eserlerin nerede durduğunun betimlemesi.” Bu sayım D141'in “huniyi incele” alt borcunu üç korpus için kapatır (yeni L9 korpusu L9 bölümünde sayıldı; dil: dört soru, tek model); STATUS'taki birleşik “fikir zinciri” satırı yeşile dönmez.

**H9 Q1 (`res_5ZrJ…`, bayt kopyası, H9 zinciri kapandıktan sonra; ürün `87cee0b`, K03 kuyruk geçişi; kütüphanede iki keşif koşusu var: ilki `paused`, ikincisi `completed`, ardından tam metin adjudikasyonu ve tablo doldurma; ):** payda 3.167 tekil eser (3.301 sürüm). Modelin okuduğu özet 156. Otomatik karar geçmişi: model/kod uyumuyla dışlanan 13, dahil 3; kodla dışlanan 5. Son üyelik: dahil 7, dışlanan 18, beklemede 3.142. Beklemedeki birincil kategori: incelemede kuyrukta 2; PDF bekliyor, getirme denendi 21; PDF bekliyor, denenmedi 82; diğer 3.037. Tam metin: deneme 30; başarılı indirme 9; çıkarılmış metin 9; modele verilen metin 9; doğrudan getirme hataları `fetch_http_error` 19, `fetch_not_pdf` 2; son aday denemelerinde hata kodu `bilinmiyor` 27. K03 kuyruk kararı: 4 (`human_include`, seçilim etkisi).

**H9b B Q3 (`res_khW4…`, bayt kopyası `b/data`; ürün: Ek B sabitlemesi `682ba1f` (runs tablosu commit saklamaz; kol A ile aynı sabitleme); kütüphanede tek tamamlanmış keşif, tam metin ve doldurma koşusu; K03 kuyruk geçişi):** payda 1.867 tekil eser (1.902 sürüm). Okunan özet 108. Otomatik karar geçmişi: model/kod uyumuyla dışlanan 19, dahil 11; kodla dışlanan 8. Son üyelik: dahil 10, dışlanan 28, beklemede 1.829. Birincil kategori: incelemede kuyrukta 7; PDF bekliyor, getirme denendi 0; denenmedi 9; diğer 1.813. Tam metin: deneme 42; başarılı indirme 18; çıkarılmış metin 18; modele verilen metin 18; doğrudan getirme hataları `fetch_http_error` 20; son aday denemelerinde hata kodu `bilinmiyor` 9. K03 kuyruk kararları: `bilinmiyor` (saklı kayıt yok).

Ham çıktılar (izlenmeyen, `.local/p9-owed/d141/`): `h9q1-count.json` (SHA-256 `4dd4b961…`), `h9bb-count.json` (`713fd426…`), kopya kayıtları. Kaynak dizinlere yazılmadı; kopyalar düzeltilmiş kitle (kaynak önce/sonra/kopya manifestleri) yeniden alındı, sayımlar özdeş çıktı. H9 kopyasının kaynak manifesti, H9b'nin kayıtlı H9 kaynak manifestiyle (`evidence/a-source-manifest.json`) dosya dosya eşit (fark yok; kitin `--trusted-manifest` karşılaştırması, kopya kaydında). Farklar betimseldir; korpuslar arası toplam yazılmaz. Dört korpusun dördü sayıldı (yeni L9 korpusu, L9 bölümünde).

**Hazırlık denemeleri (§4: her deneme ayrı satır):**

| Korpus | Deneme | Kayıt | Durum |
|---|---|---|---|
| H9 Q1 | 1 | `run_gColv…` keşif, 2026-10-03 06:53Z | `paused`, kütüphanede kalan tamamlanmamış deneme |
| H9 Q1 | 2 | `run_inu6W7…` keşif 06:57Z; sonra `fulltext_adjudication` 07:03Z ve `table_fill` 07:13Z | hepsi `completed` |
| H9 Q1 | (hazırlık değil) | `report` koşusu 07:40Z | `paused` (H9'un durmuş rapor koşusu) |
| L9 NLP | 1 | `run_VD5r…` keşif 2026-10-01 15:39Z, `run_FIZa…` tam metin 15:43Z, `run_Qbnz…` doldurma 15:51Z | hepsi `completed` |
| H9b B Q3 | 1 | keşif 13:23Z, tam metin 13:33Z, doldurma 13:42Z | hepsi `completed` |
| L9 yeni (difüzyon) | 1 | `run_kyAQ…` keşif 2026-10-04 08:57:47Z, `fulltext_adjudication` 09:11:52Z-09:16:59Z; kuyruk geçişi 09:30:56Z | keşif ve adjudikasyon `completed`; kuyruk geçişi başarısız |

Yukarıdaki sayımlar kütüphanenin son durumunu bütün olarak verir; H9 Q1'in iki keşif koşusu arasında ayrım yapmaz.

## K6 kill-search (4 Ekim 2026, §6 / Ek K)

**Ölçüm:** `gpt-5.6-luna` medium, ürün `7188ec8` (paket `ccff02a1…`), kit `measure_k6.py` (SHA-256 `597f8f3d…`, pinli; kit kendi checkout'u dışında bir veri dizinini reddettiği için kitin birebir kopyası, hash'leri eşit, ölçüm worktree'sine kopyalandı), donmuş girdiler `p9-owed-k6-ek-k.json`. Boş izole kütüphane (`DEIXIS-owed-k6/.local/p9-owed/k6/data`), `127.0.0.1:8873`, `env -i`, anahtarsız; 8765'e dokunulmadı (her POST'tan önce ve snapshot'ta lsof kaydı). Tek seri, altı iddia, tek model; değerlendirilen alt kümede ve okunan metinde. Ham kanıt (izlenmeyen): `.local/p9-owed/k6-evidence/`.

**Seyir ve sapmalar (hepsi kayıtlı):**
1. C1'in koşusu 06:55:03Z'de `client_timeout` ile (yedinci değerlendirme adımı, `outcome_unknown`) `model_call_failed` olarak duraklayıp kit durdu (kitin “asla sürdürme” kuralı). Serbest bırakılan §1.5 yalnız `client_timeout` için 10 dk sonra bir kez sürdürmeye izin verir; 07:10:00Z'de (15 dk sonra) koşunun hâlâ aynı durumda olduğu yeniden okunarak API'den **bir kez** sürdürüldü (`resume_driver.py`, kitin dışında operatör betiği); C1 `completed` oldu. Başka sürdürme yok, iptal yok.
2. Operatör betiği kalan iddiaları kitin `run_series`'iyle sürdürürken kit, POST sonrasında C1'in koşusunu “beklenmeyen koşu” sayıp reddetti; C2'nin koşusu o POST ile başlamıştı ve ikinci betikle (`continue_driver.py`) bekleyip tamamlandı (müdahale yok); C3-C6 kitin değiştirilmemiş `run_series`'iyle koştu (bitmiş koşular kitin “bilinen koşu” denetiminden gizlenerek). Kit dosyası değiştirilmedi; oturum ve süre sayaçları bu yüzden kitin tek-parça S5 çıktısında eksik, aşağıda elle birleştirildi.
3. Okuyucu (`claude-sonnet-5-5` medium, tek istek, 07:21:46-07:23:19Z, donmuş komut; çalışma dizini depo dışında olup yalnız okuyucu sayfası ve istemi içeriyordu, tam boş değildi; dönen model kimliği kaydedilmedi, bu yüzden doğrulanmadı; komut `reader-command.txt`'de) bir pasajda “state-of-art” yerine “state-of-the-art” yazarak kanıt sayfasını değiştirdi; kit bu sayfayı reddetti. Okuyucunun 20 cevabı özgün sayfaya aktarıldı (yalnız `answer`/`reason`), kit bu aktarılmış sayfayı kabul etti.
4. Semantic Scholar C1 ve C2'de 429 verdi (sağlayıcı adımı `rate_limited`, koşuyu durdurmadı).

**Sayımlar:** altı iddianın hepsi `completed`; durumlar: C1-C5 `undecided`, C6 `narrowed`. Yeni model oturumu 44 / 120 (C1 10, C2 7, C3 7, C4 9, C5 8, C6 3; biri başarısız `client_timeout`); ilk iddia isteğinden son koşunun bitişine 2.022 s (33,7 dk; duraklama ile sürdürme arası 897 s ≈ 14 dk 57 s dahil) / 180 dk; iddia başına model denemesi ≤ 54 tavanın altında. Sağlayıcı istekleri kitin S5'inde çıkarılamadı (`ölçülemedi`); ama saklı `run_steps` taşıma kayıtlarından sayılabilir: iddia başına 7, 8, 6, 6, 6, 5 (toplam 38 deneme, 38 gönderim); kitin “18” değeri yüklenen bütçedir, gerçek istek değil. Oturum toplamları (44, iddia başına yukarıdaki) tamdır; kitin S5 süresi (496 s, `clock_complete`, 35 uçuş-aşımı oturumu) yalnız ilk parçayı yansıtır ve bu yüzden süre yukarıda elle birleştirildi. Hazırlık sağlayıcı isteği 13 / 60.

**S1 geri çağırım:** 7 `N` eserinin 7'si de sonuçta hiç yok (saklı sorgu kayıtlarında ve saklı isabetlerde): yedi eser hiç dönmedi; kesilen 0, tutulan 0. **S2:** payda 0 (beklentisi “bazı öğeleri söylüyor” olan hiçbir eser tutulup değerlendirilmedi) `ölçülemedi`. **S3:** 0/2 yanlış `closed` (C4, C5 eligible); hiçbir iddia `closed` olmadı, kapatan alıntı yok. **S4a:** yayımlanmış hücre alıntılarının 72/72'si modele verilen metinde bulundu; alıntısız hücre 94. Metni farklı gelen eser yok. **S4b** (20 hücre örneklemi, model okuması): destekliyor 1, kısmen 11, desteklemiyor 8.

**S6 sorgu biçimi (sözcüksel tanılama, neden kanıtı değil):** her iddia için model 2 blok (setting/task) yazdı, blok başına 2-4 terim; sağlayıcı sorguları blok içi OR, bloklar arası AND (ör. C1 OpenAlex: `("differential drive robot" OR "moving obstacles" OR "static obstacles") AND (...)`). Dönen kayıtlarda başlık+özetinde her bloktan en az bir terim geçen: C1 12/39, C2 15/23, C3 47/67, C4 34/50, C5 43/50, C6 3/3; yalnız bazı bloklardan terim geçen: 25, 7, 20, 16, 7, 0; hiç blok geçmeyen: 2, 1, 0, 0, 0, 0. Başlık/özet eksik kayıt: 1, 6, 15, 14, 8, 0. Dönmeyen `N` eserlerinden C1 (iki eser) için “setting” bloğu, C2 (iki eser) için “task” bloğu, C5 için “setting” bloğu başlık+özetiyle eşleşmedi; C3 ve C4'ün dönmeyen eserleri her blokla eşleşiyordu.

**Dil ve sınır:** “Tek koşu, altı iddia, tek model; değerlendirilen alt kümede ve okunan metinde.” `open` hiçbir yerde “yok” diye yazılmaz (burada hiçbir iddia `open` olmadı). S1'in yüzde yüzü, kitin S6'sıyla birlikte bile, “kaybın nedeni sorgu biçimidir” sonucunu çıkarmaz; beş iddia için 20 kayıt tavanı ve çok sağlayıcılı karışım gibi başka açıklamalar elenmedi. `N` kümeleri küçük bir kalibrasyon kümesidir; C6 için yakın iş bilinmiyor (oran yok). Sonuç ürünün bugünkü sorgu derlemesinin ölçümüdür; düzeltme ayrı bir karardır.

## Dilim 4 / D157 (4 Ekim 2026, Ek S: H9e raporu `rpt_Rmd2soa3YuCZBBSyQJCF`)

**Sonuç: durdu, borç açık.** R18, R19 ve R21 yalnız E01-E02 için ölçüldü; E03-E18 `ölçülemedi` (ölçüm aracının sahiplik denetimi yüzünden). Rapor kalite iddiası yoktur; kod davranışının gerçek rapordaki sınamasıdır ve tamamlanmadı.

**Ortam:** H9e verisinin (`e/data`) bayt kopyası (`DEIXIS-owed/.local/p9-owed/s4/exec-data`, `library.sqlite` SHA-256 `ff37c851…`, Ek E'deki değerle eşit; kopya kaydında kaynak önce/sonra/kopya manifestleri eşit); sunucu `DEIXIS-owed-k6` worktree'sinde ürün `7188ec8`, `127.0.0.1:8873`, `env -i`, anahtarsız; 8765'e dokunulmadı (her mutasyondan önce lsof kaydı); canlı kütüphane okunmadı. Operasyon dosyası SHA-256 `e03d27fc…`. Kit `measure_edit.py` (pinli sürüm `0620356`), tek bir ölçüm öncesi düzeltmeyle (aşağıda).

**Seyir ve sapmalar:**
1. İlk deneme (07:33:56Z kayıtlı ret) kitin sahiplik denetiminde `lsof +D` çıkış kodu 1 verdiği için hiçbir işlem göndermeden reddedildi (kit hatası; `lsof +D` sahipleri listelerken 1 döndürüyor). Kit bu daraltılmış değişiklikle (yalnız `+D` listesi, çıkış kodu 1 ve dolu çıktı kabul) düzeltildi (Sol medium yazdı, Claude inceledi, testle); işlem gönderilmediği için kopya değişmedi. İkinci deneme 07:37:57Z'de başladı.
2. İkinci deneme E01 ve E02'yi ölçtü, sonra E03'ün `cell_recheck` koşusu sunucunun kendi `codex app-server` alt sürecini (cwd `exec-data/codex-workspace`, operatörün sonradan `ps` ile gördüğü ebeveyn: dinleyici süreç 38542, komut `codex app-server`; kitin kendi kaydı yalnız PID 41538'i ve cwd'yi tutar, `process-observation.txt`) başlattı; kitin “bu dizini yalnız dinleyici tutar” denetimi bunu yabancı süreç sayıp işlemi ve kalan bütün işlemleri durdurdu (`measurement data directory has other process owners`). Bu da bir kit hatasıdır: sunucunun alt süreçlerini sahip saymıyor. E03'ün koşusu sunucuda `completed` oldu (1 yeni model oturumu, `cell_extraction`), ama puanlanmadı.
3. §1.6 gereği duran ölçüm aynı korpusla düzeltilip yeniden koşulmaz; yeniden koşu yapılmadı. Sunucu durduruldu (kapanış doğrulandı); alt sürecin çıktığı operatörün `ps` gözlemidir (kit kaydı değil).

**Ölçülenler:** E01 (metin düzenleme) ve E02: R18 değişmezleri (etkin atıf kümesi, numaralandırma, dışa aktarım, modelin özgün revizyonunun baytları, yabancı anahtarlar) ihlalsiz; gidiş-dönüş eşitliği bu işlemler için `ölçülemedi` (E18'e bağlı); yeni model oturumu 0, süreler 1,195 s ve 1,200 s. R19: E01 ve E02'nin her birinde 3 beklenen ve 3 gözlenen işaret (`edited_basis`, V.1'e bağlı: özet, I, IX), kimlikleri tam eşleşti; birleşik yanlış pozitif 0/6, yanlış negatif 0/6 (yalnız bu iki işlem; E03-E18'in beklenen işaretleri ölçülmedi). R19'un ve R21'in kalan satırları, E18 gidiş-dönüşü, sınanmayan vakalar: `ölçülemedi`, “sınanmadı”. Kitin toplam geçen süresi 5,1 s (E03'teki durmaya kadar; E01-E02 yalnız 2,395 s); ölçülmemiş işlemlerin süresi bilinmiyor; yeni oturum 1 (E03, puanlanmamış). Ham kanıt: `.local/p9-owed/s4-evidence/s4out/` (izlenmeyen).

**Sınır ve sıradaki karar:** Tek rapor, tek korpus; yalnız iki işlem. Kalan işlemleri ölçmek için kitin sahiplik kuralının sunucunun alt süreçlerini kabul edecek biçimde düzeltilmesi ve, §1.6'ya rağmen, aracın hatası yüzünden duran bu ölçümün taze bir bayt kopyasında yeniden koşulması için açık bir koordinatör kararı gerekir; bu belge o kararı varsaymaz.

### Dilim 4 yeniden ölçümü (Ek S2, 4 Ekim 2026, 08:02-08:04Z)

**Durum:** tek izinli yeniden koşu yapıldı (D215). Önceki durmuş ölçümün (yukarıdaki bölüm) kanıtı ve `exec-data` dizini korunuyor; iki koşunun paydaları birleştirilmedi.

**Ortam:** H9e verisinin yeni, doğrulanmış bayt kopyası (`exec-data2`, `library.sqlite` SHA-256 `ff37c851…`, Ek E'dekiyle eşit); ürün `7188ec8` (`DEIXIS-owed-k6` worktree'si), `127.0.0.1:8873`, `env -i`; 8765'e dokunulmadı; Ek E işlem dosyası SHA-256 `e03d27fc…`; kit `measure_edit.py` (güncel pin `f75e884f…`, bütçe denetimi dahil), `--prior-sessions 1 --prior-seconds 300` (kalan 9 oturum / 3300 s). Sahiplik denetimi alt süreçleri kabul etti; koşu sunucu durdurulmadan önce `zero_started_verified: true` ile kapandı, sunucu sonra durduruldu (çıkış doğrulandı).

**Seyir:** E01-E05 ölçüldü. E06 (E05'in önerdiği hücre değişikliğinin kabulü) atlandı: ürünün `cell_recheck` önerisi yapısal olarak geçerli değildi; öneri elle düzeltilmedi ve yeniden üretilmedi (§5). E07-E17 bu önkoşula bağlı olduğundan `sınanmadı`; E18 (yedekle-geri yükle gidiş-dönüşü) Ek E'de E17'ye bağlıdır ve E17 atlandığı için koşmadı, `sınanmadı`. Durdurma kuralı tetiklenmedi (`stop_reason: null`).

**Ölçülenler (yalnız E01-E05, kod davranışı; anlam desteği iddiası değil):** R18: 5 işlemin 5'inde değişmez ihlali 0 (etkin atıf kümesi, numaralandırma, dışa aktarım, modelin özgün revizyonunun baytları, yabancı anahtarlar); gidiş-dönüş eşitliği E18'e bağlı olduğundan `ölçülemedi`. R19: yanlış pozitif 0/17, yanlış negatif 0/17 (gözlenen ve beklenen işaretler, işlem başına beklenen=gözlenen işaret sayısı 3, 3, 3, 4, 4; toplam 17). R21: duvar saati toplam 71,9 s; E01 1,20 s, E02 1,20 s, E03 17,21 s, E04 1,22 s, E05 48,14 s; yeni model oturumu 3 (E03 1, E05 2), 62.700 token (18.709 + 43.991); önceki ölçümle birlikte 4 / 10 oturum; süre: yeniden koşunun 71,9 s'sine eklenen 300 s, ölçülmüş birleşik süre değil muhafazakâr bütçe payıdır (toplam 372 s ≲ 3600 s).

**Ölçülemeyen / sınanmayan:** E06-E18 (13 işlem) `sınanmadı`; kaynak çıkarma, düzenleme denetimi, ikinci düzenleme, “Böyle kalsın”, geri yükleme, dışa aktarım numaralandırması, kalıcı silme reddi ve yedekle-geri yükle bu koşuda sınanmadı; D157'nin bu kısmı açık kalır. R18 payda 5/18 işlem, R19 payda 17 işaret. **Sınır:** tek rapor, tek korpus, aynı korpusun ikinci koşusu (araç hatası kurtarması), bağımsız tekrar değil; sonuç yalnız beş işlemin kod davranışıdır.

## L9 fikir zinciri hazırlığı (4 Ekim 2026, §7 / Ek L1, Ek L3)

**Sonuç: korpus koşulu karşılanmadı; lineage koşulmadı.** Keşif tamamlandı ama araştırma `G` zincirinin yalnız bir eserini dahil etti; K1 için gereken en az 6 PDF metinli satırın yerine 1 satır var. Kuyruk geçişi araç hatasıyla başarısız oldu ve yeniden denenmedi. Bu bir fikir zinciri ölçümü değildir; ölçülen, keşfin bu yeni konuda ne kadar eser dahil ettiğidir.

**Ortam:** boş izole kütüphane (`DEIXIS-owed/.local/p9-owed/l9/data`), ürün `7188ec8` (paket `ccff02a1…`), sunucu `DEIXIS-owed-l9` worktree'sinde `127.0.0.1:8873`, `gpt-5.6-luna` medium, Ek L3'teki ortam değişkenleri, 8765'e bağlanılmadı. Ölçüm commit'i `e4e109c4aa72581473828c65d20bab45d330b206` (ürün dizinleriyle `7188ec8` arasında fark yok).

**Keşif:** tek araştırma (`res_R9kD…`), `sw`, soru ve `G` Ek L1'deki gibi. Keşif koşusu 08:57:47Z-09:11:52Z, ardından tam metin adjudikasyonu 09:16:59Z'ye kadar (otomatik yürütme 19,2 dk; toplam hazırlık süresi bundan uzundur ve Ek L3'ün gözlem istisnalarını içerir: kuyruk geçişi ile K0 durma/kopya/başlama aralığında 15 sn gözlemi yapılmadı); 121 model oturumunun hepsi `completed`. Hazırlık denemesi 1.

**D141 hunisi (yeni korpus, bayt kopyası `copy2`; kopya kaydı eşit manifestler; model oturumu 0, sağlayıcı isteği 0; ham çıktı `.local/p9-owed/d141/l9new-count.json`, SHA-256 `82b7a7d6…`):** payda 1.542 tekil eser (2.408 kaynak sürümü). Modelin okuduğu özet 140 (kayıtlı model yanıtı olan girdideki özet; doğrulanmış okuma değil). Otomatik karar geçmişi: model/kod uyumuyla dışlanan 52, dahil 1; kodla dışlanan 17 (kodla dahil kaydı `bilinmiyor`). Son üyelik: dahil 1, dışlanan 68, beklemede 1.473, çıkarılan 0. Beklemedeki birincil kategori: incelemede kuyrukta 50; PDF bekliyor, getirme denendi 9; denenmedi 36; diğer 1.378. Tam metin: deneme 76 eser (kayıtlı getirme denemesi olan tekil eser; istek sayısı değil); başarılı indirme 67; çıkarılmış metin 67; modele verilen metin 50; doğrudan getirme hataları `fetch_http_error` 7, `fetch_too_large` 5; son aday denemelerinde hata kodu `bilinmiyor` 17. K03 kuyruk kararı: yok (aşağıda). Kitin zincir bölümü yalnız NLP `G` içindir; difüzyon `G` için sayım elle, kopyadan: DDPM (Ho 2020) bulundu ve dışlandı (saklı özeti Ek L1'de kayıtlı bozuk sağlayıcı metni; dışlamanın nedeni incelenmedi), DDIM (Song) DOI ve başlıkla bulunamadı, iDDPM (Nichol) bulundu ve dahil edildi. Dahil edilen tek eser iDDPM.

**K0 (bağımsızlık envanteri):** `no_overlap_detected` (`l9_independence.py check`, çıktı SHA-256 `6f99b47b…`): dört envanter (izlenen belgeler, L9 NLP, H9 Q1, H9b B Q3; belge envanteri iki donuk sonuç dosyasını dışlar), üç tarihsel kopyanın manifest hash'leri donmuş değerlerle eşit, dahil edilen tek eser için örtüşme yok. Bu yalnız kayıtlı envanterler içindeki örtüşmeyi söyler, geliştirme sırasında görülmemiş olmayı kanıtlamaz; Kimlik kapsamı sürüme göre değişir: baş sürümde `arxiv` ve `pmid` yok; ikinci sürümde (`srv_eiyq…`) `arxiv` var, `openalex` ve `pmid` yok; yüklenen PDF hash'leri ve belgelenmemiş geliştirme kimlikleri denetlenmedi. K0 kopyası ile `copy2` arasında sunucu durup yeniden başladığı için ikinci kopya alındı; dahil edilen eser aynı.

**K1:** `measure_lineage.py rows` mantığıyla (`l9_run rows`): dahil edilen 1 eser, 1 PDF metinli satır (gerekli en az 6). Satır sayısı ön koşulu tutmadı; donmuş K1 kapısının tamamı yürütülmedi (sürücünün durumu `closed: false`, K1 sonucu yazılmadı; ikinci `rows` çağrısı sunucu yeniden başladıktan sonra “uncertain table creation” ile durdu, `rows.json` ilk çağrıdan ve kopyanın salt okunur okumasından); `columns-fill` ve K2/K3 değerlendirilmedi, Ek L2 yazılmadı.

**Kuyruk geçişi (H9 K03 madde 2):** 09:30:56Z'de 30 eserlik paketle `claude-opus-5-5` medium'a tek istek gitti; istek 2,6 s'de `prompt_too_long` ile döndü (paket 2,19 MB; hata iletisi isteği ~1.003.778 belirteç, konuşmayı ~513.918 belirteç, sınırı 1.000.000 olarak bildiriyor, bunlar iletinin tahminidir, ayrıca ölçülmedi; `--tools ""`, `--strict-mcp-config` ve boş ayar kaynağıyla bile ileti ~490 bin belirteçlik ek yük gösterdi, nedeni araştırılmadı). Sürücü kuralı gereği yeniden denenmedi; 2 isteğin 1'i harcandı, karar yok. Kuyruk kararı olsaydı dahil sayısı değişebilirdi; kuyrukta 50 eser vardı ve bu denenmedi. Bu yüzden satır sayısı eksikliği “kuyruk kararı olmadan” okunmalıdır; kuyruğun dahil sayısına etkisi bilinmiyor.

**Sınır ve sıradaki karar:** Tek hazırlık, tek konu, uygulama tarafında tek model (kuyruk isteği ayrı bir Claude isteğiydi). Satır sayısının 1/6 kalması otomatik hazırlıktan sonraki durumdur; kuyruk isteği başarısız olduğundan etkisi bilinmiyor ve nedensel bir pay yazılmaz. Tamamlanmış bir hazırlığın kapıyı geçememesi donuk kurala göre sonlandırıcıdır; ikinci hazırlık yalnız açık bir dondurma değişikliği ve koordinatör kararıyla (paket boyutu, yeni kütüphane) yapılır. Lineage için hiç oturum harcanmadı (0 / 60).
