# DEIXIS plan denetimi — Claude Fable 5.1 High

**Tarih:** 14 Eylül 2026. **İncelenen sürüm:** uygulama planı taslak 1. **Model sonucu:** `ready_with_changes`. **Durum:** tek kapsamlı inceleme tamamlandı; bulgular değerlendirildi ve [ana plan](implementation-plan.md) taslak 2 olarak düzeltildi. Taslak 2 Fable tarafından yeniden incelenmedi.

Fable P0 bulgusu bildirmedi; dört P1, beş P2 ve beş P3 maddesi sundu. Bunlar plan kusurları, uygulama kontrolleri ve isteğe bağlı açıklık önerilerinin karışımıdır. Aşağıdaki disposition, ham raporu otomatik kabul etmek yerine her bulgunun nasıl ele alındığını kaydeder.

## Yürütme ve provenance

- İstenen ve CLI'ye açıkça verilen model: `claude-fable-5-1`; effort: `high`.
- Claude Code sürümü: `2.1.270`. Araçlar kapalı, safe mode açık, ek MCP yok, oturum kalıcılığı kapalı. İnceleme sırasında repo okuma/yazma veya dış arama aracı verilmedi; sekiz belgenin numaralı sabit metni girdiye eklendi.
- CLI başarıyla tamamlandı (`returncode=0`, `subtype=success`, `is_error=false`). Sonuç metadatasında `claude-fable-5-1` kullanım kaydı mevcut; otomatik fallback seçeneği verilmedi.
- Aynı CLI metadatası ayrıca `claude-haiku-4-5-20251001` için kullanım kaydı bildiriyor. Bu kaydın işlevi eldeki metadatadan belirlenemiyor; ayrı bir ikinci denetim olarak sayılmıyor.
- Tam girdi, orijinal plan kopyası, ham JSON/Markdown, CLI argümanları ve kullanım bilgileri gitignored `.local/plan-review-2026-09-14/` içinde saklandı. Bu paket yerel kanıttır; başka bir klonda kendiliğinden bulunmaz. Aşağıdaki ham rapor korunmuştur.
- Bu bir metin/plan incelemesidir. Uygulama, skill davranışı, vendor erişimi veya araştırma etkinliği testi değildir. Model görüşü kullanıcı yetkisi veya bilimsel doğrulama oluşturmaz.

**Süre:** 328.817 saniye.

**Girdi paketi SHA-256:** `e89580d1fe8349837dcf8827b33b6fde1d54a90d9e5d8606addebfad0085d793`

**İncelenen plan SHA-256:** `44dca93d5fe2204479003a1886b0b8de1e276df953efe2773310fd7b058e157d`

**Düzeltilmiş taslak 2 SHA-256:** `e0b976a02e61c319f2a4f95afdda9c373e481afd739ae7334fc2241a8bf21f45`

### İncelenen dosyalar

| Girdi dosyası | SHA-256 |
|---|---|
| `docs/product/implementation-plan.md` | `44dca93d5fe2204479003a1886b0b8de1e276df953efe2773310fd7b058e157d` |
| `docs/product/first-slice-plan.md` | `a8cd8603bfeecabd52ba4e23eb21c1acd91951ba870a5301b51892af87a875ea` |
| `docs/product/README.md` | `8348f38794f156cb04f1d0c0c429149349e4b25672f7db352b56cc94c0e79133` |
| `docs/product/api-and-data.md` | `08212a5bda12467a0f4e1b9e503070010f7c54f4a48d4e0b245a10f8131eda8f` |
| `docs/desktop/README.md` | `e737cab1260a6beaa686f97a648a0a3d71a594d61b23923d8de4e4376902906a` |
| `docs/methods/research-methods.md` | `cb0bce84bb7f1c7636dda8cd798d9ecdb511a1848903badc6a25cf1e1996b35a` |
| `prototypes/shadcn-ui/README.md` | `be3d82efd66db8a760511593c9702989daabc1b9c3324e271e482e1cbe4daee2` |
| `../quaestio/SKILL.md` | `16b1606e4fa3c16cb93b332372a833eb531633da8215ba7ba8fce4642d6ebb1a` |

