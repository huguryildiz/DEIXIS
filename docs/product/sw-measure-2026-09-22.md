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

## Üçüncü ölçüm (13f + 13g + 13h sonrası, 23 Eylül 2026)

**Koşu:** 23 Eylül 2026 01:37–02:42 UTC, commit `3ecb1ed`, `skill_package_hash` `sha256:7d4e238c…`, `codex` / `gpt-5.6-luna` · medium, `DEIXIS_SEARCH_QUERY=model`, gömme `off`, protokol olduğu gibi onaylandı, üç efor art arda. Dondurulmuş beklenti `.local/sw-measure-2026-09-24/protocol.md`'de, ham veri ve okuma betikleri (`quality.py`, `stages.py`, `summary.py`, `s2share.py`) aynı klasörde (izlenmez). Sabitler ayarlanmadı. Üç koşu da `completed`, üç yanıt da `structurally_valid`, hiçbir koşu duraklamadı.

### Kısaca

Süre üç eforda da kısaldı: `quick` 7,5 dk (hedef 10, **tuttu**), `standard` 17,9 dk (hedef 15, **tutmadı**, 26,2'den indi), `detailed` 39,7 dk (hedef 20, **tutmadı**, 45,7'den indi). Kazancın çoğu keşiften geldi: `standard`'ın keşfi 13,6 dakikadan 8,7'ye indi. Modelin sorguyu yazması 11–17 saniye sürdü, üç çağrının üçü de ilk cevapta geçerliydi.

31 doğrulanmış kuantum eserinden havuza `quick` 19, `standard` 25, `detailed` 30 eser girdi. Özet aşamasını 13 / 17 / 21 eser geçti. Tam metni okunan 1 / 7 / 17, yanıtta atıf alan **1 / 5 / 7** eser oldu.

Arama artık doğru eserlerin çoğunu buluyor; kayıp aramadan sonra oluyor. Özet aşamasını geçen eserler sıraya konuyor, tam metin planı bu sıranın başını alıyor (`quick` 40, `standard` 100, `detailed` 300 eser). Doğrulanmış eserlerin çoğu bu sırada gerilerde kalıyor. `quick`'te 246 tutulan eser arasında 13 doğrulanmış eserin yalnız biri ilk 40'taydı (5. sırada), öbürleri 46. ile 181. sıra arasındaydı. `standard`'da 17 eserin 8'i ilk 100'deydi. İkinci kampanyada da durum aynıydı (`standard`: havuzda 24, tutulan 18, okunan 1). Yani bu yeni bir kusur değil, bu ölçümle ilk kez görünür oldu.

### Süreler

| efor | hedef | ikinci ölçüm (`8fa06b4`) | bu ölçüm (`3ecb1ed`) |
|---|---|---|---|
| `quick` | 10 dk | 9,1 dk | **7,5 dk** |
| `standard` | 15 dk | 26,2 dk | **17,9 dk** |
| `detailed` | 20 dk | 45,7 dk | **39,7 dk** |

Aşamalar (ikinci ölçüm → bu ölçüm). Yöntem öncekiyle aynı: aşama süresi koşunun ilk adımının başlangıcından son adımının bitişine kadar; paralellik, adım sürelerinin toplamının aşama süresine oranı. `stages.py` ikinci ölçümün sayılarını aynen üretiyor.

| aşama | `quick` | `standard` | `detailed` |
|---|---|---|---|
| keşif | 4,0 → **3,5** dk | 13,6 → **8,7** dk | 21,8 → **16,8** dk |
| · onay kartına kadar (etiketleme, `search_query`, ölçüt önerisi) | → 2,0 dk | ~3 → 2,3 dk | → 2,7 dk |
| · `search_query` adımı (model + sayımlar) | 17 sn + 3 sn | 11 sn + 3 sn | 17 sn + 3 sn |
| · sağlayıcı aramaları, iki tur | 0,3 → 0,4 dk | 6,7 → **3,5** dk | 11,5 → **8,7** dk |
| · eksik özet tamamlama | 0,3 → 0,3 dk | 1,9 → 1,3 dk | 3,6 → 1,9 dk |
| · özet tarama (model) | 0,7 → 0,7 dk | 1,9 → 1,4 dk | 4,4 → 3,3 dk |
| getirme (`fulltext_fetch`) | 1,1 → 0,5 dk | 2,2 → 2,8 dk | 7,4 → **9,1** dk |
| tam metin okuma | 1,8 → 1,2 dk | 6,4 → 3,1 dk | 13,0 → 10,8 dk |
| yanıt | 1,8 → 1,7 dk | 3,5 → 2,8 dk | 2,7 → 2,4 dk |

