<!-- Plan denetimi (gpt-6.1-sol · high, salt okunur): tur 1 hazır değil (5 yüksek, 10 orta, 1 düşük; hepsi işlendi); tur 2 düzeltmeyle hazır (0 yüksek, 7 orta, 1 düşük; hepsi işlendi); yüksek engel kalmadı, üçüncü tur gerekmedi. Ham cevaplar /tmp/p9plan-review/answer1.md, answer2.md. -->
# P9 — Web sağlamlaştırma planı

**Tarih:** 30 Eylül 2026. **Başlangıç:** `06fa1b6` (D129). **Durum:** öneri; sahip soruları §9'da, her birinin önerilen
varsayılanıyla. **Üst belge:** [implementation-plan.md](implementation-plan.md) §9, P9 satırı: *kurulum/restore, hata
enjeksiyonu, performans ölçümü, erişilebilirlik, günlük kullanım düzeltmeleri; çıkış: desteklenen ortamda tekrarlanabilir
kurulum ve kabul matrisi, bilinen hatalar ve kapasite sınırları açık.* Bu belge yalnız plandır: kod, model çağrısı ve git
durumu değişikliği içermez.

## 1. Sade özet

DEIXIS bugün yalnız geliştiricinin makinesinde, geliştiricinin elleriyle çalıştığı biliniyor. P9'un işi, aynı şeyin
temiz bir checkout'ta, aynı adımlarla, her seferinde aynı sonuçla çalıştığını göstermek. "Başka bir kullanıcıda" çalıştığı
iddiası yalnız I08 (elle kurulum, §4) yapılırsa kurulur; yapılmazsa kanıt, geliştirici makinesindeki izole temiz
checkout'tur ve öyle yazılır; bir şey
bozulduğunda (süreç öldürülür, disk dolar, sağlayıcı yanıt vermez) verinin kaybolmadığını ve ekranın doğruyu söylediğini
göstermek; büyük bir kütüphanede uygulamanın ne kadar yavaşladığını ölçüp sınırı yazmak; klavye ve ekran okuyucuyla
kullanılabildiğini denetlemek; ve günlük kullanımda çıkan küçük kusurları kapatmaktır.

Şu an kanıtın çoğu **sahte modelle ve sentetik kayıtla** yazılmış testlerdir (pytest 3.131 geçti + bilinen bir başarısız
test, Playwright 111 geçti, lint 17 uyarı; D129 kaydı). Bunlar iş akışının doğru davrandığını gösterir. Mevcut F testi gerçek backend'i SIGTERM ile durdurup yeniden açar (sentetik kayıt, scripted
model); SIGKILL davranışını göstermez. Gerçek bir süreç öldürüldüğünde, gerçek temiz kurulumda, büyük kütüphanede ya da gerçek modelle ne olacağını göstermez. P9 bu boşlukları
tek tek adlandırır ve her birini ayrı bir ölçümle kapatır ya da "ölçülmedi" diye bırakır.

İki şey bilerek ayrı tutulur. Model gerektirmeyen işler (H0a–H8) P9'un çıkış koşulunu kapatır. Gerçek model gerektiren işler
(H9, H10) kendi dondurma kuralıyla, sonradan ve ayrı yürür; özellikle raporun gerçek modelle hiç tamamlanmamış olması
(D124, D126, D128) P9'un **bilinen sınırı** olarak yazılır, H9 bunu ölçmeye çalışır ama P9'u bekletmez (§9, S2).

## 2. Desteklenen ortam (tanım)

Bu tanım P9'un geri kalanının dayanağıdır; H0a bunu depoda sabitler.

| Öğe | Desteklenen | Kaynak / durum |
|---|---|---|
| İşletim sistemi | macOS, Apple Silicon (arm64). Gözlenen: macOS 27.0.1 (26A434). Daha eski macOS, Intel, Linux, Windows **desteklenmez ve sınanmaz** (Windows/macOS paketleri P10) | Gözlenen bu makinede; eski sürüm sınanmadı |
| Python | 3.12, `requires-python = ">=3.12,<3.13"` (`pyproject.toml`), `.python-version` 3.12, `uv` ile; native arm64 zorunlu (CLAUDE.md). Gözlenen: uv 0.11.24 aarch64 | Depoda sabit; uv sürümü sabit değil |
| Node / npm | Gözlenen: Node 22.23.2, npm 10.9.8. **Depoda sabit değil**: `apps/web/package.json`'da `engines` yok, `.nvmrc` yok | Boşluk, H0a kapatır |
| Tarayıcı | Sistem Google Chrome (Playwright `channel: 'chrome'`, `apps/web/playwright.config.ts`); arayüz için başka tarayıcı sınanmaz | Gözlenen: Chrome kurulu |
| Ağ | Yalnız loopback dinler (`DEIXIS_HOST`, `__main__.py::serve`); sağlayıcı ve model çağrıları dış ağdır | Kodda |
| Veri dizini | `~/Library/Application Support/DEIXIS` ya da `DEIXIS_DATA_DIR`; senkronize klasörler (iCloud/Documents) desteklenmez (`config.py` yorumu) | Kodda; eşleşme sınanmadı |
| Model/sağlayıcı hesabı | Kurulum testi hesap gerektirmez; model bağlantıları kurulumun parçası değildir ("Connections" ayarı) | README |

Desteklenen ortam dışı bir kombinasyonda P9 sonucu "desteklenmiyor" diye yazılır; "çalışmıyor" diye değil.

## 3. Bugün ne var: ölçülen, yalnız sahte modelle sınanan, bilinmeyen

"Ölçüldü" gerçek süreç/ağ/model çıktısına dayanan sayıdır. "Sahte" fake adapter, sahte PDF çekici ya da sentetik kayıtla
yapılmış testtir. "Bilinmiyor" hiçbir kanıt bulunamadığı anlamına gelir (arama yöntemi: dosya okuma ve `grep`; bulunamaması
yokluğun kanıtı değildir, H3 envanteri bunu doğrular).

### 3.1 Kurulum ve başlatma

