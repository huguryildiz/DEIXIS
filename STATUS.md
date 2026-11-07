# DEIXIS durumu

**Son güncelleme:** 7 Kasım 2026 (gece). Kararlar [docs/decisions.csv](docs/decisions.csv), ölçümler [docs/benchmark.md](docs/benchmark.md). Ölçüm ayrıntılarıyla uzun hali Git geçmişinde (commit c3ec6ded).

## Neredeyiz?

Uygulama çalışıyor. Son haftalarda eklenenlerin çoğu gerçek kullanımda denenmedi. 6–7 Kasım'da masaüstü paketi (P10) çıktı: Apple Silicon Mac ve Windows için ön sürüm; görsel kontrol buna paralel, parça parça sürüyor. Her maddenin ayrıntısı [docs/decisions.csv](docs/decisions.csv)'de, D numarasıyla.

**Son yapılanlar (25–26 Ekim)**

- Repo sadeleşti, ölü kod silindi; davranış değişmedi (D119, D120, D124).
- Arama sürerken kaynak dahil etmek ya da dışlamak aramayı durdurmuyor (D127).
- Cevaplar kaynakları adıyla anıyor ve hükümle açılıyor; adlar kayıttan geliyor, modelden değil (D131).
- Tam metni okunan en yakın makaleler cevaba ve tabloya giriyor; okumada daha çok soru parçası bulan önce seçiliyor (D137, D144, D145).
- Denklemler Codex'le de okunuyor ve daha hızlı; daha çok denklem bulunuyor (D134, D136, D138, D139, D142).
- Tabloda her kaynağın okunma derinliği yazıyor; rapor kaynakları adıyla anıyor (D140, D143).
- Görsel kontrolden düzeltmeler: kendi özeti olmayan sürüm diğer sürümün özetini gösteriyor; "Add to chat" yalnız cevapta; birkaç ekran sadeleşti (D146, D147).