Ham rapordaki satır numaraları bu taslak 1 girdilerine aittir. Ana planın yeni satırlarına doğrudan uygulanmamalıdır. İnceleme sonrasında ana plan ve ilk-dilim belgesinin yönlendirme notu değiştirildi; eski girdi yerel pakette korunuyor.

## Bulgu disposition'u

| Bulgu | İşlem | Uygulanan düzeltme ve sınırı |
|---|---|---|
| F01 / P1 | Kabul | §4.4 ve P1/P2 çıkışları ayrıldı: P1 sahte modelle deterministik sözleşme kontrolü; P2 gerçek modelle aynı skill paketinin davranış testi. P3'ün başsız/API testi ile P4 tarayıcı testi ayrıldı. |
| F02 / P1 | Kabul; kapsamı netleştirildi | §7.2 parasal tavanı kullanıcının seçtiği koşullu sınır olarak tanımlar. Abonelikte sonlu çağrı/yeni işlem başlatma süresi uygulanır; bilinmeyen kota veya token için garanti verilmez. Kullanıcı sert parasal tavan seçerse uygulanamayan işlem başlamaz. |
| F03 / P1 | Kabul | Codex sınır denemesi P2'nin ilk işi. Başarısızlık P4'ün canlı yanıt koşulunu durdurur; modelden bağımsız işler sürer. Kullanıcının seçimiyle Claude veya yenilenmiş anahtarlı DeepSeek adaptörü öne alınabilir; sessiz değişim yok. |
| F04 / P1 | Kabul | `StepInput` tam geri okunabilir girdi snapshot'ı ve o adıma verilen kaynak/pasaj izin listesi taşır. `ModelSession` research/run/step'e bağlıdır; ilk dilimde adım başına yeni oturum kullanılır. Sadece hash veya ortak kütüphanede var olan ID yetmez. |
| F05 / P2 | Kabul | `SearchPlan`, `ScreeningProposal`, `GroundedAnswerDraft`, `ClarificationRequest` adlandırıldı; backend tarafından beklenen ortak zarf alanları yazıldı. Modelin geri gönderdiği kimlik yetki oluşturmaz. |
| F06 / P2 | Kabul | P1'in asıl şemaları dil bağımsız JSON Schema'dır. Pydantic/TypeScript/OpenAPI uyumu P2'de üretim veya sözleşme testleriyle sağlanır. |
| F07 / P2 | Kabul; hata sınıfları genişletildi | `before_send`, `rejected_not_executed`, `after_send_unknown` ayrıldı. Yalnız güvenli geçici hatalar retry alır; kesin 429 gibi yanıtlar provider sözleşmesine göre ele alınır. Gönderim sonrası belirsiz ücretli işlem otomatik tekrarlanmaz. |
| F08 / P2 | Kısmen kabul; önerilen anahtar eşlemesi düzeltilerek | Kimlik kuralı eklendi, ancak DOI/OpenAlex ID doğrudan aile/sürüm birincil anahtarı yapılmadı. DEIXIS kendi ID'lerini üretir; DOI tek başına fiziksel sürüm veya preprint–yayın ilişkisi kanıtı değildir. Açık ilişkiler ve insan kararı kaydedilir; şüpheli benzerlik yalnız olası tekrar işaretidir. |
| F09 / P2 | Kabul | T18, çağrı sırasında kapsam değişmesini ve eski kapsamlı sonucun yeni sonuç diye uygulanmamasını sınar. Sonraki adımın yeni girdi/oturum alması açık. |
| F10 / P3 | Kabul | Özetin provider/yayıncı/kullanıcı kökeni, payload referansı, alınma tarihi ve yeniden kurma sürümü eklenir. OpenAlex'in belirli alan biçimi bu raporla doğrulanmış sayılmaz; P3 adapter kontrolüdür. |
| F11 / P3 | Kısmen kabul; kilit önerisi güçlendirildi | Tek worker için OS advisory lock, instance UUID ve süreç başlangıcı kullanılır. PID veya eski heartbeat nedeniyle canlı kilit silinmez; yeniden alınmış OS kilidi sonrasında eski yarım adımlar kurtarılır. |
| F12 / P3 | Kabul | İlk açılışta sistem teması, sonra kalıcı kullanıcı tercihi açık yazıldı. Prototipin koyu başlangıcı ürün kararı sayılmadı. |
| F13 / P3 | Kısmen kabul; farklı aşama tercihi | PDF yükleme aşaması netleştirildi. Önerilen devre dışı kontrol yerine P3 import API + P4 minimal isteğe bağlı yükleme planlandı; gelişmiş kütüphane P5. T19, ekler-only kapsamını ve PDF olmadan başlamayı sınar. Bu teknik plan tercihidir. |
| F14 / P3 | Açıklama kaydı | İlk dilimin kaynaklı yanıt sınırı ana planda yazılı; OR örneği zorunlu alan değildir. Eski gate metni yeni onay turu veya tamamlanmış test sayılmaz. İlk-dilim belgesine güncel plan/test aşaması notu eklendi. |

