# DEIXIS durumu

**Son güncelleme:** 25 Ekim 2026. Kararlar [docs/decisions.csv](docs/decisions.csv) içinde (en yenisi üstte), ölçümler [docs/benchmark.md](docs/benchmark.md) içinde. Bu dosyanın 18 Ekim öncesi uzun hali Git geçmişinde (commit 847b6b0b).

## Kısaca: neredeyiz?

- **25 Ekim, repo sadeleşmesi (davranış değişmedi):** klasörler `deixis/`, `web/`, `tests/`, `docs/`; `deixis/workflow/` adım klasörlerine ayrıldı (`run/`, `search/`, `screen/`, `read/`, `answer/`, `features/`; D124); tek `deixis/storage/schema.sql` + sürümlü yükseltme adımları (D119); karar kaydı `docs/decisions.csv`; arama `docs/search.md`'de iki şemayla; testler 17.041 → ~1.500 durum, Playwright 54 → 5 spec, tek komut ~2 dk (D120); `.local/` → `notes/`. Her aşamayı Sol High inceledi.

Durum kötü değil, ama dengesiz. Uygulama çalışıyor ve özellik bakımından geniş; asıl eksik, son haftalarda eklenen özelliklerin çoğunun gerçek bir modelle ve gerçek kullanımda denenmemiş olması.