- **Mac paketi, 1. adım:** backend artık Python kurulmadan tek klasörlük bir program olarak çalışıyor (107 MB, ~1 sn'de açılıyor). Bu Mac'te 13 kontrolün hepsi geçti: PDF, OCR, soru → atıflı cevap, eski kütüphanenin yükseltilmesi, kapanışta açık süreç kalmaması. (D150)
- **Mac paketi, 2. adım:** kendi penceresi, menü çubuğu simgesi ve DMG'si olan DEIXIS.app (57,7 MB). Çıkışta, çökmede ya da zorla öldürmede DEIXIS'in başlattığı her süreç kapanıyor; bu Mac'te sahte Codex/Gemini/Copilot ve PDF işleriyle ölçüldü (en uzun 6,6 sn). Pencere testleri (açılış, pencere içi kayıt, indirme) ekran kilitli olduğu için henüz koşmadı; release bunlardan sonra (D151).
- **Cevap kalitesi ilk kez ölçüldü (6 Kasım):** 6 kayıtlı cevapta kaynağa dayanan 128 iddianın %93'ü pasajıyla tam destekleniyor, desteklenmeyen yok (hakem Codex Sol). Asıl zayıflık kanıtın eksikliği: 3 soruda 18 referans makaleden 11'i cevaba gelmeden düştü (sıralamada ilk 50 dışı, havuzda yok, özet taramasında "kapsam dışı", sürüm karışıklığı). Üç düzeltme: plan gecikmesi aramayı kısaltmıyor, özeti eksik kayıtlar sıralamadan önce aranıyor, okunup kriter parçası bulunmayan işlerden biri en yakın iş olarak cevaba girebiliyor. Kayıpları geri getirip getirmediği ölçülmedi (D152, ayrıntı `notes/2026-11-06-answer-quality/`). Ardından (Astra ve Argon ile tartışılıp): reranker'ın bakacağı 400 kaydın eksik özetleri sıralamadan önce dolduruluyor, dolmayan yerinde kalıyor (D153); sorgu 8 kelimeye kadar eş anlamlı alıyor, yedek kelime daha akıllı devreye giriyor, arama kelimelerinden ek bir anlam araması gidiyor (D154). İlk ölçüm (4 yeni soru, kol başına 1 koşu): kazanç yok. Cevaba giren referans eski kodda 13, yenide 11 (51 referanstan); ilk 50'ye giren 13'ten 16'ya çıktı ama fazlası tarama sonrası düştü. Fark tek koşunun gürültüsü içinde; zarar da kanıtlanmadı. En büyük kayıp hâlâ "havuzda ama ilk 50'nin dışında" (`notes/2026-11-06-answer-quality/pilot/RESULT.md`). Pilotun teşhisinden sonra dört düzeltme (D155, Sol ve Argon ile): Semantic Scholar hız sınırına takılınca beklemeden Crossref'e geçiliyor ve kısa bir bekleme süresi boyunca atlanıyor; özeti olmayan iş yerinde ancak metnine bir yol varsa (açık PDF, yüklenmiş dosya, cevapsız kalan arama) kalıyor; cevapta adayların özetleri en yakın işlerin ek sayfalarından önce geliyor, kriter parçası bulunmayan en yakın iş en çok 2 pasaj alıyor; arama kelimelerinden giden ek anlam araması kapatıldı. Eski koşular kendi kurallarını koruyor. Ölçülmedi. İkinci pilot bu daraltmanın çoğu koşuda işlemediğini gösterdi (8 saniyelik arama 6 koşunun 4'ünde süreyi doldurdu, isteği hiç gönderilmemiş kayıtlar da yerinde tutuldu); yeni koşularda Crossref'e aynı anda 8 istek gidiyor ve özeti olmayan iş ancak kendisi için gerçekten gönderilmiş bir istek zamanında dönmediyse yerinde kalıyor (D156, ölçülmedi).
- Türkçe (İngilizce olmayan) soru artık durmuyor: model soruyu tek İngilizce cümleye çeviriyor, arama kelimeleri o cümleden seçiliyor; cümle plan adımında görünüyor ve düzeltilebiliyor. Çevirinin arama kalitesine etkisi ölçülmedi (D149).

**Ne kadar biliyoruz**

- Sağlam: her atıf kodun pasajda bulduğu bir yere bağlı (8 cevapta 171 bağlantı, hepsi doğru).
- Ölçüldü, iyi: arama sırası, ilk 50'de düz OpenAlex'ten iyi (BioASQ 0,618, LitSearch 0,700).
- Ölçüldü, zayıf: EE survey seti (0,129); reranker orada zarar veriyor.
- Elicit'e karşı: anahtar makalelerin %83'ü bulundu, %60'ı atıf aldı (24 Ekim, son değişikliklerden önce).
- Ölçülmedi: son cevap değişikliklerinin kaliteye etkisi. İnsan puanı yok.
- Bilinen zayıflık: cevaplar 30 iddia sınırına takılıyor; paywall arkası okunamıyor; Windows ve Linux denenmedi.

## Sırayla yapılacaklar