## Ham rapora ilişkin ek düzeltmeler

- Fable'ın “denetim ve disposition onayın kendisidir” ifadesi yetki kaynağı olarak kabul edilmedi. Kullanıcının mevcut talebi plan ve denetimi yetkilendiriyor; bu tur uygulama kurulumunu yapmıyor. P1'in teknik olarak başlanabilir olması, modelin kullanıcı adına izin verdiği anlamına gelmez.
- “P4 ve sonrası başlayamaz” ifadesi yalnız canlı model gerektiren kabul koşulları bakımından kullanıldı. UI, veri katmanı ve modelsiz testlerin geliştirilmesini gereksiz yere engelleyen bir kural yapılmadı.
- macOS/Windows için Tauri'nin sonraki aşama olması daha önce seçilmiş yöndür. Açık kalan, paketleme yöntemi, bağımlılıkların dağıtımı ve platform testleridir; platform kararı yeniden açılmadı.
- P1 test ayrımı ve P3/P4 test bağımlılığı, ana ajanın denetim sürerken tuttuğu kendi notlarında da vardı. Bunlar bağımsız iki doğrulama sonucu sayılmıyor; Fable'ın aynı hususlara ilişkin bulguları tek disposition altında işlendi.
- pypdf/PDF.js resmî belge bağlantıları düzeltme sırasında eklendi. Kaynak paneli ve çıkarım sınırını açıklıyorlar; uygulama entegrasyonu gösterilmiş değildir.

## Sonuç ve sonraki iş

Plan hazırlayan ajanın değerlendirmesi: P0 plan/denetim teslimi tamamlandı; Fable'ın somut plan açıkları taslak 2'de ele alındı. **Sonraki iş P1: minimal skill, kanonik JSON şemaları ve sentetik sözleşme testleri.** Codex araç sınırları ve gerçek model davranışı P2'de ayrıca doğrulanmadan canlı araştırma dilimi hazır sayılmayacak.

Taslak 2 için yeniden Fable “ready” kararı alındığı iddia edilmiyor. Tek denetimin ardından gerekçeli düzeltme yapıldı; uygulama ve bilimsel performans kanıtı henüz yok.

## Değiştirilmemiş model raporu

Aşağıdaki metin inceleme çıktısının aynısıdır. Bazı önerileri yukarıda kısmen kabul edilmiş veya düzeltilmiştir; uygulanacak kararlar disposition ve ana plandadır.

---

Planın kendisini, dayanak belgeleri ve Quaestio SKILL.md'yi satır satır karşılaştırarak denetledim. Aşağıdaki sonuç yalnız verilen metne dayanır.

## Karar

**Sonuç: `ready_with_changes`.**

P1 başlayabilir. P1 kapsamındaki iş, yani minimal skill paketi, provenance kaydı, sürümlü çıktı sözleşmesi ve sentetik fixture'lar, aşağıdaki F01, F02, F05 ve F06 düzeltmeleri plan dispozisyonuna yazıldıktan sonra güvenle yazılabilir. Bu düzeltmeler kod yazımını değil, P1'in çıkış koşulunun ne olduğunu netleştirir.

