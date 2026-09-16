# P5 dilim 4 — Taranmış PDF sayfalarını OCR ile okumak ve sayfayla denetlemek: tasarım notu

**Tarih:** 16 Eylül 2026. **Durum:** §8'deki yedi soru sahibin yanıtıyla kapandı; her birinde önerilen seçenek seçildi ([D51](../decisions.md)). §9'daki altı alt adım uygulandı (17 Eylül 2026); uygulamanın bu nottan farkları §10'da.

**Kısaca:** Bugün metin katmanı olmayan bir PDF sayfası okunmaz. Böyle bir dosya `no_text` diye kaydedilir; yanıt o kaynağı özetinden okur, tablo hücresi "No text" alır. Bu dilim bu sayfaları yerel bir OCR aracıyla (Tesseract) okunur yapar. OCR metni ayrı bir çıkarım olarak yazılır: eski pasajlar silinmez (D45) ve orijinal sayfa referans olarak kalır. OCR'la okunan her pasaj ekranda ve model girdisinde öyle etiketlenir. OCR metninden gelen sayı ve denklemler için doğruluk iddia edilmez; kullanıcıya sayfayla karşılaştırma yolu gösterilir (plan T10).

**Önemli bulgu:** Canlı kütüphanede şu an OCR'a ihtiyaç duyan dosya yok (§1). Bu dilim, gelecekte eklenecek taranmış makaleler için hazırlıktır; sahip yine de şimdi, en dar kapsamla yapılmasını seçti (§8, soru 1).

## 1. Kodda zaten olanlar

16 Eylül 2026'da `main` (cfba6f9) üzerindeki koddan okundu. Canlı kütüphane sayıları salt okunur bir SQLite bağlantısıyla alındı; hiçbir şey yazılmadı. "Denendi" yazan satırlar depoya eklenmeyen bir deneme betiğiyle (scratchpad, sentetik sayfa) çalıştırıldı.

| Parça | Doğrulanan durum | Dilim 4 için anlamı |
|---|---|---|
| `documents/pdf.py` | PyMuPDF yalnız gömülü metni okur; alt süreçte 90 s, 400 sayfa, 3 M karakter ve 1 GB bellek sınırıyla çalışır. Metni olmayan sayfa atlanır. Hiç metin yoksa `no_text`, bazı sayfalar boşsa `partial`. Çıkarım sürümü `pymupdf-1.28.2-layout-v2`. | OCR bu alt sürece ya da onun eşine eklenir; süre sınırı OCR için yetmez. |
| `source_assets.extraction_status`, `asset_extractions` (0027) | Her çıkarım bir satırdır (`current`, `superseded`, `rejected`); sayfa sayısı, metinli sayfa sayısı, pasaj sayısı tutulur. | OCR bir çıkarım olarak yazılabilir; yeni tablo gerekmez. |
| `Store.reextract_asset` (D45/D47) | Yeni çıkarım ancak durumu daha kötü değilse, sayfa sayısı aynıysa ve metinli sayfa sayısı azalmıyorsa `current` olur. Eski pasajlar gölgelenir, silinmez. Etkin run varken reddeder. | OCR çıkarımı bu kuralla uyumludur: metinli sayfa artar. Kural yeniden kullanılır. |
| `passages` | Metin, kaynak, tür ve sayfa trigger ile değişmez; `extraction_version` var. Bir pasajın OCR'dan mı metin katmanından mı geldiğini söyleyen alan yok. | Karışık belgede (bazı sayfalar metinli, bazıları taranmış) pasaj başına kaynak bilgisi gerekir. |
| Model girdisi (`contracts/research/step-input.schema.json`) | Pasajda `reading_depth` var (`abstract`, `selected_sections`); metnin nasıl elde edildiği yok. | Modelin OCR metnini bilmesi şema değişikliği ister (soru 5). |
| Yanıt denetimi (`domain/contracts.py`) | Özet dayanaklı matematik için `math_without_full_text` uyarısı var (ret değil, D19). | OCR dayanaklı matematik için aynı türden bir uyarı eklenebilir (soru 6). |
| Arayüz | `PdfReadiness` satırı `no_text` için "PDF has no text layer" yazar. Hücrede "No text" durumu var. Pasaj panelinde çıkarım bilgisi ve "Plain text \| PDF" geçişi var. | "OCR ile oku" eylemi ve OCR etiketi buraya gelir. |
| D49 dosya eşleştirme | Bırakılan PDF'i metninden DOI/başlık okuyarak eşler; taranmış dosya eşleşmez (D49 Limits). | OCR sonrasında eşleştirme yeniden denenebilir; bu dilimde zorunlu değil. |
| Makine | Homebrew'de Tesseract 5.5.2 kurulu; yalnız `eng`, `osd`, `snum` dil verisi var, **`tur` yok**. `ocrmypdf` yok. PyMuPDF 1.28.2 `get_textpage_ocr` destekliyor. | Yeni Python bağımlılığı gerekmeden OCR yapılabilir; Türkçe için dil paketi kurulmalı. |