1. **P10, masaüstü paketi** (planlar `notes/plans/p10-mac-first.md`, `notes/plans/p10-windows.md`): Mac M1–M2 ve Windows W1–W5 bitti, her dilim GPT Sol High incelemesinden geçti. [`v0.1.1`](https://github.com/huguryildiz/DEIXIS/releases/tag/v0.1.1) ön sürüm olarak GitHub'da: Windows kurulum dosyası (sha256 `e14f5d47…`) ve Mac DMG (sha256 `964d5683…`). Windows kurulu uygulama VM'de 11/11, Windows test paketi GitHub'ın x64 makinesinde yeşil; Mac 15/15. Windows'ta yerleşik yerel modeller ve arXiv kaynak okuma kapalı; Windows 10 ve gerçek bir x64 PC denenmedi (D158). Sırada M3 (Tesseract paket içinde, tema ve sürüm kontrolü), M4 (ilk aday sürüm, sürümden sürüme yükseltme testi). Intel Mac ve Linux sonra. OpenAI, Gemini, DeepSeek fiyatları yayından önce doğrulanacak.
2. **Görsel kontrol** (sahip, paralel): liste `notes/visual-check-2026-10-24.md`, 28 madde.
3. **D106'yı gerçek koşuyla doğrula** (BioASQ, LitSearch, EE survey): ~12 USD OpenAlex + 1–3 USD Voyage, ön ödemeli bakiye ister. Bu bitmeden reranker ayarı değişmesin.
4. **Kill search ve kartopu kesimi:** doğru makale havuzda ama okunan ilk 8 / ilk 80'in dışında. İlk denenecek: aynı makalenin sürümlerini birleştirmek, sonra kesimden önce rerank. Ayrıntı `notes/2026-10-results.md`, "Live pilots" bölümü.
5. **Yeni özellik duraklaması:** gap finder, Chain of Ideas, R5 bunlar bitene kadar bekler.

## Açık işler

- **Arama:** geniş sorularda ana makaleler ilk 50'ye girmiyor (DBR/VBF en zayıf); sorgu başına 500 kayıt sınırı; ücretsiz OpenAlex kotası ~20 araştırmada bitiyor; ULAKBİM ağından bazı yayıncı PDF'leri 403.
- **Cevap:** özeti geçen bir eser, indirilen PDF başka sürümse ve okunamazsa cevaptan düşüyor (`answer.py::cutoff_snapshot`, düzeltilmedi); `review_mode: "off"` iken answer_review çalıştı (bakılmadı).
- **Ters atıf arama:** ihtiyatlı kural destekleyicilerin çoğunu "yeterince gösterilmedi"de bırakıyor; tam metinle kontrol yok; R5 "karşı çıkıyor" bloklu.
- **Atıf kontrolü (Verify citations), P25:** tablo satırının ilk sütunundaki yazar adları ayrı bir iddia gibi kontrol ediliyor; adlar kaynağın kapağında bulununca bütün hücreleri "yok" olan satır "kısmen bulundu" çıkıyor. Düzeltilmedi (`notes/2026-10-results.md`, "Verify citations V5" bölümü).
- **Rapor değerlendirme seti:** 5 raporun sahip tarafından 1–5 puanlanması hiç yapılmadı; raporlar silindi, yapılacaksa baştan üretilmeli.
- **Sadeleşme, kalan 6 iş** (davranış değişmez, acele yok; Astra ve Argon'un ortak planı `notes/2026-10-results.md`, "Simplification review" bölümü, önerilen sırayla): birebir aynı test yardımcılarını `tests/support/` altına toplamak (2–5 sa); birebir aynı 6 yardımcı grubunu tek kopyaya indirmek, örneğin `should_write`, `errorText` (2–6 sa); model bağlantılarında ortak sağlık önbelleği (4–5 sa); `app.py`'den önce yalnız sahip incelemesi route'larını ayırmak (2–5 sa); `api.ts` ve `Connections.tsx`'i bölmek (5–8 sa); `web/src/research/` dosyalarını alt klasörlere ayırmak (3–4 sa). Düşürülenler: `documents/` içinde runtime klasörü, benchmark JSON'larını taşımak.
- **Yazar adı ekleri:** kısa atıf "van Leent"i "Leent", "de Riedmatten"i "Riedmatten" yazıyor (ad ayrıştırıcı; atıf çipleri de aynı). Düzeltilmedi.
- **Test ve platform:** paralel testler yük altında ara sıra düşüyor; hızlı akışın duraklat/sürdür testi yok; Windows PDF alt sürecinde bellek sınırı yok (P10).
- **Sahibin kararını bekleyen:** ana sayfada örnek sorular, 403 sınıflaması, P10 sonrası açılış sayfası.
