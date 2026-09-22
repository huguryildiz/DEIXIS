# SW ölçüm adımı (13ö) — D88 ölçümü, sonuç (22 Eylül 2026)

**Tarih:** 22 Eylül 2026. **Durum:** koşuldu. **Ana dosya:** [sw-status.md](sw-status.md). **Karar:** D88. **Koşan:** Opus (kampanya betiği `.local/sw-measure-2026-09-22/campaign.py`, izlenmez). **Ham veri:** `.local/sw-measure-2026-09-22/` (dondurulmuş beklentiler `protocol.md`, `protocol-luna.md`; efor başına ayrı `DEIXIS_DATA_DIR`), izlenmez. Bu dosya o klasördeki `result.md`'nin kopyasıdır; arXiv bulgusu incelemeden sonra düzeltildi.

Dondurulmuş beklentiler: `protocol.md` (DeepSeek kampanyası), `protocol-luna.md` (Luna kampanyası). Depo commit'i `7df0102`, `skill_package_hash` `sha256:b35b4f49…`, gömme `off`, protokol önerisi her koşuda olduğu gibi onaylandı, eforlar art arda koştu.

## Süreler

Luna kampanyası (`codex` / `gpt-5.6-luna` · medium), araştırmanın kurulmasından yanıt koşusunun bitmesine:

| efor | hedef | ölçülen | kayıt | ayrı çalışma | `included` (kod) | indirilen PDF | okuma çağrısı |
|---|---|---|---|---|---|---|---|
| `quick` | 5 dk | **12,1 dk** | 1.027 | 956 | 7 | 19 | 36 |
| `standard` | 10 dk | **29,9 dk** | 5.207 | 4.999 | 9 | 37 | 64 |
| `detailed` | 15 dk | **55,5 dk** (kısmi) | 6.301 | 6.115 | 16 | 58 | 119 / 300 |

Üç koşuda da yanıt `structurally_valid` çıktı. `detailed` kısmi: okuma aşaması 119. çağrıda `model_call_failed` ile duraklattı (aşağıda).

DeepSeek kampanyası (`deepseek-flash` · high): `quick` **16,5 dk** (851 kayıt, 779 çalışma, 8 `included`, 21 PDF, 40 okuma çağrısı, yanıt `structurally_valid`). `standard` bakiye bitince geçersiz (`HTTP 402 Insufficient Balance`); `detailed` koşmadı. **İki kampanyanın süreleri birbiriyle karşılaştırılmaz**, modeller farklı.

## Zaman nereye gidiyor

Duvar saati ve paralellik, aşama başına (Luna):

| aşama | `quick` | `standard` | `detailed` | paralellik |
|---|---|---|---|---|
| keşif (arama + özet tarama) | 4,9 dk | 13,5 dk | 24,6 dk | 1,6–1,9 |
| getirme (`fulltext_fetch`) | 1,5 dk | 8,1 dk | 16,4 dk | 2,0 |
| tam metin okuma | 2,4 dk | 4,1 dk | 11,1 dk | 4,6–5,5 |
| yanıt | 2,8 dk | 3,4 dk | 2,9 dk | 1,0 |

İki okuma:

1. **Sağlayıcı beklemesi artık darboğaz değil.** D88'in toplama sınırları çalıştı: `quick` keşfi 11 sağlayıcı isteği ve 47 arama yaptı; dilim 13'ün duman koşusunda 81 ve 214'tü.
2. **Tek başına en büyük kalem bizim seri kodumuz.** `code:fulltext_work` `detailed`'da 300 adımda 16,4 dakika, paralellik **1,0** — getirme aşamasının tamamı bu. Seri oluş bilinçliydi (`flow.py`: "tek bir yayıncıya altı paralel indirme kabul edilebilir değil; seri koşunun ne kadar sürdüğü ölçülmedi"); artık ölçüldü. Konak başına nazik, konaklar arası paralel bir düzen kaliteye dokunmadan bunun çoğunu geri verir.
3. Tam metin okuma **model işi** olarak en büyük kalem (`standard` 22,5 dk, `detailed` 51,1 dk) ama 4,6–5,5 kat paralel koştuğu için duvar saatinde küçük. Çağrı başına ortanca: `quick` 17 sn, `standard` 19 sn (Luna); DeepSeek'te ~40 sn.

## Bulgular

- **arXiv 406.** Üç Luna koşusunun ve DeepSeek `quick` koşusunun **hepsinde** arXiv aramalarının ikisi de boş gövdeli, `Retry-After`'sız HTTP 406 ile düştü, yani arXiv sıfır kayıt getirdi. D87 Crossref'i aramadan çıkardığı için arXiv üç arama kanalından biri; düştüğünde ve Semantic Scholar da `quick`'in beklememe kuralıyla atlandığında koşu pratikte yalnız OpenAlex'ten topluyor. Kampanya bunu "arXiv hız sınırını 429 yerine 406 ile bildiriyor" diye okudu ve `common.send`'e hangi durumların hız sınırı sayılacağı parametresini ekledi (varsayılan 429, arXiv `(429, 406)`). **İnceleme (Fable, aynı gün 15:50 UTC) bu okumanın varsayım olduğunu gösterdi:** kayıtlı sorgu ürünün kendi istemcisiyle yeniden gönderilince 406, aynı saniyede aynı User-Agent ve aynı URL ile curl 200, bir dakika sonra ürünün istemcisi de 200; sorgunun kodlaması fark etmiyor. Yani düz bir IP hız sınırı değil, aralıklı ve istemciye bağlı bir şey (olasılıkla CDN tarafında), sebebi bilinmiyor. Parametre kalır: sınırlı yeniden denemeye ikinci bir şans verir, `standard` / `detailed`'da arama başına en çok 45 sn, `quick`'te sıfır maliyet. arXiv'in kayıt getirip getirmediği yeniden ölçümde bakılır; **ölçülmedi**.
- **Tek yavaş çağrı bütün okuma aşamasını durduruyor.** `detailed`'da bir `fulltext_adjudication` çağrısı adaptörün 300 sn tur sınırını aştı (`client_timeout`) ve koşu `model_call_failed` ile duraklattı; 152 model oturumunun 151'i sorunsuzdu. Duraklama sürdürülebilir, ama ölçüm o noktada kesildi. Düzeltilmedi.
- **13a'nın cevap yarısı denenmedi.** Dört tamamlanmış koşunun dördünde de yanıt ilk denemede `structurally_valid` çıktı, yani şema + kural hatalarını tek seferde bildiren yol gerçek modelle hiç tetiklenmedi. Hâlâ **ölçülmedi**.

## Sınırlar

Tek konu, efor başına tek koşu; dağılım ölçülmedi. Üç efor art arda aynı ağdan çıktı, sağlayıcı hız sınırlarının sonraki koşulara etkisi ölçülmedi. Etiket, ifade ve yanıt kalitesi ölçülmedi. `detailed` süresi kısmi bir okumanın süresidir, tam okumanın süresi değil.