P2'nin backend, migration, başlatıcı ve olay akışı kısımları da başlayabilir. P3'ün OpenAlex adaptörü, tekilleştirme, indirme ve metin çıkarımı işleri modele bağlı değildir ve Codex sonucundan bağımsız yürüyebilir.

Şu aşamalar kanıtlanmamış entegrasyon yeteneğine bağlı olduğu için bloke sayılmalıdır: P4 ve sonrası, Codex App Server üzerinden araç sınırlaması ve yapılandırılmış çıktı P2 denemesinde gösterilene kadar başlayamaz. Plan bunu 0177 ve 0311'de kabul ediyor, ancak deneme başarısız olursa ne olacağını söylemiyor; F03 bunu ele alıyor. P5 ve üstü P4'e bağlıdır. P10 ayrıca Tauri sidecar ve backend paketleme deneyine bağlıdır ve şu an tasarım kararı bile değildir; bu doğru bir erteleme.

Planın doğru yaptığı ve yeniden açmadığım noktalar: tek ana ajan kararı korunmuş, yedi sağlayıcı kapsamda ve aşamalı, soru-öncelikli akış, insan düzenlemesinin korunması, provenance'ın kimliklerle tasarlanması, idempotency anahtarı ve olay tekilleştirme, sır saklama ve URL fetch sınırları, Quaestio'nun çalışma zamanı bağımlılığı olmaması, skill ile kod sahipliğinin ayrımı. Bunlar yeterince kapsanmış; bulgu üretmedim.

## Bulgular

Her bulguda önem, kanıt satırı, tetikleyici, etki, en küçük düzeltme ve güven düzeyi verilmiştir. "Plan kusuru", planın şu haliyle uygulamayı belirsiz veya çelişkili bıraktığı yerdir. "Uygulama kontrolü", planın zaten söz verdiği ve yalnız kayıt altına alınması gereken iştir. "İsteğe bağlı" düşük maliyetli iyileştirmedir.

**F01, P1, plan kusuru: P1 çıkış koşulu model adaptörü olmadan sınanamayan davranışlar içeriyor.**
Kanıt: §4.4 satır 0138 "sentetik kaynaklarla ... senaryoları çalıştırılır"; §9 P1 satırı 0264 "özet-only, bozuk atıf, kapsam, sürüm ve insan düzeltmesi davranışları sınanabilir"; matris T02/T04/T08 satır 0284, 0286, 0290 aşama alanı "P1–...". Tetikleyici: P1'de henüz hiçbir model bağlantısı yoktur; Codex adaptörü P2'dedir. "Özet-only kaynakta sayfa uydurulmaz" gibi bir senaryo skill'in davranışıdır ve modelsiz çalıştırılamaz. Etki: P1'in kapandığı iddiası ya doğrulanmamış kalır ya da P1 gizlice P2'nin adaptörünü bekler. Düzeltme: P1 çıkışını ikiye ayırın. Birincisi, geçmesi zorunlu deterministik kontroller: şema doğrulaması, atıf kimliklerinin verilen pasaj kümesine ait olması, sürüm bağlantısı, insan sürümünün ezilmemesi; bunlar fixture ve doğrulayıcı kodla modelsiz çalışır. İkincisi, P1'de yalnız yazılan ve P2 adaptörü hazır olunca koşulan skill davranış senaryoları. T02, T04 ve T08'in aşama alanını buna göre "P1 yazım, P2+ yürütme" olarak düzeltin. Güven: yüksek, metin içi çelişki.