**Canlı kütüphane (salt okunur):** Kullanımda 83 PDF: 82 `succeeded`, 1 `partial`, 0 `no_text`. `partial` olan dosyanın (165 sayfa) metinsiz 11 sayfasında görüntü de yok; boş sayfalar. Yani OCR bugün canlı kütüphanede hiçbir sayfaya metin kazandırmaz.

**Deneme (sentetik, tek sayfa):** Metin PDF'i 200 dpi görüntüye çevrilip görüntüden oluşan bir PDF yapıldı ve `get_textpage_ocr(language="eng")` ile okundu. İngilizce cümle birebir çıktı; 150 dpi 0,12 s, 300 dpi 0,22 s sürdü. İki sorun görüldü: (1) `tur` paketi olmadığı için "çağrı, ışık, öğrenci" → "ca?r?, ???k, 6?renci" oldu; (2) `$x^2$` → `$x*2$` / `$x‘*2$`, yani üst simge kayboldu. Tek, temiz, sentetik bir sayfadır; gerçek taramaların süresi ve doğruluğu ölçülmedi. PyMuPDF OCR sayfası kelime güven skoru vermez.

**Ölçüm (alt adım 1, 16 Eylül 2026, gerçek taramalar):** Dosyalar depoya girmedi (scratchpad). Okuma `ocr.read_page` ile, 300 dpi, sayfa başına ayrı alt süreçle yapıldı; makine Apple M1 Pro.

| Örnek | Dil | Sayfa | Metin bulunan | Süre/sayfa (ort. / en çok) |
|---|---|---|---|---|
| Shannon 1948, BSTJ 27(4) 623–656, archive.org `bstj27-4-623` (metin katmanı yok) | eng | 34 | 34 | 1,00 / 1,41 s |
| İÜ Orman Fak. Derg., DergiPark dosya 175584 | eng+tur | 9 | 9 | 1,88 / 3,33 s |
| Aynı dergi, 175589 | eng+tur | 15 | 15 | 1,66 / 2,53 s |
| Aynı dergi, 175592 | eng+tur | 8 | 8 | 1,36 / 2,16 s |

- DergiPark dosyalarında yayıncının eklediği görünmez bir OCR katmanı vardı. Ölçüm için bu katman silindi (redaksiyon, görüntüler aynen kaldı) ve dosya `no_text` olarak okundu. `tur` verisi sisteme kurulmadı: `tessdata_fast` `tur` dosyası scratchpad'e indirildi ve `TESSDATA_PREFIX` ile kullanıldı.
- Elle denetim, sayfa başına ~900–1000 karakter. **Shannon s. 627:** düz metinde küçük harfli başlık bozuk ("BaAnp LriwiteD"), `f(t)` → `f(/)`, `1/2W` kesri kayboldu, dipnot işareti yanlış çıktı. Kabaca %1–1,5 karakter hatası. Aynı sayfadaki örnekleme teoremi denklemi kullanılamaz durumda. **Tokmanoğlu s. 84 (eng+tur):** 1 hata (ğ → g) ve kenar işaretinden gelen bir "=", yani ~%0,2. Aynı sayfa yalnız `eng` ile okununca ı/ş/ğ/ö harflerinin hemen hepsi bozuldu ("Bolge sefligi", "g6-re").
- DergiPark kapak sayfaları (her dosyanın 1. sayfası) 78 karakterlik gürültü verdi ama `succeeded` sayıldı. "Metin bulundu" doğru okundu anlamına gelmiyor.
- `pdf._join_lines` satır sonu tirelemesini yalnız ASCII küçük harfte birleştiriyor. Bu yüzden "gö-/re" gibi Türkçe tirelemeler ayrık kalıyor; aynı sınır metin katmanı olan dosyalarda da var. Bloklara bölünen satırlar ("dis-/crete", "orman-/cısı") da birleşmiyor. **17 Eylül 2026:** OCR metninde düzeltildi (`OCR_VERSION` v2): tireleme her küçük harfte ve bloklar arasında birleşir; Tokmanoğlu s. 84 `eng+tur` ile yeniden okununca ayrık tireleme kalmadı. Metin katmanı değişmedi: canlı kütüphanede etkilenen pasaj 0 ve `EXTRACTION_VERSION`'ı değiştirmek Marker'la okunmuş her PDF'i yeniden okumaya sokar (D52). Aynı gün `tesseract-lang` kuruldu; `tur` artık var.
- Sayfa başına 60 s süre sınırı, görülen en uzun süreden (3,3 s) yaklaşık 18 kat yüksek; değiştirilmedi. Bu 4 dosya bir ölçüm, bir kalite iddiası değil.

