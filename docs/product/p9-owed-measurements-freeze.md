# P9 ölçülmemiş borçlar: P10 öncesi gerçek-model ölçümlerinin dondurma belgesi

**Tarih:** 3 Ekim 2026. **Durum:** 1. dondurma noktası (ortak kurallar ve kalem kuralları). Bu commit'te model çağrısı yapılmadı, sunucu başlatılmadı, sağlayıcıya istek gitmedi, hiçbir veri dizini okunmadı. Kararlar Claude Opus 5.5 ve `gpt-6.1-sol` medium tarafından sahip adına ortak verildi ([D205](../decisions.md)). İnceleme: `gpt-6.1-sol` high, salt okunur: 1. tur “hazır değil” (1 high, 4 medium, 2 low; hepsi işlendi), 2. tur “hazır”, bulgu yok. Push edilince ortak kapı (§0.4) geçer; her kalem yine kendi ekini bekler.

**Dayanak:** `STATUS.md` "Ölçülmemiş borçlar"; [D129, D141, D142, D154, D157, D171, D198, D202](../decisions.md); [H9/H9b dondurması](p9r-report-freeze.md) (§1.1, §1.2, §4.1, §4.1.1, §5, Ek A.4, Ek B); [dilim 2 L9 beklentileri](p6-slice2-expectations.md) ve [sonuçları](p6-slice2-results.md); [dilim 3 notu](p6-slice3-kill-search.md) §5, §6, §13; [dilim 4 notu](p6-slice4-editing-stale-measurement.md) §9-§10; [P9 planı](p9-hardening-plan.md) borç paragrafları.

## 0. Yetki, kapsam ve dondurma düzeni