**F02, P1, plan kusuru: sert bütçe sınırı kuralı iki yerde farklı yazılmış ve abonelik bağlantısında ilk dilimi kilitleyebilir.**
Kanıt: §7.2 satır 0242 "sınırlanamıyorsa bu garanti verilmez; ilgili işlem başlatılmadan sınırın uygulanamadığı açıklanır" ile §11 satır 0316 "sert sınır uygulanamıyorsa ilgili işlem başlamaz". Tetikleyici: birinci model Codex abonelik bağlantısıdır; çağrı başına para fiyatı yoktur, yalnız kota ve token ölçülür. 0316 harfiyen uygulanırsa Codex ile hiçbir işlem başlayamaz; 0242 ise açıklayıp devam etmeyi ima eder. Etki: P4'ün öncelikli model yolu belirsiz bir kurala bağlanır; uygulayıcı kendi kararını verir. Düzeltme: sınır türlerini ayırın. Parasal sert sınır yalnız fiyatı bilinen API'lerde uygulanır; kullanıcı böyle bir sınır koymuşsa ve bağlantı bunu destekleyemiyorsa işlem başlamaz ve nedeni görünür. Abonelik bağlantılarında çağrı sayısı, süre, ölçülen token ve sağlayıcı kotası sınırı her zaman uygulanır. 0240'taki "her çalışmanın sonlu çağrı/süre/token sınırı vardır" cümlesi zaten bunu söylüyor; 0316'yı buna bağlayın. Güven: yüksek.

**F03, P1, plan kusuru: Codex sınır denemesi başarısız olursa P4 için model yolu tanımsız.**
Kanıt: §5.2 satır 0177 "sınır uygulanamıyorsa adaptör hazır sayılmaz"; satır 0177 sonu "alternatif bağlantıya geçiş kullanıcı model seçimini değiştirmeden yapılamaz"; §11 satır 0311 "P2 canlı adaptör geçmez"; §2 satır 0030 öncelik Codex, Claude, DeepSeek. Tetikleyici: App Server oturumunun global skill, MCP, shell ve ağ araçlarını kapsam dışına taşmayacak biçimde kısıtlanıp kısıtlanamayacağı doğrulanmamıştır. Etki: deneme başarısız olursa plan durur; Claude ve DeepSeek adaptörleri P7'de olduğundan P4'ün hiç modeli kalmaz. Düzeltme: §11 tablosuna tek satır ekleyin: "Codex sınır denemesi başarısız olursa P4 durur; kullanıcı Claude programatik adaptörü veya yenilenmiş anahtarla DeepSeek adaptörünü ilk P4 modeli olarak öne almayı seçer; P3 bu karardan bağımsız sürer." Bu, kullanıcı adına karar vermez; karar noktasını ve bekleyen işi belirler. Güven: plan boşluğu için yüksek; Codex yeteneği için doğrulanmamış, aşağıdaki sınırlar bölümüne bakın.

**F04, P1, plan kusuru: model bağlamının araştırma bazında nasıl kurulduğu ve yeniden üretildiği karara bağlanmamış.**
Kanıt: §3.4 satır 0097 "önceki model oturumu tek veri kaynağı değildir"; §3.4 satır 0091 "girdi özeti/hash'i"; §4.3 satır 0131 "yalnız verilen pasaj kimlikleri"; §5.2 satır 0177 "oturumun yalnız kendi görev verisine eriştiği"; T08 satır 0290; devir belgesi satır 0227 otomatik bağlam devri. Tetikleyici: App Server thread'i kalıcıdır. Bir thread araştırma A ve B arasında yeniden kullanılırsa B'nin pasajı A'nın bağlamına girer; T08 ancak testte fark edilir, tasarımda engellenmez. Ayrıca "verilen pasaj kimlikleri" denetimi, o adımda verilen kümenin kalıcı kaydını gerektirir; 0091'deki hash bunu geri okunabilir kılmaz. Etki: kapsam sızıntısı, idempotent yeniden çalıştırma ve provenance aynı anda zayıflar. Düzeltme: iki kural ekleyin. Birincisi, her RunStep'in model girdisi veritabanından kurulur; thread veya oturum kimliği run kimliğine bağlıdır ve araştırmalar arası asla paylaşılmaz; run içinde thread sürdürme isteğe bağlıdır fakat girdi yine yeniden kurulabilir olmalıdır. İkincisi, adım başına "verilen pasaj/kaynak kimlikleri listesi" ayrı bir kayıt olarak saklanır ve atıf denetimi bu kayda karşı yapılır. Bu aynı zamanda devir belgesindeki bağlam devrini adım başına sınırlı girdiyle çözer; ayrı bir özetleme mekanizması ilk dilimde gerekmez. Güven: yüksek.