## 2. Senaryolar

### S1. Taranmış makale yüklenir

- Kullanıcı eski bir makalenin taramasını yükler. Metin katmanı yoktur; dosya bugünkü gibi `no_text` kaydedilir ve Sources satırı "PDF has no text layer" der.
- Satırda (ve PDF hazırlık panelinde) "Read with OCR" eylemi görünür. Eylem kaç sayfanın okunacağını ve dili söyler.
- OCR bitince yeni çıkarım `current` olur; kaynak "OCR text" etiketiyle tam metinden okunur. Sonraki yanıt ve hücre doldurma bu pasajları kullanır. Önceki yanıt ve hücreler değişmez (D45); eski yanıtta `source_text_changed` uyarısı çıkar.

### S2. Karışık belge

- Metinli bir makalenin bazı sayfaları (ek, eski tablo) taranmış görüntüdür. Dosya `partial` kaydedilir.
- OCR yalnız metni boş olan ve görüntü içeren sayfalara uygulanır (soru 3). Metin katmanı olan sayfalar aynı kalır. Pasaj başına kaynak kaydedilir; alıntı yalnız OCR sayfasındaysa OCR etiketi taşır.
- Boş sayfa (görüntü de yok) OCR'a gönderilmez ve "blank page" diye sayılır; canlı kütüphanedeki 11 sayfa bu durumdadır.

### S3. OCR metnine dayanan alıntı ve denklem

- Yanıt alıntısı ya da hücre kanıtı OCR pasajındaysa etiket "OCR text · check against the page" der. Pasaj panelinde "PDF" sekmesi aynı sayfada açılır.
- İddia ya da hücre değeri sayı, birim ya da denklem içeriyor ve yalnız OCR pasajına dayanıyorsa bir uyarı kaydedilir (soru 6). Uyarı yanıtı reddetmez; "sayfayla karşılaştırılmadı" demektir.

### S4. OCR başarısız ya da işe yaramaz

