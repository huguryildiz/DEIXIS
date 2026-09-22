# SW ölçüm adımı (13ö) — D88 ölçümü, sonuç (22 Eylül 2026)

**Tarih:** 22 Eylül 2026. **Durum:** koşuldu; 13e'den sonra aynı ayarlarla yeniden koşuldu (en altta). **Ana dosya:** [sw-status.md](sw-status.md). **Karar:** D88. **Koşan:** Opus (kampanya betiği `.local/sw-measure-2026-09-22/campaign.py`, izlenmez). **Ham veri:** `.local/sw-measure-2026-09-22/` (dondurulmuş beklentiler `protocol.md`, `protocol-luna.md`; efor başına ayrı `DEIXIS_DATA_DIR`), izlenmez. Bu dosya o klasördeki `result.md`'nin kopyasıdır; arXiv bulgusu incelemeden sonra düzeltildi.

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
- ~~**13a'nın cevap yarısı denenmedi.** Dört tamamlanmış koşunun dördünde de yanıt ilk denemede `structurally_valid` çıktı.~~ **Yanlış okuma, yeniden ölçümde düzeltildi:** üç Luna yanıtının üçünde de ilk taslak kural denetiminden geçemedi (`missing_citation_anchor` vb.), tek onarım turu geçerli taslağı üretti; `model_calls: 2` yanıt + onarımdı. Şema hatası hiç çıkmadı, yani 13a'nın şema + kural hatalarını birlikte bildiren parçası hâlâ **denenmedi** (ayrıntı en altta).

## Sınırlar

Tek konu, efor başına tek koşu; dağılım ölçülmedi. Üç efor art arda aynı ağdan çıktı, sağlayıcı hız sınırlarının sonraki koşulara etkisi ölçülmedi. Etiket, ifade ve yanıt kalitesi ölçülmedi. `detailed` süresi kısmi bir okumanın süresidir, tam okumanın süresi değil.

## Yeniden ölçüm (13e sonrası, 22 Eylül 2026)

**Koşu:** 22 Eylül 2026 18:44–20:05 UTC, commit `8fa06b4` (13e `20b6e77` + inceleme), `skill_package_hash` `sha256:b35b4f49…` (değişmedi), `codex` / `gpt-5.6-luna` · medium, gömme `off`, protokol olduğu gibi onaylandı, üç efor art arda. Betik ilk kampanyanınkiyle aynı, dondurulmuş beklenti `.local/sw-measure-2026-09-22b/protocol.md`, ham veri aynı klasörde (izlenmez). Sabitler ayarlanmadı. İlk deneme 18:38'de başladı, editör kapanınca `quick`'in okuma aşamasında kesildi; dosyaları `aborted-1/`'de, sayılmadı, `quick` baştan koşuldu.

### Süreler