- **Sağlam olan:** atıf kuralı. Cevaptaki her atıf, okunan bir pasajda kodun bulduğu bir yere bağlanıyor; bulunamazsa cevap "doğrulanmamış taslak" kalıyor. 8 kayıtlı cevaptaki 171 atıf bağlantısının hepsi doğru çıktı.
- **Ölçülen ve iyi olan:** arama sırası. 18 Ekim'de iki hazır test setinde, sahibin ayarlarıyla (Voyage embedding + Voyage reranker) DEIXIS ilk 50 sonuçta düz bir OpenAlex aramasından belirgin olarak fazla doğru makale buluyor: BioASQ'da 0,618'e karşı 0,489, LitSearch'te 0,700'e karşı 0,561. Reranker her iki sette de güven aralığı sıfırın üstünde katkı veriyor; bu yüzden artık varsayılan olarak açık (D104).
- **Ölçülen ve zayıf olan:** elektrik mühendisliği survey seti (42 survey, gold = survey'in kaynakçası). Burada DEIXIS düz OpenAlex'i geçiyor (0,129'a karşı 0,065) ama fark küçük ve **reranker zarar veriyor** (0,091). Sebep: bu sette doğru makalelerin çoğu atıf zincirinden geliyor, reranker yalnız başlık ve özet okuduğu için zincir kayıtlarını aşağı itiyor. Varsayılanı açık yapan karar (D104) bu sonuçtan önce alındı. D106 ile reranker yalnız zincirden gelen kayıtları artık yerinde bırakıyor: kayıtlı koşular üstünde tekrar oynatınca survey setinde 0,091 → 0,111, LitSearch değişmedi; kaybın yarısı duruyor, BioASQ ölçülmedi, yeni koşu yapılmadı.
- **Bir kez canlı denenen:** Verify Citations (taslak atıf denetimi). V5 pilotu (bir taslak, 30 çift, Sonnet 5.5; insan etiketi yok, okuyucular Sol ve Opus): D105 sonrası tekrarda kontrol tamamlanamayan %48'den %14'e indi, örneklemde yanlış "bulundu" 0, üç eşik geçti. Tek koşu; sonucun bir kısmı modelin koşudan koşuya oynamasından olabilir.
- **Canlı denenen (2):** ters atıf arama. R4b pilotunda destek sayılan 24 sonuçta 0 hata (D109). 24 Ekim'de sorguya alan ve yazar bilgisi eklendi (D116): bilinen 13 destekleyiciden bulunan 8 → 12 (aynı gün tekrar 9), yanlış "bütünüyle bulundu" 0, koşu ~32 USD. Kural hâlâ ihtiyatlı: destekleyicilerin çoğu "destek yeterince gösterilmedi" grubunda kalıyor.
- **24 Ekim'de canlı denenen:** run kartı geçti (sayılar, nedenler ve alıntılar kayıtlarla birebir tuttu). Kill search ve kartopu çalışıyor ama aranan makaleleri çoğu zaman kaçırıyor: ikisi de çok sonuç bulup yalnız ilk birkaçına bakıyor (aşağıda "Sonra bakılacak"). Sonuçlar `notes/2026-10-24-live-pilots/RESULT.md` ve `elicit3/RESULT-2.md`. Okuma ve cevap kalitesi ayrıca ölçülmedi.
- **Bilinen zayıflık:** cevaplar, kendilerine verilen eserlerin azını atıflıyor (D83 sonrası DBR/VBF sorusunda 13 eserden 12–13'ü, ama her koşu 30 iddia sınırına takılıyor). Raporlar model puanıyla 30 üzerinden 15–20 aldı (insan puanı yok). Paywall arkasındaki tam metinler okunamıyor; mühendislik makalelerinin çoğu özetten okunuyor.
- **Denklemler (D113, D118):** Marker kaldırıldı; numaralı denklemleri varsayılan cevap modeli sayfa kırpıntısından okuyor (yalnız Anthropic, OpenAI, Gemini API). 24 Ekim'de bulucu iyileşti (D118): 34 arXiv makalesindeki 452 denklemlik ölçümde tam doğru kırpıntı 185 → 274, başka satır taşıyan kırpıntı 25 → 7; D113'ün 24 denkleminde tam doğru 8 → 15. Canlı deneme (3 makale, Sonnet 5.5, 0,13 USD): kaynakla karşılaştırılabilen 19 yerleştirmenin 19'u tam doğru. Tablo başlıklı sayfalar hâlâ atlanıyor. Bu istekler artık günlük harcamaya ve Settings → Usage'a sayılıyor (D115).
- **Özetten okunan eserler rapor tablosunda (24 Ekim, D114):** yeni oluşturulan kanıt tablolarına ve raporlarına, yalnız özeti okunan eserler de "özetten" işaretiyle giriyor. Eski tablolar değişmiyor. Sol üç turda inceledi; canlı modelle denenmedi.
- **Paketleme yok:** P10 (macOS paketi) sahibin görsel kontrolünü bekliyor. Windows ve Linux hiç denenmedi.

Kısa hüküm: altyapı ve kurallar sağlam, arama ölçülmüş ve iyi; ama son iki haftada ölçmeden eklenen özellik sayısı fazla. Bir sonraki dönemin işi yeni özellik değil, var olanı gerçek kullanımda denemek ve paketlemek.

## Görsel kontrol (24 Ekim)

Sahibin hedefi: yalnız görsel kontrol, ardından uygulama (P10) kısmı. Liste `notes/visual-check-2026-10-24.md` (14 Ekim'den beri değişen ekranlar, 29 madde). Build güncel; sahibin kütüphanesinin bir kopyasında 0014–0016 kayıt dosyaları sorunsuz uygulandı ve ekranlar hatasız açıldı.

24 Ekim incelemesinde bulunup görsel kontrolü beklemeyen işler park edildi: D106 gerçek koşusu (~12 USD OpenAlex + 1–3 USD Voyage, 7–9 saat; ön ödemeli bakiye ~10 USD yükleme ister), arama sıralaması (ana makaleler havuzda ama ilk 50'nin dışında; sorgu 6 terim sınırı eş anlamlıları atıyor), plan aşaması süresi (sayım istekleri sırayla gidiyor, süre sınırı uygulanmıyor), 30 iddia sınırını 45'e çıkarma ölçümü (~18 koşu). Yan hata düzeldi: doğrudan yayımlanan bir yeniden yazım da 30 iddia sınırına tabi (e46aa4fa).

Bugün ayrıca PDF indirmede e-posta, sunucu başına 403 sayımı ve Elsevier açık erişim yolu eklendi (D117). Main'in son CI koşusunda bir test düştü (`test_worker_survives_a_code_error_in_a_turn`); yerelde art arda ve paralel geçiyor, ara sıra düşen bir test gibi görünüyor, yeniden koşturuldu.

## Döndüğünde sırayla bakılacaklar

1. **Yarım işler kapandı (24 Ekim):** `abstract-rows` alındı (D114, fd4d37bf); arama kayıpları okundu (yukarıda).
2. **Reranker ve zincir kayıtları:** D106 yalnız-zincir kayıtlarını korudu (kaybın yarısı). Kalan yarı, arama ile de bulunan zincir kayıtlarından geliyor; onları da korumak LitSearch'te −0,032 kaybettiriyor. Gerçek bir yeni koşu (BioASQ dahil) D106'yı doğrulamadan başka ayar yapılmasın.
3. **Görsel kontrol, sonra P10:** sahibin göz kontrolü ve çıkan düzeltmeler; ardından macOS paketi (plan `notes/plans/p10-plan.md`, K1–K15 satırları; OpenAI, Gemini, DeepSeek fiyatları yayından önce doğrulanacak).
4. **Ölçülmemiş özellikleri bir kez canlı dene:** ters atıf aramanın canlı pilotu R4b ile çıtayı geçti (D109: destek sayılan 24 sonuçta iki okuyucuya göre 0 hata; bedeli, okuyucuların destekleyici bulduğu ~20 sonuç "destek yeterince gösterilmedi" grubunda ve bilinen 7 destekleyiciden yalnız 1'i destek sayılıyor; arama kayıpları açık; R5 karşıtlık bloklu), kartopu okuma penceresi 24 Ekim'de ölçüldü (400'lük havuz tutulmadı, 200 kalıyor).
5. **Yeni özellik ekleme duraklaması:** gap finder, Chain of Ideas, R5 gibi fikirler yukarıdakiler bitene kadar bekler.

## Açık işler (kısaltılmış)

### Arama
- [ ] D106'yı gerçek bir benchmark koşusuyla doğrula (BioASQ, LitSearch, EE survey; reranker açık). Bugünkü sonuç yalnız kayıtlı puanların yeniden oynatılması. Maliyet yaklaşık 12 USD OpenAlex (24 Ekim tahmini; eski 3 USD yanlıştı), ön ödemeli bakiye yüklenmeli; eski koşu satırları önce ayrı klasöre taşınmalı.
- [ ] Geniş sorularda bilinen ana makaleler üste çıkmıyor (battery_soh: 15 hedeften 3'ü ilk 50'de); DBR/VBF en zayıf soru, Quick modu Maulana 2019'u kaçırıyor.
- [ ] Sorgu başına 500 kayıt okuma sınırı; BioASQ'da 480 gold makalenin 107'si hiç gelmiyor (`semantic_top` 50'de sınırlı).
- [ ] Ücretsiz OpenAlex günlük kotası yaklaşık 20 araştırmada bitiyor; Standard koşuların 20'de 7'si 5 dakikayı geçti (sebep bakılmadı).
- [ ] Tam metin sınırları (10/20/40) ölçümle seçilmedi; ULAKBİM ağından MDPI, SAGE, ScienceDirect PDF'leri 403 dönüyor.
- [ ] Kill search ve kartopu: bulunan doğru makaleler sıralama sınırında kesiliyor (aşağıda "Sonra bakılacak").

### Sonra bakılacak: bulunan makale sıralamada kesiliyor (24 Ekim)

İki özellik de aynı yerde takılıyor. Arama doğru makaleyi getiriyor, ama özellik yalnız ilk birkaçına bakıyor ve doğru makale o birkaçın dışında kalıyor.

- [ ] **Kill search, ilk 8:** yazdığın iddiayı daha önce yapan var mı diye bakıyor; havuzdan yalnız 8 eseri modele okutuyor. 24 Ekim'de 3 yeni iddiada etiketli 9 eserin 6'sı havuza geldi, yalnız 1'i 8'e girdi. Örnek: kalp yetmezliği iddiasında asıl deneme (DAPA-HF) 66. sırada. AoI iddiasında 8 yerin 5'ini iki makalenin arXiv/konferans/dergi sürümleri kapladı.
- [ ] **Kartopu, ilk 80:** bir turda yüzlerce yeni eser geliyor, yalnız ilk 80'i taranıyor. Sıra kabaca "başlıkta soru terimi var mı, kaç tohuma bağlı, ne kadar yeni" diye kuruluyor. Aranan eserler 170, 221, 298. sıralarda kaldı. Eski makalelerin çoğunun özeti yok, model okuyamıyor. 3 soruda kaçan 15 eserden 1'i aday oldu.

Önerilen çözüm sırası (ölçülmedi, öneri):
1. **Sürümleri kesimden önce birleştir** (kill search): aynı makalenin arXiv, konferans ve dergi kaydı tek eser sayılsın. Model gerekmez, 8 yeri boşaltır. İlk denenecek iş bu.
2. **Kesimden önce iddiaya/soruya göre yeniden sırala:** ana aramada zaten açık olan reranker (Voyage) kill search havuzunun ilk ~100'üne ve kartopunun yeni eserlerine uygulansın. Bugünkü sıra kelime eşleşmesi ve tarihle kuruluyor, anlama bakmıyor.
3. **İki aşamalı okuma:** ilk ~40 eserin başlık ve özeti tek ucuz model çağrısında elensin, ayrıntılı okumaya en iyi 8 (kill search) veya 80 (kartopu) gitsin.
4. **Özeti olmayana özet bul:** kartopunda taramadan önce Semantic Scholar, Crossref veya PubMed'den özet istensin; yine yoksa "başlıktan bakılmalı" diye kişiye gösterilsin.
5. **Kesileni göster:** kartta "havuzda olup okunmayan N eser" listesi ve "bunları da oku" düğmesi; kartopunda mevcut "Screen more" öne çıksın.

Her adım dondurulmuş kuralla, 24 Ekim'in iddia ve soru setinde ölçülsün (etiketler `notes/2026-10-24-live-pilots/RULES.md` ve `elicit3/targets.json`).

### Sonra bakılacak: Elicit karşılaştırması ve PDF boşluğu (24 Ekim, incelenecek)

Ölçümler yapıldı, hiçbiri koda yansımadı. Ayrıntı: `notes/2026-10-24-elicit-compare/RESULT.md` ve `notes/2026-10-24-pdf-gap/RESULT.md`.

- [ ] **Elicit'e karşı (5 soru, ikişer canlı koşu, Sonnet 5.5 medium):** Elicit'in anahtar makalelerinin %83'ü bulundu, %60'ı cevapta atıf aldı; 0,90'a ulaşılmadı. Atıfların 156'sı da bulunmuş pasaja bağlı. Hüküm karşılaştırması tek model okuyucudan; insan okuması yok (etiketsiz yan yana okuma dosyası istenirse hazırlanır).
- [ ] **Hata (düzeltilmedi):** özeti geçen bir iş, indirilen PDF başka sürümse ve PDF okuması sonuçsuz kalırsa cevaptan tamamen düşüyor (`answer.py::cutoff_snapshot`, kardeş sürümün özetine yalnız PDF'in hiç metni yoksa dönüyor). perishable_two'da Elicit'in en yakın makalesi bu yüzden iki koşuda da cevaba girmedi. Yalnız bu bir işte doğrulandı.
- [ ] **Arama kaçırması:** perishable_res'te Elicit'in 10 anahtar makalesinin 5'i hiç gelmedi (OpenAlex'te var, iki koşuda aynı 5). Sebep ölçülmedi.
- [ ] **PDF'i elle yükleme yükü:** 27 yüklemenin 19'u kapalı erişim, 7'si açık ama yalnız yayıncı sitesinde (bot koruması), 1'inin arXiv kopyası var; elle yük K sınırından değil erişimden. IEEE ağırlıklı konuda elle iş ~13–24 kalır, "3–5" hedefi arka uçla tutmuyor. Ölçülmeyen: 4 Ekim koşusunun K kaybı, kapalı işlerin yazar kopyaları.
- [x] **"Hepsini aç" düğmesi** (Waiting for your PDF): bekleyen her eserin DOI bağlantısını tek tıkla kendi sekmesinde açıyor, engellenen sekmeler sayılıyor ve sonraki tıklama yalnız onları açıyor; main'de (23440bb5, Sol 3 tur). Aynı spec'teki iki eski test D45/D46 ekran değişikliklerine göre güncellendi, spec 10/10.

### Ters atıf arama (bir ifadeyi destekleyen eserleri bulma)
Tamamlanan:
- [x] Plan (Sol ile, `notes/plans/reverse-citation-search-plan.md`)
- [x] R1: ifade kontrolü motoru, Verify Citations V3 adımını kullanıyor (D100)
- [x] R2: başlatma, sürdürme, eskime, dışa aktarım yolları (D103)
- [x] R3: Home'da "Check a statement" modu ve sonuç paneli (D107)
- [x] R4: canlı pilot, çıtayı geçemedi; "kısmen destekliyor" sonuçlarının 10–11/50'si yanlış (D108)
- [x] R4b: destek yalnız en az bir parça açıkça yazılıysa sayılıyor; aynı 10 cümlede çıta geçti (D109, `notes/2026-10-18-reverse-citation-r4b-pilot/RESULT.md`)

Yapılacak:
- [x] Arama kaybı: alan ve yazar sorguları eklendi, bulunan 8 → 12/13 (D116, `notes/2026-10-24-reverse-citation-r5/RESULT.md`); modelin alanı kendisinin bulduğu yol ölçülmedi
- [ ] İhtiyatlı kuralın bedeli: "destek yeterince gösterilmedi" grubundaki 31 sonucun ~20'si aslında destekleyici; bilinen destekleyicilerden yalnız 1/7 destek sayılıyor. Tam metin okuma ya da parça bölmeyi iyileştirmek ayrı deneme ister
- [ ] Tamamlanan kontrollerin hiçbiri tam metinle yapılmadı; hep özet
- [ ] "Bulunamadı" çıkan 113 sonuç okunmadı (kaçırma oranı ölçülmedi)
- [ ] Gemini embedding adımı iki koşuda da kredi bitmesi yüzünden çalışmadı; embedding'li koşu yok
- [ ] Türkçe metinleri anadili Türkçe biri okumadı; çalışan/duraklayan kontrol tarayıcıda görülmedi
- [ ] R5 "karşı çıkıyor" sonucu: bloklu; ayrı plan ve pilot kapısı gerekiyor (`notes/plans/reverse-citation-search-plan-with-challenge-2026-10-18.md`)

### Cevap ve rapor
- [ ] Her D83 koşusu 30 iddia sınırına takılıyor; 12–13 eser `claim_limit` ile dışarıda kalıyor. Başka sorularda ölçülmedi.
- [ ] İlk cevap taslağı çoğu zaman bağlantı kurallarını bozuyor; onarım cevap başına 1–2 dakika ekliyor.
- [ ] `review_mode: "off"` verilse de answer_review çalıştı (17 Ekim, 5 araştırma); bakılmadı.
- [ ] Rapor kalitesi için sahip puanı alınmadı (`notes/plans/report-eval-set.md`).

### Kod denetiminden kalan düşük öncelikli maddeler
- [ ] Bayat hücre yeniden kontrol tahmini 25 kaynakta duruyor; çalışma tablosu zinciri başarısız kaynaktan sonra sessizce turları bitirebiliyor; Section VI boşluk adayları saklanmayan bir okuma derinliği istiyor; takip bağlamı eski soru revizyonunun cevabını alabiliyor.
- [ ] Windows'ta PDF alt sürecinin bellek sınırı yok (P10 Job Object maddesi).

### Test ve platform
- [ ] Paralel testler yük altında ara sıra düşüyor (25 Ekim test sadeleşmesinde `tests/app/test_reference_import_parser.py` silindi; düşen testler sadeleşmiş pakette yeniden gözlenmeli).
- [ ] Hızlı cevap akışının duraklat/sürdür testi yok; arama aşaması zincir istekleri sürerken bitmiş görünebiliyor.
- [ ] Ölçülmedi: ikinci kurulu kullanıcı, ekran okuyucular, sessiz makinede kapasite, elektrik kesintisi, dolu disk.

### Sahibin kararını bekleyen fikirler
- Ana sayfada sabit örnek sorular; açık erişimli PDF'lerin neden 403 döndüğünü sınıflamak; P10 sonrası açılış sayfası; iki sorgu terimlerin çoğunu paylaşınca uyarı.

## Yapılanlar (özet)

Ayrıntı ve sayılar ilgili D kararında.

- **Arama:** tek yol hızlı yol (temiz başlangıç, 10–11 Ekim); başlangıç PDF'leri aramayı yönlendiriyor (D2, D3, D6); atıf haritası (D42); kartopu (D91); takip sorusundan yeni eser arama (D92); reranker varsayılan Voyage (D104); llama.cpp ile yerleşik embedding ve reranker modelleri (D90).
- **Okuma ve cevap:** ikinci tam metin okuması görmediği bölümleri okuyor (D76); cevaba verilen her eser ya atıflanıyor ya gerekçeyle dışarıda kalıyor (D80, D83); sonuç yoğun pasaj önce (D84); formül soruları için formül sayfası (D56).
- **Atıf denetimi:** Verify Citations V1–V4 (D86, D96, D99, D101), V5 pilotu ve düzeltmeleri (D105; sonuç `notes/2026-10-18-verify-citations-v5-pilot/RESULT-r2.md`, açık: tablo satırında yazar sütunu doğrulanacak iddia sayılıyor, P25); ters atıf arama R1–R4b (D100, D103, D107, D108, D109; Home modu, sonuç paneli, canlı pilot geçti).
- **Tablo ve rapor:** sayı kontrol bayrağı (D54), yazım kuralları (D51, D55), hücre yeniden deneme (D68), Anthropic API'de rapor şeması (D87, D93).
- **Modeller ve ayarlar:** Anthropic API akışlı cevap, 64k token (D85); anahtarlar sistem keychain'inde (D19, D29); şirket başına model kartı (D20–D24, D34); Ollama/LM Studio (D39); kullanım ve harcama ekranı (D78).
- **Uygulama:** mockup v24/v25 tasarımı (D5, D77, D79); run kartı (D82); P10 öncesi hazırlık kodda bitti; GitHub Actions tam testi dört makinede koşturuyor (bilgi amaçlı, hiçbir şeyi engellemiyor).
- **Kod denetimi (16–17 Ekim):** üç denetimde 33 kusur bulundu, 27'si testle ve Sol incelemesiyle düzeltildi; kalanlar yukarıda.