- Tesseract kurulu değil ya da dil paketi eksik: eylem kapalıdır ve nedenini, kurulum komutunu yazar (Connections'taki yerel araç kartı gibi). Başka araca ya da çevrim içi OCR'a geçilmez.
- OCR hiçbir sayfada metin bulamadı ya da süre doldu: çıkarım `no_text`/`failed` olarak kaydedilir, eski durum değişmez, neden ekranda yazar.
- OCR bazı sayfalarda metin buldu: `partial`, hangi sayfaların okunmadığı sayılır.

## 3. Kurallar

- **Orijinal sayfa referanstır.** PDF dosyası değiştirilmez; OCR metni yalnız pasaj olarak yazılır. Görüntüye metin katmanı eklenmiş yeni PDF üretilmez.
- **Eski kanıt yeniden yazılmaz.** OCR yeni bir çıkarımdır; D45 kuralıyla `current` olur, eski pasajlar gölgelenir.
- **OCR görünürdür.** Her OCR pasajı ekranda "OCR text" etiketi taşır; sayılar ve denklemler için doğruluk iddia edilmez. Bir OCR'lı kaynak "full text" diye OCR'sız kaynakla aynı gösterilmez.
- **Yerel ve açık.** OCR yalnız bu makinedeki araçla çalışır; dosya dışarı gönderilmez. Eksik araç ya da dil sessizce atlanmaz.
- **Sınırlı iş.** OCR ayrı bir alt süreçte sayfa, süre ve bellek sınırıyla çalışır; sınır dolunca `partial` kaydedilir.

## 4. Veri modeli taslağı

**0030 — OCR kaynağı (taslak).**

```sql
-- Pasajın metni nasıl elde edildi: PDF'in metin katmanı mı, OCR mı. Özet pasajlarında NULL.
ALTER TABLE passages ADD COLUMN text_source TEXT CHECK (text_source IN ('text_layer', 'ocr'));
-- Bir çıkarımın OCR ayrıntısı: araç ve sürümü, diller, OCR'lanan / metin bulunan / boş sayfa sayısı.
ALTER TABLE asset_extractions ADD COLUMN ocr_json TEXT;
```

- Eski `pdf_page` pasajları `text_layer` sayılır (migration'da doldurulur ya da görünümde NULL → `text_layer`).
- Çıkarım sürümü OCR'ı adıyla taşır: `pymupdf-1.28.2-layout-v2+ocr-tesseract-5.5.2-eng+tur-v1`. Aynı sürüm ikinci kez çalışmaz (`reextract_asset` "unchanged").
- Görünümler: kaynakta `has_ocr_text`, pasaj ve kanıtta `text_source`. `evidence_status` değişmez.
- Olay: `asset_ocr_read` (sayfa sayıları ve sonuç).
- Uçlar: `POST /api/researches/{rid}/sources/{svid}/assets/{aid}/ocr` (`pdf_ocr` run'ı başlatır), `GET /api/ocr` (araç, sürüm, kurulu diller).

## 5. Arayüz

`.impeccable.md`'ye uyulur. OCR etiketi metinle yazılır; renk yalnız dikkat (amber) tonudur.

1. **Sources satırı ve PDF hazırlık paneli.** `no_text`/`partial` dosyada "Read with OCR · {n} pages · English + Turkish". Araç yoksa kapalı düğme ve nedeni.
2. **Kaynak durumu.** "PDF text" yanında "OCR text on {k} of {n} pages".
3. **Alıntı, hücre kanıtı ve pasaj paneli.** "OCR text · check against the page" etiketi; pasaj panelinde tek tıkla aynı sayfanın PDF görünümü.
4. **Settings → Connections → yerel araçlar.** Tesseract kartı: kurulu mu, sürüm, diller, `brew install tesseract tesseract-lang` komutu.
5. Masaüstü ve 390 px, açık ve koyu tema.

## 6. Testler (taslak)

**Çıkarım (sentetik)**

- Görüntüden oluşan tek sayfalık PDF: metin katmanıyla `no_text`, OCR ile metin; pasajlar `text_source = 'ocr'`; çıkarım satırında araç, sürüm, dil ve sayfa sayıları.
- Karışık PDF (1 metinli, 1 taranmış, 1 boş sayfa): yalnız taranmış sayfa OCR'lanır, metinli sayfanın pasajı aynı metinle `text_layer`, boş sayfa "blank" sayılır.
- Tesseract yok ya da dil eksik: OCR reddedilir, asset ve pasajlar değişmez, neden döner.
- Süre ya da sayfa sınırı: `partial`/`failed` kaydedilir, eski çıkarım `current` kalır.
- Aynı OCR sürümü ikinci kez: "unchanged".

**Kanıt ve model girdisi**

- OCR sonrası yanıt girdisi OCR pasajlarını verir; önceki yanıtın alıntısı eski (boş/özet) kanıtı açar ve `source_text_changed` doğru.
- (Soru 5a ise) StepInput pasajında `text_source`; şema, sahte çıktılar ve `skill_package_hash` güncel.
- (Soru 6a ise) yalnız OCR pasajına dayanan sayı/denklem iddiasında uyarı; yanıt reddedilmez.
- Tablo doldurma OCR'lı kaynağı artık "No text" diye sistem dolgusuyla geçmez.

**API ve web**

- Uç: CSRF, etkin run 409, çıkarılmış kaynak 404, kullanılmayan asset 404.
- Playwright (fixture sunucusu, sentetik taranmış PDF): yükle → "PDF has no text layer" → "Read with OCR" → "OCR text" etiketi → yanıt → alıntıda OCR etiketi → PDF sayfası açılır. Masaüstü ve 390 px, açık ve koyu.

**Gerçek örnekler (ölçüm, test değil):** İngilizce ve Türkçe birkaç gerçek taranmış makale (soru 7). Sayfa başına süre, metinli sayfa oranı ve elle denetlenen birkaç sayfada karakter hatası raporlanır; denklem sayfaları ayrıca sayılır. Bu bir OCR kalitesi iddiası değildir.

**Bu dilimde geçmeyecekler:** Görüntüdeki tablo ve şeklin yapısal okunması; el yazısı; denklemin LaTeX'e çevrilmesi (matematik OCR); D49 dosya eşleştirmesinin OCR ile yeniden denenmesi; OCR metninin kullanıcı tarafından elle düzeltilmesi; çevrim içi OCR servisleri.

## 7. Varsayımlar

- OCR bir uygunluk özelliğidir, bir doğrulama değildir. "OCR ile okundu" "doğru okundu" demek değildir.
- Tesseract'ın kurulumu kullanıcıya bırakılır; DEIXIS aracı indirmez ya da kurmaz (Connections'taki yerel araç kalıbı).
- Sentetik denemedeki süreler gerçek taramaları temsil etmez; süre sınırları 1. alt adımda gerçek örnekle belirlenir.

## 8. Sahibe sorulanlar

Her soruda önerim ilk seçenekti; sahip yedisinde de onu seçti (16 Eylül 2026).

1. **Öncelik.** Canlı kütüphanede OCR'a ihtiyaç duyan dosya yok.
   - a. Dilim 4 şimdi yapılır, ama kapsam en dar haliyle (S1–S4, bu nottaki sorular önerilen seçenekle). (öneri)
   - b. Dilim 4 ertelenir; önce dilim 5 (ölçüm: tablo doldurma ve yanıtların gerçek model ile denetimi) yapılır, OCR ilk taranmış makale geldiğinde açılır.
   - c. Dilim 4 tam kapsamla (matematik OCR, tablo yapısı dahil) yapılır.
2. **OCR nasıl çalışır.**
   - a. Kullanıcı isteğiyle, arka planda bir run olarak (`pdf_ocr`): sayfa sayfa ilerleme, duraklatma ve iptal; model çağrısı yok. (öneri)
   - b. Kullanıcı isteğiyle, istek içinde eşzamanlı (sayfa sınırı ~30, süre boyunca bekleme göstergesi).
   - c. Yüklemede ve indirmede kendiliğinden; metin katmanı yoksa hemen OCR.
3. **Hangi sayfalar.**
   - a. Yalnız metni boş ve görüntü içeren sayfalar; metin katmanı olan sayfaya dokunulmaz. (öneri)
   - b. Bütün sayfalar OCR'lanır; metin katmanı olanlarda da OCR metni kullanılır.
   - c. Kullanıcı sayfa aralığı seçer.
4. **Diller.**
   - a. İngilizce + Türkçe; `tur` kurulu değilse eylem yalnız İngilizceyle çalışır ve etiket bunu yazar ("English only; Turkish characters may be wrong"), kurulum komutu gösterilir. (öneri)
   - b. Yalnız İngilizce.
   - c. Kullanıcı her OCR'da dil seçer.
5. **Model OCR'ı bilsin mi.**
   - a. Evet: StepInput pasajına `text_source` eklenir, yöntem paketine "OCR metnindeki sayı ve denklemleri olduğu gibi aktarma, belirsizse söyle" kuralı; şema sürümü artar. (öneri)
   - b. Hayır: yalnız ekranda etiket; model girdisi değişmez.
   - c. OCR metni model girdisine hiç girmez; yalnız kullanıcı okumak için açar.
6. **OCR'a dayanan sayı ve denklem.**
   - a. Yalnız OCR pasajına dayanan sayı/birim/denklem içeren iddia ve hücre için uyarı (`ocr_numbers_unchecked`); ret yok, ekranda "check against the page". (öneri)
   - b. Böyle bir iddia reddedilir (onarım yoluna girer).
   - c. Ayrı işlem yok; genel OCR etiketi yeter.
7. **Ölçüm örnekleri.**
   - a. Sentetik taranmış sayfalar (testler için) + sahibin vereceği 2–4 gerçek taranmış makale (İngilizce ve Türkçe, en az biri denklemli; yalnız ölçüm için, depoya girmez). (öneri)
   - b. Yalnız sentetik sayfalar.
   - c. Açık erişimli eski taranmış makaleler DEIXIS dışından bulunur.

## 9. Alt adımlar

Her alt adımda önce testler yazılır ve kırmızı görülür, sonra uygulanır.

1. **OCR çıkarımı (alt süreç).** `pdf.py`: metinsiz ve görüntülü sayfaları bulma, Tesseract ile okuma, pasaj başına `text_source`, sınırlar; araç ve dil algılama. Gerçek örneklerle süre ve sınır ölçümü.
2. **Migration 0030 ve kayıt.** `passages.text_source`, `asset_extractions.ocr_json`; `reextract_asset` ile OCR çıkarımının yazılması; olay.
3. **`pdf_ocr` run'ı.** Migration'da run türü; sayfa sayfa ilerleme, duraklatma, iptal ve yeniden başlatmada tekrar okumama; uç ve etkin run, çıkarılmış kaynak ve kullanılmayan asset kontrolleri.
4. **Görünümler ve model girdisi.** `has_ocr_text`, kanıtta `text_source`; StepInput şeması ve yöntem paketi; `ocr_numbers_unchecked` uyarısı.
5. **Arayüz.** Sources satırı, PDF hazırlık paneli, etiketler, pasaj paneli, Connections kartı; `api.ts`, `i18n.ts`.
6. **Kapanış.** Tam backend suite, build, lint, acceptance, `git diff --check`; karar kaydına Evidence ve Limits, bu nota uygulama farkları. Canlı kütüphaneye yazılmaz.

## 10. Uygulama farkları

17 Eylül 2026'da, alt adım 6'da yazıldı. Kanıt ve sınırlar [D51](../decisions.md)'de.

- **Migration numaraları.** `passages.text_source` D52 ile gelen 0030'da (`text_layer`, `ocr`, `marker`); `asset_extractions.ocr_json` 0031'de; `pdf_ocr` run türü 0032'de. §4'teki tek 0030 taslağı böyle bölündü.
- **Çalışma adımları.** `pdf_ocr` run'ı üç tür adım yazar: `ocr:pages` (metinsiz ve görüntülü sayfalar bir kez bulunur), sayfa başına `ocr:page:{n}`, `ocr:merge`. Bir sayfa başarısız olursa diğerleri yine okunur, run hiçbir şey yazmadan duraklar ve devam edince yalnız o sayfa okunur. Aynı Tesseract sürümü ve dillerle yazılmış bir okuma tekrarlanmaz (uç 409 döner).
- **Düğmedeki sayfa sayısı.** "Read with OCR · {n} pages · English + Turkish" yerine düğme yalnız "Read with OCR" der; altındaki not "{n} pages have no text" ve dilleri yazar. Buradaki sayı metinsiz sayfaların hepsidir, boş sayfalar dahil: hangi sayfanın görüntü olduğu ancak run başlayınca bulunur. Türkçe verisi yoksa not "Turkish characters may be wrong" ve kurulum komutunu ekler; araç yoksa düğme kapalıdır ve not nedenini yazar. Başka bir run sürerken düğme kapalıdır.
- **Kaynak durumu.** "OCR text on {k} of {n} pages · check against the page", amber tonda. Metni bulunamayan bir OCR okuması ayrı bir etiket almaz; mevcut "A later text extraction … was not used" notu onu söyler.
- **Görünüm alanları.** Kaynak PDF'inde `ocr` (`pages_without_text`, `ocr_pages`, `last_read`), yanıt alıntısında `text_source`, `GET /api/ocr`. Bunlar alt adım 5'te eklendi.
- **Connections kartı.** Tesseract'ı DEIXIS kurmaz; kart sürümü, kurulu ve eksik dilleri ve kurulum komutunu gösterir, bir "Check again" düğmesi vardır.
- **Zaman çizelgesi.** `pdf_ocr` run'ı tek aşamalı bir kayıttır: dosya adı, okunan sayfa sayısı, metin bulunan ve atlanan boş sayfalar, "in use / not used" ve diller. Duraklarsa okunamayan sayfalar listelenir. `asset_ocr_read` Activity'de görünür.
- **Ölçülmeyenler.** Arayüz yalnız İngilizce Tesseract verisiyle denendi; Tesseract kurulu değilken ekran tarayıcıda görülmedi. Canlı kütüphaneye yazılmadı.
