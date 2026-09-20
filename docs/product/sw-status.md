# SW uygulaması: ana dosya

SW1–SW16'nın ürüne işlenmesi bu dosyadan yürür. Her sohbet (plan, uygulama, inceleme) önce burayı okur: sırada ne var, hangi dilim dosyası ve hangi prompt kullanılacak, hangi karar bekliyor. Kararların kendisi [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md)'dedir; dilimlerin kapsamı, kabul koşulları ve tüm dilimler için geçerli kurallar [sw-implementation-plan.md](sw-implementation-plan.md)'dedir. Bu dosya yeni tasarım taşımaz; doğruluk kaynağı kod ve testlerdir.

## Bir tur

1. **Plan** (Fable, plan sohbeti): sıradaki dilimin dosyası ve promptu yazılır; satır `dosya hazır` olur.
2. **Uygulama** (yeni sohbet, Opus, efor medium): ilk ileti yalnızca `docs/product/sw-sliceNN-prompt.md dosyasını uygula.` olur. Satırını `uygulanıyor` yapar; iş bitip testler yeşil olunca satırı `uygulandı, inceleme bekliyor` yapar, açık kalanı yazar, tek commit olarak işler ve `main`'e iter. Yarım kalan iş commit'lenmez.
3. **İnceleme** (yeni sohbet, Fable): uygulayan sohbetin commit'i dilim dosyasına karşı okunur, testler koşulur, bulgular ayrı bir düzeltme commit'iyle işlenir ve itilir; satır `kapandı` olur, commit özeti ve `D` numarası yazılır.
4. **Ölçüm en sonda, toplu yapılır** (dilim 24: kuantum yeniden, yeni bir soru, Elicit raporlarıyla karşılaştırma). Dilimler ölçüm için durmaz; ölçülmemiş parça "ölçülmedi" diye kaydedilir. İstisnalar: dilim 06'nın bilinen kusuru ve dilim 13'ün duman testi.

Plan ve inceleme turları her dilimde Fable · high ile yapılır; tablodaki sütun yalnızca uygulayan sohbeti gösterir. **medium:** tasarımı dilim dosyasında bitmiş, mekanik işler. **high:** uygulayanın köşe durumlarında kendi yargısını kullanması gereken dilimler (karar kuralları, `selections` türetmesi, sürüm birleştirme, sözleşme + yöntem paketi + akışın birlikte değiştiği yerler). Duman testi ve ölçüm kampanyası Fable'da koşar, çünkü protokolü dondurmak ve sonucu yorumlamak muhakeme işidir; uzun koşan ölçüm betiği arka plan ajanına (Sonnet) verilebilir. Bir dilimin son iletisinde "yazıldığı gibi yapılamayan yerler" listesi uzunsa sonraki benzer dilimin eforu bir kademe yükseltilir.

Durumlar: `plan` (yalnızca ana planda) · `dosya hazır` · `uygulanıyor` · `uygulandı, inceleme bekliyor` · `kapandı` · `sahip kararı bekliyor`.

## Dilimler

