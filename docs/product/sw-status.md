# SW uygulaması: ana dosya

SW1–SW16'nın ürüne işlenmesi bu dosyadan yürür. Her sohbet (plan, uygulama, inceleme) önce burayı okur: sırada ne var, hangi dilim dosyası ve hangi prompt kullanılacak, hangi karar bekliyor. Kararların kendisi [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md)'dedir; dilimlerin kapsamı, kabul koşulları ve tüm dilimler için geçerli kurallar [sw-implementation-plan.md](sw-implementation-plan.md)'dedir. Bu dosya yeni tasarım taşımaz; doğruluk kaynağı kod ve testlerdir.

## Bir tur

1. **Plan** (Fable, plan sohbeti): sıradaki dilimin dosyası ve promptu yazılır; satır `dosya hazır` olur.
2. **Uygulama** (yeni sohbet, Opus, efor medium): ilk ileti yalnızca `docs/product/sw-sliceNN-prompt.md dosyasını uygula.` olur. Sohbet commit yapmaz; satırını `uygulanıyor`, bitince `uygulandı, inceleme bekliyor` yapar ve açık kalanı yazar.
3. **İnceleme** (yeni sohbet, Fable): diff dilim dosyasına karşı okunur, testler koşulur, düzeltilir, commit ve `git push origin main` yapılır; satır `kapandı` olur, commit özeti ve `D` numarası yazılır.
4. **Ölç→Kur** dilimleri iki turdur: önce ölçüm ve sahibin "uygun" demesi, sonra ürün kodu.

Plan ve inceleme turları her dilimde Fable · high ile yapılır; tablodaki sütun yalnızca uygulayan sohbeti gösterir. **medium:** tasarımı dilim dosyasında bitmiş, mekanik işler. **high:** uygulayanın köşe durumlarında kendi yargısını kullanması gereken dilimler (karar kuralları, `selections` türetmesi, sürüm birleştirme, sözleşme + yöntem paketi + akışın birlikte değiştiği yerler). Ölçüm turları Fable'da koşar, çünkü protokolü dondurmak ve sonucu yorumlamak muhakeme işidir; uzun koşan ölçüm betiği arka plan ajanına (Sonnet) verilebilir. Bir dilimin son iletisinde "yazıldığı gibi yapılamayan yerler" listesi uzunsa sonraki benzer dilimin eforu bir kademe yükseltilir.

Durumlar: `plan` (yalnızca ana planda) · `dosya hazır` · `uygulanıyor` · `uygulandı, inceleme bekliyor` · `kapandı` · `ölçüm bekliyor` · `sahip kararı bekliyor`.

## Dilimler

| # | Dilim | Tür | Uygulayan model · efor | Durum | Dosya · prompt | Commit / D | Açık kalan |
|---|---|---|---|---|---|---|---|
| 01 | Protokol kaydı ve belirlenimcilik | Kur | Opus · medium | kapandı | [dilim](sw-slice01-protocol-and-determinism.md) · [prompt](sw-slice01-prompt.md) | `b09e9a9` + inceleme düzeltmesi · D70 | Protokol gövdesinin ölçüt/blok/sinyal alanları `None`; `attached` araştırmada protokol kaydı yok (sahip kararı); uygulama-geneli varsayılan gözden geçirici gövdeye çözülmüyor (`build_protocol` deposuz); `code_version` commit başına değişmiyor (dilim 24 öncesi); FTS eşitliği yalnızca ikinci anahtarla sabit, ölçülmedi; `search_workflow` yalnızca saklanıyor. Slice SQL'inden sapma: `protocol_records_no_delete` tetikleyicisine 0010'daki kalıcı-silme istisnası eklendi. |
| 02 | Aşama kararlarının saklanması | Kur | Opus · high | dosya hazır | [dilim](sw-slice02-stage-decisions.md) · [prompt](sw-slice02-prompt.md) | | |
| 03 | Kayıt türü ve sürüm birleştirme | Kur | Opus · high | plan | | | |
| 04 | Kodla sözcük dağarcığı ve kavram blokları | Ölç→Kur | Fable · high (ölçüm), Opus · high (kod) | plan | | | |
| 05 | Derleme işareti, eksik özet, sürüm bağlantıları | Kur | Opus · medium | plan | | | |
| 06 | Ölçüt, parçaları ve ipucu ifadeleri önerisi | Ölç→Kur | Fable · high (ölçüm), Opus · medium (kod) | ölçüm bekliyor (SW15.1 ikinci konuda genellemedi) | | | |
| 07 | Kayıt düzeyinde sıralama | Kur | Opus · high | plan | | | |
| 08 | Protokol onay adımı (arayüz) | Kur | Opus · medium | plan | | | |
| 09 | Özet taraması v2 | Kur | Opus · high | sahip kararı bekliyor (K3) | | | |
| 10 | Arka planda tam metin getirme | Kur | Opus · high | plan | | | |
| 11 | Ölçüt pasajları | Kur | Opus · medium | plan | | | |
| 12 | Tam metin kararı | Kur | Opus · high | plan | | | |
| 13 | Uçtan uca ara ölçüm | Ölç | Fable · high | plan | | | |
| 14 | Kaynak yönlendirme | Ölç→Kur | Fable · high (ölçüm), Opus · medium (kod) | sahip kararı bekliyor (K5) | | | |
| 15 | Atıf zinciri | Kur | Opus · high | plan | | | |
| 16 | İnsan kuyruğu (arka uç) | Kur | Opus · high | plan | | | |
| 17 | İnsan kuyruğu (arayüz) | Kur | Opus · medium | plan | | | |
| 18 | PDF bekleyenler ve kullanıcının eklediği PDF | Kur | Opus · medium | plan | | | |
| 19 | Prob seti, kol ve sinyal tabloları, durma kuralı | Kur | Opus · high | plan | | | |
| 20 | Akış sayıları, denetim örneği, ezme sayısı, PRISMA-S dışa aktarımı | Kur | Opus · medium | plan | | | |
| 21 | Yerleşik yerel gömme | Kur | Opus · medium | plan | | | |
| 22 | arXiv LaTeX kaynağından okuma | Ölç→Kur | Fable · high (ölçüm), Opus · high (kod) | plan | | | |
| 23 | Kullanıcının onayladığı kod kapısı | Kur (isteğe bağlı) | Opus · high | plan | | | |
| 24 | Varsayılanı değiştir ve kapat | | plan | Fable · high | | | |

## Sahip kararları

Öneriler ana planın §5'indedir.

| Karar | Konu | Durum |
|---|---|---|
| K1 | Eski ve yeni akışın birlikte yaşaması (araştırma başına bayrak) | kabul edildi, önerildiği gibi (2026-09-20); bayrak D70 ile geldi |
| K2 | Yeni aşama kararlarının `selections` ile ilişkisi | kabul edildi, önerildiği gibi (2026-09-20); dilim 02 uygular |
| K3 | Özet aşamasında model çağrı bütçesi | bekliyor |
| K4 | Ölçüm modeli (`deepseek-flash`, efor `high`) | bekliyor |
| K5 | Üçüncü konu (tıp ya da yaşam bilimi) | bekliyor |
