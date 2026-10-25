# DEIXIS durumu

**Son güncelleme:** 26 Ekim 2026. Kararlar [docs/decisions.csv](docs/decisions.csv), ölçümler [docs/benchmark.md](docs/benchmark.md). Bu dosyanın uzun hali Git geçmişinde (25 Ekim öncesi: commit 88155c1e).

## Neredeyiz?

Uygulama çalışıyor ve özellik bakımından geniş. Asıl eksik: son haftalarda eklenen özelliklerin çoğu gerçek modelle ve gerçek kullanımda denenmedi. Sıradaki iş yeni özellik değil; görsel kontrol, sonra macOS paketi (P10).

- **25 Ekim:** repo sadeleşti (klasör düzeni, davranış değişmedi; D119, D120, D124). Testler ~1.500 durum, Playwright 5 spec, tek komut ~2 dk. Aynı gün Astra ve Argon'un üç turluk ortak incelemesiyle ölü kod ve kopyalar temizlendi (davranış değişmedi); hiçbir yerden çağrılmayan iki API yolu (Ollama gömme modeli indirme, kütüphane PDF'i) kaldırıldı; 6–7 Ekim ölçüm betikleri kalıyor (sahip kararı); sonraya kalan 11 sadeleşme işinde Astra ve Argon üç turda anlaştı: 9'u yapılacak, 2'si düşürüldü (`notes/2026-10-results.md`, "Simplification review" bölümü). İlk üçü yapıldı: `store.py`'de 3 ölü metot, 5 ölü çeviri anahtarı, testlerde ölü yardımcılar ve çift importlar (davranış değişmedi).
- **25 Ekim, görsel kontrolden:** arama sürerken bir kaynağı dahil etmek ya da dışlamak artık aramayı durdurmuyor; arama devam ediyor ve kararının üstüne yazmıyor; kuyrukta verilen bir karardan sonra o kaynak modele de gönderilmiyor (D127; cevap yazımı sırasında seçim değişirse cevap yine duruyor). Çalışma göstergesi geniş ekranda sol kenar çubuğunda, erişim kartının üstünde (D128). Gerçek bir aramada denenmedi, yalnız testlerle.
- **26 Ekim, cevap yazımı (D131):** cevaplar artık kaynakları adıyla anıyor; yazar, yıl ve başlık modelden değil kayıttan geliyor (model yalnız kaynak işareti yazıyor, kendi yazdığı yazar adı ya da başlık reddediliyor). Cevap talimatı Elicit'in 20 cevabındaki düzene göre yeniden yazıldı: önce hüküm, yakın kaynak başına bir paragraf, "özete göre" gibi süreç sözleri metinde yok. Heralded ve sualtı hub sorularında aynı kanıtla yeniden yazılan cevaplar her kaynağı adıyla anıyor ve hükümle açılıyor (`notes/test-questions/*/deixis-answer-2026-10-26-d131.md`); insan puanlaması yok, eksik kaynaklar (Humphreys, Mitrolaris, Iñesta) kanıt sorunu olarak duruyor.
- **Sağlam:** atıf kuralı. Her atıf, kodun pasajda bulduğu bir yere bağlı; 8 cevaptaki 171 atıf bağlantısının hepsi doğru.
- **Ölçülmüş, iyi:** arama sırası. İlk 50'de düz OpenAlex'ten belirgin iyi (BioASQ 0,618 / 0,489; LitSearch 0,700 / 0,561).
- **Ölçülmüş, zayıf:** EE survey seti (0,129 / 0,065) ve reranker orada zarar veriyor; D106 kaybın yarısını kapattı, yalnız kayıtlı koşularla, yeni koşu yok.
- **Elicit karşılaştırması:** anahtar makalelerin %83'ü bulundu, %60'ı atıf aldı; insan okuması yok (24 Ekim, 5 soru × 2 koşu; Elicit çıktıları `notes/test-questions/`).
- **Bir kez canlı denenen:** Verify Citations (V5), ters atıf arama (R4b, D116), denklem okuma (D118), run kartı. Kill search ve kartopu çalışıyor ama aranan makaleyi çoğu zaman kaçırıyor.
- **Bilinen zayıflık:** cevaplar 30 iddia sınırına takılıyor; paywall arkasındaki tam metinler okunamıyor; Windows ve Linux hiç denenmedi.

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
