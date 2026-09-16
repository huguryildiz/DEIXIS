# P5 dilim 2 — Dosya, çıkarım ve kaynak sürümü değişince eski kanıt: tasarım notu

**Tarih:** 16 Eylül 2026. **Durum:** §8'deki yedi soru sahibin yanıtıyla kapandı; her birinde önerilen seçenek seçildi ([D45](../decisions.md)). D44 ve D46 numaraları ile `0025`–`0026` migration'ları aynı gün başka işlere gitti; bu dilimin migration'ı `0027`. Alt adımlar 1–4 ve 5'in test kısmı uygulandı (D45 Evidence). Yeniden çıkarma işlemi ve CLI'ı D47 kapsamında başka bir oturumda yazıldı ve canlı kütüphaneye uygulandı (69 PDF, hepsi `current`); bu yüzden 5. adımdaki kopyada kuru çalıştırma raporu yapılmadı. Taslaktan farklar: hücre işaretleri `pdf_withdrawn` yerine `pdf_removed`, `pdf_replaced`, `text_superseded`; Sources satırındaki değiştirme menü değil düğmedir; yanıt uyarısı rapor sayfasında görünür.

**Kısaca:** Kanıt pasaj kimliğine bağlıdır ve pasajlar değişmez. Bu yüzden eski kanıtı korumanın yolu eski pasajı silmemek ya da değiştirmemektir: yeni dosya ve yeni çıkarım **yeni pasajlar** üretir, eski pasajlar yalnız yeni model girdilerinden çekilir ("gölgelenir"). Eski hücre kanıtı ve eski yanıt alıntıları eski pasajı açmaya devam eder ve ekranda neyin değiştiği yazılır. Hiçbir kanıt yeni pasaja ya da başka sürüme kendiliğinden taşınmaz (D37). Yeni metni okumak kullanıcının isteğiyle olur: hücrede recheck, yanıtta yeni yanıt.

## 1. Kodda zaten olanlar

Aşağıdakiler 16 Eylül 2026'da çalışma ağacındaki koddan okundu. "Denendi" yazanlar, depoya eklenmeyen bir deneme testiyle (scratchpad, sentetik kayıtlar) çalıştırıldı. Canlı kütüphane sayıları salt okunur bir SQLite bağlantısıyla alındı; hiçbir şey yazılmadı.