1. **Yetki.** Sahibin 3 Ekim 2026 talimatları (“benden bir şey bekleme...”, “bana onay sorma; gpt 6.1 sol medium'a sor.”). Bu belgedeki her seçim Claude Opus 5.5 + `gpt-6.1-sol` medium ortak kararıdır (bir salt okunur tur; O1-O10). Sol O3'ü reddetti ve yerine yazdığı metni verdi; O1, O2, O4-O10'u değiştirdi; değişiklikler anlamca aynen alındı (D205). Sahip tek tek onaylamadı.
2. **Kapsam.** Beş borç: (1) dilim 2 gelişim çizgileri L9 (D142), (2) dilim 3 K6 kill-search ve sorgu biçimi (D154), (3) dilim 4 gerçek rapor dizisi (D157), (4) D141 keşif hunisi, (5) D129 bölüm IV çapa onarımı. Bu plan H8 matris çiftini, `TODO.md` borçlarını, paralel yükte düşen testleri ve D171'in durum paragrafındaki çelişkili cümleyi (“gate 1 passed” ile “has not passed”) kapatmaz (§10).
3. **İki aşama.** Bu belge kuralları dondurur. Her model kalemi kendi tarihli ekini (2. dondurma noktası) bu belgenin sonuna alır: sabitlenen ürün commit'i, ölçüm worktree'si, kit hash'leri, kaleme özgü donmuş girdiler. Ek, kalemin ilk uygulama modeli çağrısından önce `gpt-6.1-sol` high incelemesinden “hazır” alır (en çok 3 tur) ve koordinatörce push edilir. L9'un iki eki vardır: keşiften önce (konu, soru, sütunlar, `G`) ve lineage isteğinden önce (gerçekleşen satırlar, hash'ler, kapı değerleri, önizleme parmak izi). Ekler bu belgenin kurallarını değiştiremez; değişiklik yeni Claude + Sol medium kararı ve yeni high inceleme ister.
4. **Ortak kapı.** Hiçbir kalem bu belge “hazır” almadan ve koordinatörce push edilmeden başlamaz. Bu belgeye `gpt-6.1-sol` high en çok 3 tur bakar; çözülmemiş bir high ya da medium bulgu kapıyı kapalı tutar. Son düzeltmeleri, adıyla sayılmış olarak, tek bir dar `gpt-6.1-sol` medium doğrulaması onaylayabilir; bu doğrulama donmuş kural değiştiremez, inceleme kapsamını genişletemez. Bir kalem ancak hem bu ortak kapı hem kendi eki “hazır” ve push edilmiş olduğunda koşar.
5. **Kitler koddur.** Her yeni ölçüm betiğini `gpt-6.1-sol` yazar, Claude inceler (yazan ve inceleyen farklı şirket); belirleyici testleri ölçümden önce geçer. Kit hash'leri kalemin ekinde donar.
6. **Ön koşul (bütün kalemler).** H9b'nin sonucu ([D202](../decisions.md)) yazılmış ve push edilmiş, koordinatör Codex kotasını, 8873 portunu ve `../DEIXIS-h9*` worktree'lerini serbest bıraktığını kaydetmiş olmalı. Bu belge H9b'yi beklemez, H9b'nin hiçbir kuralını değiştirmez ve onun dosyalarına dokunmaz.

## 1. Ortak kurallar (her model kalemi)

1. **Ortam.** H9'un K05'i aynen ([D171](../decisions.md), freeze §4.1): kalemin sabitlenen commit'inde ayrık (detached) ölçüm worktree'si (`../DEIXIS-owed-<kalem>`), kendi arm64 `.venv`'i; `env -i` ile yalnız donmuş değişkenler; null keyring; `.env` yok; yalnız anahtarsız sağlayıcılar (IEEE, Scopus, CORE, SerpApi `not_configured`); veri dizini worktree altında `.local/p9-owed/<kalem>/data`; `127.0.0.1:8873` (tek yedek 8874). `DEIXIS_CODEX_HOME` canlı `codex-home`'dur ve yalnız K05'in dar istisnasıyla kullanılır: yürütücü üzerinde yalnız `test -d` çalıştırır; `~/Library/Application Support/DEIXIS` altında başka hiçbir şey okunmaz, yazılmaz, kopyalanmaz. Port 8765'e bağlanılmaz.
2. **Port 8765.** §4.1.1 aynen: her sunucu başlangıcında, her POST'tan hemen önce ve her nihai snapshot'tan önce kapalıya düşen `lsof` denetimi ve JSON kaydı; koordinatörün 8765 kuralı; elle durdurma ve 120 s çıkış doğrulaması (≤5 s `ps` okumaları), sunucu ve kayıtlı `codex app-server` alt süreçleri için.
3. **Model.** Ürünün her adımı `codex` / `gpt-5.6-luna` / `medium`, açıkça verilir. Başka model, bağlantı veya efor sessizce konmaz.
4. **Sıra.** Kalemler §2'deki sırayla, birbiri ardına koşar; hiçbiri H9b, bir matris çifti ya da başka bir Luna işiyle aynı anda koşmaz. Bir kalem, öncekinin sunucusu ve kayıtlı Codex alt süreçleri çıkmış olarak doğrulanmadan başlamaz.
5. **Durdurma.** Her koşu için H9 §5: yalnız bütün terminal kök nedenler `client_timeout` ise 10 dk sonra bir kez sürdürme; başka, karışık veya ikinci hata, model uyuşmazlığı, araç ihlali, okunamayan sayaç veya dolan tavan durdurur. Kota/kullanım sınırı kök nedeni kalemi “yapılmadı, bekliyor” yapar; başka modele geçilmez. **İstisna yalnız L9'a:** L9'un donmuş kota/yük kuralı korunur (aynı koşu; lineage koşusu için en çok 2, hazırlık koşusu başına en çok 3 sürdürme; yalnız koordinatör “bağlantı döndü” dediğinde; uygunluk yalnız kök neden sınıfına bağlı). Başka kaleme bu hak verilmez.
6. **Müdahale yok.** Koşu sürerken ve sonuç okunurken hücre, bağ, kaynak, iddia, plan, ürün, yöntem, şema veya doğrulayıcı değişmez. Tek istisna: Kalem 3'ün önceden donmuş işlemleri (§5). Duran bir ölçüm aynı korpusla düzeltilip yeniden koşulmaz.
7. **Sayaçlar.** Uygulama sayaçları yalnız yeni oluşan oturumları sayar (onarım ve yeniden gönderim dahil); kopyalanan tarihsel oturumlar sayılmaz. Poll aralığıyla okunan tavanlar durdurma eşiğidir, sert üst sınır değildir: uçuşta aşan çağrılar ayrıca yazılır ve kalemin kalan iznini düşürür. Bir kalem başka kalemin payını ödünç almaz.
8. **Okuyucular.** Okuma Claude'la yapılır (Luna'dan farklı şirket); H9 K09'un ikinci okuyucu komutuyla, depo dışında boş bir dizinde, ayrı oturumda: `claude -p --model claude-sonnet-5-5 --effort medium --tools "" --strict-mcp-config --setting-sources "" --no-session-persistence`. Okuyucu yalnız kitin ürettiği sayfayı görür. Sonuç “model okuması” diye yazılır, insan doğrulaması sayılmaz. Tamamlanmayan okuma, ilgili satırı `ölçülemedi` yapar.
9. **Kanıt.** Özel kanıt ölçüm worktree'sinin `.local/p9-owed/<kalem>/` altında izlenmeden kalır; yürütücü komut kaydı (`ledger.jsonl`), port kayıtları, kopya manifestleri ve snapshot'lar orada durur.
10. **Kopya kuralı.** Daha önceki bir ölçümün veri dizini yalnız bayt kopyasından okunur: kopyadan önce koordinatör kaynak kütüphanede yazan süreç olmadığını doğrular (`lsof` ile dosyayı tutan süreç yok, ilgili sunucu kapalı); `cp -Rp`; SQLite yan dosyaları dahil; sert bağ (`nlink > 1`), sembolik bağ ve yetkili veri dizini dışına çıkan yol reddedilir. Asıl dizin yalnız iki salt okunur işlemle açılır: `cp -Rp` ve manifest betiğinin dosya hash'lemesi (H9b'nin `manifest.py` yöntemi). Manifest her dosya için göreli yolu, bayt boyunu, SHA-256 değerini, `nlink` ve türünü yazar, bütününün SHA-256'sını verir; kaynak ve kopya manifestleri kopyadan önce ve sonra eşit olmalıdır, değilse kopya kullanılmaz. Kaynak için daha önce güvenilir bir manifest kaydedilmişse (H9 dizini için Ek B.2'deki `80764df4…2ded1f`) ayrıca onunla da karşılaştırılır ve fark yazılır. Sayım betikleri kopyayı `mode=ro` ve tek okuma işleminde açar; açamazsa durur.
11. **Saatler.** Gözlemci 15 s'de bir okur. Saatler: dilim 4'ün 60 dk'sı ilk işlem isteğiyle başlar, son işlemin yanıtı ve sıfır `started` oturum doğrulamasıyla biter; K6'nın 180 dk'sı ilk iddianın kill-search isteğiyle başlar, son iddianın koşusu terminal olup sıfır `started` oturum doğrulanınca biter; L9 hazırlığının 240 dk'sı ilk keşif koşusunun kuyruğa girdiği anda başlar, kabul edilen son doldurma koşusu terminal olunca biter; her doldurmanın 60 dk'sı doldurma isteğiyle, lineage koşusunun 60 dk'sı lineage isteğiyle başlar ve koşu terminal olunca biter; okuyucu saatleri istekle başlar, cevap dosyası yazılınca biter. Bütün beklemeler saate dahildir (`client_timeout` sonrası 10 dk dahil). Tek istisna L9'dur: L9'un kota/yük kuralıyla duraklayan koşunun duraklamadan koordinatörün “bağlantı döndü” talimatına kadar geçen süresi L9 saatlerine sayılmaz, ayrıca yazılır. Yeniden deneme, sürdürme ya da ikinci deneme hiçbir birleşik saati veya sayacı sıfırlamaz.

## 2. Sıra ve bütçe

Yeni izin, H9/H9b izinlerinden ayrıdır; H9b'nin payı kendi dondurmasına ve yeniden sabitleme kararına bağlı kalır, buraya eklenmez.

| Sıra | Kalem | Luna uygulama oturumu | Claude isteği | Not |
|---|---|---|---|---|
| 1 | D129 / RF sayımlarının okunması (§3) | 0 | 0 | H9b sonucundan |
| 2 | D141 huni sayımı (§4) | 0 | 0 | modelsiz; L9'un hunisi hazırlığı bitince eklenir |
| 3 | Dilim 4 gerçek rapor dizisi (§5) | en çok 10 / 60 dk | 0 | yalnız `cell_recheck` |
| 4 | K6 kill-search (§6) | en çok 120 / 180 dk | 2 okuma / 30 dk | |
| 5 | L9 gelişim çizgileri (§7) | en çok 240 | 2 okuma / 60 dk + 2 kuyruk / 30 dk | |
| | **Toplam** | **en çok 370** | **en çok 6** | |

Kit hazırlığındaki sağlayıcı sorguları (K6'nın `N` özetleri, L9'un `G` kimlikleri) birlikte en çok 60 gerçek istek, yeniden denemeler dahil; ayrı sayılır. İnceleme çağrıları (Sol) ölçümün dışında ayrıca kaydedilir. Kota bir kalemi durdurursa sonraki kalemler bekler; pay yeniden dağıtılmaz. Eksik ön koşul (korpus, tamamlanmış rapor) yerine model koşusu başlatılmaz; eksiklik kaydedilir.

