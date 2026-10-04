# DEIXIS durumu

**Son güncelleme:** 4 Ekim 2026.

## Şu an

**P9 kapandı, P10’a hazır** ([D218](docs/decisions.md#d218--p9-exit)). Son matris çifti `0af3216` üzerinde iki kez geçti: pytest 14.265 toplandı, 0 başarısız, 23 atlandı; süreç 45/45; tarayıcı 212/212. Bu, tek macOS arm64 makinede sentetik kayıt ve betikli model kanıtıdır; kapasite satırları paralel yük altında koştu. H9e ilk kabul edilen gerçek model raporunu tamamladı; kalite koşullarının çoğu aralık dışında. D217 ölçüm kümesini kapattı, bütün borçları kapatmadı.

Kural (sahip, 3 Ekim): yazan ve inceleyen farklı şirketin modeli; Sol yazarsa Claude, Claude yazarsa Sol inceler. Sahip adına kararlar Sol medium ile ortak verilir.

## Sıradaki

1. P10: macOS paketi. Rapor kalitesi çalışması (kanıt kesilmesi, çok parçalı iddialar) isteğe bağlı ve sahip kararıyla.

## Açık işler

Bütün eksikler burada; ayrı TODO dosyası yok. Parantezdeki D numaraları [karar kaydına](docs/decisions.md) gider.

### Ölçülmedi (gerçek model veya gerçek kullanım gerekiyor)

- Rapor kalitesi: H9e'de R1a, R2, R4b, R5, R7 süre, R8, R11 aralık dışında. R2'de 4 yanlış atıf, 18 kısmi destek; iki model okudu, insan bakmadı. (D202, D218)
- Denklem, çift ve inceleme: R6'da denklem birimi yok, R9'un yedi çifti ölçülemedi, R10 hiç ölçülmedi. (D202, D218)
- Rapor düzenleme E06–E18: 18 işlemden 5'i ölçüldü; kabul, kaldırma, geri yükleme, dışa aktarım, yedek/geri yükleme sınanmadı. (D215, D217)
- Soy zinciri L9 (R12–R15): hiçbir korpusta ölçülmedi; yeniden hazırlanmayacak. (D216, D217)
- Kill-search K6/S2: S2 paydası sıfır, en yakın işler hiç bulunmadı; sorgu biçiminin suçlu olduğu gösterilmedi. (D212)
- Çöküş kurtarma H10: gerçek Codex ile hiç koşulmadı; tekrar çağrı ve fatura bilinmiyor. (D218)
- Günlük kullanım: sahibin yedi günlük kullanım günlüğü yok; H7 bulguları test ve kod okumasından. (D165)
- Planted prior-art ölçümü: yayımlanmış bir makalenin fikrini aday diye ver, kill-search onu bulup `closed` diyor mu bak. Bu koşulana kadar "Novelty Checker'dan iyi" yalnız tasarım iddiası.

### Ortam ve platform

- İkinci kullanıcı kurulumu (temiz hesap, başka makine, proxy) ölçülmedi. (D161, D168)
- Erişilebilirlik: VoiceOver ve diğer ekran okuyucular, okuma sırası, yüzde 400 yakınlaştırma ölçülmedi. (D167)
- Kapasite: sessiz makinede tekrar, gerçek PDF karışımı, canlı model gecikmesi, yük altında eş zamanlılık yok; H8 K02c N=100 eksik. (D166, D170)
- Hata sınırları: elektrik kesintisi, kernel panic, APFS disk dolu ölçülmedi; OCR/JATS çocuk süreç sınırları sürüyor. (D159, D162, D164)
- Platform: eski macOS, Intel, Linux, Windows desteklenmiyor; başka makineye geri yükleme ölçülmedi. P10'da ele alınacak.

### Kod düzeltmeleri

- `tests/hardening/test_capacity_script.py` içinde iki test kırık (4 Ekim'de görüldü, değişiklikten bağımsız).
- K03 sürücüsü: kuyruk geçişi prompt boyutunda düşüyor; bayt bütçesi eklenmedi. Paketleme engeli sayılmadı. (D216, D217)
- Yeniden çıkarım R5: T10 arka plan okuyucuyu (D52) yürütmüyor; aday/soy güncellik görünümü ve Türkçe Zotero notları; görüntüleyici kilidi veya önbellek geçersizleştirme. (D208)
- İlk cevap taslağı atıf çapası kurallarını hep bozuyor (9/9); onarım turu düzeltiyor ama cevap başına 46–134 s ekliyor. Nedeni bulunmadı.
- arXiv hiç kayıt döndürmüyor (üç ölçümde sıfır, hep `rate_limited`); nedeni bilinmiyor. Durumu 23 Eylül'den beri yeniden kontrol edilmedi.
- `sw` araştırmada kaynak eklenene kadar kısa başlık yok (`_research_title`, D39); sorudan mı başlık üretilsin, karar bekliyor. (D119)
- Protokol kaydı derlenen sorguları arama bitmeden donduruyor; iptal edilen koşu hiç gönderilmeyen sorguyu kayıtta tutuyor.
- Scopus özet okuması DOI başına bir istek atıyor; `DOI(a) OR DOI(b)` ile 25'lik gruplar istek sayısını ~25 kat azaltabilir (`COMPLETE` görünümüyle denenmedi).
- `detailed` süre: tam metin alma ve okuma tek başına 20 dakika hedefini aşıyor (23 Eylül ölçümü).
- Test borcu: dilim 31'den kalan uçtan uca iddialar tam karşılanmadı; aralıklı paralel test hataları; CI yok. (D119, D175)
- PDF indirici `User-Agent`'ında iletişim adresi yok, `Accept: application/pdf` gönderilmiyor.

### Ertelenmiş fikirler (sahip kararı bekler)

- Örnek sorular: soru kutusunun altında yalnız kutuyu dolduran 2–3 tıklanabilir örnek.
- Kütüphaneden süreklilik: "bu kaynak X araştırmasına dahil edilmişti" gibi veritabanından hesaplanan ipuçları. Sohbet tarzı gizli "bellek" planlanmıyor.
- PDF indirme teşhisi: HTML veya 403 dönen en fazla 20 açık erişim vakasını düz Chromium ile aç, nedeni sınıflandır (`citation_pdf_url`, JavaScript, çerez duvarı, bot engeli). Bot engelini aşmak planlanmıyor.
- Sorgu örtüşme uyarısı: iki sorgunun terimleri büyük ölçüde örtüşüyorsa uyarı (onarım değil).
- Kill-search: aday kartındaki iddia öğelerini RRF'de ayrı sinyal olarak kullanmak; Semantic Scholar snippet search'ü dördüncü yol olarak eklemek; `answer_review`'u geliştirirken kullanılmayan bir modelle değerlendirmek.