| Parça | Doğrulanan durum | Dilim 2 için anlamı |
|---|---|---|
| `passages` | Metin, kaynak sürümü, tür ve sayfa trigger ile değişmez (0001). `extraction_version` sütunu var. | Gölgeleme pasajı değiştirmeden yapılmalı. |
| `Store._insert_passage` | Tekrar anahtarı: kaynak sürümü + tür + asset + sayfa + metin hash'i. `extraction_version` anahtarda yok. **Denendi:** aynı asset'e aynı metin yeni sürüm etiketiyle yazılınca eski kimlik ve eski etiket (`test-v1`) döner. | Aynı dosyanın yeniden çıkarımı bugün yeni pasaj üretemez. Anahtar genişlemeli. |
| `add_asset_with_pages` | Her çağrı yeni bir `source_assets` satırı açar; çıkarımı mevcut asset'e yazan yol yok. Kodda yeniden çıkarma işlevi yok (`pdf.py` belgesi "not re-extracted" der). | Yeniden çıkarma yeni bir işlem. |
| `upload_to_source` | Aynı kaynağa aynı bayt (sha) ikinci kez gelirse yok sayılır. Farklı bayt ikinci etkin asset olarak eklenir. **Denendi:** 1 sayfalık ve 2 sayfalık iki PDF → 2 etkin asset, 3 canlı pasaj, ilk sayfanın metni iki kez. | "Değiştirme" yok; ikinci dosya yan yana eklenir. |
| Arayüz | "Attach PDF" yalnız asset yokken görünür (`ResearchView.tsx`); çekmek için "Remove PDF" var. Aday onayı (D33) asset varsa 409. Acquisition ve Zotero içe aktarımı `has_asset` ise atlar. | İkinci etkin asset bugün yalnız API ile oluşur. Arayüzdeki değiştirme yolu "kaldır, sonra ekle"dir. |
| `remove_asset` | `removed_at` yazar, pasajları siler değil. Yalnız işlemi yapan araştırmanın `selection_revision` değerini artırır. Neden (yanlış dosya mı, değiştirildi mi) kaydedilmez. **Denendi:** kaldırıp aynı baytı yeniden eklemek yeni asset ve yeni pasaj kimlikleri üretir; eski kimlikler yeniden kullanılmaz. | Eski kanıt çözülmeye devam eder. Ama asset kaynak sürümüne, kaynak sürümü kütüphaneye aittir: bir araştırmadaki kaldırma, aynı kaynağı kullanan öteki araştırmaları da etkiler. |
| `passages_for`, `search_passages` | Kaldırılmış asset'in pasajlarını dışarıda bırakır; çıkarım sürümüne bakmaz. | Gölgeleme filtresi buraya eklenir. |
| Hücre doldurma (`_extraction`, `_cell_passages`) | **Denendi:** aynı metinli iki etkin asset'te StepInput 4 pasaj taşır, her metin iki kez; `passage_scope` = `{given: 4, available: 4, all_pages_given: true}`. | Kopya, model girdisine iki kez girer ve kapsam sayısını şişirir. |
| Yanıt seçimi (`_retrieve`) | **Denendi:** tek eklenmiş kaynakta, iki asset "küçük belgeyi bütün ver" yolunu kapatır (`len(asset_ids) == 1` koşulu); FTS yolu 2 pasaj seçti, ikisi aynı metin. İki kaynakla 3 pasajın 2'si aynı metin. Kaynak başına 6 pasaj sınırında kopya bir yuva harcar. | Kopya yanıt girdisine de girer. |
| Hücre kanıtı görünümü (`tables.py`) | Kanıt satırı `asset_removed` taşır; geçerli revizyonda varsa `pdf_withdrawn` işareti. Arayüz "PDF removed" yazar ve PDF sekmesini kapatır. | Genişletilecek işaretin bugünkü hali. |
| Yanıt alıntısı görünümü (`views.py`, `passage_view`) | Kanıt satırında ve pasaj görünümünde asset durumu yok. `ResearchView` alıntıdan açılan `PassageSheet`'e `pdfRemoved` geçmez; PDF sekmesi `asset_id` ile açılır, `GET /assets/{id}` kaldırılmış asset için 404 döner. **Koddan okundu, çalıştırılmadı.** | Yanıt alıntısında "PDF çekildi" işareti yok; PDF sekmesi hata verir. |
| Yanıt eskimesi | `result_applicability`: soru ya da seçim revizyonu değişince `stale_scope` / `stale_selection`. Metin değişimi için ayrı durum yok. | Kaldırma bugün yanlış metinle ("kaynak seçiminiz değişti") eskitir. |
| Kaynak sürümleri (D4, D6, D33) | Başka sürüm ayrı `source_version`; OA PDF yalnız aynı sürüme bağlanır; belirsiz sürüm kullanıcı onayı ister. `enrich_source` yalnız boş alanları doldurur, `version_label` değişmez. `cell_evidence_same_source` trigger'ı başka sürümün pasajını reddeder. | Sürüm değişimi yeni kaynak sürümü demektir; kanıt geçişini trigger zaten engelliyor. |
| Yedek ve silme (D6, `purge_research`) | Yedek, kaldırılmış olanlar dahil her `source_assets` dosyasını hash'iyle alır. Kalıcı silme, başka araştırmanın kullandığı kaynağın dosyasına ve bir asset satırının hâlâ gösterdiği dosyaya dokunmaz. | Değiştirilen eski dosya yedekte kalır; T15 için test eklenir. |
| Gömme vektörleri (D27) | `passage_embeddings` pasaj kimliğiyle; eksik olan anlamsal adımda hesaplanır. | Yeni pasajlar bir sonraki anlamsal adımda yeniden gömülür (ek çağrı maliyeti). |