- **`search_query` adımı ucuz.** Tek model çağrısı 11–17 sn, sayım istekleri ~3 sn; üç eforda da onarım gerekmedi (`attempts: [1]`).
- **13f'nin paralel araması:** `standard`'da arama 6,7 dakikadan 3,5'e indi; bunun içinde Scopus'un çıkması da var (D91; ikinci ölçümde tek başına 80 istek). `detailed`'da arama hâlâ 8,7 dk, çünkü Semantic Scholar kendi konağında tek sıra okunuyor: üç sorgu, 24 sayfa adımı, 44 istek, adım ortancası 19,6 sn. Birinci tur Semantic Scholar'ı bekleyerek 5,6 dk sürdü (öbür konaklar daha önce bitti), ikinci turda yine Semantic Scholar ~3 dk aldı. Arama adımlarının paralelliği 1,4 (ikinci ölçümde 1,0). Bu sayı iç içe sayfa adımlarını da sayıyor, aynı anda kaç konağın okunduğunu göstermiyor.
- **`detailed`'ın 1.000'lik okuması:** OpenAlex'te modelin sorgusu 922 kayıtla bitti (sınıra varmadı), kodun sorgusu 1.914'ün ilk 1.000'ini okudu, Semantic Scholar'da modelin sorgusu 18.986'nın ilk 1.000'ini okudu. Havuz 6.696 kayıttan 3.679'a indi. Arama yine 8,7 dk sürdü, çünkü darboğaz okunan kayıt değil Semantic Scholar'ın hızı.
- **`detailed`'ın getirmesi uzadı** (7,4 → 9,1 dk): 117 yerine 139 PDF indi, `code:fulltext_work` paralelliği 3,9–4,0 (300 iş, toplam 36,2 dk). Okuma 244 çağrı, 5,8 kat paralel, 10,8 dk.
- `detailed`'ın 39,7 dakikasının kabaca 21'i sonraki aşamalarda: getirme 9,1 + okuma 10,8 + yanıt 2,4 dk. Keşif hedefe inse bile `detailed` 20 dakikaya getirme ve okuma yüzünden varmaz.

### Kalite: 31 doğrulanmış kuantum eseri

Eşleme `common.hits` ile aynı (DOI ya da normalleştirilmiş başlık). Bir eser, sürümlerinden biri o aşamadaysa o aşamada sayılır. Her eforun kendi `library.sqlite`'ı okundu (`quality.py`).

| efor | havuzda | tutulan (özet aşaması `candidate`) | getirme planında | PDF'si var | okunan | `include` | atıf alan |
|---|---|---|---|---|---|---|---|
| `quick` | 19 | 13 | 1 / 40 | 1 | **1** | 1 | **1** |
| `standard` | 25 | 17 | 8 / 100 | 7 | **7** | 5 | **5** |
| `detailed` | 30 | 21 | 19 / 300 | 17 | **17** | 12 | **7** |
| *ikinci ölçüm, aynı betikle:* | | | | | | | |
| `quick` (`8fa06b4`) | 13 | 13 | 3 | 1 | 1 | 1 | 1 |
| `standard` | 24 | 18 | 5 | 1 | 1 | 1 | 1 |
| `detailed` | 28 | 24 | 16 | 14 | 14 | 11 | 8 |

Tutulan doğrulanmış eserlerin, tutulan eserler arasındaki sırası (inceleme sırası, yani getirme planının okuduğu sıra):

- `quick` (246 eser, plan 40): 5, 46, 48, 51, 64, 78, 84, 116, 117, 127, 155, 164, 181
- `standard` (395 eser, plan 100): 2, 19, 24, 44, 62, 72, 79, 100 | 115, 135, 150, 189, 222, 243, 258, 260, 339
- `detailed` (519 eser, plan 300): 1, 5, 22, 32, 45, 46, 48, 56, 67, 76, 86, 91, 167, 177, 178, 188, 235, 295, 298 | 333, 426

Tam metne kalan kayıp, bu sıranın sınırında oluyor. Plana giren doğrulanmış eserlerin neredeyse hepsinin PDF'si bulunup okundu (`standard` 8'den 7, `detailed` 19'dan 17). `quick` ve `standard`'da doğrulanmış eserlerin çoğu sınırın gerisinde kaldı.

**Hangi sorgudan geldiler.** Her sayfanın saklanan ham sağlayıcı cevabından okundu, çünkü aday satırı kayıt başına tek bir arama tutuyor. İkinci tur modelin terimlerinden kurulduğu için modelin tarafında sayıldı (D92).

