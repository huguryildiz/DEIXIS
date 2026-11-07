# DEIXIS durumu

**Son güncelleme:** 7 Kasım 2026. Kararlar [docs/decisions.csv](docs/decisions.csv), ölçümler [docs/benchmark.md](docs/benchmark.md). Ayrıntılı eski hali Git geçmişinde (commit 33308dd9).

## Neredeyiz?

Uygulama çalışıyor ve masaüstü uygulaması olarak kuruluyor. Son haftalarda eklenenlerin çoğu gerçek kullanımda denenmedi.

- **Masaüstü paketi (P10):** Mac (Apple Silicon), Windows ve Linux paketleri hazır. GitHub'daki son ön sürüm [`v0.1.1`](https://github.com/huguryildiz/DEIXIS/releases/tag/v0.1.1) (Mac + Windows). Kodda sürüm 0.1.2 (Linux paketleri, Tesseract kurmadan OCR, temaya uyan pencere, yeni sürüm uyarısı), ama henüz GitHub'da yayımlanmadı.
- **Kurulu uygulama testleri:** Mac 17/17, Windows sanal makinede 12/12, Linux GitHub'ın Ubuntu 22.04 ve 24.04 makinelerinde 23/23 geçti. Windows 10, gerçek bir x64 PC ve gerçek bir Linux masaüstü denenmedi. Windows'ta yerleşik yerel modeller ve arXiv kaynak okuma yok.
- **Tanıtım sitesi:** [deixis-app.vercel.app](https://deixis-app.vercel.app), içinde arayüzün kayıtlı, salt okunur bir demosu var (D162).
- **Cevap kalitesi:** 6 Kasım'daki ilk ölçümde 128 iddianın %93'ü pasajıyla tam destekleniyordu. Asıl sorun kanıtın cevaba ulaşmadan kaybolması: referans makalelerin çoğu sıralamada ilk 50'nin dışında kalıyor. Bunun için yapılan düzeltmeler (D152–D156) ölçümde kazanç göstermedi, zarar da göstermedi.
- **Yeni ölçüm yöntemi (D163):** sahip 30 soru yazacak, her soru için cevapta bulunması gereken 3–4 nokta. Üç iyileştirme sırayla denenecek; ilki kodlandı ama kapalı duruyor (D164). Ölçüm sorular hazır olunca başlayacak.
- Türkçe soru artık durmuyor: model soruyu İngilizceye çeviriyor, arama o cümleyle yapılıyor (D149). Arama kalitesine etkisi ölçülmedi.

## Ne kadar biliyoruz

- **Sağlam:** her atıf kodun pasajda bulduğu bir yere bağlı (8 cevapta 171 bağlantı, hepsi doğru).
- **Ölçüldü, iyi:** arama sırası ilk 50'de düz OpenAlex'ten iyi (BioASQ 0,618, LitSearch 0,700).
- **Ölçüldü, zayıf:** EE survey seti (0,129); reranker orada zarar veriyor.
- **Elicit'e karşı:** anahtar makalelerin %83'ü bulundu, %60'ı atıf aldı (24 Ekim, son değişikliklerden önce).
- **Ölçülmedi:** son cevap değişikliklerinin etkisi. İnsan puanı yok.

## Sırada

1. **Sahibin 30 sorusu** (`notes/2026-11-07-eval-questions/`), sonra D163 ölçümü.
2. **Sürüm 0.1.2'yi yayımlamak** (sahip kararı), ardından ilk aday sürüm ve sürümden sürüme yükseltme testi (M4). Yayından önce OpenAI, Gemini, DeepSeek fiyatları doğrulanacak. Intel Mac sonra.
3. **Görsel kontrol** (sahip, paralel): `notes/visual-check-2026-10-24.md`, 28 madde.
4. **Reranker ayarını gerçek koşuyla doğrulamak** (D106): ~12 USD OpenAlex + 1–3 USD Voyage. Bitmeden reranker değişmesin.
5. **Yeni özellik yok:** gap finder, Chain of Ideas, R5 bunlar bitene kadar bekler.

## Açık işler

- **Arama:** geniş sorularda ana makaleler ilk 50'ye girmiyor (DBR/VBF en zayıf); sorgu başına 500 kayıt sınırı; ücretsiz OpenAlex kotası ~20 araştırmada bitiyor; ULAKBİM ağından bazı yayıncı PDF'leri 403 veriyor. Kill search ve kartopunda doğru makale havuzda ama okunan ilk 8 / ilk 80'in dışında; ilk denenecek: sürümleri birleştirmek, sonra kesimden önce rerank (`notes/2026-10-results.md`, "Live pilots").
- **Cevap:** cevaplar 30 iddia sınırına takılıyor; paywall arkası okunamıyor; indirilen PDF başka sürümse ve okunamazsa eser cevaptan düşüyor (`answer.py::cutoff_snapshot`); `review_mode: "off"` iken answer_review çalıştı (bakılmadı).
- **Ters atıf arama:** destekleyicilerin çoğu "yeterince gösterilmedi"de kalıyor; tam metinle kontrol yok; R5 "karşı çıkıyor" bloklu.
- **Atıf kontrolü (P25):** tablo satırının ilk sütunundaki yazar adları ayrı bir iddia gibi kontrol ediliyor, satır yanlışlıkla "kısmen bulundu" çıkıyor.
- **Yazar adı ekleri:** "van Leent" kısa atıfta "Leent" oluyor.
- **Rapor değerlendirme:** 5 raporun 1–5 puanlanması yapılmadı; raporlar silindi.
- **Sadeleşme, kalan 6 iş** (davranış değişmez, acele yok; plan `notes/2026-10-results.md`, "Simplification review"): ortak test yardımcıları, tekrarlanan 6 yardımcıyı tek kopyaya indirmek, model bağlantılarında ortak sağlık önbelleği, `app.py`'den sahip incelemesi route'ları, `api.ts` ve `Connections.tsx`'i bölmek, `web/src/research/` alt klasörleri.
- **Test ve platform:** paralel testler yük altında ara sıra düşüyor; hızlı akışın duraklat/sürdür testi yok; Windows PDF alt sürecinde bellek sınırı yok; Mac'te menü çubuğu menüsü ve yerel model sunucusu kapanışı elle kontrol edilecek.
- **Sahibin kararını bekleyen:** ana sayfada örnek sorular, 403 sınıflaması.