## 3. Kalem 5 — D129: bölüm IV çapa onarımı (H9b kapsar; ayrı koşu yok)

**Ne ölçülür.** Ayrı ölçüm yok. H9b'nin donmuş sayımları ([D202](../decisions.md), Ek B.5) her kol için tam onarım ve RF yaması maruziyetini, denemeleri, doğrulamayı, uygulamayı ve yayımlamayı ayrı sayar; P19 a-e (yama denemesinde (e) uyarlamasıyla), eksik/okunamayan kategorileriyle. Kollar: A2 (bölüm IV'ün durduğu H9 tablosu, bağımsız değil) ve B (yeni Q3 korpusu).

**Yönlendirme.** Onarım yolu D198'in tam uygunluk koşuluna uyar: her sorun tam bir çapa alıntı yolunda `anchor_not_in_cell_evidence` olmalı ve tam olarak bir eşleşen hücre çifti bulunmalı; aksi hâlde D129'un tam onarımı uygulanır. “Yalnız hücre çapası sorunu olan bölüm yamaya gider” demek bu koşuldan geniştir; kullanılmaz.

**Bitiş.** H9b sonucu yazılınca: gerçek bir onarım denemesi (tam ya da yama) maruz kaldı ve sayıldıysa STATUS satırı “ölçüldü: [gözlenen sonuç], tek korpus/koşu sınırıyla” olur; maruz kalma etkinlik kanıtı değildir. Hiç deneme yoksa satır 🟡 “maruz kalma yok, ölçülmedi” kalır; ayrı koşu açılmaz, çünkü çapa hatası istenerek üretilemez ve onu üreten korpus zaten A2'dir. H9'un kayıtlı D129/P19 gözlemleri tarihsel kanıt olarak kalır; H9b gözden geçirilmiş RF/RF2 yolunu ölçer, D129'un nedensel yararını göstermez.

## 4. Kalem 4 — D141: keşif hunisinin sayımı (modelsiz)

**Karar.** D141'in bulgusu ölçülmemiş diye bırakılmaz ve canlı kütüphane hiç kullanılmaz: yeni korpusların kendi veri dizinlerinde, saklı kayıtlardan sayılır. Bu bir betimlemedir, oran ya da neden değildir.

**Girdiler (bayt kopyaları, §1.10):**

| Korpus | Kaynak | Ürün ve hazırlık kuralı |
|---|---|---|
| L9 NLP (D141) | `DEIXIS/.local/p6-slice2-l9/data/` (L9'un kendi izole kütüphanesi). Kardeş `owner-backup/` dizini kopyalanmaz, okunmaz. | `6e85654`; kuyruk kararı yok |
| H9 Q1 | `DEIXIS-h9run/.local/p9r-h9/data/`, koordinatör serbest bıraktıktan sonra | `87cee0b`; K03 kuyruk geçişi |
| H9b B Q3 | `DEIXIS-h9b-run/.local/p9r-h9b/b/data/`, H9b bittikten sonra; B hiç hazırlanmadıysa satır “korpus yok” | H9b'nin sabitlediği commit; K03 |
| L9 yeni korpus | §7'nin hazırlığı bitince (ekleme) | §7 |

**Sayılanlar (araştırma başına; kit `funnel_counts.py`):** tekil eser (payda) ve kaynak sürümü; modelin okuduğu özet; otomatik kararların geçmişi (model/kod dahil ve dışlama) ile son üyelik ayrı; K03 kuyruk kararları ayrı (seçilim etkisi); beklemedeki eserler için birbirini dışlayan tek bir birincil kategori, öncelik sırasıyla: inceleme kuyruğunda → PDF bekliyor, getirme denendi → PDF bekliyor, denenmedi → diğer; kuyruk üyeliği ve getirme geçmişi ayrıca ayrı boyutlar olarak da raporlanır (örtüşebilirler); tam metin için deneme, başarılı indirme, çıkarılmış PDF metni ve bir modele gerçekten verilen metin ayrı sayılır, getirme hataları saklı hata koduna göre kırılır. L9 NLP için ayrıca donmuş `G` zincirinin dört eseri: bulundu / bulunmadı ve son durumu. Kaydı olmayan değer `bilinmiyor`dur, sıfır değildir. Birincil kategorilerin ürün alanlarına eşlemesi kitte yazılır ve kitin incelemesinde (Claude) sabitlenir.

**Payda, durdurma, bütçe.** Payda her korpusun tekil eser sayısıdır; korpuslar arası toplam yazılmaz. Durdurma: kopya manifesti tutmaz veya kütüphane `mode=ro` açılamazsa o korpus `ölçülemedi`. Bütçe 0 model oturumu, 0 sağlayıcı isteği.

**Sonuç dili ve bitiş.** “Üç (L9 hazırlanırsa dört) soru, tek model; eserlerin nerede durduğunun betimlemesi.” Her hazırlık araştırması ve denemesi, başarısız olanlar dahil, ayrı satırda yazılır; deneme sayısı olduğu gibi verilir, “her biri tek koşu” denmez. Her korpus ürün commit'i ve hazırlık kuralıyla etiketlenir; farklar betimseldir, nedensel değildir. Bu sayım yalnız D141'in “huniyi incele” alt borcunu kapatır; STATUS'taki birleşik “fikir zinciri” satırını yeşile çevirmez (gelişim bağları §7'de).

## 5. Kalem 3 — D157: dilim 4'ün gerçek rapordaki dizisi

**Ön koşul.** H9b bir rapor tamamladıysa: B tamamladıysa B, yalnız A2 tamamladıysa A2; ikisi birden asla. H9b hiç rapor tamamlamadıysa bu kalem için yeni rapor koşusu açılmaz; R18, R19, R21 “ölçülemedi: tamamlanmış gerçek-model rapor yok” olur, borç ❌ kalır.

**Ortam.** Seçilen kolun veri dizininin bayt kopyası (§1.10), H9b'nin son snapshot'ı ve okurları bittikten sonra; raporu yazan ürün commit'i (o kolun sabitlenen commit'i) kendi ayrık worktree'sinde. Kit: `measure_edit.py` (API üzerinden; modele yalnız ürünün kendi `cell_recheck` adımı gider).