| Var olan | Dosya | Kanıt durumu |
|---|---|---|
| `python -m deixis serve` (`--port`, `--no-browser`, `--dev`); port doluysa anlaşılır hata ve çıkış 2; dist yoksa API açılır ve uyarı verir; loopback dışı host reddedilir | `backend/deixis/__main__.py::serve`, `port_available` | `tests/test_cli_options.py` ve README komutları; **gerçek temiz kurulumda koşulmadı** |
| README "Quickstart": `uv sync`, `npm ci`, `npm run build`, `serve` | `README.md` | Adımlar geliştirici makinesinde kullanılıyor; başka kullanıcıda denenmedi. CLAUDE.md README'nin durum paragrafını eski olarak işaretliyor |
| Tek yazıcı sahibi: OS `flock` kilidi (`worker.lock`); ikinci örnek `worker: not_owner` görür ve kilit bırakılınca devralır | `workflow/worker.py`, `api/app.py::lifespan`, `/api/health` | `tests/test_api_flow.py` (ikinci örnek, süreç içi); **iki gerçek süreçle sınanmadı** |
| Kapanış: `timeout_graceful_shutdown=3`, açık olay akışları bağlantıyı tutmasın diye | `__main__.py::serve` | Yorumla gerekçeli; **ölçülmedi** |
| Kurulum sihirbazı, LaunchAgent, paket, `.app` | yok | Kapsam dışı; P10 |
| Model/OCR/denklem alt süreçleri (Codex RPC, Marker, yerel embedding, arXiv kaynağı) için terminate/kill yolları | `models/codex_rpc.py`, `workflow/equations.py`, `workflow/local_embedding_service.py`, `documents/*` | Kodda var; **ana süreç SIGKILL ile ölünce yetim alt süreç kalıp kalmadığı bilinmiyor** (T17'nin "artık worker/model süreci kalmaz" koşulu) |
| CI | yok (`.github` yok; README rozetleri "CI sonucu yok" diyor) | Tekrarlanabilirlik şimdilik elle |

### 3.2 Backup ve restore

| Var olan | Dosya | Kanıt durumu |
|---|---|---|
| `deixis backup <hedef>`: SQLite backup API anlık görüntüsü, `integrity_check`, atıf verilen PDF ve sağlayıcı payload'ları, SHA-256 manifesti, yarım klasörü silen hata yolu; Codex home ve kimlik bilgileri yok | `storage/backup.py::create_backup` | `tests/test_backup.py` (3 test), `tests/test_trash_backup.py`; **D34'te canlı kütüphane yedeği boş dizine geri yüklendi**: 30 tablo satır sayısı eşit, 65 PDF hash'i eşit, araştırma görünümü aynı, reopen 46/46. O zamandan 57 migration'a çıkıldı; aynı ölçüm yenilenmedi |
| `deixis restore`: manifest ve hash doğrulaması, var olan kitaplığı reddeder, `.restoring` ile yerleştirir | `backup.py::restore_backup` | `tests/test_backup.py::test_restore_refuses_changed_backup_and_existing_library` |
| Yedek sırasında sunucu yazıyor olabilir ("safe while serving") | `backup.py` yorum/README | SQLite backup API'sine güveniyor; **eşzamanlı yazıcıyla sınanıp sınanmadığı bilinmiyor** |
| Şema uyumu: `restore` yalnız `schema_versions` yazıyor; `db.migrate` **bilinmeyen (kodundan yeni) sürümü olan veritabanını reddetmiyor**, yalnız eksik dosyaları uyguluyor | `storage/db.py::migrate` (okundu) | **Bulgu (okuma ile, çalıştırılmadı):** eski bir checkout yeni bir kitaplığı sessizce açabilir. H4 doğrular |
| Migration öncesi otomatik yedek | yok | Bulgu; H4 sahip sorusu (S6) |

### 3.3 Hata işleme ve kurtarma

| Var olan | Dosya | Kanıt durumu |
|---|---|---|
| Açılışta `recover()`: `running` adımlar ve `started` model oturumları `outcome_unknown`, `running`/`pause_requested` koşular `paused` + `backend_restarted`; tamamlanmış adım yeniden çağrılmaz, `outcome_unknown` adım resume'da yeniden gönderilir | `workflow/worker.py::recover`, D121 | Çok sayıda süreç içi test (`test_api_flow.py` çökme testleri, `test_fetch_overlap_flow.py` dört çökme noktası, `test_report_flow.py`, `test_person_reading_flow.py`). D121 Limits kendisi yazıyor: **testler çökme durumunu simüle eder, süreci öldürmez** |
| Sağlayıcı hata/kota görünürlüğü, sıfır sonuçtan ayrı (D18, T05/E) | `flow.py`, `providers/common.py` | Playwright E: `acceptance.spec.ts:513`, işaretleyici `[rate-limit]` |
| Model çökmesi duraklatır, aynı modelde devam eder | `flow.py` | Playwright: `acceptance.spec.ts:523`, `[model-down]` |
| Uydurma konum yanıtı doğrulanmış yanıt gibi gösterilmez | `domain/contracts.py` | Playwright: `acceptance.spec.ts:541`, `[invent-locator]` |
| Başka fixture işaretleyicileri: `[read-fails]`, `[suggest-down]`, `[query-down]`, `[embed-fails]`, `[slow-cells]`, `[fill-fails-one-row]`, `[report-empty-section]`, `[report-bad-anchor]`, `[report-banned-word]`, `[report-review-finding]` | `tests/acceptance/fixture_server.py` | Sahte model |
| Kötü URL / özel ağ: DNS yeniden bağlama korumalı bağlantı (D6), `blocked_url` | `documents/fetch.py` | `tests/test_documents.py` assertion'ları (Playwright G güvenli metin gösterimini ve scripted iş akışını sınar, bu korumayı değil) |
| Sınırlar (kodda, `documents/pdf.py`, `documents/fetch.py`, `api/app.py`, D6): yükleme 50 MiB, indirme 30 MiB, çıkarım 400 sayfa, 3.000.000 karakter, 90 s, izleyici eşiği varsayılan 1 GiB. İzleyici **eşik aşıldıktan sonra** çıkarım sürecini durdurur, tahsisi önlemez; macOS `RLIMIT_AS` uygulamıyor, Windows'ta izleyici yok | `api/app.py`, `documents/pdf.py`, `documents/fetch.py`, D6 | Testler var. **Bilinen başarısız test:** `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit` "extraction timed out" diyor (testin kendisi eşiği üretimdeki 1 GiB yerine **100 MiB** verir); 17 Eylül devir kaydı "işle ilgisiz nedenle bozuk" diyor, **neden teşhis edilmedi**. İzleyicinin bu makinede, üretim eşiğinde işleyip işlemediği bilinmiyor; ürün güvenlik sınırı olduğu için H0b teşhis eder |
| Adapter tur sınırı 300 s (`client_timeout`) | adapter'lar | D88 gerçek ölçümde bir adjudication çağrısını duraklattı; gerçek, ama tek olay |
| Kaydedilmiş günlük dosyası | yok; `logging` 8 satır | Hata kaynağı ekran (koşunun `error` alanı) ve terminal çıktısı; P10'da terminal olmayacak |
| Disk dolu, yazılamaz veri dizini, bozuk/kesik veritabanı, şifreli veya sıfır sayfalı PDF | — | Kısmen: `grep` ile "encrypted" testi **bulunamadı**; sıfır sayfa/metin yok ve bütünlük testleri var (21 dosya `corrupt/integrity` geçiyor, anlamları H3 envanterinde ayrılır). Disk dolu için hiçbir test bulunamadı |

### 3.4 Performans ve kapasite

| Ölçüm | Kaynak | Ne gösterir, ne göstermez |
|---|---|---|
| Uçtan uca süre, gerçek model (`gpt-5.6-luna` · medium). D88'de üç tarihli kampanya: ilk ölçüm `quick` 12,1 / `standard` 29,9 dk (`detailed` 55,5 dk **kısmi okuma**, bir çağrı `client_timeout` ile koşuyu duraklattı); sonraki kampanyalarda `quick` 9,1 ve 7,5 dk, yani revize `quick` hedefini (≤ 10) karşıladı, `standard` ve `detailed` karşılamadı. D95: iki konuda geliştirme ölçümleri (kuantum `quick` 12,9–14,0, paket `quick` 13,8–14,1, `standard` 20,8, `detailed` 41,8 dk). D111: önceki koşuların saklı süreleri (`standard` 17,7, 19,9 ve bir zaman aşımı beklemeli 29,2 dk) | `docs/decisions.md` D88, D95, D111 | Bunlar birleştirilmiş bir örnek ya da bugünkü performans sonucu değildir: farklı commit'ler, farklı konular, az tekrar. Hedefler `quick` ≤ 10, `standard` 15, `detailed` 20 dk. Dilim 17a'dan (keşif içi getirme) ve dilim 31'den sonra **son ürün commit'inin uçtan uca süresi bilinmiyor** |
| Araştırma görünümü: 7.769 kaynaklı araştırmada `research_view` olay döngüsünde 37 s sürdü; bu DeepSeek sağlık kontrolünü 20 s'lik bağlantı zaman aşımında düşürdü | `tests/test_view_scaling.py` başlık notu | Düzeltme **SQL ifade sayısı** ile test ediliyor, duvar saati ile değil; sentetik kayıtlar. Bugünkü gecikme ve bellek **ölçülmedi** |
| Arayüz ilk boyama, büyük pasaj listesi, büyük PDF, hızlı arama ölçeği | — | **Bilinmiyor** |
| Eşzamanlılık: `model_concurrency` 6; olay akışı ve yedek alma aynı anda | `config.py` | Model eşzamanlılığı için ölçüm var (D89 vd.); sunucu yüklü iken arayüz yanıtı ölçülmedi |
| Test paketi süresi | `pyproject.toml` yorumu | 8 dk 42 s seri, 1 dk 13 s `-n auto` (22 Eylül, 10 çekirdek); sonra testler çoğaldı |

### 3.5 Erişilebilirlik

| Var olan | Dosya | Kanıt durumu |
|---|---|---|
| Kurallar: odak halkası, `role=grid`, combobox/listbox, `role=status/alert`, dekoratif simgeler `aria-hidden`, 4,5:1 kontrast, azaltılmış hareket | `.impeccable.md` §9 | Yazılı kural |
| `aria-*`/`role` kullanan 39 kaynak dosya; `prefers-reduced-motion` blokları (`index.css` genel blok, `EvidenceTable.css`, `workspace.css`, `ResearchView.tsx`) | `apps/web/src` | Kodda var; **ölçülmedi** |
| Klavye: kanıt tablosunda ok tuşları, insan kuyruğunda Tab sırası | `acceptance.spec.ts` (24 `press` çağrısı), `human-queue.spec.ts`, `report.spec.ts` | Bazı akışlar için davranış testi |
| Dar ekran (390 px) ve koyu tema ekran görüntüleri | `acceptance.spec.ts` `shot(...)` çağrıları | Görüntü üretir; görüntüler bir iddiaya bağlı değil |
| Otomatik erişilebilirlik tarayıcısı (axe vb.), ekran okuyucu geçişi, gerçek kontrast ölçümü, 200% yakınlaştırma | — | **Yok; bilinmiyor** |

### 3.6 Günlük kullanım açıkları

| Kalem | Kaynak | Durum |
|---|---|---|
| Rapor gerçek modelle hiç tamamlanmadı: D124 (tablo hazır değil, rapor başlamadı), D126 (IV. bölümde `unknown_passage_id`), D128 (IV. bölümde `anchor_not_in_cell_evidence`, 8 oturum); yalnız R1 ve R7 ölçülebildi; seri kapalı, dördüncü deneme yok | `docs/decisions.md` | D127/D129 kodu sahte/scripted modelle sınandı, **gerçek modelde etkisi ölçülmedi**. D128/D129: yeni ölçüm, bilinen korpustan bağımsız bir korpus ister |
| Rapor hazır olmayan tablo: `continue_with_failed` açık seçimle (D125) | D125 | Sahte modelle |
| `sw` aramasının keşif sonunda kısa başlığı yok, ilk kaynak dahil edilene kadar (D39/D119 sınırı) | `TODO.md` "Carried over from slice 31" | Açık, karar bekliyor |
| Dilim 31 test borcu: eski cevap testi tek kısa PDF kullanıyor; eski pdf/ocr/tablo/rapor testi yalnız durum geçişlerini yürüyor; D119 yer değiştirmeleri eski uçtan uca iddiaları tam karşılamıyor; kanıt tablosu kabul testi kaynakları UI'dan değil API'den dahil ediyor | `TODO.md` | Açık |
| `arXiv` aramasında aralıklı 406 (neden bilinmiyor) | D88 | Açık; bugünkü sıklık bilinmiyor |
| PDF çekicide dürüst kimlik (`User-Agent`'ta iletişim e-postası) | `TODO.md`; `config.py:84` `DEIXIS_CONTACT_EMAIL` var | TODO maddesi açık görünüyor; koddaki durumun tam karşılığı H7'de doğrulanır |
| Erteleme kararları: bellek benzeri gizli bağlam, niyet çipleri, Playwright ile PDF edinme | `TODO.md` | "Planlanmadı"; P9'a girmez |
| README durum paragrafı eski | CLAUDE.md | H1/H8 düzeltir |
| P7/P8 kapsamından **uygulanmış olanların tam listesi** | README (model bağlantıları ve sağlayıcılar yazılı); P8 (başka model incelemesi, yayın takibi) için backend'de ilgili bir modül **bulamadım** | H0a, matrisin hangi özellikleri kapsadığını koddan çıkarır; P8'in uygulanmamış olması P9'un işi değildir, yalnız matriste "yok" yazar |

## 4. Kabul matrisi (P9'un merkezi)

Matris, P9'un tek teslimidir. Her satır bir iddia, o iddiayı hangi **kanıt türü** gösterdiğini ve neyi **göstermediğini**
söyler. Kanıt türleri: **S** sahte model/sentetik kayıt (pytest/Playwright), **G** gerçek süreç (alt süreç başlatılıp
öldürülür, gerçek `uv`/`npm`), **A** gerçek ağ, modelsiz (örneğin OpenAlex'e anahtarsız istek), **M** gerçek model,
**E** elle/insan. Matris `docs/product/p9-acceptance-record.md` (H8'de oluşur) ve `scripts/p9/run_matrix.sh` (H1'de
başlar, her batch satır ekler) olarak tek komutla yeniden koşulabilir olur; ham çıktı `.local/p9-*` altında kalır
(izlenmez), kayda hash ve sayılar girer.

**Satır kuralları.**

1. **Sınıf.** Her satır ölçümden önce bir sınıf alır: **zorunlu** (geçmeden P9 kapanmaz), **isteğe bağlı** (geçmezse
   "ölçülmedi/başarısız" diye yazılır, kapanışı bekletmez) ya da **yalnız ölçüm** (eşiği yok, sayı yazılır). Zorunlu:
   I01–I07, F01–F04, F06, F09, F10, B01, B01n, B03, X01–X06 ve A–G; F07/F08'in H3 envanterinde kapsam içi kalan sınıfları ve
   eşikli K alt ölçümleri de zorunludur ve **ölçümden önce tek tek sınıflandırılıp dondurulur**. İsteğe bağlı: B02 (sahip onayı yoksa
   "ölçülmedi"), I08 (ama bkz. ikinci kullanıcı iddiası), F05, X07, R01–R02. Yalnız ölçüm: eşiği olmayan K alt ölçümleri. K01
   N noktaları, K03 ve K06 eşikli/eşiksiz parçalar ayrı alt kimliklerle (K01a…, K03a/b, K06a/b) kaydedilir ve her biri kendi
   sınıfını ve sonucunu taşır. Kayıtta her satırın ayrı bir `Sınıf` sütunu olur.
2. **Kapanış kuralı.** Veri kaybı, kanıt bütünlüğü ihlali, uygulanmayan bir güvenlik sınırı (F09 dahil) ve ciddi/kritik
   erişilebilirlik kusuru açıkken H8 kapanmaz. "Bilinen sorun kaydı" başarısız bir **zorunlu** satırı geçmiş saydırmaz; kayıt
   yalnız düzeltilmeyen **isteğe bağlı** ve **yalnız ölçüm** bulgularını taşır. Bir zorunlu satır düzeltilemiyorsa P9 açık kalır
   ve sahibe götürülür (kapsam daraltma sahibin kararıdır).
3. **Sınanabilirlik.** Her satır tek iddiaya bağlanır ve şunları yazar: başlangıç durumu, tetikleyici, gözlenen sonuç (API
   yanıtı, DOM öğesi, dosya ya da veritabanı durumu) ve eşik. "Health 200", "mesaj anlaşılır" ya da "test eklendi" tek
   başına geçme ölçütü değildir; aşağıdaki satırlar bu kurala göre yazılmıştır.
4. **Kayıt alanları.** Her sonuç iki ayrı alan taşır: **yürütme türü** (otomatik test, gerçek süreç, gerçek ağ, elle) ve
   **veri/model gerçekliği** (sentetik kayıt, scripted model, gerçek kayıt, gerçek model). "Gerçek süreç" gerçek kayıt ya da
   gerçek model anlamına gelmez.
5. **Yalıtım.** Bu matrisin H0a–H8 satırları gerçek model çağrısı yapmaz ve sahibin keychain'ine, model hesaplarına, kişisel CLI
   yapılandırmasına ve kütüphanesine dokunmaz: harness ortam değişkenlerini **tek tek adlandırılmış** izin listesiyle geçirir (veri dizini, port ve model home harness
   tarafından üretilir; `.env` yüklenmesi, çalıştırılan checkout'ta kişisel `.env` bulunmayarak ya da yüklenmesi test sınırında engellenerek
   önlenir; bu, H0a'nın **ilk adımı olarak kontrol edilir** ve bütün harness'lerden önce geçmelidir, geçmezse sınama başlamaz; modelsiz
   uygulama sınamalarında dış istekler reddedilir, kurulum indirmeleri ayrı kapsamdır), keychain için `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` (H1 bu ortam değişkeninin
   bu sürümde işlediğini doğrular), `PATH` model CLI'lerini içermez. Gerçek bir bağlantı sağlık kontrolü yapılırsa ayrı bir
   gerçek-ağ satırı olarak kaydedilir.

**A–G yeniden kullanımı.** İlk dilimin A–G kimlikleri korunur, yeni bir A–G yazılmaz; ancak mevcut testlerin kapsamı kimliğin
tamamı değildir ve aşağıda ayrı yazılır. Mevcut Playwright kanıtı (`apps/web/e2e/acceptance.spec.ts`; yürütme: otomatik,
veri: sentetik kayıt, scripted model):

| Vaka | İddia | Mevcut test (S) | P9'un eklediği |
|---|---|---|---|
| A | Yanıt atfı saklı pasajı açar | `:357` | Yok; büyük kütüphanede açılma süresi (K04) |
| B | Yalnız özet kaynağı özet olarak etiketli, sayfasız; uydurma konum doğrulanmış yanıt olmaz | `:433`, `:541` | Yok |
| C | Preprint ve yayın ayrı sürüm | `:328`, `:445` | Yok |
| D | Yanıltıcı anahtar sözcük dışlanır, gerekçe kalır | `:313` | Gerçek model davranışı P2 vakalarında; P9 dışı |
| E | Sağlayıcı kotası ve model hatası görünür, sıfır sonuç değil | `:513`, `:523` | G: gerçek süreçte sağlayıcı zaman aşımı/5xx (F-satırları) |
| F | Reload ve backend yeniden başlatma sonrası aynı durum | `:494`, `:499` (gerçek süreç, `server.stop()`/`start()` ile düzgün durdurma; sentetik kayıt, scripted model) | **SIGKILL ile öldürme** (F01–F03) |
| G | PDF içi talimat ve kötü URL iş akışını değiştirmez | `:338`, `:454`: metnin metin olarak gösterilmesi ve scripted modelin davranışı; kötü URL/DNS koruması ayrı backend testlerinde (`test_documents.py`) | Gerçek modelin talimata direnci **gösterilmez** (P2 vakaları); kötü URL sınıfı F08 envanterinde eşlenir |

**Yeni satırlar.** Kimlik `I` kurulum, `F` hata, `K` kapasite, `X` erişilebilirlik, `D` günlük kullanım, `R` gerçek model.

| Kimlik | İddia | Tür | Batch | Geçme ölçütü | Göstermez |
|---|---|---|---|---|---|
| I01 | Temiz klasörde `uv sync`, `npm ci`, `npm run build` hatasız biter | G | H1 | Üç komut 0 ile çıkar; süreleri kayda yazılır | Başka kullanıcı hesabı, başka ağ, eski macOS |
| I02 | `serve` açılır, `/api/health` `ok`, arayüz yüklenir; kapatınca port boşalır ve artık süreç kalmaz | G | H1 | `/api/health` 200 **ve** Chrome'da ana kabuk öğesi (soru kutusu) görünür; SIGTERM sonrası betiğin başlattığı PID ağacı ve port boş | Kullanıcının canlı 8765 örneği (dokunulmaz) |
| I03 | Dolu port: anlaşılır hata, çıkış 2, ikinci örnek yazıcı olmaz | G | H1 | Mesaj `Port … in use`; veri dizini değişmez | — |
| I04 | `apps/web/dist` yok: API açılır, uyarı verir | G | H1 | Uyarı satırı; `/api/health` 200 | — |
| I05 | Yazılamaz veri dizini (salt okunur): açılış başarısız, çıkış kodu sıfır değil, dizinde yeni dosya ya da yarım `library.sqlite` kalmaz | G | H1 | Çıkış kodu ≠ 0; dizin listesi önce/sonra aynı; hata çıktısı dizin yolunu ve nedeni tek cümlede söyler | Disk dolu (F05) |
| I06 | Aynı veri dizinine iki gerçek süreç: ikincisi `not_owner`, birincisi ölünce devralır | G | H2 | İkinci `/api/health` `not_owner`; ilki SIGKILL edilince ≤ 10 s içinde `owner` | — |
| I07 | Yalıtılmış ortamda (kural 5) model bağlantıları "hazır değil" ve nedenleriyle görünür; hesap istemez | G | H1 | `/api/connections` her model için `ready: false` ve boş olmayan `reason` döner | Model hesabının çalışması; gerçek bağlantı sağlığı |
| I08 | Temiz macOS kullanıcı hesabında yalnız README adımlarıyla kurulum | E | H1 | Build biter, `/api/health` ok, soru kutusu görünür; gereken ön koşullar ve README dışı her müdahale yazılır | Geliştirici olmayan kullanıcı deneyimi. **İkinci kullanıcı iddiası için zorunlu**; yapılmazsa iddia kurulmaz (kural 2 ve §1) |
| F01 | Model adımı sürerken SIGKILL: yeniden açılışta adım `outcome_unknown`, koşu `paused/backend_restarted`; tamamlanmış adım yeniden çağrılmaz; resume bu adımı **bir kez** yeniden gönderir ve tek yayımlanmış yanıt oluşur | G | H2 | Sahte yavaş adapter çağrı sayacı: tamamlanmış adımlar için çağrı artışı 0, `outcome_unknown` adım için tam 1; yeniden gönderim **ayrı model oturumu ve ayrı bütçe tüketimi** olarak kayıtlı (beklenen davranış, hata değil); yayımlanmış yanıt sayısı 1 | Gerçek sağlayıcının ilk gönderimi tamamlayıp ücretlendirip ücretlendirmediği (R02) |
| F02 | PDF indirirken / pasaj yazarken SIGKILL: yarım kayıt yok | G | H2 | Yeniden açılışta her `source_assets` satırının dosyası vardır ve hash'i eşittir ya da satır yoktur; `integrity_check` ok, `foreign_key_check` boş; önceden tamamlanmış pasajların kanonik içeriği değişmez; kesilen yazım tanımlı işlem sınırında ya tamamen bulunur ya tamamen bulunmaz | — |
| F03 | Yedek alırken SIGKILL, iki kontrollü noktada: manifest yayımlanmadan önce ve sonra | G | H2/H4 | Önce: klasör `restore` tarafından reddedilir ("tam yedek" sayılmaz); sonra: restore B01 karşılaştırmalarını geçer | — |
| F04 | SIGTERM/Ctrl-C ile kapanış 10 s içinde; açık olay akışı varken bile | G | H2 | Süre ve çıkış kodu; port boş | — |
| F05 | Disk dolu (küçük disk imajında): yazma hatası anlaşılır, veritabanı bozulmaz | G | H3 | `integrity_check ok`; UI/koşu hatası söylenir | Gerçek kullanıcı diski |
| F06 | Bozuk/kesik veritabanı dosyası ve bilinmeyen (yeni) migration sürümü: açılış reddeder, veri değişmez | G | H3/H4 | Açıklayıcı hata; dosya hash'i aynı | — |
| F07 | Sağlayıcı: zaman aşımı, 5xx, bozuk JSON, boş gövde, yavaş yanıt; her sınıf için saklı arama kaydı durumu ve ekranda görünen neden, sıfır sonuçtan ayrı | S | H3 | Her sınıf için: saklı `status` değeri ve görünen metin iddiası, test dosyası:satır ile envanterde | Gerçek sağlayıcı davranışı |
| F08 | PDF: şifreli, sıfır sayfa, çok büyük sayfa sayısı, bozuk; yükleme 50 MB üstü reddi | S+G | H3 | Durum kodu ve kullanıcıya görünen neden | Tüm gerçek dünya PDF'leri |
| F09 | Üretimdeki 1 GiB eşiğinde bellek izleyicisi, eşiği aşan bir PDF çıkarımını sonlandırır ve hata `extraction exceeded the memory limit` olur | G | H0b | Ölçeklenmiş (üretim eşiğinde) girdiyle süreç kanıtı: durdurma nedeni ve tepe RSS kayıtlı. Bilinen başarısız testin başarısızlığının ayrıştırılması **tek başına yeterli değildir**; eşiğin işlediği gösterilemezse bu ürün hatasıdır ve zorunlu satır kırmızı kalır | Windows (izleyici yok; P10); eşiğin altında kalan bellek kullanımı |
| F10 | Yedek alma + yazıcı aynı anda (çalışan koşu); **zorunlu** | G | H4 | Yedek `integrity ok`, geri yüklenince B01 karşılaştırmalarını geçer | — |
| B01 | Yedek → boş dizine geri yükleme **sunucu açılmadan** karşılaştırılır: her tablonun satır sayısı, tablo içeriğinin kanonik özeti ve her dosyanın hash'i ayrı ayrı eşit; ardından sunucu açılınca her araştırma görünümü JSON'u aynı (başlatmanın yazdığı `worker_owner`/recovery kayıtları izin listesiyle hariç) ve atıf çapaları açılır | S+G | H4 | Genel "tüm tablo" karşılaştırması (D34'te 30 tablo, bugünkü sayı betikle çıkarılır) | Model kimlik bilgileri (yedekte yok, bilinen) |
| B01n | Restore'un negatif vakaları: dolu hedef, artık dosyalı hedef (farklı hash), belirsiz hedef, eksik/değişmiş dosya, manifestsiz klasör | S | H4 | Her birinde `BackupError` ve hedefte değişiklik yok | — |
| B02 | Bugünkü kod, sahibin kendi kütüphane yedeğinin geri yüklenmiş kopyasını açar. Önce kopyanın şema sürümleri ve beklenen migration listesi kaydedilir; uygulanacak migration varsa uygulanır, yoksa sonuç **yalnız yeniden açılış**tır | G | H4 | Açılış hatasız; görünüm sayıları (araştırma, kaynak, pasaj) yedek anındakiyle eşit; yalnız sayılar kayda girer. Kopya **yalnız** `create_app(start_worker=False)` ve boş adapter'larla açılır: worker, arka plan model/OCR işi ve dış çağrı yok; saklı `queued` koşular çalıştırılmaz | Canlı dizin (dokunulmaz). Yalnız **sahibin açık onayıyla** (S4); onay yoksa satır "ölçülmedi" |
| B03 | Kodun bilmediği migration kimliği taşıyan kitaplığı kod açmaz | G | H4 | Ön kontrol **salt okunur** yapılır (WAL/yazma bağlantısından önce); reddetme hatası açıklayıcı; `library.sqlite` ve varsa `-wal`/`-shm` dosyalarının hash'i/boyutu önce ve sonra aynı | — |
| K01 | Araştırma görünümü süresi, N = 100 / 1.000 / 5.000 / 10.000 eser | G | H5 | S7'deki donmuş eşik | Gerçek model ve sağlayıcı gecikmesi |
| K02 | Görünüm kurulurken `/api/health` gecikmesi (olay döngüsü bloke süresi) | G | H5 | S7 eşiği | — |
| K03 | Sunucu tepe RSS, veritabanı ve veri dizini boyutu | G | H5 | S7 eşiği (RSS); boyut yalnız ölçüm | — |
| K04 | Hızlı arama (Cmd/Ctrl+K), kaynak listesi ve pasaj paneli ilk boyama süresi | G | H5 | **Yalnız ölçüm** (eşik önerisi S7'de yok; H5 dondurma kaydında eklenir ya da yalnız ölçüm kalır) | — |
| K05 | Büyük PDF: ilk sayfa ve sayfa atlama süresi | G | H5 | **Yalnız ölçüm** | Bütün PDF türleri |
| K06 | Yedek alma süresi ve boyutu, 5.000 eserde | G | H5 | S7 eşiği | — |
| K07 | Üst sınırlar ayrı yazılır: **sert sınır** (yükleme 50 MiB, indirme 30 MiB, çıkarım 400 sayfa / 3.000.000 karakter / 90 s), **izleyici eşiği** (1 GiB, aşım sonrası durdurur), **yapılandırılabilir varsayılan** (`model_concurrency` = 6) ve **ölçülen tepe** | S+G | H5 | Kaydın dört sütunu dolu | — |
| X01–X04 | axe taraması, dondurulmuş ekran listesi üzerinde: X01 açık/1280 px, X02 koyu/1280 px, X03 açık/390 px, X04 koyu/390 px; ciddi ve kritik bulgu sayısı | G (tarayıcı) | H6 | Ciddi + kritik bulgu sayısı **0** (yalnız kaydedilmiş bulgu yeterli değil; zorunlu) | Axe'in yakalamadığı (odak sırası anlamı, metin kalitesi) |
| X05 | Klavye yürüyüşü: A–G akışı yalnız klavyeyle; odak görünür, Esc ile kapanan panel odağı geri verir | S (Playwright) | H6 | Senaryo geçer | Gerçek kullanıcı alışkanlığı |
| X06 | Azaltılmış hareket ve %200 yakınlaştırma | S | H6 | Animasyon kalmaz; %200'de temel görevler tamamlanır, temel kontroller ve kanıt erişimi kesilmez ya da örtülmez | — |
| X07 | VoiceOver: üç akış (açılış, yanıt+atıf, kanıt tablosu hücresi) | E | H6 | Her akışta görev tamamlandı mı (evet/hayır), etiket ve okuma sırası sorunları ve odak engelleri listelenir | Başka ekran okuyucular; tek geçiş, tek kişi |
| D01… | Günlük kullanım kalemleri (H7) | S/E | H7 | Kalem başına | — |
| R01 | Yeni korpusta rapor, gerçek modelle: R1–R11 (D124 beklenti tablosu) | M | H9 | Bkz. §7 | Başka korpus, başka model, hız/maliyet oranı |
| R02 | Gerçek model çağrısı sürerken SIGKILL: adım `outcome_unknown` kalır; kullanıcı resume edince aynı adım **bir kez** yeniden gönderilir ve tek yayımlanmış yanıt oluşur; yeniden gönderim ayrı model oturumu ve bütçe tüketimi olarak kayıtlı | M | H10 | Bkz. §7 | İlk gönderimin sağlayıcı tarafında tamamlanıp tamamlanmadığı, ücretlendirilmesi ve toplam fatura **bilinmez** |

Matrisin tamamı "geçti" demeden önce şu sınır açık yazılır: S satırlarının geçmesi iş akışının davranışını gösterir,
model kalitesini ya da canlı sağlayıcıyı göstermez (AGENTS.md "Verification Matrix").

## 5. Batch'ler

Her batch ayrı bir commit olur; commit ve push yalnız sahibin istediği zaman, doğrudan `main`'e yapılır (PR yok). Batch
kabul edilirken tam takım (`uv run python -m pytest -q`, `npm run build`, `npm run lint`, tam Playwright) bir kez koşulur ve
sayılar yazılır; geliştirme sırasında yalnız ilgili test dosyaları koşulur. Karar numarası yazım anında `decisions.md`'deki
en yüksek numaradan sonra seçilir; kabul edilen kalıcı ürün kararı ilgili batch'te kaydedilir. Canlı 8765 örneğine ve sahibin kütüphanesine
**hiç** dokunulmaz: her sınama geçici `DEIXIS_DATA_DIR` ve başka port ile koşar; süreçler yalnız betiğin kendi başlattığı
PID'ler üzerinden sonlandırılır (`pkill` yok). Boyut tahmini: **S** yarım gün, **M** bir gün, **L** iki–üç gün ajan çalışması
artı gpt-6.1-sol planı/kod denetimi; tahmin ölçüm değildir.

### H0a — Taban çizgisi, ortam sabitleme ve özellik envanteri (S)

**Kapsam.** (1) Temiz bir `git worktree`'de tam matrisi bir kez koşup sayıları taban çizgisi olarak kaydetmek: pytest
(seri ve `-n auto` süreleri), build, lint uyarı sayısı (beklenen 17), Playwright (beklenen 111). (2) Desteklenen ortamı (§2)
depoda sabitlemek: `apps/web/package.json`'a `engines`, bir `.node-version`, README'ye desteklenen ortam satırı; başka hiçbir
bağımlılık değişmez. (3) Kodda uygulanmış özellik listesini çıkarmak (hangi sağlayıcı, model bağlantısı, P7/P8 parçası var),
matrisin kapsamı için. (4) Sahibin günlüğünü (S9) başlatmak.

**Dosyalar.** `apps/web/package.json`, `.node-version`, `README.md` (yalnız ortam satırı); taban çizgisi `.local/p9-baseline/`.

**Testler/kontroller.** Tam takım bir kez; sayılar taban çizgisi dosyasına.

**Çıkış.** Taban çizgisi sayıları kayıtlı; Node sürümü depoda sabit; özellik listesi matrisin kapsamına bağlı.

**Göstermez.** Başka makinede aynı sayıların çıkacağını (H1); bilinen kırmızı testin nedenini (H0b).

### H0b — Bellek sınırı teşhisi (S)

**Kapsam.** `test_extraction_is_stopped_when_it_exceeds_the_memory_limit` başarısızlığını teşhis etmek: zaman aşımı testin
makine yükünden mi (`-n auto` altında; testin 100 MiB eşiği ve 70 MB'lık sıkıştırılmış sayfası var), yoksa bellek izleyicisi
macOS arm64 27'de belleği göremediği için mi? Ardından **üretim eşiğinde (1 GiB) çalıştığı** ayrıca gösterilir (F09): eşiği
aşan ölçekli bir girdiyle, tepe RSS ve durdurma nedeniyle. İzleyici çalışmıyorsa bu **ürün hatasıdır** (1 GiB sınırı
işlemiyor) ve düzeltme `documents/pdf.py`'de yapılır; yalnız test kararsızsa test kararlı hâle getirilir ama F09 yine
üretim eşiğiyle ayrıca kanıtlanır.

**Dosyalar.** `documents/pdf.py` (gerekirse), `tests/test_documents.py`, `scripts/p9/` (ölçekli girdi üreteci), `.local/p9-h0b/`.

**Testler/kontroller.** Bilinen test tek başına seri (`-n 0`) ve `-n auto`; üretim eşiğinde süreç ölçümü (tepe RSS, geçen süre,
hata metni); tam pytest.

**Çıkış.** F09 geçer (üretim eşiğinde süreç kanıtıyla). Geçmezse P9 kapanmaz (§4 kural 2).

**Göstermez.** Bellek sınırının başka dosya türlerinde ya da eşiğin altındaki kullanımda işlediğini; Windows'ta izleyici yok.

**H0c (devam, D159).** OCR, JATS çizimi ve arXiv kaynağı alt süreçleri aynı üretim eşiğinde ölçüldü (`scripts/p9/child_memory_probe.py`): OCR ve JATS kendi süreç-içi izleyicisiyle durdu (geç: kernel tepe değeri sınırın yaklaşık 2,4 ve 1,5 katı), arXiv kaynağı durmadı ve D138'in ebeveyn izleyicisine alındı. D138'in açık maddesi kapandı.

### H1 — Temiz kurulum ve başlatma denetimi (M)

**Kapsam.** `scripts/p9/install_check.sh` (ya da Python): verilen bir commit'i geçici klasöre dışa aktarır (çalışma ağacını
değil), ayrı veri dizini ve ayrı port ile `uv sync`, `npm ci`, `npm run build`, `serve --no-browser` çalıştırır; I01–I05
ve I07'yi koşar; çıkışta betiğin başlattığı süreç ağacının bittiğini ve portun boşaldığını doğrular. `keyring`'e hiçbir
anahtar yazılmaz; `DEIXIS_CODEX_HOME` geçici dizine yönlenir. README Quickstart güncellenir (durum paragrafı, desteklenen
ortam, yedek komutları, "canlı örneğe dokunma"). Elle satır I08: sahibin ya da ikinci bir kullanıcının temiz hesapta README'yi
izlemesi; I08'i kimin yapacağı §9 S8'de. Keychain yalıtımı için `PYTHON_KEYRING_BACKEND` ortam değişkeninin bu `keyring`
sürümünde işlediği (gerçek keychain'e hiç erişilmediği) ayrıca doğrulanır; işlemiyorsa H1 bunun yerine ayrı bir kullanıcı
hesabı ya da `HOME` yönlendirmesi önerir ve durur.

**Dosyalar.** `scripts/p9/`, `README.md`, olası küçük `__main__.py` hata iletisi düzeltmeleri (yalnız bir kurulum adımı
anlaşılmaz hata veriyorsa).

**Testler/kontroller.** Betiğin kendisi; her başarısızlık modu için bir çalıştırma (port dolu, dist yok, yazılamaz dizin);
`git diff --check`.

**Çıkış.** I01–I05 ve I07 geçer (zorunlu; başarısızlık bilinen sorun kaydıyla kapanmaz, §4 kural 2); kurulum süreleri yazılı.
I08 yapıldıysa sonucu, yapılmadıysa "ikinci kullanıcı iddiası kurulmadı" notu yazılır.

**Göstermez.** macOS'un başka sürümünde, hiç `uv`/Node bulunmayan makinede, kurumsal ağ/proxy arkasında kurulumu; model
hesabı bağlamayı.

### H2 — Süreç düzeyinde çökme ve kapanış (M)

**Kapsam.** Sahte yavaş adapter'lı fixture sunucusu (`tests/acceptance/fixture_server.py` genişletilir ya da yanına küçük
bir sürücü) **gerçek alt süreç** olarak başlatılır ve SIGKILL/SIGTERM alır. Senaryolar: F01 (model adımı sürerken), F02
(PDF indirme ve pasaj yazımı sürerken), F03 (yedek sürerken), F04 (SIGTERM, açık olay akışı), I06 (iki gerçek süreç, kilit
devri). Her senaryo yeniden başlatıp `recover()` sonucunu, koşu durumunu, adım satırlarını, çağrı sayacını ve yetim alt
süreçleri (Codex RPC / yerel embedding runner yerine yerinde bir sahte alt süreç; gerçek `codex` bu batch'te
**başlatılmaz**) kontrol eder. SIGTERM kapanış temizliği ile SIGKILL sonrası çocuk süreç ömrü **ayrı** sınanır. SIGKILL kusuru, öldürülen ana sürecin kapanış
koduyla kapatılamaz: üretim yolunda ana süreç kaybını algılayan çocuk davranışı ya da uygun süreç sahipliği mekanizması gerekir
(`codex_rpc.py`/`local_embedding_service.py`; yalnız bu batch'te bulunan hata için). Harness temizliği gözlemden sonra yapılır ve
ürün başarısı sayılmaz.

**Dosyalar.** `tests/process/` (yeni, `-m process`; süresi 60 s'yi aşarsa varsayılan takımdan ayrı, `run_matrix.sh` koşar),
`tests/acceptance/fixture_server.py` yardımcıları, olası kapanış düzeltmeleri.

**Testler/kontroller.** Yeni process testleri, tam pytest, Playwright F dosyaları.

**Çıkış.** F01, F02, F04 ve I06 "geçti"; F03'ün **yedek alırken öldürme** kısmı burada, restore sonrası değerlendirmesi H4'te. Bulunan
her zorunlu satır hatası düzeltilir (§4 kural 2).

**Göstermez.** Gerçek `codex` alt sürecinin SIGKILL sonrası davranışı (H10'un konusu); güç kesintisi/çekirdek paniği
(SQLite WAL dayanıklılığı SIGKILL ile kanıtlanmaz, yalnız uygulama sonlanmasıyla).

### H3 — Hata enjeksiyonu envanteri ve boşlukları (M)

**Kapsam.** Önce **envanter**: §4'teki F satırı sınıflarının her biri için mevcut testi dosya:satır ile eşleştir
(sağlayıcı 429/5xx/zaman aşımı/bozuk yanıt, PDF şifreli/sıfır sayfa/çok büyük, yükleme reddi, SQLite kilidi, CSRF/Host,
model `client_timeout`, `model_mismatch`, şema onarım tükenmesi, kota bitmesi). Yalnız **test bulunmayan** sınıflar için
test eklenir; var olanlar tekrar yazılmaz. Disk dolu (F05): `hdiutil` ile küçük sparse disk imajı bağlanıp veri dizini
olarak kullanılır, PDF indirme ve SQLite yazımı sırasında dolması sağlanır. Bozuk veritabanı ve eksik dosya başlangıç
davranışı (F06) doğrulanır. Kullanıcıya görünen mesaj kontrol edilir: hata "bir cümle ve neden" mi söylüyor (.impeccable
kopya kuralı), yoksa ham istisna mı?

**Dosyalar.** `tests/test_p9_faults.py` (yeni, yalnız boşluklar), `tests/process/` (disk imajı), gerekiyorsa
`backend/deixis/api/app.py` hata eşlemeleri, `apps/web/src/i18n.ts` (İngilizce + Türkçe).

**Testler/kontroller.** Yeni testler; envanter tablosu kayda girer (sınıf, mevcut test, yeni test ya da "kapsam dışı + neden").

**Çıkış.** Her sınıf için bir satır; zorunlu satırların tamamı geçer. Bilinen sorun kaydı yalnız isteğe bağlı ve yalnız ölçüm
satırlarını kapatır (§4 kural 2).

**Göstermez.** Gerçek sağlayıcı/ağ davranışı; kullanıcıların karşılaşacağı, bizim düşünmediğimiz hata sınıfları.

### H4 — Yedek, geri yükleme ve yükseltme matrisi (M)

**Kapsam.** (1) Zengin sentetik kütüphane (fixture sunucusunun A–G, tablo, çöp, sw kuyruğu, rapor akışlarını koşarak
kurduğu) → `backup` → **boş** dizine `restore` → sunucu açılmadan **bütün tabloların** satır sayısı, kanonik içerik özeti ve
dosya hash'leri; sonra görünüm JSON eşitliği ve atıf çapalarının açılması (B01; D34'ün 30 tablosu bugün 57 migration'lık
şemaya genellenir). Negatif vakalar (B01n) aynı batch'te. (2) Yedek sırasında yazıcı (F10) ve F03. (3) **Şema koruması:** `db.migrate`'in
bilinmeyen sürümü reddetmemesi (§3.2) doğrulanır. Öneri (S6): **salt okunur ön kontrol**, `db.connect`'in `PRAGMA journal_mode = WAL`
yazısından ve `migrate`'ten önce; uygulanmış sürümler paketli migration dosyalarının kümesiyle karşılaştırılır (yalnız "en
yüksek sürüm" değil, kümede olmayan her kimlik), bilinmeyen kimlik açıklayıcı hatayla reddedilir ve dosyalar değişmez (B03). (4) **Yükseltme (yalnız sahibin açık onayıyla, S4):** gerçek kütüphanenin `backup` çıktısı geçici dizine geri yüklenir; önce
şema sürümleri ve beklenen migration listesi kaydedilir; kopya `create_app(start_worker=False)` ve boş adapter'larla açılır
(worker, model/OCR ve dış çağrı yok, saklı `queued` koşular çalışmaz); görünüm sayıları karşılaştırılır (B02); yalnız sayılar
kayda girer, içerik girmez. Onay yoksa satır "ölçülmedi" kalır. (5) Restore sonrası bağlantılar: kimlik bilgileri yedekte yok, UI bunu "hazır değil,
bağlantıyı yeniden kurun" diye söylüyor mu? (6) Migration öncesi otomatik yedek önerisi (S6) kararlaştırılırsa burada.

**Dosyalar.** `tests/test_p9_restore_matrix.py`, `scripts/p9/`, olası `storage/db.py` (sürüm koruması), `storage/backup.py`
(manifest'e gözlenen kod sürümü).

**Testler/kontroller.** Yeni testler, `tests/test_backup.py`, `tests/test_trash_backup.py`, tam pytest.

**Çıkış.** B01, B01n, B03, F03 (restore kısmı) ve F10 geçer; B02 sahip onayına göre geçer ya da "ölçülmedi"; şema koruması
kararlaştırıldığı gibi; kayıtta tablo sayısı ve hash sayısı yazılı.

**Göstermez.** Sahibin kütüphanesinin eksiksiz doğruluğunu (yalnız açılış ve sayı eşitliği); yedeğin başka makineye
taşınmasını (yol bağımlılığı `storage_path` yalnız dosya adı; başka makinede elle sınanır, I08 ile birlikte).

### H5 — Kapasite ve performans ölçümü, modelsiz (M–L)

**Kapsam.** Sentetik kütüphane üreteci (var olan `tests/test_view_scaling.py::library` mantığı genişletilir), gerçek sunucu
süreci ve gerçek Chrome ile: N = 100, 1.000, 5.000, 10.000 eser (ve 7.769'luk eski durumu yeniden üreten bir nokta).
Ölçülenler: `GET` araştırma görünümü süresi ve olay döngüsü bloke süresi (görünüm kurulurken `/api/health` gecikmesi),
sunucu tepe RSS, veritabanı ve klasör boyutu, hızlı arama (Cmd/Ctrl+K), kaynak listesi ve pasaj paneli ilk boyama,
büyük PDF (örn. 50 MB sınırına yakın, 500 sayfa) görüntüleyicide ilk sayfa ve sayfa atlama, ikinci sekme ve olay akışı,
yedek alma süresi ve boyutu. Eşikler ölçümden **önce** dondurulur (S7); ölçüm sonrası eşik değiştirilmez. Gerçek modelin
uçtan uca süresi bu batch'te ölçülmez (§3.4'te tarihî sayılar olarak kalır).

**Dosyalar.** `scripts/p9/capacity.py`, `tests/test_view_scaling.py` (gerekirse yeni kıyas testleri), bulunan darboğaz için
`workflow/views.py`/SQL indeksleri (yeni migration gerekirse `storage/migrations/0058_*`; yayımlanmış bir migration
düzenlenmez).

**Testler/kontroller.** Ölçüm betiği üç tekrar; en kötü ve ortanca yazılır; ifade sayısı testleri.

**Çıkış.** Kapasite tablosu (K01–K07): her eşik için ölçülen değer ve donmuş eşikle karşılaştırma; eşiği aşan noktada
**belgelenmiş sınır** ("N eserin üstünde X yavaşlar") ya da düzeltme; desteklenen üst boyut yazılı.

**Göstermez.** Gerçek sağlayıcı/model gecikmesi; sentetik kayıtların gerçek metin dağılımını; başka donanım.

### H6 — Erişilebilirlik denetimi (M)

**Kapsam.** (1) `@axe-core/playwright` yalnız geliştirme bağımlılığı olarak (S3) ve ana ekranlarda (yeni araştırma,
araştırma ekranı Answer/Papers/Evidence/Report, pasaj paneli, PDF sekmesi, kanıt tablosu, kütüphane, çöp, ayarlar/
bağlantılar, insan kuyruğu) × açık/koyu × 1280 px/390 px taraması. (2) Klavye yürüyüşü Playwright senaryosu (X05): A–G
akışı Tab/Shift+Tab/Enter/Esc/ok tuşlarıyla; her adımda odak görünürlüğü ve odak dönüşü. (3) `prefers-reduced-motion:
reduce` ve %200 yakınlaştırma senaryoları (X06). (4) Kontrast: axe'in `color-contrast` kuralı iki temada; ölçülemeyenler
(gradyan/görsel üstü metin) elle. (5) **Elle VoiceOver geçişi** (X07): üç akış için adım adım not; sahip ya da ben
yürütürsem notlar açıkça "elle, tek geçiş". Bulgular ciddiyete göre: ciddi/kritik bulgular bu batch'te `.impeccable.md`
kurallarına uygun düzeltilir; diğerleri bilinen sorun kaydına girer. Yeni UI bağımlılığı eklenmez.

**Dosyalar.** `apps/web/e2e/a11y.spec.ts` (yeni), `apps/web/package.json` (dev bağımlılığı), `apps/web/src/*` düzeltmeleri,
`.impeccable.md` (yalnız bir istisna gerekirse §10).

**Testler/kontroller.** `npm run build`, `npm run lint`, yeni spec, tam Playwright; masaüstü ve 390 px, açık ve koyu
görsel kontrolü (`.impeccable.md` §11).

**Çıkış.** X01–X06 (zorunlu) geçer, ciddi/kritik bulgu sayısı 0; X07 isteğe bağlıdır, sonucu ya da "ölçülmedi" kaydı yazılır.

**Göstermez.** Axe'in otomatik yakalayamadığı sorunları (anlamlı etiket, okuma sırası); başka tarayıcı/ekran okuyucu;
kognitif erişilebilirlik.

### H7 — Günlük kullanım düzeltmeleri (S–M, sınırlı)

**Kapsam.** Sahibin günlük kullanım günlüğü (S9: `.local/p9-daily-use-log.md`, izlenmez, sahip yazar, tarih + ne oldu + ekran
görüntüsü yolu; ham içerik ve ekran görüntüleri izlenmeyen özel alanda kalır, belgelere yalnız kimliksizleştirilmiş hata özeti girer) ile H2–H6'nın bulguları ve §3.6'daki açık kalemler bir listede toplanır ve **ciddiyet** sırasıyla
ele alınır: (a) veri kaybı veya kanıt anlamını bozan (AGENTS.md "Evidence Contract"), (b) iş akışını bloke eden, (c) yanıltıcı
ya da anlaşılmaz metin, (d) kozmetik. En fazla **10** kalem kapatılır; her kalemin tekrar üretimi, düzeltmesi ve testi ayrı
satırdır. §3.6'dan önerilen kalemler: dilim 31 test borcu dört kalemi, `User-Agent`
iletişim e-postası, README durum paragrafı. Yeni özellik girmez (örnek sorular, bellek, niyet çipleri TODO'da kalır). Mevcut davranışı değiştiren ürün kararları (keşif sonu
başlığı, açılışta yeni bir yedek önerisi mesajı) ayrı bir sahip kararı alınmadıkça H7'ye girmez; mevcut bir hata mesajının
açıklığını düzeltmek kapsam içidir.

**Dosyalar.** Kaleme göre; her commit tek kalem.

**Testler/kontroller.** Kalem başına odaklı test; tam takım; arayüz kalemlerinde masaüstü + 390 px görsel kontrol.

**Çıkış.** Kapatılan ve kapatılmayan kalemler listede ciddiyet ve nedenle yazılı.

**Göstermez.** Günlükte yazılmayan sorunları; günlüğün temsil ettiği kullanım süresinin ötesini.

### H8 — Matris birleştirme, bilinen sorunlar ve kapasite sınırları kaydı (S)

**Kapsam.** `scripts/p9/run_matrix.sh` tek komutla **otomatik** (S/G/A) satırları sırayla koşar ve sonuç tablosunu üretir; elle (E) ve
gerçek model (M) kayıtlarını tarih, ortam ve provenance ile rapora bağlar, yeniden yürütmez;
`docs/product/p9-acceptance-record.md` oluşturulur: desteklenen ortam, taban çizgisi sayıları, matrisin son sonucu (satır
satır: geçti / geçmedi / ölçülmedi / desteklenmiyor), **bilinen hatalar**, **kapasite sınırları**, **ölçülmemiş olanlar**
(rapor gerçek modelde, VoiceOver dışı ekran okuyucular, eski macOS, Windows, güç kesintisi). `docs/decisions.md`'ye
(yazım anında en yüksek numara D129; sonraki boş numara seçilir) "P9 model-free hardening closes" kararı eklenir: Status/Date/Context/Decision/Limits,
kanıt seviyesi açık. `docs/README.md` ve `README.md` durum satırı güncellenir. H9/H10 sonuçları varsa ayrı kararla eklenir.

**Dosyalar.** `scripts/p9/run_matrix.sh`, `docs/product/p9-acceptance-record.md`, `docs/decisions.md`, `docs/README.md`,
`README.md`.

**Testler/kontroller.** Matris tam koşu (en az bir temiz worktree'de baştan sona), `git diff --check`, bağlantı ve komut
doğrulaması.

**Çıkış.** Otomatik satırlar temiz worktree'de tek komutla tekrarlanır ve iki koşuda **aynı geçti/geçmedi sonucunu** verir (süre
ve RSS gibi değişken değerlerin aynen eşit olması beklenmez, eşikleri karşılamaları yeter); zorunlu satırların hepsi geçmiştir
(§4 kural 2); P9'un çıkış koşulu (implementation-plan §9) madde madde işaretlenir.

**Göstermez.** Gerçek model davranışını; matrisin başka makinede tekrarlandığını (H1 ve I08 dışında).

### H9 — Gerçek model: yeni korpusta rapor ölçümü (L) — **ayrı dondurma kuralı**

**Kapsam.** Kapalı P16 serisinin dördüncü denemesi **değil**; yeni bir seri (P9-R), yeni bir korpus, tek koşu. Kuralı §7'de.

**Dosyalar.** Yeni dondurma belgesi `docs/product/p9r-report-freeze.md`, sonuç belgesi `docs/product/p9r-report-results.md`;
ölçüm kiti `scripts/p6_eval/` (D124–D128'de kullanılan sürüm, hash'iyle); ham kanıt `.local/p9r-*/`. Ürün, yöntem ve şema
dosyaları bu batch'te **değişmez**.

**Kuru kontrol (modelsiz, ölçümden önce).** Dondurma belgesinde adlandırılan ürün commit'inin dondurma commit'inin atası olduğu, çalıştırılan ürün/yöntem/şema dosyalarının
seçilen ürün commit'iyle aynı olduğu (dondurma commit'iyle aradaki fark yalnız izin verilen ölçüm belgeleridir), `skill_package_hash`'in
dondurulan değere eşit olduğu, kit hash'lerinin eşit olduğu, izole veri dizini ve portla `/api/health`'in ok döndüğü.

**Çıkış.** Sonuç belgesi + bir karar (`decisions.md`), başarı ya da başarısızlık olduğu gibi.

**Göstermez.** Başka korpusu, başka modeli, oranı, hızı ya da maliyeti; R10'u (ölçülmez).

### H10 — Gerçek model: SIGKILL sonrası çağrı tekrarı (S, isteğe bağlı) — **ayrı dondurma kuralı**

**Kapsam.** Tek gerçek Codex çağrısı sürerken sunucuyu öldürüp resume etmek; kuralı §7'de.

**Dosyalar.** `scripts/p9/` (sürücü), `.local/p9-h10/`; ürün dosyası değişmez.

**Kuru kontrol.** H2'nin F01 sonucu (sahte adapter ile aynı senaryo) geçmiş olmalı; model/bağlantı hazır ve kota var.

**Çıkış.** R02 satırı: geçti/geçmedi ve gözlenen çağrı sayıları.

**Göstermez.** Sağlayıcı tarafındaki tamamlanma ve fatura; başka model/kota.

P6 dilim 2'den devreden (D142): bağımsız gelişim çizgisi (lineage) ölçümü, P9 başında ayrı bir L9 işi olarak planlanır (H9 yalnız raporu kapsar); ve D141'in keşif bulgusu (varsayılan akış NLP sorusunda 99 işten 1'ini dahil etti, 69'u beklemede) ayrı bir ürün bulgusu olarak P9'da incelenir, bulundu / beklemede / bulunamadı ayrı sayılarak.

P6 dilim 3'ten devreden (D154): kill-search'ün bağımsız gerçek-model ölçümü (K6, slice note §13: S1–S5, altı taze iddia, tek koşu, `p6-slice3-expectations.md` koşudan önce dondurulur ve Sol incelemesinden geçer) sahibin 2 Ekim 2026 kararıyla P9'a kaldı. K5'in geliştirme koşusunda sorgu (blok içi OR) alakasız geniş sonuç getirdi ve 3/8 tutulan iş özetsizdi (D154); bu K6 öncesi bir ürün bulgusudur.

P6 dilim 4'ten devreden (D157): düzenle-denetle-atıf kaldır-bayatlama dizisinin gerçek-rapor sürümü (slice note §9 ve §10: R18 düzenleme bütünlüğü, R19 bayatlama doğruluğu, R21 süre ve maliyet) ön koşulu olan, bugünkü kodla tamamlanmış bir gerçek-model rapor olmadığı için ölçülmedi (D124, D126, D128). Rapor tamamlanırsa: bir kopya kütüphanede dizi koşulur, beklentiler koşudan önce ayrı dosyada dondurulur, sonuç anlam desteği iddiası değildir. Kimlik kararlılığı (R20) ve bölüm yeniden yazma ancak yeniden yazma kurulursa ölçülür. Dilim 4'ün sentetik dizisi (`tests/test_report_edit_sequence.py`) kod davranışını sınar, bu borcu kapatmaz.

## 6. Sıra, bağımlılık, boyut

| Batch | Bağlı olduğu | Boyut | Model |
|---|---|---|---|
| H0a | — | S | hayır |
| H0b | H0a | S | hayır |
| H1 | H0a (ortam sabit) | M | hayır |
| H2 | H0a | M | hayır (sahte adapter); süreç harness'ini sağlar |
| H3 | H0a, H2 harness'i | M | hayır |
| H4 | H0a, H2 harness'i (F03 yedek-öldürme kısmı H2'de, restore değerlendirmesi H4'te) | M | hayır |
| H5 | H0a | M–L | hayır |
| H6 | H0a | M | hayır |
| H7 | H0b ve H2–H6 bulguları + sahibin günlüğü (günlük H0a'da başlar) | S–M | hayır |
| H8 | H0a–H7 | S | hayır |
| H9 | H8 kapanışı, korpus seçimi, dondurma commit'i ve dondurma incelemesi (§7), sahip onayı | L | **evet** |
| H10 | H8 kapanışı, H2 (F01 sonucu), dondurma, sahip onayı | S | **evet** |

H0a'dan sonra H0b, H1, H2, H5 ve H6 birbirinden bağımsızdır (ayrı worktree'lerle paralel yürüyebilir). H3 ve H4 H2'nin süreç
harness'inden sonra başlar; bu yüzden H2 öne alınır. Toplam: model gerektirmeyen kısım kabaca 9–12 gün ajan çalışması ve her batch için bir
Sol planı/kod denetimi turu; H9 ayrıca 2–3 gün ve gerçek model kotası.

## 7. Gerçek model gerektiren işler: ayrı kural

H9 ve H10 **H8'den sonra**, ayrı bir oturumda ve sahibin açık onayıyla başlar. Hiçbiri P9'un model-free çıkış koşuluna
girmez. AGENTS.md gereği: seçilen bağlantı ve model yerine başkası sessizce konmaz; model kotası yoksa batch bekler,
değiştirilmez (değişiklik sahibin kararıdır ve dondurma kaydına yazılır).

### H9 — Dondurma kuralı (P9-R serisi)

1. **Dondurulanlar, keşiften önce.** Araştırma konusu, kaynak seçme/dışlama kuralları, tablo sütunları, hazırlık aşamasının
   çağrı ve süre tavanları ve **toplam hazırlık denemesi sayısı** (öneri: en çok 2 keşif+doldurma denemesi) ilk model
   çağrısından önce dondurulur. Başarısız hazırlık denemeleri silinmez; her kaynak kümesi değişikliği gerekçesiyle ayrı
   kaydedilir. Rapora hazır bir korpus bulunana kadar korpus aranmaz: tavan dolarsa H9 "korpus hazırlanamadı" sonucuyla biter.
2. **Korpus bağımsızlığı.** Korpus D124–D129 geliştirmesinde hiç kullanılmamış bir konudan gelir. Kullanılmış konular ve
   korpuslar (paket boyutu/WSN araştırması ve Kurt 2017 kaynakları, SW-izi kuantum ve tıp ölçüm korpusları, bu belgelerde adı
   geçen başka konular) H9 başlamadan depo belgelerinden çıkarılıp dondurma dosyasına yazılır. Bağımsızlık, seçilen korpusun
   dahil edilen kaynaklarının **normalize DOI, sağlayıcı/eser kimliği, sürüm ilişkisi (aynı eserin preprint/yayın sürümü) ve
   yüklenen dosya hash'i** ile bu listeye karşı kesiştirilmesiyle denetlenir; kesişim boşsa "bağımsız" yazılır. Eşleştirilemeyen
   bir kaynak (DOI'siz, kimliği belirsiz) varsa o kaynak için **"bağımsızlık doğrulanmadı"** yazılır ve sonuç bu sınırla sunulur.
   Korpus ilk gözlemden sonra yanmış sayılır: aynı korpusla ikinci bir ölçüm "bağımsız" diye yazılamaz.
3. **Rapora hazır tablo koşulu.** Rapor, yalnız `report_ready` tabloda başlar: en çok 10 kaynak (R11'in ≤ 10 kaynaklı
   beklentisiyle uyumlu) ve hepsi metinli (D124'te iki yalnız-metaveri satırı raporu engellemişti). `continue_with_failed`
   **kullanılmaz**. Hazırlık sırasında başarısız satır çıkarsa, madde 1'in tavanı içinde tablo yeniden denenebilir ya da kaynak
   kümesi değiştirilir ve bu kayda yazılır. Hazırlık koşusu kontrollü ölçüm değildir; süreleri yalnız bilgidir.
4. **Dondurulanlar, ilk rapor isteğinden önce.** Ürün commit'i ve `skill_package_hash`, bağlantı/model/efor
   (öneri: `codex` / `gpt-5.6-luna` · medium, D124–D128 ile aynı), kaynak kümesi ve tablo hash'i, beklenti tablosu
   (D124'ün R1–R11 tablosu eşikleriyle değişmeden), durdurma kuralı, koşu sayısı (**bir**), oturum/süre tavanları (D128'deki
   60 oturum / 90 dk), ölçüm kiti sürümü ve **okuyucular**: R2 (30 iddia, sabit tohum), R3, R4b, R5, R6, R9 ve R11'in kimin tarafından,
   hangi tohum ve hangi "okunamadı" kuralıyla okunacağı. Yeni korpusun **R9 (kaynak, formülasyon) çiftleri**, rapor çıktısı görülmeden, doldurulmuş tablonun denklem sütunundan önceden
   dondurulan bir seçim kuralıyla belirlenir; çift dosyasının hash'i, kaynak/satır kimliği ve hücre revizyonu ilk rapor
   isteğinden önce kaydedilir, sonradan çift eklenmez ya da değiştirilmez, eski korpusun çiftleri taşınmaz; uygun çift yoksa R9
   "ölçülemedi" kalır. **R10 ölçülmez** ve öyle yazılır. Dondurma commit'i ölçümden önce
   atılır ve gpt-6.1-sol ile incelenir (önceki P16 dondurmalarında olduğu gibi; tur sayısı kayda).
5. **Tek koşu, gözlemci kuralı, müdahale yok.** Gözlemci her kontrolde adım ve oturum hatalarını, bölüm doğrulamalarını ve
   inceleme nedenini **saklı kök nedenden** okur (koşunun dış `pause_reason`'ına ya da `running` görünümüne güvenmez; D128'de
   koşu `running` görünürken bir adım `failed` olmuştu). Yalnız bütün kök nedenler `client_timeout` ise, tavanlar aşılmamışsa ve
   hak kullanılmamışsa aynı koşu 10 dakika sonra **bir kez** sürdürülür (D128'in kuralı). Başka ya da karışık nedende ölçüm durur
   ve sonuç **olduğu gibi** yazılır (R1c 1/1 ya da 0/1, oran olarak yorumlanmaz). Ürün, yöntem, doğrulayıcı ya da beklenti
   koşu sırasında değişmez. Başarısızlık sonrası düzeltme bu serinin içinde yapılmaz; ayrı bir slice'a gider ve sonraki ölçüm
   **başka bir yeni korpus** ister. Nihai kayıt, yürütücünün döndüğü ve **sıfır `started` model oturumu** kaldığı doğrulandıktan
   sonra alınır; tamamlanmaya bağlı metrikler, rapor tamamlanmadıysa hesaplanmaz ("ölçülemedi").
6. **Okuma ve sonuç dili.** Okumalar insan ya da model okuması olarak etiketlenir; model okuması AGENTS.md'ye göre "kayıtlı
   değerlendirme"dir, bağımsız insan doğrulaması değildir. Sayılar ayrı tutulur (bulunan, tekil, taranan, dahil edilen,
   incelenen, modele verilen, atıf yapılan). Okuma gerekçelerinin ham hâli `.local/` altında kalır; sonuç belgesine
   temizlenmiş özet girer. Sonuç "geliştirme sonrası yeni korpus, tek koşu, tek model, rapora hazır tablo koşuluna bağlı"
   diye yazılır; oran, genelleme, hız veya maliyet iddiası taşımaz. Başarı da başarısızlık da `decisions.md`'de ayrı bir karar
   olur.
7. **Sonucun P9'a etkisi.** P9'un bilinen sınırı yazısına tek satır eklenir (geçti/geçmedi/kısmen); P9'un kapanışı bu sonuca
   bağlı değildir.

Model-free ön koşul: H9 başlamadan D129 düzeltmesinin hâlâ ürün commit'inde olduğunu ve `skill_package_hash`'in dondurulan
değerle eşit olduğunu doğrulayan kuru başlangıç (P16 üçüncü deneme kuru başlangıcıyla aynı biçim) kayıtlı olur.

### H10 — Dondurma kuralı (isteğe bağlı)

Tek gerçek Codex çağrısı (en küçük adım): çağrı sürerken sunucuyu SIGKILL et, yeniden başlat, resume et. Dondurulanlar: model,
adım, beklenen davranış (adım `outcome_unknown` kalır, resume'da **bir** yeniden gönderim, tek yayımlanmış yanıt; yeniden gönderim
ayrı model oturumu ve bütçe tüketimi olarak kayıtlı, bu beklenen davranıştır), gözlenecek kayıtlar (adapter günlüğü, model
oturum tablosu). İlk gönderimin sağlayıcı tarafında tamamlanıp tamamlanmadığı, ücretlendirilmesi ve toplam fatura **bilinmez**;
yalnız DEIXIS'in kaydettiği oturum sayısı yazılır ve öyle yazılır. Sonuç R02 satırına girer.

## 8. Ölçüm kayıtlarının biçimi

- Her batch kendi sonucunu `docs/product/p9-acceptance-record.md`'ye tek bölüm olarak ekler (H8'de birleştirilir);
  ham çıktı `.local/p9-<batch>/` (izlenmez). Kayda sayı, süre, hash, komut satırı **ve** özet gerekçe/açık sorun girer; özel
  içerik, gerçek kütüphane içeriği ve ekran görüntüleri girmez.
- "Geçti" yalnız **yürütme türü** ve **veri/model gerçekliği** ayrı iki alanla birlikte yazılır (§4 kural 4); tablodaki S/G/A/M/E
  kısaltması bunların özetidir. Bir satırın birden çok kanıtı varsa ayrı yazılır.
- Ölçülmeyen ya da desteklenmeyen satır silinmez; "ölçülmedi" / "desteklenmiyor" diye kalır.
- Kalıcı kararlar `decisions.md`'ye ilgili batch'te, yazım anındaki en yüksek numaradan sonra yazılır (öneri: H8 kapanışı bir
  karar, H9 ve H10 sonuçları ayrı kararlar); belge yerleşimi
  `docs/layout.md`'ye uyar (`docs/product/`: ürün planları; `scripts/`: yalnız izole ölçüm araçları; `tests/`: deterministik
  testler; `.local/`: ham kanıt).

## 9. Açık sahip soruları ve önerilen varsayılanlar

Sahip seçimleri Claude ile gpt-6.1-sol birlikte verilen önerilen varsayılanla kapanır. Bu, **teknik** varsayılanlar için
geçerlidir. Gerçek kütüphane kullanımı (S4), özel içerik içeren günlük (S9), gerçek model çağrısı (S10, S11) ve commit/push
sahibin açık onayını ister; onay gelmezse ilgili satır "ölçülmedi" kalır.

| # | Soru | Önerilen varsayılan | Gerekçe |
|---|---|---|---|
| S1 | Desteklenen ortam: yalnız macOS arm64 (§2) mı, Linux da mı? | Yalnız macOS arm64, Python 3.12, Node 22, sistem Chrome. Linux/Windows P9'da sınanmaz | Tek kullanıcı, gerçek kullanılan ortam; Windows/macOS paketleri P10'da |
| S2 | P9 kapanışı H9'a (gerçek model, yeni korpusta rapor) bağlı mı? | Hayır. P9 H8'de kapanır; rapor sınırı "ölçülmedi/bilinen sınır" diye yazılır, H9 sonra | Çıkış koşulu kurulum, matris, bilinen hata ve kapasite; rapor P6'nın açık konusu ve kota/zamana bağlı |
| S3 | `@axe-core/playwright` dev bağımlılığı eklensin mi? | Evet, yalnız `devDependencies`; çalışma zamanı değişmez | Otomatik tarayıcı olmadan erişilebilirlik iddiası yazılamaz; `.impeccable.md` yalnız UI stil bağımlılığını yasaklıyor |
| S4 | Sahibin gerçek kütüphanesinin yedeğinden geri yüklenmiş kopya yükseltme testinde (B02) kullanılsın mı? | Öneri: evet, **ama yalnız sahibin açık onayıyla**; yalnız `backup` → geçici dizine `restore`, worker/model kapalı (`create_app(start_worker=False)`), canlı dizine hiç dokunmadan; kayda yalnız sayılar. Onay yoksa sentetik test yürür ve B02 "ölçülmedi" kalır | Gerçek veri en iyi yükseltme kanıtıdır; AGENTS.md canlı dizini korur; özel içerik sahibin kararıdır |
| S5 | Günlük dosyası/tanılama eklensin mi? | Hayır. Hata yerleri belgelenir (koşunun `error` alanı, terminal); günlük dosyası P10'da paketli uygulama için yeniden değerlendirilir | P9 sağlamlaştırır, özellik eklemez; terminal yokluğu P10'un sorunu |
| S6 | Şemadan yeni kitaplığı reddetme ve migration öncesi otomatik yedek eklensin mi? | Reddetme: evet (küçük, güvenlik; salt okunur ön kontrol, kümede olmayan her kimlik). Otomatik yedek: hayır; yalnız README'de "güncellemeden önce `deixis backup`" adımı. Açılışta yeni bir mesaj eklenmez (ayrı ürün kararı) | Reddetme sessiz veri bozulmasını önler; otomatik yedek disk ve süre getirir, ölçmeden eklenmez |
| S7 | Kapasite eşikleri (ölçümden önce donar) | 1.000 eserde araştırma görünümü ≤ 2 s; görünüm kurulurken `/api/health` ≤ 500 ms; 5.000 eserde görünüm ≤ 10 s ve olay döngüsü 1 s'den uzun bloke olmaz; 10.000'de ölçüm yalnız "çalışıyor/çalışmıyor" kaydı; sunucu RSS 2 GB altı; yedek 5.000 eserde ≤ 2 dk | 7.769 eserde 37 s'lik gerçek olay (test_view_scaling) bir üst sınır gösteriyor; sayılar el ile seçilmiş başlangıç noktasıdır, türetilmemiştir ve H5 dondurma kaydında aynen yazılır |
| S8 | I08 (temiz hesapta elle kurulum) kim yapsın? | Sahip, yeni bir macOS kullanıcı hesabında ya da yakın birinde, README'yi izleyerek, takıldığı yeri yazarak (15–30 dk). Yapılmazsa I08 "ölçülmedi" kalır ve **ikinci kullanıcı iddiası kurulmaz** (§1, §4 kural 2) | Geliştirici olmayan gözün yerine geçen tek yol |
| S9 | Günlük kullanım günlüğü süresi ve sahibi | Sahip H0a ile birlikte 7 gün yazar (`.local/p9-daily-use-log.md`, izlenmez, serbest biçim; ekran görüntüleri de `.local/`); belgelere yalnız kimliksizleştirilmiş hata özeti girer; H7 kalem sınırı 10 | Gerçek kullanımda çıkan hatayı biz tahmin edemeyiz; özel içerik izlenen belgelere girmez; sınır H7'yi bitirilebilir tutar |
| S10 | H9 korpus konusu ve model | Konuyu sahip seçer (kendi alanı, kullanılmış konu listesinin dışında); yoksa Claude+Sol üç aday önerir, sahip birini seçer; model `gpt-5.6-luna` · medium, kota yoksa bekler | Model değişimi sessiz olamaz; bağımsızlık listesi §7'de |
| S11 | H10 (SIGKILL sonrası gerçek çağrı) yapılsın mı? | Sahip açıkça isterse; aksi hâlde R02 "ölçülmedi" kalır | Çağrı başına küçük ama gerçek kota; bilgi değeri sınırlı (D121 davranışı zaten yazılı) |
| S12 | CI (GitHub Actions, macOS arm64) eklensin mi? | Hayır. Tekrarlanabilirlik `run_matrix.sh` ile yerel; CI ayrı bir sahip kararı ve Chrome/uv/npm kurulum süresi ister | Şu an "CI yok" dürüst bir durum; P9 bunu değiştirmeden tekrarlanabilir kanıt üretir |
| S13 | TODO'daki "örnek sorular" (boş kutu sorunu) P9'a girsin mi? | Hayır; özellik, sağlamlaştırma değil, TODO'da kalır | Kapsam kayması; H7 yalnız kusur kapatır |

## 10. Sınırlar ve riskler

- Bu plan hiçbir batch'in sonucunu öngörmez; §3'teki "bulgu" satırları (şema koruması yok, bellek testi kırmızı,
  yetim süreç belirsiz) **okuma ile çıkarılmıştır**, çalıştırılmamıştır; H0b/H2/H4 önce doğrular, sonra düzeltir.
- SIGKILL testleri uygulama düzeyinde dayanıklılığı gösterir, güç kesintisini ya da dosya sistemi hatasını göstermez.
- Kapasite ölçümü sentetik kayıtla yapılır; gerçek kütüphanelerin metin dağılımı ve PDF karışımı farklı olabilir.
- Sahibin günlüğü tek kullanıcının deneyimidir; ikinci kullanıcı (I08) yoksa kurulum bilgisi yalnız geliştirici makinesine dayanır.
- Model-free P9 kapanışı "ürün her koşulda doğru sonuç verir" demez; yalnız bu matristeki satırların bu ortamda bu sayıda
  geçtiğini söyler.
- H9'un tek koşusu, raporun gerçek modelde güvenilir olduğunu ya da olmadığını kanıtlamaz; yalnız bir yeni korpusta bir
  koşunun ne yaptığını gösterir (D128/D129 Limits).
