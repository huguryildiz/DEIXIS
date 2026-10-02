# DEIXIS durumu

Projenin genel durumu için tek kaynak bu dosya. Notion'daki "Plan durumu" sayfası bunun kopyası; ikisi her push'ta birlikte güncellenir. Ayrıntılı sayılar `docs/decisions.md` içindeki D kayıtlarında. ✅ bitti · 🟡 sürüyor · ❌ yapılmadı ya da ölçülmedi · ⏸ bekliyor.

**Son güncelleme:** 3 Ekim 2026 · main `8e4bb5d`

## Şu an çalışanlar

- 🟡 **P9 RR-B** (`../DEIXIS-rrb`, Sol high yazıyor): kapanış iddiası, düşen tarayıcı testi, yetim çocuk sürecin bellek sınırı. Bitince iki matris koşusu üst üste geçmeli.
- 🟡 **P8 B1** (`../DEIXIS-p8b1`, D181): görev metni Sol plan incelemesinde. 3. tur "düzeltmeyle hazır"; bulgular ve tasarım bölüm 15'in B1 maddeleri işleniyor, sonra 4. tur ve kodlama.
- Koordinatör: "DEIXIS koordinatör devamı" oturumu. Oturum kuralları `/tmp/deixis-coordination.md` içinde.

## Sıradaki

1. RR-B kapanır → P9'un modelsiz kısmı kapanır (birkaç saat)
2. P8 B1 kodlanır, sonra B2–B8 (3–5 gün)
3. H9–H10 gerçek model rapor ölçümü; en büyük risk, gerçek modelle hiç rapor tamamlanmadı (1–2 gün)
4. P7 kalan boşluklar (1 gün)
5. P10 paketleme (2–4 gün)

Toplam kaba tahmin: 1,5–2,5 hafta (belirsiz).

## Aşamalar

| Aşama | İçerik | Durum |
|---|---|---|
| P0–P2 | Plan, sözleşmeler, yerel temel, model bağlantısı | ✅ |
| P3 | Arama ve kaynak işleme | ✅ tek arama akışı (D119) |
| P4–P5 | İlk web dilimi, kütüphane, kanıt tablosu | ✅ |
| P6 | Sentez ve rapor | ✅ beş dilim kapandı; gerçek model ölçümleri P9'a borç |
| P7 | Bağlantı kapsamı | 🟡 4 boşluk kapandı (D172); eklenti sözleşmesi yok, canlı anahtarla ölçülmedi |
| P8 | Başka modelle inceleme, yayın takibi | 🟡 tasarım D180 + bölüm 15; B1 sürüyor; B5 P7'yi bekliyor |
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