**F05, P2, plan kusuru: ilk dilimin adım bazlı çıktı şemaları sayılmamış.**
Kanıt: §4.3 satır 0129–0133 genel girdi/çıktı; §3.3 satır 0077 "arama modülüne gerekli girdiler yapılandırılmış model çıktısından gelir"; §12 satır 0331 "sürümlü çıktı sözleşmesi". Tetikleyici: P1'in teslimatı sözleşmedir; ama hangi adımın hangi şemayı döndürdüğü yazılmamıştır. Etki: P1 uygulayıcısı şemaları icat eder, P2 adaptörü başka bir şekil bekler. Düzeltme: P1 için en az şu dört şemayı adlandırın: arama planı, eleme önerisi, kaynaklı yanıt taslağı, hedefli açıklama sorusu. Her biri `scope_revision`, skill paket hash'i ve şema sürümünü taşır. Alan ayrıntısı kodda kalır; adlar ve zorunlu kimlik alanları planda olur. Güven: yüksek.

**F06, P2, plan kusuru: P1 şemaları, backend dili P2'de kilitlenmeden yazılacak.**
Kanıt: §5 satır 0147 Python+Pydantic önerisi; satır 0159 "P2'de başarısız olan ... yeniden karar gerekçesidir"; §5.1 satır 0167 "P2'de ... seçilip kilitlenir"; P1 satırı 0264 "domain/JSON şemaları". Tetikleyici: P1 şemaları Pydantic olarak yazılırsa P2'deki yeniden karar bunları çöpe atar. Etki: küçük ama gereksiz yeniden iş; sözleşme sahipliği bulanır. Düzeltme: P1'in kanonik ürünü dil bağımsız JSON Schema dosyalarıdır; Pydantic ve TypeScript tipleri P2'de bunlardan üretilir veya bunlara karşı test edilir. 0167'deki "UI tipleri OpenAPI'den üretilir" cümlesiyle çelişmez; JSON Schema girdisidir. Güven: orta yüksek.

**F07, P2, plan kusuru: yeniden deneme güvenli hata sınıfı tanımlanmamış.**
Kanıt: §3.4 satır 0094 "yanıt alınmadan kopan ücretli çağrı otomatik tekrarlanmaz"; §7.2 satır 0244 "en fazla iki geçici ağ retry'ı" ve "yanıtı belirsiz ücretli çağrı retry kapsamına alınmaz"; T05/T06. Tetikleyici: bağlantı kurulamadan alınan hata ile istek gönderildikten sonra gelen timeout aynı "ağ hatası" görünür. Etki: uygulayıcı her ikisini de retry'a alırsa ücretli çift çağrı; hiçbirini almazsa gereksiz duraklama. Düzeltme: adaptör hatalarını `before_send` ve `after_send_unknown` olarak sınıflandırın; yalnız birincisi retry bütçesine girer; sınıf RunStep kaydına yazılır. Güven: yüksek.

**F08, P2, plan kusuru: yayın kimliği ve sürüm eşleme önceliği P1 şemasında belirlenmemiş.**
Kanıt: §3.3 satır 0078 "aynı yayın ailesi farklı sürümlerle bağlanır"; §6.1 satır 0196; §6.2 satır 0215 "şüpheli eşleşme otomatik birleştirilmez"; T03. Tetikleyici: P3'te yalnız OpenAlex vardır; Crossref'in preprint ilişkisi P5'e kadar yoktur. Hangi anahtarın aile, hangisinin sürüm olduğu yazılmadan Work/SourceVersion tablosu P1'de tasarlanamaz. Düzeltme: kimlik önceliğini yazın: OpenAlex work kimliği ve DOI aile için, DOI/arXiv kimliği ve sürüm etiketi sürüm için; sağlayıcı ilişkisi yoksa başlık benzerliği yalnız `suspected_duplicate` üretir, birleştirmez. Güven: yüksek.