| # | Dilim | Tür | Uygulayan model · efor | Durum | Dosya · prompt | Commit / D | Açık kalan |
|---|---|---|---|---|---|---|---|
| 01 | Protokol kaydı ve belirlenimcilik | Kur | Opus · medium | kapandı | [dilim](sw-slice01-protocol-and-determinism.md) · [prompt](sw-slice01-prompt.md) | `b09e9a9` + inceleme düzeltmesi · D70 | Protokol gövdesinin ölçüt/blok/sinyal alanları `None`; `attached` araştırmada protokol kaydı yok (sahip kararı); uygulama-geneli varsayılan gözden geçirici gövdeye çözülmüyor (`build_protocol` deposuz); `code_version` commit başına değişmiyor (dilim 24 öncesi); FTS eşitliği yalnızca ikinci anahtarla sabit, ölçülmedi; `search_workflow` yalnızca saklanıyor. Slice SQL'inden sapma: `protocol_records_no_delete` tetikleyicisine 0010'daki kalıcı-silme istisnası eklendi. |
| 02 | Aşama kararlarının saklanması | Kur | Opus · high | kapandı | [dilim](sw-slice02-stage-decisions.md) · [prompt](sw-slice02-prompt.md) | `081a566` + inceleme düzeltmesi · D71 | Hiçbir akış adımı bu tabloları yazmıyor (yazanlar dilim 05, 07, 09, 12, 16); neden kodları yalnızca SW11'in çalışma adları, derleme işareti / kod kapısı / K3 bütçe kodları yok; `criterion_not_met` `selections`'ta `excluded` görünüyor, ayrımı hiçbir görünüm göstermiyor; sürümler çeliştiğinde iş `pending` kalıyor ve hiçbir yerde gösterilmiyor; `apps/web/src/api.ts` `origin` tipi `code_rule`'u tanımıyor, ilk yazan dilimde genişletilmeli; SW9.5 konu özellikleri ve geniş dışa aktarım yapılmadı. Slice'tan sapma: `purge_sources` (D65), kaynak düzeyinde yetki tablosu olmadığı için karar silme tetikleyicisini araştırma purge yetkisiyle açıyor. İncelemede düzeltildi: `undo_human` geri getirdiği karara güncel revizyonu damgalıyordu (eskimiş karar taze görünüyordu); `work_outcome` aynı sonuçlu sürümlerden ilk yazılanı adlandırıyordu, şimdi işin başı, yoksa en küçük kimlik. Yoruma açık nokta: insan kararı en yenisi alınırken eşit zaman damgasında yazma sırası belirliyor. |
| 03 | Kayıt türü ve sürüm birleştirme | Kur | Opus · high | plan | | | |
| 04 | Kodla sözcük dağarcığı ve kavram blokları | Kur (ölçülmedi) | Opus · high | plan | | | |
| 05 | Derleme işareti, eksik özet, sürüm bağlantıları | Kur | Opus · medium | plan | | | |
| 06 | Ölçüt, parçaları ve ipucu ifadeleri önerisi | Kur (ölçülmedi) | Fable · high (istem düzeltmesi), Opus · medium (kod) | plan (önce SW15.1 kusuru düzeltilir) | | | |
| 07 | Kayıt düzeyinde sıralama | Kur | Opus · high | plan | | | |
| 08 | Protokol onay adımı (arayüz) | Kur | Opus · medium | plan | | | |
| 09 | Özet taraması v2 | Kur | Opus · high | sahip kararı bekliyor (K3) | | | |
| 10 | Arka planda tam metin getirme | Kur | Opus · high | plan | | | |
| 11 | Ölçüt pasajları | Kur | Opus · medium | plan | | | |
| 12 | Tam metin kararı | Kur | Opus · high | plan | | | |
| 13 | Uçtan uca duman testi | Duman | Fable · high | plan | | | |
| 14 | Kaynak yönlendirme | Kur (ölçülmedi) | Opus · medium | plan | | | |
| 15 | Atıf zinciri | Kur | Opus · high | plan | | | |
| 16 | İnsan kuyruğu (arka uç) | Kur | Opus · high | plan | | | |
| 17 | İnsan kuyruğu (arayüz) | Kur | Opus · medium | plan | | | |
| 18 | PDF bekleyenler ve kullanıcının eklediği PDF | Kur | Opus · medium | plan | | | |
| 19 | Prob seti, kol ve sinyal tabloları, durma kuralı | Kur | Opus · high | plan | | | |
| 20 | Akış sayıları, denetim örneği, ezme sayısı, PRISMA-S dışa aktarımı | Kur | Opus · medium | plan | | | |
| 21 | Yerleşik yerel gömme | Kur | Opus · medium | plan | | | |
| 22 | arXiv LaTeX kaynağından okuma | Kur (ölçülmedi) | Opus · high | plan | | | |
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
| K5 | Kampanyanın yeni sorusu (öneri: tıp ya da yaşam bilimi) | dilim 24'te sahip seçer |
