# DEIXIS durumu

**Son güncelleme:** 25 Ekim 2026. Kararlar [docs/decisions.csv](docs/decisions.csv), ölçümler [docs/benchmark.md](docs/benchmark.md). Bu dosyanın uzun hali Git geçmişinde (25 Ekim öncesi: commit 88155c1e).

## Neredeyiz?

Uygulama çalışıyor ve özellik bakımından geniş. Asıl eksik: son haftalarda eklenen özelliklerin çoğu gerçek modelle ve gerçek kullanımda denenmedi. Sıradaki iş yeni özellik değil; görsel kontrol, sonra macOS paketi (P10).

- **25 Ekim:** repo sadeleşti (klasör düzeni, davranış değişmedi; D119, D120, D124). Testler ~1.500 durum, Playwright 5 spec, tek komut ~2 dk.
- **Sağlam:** atıf kuralı. Her atıf, kodun pasajda bulduğu bir yere bağlı; 8 cevaptaki 171 atıf bağlantısının hepsi doğru.
- **Ölçülmüş, iyi:** arama sırası. İlk 50'de düz OpenAlex'ten belirgin iyi (BioASQ 0,618 / 0,489; LitSearch 0,700 / 0,561).
- **Ölçülmüş, zayıf:** EE survey seti (0,129 / 0,065) ve reranker orada zarar veriyor; D106 kaybın yarısını kapattı, yalnız kayıtlı koşularla, yeni koşu yok.
- **Bir kez canlı denenen:** Verify Citations (V5), ters atıf arama (R4b, D116), denklem okuma (D118), run kartı. Kill search ve kartopu çalışıyor ama aranan makaleyi çoğu zaman kaçırıyor.
- **Bilinen zayıflık:** cevaplar 30 iddia sınırına takılıyor; paywall arkasındaki tam metinler okunamıyor; Windows ve Linux hiç denenmedi.

## Sırayla yapılacaklar

1. **Görsel kontrol** (sahip): liste `notes/visual-check-2026-10-24.md`, 29 madde.
2. **P10, macOS paketi:** plan `notes/plans/p10-plan.md`; OpenAI, Gemini, DeepSeek fiyatları yayından önce doğrulanacak.
3. **D106'yı gerçek koşuyla doğrula** (BioASQ, LitSearch, EE survey): ~12 USD OpenAlex + 1–3 USD Voyage, ön ödemeli bakiye ister. Bu bitmeden reranker ayarı değişmesin.
4. **Kill search ve kartopu kesimi:** doğru makale havuzda ama okunan ilk 8 / ilk 80'in dışında. İlk denenecek: aynı makalenin sürümlerini birleştirmek, sonra kesimden önce rerank. Ayrıntı `notes/2026-10-24-live-pilots/RESULT.md`.
5. **Yeni özellik duraklaması:** gap finder, Chain of Ideas, R5 bunlar bitene kadar bekler.

## Açık işler

- **Arama:** geniş sorularda ana makaleler ilk 50'ye girmiyor (DBR/VBF en zayıf); sorgu başına 500 kayıt sınırı; ücretsiz OpenAlex kotası ~20 araştırmada bitiyor; ULAKBİM ağından bazı yayıncı PDF'leri 403.
- **Cevap:** özeti geçen bir eser, indirilen PDF başka sürümse ve okunamazsa cevaptan düşüyor (`answer.py::cutoff_snapshot`, düzeltilmedi); `review_mode: "off"` iken answer_review çalıştı (bakılmadı); rapor kalitesine sahip puanı yok.
- **Ters atıf arama:** ihtiyatlı kural destekleyicilerin çoğunu "yeterince gösterilmedi"de bırakıyor; tam metinle kontrol yok; R5 "karşı çıkıyor" bloklu.
- **Elicit karşılaştırması:** anahtar makalelerin %83'ü bulundu, %60'ı atıf aldı; insan okuması yok (`notes/2026-10-24-elicit-compare/RESULT.md`).
- **Test ve platform:** paralel testler yük altında ara sıra düşüyor; hızlı akışın duraklat/sürdür testi yok; Windows PDF alt sürecinde bellek sınırı yok (P10).
- **Sahibin kararını bekleyen:** ana sayfada örnek sorular, 403 sınıflaması, P10 sonrası açılış sayfası.