| efor | yalnız modelin sorgusu (içinden yalnız 2. tur) | yalnız kodun sorgusu | ikisi de |
|---|---|---|---|
| `quick` | 8 (2) | 1 (g074) | 10 |
| `standard` | 11 (2) | 3 (g102, g106, g158) | 11 |
| `detailed` | 10 (2) | 7 (g010, g016, g047, g074, g096, g106, g158) | 13 |

Yalnız bir sorgudan gelip atıf alan eserler: `standard`'da modelin tarafından g013 ve g051, `detailed`'da kodun tarafından g016. İki sorgunun birlikte aranması üç eforda da havuza eser ekledi.

### Sorgu

Her araştırma modeli bir kez çağırdı; üç eforun terimleri birbirinden farklı çıktı.

| efor | ayar bloğu | görev bloğu | uyarı |
|---|---|---|---|
| `quick` | quantum network (topic), quantum repeater (topic) | entanglement distribution (topic), entanglement routing (topic), mathematical optimization (method) | `mathematical optimization` öbür blokla 0 kayıt (`no_records_with_other_block`), sorguda kaldı |
| `standard` | quantum network (topic) | entanglement distribution, entanglement routing, end-to-end entanglement (üçü topic) | yok |
| `detailed` | quantum networks (topic) | entanglement distribution (topic), mixed integer programming (method) | yok; ama `mixed integer programming` öbür blokla yalnız **1** kayıt |

Hiçbir terim yedeğiyle değiştirilmedi. OpenAlex sorguları:

- `quick` model: `("quantum network" OR "quantum repeater") AND ("entanglement distribution" OR "entanglement routing" OR "mathematical optimization")` (1.228 kayıt, 400 okundu)
- `standard` model: `"quantum network" AND ("entanglement distribution" OR "entanglement routing" OR "end-to-end entanglement")` (1.112, 1.000 okundu)
- `detailed` model: `"quantum networks" AND ("entanglement distribution" OR "mixed integer programming")` (922, hepsi okundu)
- kod (üçünde aynı): `("end-to-end entanglement distribution" OR "quantum networks") AND ("decision variables" OR objectives OR constraints OR routing)` (1.914; `quick` 400, `detailed` 1.000 okudu). `standard`'da görev bloğu `routing` yerine `treatment` ile kesildi: 797 kayıt, hepsi okundu.

İkinci turun eklediği terimler:

- `quick`: quantum internet, remote entanglement, repeaters based, quantum networking, multiplexed quantum, quantum memories, repeater based, entanglement swapping
- `standard`: quantum internet, quantum networking, quantum repeater, remote entanglement, entanglement-based quantum, quantum repeaters
- `detailed`: quantum internet, quantum repeater, quantum networking, quantum repeaters, entanglement swapping, distributed quantum, entanglement-based quantum

İkinci turun OpenAlex sorgusu 251–285 kayıtla bitti. Her eforda ikinci tur, birinci turun okunan sayfalarında olmayan 2 doğrulanmış eser getirdi.

Tur başına sağlayıcı isteği (sorgu sayaçlarından): `quick` 5 + 5 (6 sorgu), `standard` 35 + 13 (16 sorgu), `detailed` 53 + 28 (20 sorgu). `quick`'in ilk turu yalnız OpenAlex'in iki sorgusu ve Semantic Scholar'ın model sorgusundan oluştu (`max_provider_requests` kesti).

### Maliyet

| | `quick` | `standard` | `detailed` |
|---|---|---|---|
| etiketleme (`vocabulary_labels`) | 3 | 3 | 3 |
| `search_query` | 1 | 1 | 1 |
| ölçüt önerisi | 3 | 3 | 3 |
| özet tarama | 4 | 10 | 30 |
| tam metin okuma | 22 | 82 | 244 |
| yanıt (taslak + onarım) | 2 | 2 | 2 |
| **model çağrısı, toplam** | 35 | 101 | 283 |
| sağlayıcı isteği (arama) | 10 | 48 | 81 |
| özet tamamlama isteği | 77 | 203 | 204 |
| indirme | 16 | 51 | 139 |

Başarısız model oturumu yok; 13e'nin okuma yeniden gönderimi bu kez tetiklenmedi.

### Semantic Scholar (sahip kararı, 23 Eylül 2026)

