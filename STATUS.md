# DEIXIS durumu

Projenin genel durumu için tek kaynak bu dosya. Notion'daki "Plan durumu" sayfası bunun kopyası; ikisi her push'ta birlikte güncellenir. Ayrıntılı sayılar `docs/decisions.md` içindeki D kayıtlarında. ✅ bitti · 🟡 sürüyor · ❌ yapılmadı ya da ölçülmedi · ⏸ bekliyor.

**Son güncelleme:** 3 Ekim 2026 · Yeniden işleme R1 (D190) main'e hazır; P8 B2 (D182) ve P7 G1 B1 (D177) main'de

## Şu an çalışanlar

Kural (sahip, 3 Ekim): yazan ve inceleyen her zaman farklı şirketin modeli. Sol (gpt-6.1-sol) yazarsa Claude inceler, Claude yazarsa Sol inceler. Sahip onayı gereken kararlar Sol medium ile ortak verilir.

- ✅ **P7 G1 B3a** (D179): facade seçenek türünü, izinli değerleri ve yeniden deneme sayısını göndermeden denetliyor; 566 doğrudan/facade eşitlik vakası, 181 gönderim biçimi ve 88 yeniden deneme/zaman aşımı uyum testi (yeni takım 925 test); Sol yazdı, plan Sol medium 3 turda, kod Claude 1 turda hazır; 11.180 test geçti. Gönderim hâlâ registry üzerinden; B3b (sorgu yazımı) ayrı parti, sonra B4.
- ✅ **P7 G1 B2** (D178): sağlayıcı uyum test takımı (641 test, 566 sentetik vaka); anahtar sonradan silinirse istek sayılmıyor ve arama tablosu bozulmuyor; PubMed kota türü, bozuk 200 yanıtı, boş sayfa imleci, başlıkta anahtar ve geçersiz bekleme düzeltildi; Sol yazdı, Claude 2 turda hazır; 9.992 test geçti. Seçenek türü denetimi B3a'ya, kimliksiz kayıt kabulü B4'e kaldı.
- ✅ **P7 G1 B1** (D177): iç bağlayıcı sözleşmesi (`contract.py`), facade ve 111 sentetik uyumluluk vakası; çalışma akışı değişmedi; Sol yazdı, Claude 2 turda hazır dedi; 9.231 test geçti. Bulunan iki kusur (PubMed EFetch `error_kind` kaybı, S2/IEEE yanlış kökte çöküş) B2'ye yazıldı.
- 🟡 **P9 RR-B** (`../DEIXIS-rrb`): kod Sol, inceleme ve iki matris koşusu Claude.
- ✅ **P8 B1** (D181): inceleme sözleşmesi, anlık görüntü, tablolar, bayatlama kuralı; Sol yazdı, Claude 2 turda hazır dedi; 8.839 test geçti.
- ✅ **P7 G6–G8, G11, G12** (D173): kota ile hız sınırı ayrıldı, kotası biten sağlayıcıya koşu boyunca istek gitmiyor (devam ve yeniden denemede sıfırlanır); Sol yazdı, Claude 3 turda hazır.
- ✅ **P8 B2** (D182): inceleme koşusu ve rotaları; önizleme, başlatma, gruplu çalıştırma, bulgu kararları, kabul edilen bulgunun mevcut düzenleyiciyle uygulanması (kanıt değiştiyse 409); Sol yazdı, Claude 2 turda hazır; 8.963 test geçti. Gerçek modelle inceleme B4'te.
- ✅ **Yeniden işleme R1** (D190, göç 0066): bir metin çıkarımının kendi kimliği var; kurtarma denemesi eskisinin yanına yeni bir kayıt olarak yazılır, hangisinin geçerli olacağına test edilmiş tek bir kural karar verir; eski pasajlar ve atıflar değişmez. Henüz düğme ya da rota yok (R2a). Sol yazdı, plan Sol medium 4 turda, kod Claude 2 turda hazır; 9.614 test geçti.
- ✅ **Yeniden işleme R2a** (D191): bir kişi, başarısız ya da yarım kalmış bir metin çıkarımını uç nokta ya da CLI ile bir kez yeniden deneyebiliyor; dosyanın hash'i kontrol edilmiş özel bir kopyası, dosya başına kilit altında okunuyor; deneme sürerken o kaynağı tutan araştırmanın koşusu bekliyor. Kendiliğinden yeniden deneme yok; düğme R4'te, dosya onarım makbuzu R2b'de. Sol yazdı, plan Sol medium 4 turda, kod Claude 2 turda hazır; 9.781 test geçti.
- ✅ **Küçük kalanlar** (D175): dışa aktarma hatasının Türkçesi, slice 31 test eksikleri.
- ✅ **Onarılan dosyanın yeniden işlenmesi, tasarım** (D176); kodu R1–R5 partilerinde.
- ✅ **P7 G10 canlı deneme** (3 Ekim 02:48): IEEE, Scopus, CORE, SerpApi birer arama, hepsi HTTP 200.
- ✅ **P7 G1 eklenti sözleşmesi tasarımı** (D174) ve **H9 dondurma taslağı** main'de.

## Sıradaki

1. RR-B kapanır → P9'un modelsiz kısmı kapanır
2. P7 G1 eklenti sözleşmesi kodlaması (B1–B5)
3. H9: K01–K12 kararları Sol medium ile, sonra gerçek model rapor ölçümü (P19 ölçümü de içinde)
4. P8 B2–B8 ve G1 kodlaması (B1–B5), sırayla
5. Yeniden işleme R2b (dosya onarım makbuzu), sonra R2c–R5; H10

Hedef: P10'dan önceki her şey. Kaba tahmin 1–1,5 hafta; en büyük belirsizlik H9.

## Aşamalar

| Aşama | İçerik | Durum |
|---|---|---|
| P0–P2 | Plan, sözleşmeler, yerel temel, model bağlantısı | ✅ |
| P3 | Arama ve kaynak işleme | ✅ tek arama akışı (D119) |
| P4–P5 | İlk web dilimi, kütüphane, kanıt tablosu | ✅ |
| P6 | Sentez ve rapor | ✅ beş dilim kapandı; gerçek model ölçümleri P9'a borç |
| P7 | Bağlantı kapsamı | 🟡 D172, D173 kapandı; G10 canlı erişim gösterildi; G1 tasarımı D174, kodu sırada |
| P8 | Başka modelle inceleme, yayın takibi | 🟡 tasarım D180 + bölüm 15; ✅ B1 (D181), B2 (D182); sırada B3–B8 |
| P9 | Web sağlamlaştırma | 🟡 H0–H8, RR-A, H6 düzeltmeleri bitti; RR-B sürüyor; H9–H10 yok |
| P10 | macOS / Windows paketi | ❌ |

## Ölçülmemiş borçlar

- ❌ Gerçek modelle hiç rapor tamamlanmadı (P16, üç deneme: D124, D126, D128)
- ❌ Fikir zinciri gerçek korpusta ölçülmedi; keşif 99 işten 1'ini dahil etti (D141)
- ❌ Özgünlük araması K6 ölçümü (D154)
- ❌ Dilim 4 gerçek model raporla ölçüm (D157)
- 🟡 Bölüm IV alıntı çapası: hedefli onarım var, gerçek modelde ölçülmedi (D129)
- 🟡 Paralel yükte ara sıra düşen iki test; tek başına geçiyor
- ❌ `TODO.md`'de slice 13 ve 31'den devreden maddeler
