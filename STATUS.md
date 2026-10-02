# DEIXIS durumu

Projenin genel durumu için tek kaynak bu dosya. Notion'daki "Plan durumu" sayfası bunun kopyası; ikisi her push'ta birlikte güncellenir. Ayrıntılı sayılar `docs/decisions.md` içindeki D kayıtlarında. ✅ bitti · 🟡 sürüyor · ❌ yapılmadı ya da ölçülmedi · ⏸ bekliyor.

**Son güncelleme:** 3 Ekim 2026 03:20 · main'e D174 ve H9 taslağı girdi

## Şu an çalışanlar

Kural (sahip, 3 Ekim): yazan ve inceleyen her zaman farklı şirketin modeli. Sol (gpt-6.1-sol) yazarsa Claude inceler, Claude yazarsa Sol inceler. Sahip onayı gereken kararlar Sol medium ile ortak verilir.

- 🟡 **P9 RR-B** (`../DEIXIS-rrb`): kod Sol, inceleme ve iki matris koşusu Claude.
- 🟡 **P8 B1** (`../DEIXIS-p8b1`, D181): kod Sol high, Claude incelemesi sürüyor.
- 🟡 **P7 G6–G8, G11, G12** (`../DEIXIS-p7g`, D173): Claude 1. tur "düzeltmeyle hazır"; Sol düzeltiyor, G8'in koşu boyu kota korumasını da ekliyor.
- 🟡 **Küçük kalanlar** (`../DEIXIS-leftovers`, D175): dışa aktarma hatasının Türkçesi, slice 31 test eksikleri; Sol medium.
- 🟡 **Onarılan dosyanın yeniden işlenmesi, tasarım** (`../DEIXIS-reextract`): Claude 1. tur "düzeltmeyle hazır", Sol düzeltiyor.
- ✅ **P7 G10 canlı deneme** (3 Ekim 02:48): IEEE, Scopus, CORE, SerpApi birer arama, hepsi HTTP 200.
- ✅ **P7 G1 eklenti sözleşmesi tasarımı** (D174) ve **H9 dondurma taslağı** main'de.

## Sıradaki

1. RR-B kapanır → P9'un modelsiz kısmı kapanır
2. B1, P7 boşlukları ve küçük kalanlar push edilir
3. H9: K01–K12 kararları Sol medium ile, sonra gerçek model rapor ölçümü (P19 ölçümü de içinde)
4. P8 B2–B8 ve G1 kodlaması (B1–B5), sırayla
5. Yeniden işleme kodu (B1'den sonra), H10

Hedef: P10'dan önceki her şey. Kaba tahmin 1–1,5 hafta; en büyük belirsizlik H9.

## Aşamalar

| Aşama | İçerik | Durum |
|---|---|---|
| P0–P2 | Plan, sözleşmeler, yerel temel, model bağlantısı | ✅ |
| P3 | Arama ve kaynak işleme | ✅ tek arama akışı (D119) |
| P4–P5 | İlk web dilimi, kütüphane, kanıt tablosu | ✅ |
| P6 | Sentez ve rapor | ✅ beş dilim kapandı; gerçek model ölçümleri P9'a borç |
| P7 | Bağlantı kapsamı | 🟡 D172 kapandı; G10 canlı erişim gösterildi; G1 tasarımı D174; G6–G8, G11, G12 sürüyor |
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
