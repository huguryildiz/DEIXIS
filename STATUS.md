# DEIXIS durumu

**Son güncelleme:** 26 Ekim 2026. Kararlar [docs/decisions.csv](docs/decisions.csv), ölçümler [docs/benchmark.md](docs/benchmark.md). Ölçüm ayrıntılarıyla uzun hali Git geçmişinde (commit c3ec6ded).

## Neredeyiz?

Uygulama çalışıyor. Son haftalarda eklenenlerin çoğu gerçek kullanımda denenmedi. Sıradaki iş yeni özellik değil: görsel kontrol, sonra macOS paketi (P10). Her maddenin ayrıntısı [docs/decisions.csv](docs/decisions.csv)'de, D numarasıyla.

**Son yapılanlar (25–26 Ekim)**

- Repo sadeleşti, ölü kod silindi; davranış değişmedi (D119, D120, D124).
- Arama sürerken kaynak dahil etmek ya da dışlamak aramayı durdurmuyor (D127).
- Cevaplar kaynakları adıyla anıyor ve hükümle açılıyor; adlar kayıttan geliyor, modelden değil (D131).
- Tam metni okunan en yakın makaleler cevaba ve tabloya giriyor; okumada daha çok soru parçası bulan önce seçiliyor (D137, D144, D145).
- Denklemler Codex'le de okunuyor ve daha hızlı; daha çok denklem bulunuyor (D134, D136, D138, D139, D142).
- Tabloda her kaynağın okunma derinliği yazıyor; rapor kaynakları adıyla anıyor (D140, D143).
- Görsel kontrolden düzeltmeler: kendi özeti olmayan sürüm diğer sürümün özetini gösteriyor; "Add to chat" yalnız cevapta; birkaç ekran sadeleşti (D146, D147).

**Ne kadar biliyoruz**

- Sağlam: her atıf kodun pasajda bulduğu bir yere bağlı (8 cevapta 171 bağlantı, hepsi doğru).
- Ölçüldü, iyi: arama sırası, ilk 50'de düz OpenAlex'ten iyi (BioASQ 0,618, LitSearch 0,700).
- Ölçüldü, zayıf: EE survey seti (0,129); reranker orada zarar veriyor.
- Elicit'e karşı: anahtar makalelerin %83'ü bulundu, %60'ı atıf aldı (24 Ekim, son değişikliklerden önce).
- Ölçülmedi: son cevap değişikliklerinin kaliteye etkisi. İnsan puanı yok.
- Bilinen zayıflık: cevaplar 30 iddia sınırına takılıyor; paywall arkası okunamıyor; Windows ve Linux denenmedi.

## Sırayla yapılacaklar

1. **Görsel kontrol** (sahip): liste `notes/visual-check-2026-10-24.md`, 28 madde.
2. **P10, macOS paketi:** plan `notes/plans/p10-plan.md`; OpenAI, Gemini, DeepSeek fiyatları yayından önce doğrulanacak.
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