`s2share.py` her sağlayıcının saklanan sayfalarını okudu. Semantic Scholar'ın getirdiği doğrulanmış eserlerin neredeyse hepsini başka bir sağlayıcı da getirdi: yalnız onun getirdiği 3 eser vardı (`quick` g009, `detailed` g030 ve g126) ve hiçbiri özet aşamasını geçmedi. Buna karşılık `detailed`'da aramanın süresini o belirledi: 24 sayfa adımı, 44 istek, sayfa başına ortanca ~19 sn (öbür sağlayıcılarda 2–7 sn). Sağlayıcı başına 300 kayıtlık bir okuma sınırı önerildi; sahip önce Semantic Scholar'ın Scopus gibi (D91) sw aramasından çıkmasına karar verdi. Ardından bulk uç noktası denendi (`.local/sw-s2-bulk-probe-2026-09-23/result.md`): aynı ilk tur blok sorguları mantıksal sözdizimiyle efor başına 2–3 istek ve 4–6 sn'de 20 / 21 / 20 doğrulanmış eser getirdi (bugünkü ilgi aramasıyla 6 / 8 / 19); `standard` ve `detailed`'da OpenAlex'in bulmadığı eser yoktu, `quick`'te havuza 4 eser ekledi. **Sahip kararı:** Semantic Scholar bütün sw aramalarında bulk uç noktasıyla aranır. Bulk ilgiye göre sıralamadığı için 1.000'i aşan sorgunun kesim sırası dilimde karara bağlanır. Kod değişmedi; kararı ve kaydını (D93) ayrı bir dilim yazar, kabul koşulu paket sorusunda da kayıp olmadığını göstermektir.

### Önceki koşudan taşınanlar

- **arXiv yine sıfır kayıt getirdi.** 7 aramanın 7'si `rate_limited` ile bitti (`quick` 1, `standard` 3, `detailed` 3).
- **Yanıt onarım turu üç eforda da koştu.** İlk taslakta `duplicate_citation_anchor` hataları vardı, tek onarım turu geçerli taslak üretti. Şema hatası yok, yani 13a'nın şema ve kural hatalarını tek raporda bildiren yolu Luna'yla hâlâ denenmedi.
- Semantic Scholar'ın bazı sayfaları hız sınırına düştü (Semantic Scholar sorgularının `quick`'te 2'nin 2'si, `standard`'da 3'ün 3'ü, `detailed`'da 3'ün 2'si birer sayfada kesildi). Koşuyu durdurmadı.

### Beklentiden sapmalar (`protocol.md`)

- Süre: `quick` 8–9 dk beklendi, 7,5 çıktı. `standard` 20–22 beklendi, 17,9 çıktı. `detailed` 33–38 beklendi, **39,7** çıktı: keşif 12–14 yerine 16,8 dk sürdü (Semantic Scholar), getirme de uzadı.
- Havuz: tuttu (19 / 25 / 30).
- Tutulan: %70–90 beklendi. %68 / %68 / %70 çıktı, alt sınırda.
- **Okunan ve atıf alan: tutmadı.** Okunan için 5–8 / 10–15 / 18–22 beklendi, 1 / 7 / 17 çıktı. Atıf alan için 4–7 / 7–12 / 10–16 beklendi, 1 / 5 / 7 çıktı. Beklenti, tutulan eserlerin sıralamada öne çıkacağını varsayıyordu; sıralama bunu yapmıyor.
- Yanıt onarımının koşması ve arXiv'in boş dönmesi beklendiği gibi.
- Kampanya betiğinde yalnız `DEIXIS_SEARCH_QUERY="model"` satırı değişti. Kalite, sıra ve kaynak ölçümleri için bu klasöre `quality.py`, `stages.py`, `summary.py` eklendi; üçü de yalnız okur.

### Ölçülmeyenler

- Tek konu, efor başına tek koşu; dağılım yok. Üç eforun her biri modeli ayrı çağırdı ve farklı terimler aldı. Eforlar arasındaki kalite farkının bir kısmı bu sorgu farkından gelir; bu ayrıştırılmadı.
- Ağ ve sağlayıcılar yalnız o saatteki durumlarıyla ölçüldü (Semantic Scholar'ın hız sınırı, arXiv'in 406'sı). Üç koşu art arda aynı ağdan çıktı.
- Yanıt kalitesi, 31 eserden kaçına atıf yapıldığının ötesinde ölçülmedi. 31 eser, tek bir sınıflamadan gelen yüksek güvenli `confirmed_mathematical_model` listesidir. Listede olmayan bir kaynağa yapılan atıf yanlış sayılmaz; yanıtların atıf yaptığı öbür 4 / 6 / 8 eser okunmadı.
- Sıralamanın doğrulanmış eserleri neden geriye koyduğu incelenmedi; bu ölçüm yalnız nerede kaldıklarını gösteriyor.
