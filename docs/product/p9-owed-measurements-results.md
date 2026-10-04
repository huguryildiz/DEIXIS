# P9 ölçülmemiş borçlar: sonuçlar

Dondurma: [p9-owed-measurements-freeze.md](p9-owed-measurements-freeze.md) ([D205](../decisions.md)). Her kalem kendi tarihli bölümünü alır. Burada yazılanlar betimlemedir; nedensel iddia değildir.

## D129: bölüm IV çapa onarımı (4 Ekim 2026, H9b sonucundan okundu)

**Durum:** **Kaynak:** [p9r-report-results.md](p9r-report-results.md) H9b bölümleri (A, A2, B, H9c, H9d; [D202](../decisions.md)). Ayrı koşu yok, model çağrısı yok, sağlayıcı isteği yok. H9e (RF6 sonrası tek B koşusu; ölçülen ürün `7188ec8`, sonuç kaydı `09aa2cf`) sonradan eklendi (aşağıdaki son satır).

**Kayıtlı maruziyet (hücre çapası onarımı, ürün sürümüne göre):**

| Koşu | Ürün | Bölüm | Yol | Kayıtlı sonuç |
|---|---|---|---|---|
| A | `682ba1f` | V | yama | canlı API isteği `invalid_json_schema` ile reddetti (şema ürün hatası); yama modeli çıktı vermedi |
| A | `682ba1f` | III | tam onarım | iptalle kesildi (sonuç yok) |
| A | `682ba1f` | IV | tam onarım | IV onarımdan sonra `valid` (p9r-report-results.md, kol A) |
| A2 | `7cc1168` | IV | yama | API kabul etti, yama doğrulanıp uygulandı, IV `valid` |
| A2 | `7cc1168` | V | tam onarım | kayıtta ayrıca geçerlilik sonucu yok; koşu VI'da durdu (V geçerli sayıldı: II-V `valid`) |
| B | `b90583b` | IV | yama | API kabul etti, yama uygulandı, IV `valid` |
| H9c | `2b185a8` | V | tam onarım | bölüm geçerli; koşu özette durdu (başka neden) |
| H9d | `1f4903f` | V | tam onarım | onarım çıktısı ilk denemenin `step_input_id` değerini taşıdı (`envelope_mismatch`); bölüm başarısız |
| H9d | `1f4903f` | IV | tam onarım | IV `valid` |
| H9e | `7188ec8` | V | yama | API kabul etti, yama uygulandı, V `valid`; rapor ilk kez birleştirmeden geçti |

Çıkarılan iddia (`repair_dropped_*`) her koşuda 0. Yama doğruladığı bölüm sayısı: 3 (A2 IV, B IV, H9e V), hepsi RF2'den sonraki şemayla. Yönlendirme D198'in tam uygunluk koşuluna göre kodda yapılır; bu okuma yönlendirmeyi yeniden sınamaz.

**P19 sayımları (kayıtlı olduğu gibi, `p9r-report-results.md`; tanımlar D202 Ek B.5):** A: a=[V], b=1, c=0, d=0. A2: a=[V, IV], b=2 (V tam, IV yama), c=2, d=0. B: a=[IV], b=1, c=1, d=0, e boş. H9c: a=[V], b=1, c=1, d=0. H9d: a=[V, IV], b=[V, IV] (ikisi tam onarım), c=[IV], d boş, `envelope_mismatch` V'te ayrıca. H9e: a=[V], b=[V] (yama), c=[V], d boş. Eksik/okunamayan kategorileri: bu kayıtlarda ayrıca bildirilmemiş (yok demek değildir; kaynakta yazılı olmayanı yeniden üretmedim). Yamanın (e) uyarlaması yalnız B ve H9e'de ayrı satır olarak yazıldı (B: boş).

