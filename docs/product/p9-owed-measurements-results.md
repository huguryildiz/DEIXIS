# P9 ölçülmemiş borçlar: sonuçlar

Dondurma: [p9-owed-measurements-freeze.md](p9-owed-measurements-freeze.md) ([D205](../decisions.md)). Her kalem kendi tarihli bölümünü alır. Burada yazılanlar betimlemedir; nedensel iddia değildir.

## D129: bölüm IV çapa onarımı (4 Ekim 2026, H9b sonucundan okundu)

**Durum:** *Sol review pending (Codex quota until 10 Oct).* Yazan ve inceleyen aynı şirket (Claude); Sol incelemesi bekliyor.

**Kaynak:** [p9r-report-results.md](p9r-report-results.md) H9b bölümleri (A, A2, B, H9c, H9d; [D202](../decisions.md)). Ayrı koşu yok, model çağrısı yok, sağlayıcı isteği yok. H9e (RF6 sonrası tek B koşusu) bu okumaya dahil değildir; sonucu D202'ye ayrıca yazılır.

**Kayıtlı maruziyet (hücre çapası onarımı, ürün sürümüne göre):**

| Koşu | Ürün | Bölüm | Yol | Kayıtlı sonuç |
|---|---|---|---|---|
| A | `682ba1f` | V | yama | canlı API isteği `invalid_json_schema` ile reddetti (şema ürün hatası); yama modeli çıktı vermedi |
| A | `682ba1f` | III | tam onarım | iptalle kesildi (sonuç yok) |
| A2 | `7cc1168` | IV | yama | API kabul etti, yama doğrulanıp uygulandı, IV `valid` |
| A2 | `7cc1168` | V | tam onarım | kayıtta ayrıca geçerlilik sonucu yok; koşu VI'da durdu (V geçerli sayıldı: II-V `valid`) |
| B | `b90583b` | IV | yama | API kabul etti, yama uygulandı, IV `valid` |
| H9c | `2b185a8` | V | tam onarım | bölüm geçerli; koşu özette durdu (başka neden) |
| H9d | `1f4903f` | V | tam onarım | onarım çıktısı ilk denemenin `step_input_id` değerini taşıdı (`envelope_mismatch`); bölüm başarısız |
| H9d | `1f4903f` | IV | tam onarım | IV `valid` |

Çıkarılan iddia (`repair_dropped_*`) her koşuda 0. Yama doğruladığı bölüm sayısı: 2 (A2 IV, B IV), ikisi RF2'den sonraki şemayla. Yönlendirme D198'in tam uygunluk koşuluna göre kodda yapılır; bu okuma yönlendirmeyi yeniden sınamaz.

**Sonuç.** Ölçüldü: RF2 şeması canlı API'de iki ayrı koşuda, iki ayrı bölümde kabul edildi ve yama bir bölümü geçerli yayımladı; tam onarım yolu (A III iptalle kesildi, sonuçsuz) A2 V, H9c V ve H9d IV'te bölümü geçerli bıraktı, H9d V'te onarım çıktısının girdi kimliği hatası yüzünden başarısız oldu (çapa değil; RF6/D211 bunu kodla damgalar). Tek korpus (Q3 B tablosu ile H9 tablosu), tek model, her kol bir koşu. Maruz kalma etkinlik kanıtı değildir: onarılan iddiaların anlam desteği ayrıca okunmadı ve H9b hiçbir kolda D129'un nedensel yararını göstermez. H9'un kayıtlı gözlemleri tarihsel kalır. D129'un hedefli onarım yolu gerçek modelde çalıştırıldı; başarı oranı ölçülmedi.

## D141: keşif hunisinin sayımı (4 Ekim 2026, modelsiz)

**Durum:** *Sol review pending (Codex quota until 10 Oct).* Kit `scripts/p9_owed/funnel_counts.py` Sol tarafından yazıldı (kota bitmeden, oturum yarıda kesildi); Claude inceledi ve 70 testi (funnel + prep) geçirdi; Sol'un son raporu ve kategori eşlemesinin ortak sabitlemesi bekliyor. 0 model oturumu, 0 sağlayıcı isteği. Kaynak: `DEIXIS/.local/p6-slice2-l9/data/` bayt kopyası (`cp -Rp`, kaynakta dosyayı tutan süreç yok, kaynak ve kopya manifestleri eşit, kopya `mode=ro&immutable=1` açıldı). Canlı kütüphane ve `owner-backup/` okunmadı. Ham çıktı (izlenmeyen): `.local/p9-owed/d141/l9nlp-count.json` (SHA-256 `ab653044…dd63c`), `l9nlp.copy-record.json`.

**Satırlar (hepsi betimsel; oran ya da neden değildir):**

| Korpus | Ürün / hazırlık | Durum |
|---|---|---|
| L9 NLP (D141) | `6e85654`; kuyruk kararı yok | sayıldı (aşağıda) |
| H9 Q1 | `87cee0b`; K03 | bekliyor: kaynak `../DEIXIS-h9run` bu oturumda yasak; koordinatör serbest bırakınca |
| H9b B Q3 | H9b'nin sabitlediği commit; K03 | bekliyor: kaynak `../DEIXIS-h9b-run` H9e koşusunda kullanımda |
| L9 yeni korpus | §7 | bekliyor: L9 hazırlığı henüz yok |

**L9 NLP, tek araştırma (`res_SQ8K…`), tek model, hazırlık denemesi 1; payda 99 tekil eser (129 kaynak sürümü):**

- Modelin okuduğu özet: 79 eser. Otomatik karar geçmişi: model/kod uyumuyla dışlanan 28, dahil edilen 1; kod kuralıyla dışlanan 3 (kodla dahil kaydı: `bilinmiyor`).
- Son üyelik: dahil 1, dışlanan 29, beklemede 69, çıkarılan 0.
- Beklemedeki 69 için tek birincil kategori: incelemede kuyrukta 25; PDF bekliyor, getirme denendi 2; PDF bekliyor, denenmedi 23; diğer 19. Ayrı boyutlar (örtüşebilir): kuyruk üyeliği 25, PDF bekleyen 25, getirme kaydı olan 29.
- Tam metin: deneme 29 eser; başarılı indirme 27; çıkarılmış PDF metni 27; modele verilen metin 26. Doğrudan getirme hataları: `fetch_http_error` 2. Son aday denemelerinde hata: "too many redirects" 1, kod kaydı yok (`bilinmiyor`) 2.
- K03 kuyruk kararları: `bilinmiyor` (bu korpusta kuyruk kararı verilmedi; saklı kayıt yok, sıfır değil).
- Donmuş `G` zinciri (4 eser): ELMo bulundu (beklemede, kuyrukta), BERT bulundu (beklemede, PDF bekliyor), RoBERTa bulunmadı, ALBERT bulunmadı. Bu D141'in önceki bulgusuyla uyumludur (1/99 dahil).
- Kitin `missing` listesi: kod dahil kaydı, K03 kayıtları, PDF aday geçmişi (yalnız son deneme saklanıyor), bazı hata kodları, model teslimi için yanıtsız oturumlar.

**Dil.** “Üç (L9 hazırlanırsa dört) soru, tek model; eserlerin nerede durduğunun betimlemesi.” Bu sayım yalnız D141'in “huniyi incele” alt borcunu kısmen kapatır (bir korpus); STATUS'taki birleşik “fikir zinciri” satırı yeşile dönmez.