**Canlı kütüphane (salt okunur, 16 Eylül 2026):** 67 etkin asset, kaldırılmış yok; birden çok etkin asset'i olan kaynak sürümü 0. Çıkarım sürümleri: 56 asset `pypdf-6.18.1-chunks-v1`, 11 asset `pymupdf-1.28.2-chunks-v1`; `chunks-v2` hiç yok. Pasajlar: 2.746 pypdf, 393 PyMuPDF v1, 807 özet. Yanıt kanıt bağlarının 42'si PDF pasajına (25 pypdf, 17 PyMuPDF v1), 445'i özete gider; hücre kanıt bağı 12. PDF'i olan 44 kaynak sürümü birden çok araştırmada kullanılıyor. Aynı dosya (sha) iki ayrı eserde 2 kez görülüyor (bir preprint'in üç, bir başkasının iki ayrı kaydı); bu kimlik eşleştirme sorunudur, dilim 2'nin konusu değildir. Kaynak içinde tekrarlanan canlı metin 1 kez var: bioRxiv alt bilgisi aynı dosyanın 10. ve 19. sayfasında; kopya dosya değil.

Yani iki kopya sorunu kodda gerçek ama canlı veride şu an yok. Asıl canlı ihtiyaç yeniden çıkarmadır: PDF metninin %84'ü (56/67 dosya) D25'in bıraktığı pypdf çıkarımıdır ve D43'teki IEEE notu ayıklaması hiçbir mevcut dosyaya uygulanmadı.

## 2. Senaryolar

### S1. Dosya değiştirme

Kullanıcı bir kaynak sürümündeki PDF'i başka bir dosyayla değiştirir: daha iyi tarama, aynı sürümün yayıncı kopyası, eksik sayfalı dosyanın tamamı.

- Yeni dosya **yeni asset** olur; eski asset aynı işlemde `removed_at` ve `removal_reason = 'replaced'`, `replaced_by_asset_id` alır. Değişen tek şey, gelecekteki model girdilerinin hangi asset'ten okunacağıdır.
- Metni aynı olsa bile yeni asset yeni pasaj kimlikleri üretir (tekrar anahtarı asset'i içerir). Eski kimlikleri yeniden kullanmak, eski kanıtın gösterdiği dosyayı sessizce değiştirmek olurdu.
- Değiştirme bir kaynak sürümünde tek geçerli PDF bırakır. Bugünkü yan yana ekleme, §1'deki çift girdi sorununu doğurur; bu yüzden `upload_to_source` asset varken 409 döner ve değiştirme ayrı bir uç olur (§8, soru 2).
- Asset kütüphane düzeyinde olduğu için değiştirme, kaynağı kullanan bütün araştırmalarda geçerlidir (§8, soru 1). Onay ekranı etkilenen araştırma, hücre ve alıntı sayılarını gösterir.
- Yanlış dosya çekmek (bugünkü "Remove PDF") ayrı kalır: `removal_reason = 'wrong_file'`. Fark ekranda görünür: değiştirilen dosya aynı eserin geçerli bir kopyasıydı, yanlış dosya değildi.

### S2. Yeniden çıkarma

Dosya aynıdır; çıkarıcı ya da parçalama değişmiştir (`pypdf-…-chunks-v1` → `pymupdf-…-chunks-v2`, ileride `chunks-v3` ya da OCR).

- Yeni bir `asset_extractions` satırı açılır; sayfalar mevcut asset'e yeni `extraction_version` ile yazılır. `_insert_passage` tekrar anahtarına `extraction_version` eklenir, böylece aynı metin de yeni pasaj kimliği alır ve kendi sürüm etiketini taşır.
- Yeni çıkarım denetimden geçerse aynı işlemde asset'in geçerli çıkarımı olur; eski pasajlar gölgelenir (§4). Geçmezse `rejected` kaydedilir, eski metin kullanılmaya devam eder ve bu görünür.
- Aynı sürüme ikinci kez yeniden çıkarma istemek iş yapmaz.
- Başlatma yolu kullanıcı eylemidir: kaynak başına "Metni yeniden çıkar" ve toplu bir CLI komutu. Açılışta ya da run içinde kendiliğinden çalışmaz, çünkü bu bir araştırmanın model girdisini sessizce değiştirirdi (§8, soru 3).
- **Parça sınırı notu.** D43 denemesinde 3 alıntı iki pasajın sınırına düştü. Bu dilim chunker'ı değiştirmez, ama mekanizma `chunks-v3`'ü aynı yoldan taşıyabilmelidir. Seçenekler ayrı bir karardır: örtüşen parçalar (komşu pasajlarda tekrar eden metin yaratır; `duplicate_evidence_quote` bugün yalnız aynı pasaj içinde bakar), sayfa düzeyi pasaj (girdi bütçesini büyütür) ya da alıntıyı bitişik iki parçada `payload_ref` karakter aralıklarıyla bulmak (kanıt iki pasaja bağlanır). Son seçenek için `payload_ref` sayfa içi aralıkları yeni çıkarımda korunmalıdır; bu dilimde korunur.

### S3. Kaynak sürümü değişimi

"Sürüm" burada yayın sürümüdür: preprint, kabul edilmiş metin, yayıncı sürümü (D4, D6).

- **Başka sürüm sonradan bulunur ya da eklenir.** Yeni `source_version` olur. Tabloda ayrı satırdır, hücreleri boş başlar; eski satırın değerleri ve kanıtı kopyalanmaz (D37, `cell_evidence_same_source`). Satır başlığı "bu eserin başka bir sürümü tabloda / araştırmada" bilgisini gösterir ve "satır olarak ekle" eylemi sunar; doldurmayı kullanıcı ister.
- **Eklenen PDF'in başka sürüm olduğu anlaşılır** (ör. D33'te onaylanan belirsiz aday aslında preprint). Dosya bu kaynaktan `wrong_file` nedeniyle çekilir. Doğru sürüme ayrıca eklenir ve orada yeni pasajlar üretir. Kanıt taşınmaz; eski hücre "PDF çekildi" gösterir, recheck yeni metni okur.
- **Sağlayıcı kaydın sürüm etiketini değiştirir.** Bugün `version_label` üzerine yazılmıyor (`enrich_source`); meta veri geçmişi dilim 2'nin konusu değil. Bu dilimde değişiklik yok.
- **Yanıt:** Bir yanıt iki sürümü de okuduysa ikisi ayrı kaynak olarak kalır ve bağımsız doğrulama sayılmaz (AGENTS.md, sürüm kimliği). Bu mevcut davranıştır; test T03 için yeniden koşulur.

## 3. Eski kanıt nasıl çözülür

İlke: bir kanıt bağı her zaman kaydedildiği pasajı açar, vurgu o pasajın saklı metninde bulunan `anchor_text`'tir. Görünümler o pasajın bugünkü durumunu ayrıca hesaplar.

**Pasaj durumu** (yeni `evidence_status`, sunucu hesaplar; öncelik sırasıyla):

| Durum | Koşul | Metin | PDF sekmesi | Etiket |
|---|---|---|---|---|
| `current` | Asset etkin (ya da özet) ve pasaj geçerli çıkarımdan | Açılır | Açılır | — |
| `pdf_removed` | Asset `wrong_file` ile çekildi | Açılır | Kapalı | "PDF çekildi" |
| `pdf_replaced` | Asset `replaced` ile çekildi | Açılır | Eski dosya salt okunur açılır (§8, soru 4) | "Önceki PDF" |
| `text_superseded` | Asset etkin, pasajın `extraction_version` değeri geçerli çıkarımdan farklı | Açılır | Açılır (dosya aynı) | "Eski metin çıkarımı" |

**Hücreler.** Revizyon ve kanıt bağları değişmez. `pdf_withdrawn` işareti yukarıdaki durumlardan türetilen üç işarete ayrılır: `pdf_removed`, `pdf_replaced`, `text_superseded`. Geçerli değer değişmez. Recheck her zaman yeni (geçerli) pasajları okur ve öneri üretir. Doldurmadaki `include_stale` seçeneği, kanıtı gölgelenmiş hücreleri de kapsayacak şekilde genişler; bu hücreler de yalnız öneri alır.

**Yanıtlar.** Yanıt, iddiaları ve kanıt bağları değişmez; alıntılar eski pasajı ve saklı vurguyu açar. Değiştirme ve yeniden çıkarma `selection_revision` değerini artırmaz, çünkü seçim değişmedi ve bugünkü metin ("kaynak seçiminiz değişti") yanlış olurdu. Bunun yerine görünüm, yanıtın StepInput'unda verilen pasajlardan herhangi biri artık `current` değilse `source_text_changed` işareti hesaplar. `applicability` alanı ve mevcut `remove_asset` artırması aynen kalır. Yanıt inceleme (D14) sonucu da değişmez; eski metne yapılmış bir değerlendirme olarak kalır.

**Tablo dışı okumalar.** `passage_view` durumu ve (değiştirildiyse) yeni asset kimliğini döndürür. `GET /assets/{id}` `replaced` bir asset'i yalnız araştırmanın bir kanıt bağı o asset'in pasajını gösteriyorsa verir (soru 4 "evet" ise); `wrong_file` için 404 kalır.

## 4. Yeni çıkarım eski pasajları ne zaman gölgeler

- **Gölgelenmiş pasaj:** asset'i çekilmiş ya da `extraction_version` değeri asset'in geçerli çıkarımından farklı olan pasaj. `passages_for` ve `search_passages` bu pasajları vermez; yani fill, recheck, yanıt, sütun önerisi ve anlamsal sıralama bunları görmez. `passage(id)` ve görünümler görmeye devam eder.
- **An:** yeni pasajların yazılması ile geçerli çıkarımın değişmesi tek işlemdir. Arada bir model girdisinin yarım gölgelenmiş bir kaynağı görmesi mümkün değildir.
- **Denetim (otomatik, §8 soru 5):** yeni çıkarım ancak şunları sağlarsa geçerli olur: durum `succeeded` (eski `partial` ya da `no_text` idiyse `partial` da kabul), sayfa sayısı eskisiyle aynı, metin içeren sayfa sayısı eskisinden az değil. Aksi halde `rejected` kalır; sebep kaydedilir ve Sources'ta görünür. Bu denetim metnin daha doğru olduğunu göstermez, yalnız belirgin kaybı engeller.
- **Etkin run:** kaynağın üye olduğu herhangi bir araştırmada `queued`, `running` ya da `pause_requested` run varsa değiştirme ve yeniden çıkarma 409 alır (§8, soru 6). Duraklatılmış run'da kaydedilmiş StepInput'lar değişmez; devam eden run henüz girdisi kaydedilmemiş adımlarda yeni pasajları okur. Bunun sonucu run'ın kaynak sayısında görünür değildir; Activity'deki olay açıklar.
- **Asla:** eski pasaj silinmez, `text` güncellenmez, kanıt bağı yeni pasaja yazılmaz, `extraction_version` sessizce değiştirilmez.

## 5. Veri modeli taslağı

**0027 — asset değişimi ve çıkarım kuşakları.** SQL'in geçerli hali uygulamada migration dosyası olacak.

```sql
ALTER TABLE source_assets ADD COLUMN removal_reason TEXT CHECK (removal_reason IN ('wrong_file', 'replaced'));
ALTER TABLE source_assets ADD COLUMN replaced_by_asset_id TEXT REFERENCES source_assets(id);
-- A source version has at most one PDF in use; replacing is a separate action (question 2).
CREATE UNIQUE INDEX source_assets_one_in_use ON source_assets(source_version_id) WHERE removed_at IS NULL;

CREATE TABLE asset_extractions (
  id TEXT PRIMARY KEY,                 -- ext_
  asset_id TEXT NOT NULL REFERENCES source_assets(id),
  extraction_version TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('succeeded', 'partial', 'no_text', 'failed')),
  error TEXT, page_count INTEGER, text_pages INTEGER, passage_count INTEGER,
  outcome TEXT NOT NULL CHECK (outcome IN ('current', 'superseded', 'rejected')),
  rejection_reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (asset_id, extraction_version)
);
CREATE UNIQUE INDEX asset_extractions_one_current ON asset_extractions(asset_id) WHERE outcome = 'current';
-- Backfill: one 'current' row per existing asset from source_assets.extraction_version/status/page_count.
```

- `source_assets.extraction_version`, `extraction_status`, `page_count` geçerli çıkarımı yansıtacak şekilde güncellenir, böylece mevcut görünümler değişmeden doğru kalır.
- Benzersiz indeks, iki etkin asset'li bir veritabanında migration'ı durdurur. Canlı kütüphanede bu 0'dır; test ve kopyalarda hata mesajı açıktır, kod hiçbir asset'i kendiliğinden çekmez.
- `evidence_status` saklanmaz, her görünümde hesaplanır.

**Uçlar** (`/api/researches/{rid}/sources/{svid}` öneki; mevcut CSRF, Host/Origin, üyelik 404 kuralları):

| Uç | Gövde | Sonuç |
|---|---|---|
| `POST /uploads` (mevcut) | dosya | Asset yoksa ekler; varsa 409 "replace kullanın" |
| `PUT /assets/{aid}` | dosya, `expected_asset_id` | Değiştirme; etkin run 409; aynı sha 422 ("aynı dosya") |
| `DELETE /assets/{aid}` (mevcut) | — | `removal_reason = 'wrong_file'` |
| `POST /assets/{aid}/extractions` | — | Yeniden çıkarma; etkin run 409; güncel sürümse 200 ve iş yok |
| `GET /assets/{aid}/impact` | — | Etkilenen araştırmalar, hücre ve alıntı sayıları (onay ekranı için) |

CLI: `deixis reextract [--dry-run] [--version-below chunks-v2]`. Kuru çalıştırma hiçbir şey yazmaz; dosya başına eski ve yeni sayfa, metinli sayfa, karakter sayısı ve denetim sonucunu yazar. Canlı kütüphanede önce kopyada ve sahibin onayıyla çalışır.

## 6. Arayüz

`.impeccable.md`'ye uyulur; renk tek başına anlam taşımaz, her işaretin metni vardır. Kehribar "dikkat", kırmızı yalnız geçersiz öneri için kalır.

1. **Sources satırı, PDF satırı.** Bugün: dosya adı ve "Remove PDF". Yeni:
   - Metin kaynağı bilgisi: "PDF · 12 sayfa · metin: PyMuPDF, chunks-v2". Eski çıkarımsa yanında "Metni yeniden çıkar".
   - Menü: "PDF'i değiştir…" (dosya seçimi) ve "Yanlış dosya, çek".
   - Değiştirme onayı: "Yeni dosya bundan sonraki yanıt ve hücrelerde okunur. Önceki dosya silinmez; ona bağlı {n} hücre ve {m} alıntı onu göstermeye devam eder. Bu kaynak {k} araştırmada kullanılıyor."
   - Katlanmış geçmiş: "Önceki dosya: x.pdf · 16 Eyl'de değiştirildi" ve "Yeniden çıkarım reddedildi: metinli sayfa 12 → 9".
2. **Hücre (tablo).** "PDF removed" etiketi üç etikete ayrılır: "PDF çekildi", "Önceki PDF", "Eski metin". Hücre panelinde açıklama cümlesi: "Bu değer önceki dosyadan alıntı yapıyor. Alıntılar o dosyanın metnini açar. Recheck güncel dosyayı okur."
3. **Yanıt alıntısı.** Alıntı açılır penceresi ve `PassageSheet` aynı etiketi gösterir. Yanıtın üstünde, `stale_selection` bandıyla aynı yerde: "Bu yanıtın okuduğu bir PDF sonradan değiştirildi ya da metni yeniden çıkarıldı. Alıntılar okunan metni açar; yeni metin için yanıtı yeniden oluşturun." `pdf_removed` alıntıda PDF sekmesi kapalıdır (bugünkü 404 hatası giderilir).
4. **PassageSheet bandı.** `pdf_replaced`: "Önceki PDF · değiştirildi {tarih}"; PDF görünümü salt okunur. `text_superseded`: "Eski çıkarım ({sürüm}). Güncel metin farklı bölünmüş olabilir."
5. **Activity.** Yeni olaylar: `asset_replaced`, `asset_reextracted`, `asset_reextraction_rejected`. Kütüphane düzeyindeki olay, kaynağın üye olduğu her araştırmanın akışına yazılır.
6. Masaüstü ve 390 px'te, açık ve koyu temada, klavyeyle menü ve onay denetlenir.

## 7. Testler

**Depolama ve migration**

- 0026'daki bir veritabanında 0027: her asset için bir `current` çıkarım satırı; mevcut pasaj, kanıt ve hücre sayıları değişmez; iki etkin asset'li veritabanında migration durur ve hiçbir satırı çekmez.
- `_insert_passage`: aynı asset, sayfa ve metin, farklı `extraction_version` → yeni kimlik ve kendi etiketi; aynı sürüm → aynı kimlik.
- İkinci etkin asset benzersiz indeksle reddedilir; `upload_to_source` asset varken 409.

**Kopya girdisi (bugünkü hatanın regresyon testleri, önce kırmızı yazılır)**

- Aynı metinli dosya değiştirmeyle eklenince doldurma StepInput'u her metni bir kez taşır ve `passage_scope.available` tek dosyanın sayısıdır.
- Aynı durumda `_retrieve` tek eklenmiş kaynakta "küçük belgeyi bütün ver" yolunu kullanır ve tekrar eden metin seçmez.

**T03: dosya değiştirme**

- Doldurma ve yanıttan sonra değiştirme: hücre değeri ve kanıt bağları aynı; kanıt eski pasajı açar ve vurgu bulunur; işaret `pdf_replaced`; yanıtın iddia ve bağları aynı, `source_text_changed` doğru; `applicability` değişmez.
- Değiştirmeden sonra recheck ve yeni yanıt StepInput'u yalnız yeni asset'in pasajlarını taşır; eski pasaj kimliği allowlist'te yoktur ve model onu gösterirse `unknown_passage_id` alır.
- Değiştirme başka bir araştırmada da geçerlidir; o araştırmanın hücresi de işareti gösterir.
- `wrong_file` çekme: işaret `pdf_removed`, eski dosya 404; `replaced`: eski dosya yalnız kanıt bağı olan araştırmaya açılır (soru 4'e bağlı).
- Etkin run varken değiştirme 409; aynı dosya 422; CSRF ve başka araştırmanın kaynağı 404.

**T03: yeniden çıkarma**

- Geçen çıkarım: yeni pasajlar, eski pasajlar `passages_for` ve FTS aramasında yok, `passage(id)` ile var; hücre `text_superseded`; yanıt `source_text_changed`.
- Reddedilen çıkarım (daha az metinli sayfa): geçerli çıkarım ve pasajlar değişmez, `rejected` kaydı ve sebebi görünür.
- Aynı sürüme tekrar istek iş yapmaz; `include_stale` doldurması gölgelenmiş kanıtlı hücrede yalnız öneri üretir.
- Duraklatılmış doldurma, yeniden çıkarmadan sonra devam eder: tamamlanmış adımlar tekrar çağrılmaz, kalan adımların StepInput'u yeni pasajları taşır, eski revizyonlar değişmez.
- Gömme: gölgelenmiş pasajların vektörleri silinmez, anlamsal sıralamaya girmez.
- CLI `--dry-run` veritabanına ve dosyalara yazmaz (satır sayıları ve dosya hash'leri önce/sonra aynı).

**T03: kaynak sürümü**

- Yayıncı sürümü satır olarak eklenir: preprint satırının hücreleri kopyalanmaz; yeni satırın recheck'i preprint pasajını allowlist'e almaz (mevcut trigger testine ek olarak akış düzeyinde).
- D33 ile onaylanan dosya `wrong_file` ile çekilip doğru sürüme eklenir: eski hücre `pdf_removed`, yeni sürümün pasajları eski hücreye bağlanamaz.

**T15'in bu dilimdeki payı**

- Değiştirme ve yeniden çıkarmadan sonra yedek ve geri yükleme: eski ve yeni dosya manifestte ve hash'leri doğru; her iki pasaj kuşağı, `asset_extractions` satırları ve eski kanıtın vurgusu geri gelir.
- Araştırma A kalıcı silinir: B'nin eski kanıtının gösterdiği değiştirilmiş dosya diskte kalır.

**Web**

- `npm run build`, `npm run lint`.
- Playwright (fixture sunucusu, senaryolu model): doldur → PDF'i değiştir (onay sayıları) → hücrede "Önceki PDF" → Show evidence eski metni ve vurguyu açar → recheck önerisi yeni dosyayı gösterir; yanıt alıntısında aynı etiket ve bant; `pdf_removed` alıntıda PDF sekmesi kapalı.
- Chrome'da masaüstü ve 390 px.

**Gerçek model:** Bu dilim model davranışını değiştirmez; zorunlu değil. Canlı kütüphane kopyasında `deixis reextract --dry-run` raporu, sahibin toplu yeniden çıkarma kararına girdi olur (soru 3). Kopyada bir yeniden çıkarma sonrası D43 araştırmasında 23 hücrelik doldurma tekrarı isteğe bağlıdır; yapılırsa `gpt-5.6-luna` ile ve sonuç tek araştırmayla sınırlı raporlanır.

**Bu dilimde geçmeyecekler:** chunker değişikliği ve sınırı aşan alıntılar, OCR (dilim 4), çöp kutusu ekranı ve T15'in çöp kısmı (dilim 3), meta veri düzeltme geçmişi, aynı dosyanın ayrı eserlerde kayıtlı olması (kimlik eşleştirme).

## 8. Sahibe sorulanlar

Her birinde önerim ilk seçenekti; sahip yedisinde de onu seçti (16 Eylül 2026). 7. soruya yanıt "öteki iş bitti, başla" oldu.

1. **Değiştirme kapsamı.** PDF kaynak sürümüne, kaynak sürümü kütüphaneye ait; PDF'li 44 kaynak birden çok araştırmada kullanılıyor.
   - a. Kütüphane genelinde değiştir; onay ekranı etkilenen araştırmaları sayar. (öneri)
   - b. Araştırma başına dosya seçimi: asset'e araştırma bağlamı eklenir; veri modeli ve görünümler belirgin büyür.
2. **Kaynak sürümü başına tek kullanılan PDF.**
   - a. Evet; benzersiz indeks, ikinci ekleme 409, değiştirme ayrı eylem. Ek dosyalar (supplementary) ileride ayrı tür olarak gelir. (öneri)
   - b. Birden çok PDF'e izin ver, girdide metin hash'iyle tekrarları ele.
3. **Yeniden çıkarma ne zaman.**
   - a. Kaynak başına eylem + CLI; canlı kütüphanedeki 67 dosya için önce kopyada kuru çalıştırma raporu, toplu uygulama ayrıca senin onayınla. (öneri)
   - b. Yalnız kaynak başına eylem, toplu yol yok.
   - c. Açılışta eski sürümdeki her dosyayı kendiliğinden yeniden çıkar.
4. **Değiştirilen eski PDF kanıttan açılsın mı.**
   - a. Evet, salt okunur ve "Önceki PDF" bandıyla; yalnız o dosyanın pasajına kanıt bağı olan araştırmada. Yanlış dosya (`wrong_file`) bugünkü gibi yalnız metin. (öneri)
   - b. Hayır; her çekilmiş dosya yalnız metin olarak açılır.
5. **Yeni çıkarım ne zaman geçerli olur.**
   - a. §4'teki otomatik denetimi geçince hemen; geçmezse eski metin kalır ve görünür. (öneri)
   - b. Her zaman kullanıcı onayıyla (eski/yeni karşılaştırma ekranı gerekir).
6. **Etkin run sırasında.**
   - a. Kaynağın üye olduğu herhangi bir araştırmada etkin run varsa 409. (öneri)
   - b. İzin ver; yalnız sonraki adımlar etkilenir.
7. **Kirli çalışma ağacı.** Dilim 2 `store.py`, `views.py`, `api.ts`, `i18n.ts` ve `ResearchView.tsx` dosyalarına dokunmak zorunda; bunlar şu an başka bir oturumun commit'lenmemiş değişikliklerini taşıyor.
   - a. O iş commit'lenene kadar yalnız kendi dosyalarımda çalışırım (migration 0027, testler, yeni modül); ortak dosyalara commit'ten sonra geçerim. (öneri)
   - b. Ortak dosyalarda şimdi dar düzenleme yaparım; commit'te yalnız kendi parçalarımı sahneye alırım (hunk ayırma el ile yapılır, hata riski var).

## 9. Alt adımlar

Her alt adımda önce testler yazılır ve kırmızı görülür, sonra uygulanır; sonunda backend suite çalışır.

1. **Depolama ve gölgeleme.** Migration `0027`; `_insert_passage` anahtarına `extraction_version`; `passages_for` ve `search_passages` gölgeleme filtresi; `upload_to_source` asset varken 409; `remove_asset` nedeni `wrong_file`. Testler: migration, tek kullanılan PDF, kopya girdisi regresyonları (doldurma ve `_retrieve`).
2. **Değiştirme ve yeniden çıkarma işlemleri.** `Store.replace_asset`, `Store.reextract_asset` (denetim, `rejected`), etkin run 409, her araştırmaya olay; uçlar (`PUT /assets/{aid}`, `POST /assets/{aid}/extractions`, `GET /assets/{aid}/impact`); CLI `deixis reextract [--dry-run]`.
3. **Görünümler.** `evidence_status`; hücre işaretlerinin ayrılması ve `include_stale` genişlemesi; yanıt kanıtında durum ve `source_text_changed`; `passage_view`; `replaced` asset'in kanıt bağlı araştırmaya açılması. T03 akış testleri.
4. **Arayüz.** Sources PDF satırı, onay ekranı, hücre ve alıntı etiketleri, `PassageSheet` bandı, Activity olayları; Playwright senaryosu; Chrome'da masaüstü ve 390 px.
5. **T15 ve canlı kopya.** Yedek/geri yükleme ve kalıcı silme testleri; canlı kütüphane kopyasında (ayrı veri dizini ve port) `reextract --dry-run` raporu; toplu uygulama sahibin onayına kalır.