**Sonuç.** Ölçüldü: RF2 şeması canlı API'de üç ayrı koşuda kabul edildi ve yama bir bölümü geçerli yayımladı; tam onarım yolu (A III iptalle kesildi, sonuçsuz; A IV geçerli) A2 V, H9c V ve H9d IV'te bölümü geçerli bıraktı, H9d V'te onarım çıktısının girdi kimliği hatası yüzünden başarısız oldu (çapa değil; RF6/D211 bunu kodla damgalar). İki korpus (H9 tablosu: A, A2; Q3 B tablosu: B, H9c, H9d, H9e yeniden kullanır), tek model, her kol bir koşu. P19 a-e ve eksik/okunamayan kategorilerinin kol başına tam dökümü bu belgede yok; kaynak sayımlar `p9r-report-results.md` ve H9b kitinin kayıtlarındadır, burada yeniden üretilmedi. Maruz kalma etkinlik kanıtı değildir: onarılan iddiaların anlam desteği ayrıca okunmadı ve H9b hiçbir kolda D129'un nedensel yararını göstermez. H9'un kayıtlı gözlemleri tarihsel kalır. D129'un hedefli onarım yolu gerçek modelde çalıştırıldı; başarı oranı ölçülmedi.

## D141: keşif hunisinin sayımı (4 Ekim 2026, modelsiz)

**Durum:** Kit `scripts/p9_owed/funnel_counts.py` Sol tarafından yazıldı (kota bitmeden, oturum yarıda kesildi); Claude inceledi ve 70 testi (funnel + prep) geçirdi; Sol'un son raporu ve kategori eşlemesinin ortak sabitlemesi bekliyor. 0 model oturumu, 0 sağlayıcı isteği. Kaynak: `DEIXIS/.local/p6-slice2-l9/data/` bayt kopyası (`cp -Rp`, kaynakta dosyayı tutan süreç yok, kaynak ve kopya manifestleri eşit, kopya `mode=ro&immutable=1` açıldı). Canlı kütüphane ve `owner-backup/` okunmadı. Ham çıktı (izlenmeyen): `.local/p9-owed/d141/l9nlp-count.json` (SHA-256 `ab653044…dd63c`), `l9nlp.copy-record.json`.

**Satırlar (hepsi betimsel; oran ya da neden değildir):**

| Korpus | Ürün / hazırlık | Durum |
|---|---|---|
| L9 NLP (D141) | `6e85654`; kuyruk kararı yok | sayıldı (aşağıda) |
| H9 Q1 | `87cee0b`; K03 | sayıldı (aşağıda) |
| H9b B Q3 | H9b'nin sabitlediği commit; K03 | sayıldı (aşağıda) |
| L9 yeni korpus | §7 | bekliyor: L9 hazırlığı henüz yok |

**L9 NLP, tek araştırma (`res_SQ8K…`), tek model, hazırlık denemesi 1; payda 99 tekil eser (129 kaynak sürümü):**

- Modelin okuduğu özet: 79 eser. Otomatik karar geçmişi: model/kod uyumuyla dışlanan 28, dahil edilen 1; kod kuralıyla dışlanan 3 (kodla dahil kaydı: `bilinmiyor`).
- Son üyelik: dahil 1, dışlanan 29, beklemede 69, çıkarılan 0.
- Beklemedeki 69 için tek birincil kategori: incelemede kuyrukta 25; PDF bekliyor, getirme denendi 2; PDF bekliyor, denenmedi 23; diğer 19. Ayrı boyutlar (örtüşebilir): kuyruk üyeliği 25, PDF bekleyen 25, getirme kaydı olan 29.
- Tam metin: deneme 29 eser; başarılı indirme 27; çıkarılmış PDF metni 27; modele verilen metin 26. Doğrudan getirme hataları: `fetch_http_error` 2. Son aday denemelerinde hata: "too many redirects" 1, kod kaydı yok (`bilinmiyor`) 2.
- K03 kuyruk kararları: `bilinmiyor` (bu korpusta kuyruk kararı verilmedi; saklı kayıt yok, sıfır değil).
- Donmuş `G` zinciri (4 eser): ELMo bulundu (beklemede, kuyrukta), BERT bulundu (beklemede, PDF bekliyor), RoBERTa bulunmadı, ALBERT bulunmadı. Bu D141'in önceki bulgusuyla uyumludur (1/99 dahil).
- Kitin `missing` listesi: kod dahil kaydı, K03 kayıtları, PDF aday geçmişi (yalnız son deneme saklanıyor), bazı hata kodları, model teslimi için yanıtsız oturumlar.