**Ek E (ilk düzenlemeden önce donar):** belirleyici işlem listesi ve başlangıç hash'leri. Liste E4 dizisinin gerçek rapor karşılığını kapsar: metin düzenleme; atıf kaldırma; hücre değişikliği önerisi ve kabulü (`cell_recheck`); kaynak çıkarma; düzenleme denetimi; denetimi eskiten ikinci düzenleme; “Böyle kalsın” ve ardından yeni değişiklik; revizyon ve kaynak geri yükleme; dışa aktarımda atıf numaralandırması; kaynak kalıcı silmenin reddi; ürünün yedeğiyle yeni, boş, izole bir hedefe yedekle-geri yükle gidiş-dönüşü. On iki rapor tablosu, bağlı kayıtlar ve yabancı anahtar bütünlüğü korunur; seçili tablolar dolu bir kütüphaneye doğrudan geri yüklenmez. Her işlem için beklenen bayatlama işaretleri işlem, iddia ve neden kodu düzeyinde, koddaki kurallardan önceden yazılır.

**Ne ölçülür.**

| # | Tanım | Payda |
|---|---|---|
| R18 düzenleme bütünlüğü | değişmez ihlali (etkin atıf kümesi, numaralandırma, dışa aktarım, modelin özgün revizyonunun baytları, gidiş-dönüş eşitliği) | işlem sayısı |
| R19 bayatlama doğruluğu | yanlış pozitif işaret / gözlenen işaret; yanlış negatif işaret / beklenen işaret; ayrı | gözlenen ve beklenen işaret; payda 0 ise `ölçülemedi` |
| R21 süre ve maliyet | işlem başına duvar saati; yeni model oturumu ve token | ölçüm, oran değil |

R20 (kimlik kararlılığı) ve bölüm yeniden yazma ölçülmez: yeniden yazma yok.

**Durdurma ve bütçe.** Ortak durdurma; model adımları ürünün sınırlı onarımıyla çalışır; kullanılamayan bir öneri elle düzeltilmez ve istenen vaka çıksın diye yeniden üretilmez; işlenemeyen vaka “sınanmadı” diye yazılır. En çok 10 yeni oturum / 60 dk; kopyalanan oturumlar sayılmaz.

**Sonuç dili ve bitiş.** “Tek rapor, tek korpus; kod davranışının gerçek rapordaki sınaması; anlam desteği iddiası değil.” Bitiş: R18, R19, R21 değerleri ya da `ölçülemedi`, sınanmayan vakaların listesi, sonuç bölümü ve ayrı karar kaydı.

## 6. Kalem 2 — D154: K6 kill-search ölçümü ve sorgu biçimi

**Karar: bugünkü ürün olduğu gibi ölçülür.** K6'dan önce sorgu derleme yolu ve `kill_search_query` yöntem dosyası değişmez. D154'ün K5 bulgusu (modelin yazdığı her bloğun içindeki terimler OR ile birleşiyor; genel ömür makaleleri döndü) açık kalır ve burada düzeltilmez, ölçülür. K5 commit'inden (`3091b0f`) bu yana `backend/deixis/providers/query_compiler.py`, `backend/deixis/workflow/candidates/terms.py` ve `methods/deixis-research/references/candidate-check.md` dosyalarına yalnız D193 (`98f651f`) dokundu; D193 sorgu yazımını registry bildirimlerine taşıdı ve dondurulan 39.683 çağrının 39.586'sının çıktısı bayt bayt aynı kaldı (kalan 97, bildirilmemiş uç nokta girdileri için adlandırılmış retlerdir). Ek K'nın kapısı bu dosyaların hash'ini sabitler.