| efor | hedef (D88) | sahibin yeni hedefi | ilk ölçüm (`7df0102`) | yeniden ölçüm (`8fa06b4`) |
|---|---|---|---|---|
| `quick` | 5 dk | en çok 10 dk | 12,1 dk | **9,1 dk** |
| `standard` | 10 dk | 15 dk | 29,9 dk | **26,2 dk** |
| `detailed` | 15 dk | 20 dk | 55,5 dk (kısmi, okuma 119/300'de duraklattı) | **45,7 dk** (tam) |

Üç koşu da `completed`, üç yanıt da `structurally_valid`. Yeni hedeflere göre `quick` içinde, `standard` ve `detailed` değil.

| efor | kayıt | ayrı çalışma | `included` (kod) | indirilen PDF | okunan iş | okuma çağrısı / bütçe |
|---|---|---|---|---|---|---|
| `quick` | 1.027 → 720 | 956 → 695 | 7 → 7 | 19 → 13 | 18 → 10 | 36 → 20 / 40 |
| `standard` | 5.207 → 4.038 | 4.999 → 3.917 | 9 → 9 | 37 → 31 | 32 → 24 | 64 → 48 / 100 |
| `detailed` | 6.301 → 6.696 | 6.115 → 6.217 | 16 → 31 | 58 → 117 | — → 96 | 119 → 193 / 300 |

**İki koşunun girdisi aynı değil.** Aynı soru ve ayarlar farklı sayıda kayıt topladı (sağlayıcıların o anki cevabına bağlı; `quick`'te Semantic Scholar'ın iki araması bu kez ilk sayfada hız sınırına düştü), sonra farklı sayıda PDF bulundu. `quick` ve `standard`'da daha az, `detailed`'da iki kat PDF indirildi; sebebi ölçülmedi. Bu yüzden okuma aşamasının süresi iki kampanya arasında iş miktarı farkı da taşır; getirme aşamasının kısalması ise iş miktarından bağımsızdır (aşağıda).

### Zaman nereye gidiyor (ilk → yeni)

Yöntem ilk ölçümle aynı: aşama süresi = koşunun ilk adımının başlangıcından son adımının bitişine; paralellik = adım sürelerinin toplamı / aşama süresi (iç içe adımlar da sayıldığı için getirme aşamasının paralelliği iş parçacığı sayısı değildir; `code:fulltext_work` satırı ayrıca verildi). İlk ölçümün sayıları bu yöntemle aynen yeniden üretildi.

| aşama | `quick` | `standard` | `detailed` |
|---|---|---|---|
| keşif (protokol önerisi + arama + özet tarama) | 4,9 → 4,0 dk | 13,5 → 13,6 dk | 24,6 → 21,8 dk |
| getirme (`fulltext_fetch`) | 1,5 → **1,1** dk | 8,1 → **2,2** dk | 16,4 → **7,4** dk |
| `code:fulltext_work` paralellik | 1,0 → 3,7 | 1,0 → 3,9 | 1,0 → 3,8 |
| tam metin okuma | 2,4 → 1,8 dk | 4,1 → 6,4 dk | 11,1 (kısmi) → 13,0 dk |
| yanıt | 2,8 → 1,8 dk | 3,4 → 3,5 dk | 2,9 → 2,7 dk |

Okuma çağrısı ortancası 16–19 sn (ilk ölçümde 17–19 sn); paralellik 3,8–5,5.

Okuma:

1. **13e getirmede işe yaradı.** `code:fulltext_work` artık ~3,8 kat paralel; `standard`'da getirme 8,1'den 2,2 dakikaya, `detailed`'da iki kat PDF indirildiği hâlde 16,4'ten 7,4 dakikaya indi. PDF'den metin çıkarma bu sürenin küçük bir parçası: ilk ölçümün 33 PDF'si tek tek 20 sn, 4 iş parçacığıyla 6,2 sn sürüyor (PDF başına ortanca 0,5 sn).
2. **Keşif artık en büyük kalem ve değişmedi** (arama paralelliği 13e'den sahip kararıyla çıkarıldı). `standard`'ın keşfi dakika dakika: protokol önerisi (model) ~3 dk, sağlayıcı aramaları ~6,5 dk (Scopus tek başına 80 sayfa isteği, CORE en sonda ~2 dk; aynı anda ortalama 1,5–1,9 istek), eksik özet tamamlama (Semantic Scholar, Crossref) ~2 dk, özet tarama (model) ~2 dk.
3. `standard`'ın 26 dakikasının kabaca 15'i model çağrısı (protokol önerisi, özet tarama, okuma, yanıt), 10–11'i ağ.

### Bulgular

- **arXiv yine sıfır kayıt getirdi.** Üç koşunun altı arXiv aramasının altısı da düştü; bu kez `error_code: rate_limited` (406 artık hız sınırı sayılıyor, D88'in inceleme notu). Yani `common.send`'in `(429, 406)` ile verdiği ikinci şans arXiv'i geri getirmedi. `quick` beklemediği için orada hiç yeniden denenmedi; `standard` / `detailed`'da yeniden denemeler de 406 aldı. Sebep hâlâ bilinmiyor.
- **13e'nin okuma yeniden gönderimi bir kez tetiklendi ve işe yaradı.** `detailed`'da bir `fulltext_adjudication` çağrısı 307 sn sonra Codex tur sınırına düştü (`failed` oturum), adım bir kez yeniden gönderildi ve `succeeded` oldu; koşu duraklamadı, 193 çağrının hepsi tamamlandı.
- **Yanıt onarım yolu tetikleniyor — ilk ölçümün okuması yanlıştı.** Üç yanıt koşusunun üçünde de ilk taslak kural denetiminden geçemedi (`missing_citation_anchor` 1–23, `duplicate_citation_anchor` 0–9), tek onarım turu geçerli taslak üretti. İlk ölçümün veritabanı yeniden okununca aynı şey orada da var: üç Luna yanıtının üçünde ilk taslak geçersiz (`missing_citation_anchor` 6–12, `standard`'da 10 `duplicate_citation_anchor` + 1 `anchor_passage_not_cited`), ikincisi geçerli. Yanıt koşusunun `model_calls: 2`'si yanıt + inceleme değil, yanıt + onarımdı. Düzeltme: onarım yolu gerçek modelle **tetiklendi ve tek turda kapattı**; ama hatalar yalnızca kural hatası, şema hatası hiç yok, yani 13a'nın eklediği parça (şema ve kural hatalarının aynı raporda bildirilmesi) Luna'yla hâlâ **denenmedi**. Maliyeti: onarım turu yanıt aşamasının yaklaşık yarısı (`quick` 60 + 46 sn, `standard` 74 + 134 sn, `detailed` 73 + 73 sn).

### Sapmalar

- İlk deneme editör kapanınca kesildi (yukarıda); ikinci deneme editörden bağımsız bir süreçte koştu.
- Beklentiler (`protocol.md`): getirme kısalması ve `detailed`'ın duraklamaması tuttu; `quick` ~10–11 beklendi, 9,1 çıktı; `standard` ~23–25 beklendi, 26,2 çıktı; yanıt onarımının tetiklenmemesi beklendi, tetiklendi (yukarıdaki düzeltme).

### Sınırlar

Tek konu, efor başına tek koşu; dağılım ölçülmedi. İki kampanyanın topladığı kayıt ve bulunan PDF sayısı farklı, okuma süreleri bu farkı taşır. Üç efor art arda aynı ağdan çıktı; hız sınırı taşması ölçülmedi. Etiket, ifade ve yanıt kalitesi ölçülmedi. PDF çıkarma süresi kampanya koşarken ölçüldü.