**F09, P2, eksik test: çalışma sırasında yönlendirme ve bayat `scope_revision` sonucu için senaryo yok.**
Kanıt: §3.4 satır 0095 "eski sürümle başlayan sonuç saklanır fakat ... otomatik uygulanmaz"; matris satır 0281–0299'da karşılığı yok; devir belgesi satır 0253 bunu onaylanmış davranış sayıyor. Etki: onaylanmış bir davranışın hiç testi olmaz; T13 sürüm provenance'ına bakar, yönlendirmeye bakmaz. Düzeltme: T18 ekleyin: "Çağrı sürerken kapsam değişir; eski çağrının sonucu kaydedilir, yeni kapsamın geçerli sonucu sayılmaz, UI'da eski sürüm etiketiyle görünür." Aşama P2–P4. Güven: yüksek.

**F10, P3, uygulama kontrolü: özet metninin kaynağı Passage'da işaretlenmeli.**
Kanıt: §6.1 satır 0199 "abstract/section konumu"; §6.2 satır 0211. Tetikleyici: OpenAlex özeti sağlayıcının indekslenmiş biçiminden yeniden kurulur; yayıncı metniyle birebir olmayabilir. Düzeltme: Passage kaydına özet kaynağı ve yeniden kurulma bilgisi ekleyin. Küçük alan, P3'te. Güven: orta; OpenAlex'in güncel özet biçimi bu denetimde doğrulanmadı.

**F11, P3, uygulama kontrolü: tek sahipli kilidin çökme sonrası geri alınması yazılmamış.**
Kanıt: §3.4 satır 0092 "tek sahipli çalışma kilidi"; §5.1 satır 0169 port çakışması. Düzeltme: kilit sahibi süreç kimliği ve başlangıç zamanıyla kaydedilir; backend açılışta kendi eski kilitlerini geri alır; ikinci örnek port ve kilit dosyasıyla reddedilir. P2'de. Güven: yüksek.

**F12, P3, plan kusuru, küçük: tema uzlaşması kararı yazılmamış.**
Kanıt: §8 satır 0255 "uzlaştırılır"; devir belgesi satır 0236 sistem teması onaylı; plan satır 0009 kullanıcı kararı üstündür. Düzeltme: "sistem teması izlenir, tercih korunur" olarak yazın; prototipin koyu başlangıcı teknik varsayılandı. Güven: yüksek.

**F13, P3, isteğe bağlı: kullanıcı PDF yüklemesinin aşaması belirsiz.**
Kanıt: §1 satır 0020 "PDF eklemek isteğe bağlıdır"; §8 satır 0250 P4 "pasaj/PDF açma"; devir belgesi satır 0244–0246 ekleme akışı ve kapsam etiketi. P4'te yalnız indirilen PDF'ler var; yükleme P5 kütüphanesine gidiyor gibi okunuyor ama yazılmamış. Düzeltme: tek cümle: "kullanıcı PDF yüklemesi P5'tedir; P4'te ek dosya kontrolü görünür fakat devre dışı ve etiketli." Güven: yüksek.

**F14, P3, dispozisyon: ilk dilim belgesinin skill yazım kapısı planda karşılanmış ama işaretlenmemiş.**
Kanıt: first-slice-plan satır 0045 "Gate to writing the method instruction"; plan satır 0009 "eski taslak cümlesi yeni onay şartı oluşturmaz"; §3.2 satır 0072 ve T04. Kapı, ilk çıktının mevcut formülasyon haritası olması ve yeni model uydurulmamasıdır; plan bunu alan bağımsız skill ve T04 ile zaten karşılıyor. Düzeltme: P0 dispozisyonunda "kapı tasarımla karşılandı" notu. Güven: yüksek.

Ek adaylar değerlendirildi ve bulgu yapılmadı: OCR'ın P5'e bırakılması devir belgesi 0247 ile çelişmez, çünkü 0154 inceleme limitini görünür kılıyor. Tek etkin çalışma sınırı, 0090'da kapasite tercihi olarak açıkça yazılmış. Codex thread iptali "destekliyorsa" koşuluyla yazılmış, doğru.

## Çelişen kaynak gereksinimleri, ilk üç teslimat ve inceleme sınırları