**Korpus ve konu.** Hazırlanmış korpus gerekmez: K6 yeni, boş bir veri dizininde keşif başlatmadan bir araştırma açar (`POST /api/researches` koşu açmaz, `c025877`'de `backend/deixis/api/app.py:1053-1092`; kit her adımda beklenmeyen etkin koşuyu denetler ve görürse durur) ve adayları `owner_text` girişiyle, iddia sürümü Claude'un yazdığı donmuş içerikle (`human_edit`, sürüm 1) oluşturur. Ayrıştırma ölçülmez ve sonuçta öyle yazılır. Konu: H9 aday tablosundaki Q2'nin alanı (mobil robotlarda engelden kaçınan yörünge planlaması için model öngörülü kontrol); geliştirmede ve ölçümde hiç kullanılmadı. Dışlananlar: dilim 2 §14 listesi, L9 NLP, K5 iddiası ve araştırması, H9 Q1, H9b Q3, §7'nin L9 konusu. H9b B ile korpus paylaşımı yok: K6 korpus hazırlamaz, paylaşım bütçe kazandırmaz, `N` kümeleri görülmüş bir korpustan seçilirse S1 iyimser olur.

**Ek K (ilk K6 modeli çağrısından önce donar):** altı iddianın tam sürüm-1 yükü (önerme, öğeler, koşullar, varsayımlar, doğrulama planı); beşi için 1-3 eserlik `N` kümesi, en az biri için boş `N` (“yakın iş bilinmiyor”, Claude'un etiketi; bu iddiadan oran üretilmez); her `N` eserinin kimliği, sağlayıcıdan gelen özet metninin hash'i ve modele verilecek bütün metnin hash'i, Claude'un yazdığı beklenen ilişki (“bütün iddiayı söylüyor / bazı öğeleri söylüyor / söylemiyor”); S4b tohumu `20261002` (örneklem kuralı aşağıda); araştırma sorusu ve dili; ürün commit'i ve kit hash'leri; S6'nın sözcük normalizasyonu ve öbek eşleme algoritması. Özetler kit hazırlığında modelsiz bir betikle anahtarsız sağlayıcılardan alınır; istekleri §2'nin 60 isteklik sınırına sayılır.

**Ne ölçülür.** §13'ün S1-S5 tanımları aynen, şu eklerle:

| # | Tanım | Payda |
|---|---|---|
| S1 geri çağırım kaçağı | `N` eserlerinden sonuçta hiç olmayan / sonuçta olup kesilen / tutulan; ayrı | `N` eserleri |
| S2 yanlış `open` | beklentisi “en az bir öğeyi söylüyor” olan bir eser tutulup değerlendirilmişken `open` türeyen iddia | böyle iddialar |
| S3 yanlış `closed` | §13 gibi; her `closed` için kapatan eserin bütün-iddia alıntısı okunur, `N` dışındaki tanık da; gerçekten söylüyorsa “etiketsiz tanık” ayrı sayılır | beklentisi “`N`'de bütün iddiayı söyleyen yok” olan iddialar |
| S4a alıntı yeri (yapısal, tam sayım) | yayımlanmış bütün değerlendirme hücrelerindeki alıntılardan modele verilen metinde bulunanlar | bütün alıntılar |
| S4b alıntı desteği (model okuması, örneklem) | örneklem hücrelerinde okuyucunun hükmü: hücrenin alıntıları birlikte, hücrenin yazdığı ilişkiyi (destek türü, koşul uyumu) destekler / kısmen destekler / desteklemez; üçü ayrı sayılır | örneklenen hücreler |
| S5 bütçe ve süre | uçtan uca süre, model denemeleri, sağlayıcı istekleri, §6 tavanlarına karşı | ölçüm |
| S6 sorgu biçimi (yeni, modelsiz) | iddia başına modelin yazdığı bloklar, sağlayıcı başına derlenen sorgu, blok ve blok başına terim sayısı; dönen kayıtlardan başlık+özetinde her bloktan en az bir terim geçen / yalnız bazı bloklardan terim geçen; S1'de “sonuçta hiç yok” olan her `N` eseri için başlık+özetinin eşleşmediği bloklar; başlık/özet metni eksik kayıtlar ayrı | dönen kayıtlar; S1 “hiç yok” eserleri |

**S4b örneklemi:** evren, en az bir alıntı taşıyan yayımlanmış değerlendirme hücreleridir; alıntısız hücreler evrenin dışındadır ve ayrıca sayılır. Evren (iddia anahtarı, kill-search kimliği, eser kimliği, öğe kimliği) sırasıyla dizilir; `random.Random(20261002).sample(evren, min(20, |evren|))`. Evren boşsa S4b `ölçülemedi`.

Metni dondurulandan farklı gelen eser §13'ün kuralıyla değerlendirmeden çıkar ve ayrıca sayılır; ürün sonuçları bu dışlamayı uygulamak için düzenlenmez. S6 sözcüksel bir tanılamadır: sağlayıcı dizinlemesini yeniden üretmez, bir eserin neden dönmediğini kanıtlamaz. S1 ve S6'dan tek başına “geri çağırım kaybının nedeni sorgu biçimidir” sonucu çıkarılmaz. Bir düzeltme gerekirse sonraki ayrı bir karardır, bu dondurmanın parçası değildir.

**Okuyucu.** §1.8'deki yalıtılmış Sonnet okuyucusu S3 okumalarını ve S4b örneklemini birlikte yapar: toplam en çok 2 istek / 30 dk. Tamamlanmazsa etkilenen anlam satırı `ölçülemedi`.

**Durdurma ve bütçe.** Altı iddianın tek serisi; yeniden koşu yok. Ürünün iddia başına tavanları (60 model denemesi, taşıma tavanı) aynen; K6 toplamı en çok 120 oturum / 180 dk. Ortak durdurma kuralı; durmuş seride okunabilen ve okunamayan satırlar ayrı yazılır.

**Sonuç dili ve bitiş.** “Tek koşu, altı iddia, tek model; değerlendirilen alt kümede ve okunan metinde.” `open` hiçbir zaman “yok” diye yazılmaz. Bitiş: S1-S6 değer ya da `ölçülemedi`, sonuç bölümü ve ayrı karar kaydı (başarı da başarısızlık da).

## 7. Kalem 1 — D142: L9 gelişim çizgileri, yeni ve bağımsız korpusta

**Karar.** L9, H9b B'nin korpusunu paylaşmaz. Paylaşım bağımsızlık kapısını (§7 K0) geçemez, yazar-yıl/başlık alanı şartını sağladığı gösterilmemiştir ve korpus görülmeden `G` dondurulamayacağı için R14'ü düşürür; başarılı bir paylaşımlı sonuç bile asıl borcu açık bırakırdı. Bu yeni bir ölçüm protokolüdür; yanmış NLP ölçümünün sonradan değiştirilmesi değildir.

**Ek L1 (keşiften önce donar):** yazar-yıl ya da başlıkla anan, önceki bütün geliştirme ve ölçüm korpuslarının dışında tek bir taze konu; soru metni ve dili; üç geliştirme sütunu (`problem_addressed`, `established_or_changed`, `uncertainty_left`); seçim kuralları; zincir `G`: 2-4 eser, kimlikleri dondurmadan önce Crossref/OpenAlex'te doğrulanmış (istekler §2'nin 60 isteklik sınırına sayılır), yönlü gelişim çiftleri tek tek sayılmış ve eserlerin kendi özet ya da giriş cümleleriyle desteklenmiş; eşleme kuralı (normalize başlığın başı, ilk yazar, izinli yıllar; tutmayan satır `identity_unverified`); ürün commit'i ve kit hash'leri. Konu ve `G` Claude + Sol medium ile seçilir, Sol high incelemesiyle donar.

**Hazırlık.** Yeni ve boş veri dizini; `sw`, akademik, yalnız soru, keşif eforu `standard`; protokol kartı değiştirilmeden yürütücü tarafından onaylanır (ürün `approved_by=user` saklar; sonuç onaylayanın yürütücü model olduğunu yazar). H9 §1.2'nin yeniden deneme kuralı (madde 4) ve K03 kuyruk geçişi (madde 2; `claude-opus-5-5` medium, yalnız saklı metin, deneme başına 1, toplam 2 istek, 30 dk, ayrı defter, ürünün “person” etiketi bu satırlar için yanlıştır) açıkça benimsenir. H9 §1.2 maddesi 4'ün başarısız doldurma satırını sıradaki eserle değiştirme kuralı L9'a **uygulanmaz**: satırlar aşağıdaki belirleyici kuralla seçilir, başarısız doldurma satırı tabloda kalır ve K2'de sayılır. En çok 2 deneme; birlikte 180 uygulama oturumu / 240 dk, her doldurma dahil; her doldurma en çok 60 / 60. **İkinci deneme** yalnız birinci deneme hazırlığı tamamlayamadığında açılır: keşif, tam metin getirme/okuma ya da doldurma koşusu `completed` olmadıysa (altyapı hatası, çökme, model bağlantısı, koşu tavanı; ya da kota/yük sürdürme hakları tükendiyse, koordinatör bağlantının döndüğünü söyledikten sonra). Hazırlığı tamamlanmış ama K0-K3'ten birini geçemeyen deneme ikinci denemeyi açmaz; L9 “korpus koşulu karşılanmadı” diye biter. İkinci deneme aynı veri dizininde aynı soru, sütunlar, `G` ve kurallarla yeni bir araştırmadır; birincinin kayıtları korunur.

**Tablo ve kapılar.** Satırlar: dahil edilmiş eserlerden başı saklı PDF metni taşıyan ilk 15'i, `Store.included_sources` sırasıyla; elle ekleme, çıkarma, sıralama yok. Yalnız üç geliştirme sütunu; ürünün kendi `table_fill` yoluyla doldurulur.

- **K0 bağımsızlık (O2, eski K0'ın yerine; daha dar):** dahil edilmiş bütün eserlerin ve bütün sürümlerinin normalize kimlikleri (DOI ailesi, sürüm ekinden arınmış arXiv, OpenAlex, PMID, `identifier_mappings`) şu envanterlerle kesiştirilir: ölçümün commit'inde yeniden kurulan izlenen-belge envanteri (H9'un `old-corpus-inventory.json` yöntemi), H9 Q1 ve H9b B Q3 kaynak envanterleri, L9 NLP kütüphanesinin bayt kopyası. Her envanter hash'lenir; kökeni, kapsadığı korpuslar, kimlik şemaları ve eksik boyutları yazılır. Gerekli bir envanter yoksa kapı durur, kapsamı sessizce daralmaz. Örtüşme K0'ı düşürür; örtüşen eser sonuç görüldükten sonra çıkarılıp korpus kurtarılmaz. Boş kesişim yalnız “kayıtlı envanterler içinde örtüşme saptanmadı” demektir. Kullanılabilir kimliği olmayan kaynak `bağımsızlık doğrulanmadı`; eski yükleme hash'leri ve belgelenmemiş kimlikler `denetlenmedi`. `measure_lineage.py`'ye envantere dayanan bir `independence` yolu eklenir; sahip yedeğine dayanan eski yol kullanılmaz.
- **K1** `pdf_text_rows ≥ 6`: doldurmadan önce, modelsiz denetlenir (`measure_lineage.py rows` çıktısındaki satır sayısı ve tablo kurulduktan sonra, sütun eklenmeden `GET .../lineage` durumundaki `pdf_text_rows`; ikisi eşit olmalı); tutmazsa sütun eklenmez, doldurma yapılmaz.
- **K2** `nodes_complete ≥ 4` ve **K3** en az iki farklı sonraki eserden en az 3 aday çift: doldurmadan sonra.

**Ek L2 (lineage isteğinden önce donar):** tablo kimliği, satır listesi ve tablo yanıtının hash'leri, kapı değerleri, planın `counts` bölümü, önizleme parmak izi, tarih/saat. İstek bu parmak iziyle gönderilir.

**Ne ölçülür.** L9 beklentilerinin R12, R13, R15 tanımları, aralıkları, yapısal beklentileri ve R14 çift durumları aynen. R14 `x/|G|` olarak yazılır; beklenti en az bir kazanılmış çift; lineage koşusu tamamlanır ve hiç çift kazanılmazsa bu beklenti yanlışlanmış olur. Okuyucu (R12, R13, anma biçimi): §1.8'deki yalıtılmış Sonnet, en çok 2 istek / 60 dk; örneklem `min(|L|, 20)`, tohum `20261001`. Hazırlık bittiğinde bu korpusun hunisi §4'e eklenir.

**Durdurma ve bütçe.** Tek lineage koşusu: ürünün `max_model_calls` tavanı ve en çok 60 oturum / 60 dk. L9 toplamı en çok 240 uygulama oturumu. Bir kapı tutmazsa lineage koşusu yapılmaz, borç açık kalır; P10'dan önce üçüncü hazırlık denemesi ya da ikinci konu yok. L9'un kota/yük kuralı §1.5'teki gibi.

**Sonuç dili ve bitiş.** L9 beklentilerinin dili: “geliştirme sonrası yeni korpus, tek koşu, bağları üreten tek model, bu tabloya bağlı, desteklenen anma biçimiyle”; okuyucu modeller ayrıca. Bitiş: R12-R15 değer ya da `ölçülemedi` (kapıda durduysa nedeniyle), sonuç bölümü ve ayrı karar kaydı.

## 8. H9b arm B ile paylaşım: özet

| Kalem | B ile paylaşım | Gerekçe |
|---|---|---|
| D129 | evet, H9b'nin içinde | sayımlar D202'de donmuş |
| D141 | evet, B'nin hunisi sayılır | modelsiz, ek bütçe yok |
| Dilim 4 | B'nin tamamlanmış raporunun kopyası (yoksa A2'nin) | rapor yazmanın tek kaynağı H9b |
| K6 | hayır | korpus gerekmez; paylaşım S1'i iyimser yapar |
| L9 | hayır | bağımsızlık, alan şartı ve R14 (§7) |

## 9. Önceki dondurmalardan sapmalar (tarihsel dondurmalar değişmez)

1. L9 K0: sahip kütüphanesinin salt okunur yedeği yerine envantere dayanan, daha dar kesişim (O2).
2. L9 hazırlığı: K03 kuyruk geçişi ve H9 §1.2'nin yeniden deneme kuralı eklendi (eski L9 kuyruk kararını yasaklıyordu), başarısız satırı değiştirme kuralı alınmadı; ikinci deneme yalnız tamamlanmamış hazırlıkta; bütçe 300 oturum / 4 saatten 180 / 240 dk'ya, doldurma dahil; L9 toplamı 240.
3. L9 sırası: K1 doldurmadan önce denetlenir.
4. L9 okuyucu: Agent aracıyla Sonnet yerine yalıtılmış `claude -p` Sonnet medium.
5. L9 konusu yeni; `G` yeni ve kimlikleri doğrulanmış; R14 `x/|G|`.
6. K6: okuyucu S3 ve S4b'yi toplam 2 istek / 30 dk içinde yapar; S4, yapısal tam sayım (S4a) ve örneklem okuması (S4b) olarak payda ve örneklem evreniyle tanımlandı; S6 eklendi; konu Q2'nin alanı.
7. Dilim 4: E4'ün sentetik dizisi gerçek rapor üzerinde, rapor oluştuktan sonra donan işlem listesiyle.
8. D141: huni, yeni korpusların kopyalarında sayılır; canlı kütüphane yerine.
9. H9'un K05 ortamı ve §5 durdurma kuralı K6, L9 ve dilim 4'e uygulanır; L9'un kota kuralı korunur, başka kaleme verilmez.

## 10. Bitiş, sonuç dili ve STATUS

Her kalem üç sondan birine varır: değerler (paydalarıyla) ölçüldü; donmuş bir kapı ya da durdurma kuralıyla durdu; kota yüzünden bekliyor. Bunlar eşit tamamlanma kanıtı değildir. Sonuçlar `docs/product/p9-owed-measurements-results.md` dosyasına kalem başına tarihli bölüm olarak, kararlar kalem başına ayrı D kaydı olarak yazılır. STATUS yalnız kaydedilmiş sonucun desteklediği alt borç için değişir; kısmi ölçümler ve engellenmiş ön koşullar görünür kalır. P10, açık kalan ölçüm borçlarıyla ancak bu borçları ve sonuçlarını adıyla sayan açık bir koordinatör kararıyla ilerleyebilir; “bekliyor” P10 için kendiliğinden geçiş değildir. Bu plan H8 matris çiftini, `TODO.md` borçlarını (slice 31 dahil), paralel yükte düşen testleri ve D171'in çelişkili durum cümlesini kapatmaz; sonuncusu ayrı bir düzeltme ister.

## Ek K (4 Ekim 2026): K6 kill-search, 2. dondurma noktası

**Durum:** koşudan önce dondurulacak; `gpt-6.1-sol` incelemesi (en çok 3 tur; sahibin 4 Ekim kuralıyla her Codex çağrısı medium efordadır, §0.3'ün “high”i bu kalemler için medium olarak değiştirildi, koordinatör mesajıyla) ve koordinatör push'u sonrası geçerli. Kararı Claude Opus 5.5 ve `gpt-6.1-sol` medium ortak verdi (4 Ekim 2026, sahip adına; sahip tek tek onaylamadı). Bu ek §6'nın kurallarını değiştirmez.

**Sabitlenen ürün commit'i:** `7188ec8` (RF6; H9e'de ölçülen kod, paket hash'i `ccff02a1…`). K6 bu commit'te kendi ayrık worktree'sinde (`../DEIXIS-owed-k6`) koşar; origin/main'in sonraki commit'leri yalnız belge ve ölçüm kitidir ve ürün kodunu değiştirmemelidir (koşu öncesi `git diff 7188ec8 HEAD -- backend methods contracts` boş olmalı; boş değilse ek yeniden dondurulur).

**Donmuş girdiler:** `docs/product/p9-owed-k6-ek-k.json` (SHA-256 aşağıda): soru ve dil (Q2 alanının H9 metni, Türkçe); altı iddianın tam sürüm-1 yükü (önerme, 4-5 öğe, koşullar, kritik varsayım, en yakın basit açıklama, doğrulama planı; yük başına SHA-256); `N` kümeleri ve beklenen ilişki (Claude'un etiketi, Sol medium'un yaptığı düzeltmeyle): C1 {W4416799054 bütün iddia, W4383108357 bazı öğeler}; C2 {W4384519478 bütün iddia, W3204442505 bazı öğeler}; C3 {W2896154143 bütün iddia}; C4 {W4394862912 bazı öğeler: özette 10 ms süresi yok}; C5 {W4206270771 bazı öğeler: özette fiziksel robot sayısı yok}; C6 boş (“yakın iş bilinmiyor”, Claude'un etiketi; bu iddiadan oran üretilmez). Her `N` eseri için OpenAlex kimliği, DOI, sağlayıcı özetinin SHA-256'sı ve modele verilecek bütün metnin SHA-256'sı JSON'da. C4 ve C5'teki “10 ms” ve “en az 10 fiziksel robot” sınanacak sahip yazımı önermelerdir; doğrulanmış sonuç ya da çürütülmüş iddia değildir. S4b tohumu `20261002`; S6'nın sözcük normalizasyonu (`title_tokens` kuralı: NFKD, ASCII, casefold, `[^\W_]+`) ve öbek eşleme algoritması (terim, bir bloktaki bir terimin başlık+özet belirteç dizisinde ardışık geçmesi) K6 ölçüm kitinde yazılır (kit henüz yok; aşağıdaki tablo).

**Kayıtlı sınırlar:** (1) Kümeler küçük bir kalibrasyon kümesidir: özetlerin doğrudan paraphrase'ı olan iddialar ve eklenmiş sayısal şartlar işi kolaylaştırır; zor en-yakın-eser ayrımı bu koşuyla kanıtlanmaz. (2) Beklenen etiketler özet metnine göre yazıldı; modele verilen metin kesilirse (özet üst sınırı 2.500 karakter; hepsi altında) etiket yeniden gözden geçirilmez, eser §6'nın metin-farkı kuralıyla dışlanır. (3) Gizli anahtar (beklenen etiketler) uygulama modeline ve okuyucuya verilmez. (4) Sağlayıcı özetleri 4 Ekim 2026'da OpenAlex'ten alındı; koşuda gelen metin farklıysa §6 dışlama kuralı.

**Hazırlık sağlayıcı istekleri:** K6 için 9 (5 arama, 3 arama, 1 toplu kimlik); L9 için 4 (aşağı); birlikte 13 / 60; deftere yazılı (`.local/p9-owed/prep/ledger.jsonl`). Yeniden deneme yok.

**Kit hash'leri ve dosya pinleri:** aşağıdaki tabloya bakın (ortak).

## Ek L1 (4 Ekim 2026): L9 gelişim çizgileri, keşiften önce dondurulacak girdiler

**Durum:** `gpt-6.1-sol` incelemesi (medium, sahibin 4 Ekim kuralı; §0.3'ün “high”inin yerine) ve push sonrası geçerli; Claude + Sol medium ortak kararı (4 Ekim 2026). Ek L2 (lineage isteğinden önce) ayrıdır ve henüz yok.

**Konu ve soru:** görüntü üretiminde difüzyon modelleri (tamamen yeni; dilim 2, H9, H9b, K5 ve K6 korpuslarının dışında). Soru (İngilizce): *“How did denoising diffusion generative models develop after the original denoising diffusion probabilistic model, in sampling speed, likelihood and sample quality?”* Üç geliştirme sütunu: dilim 2'nin metni, `docs/product/p6-slice2-chain-of-ideas.md:280-284`, kelimesi kelimesine. Seçim kuralları §7'deki gibi; elle ekleme/çıkarma/sıralama yok.

**`G` (`docs/product/p9-owed-l9-ek-l1.json`, SHA-256 aşağıda):** üç eser, iki yönlü çift. ddpm (Ho 2020, OpenAlex W3036167779), ddim (Song 2020, W3092442149), iddpm (Nichol 2021, W3122887982); çiftler ddpm→ddim ve ddpm→iddpm; ddim→iddpm bilerek yok. Her çift, sonraki eserin kendi özet cümlesiyle desteklenir (JSON'da alıntı). Kimlikler 4 Ekim 2026'da OpenAlex'ten doğrulandı (Crossref kullanılmadı: arXiv DOI'leri DataCite'tadır); 4 istek. Sol medium'un düzeltmesiyle skor tabanlı SDE eseri (W3110257065) ve ddpm→sde çifti `G`'den çıkarıldı: özeti belirli bir selefi adlandırmıyor, girişi okunmadı. Eşleme kuralı §7'deki gibi (normalize başlığın başı, ilk yazar soyadı belirtecinin yazarda geçmesi, izinli yıllar); `ddpm` için izinli yıllar 2020-2021, `ddim` 2020-2021, `iddpm` 2021; başlık başları birbirini kapsamaz (kontrol edildi).

**Kayıtlı sağlayıcı kusuru:** OpenAlex'in ddpm kaydındaki özet alanı alakasız bir depo metni (DiffuCpG) taşıyor; kayıt olduğu gibi tutulur, onarılmaz, ddpm için kanıt sayılmaz; ürün bu kaydı aynen alırsa sonuçta “sağlayıcı kusuru” olarak yazılır. Bir OpenAlex yinelenen kaydı (“Ho 2024”) yıl kuralıyla eşleşmez.

**Sınırlar:** Konu tanıtım içeriği modelce iyi bilinen bir çizgidir; bellekten yanıt riski ölçülmez (K0 bağımsızlığı korpus örtüşmesini ölçer, model bilgisini değil). K1 (≥6 PDF metinli satır) henüz doğrulanmadı; dört (burada üç) `G` eseri tek başına yetmez. Konu, `G` ve kurallar koşu başladıktan sonra değişmez; bir kapı tutmazsa §7'nin kuralı geçerlidir (ikinci konu yok).

## Ek S (4 Ekim 2026): dilim 4 / D157 için H9e raporunun kullanılması, koordinatör değişikliği önerisi

**Karar (Claude + `gpt-6.1-sol` medium, review-b turunda AGREE, kapılar için bir değişiklik istedi ve alındı):** dilim 4 H9e'nin kabul edilmiş raporunda (`rpt_Rmd2soa3YuCZBBSyQJCF`; ürün `7188ec8`) ölçülür; borç adlandırılmış borç olarak ertelenmez. Gerekçe: §5 “B tamamladıysa B” der; H9e B'nin kendi korpusunda (Q3, `e/data` = `b/data`'nın doğrulanmış kopyası) tamamlanan tek rapordur ve ürün kodu RF6 sonrasıdır. §5'in B'yi adlandırması H9b'nin üç B koşusunu varsaydı; H9e Ek G ile eklendi, bu yüzden açık bir koordinatör değişikliği gerekir: **bu ek, koordinatör push edip onaylamadan geçerli değildir** (sahip kuralı: koordinatör iznini bu ekle birlikte alır; “go” ayrıca verilir).

**Ek kapılar (§5'in üstüne):** (1) Ön koşul: H9e sonucu push edilmiş (`09aa2cf`) ✓, H9 zinciri kapalı ✓. (2) Ortam: `e/data` bayt kopyası (§1.10), H9e'nin son snapshot ve okurları bitmiş olarak; ürün worktree'si `7188ec8`'de ayrık. (3) Kit `measure_edit.py` henüz **yok**: Sol yazar, Claude inceler; deterministik testleri ve hash'leri bu ekin güncellemesinde, koşudan önce donar. (4) Ek E (belirleyici işlem listesi ve başlangıç hash'leri) rapor artık var olduğundan şimdi yazılabilir; koşudan (ilk düzenleme) önce donar ve Sol medium incelemesi alır. Kit ve Ek E tamamlanıp incelenmeden “go” istenmez. (5) En çok 10 yeni oturum / 60 dk, yalnız `cell_recheck`; R20 ve bölüm yeniden yazma ölçülmez. (6) Bu amendment'ın kendisi koşudan önce Sol incelemesinden (medium, sahibin 4 Ekim kuralı) “hazır” alır; Ek S, kit ve Ek E ayrı ayrı incelenir. (7) Koşu K6/L9 gibi koordinatörün “go”'sunu bekler; K6, L9 ve dilim 4 aynı anda koşmaz.

**Sınır:** hâlâ tek rapor, tek korpus; kod davranışının gerçek rapordaki sınaması, anlam desteği iddiası değil.

## Ortak hash'ler ve hazırlık durumu (4 Ekim 2026)

| Dosya | SHA-256 |
|---|---|
| `scripts/p9_owed/funnel_counts.py` | `ea3fc2ee9401a15134b3100904245cb9e95eb9de52f907338d0bb4cddb58de31` |
| `scripts/p9_owed/prep_lookup.py` | `20c1785c95159a1d92b5845f13de2ab83e732f2b12c35094a87c066a6944bab6` |
| `scripts/p9_owed/measure_k6.py` | `597f8f3da34f84c297cfc56f4eb0d4366c7e1a15c680fe49ec7f3a28ef819bdc` |
| `tests/test_p9_owed_measure_k6.py` | `8fed61ff3c3e16d0907a3ba27106252da7f535283238d9e8cc88fb6154834a1c` |
| `scripts/p6_eval/measure_lineage.py` | `a335b3835d571bb3643969510634ab7728e762d1e1c81e5f3b785b023dc40751` |
| `scripts/p6_eval/measure_fill.py` | `8db4e90616eff3712c0d5a1ba1581358982ebf048b2456332afd9ee21512e7ad` |
| `scripts/p6_eval/measure_report.py` | `80662aa18fb6e24ae507799754bf36fdc463c466d7201e857aa4537600fbcff9` |
| `backend/deixis/providers/query_compiler.py` | `d47afa94809553357700cf2acaa59241a3c2c7c3b5c001311330bfd71a725aea` |
| `backend/deixis/workflow/candidates/terms.py` | `1337ad58619f06fd04ea1272d60aa08674982e94259af1e5313e6d568e0c0527` |
| `methods/deixis-research/references/candidate-check.md` | `7e4222f3932a2905897a79d744addd4f4ce8a74efa880b51f2fd180d46401ffe` |
| `docs/product/p9-owed-k6-ek-k.json` | `4a5a3598f8fed9a36632a630105f687f67b9fe5b19f1ab60564fa452bb7e7420` |
| `docs/product/p9-owed-l9-ek-l1.json` | `1786d1ff3d2b76a4e5be31fb9bc52c182d7083ef9b78b336481a187391f19f1a` |

Runtime paket hash'i: `sha256:ccff02a169ea72690a594b3277c09c0975537f45ed20f9a6203a364d0c2b132c` (H9e'nin ölçtüğü paketle aynı önek `ccff02a1`).

**Kitler (henüz yok, koşudan önce yazılır, Sol yazar / Claude inceler, hash'leri bu ekin güncellemesinde donar):** K6 ölçüm kiti YAZILDI (yukarıdaki tablo; Sol medium yazdı, Claude inceledi, 40 çevrimdışı test), `measure_edit.py` (dilim 4), L9 için `measure_lineage.py`'ye envanter tabanlı `independence` yolu ve K0 envanterleri. Hazır olanlar: `funnel_counts.py` ve `prep_lookup.py` (Sol medium düzeltmelerinden sonra 99 test geçti).

**Hazırlık sağlayıcı istekleri:** toplam 13 / 60 (K6 9, L9 4; hepsi OpenAlex, anahtarsız, yeniden deneme yok); defter `.local/p9-owed/prep/ledger.jsonl`. Model oturumu 0; sunucu başlatılmadı; 8765'e dokunulmadı.
