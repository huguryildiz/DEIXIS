# DEIXIS durumu

**Son güncelleme:** 18 Ekim 2026. Kararlar [docs/decisions.md](docs/decisions.md) içinde (en yenisi üstte), ölçümler [docs/benchmark.md](docs/benchmark.md) içinde. Bu dosyanın 18 Ekim öncesi uzun hali Git geçmişinde (commit 847b6b0b).

## Kısaca: neredeyiz?

Durum kötü değil, ama dengesiz. Uygulama çalışıyor ve özellik bakımından geniş; asıl eksik, son haftalarda eklenen özelliklerin çoğunun gerçek bir modelle ve gerçek kullanımda denenmemiş olması.

- **Sağlam olan:** atıf kuralı. Cevaptaki her atıf, okunan bir pasajda kodun bulduğu bir yere bağlanıyor; bulunamazsa cevap "doğrulanmamış taslak" kalıyor. 8 kayıtlı cevaptaki 171 atıf bağlantısının hepsi doğru çıktı.
- **Ölçülen ve iyi olan:** arama sırası. 18 Ekim'de iki hazır test setinde, sahibin ayarlarıyla (Voyage embedding + Voyage reranker) DEIXIS ilk 50 sonuçta düz bir OpenAlex aramasından belirgin olarak fazla doğru makale buluyor: BioASQ'da 0,618'e karşı 0,489, LitSearch'te 0,700'e karşı 0,561. Reranker her iki sette de güven aralığı sıfırın üstünde katkı veriyor; bu yüzden artık varsayılan olarak açık (D104).
- **Ölçülen ve zayıf olan:** elektrik mühendisliği survey seti (42 survey, gold = survey'in kaynakçası). Burada DEIXIS düz OpenAlex'i geçiyor (0,129'a karşı 0,065) ama fark küçük ve **reranker zarar veriyor** (0,091). Sebep: bu sette doğru makalelerin çoğu atıf zincirinden geliyor, reranker yalnız başlık ve özet okuduğu için zincir kayıtlarını aşağı itiyor. Varsayılanı açık yapan karar (D104) bu sonuçtan önce alındı. D106 ile reranker yalnız zincirden gelen kayıtları artık yerinde bırakıyor: kayıtlı koşular üstünde tekrar oynatınca survey setinde 0,091 → 0,111, LitSearch değişmedi; kaybın yarısı duruyor, BioASQ ölçülmedi, yeni koşu yapılmadı.
- **Bir kez canlı denenen:** Verify Citations (taslak atıf denetimi). V5 pilotu (bir taslak, 30 çift, Sonnet 5.5; insan etiketi yok, okuyucular Sol ve Opus): D105 sonrası tekrarda kontrol tamamlanamayan %48'den %14'e indi, örneklemde yanlış "bulundu" 0, üç eşik geçti. Tek koşu; sonucun bir kısmı modelin koşudan koşuya oynamasından olabilir.
- **Ölçülmeyen:** ters atıf arama, kartopu (snowballing), kill search'in Next steps girişi, run kartı. Hepsi yalnız sahte modelli testlerle ve Playwright'la sınandı. Okuma ve cevap kalitesi de ayrıca ölçülmedi: arama testleri yalnız sıralamayı ölçüyor.
- **Bilinen zayıflık:** cevaplar, kendilerine verilen eserlerin azını atıflıyor (D83 sonrası DBR/VBF sorusunda 13 eserden 12–13'ü, ama her koşu 30 iddia sınırına takılıyor). Raporlar model puanıyla 30 üzerinden 15–20 aldı (insan puanı yok). Paywall arkasındaki tam metinler okunamıyor; mühendislik makalelerinin çoğu özetten okunuyor.
- **Paketleme yok:** P10 (macOS paketi) sahibin görsel kontrolünü bekliyor. Windows ve Linux hiç denenmedi.

Kısa hüküm: altyapı ve kurallar sağlam, arama ölçülmüş ve iyi; ama son iki haftada ölçmeden eklenen özellik sayısı fazla. Bir sonraki dönemin işi yeni özellik değil, var olanı gerçek kullanımda denemek ve paketlemek.

## Yarım kalan işler (18 Ekim)

- **Özet kaynaklar rapor tablosunda (D99 taslağı):** yerel `abstract-rows` dalında tek commit (dcd775ca), uzakta yok, main'e girmedi. Bekleyen sahip kararına bağlı: rapor tablosu bugün yalnız tam metni okunan kaynakları alıyor, cevap özetten okunanları da atıflıyor; az tam metinli sorularda (battery_soh, higher_ed_ai) rapor tek kaynağa dayanıyor. Plan: `.local/plans/abstract-rows-plan.md`.
- **Arama kayıpları oturumu** ("okuma payı ve sorgu talimatı"): 18 Ekim'de hâlâ çalışıyordu. Kaçan makalelerin analizi `.local/benchmark-loss-2026-10-18/RESULT.md`: 74 kayıptan 35'i hiçbir DEIXIS sorgusuna uymuyor, 39'u sorgu başına okunan 500 kaydın ötesinde kalıyor.

## Döndüğünde sırayla bakılacaklar

1. **Yarım işleri kapat:** `abstract-rows` için kararı ver (al ya da sil); arama kayıpları oturumunun sonucunu oku.
2. **Reranker ve zincir kayıtları:** D106 yalnız-zincir kayıtlarını korudu (kaybın yarısı). Kalan yarı, arama ile de bulunan zincir kayıtlarından geliyor; onları da korumak LitSearch'te −0,032 kaybettiriyor. Gerçek bir yeni koşu (BioASQ dahil) D106'yı doğrulamadan başka ayar yapılmasın.
3. **Görsel kontrol, sonra P10:** sahibin göz kontrolü ve çıkan düzeltmeler; ardından macOS paketi (plan `.local/plans/p10-plan.md`, K1–K15 satırları; OpenAI, Gemini, DeepSeek fiyatları yayından önce doğrulanacak).
4. **Ölçülmemiş özellikleri bir kez canlı dene:** ters atıf aramanın canlı pilotu (R4; ekran R3 D107 ile main'de), kartopu için okuma penceresi ölçümü (havuz 200 ve 400, ikinci bir soruda).
5. **Yeni özellik ekleme duraklaması:** gap finder, Chain of Ideas, R5 gibi fikirler yukarıdakiler bitene kadar bekler.

## Açık işler (kısaltılmış)

### Arama
- [ ] D106'yı gerçek bir benchmark koşusuyla doğrula (BioASQ, LitSearch, EE survey; reranker açık). Bugünkü sonuç yalnız kayıtlı puanların yeniden oynatılması. Maliyet yaklaşık 3 USD OpenAlex.
- [ ] Geniş sorularda bilinen ana makaleler üste çıkmıyor (battery_soh: 15 hedeften 3'ü ilk 50'de); DBR/VBF en zayıf soru, Quick modu Maulana 2019'u kaçırıyor.
- [ ] Sorgu başına 500 kayıt okuma sınırı; BioASQ'da 480 gold makalenin 107'si hiç gelmiyor (`semantic_top` 50'de sınırlı).
- [ ] Ücretsiz OpenAlex günlük kotası yaklaşık 20 araştırmada bitiyor; Standard koşuların 20'de 7'si 5 dakikayı geçti (sebep bakılmadı).
- [ ] Tam metin sınırları (10/20/40) ölçümle seçilmedi; ULAKBİM ağından MDPI, SAGE, ScienceDirect PDF'leri 403 dönüyor.
- [ ] Kill search: canlı kapının üçüncü iddiası (diz osteoartriti) 0/3 kaldı; genel olarak önceki çalışmayı bulup bulmadığı gösterilmedi. Ayar çalışması durduruldu.

### Cevap ve rapor
- [ ] Her D83 koşusu 30 iddia sınırına takılıyor; 12–13 eser `claim_limit` ile dışarıda kalıyor. Başka sorularda ölçülmedi.
- [ ] İlk cevap taslağı çoğu zaman bağlantı kurallarını bozuyor; onarım cevap başına 1–2 dakika ekliyor.
- [ ] `review_mode: "off"` verilse de answer_review çalıştı (17 Ekim, 5 araştırma); bakılmadı.
- [ ] Rapor kalitesi için sahip puanı alınmadı (`.local/plans/report-eval-set.md`).

### Kod denetiminden kalan düşük öncelikli maddeler
- [ ] Bayat hücre yeniden kontrol tahmini 25 kaynakta duruyor; çalışma tablosu zinciri başarısız kaynaktan sonra sessizce turları bitirebiliyor; Section VI boşluk adayları saklanmayan bir okuma derinliği istiyor; takip bağlamı eski soru revizyonunun cevabını alabiliyor.
- [ ] Windows'ta PDF alt sürecinin bellek sınırı yok (P10 Job Object maddesi).

### Test ve platform
- [ ] Paralel testler yük altında ara sıra düşüyor; `tests/app/test_reference_import_parser.py` tam seri `--testmon`'da 3 test düşüyor, tek başına geçiyor.
- [ ] Hızlı cevap akışının duraklat/sürdür testi yok; arama aşaması zincir istekleri sürerken bitmiş görünebiliyor.
- [ ] Ölçülmedi: ikinci kurulu kullanıcı, ekran okuyucular, sessiz makinede kapasite, elektrik kesintisi, dolu disk.

### Sahibin kararını bekleyen fikirler
- Ana sayfada sabit örnek sorular; açık erişimli PDF'lerin neden 403 döndüğünü sınıflamak; P10 sonrası açılış sayfası; iki sorgu terimlerin çoğunu paylaşınca uyarı.

## Yapılanlar (özet)

Ayrıntı ve sayılar ilgili D kararında.

- **Arama:** tek yol hızlı yol (temiz başlangıç, 10–11 Ekim); başlangıç PDF'leri aramayı yönlendiriyor (D2, D3, D6); atıf haritası (D42); kartopu (D91); takip sorusundan yeni eser arama (D92); reranker varsayılan Voyage (D104); llama.cpp ile yerleşik embedding ve reranker modelleri (D90).
- **Okuma ve cevap:** ikinci tam metin okuması görmediği bölümleri okuyor (D76); cevaba verilen her eser ya atıflanıyor ya gerekçeyle dışarıda kalıyor (D80, D83); sonuç yoğun pasaj önce (D84); formül soruları için formül sayfası (D56).
- **Atıf denetimi:** Verify Citations V1–V4 (D86, D96, D99, D101), V5 pilotu ve düzeltmeleri (D105; sonuç `.local/verify-citations-v5-pilot/RESULT-r2.md`, açık: tablo satırında yazar sütunu doğrulanacak iddia sayılıyor, P25); ters atıf arama R1–R3 (D100, D103, D107; R3: Home modu ve sonuç paneli).
- **Tablo ve rapor:** sayı kontrol bayrağı (D54), yazım kuralları (D51, D55), hücre yeniden deneme (D68), Anthropic API'de rapor şeması (D87, D93).
- **Modeller ve ayarlar:** Anthropic API akışlı cevap, 64k token (D85); anahtarlar sistem keychain'inde (D19, D29); şirket başına model kartı (D20–D24, D34); Ollama/LM Studio (D39); kullanım ve harcama ekranı (D78).
- **Uygulama:** mockup v24/v25 tasarımı (D5, D77, D79); run kartı (D82); P10 öncesi hazırlık kodda bitti; GitHub Actions tam testi dört makinede koşturuyor (bilgi amaçlı, hiçbir şeyi engellemiyor).
- **Kod denetimi (16–17 Ekim):** üç denetimde 33 kusur bulundu, 27'si testle ve Sol incelemesiyle düzeltildi; kalanlar yukarıda.