**Çelişkiler.** Kaynak belgeler arasında maddi çelişki azdır; çoğu plan içi tutarsızlıktır.

- Sert bütçe kuralı, F02. Çözüm plan içindedir; kullanıcı kararı gerekmez, çünkü 0240 zaten sonlu çağrı/token sınırını temel alıyor.
- Tema, F12. Devir belgesi kararı üstündür; kullanıcı onayı gerekmez.
- İlk dilim belgesinin "davranış sözleşmesini onayla" adımı ile planın "aşamalar yeni onay töreni değildir" ilkesi. Kullanıcının istediği sıra plan, denetim, uygulamadır; bu denetim ve bulgu dispozisyonu o onayın kendisidir. Ek tören gerekmez; dispozisyon kaydı yeterlidir.
- Codex öncelik kararı ile Codex sınırının doğrulanmamışlığı, F03. Bu çelişki değil, koşullu bağımlılıktır; çözümü kullanıcıya bırakan karar noktası eklenmelidir. Kullanıcının hangi alternatifi seçeceği bu denetimde varsayılmadı.

**İlk üç teslimat.**

- P1: doğru büyüklükte. Skill yalnız kaynaklı yanıt görevini destekliyor, sentez ve kill-search sonraya bırakılmış, provenance sabit revizyona bağlı. F01, F05 ve F06 uygulanınca P1 kendi başına kapanabilir. Skill metninin desteklenmeyen görevleri mevcut özellik gibi sunmaması 0123'te yazılı ve doğru.
- P2: en riskli parça Codex adaptörüdür ve backend iskeletine ihtiyacı yoktur. Sıralama düzeltmesi: Codex sınır ve yapılandırılmış çıktı denemesini P2'nin ilk işi yapın, hatta P1 ile paralel bir izole deneme olarak yürütün. Sonuç P4'ün modelini belirler ve F03'teki karar noktasını erken tetikler. Backend, migration, olay akışı ve başlatıcı bu denemeden bağımsız ilerler.
- P3: model gerektirmeyen kısımları, yani OpenAlex adaptörü, kimlik eşleme, indirme, sayfa çıkarımı ve FTS5, P2 denemesini beklemeden başlayabilir. F08 kimlik önceliği bu işin ön koşuludur. "Sentetik A–G uygulama testleri geçer" çıkış koşulu, F01'e göre model adaptörü hazır olmadan yalnız deterministik kısımlar için geçerlidir; koşulu buna göre bölün.

Genel sıralama önerisi: P1 sözleşme ve skill, eş zamanlı Codex sınır denemesi, ardından P2 backend ve P3 arama katmanı, sonra P4. Bu, planın aşamalarını değiştirmez; yalnız en belirsiz bağımlılığı öne alır.

**İnceleme sınırları.** Hiçbir uygulama testi çalıştırılmadı; bu bir metin denetimidir. Şu dış iddialar doğrulanmadı ve doğru diye kabul edilmedi: Codex App Server'ın yapılandırılmış turn çıktısı, dinamik araç akışının deneysel olduğu, turn iptal desteği ve oturum başına araç kısıtlama olanağı; OpenAlex'in anahtarsız/anahtarlı erişim modları ve özet biçimi; SQLite FTS5'in seçilecek Python dağıtımında bulunması; FastAPI arka plan görevleri, SQLite WAL ve backup API notları; Tauri sidecar gereksinimleri; 0017'deki Claude Code ve Codex CLI sürüm numaraları; 0105'teki Quaestio revizyon hash'i. Yöntem belgesindeki literatür referansları bu denetimde yeniden değerlendirilmedi. Quaestio SKILL.md'nin içeriği yalnız uyarlama kaynağı olarak okundu; etkinliği hakkında görüş verilmedi.

Bu karar bir plan incelemesidir. Skill'in modeli gerçekten hizalayacağı, kaynaklı yanıtların bilimsel olarak doğru olacağı veya seçilen mimarinin günlük kullanımda yeterli olacağı bu denetimle gösterilmiş olmaz; bunlar planın kendi ifadesiyle P4 sonrası ölçümün konusudur.