**Dil.** “Üç (L9 hazırlanırsa dört) soru, tek model; eserlerin nerede durduğunun betimlemesi.” Bu sayım D141'in “huniyi incele” alt borcunu üç korpus için kapatır (yeni L9 korpusu hariç, bekliyor); STATUS'taki birleşik “fikir zinciri” satırı yeşile dönmez.

**H9 Q1 (`res_5ZrJ…`, bayt kopyası, H9 zinciri kapandıktan sonra; ürün `87cee0b`, K03 kuyruk geçişi; kütüphanede iki keşif koşusu var: ilki `paused`, ikincisi `completed`, ardından tam metin adjudikasyonu ve tablo doldurma; ):** payda 3.167 tekil eser (3.301 sürüm). Modelin okuduğu özet 156. Otomatik karar geçmişi: model/kod uyumuyla dışlanan 13, dahil 3; kodla dışlanan 5. Son üyelik: dahil 7, dışlanan 18, beklemede 3.142. Beklemedeki birincil kategori: incelemede kuyrukta 2; PDF bekliyor, getirme denendi 21; PDF bekliyor, denenmedi 82; diğer 3.037. Tam metin: deneme 30; başarılı indirme 9; çıkarılmış metin 9; modele verilen metin 9; doğrudan getirme hataları `fetch_http_error` 19, `fetch_not_pdf` 2; son aday denemelerinde hata kodu `bilinmiyor` 27. K03 kuyruk kararı: 4 (`human_include`, seçilim etkisi).

**H9b B Q3 (`res_khW4…`, bayt kopyası `b/data`; ürün: Ek B sabitlemesi `682ba1f` (runs tablosu commit saklamaz; kol A ile aynı sabitleme); kütüphanede tek tamamlanmış keşif, tam metin ve doldurma koşusu; K03 kuyruk geçişi):** payda 1.867 tekil eser (1.902 sürüm). Okunan özet 108. Otomatik karar geçmişi: model/kod uyumuyla dışlanan 19, dahil 11; kodla dışlanan 8. Son üyelik: dahil 10, dışlanan 28, beklemede 1.829. Birincil kategori: incelemede kuyrukta 7; PDF bekliyor, getirme denendi 0; denenmedi 9; diğer 1.813. Tam metin: deneme 42; başarılı indirme 18; çıkarılmış metin 18; modele verilen metin 18; doğrudan getirme hataları `fetch_http_error` 20; son aday denemelerinde hata kodu `bilinmiyor` 9. K03 kuyruk kararları: `bilinmiyor` (saklı kayıt yok).

Ham çıktılar (izlenmeyen, `.local/p9-owed/d141/`): `h9q1-count.json` (SHA-256 `4dd4b961…`), `h9bb-count.json` (`713fd426…`), kopya kayıtları. Kaynak dizinlere yazılmadı; kopyalar düzeltilmiş kitle (kaynak önce/sonra/kopya manifestleri) yeniden alındı, sayımlar özdeş çıktı. H9 kopyasının kaynak manifesti, H9b'nin kayıtlı H9 kaynak manifestiyle (`evidence/a-source-manifest.json`) dosya dosya eşit (fark yok; kitin `--trusted-manifest` karşılaştırması, kopya kaydında). Farklar betimseldir; korpuslar arası toplam yazılmaz. Dört korpustan üçü sayıldı; yeni L9 korpusu bekliyor.

**Hazırlık denemeleri (§4: her deneme ayrı satır).** H9 Q1: (1) `run_gColv…` keşif koşusu `paused` (2026-10-03 06:53Z), kütüphanede kalan, tamamlanmamış; (2) `run_inu6W7…` keşif `completed` (06:57Z), ardından `fulltext_adjudication` `completed` (07:03Z) ve `table_fill` `completed` (07:13Z); ayrıca `report` koşusu `paused` (07:40Z, H9'un durmuş rapor koşusu, hazırlık değil). Sayımlar kütüphanenin son durumunu bütün olarak verir; iki keşif koşusu arasında ayrım yapmaz. H9b B Q3: tek hazırlık, 13:23Z keşif `completed`, 13:33Z tam metin `completed`, 13:42Z doldurma `completed`.
