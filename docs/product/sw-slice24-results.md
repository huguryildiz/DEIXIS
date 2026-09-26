# Dilim 24a — ölçüm kampanyasının sonucu

**Tarih:** 2026-09-26. **Plan:** [sw-slice24-measurement-campaign.md](sw-slice24-measurement-campaign.md), commit `65a7ec8`.
**Kampanya klasörü (git dışı):** `.local/sw-slice24-campaign-2026-09-26-134050/` (defter `ledger.jsonl`, protokol
`protocol.md`, ölçüm `measure/`, kapılar `gates.json`, analist okuması `analyst-reading.jsonl`, G1 `g1/`).
**Makine ve model:** bir Apple M1 Pro; her model çağrısı Codex bağlantısında `gpt-5.6-luna`, efor `medium`. Başka model
çağrılmadı, sessiz geri dönüş olmadı (1.230 oturumun hepsi `gpt-5.6-luna->gpt-5.6-luna`).

## Kısa özet

İki soruda 14 araştırma koştu: kuantum sorusu (q1) ve yetişkinlerde zaman kısıtlı beslenmenin (TRE) vücut ağırlığına
etkisi (tıp sorusu, q-tre). Her soruda `sw` `quick`, `standard` (iki kez), `detailed`, yerleşik gömmeli `standard` ve
`legacy` `standard` (iki kez). 14'ün 13'ü yanıtıyla bitti. Biri, tıp sorusunun gömmeli `sw` koşusu, tam metin okumasından
hiç `include` çıkarmadı; ürün yanıt koşusunu "önce en az bir kaynak ekle" diye reddetti.

Kuantumda `sw` beklendiği gibi çalıştı: 31 eserlik referans kümenin 29–30'unu havuza aldı (`legacy` 5–11), atıf alan
eser sayısı `legacy` ile aynı (ortalama 5'e 5), analist okumasında 10 `include`'da ve 10 iddiada ciddi hata çıkmadı.
Tıpta tablo başka: `sw` referans denemelerin hiçbirini okuyamadı, çünkü hiçbirinin açık PDF'ini bulamadı. Model
önerdiği ölçüte popülasyonu ve karşılaştırıcıyı ayrı parça olarak koymadı, bu yüzden obez olmayan gönüllülerle yapılmış
bir deneme ve TRE'yi başka bir TRE ile kıyaslayan bir deneme `include` oldu.

Varsayılan için sonuç: **dört kapıdan üçü geçmedi (1, 2, 4), varsayılan `legacy` kalır.** Kapı 2 tıpta zaten
okunamazdı: dondurulmuş kuralla kurulan referans küme 4 denemede kaldı (eşik 10). Kapı 3 (kanıt bütünlüğü) geçti.
G1 tuttu (`arxiv_source` için öneri `auto`), ama 24b koşmadığı için hiçbir varsayılan değişmedi. Karar [D105](../decisions.md) olarak yazıldı; satır 24 sahibin kararını bekliyor.

Ne ölçüldü, ne ölçülmedi: bunlar tek makinede, tek modelle, iki soruda, hücre başına bir (kapı 2'de iki) canlı koşudur.
Referans kümeler doğruluk ölçütü değildir; kuantum kümesi kendi eski koşularımızdan türedi, tıp kümesi analistin
tablolardan kurduğu bir kümedir. Elicit karşılaştırması "bulduk / kaçırdık / ikisi de" der, doğruluk söylemez. Analist
okuması iki model okumasıdır (biri kör), insan doğrulaması değildir.

## Kapılar

Kurallar planın karar 11'inden, `gates.py` ile uygulandı (dondurulmuş, sha256 `frozen-sha256.json`'da).

| Kapı | Sonuç | Sayılar |
|---|---|---|
| 1 tamamlanma (10 `sw`) | **geçmedi** | 10'un 9'u yanıtıyla bitti. `qtre-sw-standard-emb-r1`: keşif ve okuma tamam, 0 `include`, yanıt koşusu 422 ("Include at least one source") ile reddedildi. `q1-sw-standard-r1` izin verilen tek sürdürmeyi kullandı (`client_timeout`, 10 dk bekleyip). |
| 2 iş akışı karşılaştırması | **geçmedi** (q1 geçti, q-tre okunamaz) | q1, \|R\| = 31: havuz `sw` 29 ve 30 (ort. 29,5), `legacy` 11 ve 5 (ort. 8); pay 4 → geçer. Atıf `sw` 6 ve 4 (ort. 5), `legacy` 5 ve 5 (ort. 5); 5 ≥ 4 ve iki `sw` koşusu da en az bir R birimine atıf verdi → geçer. q-tre: \|R\| = 4 < 10, okunamaz (havuz `sw` 3/3, `legacy` 2/2; atıf dördünde de 0). Betimleyici bir karar kuralıdır, istatistiksel sınama değil. |
| 3 kanıt bütünlüğü | geçti | 9 `sw` yanıtında 0 kötü bağ; çapalar exact ya da fuzzy bulundu; `model_isolation_violation` 0; başka modelin oturumu 0. Yanıtı olmayan `qtre-sw-standard-emb-r1` denetlenecek yayım içermez. |
| 4 analist okuması | **geçmedi** (q1 geçti, q-tre geçmedi) | q1: 10 `include`'da 0 ciddi, 10 iddiada 0 ciddi. q-tre: 8 `include`'da 3 ciddi (2 karşılaştırıcı, 1 popülasyon), 10 iddiada 0 ciddi. Ayrıntı aşağıda. |
| G1 (arXiv kaynağı) | tutar → `auto` önerisi | 642 yerleşik blok, KaTeX 0.16.47 hatası 0; 584 uygun bloktan tohumla 40 (26 makale) çekildi, 40'ı da görüntüde doğru okundu. |

Dondurulmuş beklenti "1, 2, 3 ve 4 geçer" idi. Tutmadı.

## Koşular, süre ve maliyet

Süre: araştırmanın yaratılmasından yanıtın bitişine. 10 / 15 / 20 dk hedefleri `quick` / `standard` / `detailed`
içindir. Jetonlar Luna aboneliğinden düştü; para karşılığı yok.

| Araştırma | Durum | Süre (dk) | Model çağrısı | Giriş / önbellek / çıkış jetonu | Havuz (eser) |
|---|---|---|---|---|---|
| q1-sw-standard-r1 | bitti | 29,2 (10 dk bekleme dahil) | 125 | 1.276.039 / 145.152 / 98.518 | 3.118 |
| q1-legacy-standard-r1 | bitti | 8,6 | 9 | 265.943 / 43.520 / 20.967 | 188 |
| q1-sw-quick-r1 | bitti | 12,2 | 75 | 785.456 / 164.352 / 64.653 | 1.074 |
| q1-sw-detailed-r1 | bitti | 35,9 | 318 | 3.256.435 / 590.848 / 282.701 | 2.880 |
| q1-sw-standard-emb-r1 | bitti | 19,9 (kurulum 31 s ayrı) | 117 | 1.215.320 / 270.848 / 93.871 | 3.049 |
| q1-sw-standard-r2 | bitti | 17,7 | 125 | 1.294.126 / 253.952 / 120.222 | 3.043 |
| q1-legacy-standard-r2 | bitti | 8,8 | 8 | 227.599 / 37.632 / 19.875 | 120 |
| qtre-sw-standard-r1 | bitti | 12,8 | 82 | 885.473 / 127.488 / 76.635 | 5.423 |
| qtre-legacy-standard-r1 | bitti | 7,8 | 9 | 309.044 / 23.552 / 21.771 | 200 |
| qtre-sw-quick-r1 | bitti | 8,3 | 47 | 536.317 / 65.280 / 39.697 | 1.880 |
| qtre-sw-detailed-r1 | bitti | 30,2 | 173 | 1.866.502 / 308.736 / 155.215 | 5.127 |
| qtre-sw-standard-emb-r1 | bitmedi (yanıt yok) | keşif 19,4 + okuma 2,3 (kurulum 3 dk 1 s ayrı) | 71 | 726.905 / 114.176 / 66.411 | 7.565 |
| qtre-sw-standard-r2 | bitti | 13,1 | 62 | 676.580 / 91.904 / 67.104 | 5.588 |
| qtre-legacy-standard-r2 | bitti | 7,1 | 9 | 252.693 / 11.776 / 19.716 | 213 |

Toplam: 1.230 model çağrısı, 13,57 M giriş (2,25 M'si önbellekten) ve 1,15 M çıkış jetonu. Koşular 14:02'den 18:29'a,
yaklaşık 4 sa 27 dk sürdü (aralar dahil; hazırlık 13:41'de başladı). Beklenti 1.400–1.650 çağrı, 14–18 M giriş,
1,1–1,5 M çıkış, 4,5–5,5 saatti: çağrı ve giriş beklentinin altında, çünkü tıp koşuları kuantumdakinin yarısı ile üçte
ikisi arasında çağrı yaptı.

Süre hedefleri: kuantumda `quick` 12,2 (hedef 10), `standard` 17,7 ve 19,9 (hedef 15; r1'in 29,2'si 10 dk bekleme
içerir), `detailed` 35,9 (hedef 20) — üçü de tutmadı, beklenti de tutmayacaklarını söylüyordu (`quick` 9–14, `standard`
16–25, `detailed` 38–46; üçü de aralıkta). Tıpta `quick` 8,3 ve `standard` 12,8 / 13,1 hedefin altında, `detailed` 30,2
üstünde. Getirmenin bitişi ile son keşif model partisi arasındaki fark (17a): kuantum 0,2–1,8 dk, tıp 0,1–5,6 dk (en
büyüğü tıp `detailed`).

Kuota ve model hataları: ilk araştırmanın ilk model adımları 14:05'te döndü, kota hatası yok. `q1-sw-standard-r1`'in
okuma koşusu 14:17'de `model_call_failed` / `client_timeout` ile durdu, 10 dk sonra bir kez sürdürüldü ve bitti. Ayrıca
`qtre-sw-detailed-r1`'de iki model çağrısı 5 dakikada zaman aşımına uğradı; ürün adımı kendisi ikinci denemede bitirdi,
koşu durmadı.

## Kuantum (q1): referans küme (31 eser), aşama sayımları

Aşama sayımları n/31, sözlüğün adlarıyla. `legacy`'de yalnız havuz, eleme sonrası ve atıf vardır.

| Araştırma | havuz | özette aday | yönlendirilen | N yüzünden okunmayan | planlanan | PDF'i olan | okunan | `include` | atıf |
|---|---|---|---|---|---|---|---|---|---|
| sw standard r1 | 29 | 23 | 23 | 6 | 13 | 11 | 8 | 6 | 6 |
| sw standard r2 | 30 | 24 | 24 | 6 | 12 | 11 | 10 | 5 | 4 |
| sw quick | 23 | 19 | 19 | 4 | 10 | 8 | 8 | 5 | 1 |
| sw detailed | 27 | 23 | 23 | 4 | 23 | 22 | 22 | 16 | 4 |
| sw standard gömmeli | 28 | 24 | 24 | 4 | 14 | 11 | 11 | 9 | 5 |
| legacy r1 | 11 | – | – | – | – | – | – | 8 (eleme) | 5 |
| legacy r2 | 5 | – | – | – | – | – | – | 5 (eleme) | 5 |

Dondurulmuş beklentiyle (quick / standard / detailed): havuz 19–26 / 27–30 / 28–30 → 23 / 29, 30 / 27 (`detailed` bir
eksik); özette aday 13–22 / 20–24 / 21–26 → hepsi aralıkta; okunan 1–9 / 7–8 / 17–19 → 8 / 8, 10 / 22 (`standard` r2 ve
`detailed` üstünde); `include` 1–7 / 5–7 / 11–13 → 5 / 6, 5 / 16 (`detailed` üstünde); atıf 0–3 / 4–5 / 0–7 → 1 / 6, 4 / 4
(`standard` r1 bir üstünde). İki `standard` koşusu arasındaki fark havuzda 1, atıfta 2 (beklenti en çok 3 ve 3).
`legacy` havuzda `sw`'den az, atıfta benzer (beklenti de böyleydi, dayanağı zayıftı).

Kaybın yeri (`standard` r1 / r2, 31 birim): aramada yok 2 / 1; N yüzünden özet okunmadı 6 / 6; tam metne yönlendirildi ama
getirme sınırı yüzünden planlanmadı 10 / 12; planlandı ama PDF yok 2 / 1; PDF var okunmadı 3 / 1; okundu ama
`unresolved` 2 / 5; `include` olup atıf almadı 0 / 1. En büyük kayıp getirme sınırında (`FULLTEXT_WORK_LIMIT` 100).

K3 (özet okuma sınırı N): N yüzünden okunmayan set eseri `quick` 4, `standard` 6 ve 6, `detailed` 4 (beklenti 4–6 / 6–9 /
4–5, hepsi aralıkta). Bunların açık erişimli olanı 2 / 2, 1 / 0 (beklenti 1–3; `detailed` 0). Model açık erişimli bir set
eserini hiç kapsam dışı saymadı (0, beklenti 0). Hepsini okumak için gereken N: `standard` 1.896 ve 1.815, `detailed`
1.762 (modelin havuzu 2.100–2.300).

Hangi sorgudan geldi (yalnız o sorgunun getirdiği set eserleri): `standard` r1'de yalnız model sorgusu 3, yalnız kod sorgusu
4, yalnız zincir 2; r2'de 4 / 4 / 1. İkinci tur tek başına bir şey getirmedi (`quick`'te 2, `detailed`'da 1).

Kuyruk (sürüm düzeyinde): `quick` 20, `standard` 30 ve 33, `detailed` 94 (beklenti 7–17 / 25–30 / 90–105; `quick` üstte).
Çoğu `part_without_evidence` (24/112, 22/111, 75/311). PDF bekleyen: 61 / 58, 57 / 173 (beklenti 27–65 / 55–60 / 165–175,
hepsi aralıkta).

arXiv araması: dört `sw` koşusunda `rate_limited`, 0 kayıt (beklendiği gibi).

Gömmeli `standard`: havuz 3.049 (gömmesiz 3.118 ve 3.043). `probe_report.py`'nin bir-dışarıda sırası: gömme sinyali ilk
200'e +3 set eseri ekliyor, %95 aralık [−1, 7]; bu havuzda ve bu kümede, tek koşu.

## Kuantum: Elicit'in 9 eseri

Elicit "Balanced" ayarında koştu. `standard` başlık sütunudur, "aynı bütçe" değildir. Elicit'in 5 eseri bizim 31'lik
kümemizde de var (e02, e04, e06, e07, e09 — Elicit'in "Full text" dedikleri); "Abstract only" dediği 4'ü (e01, e03, e05,
e08) kümede yok.

| Araştırma | havuz | yönlendirilen | okunan | `include` | atıf |
|---|---|---|---|---|---|
| sw standard r1 | 9 | 9 | 2 | 2 | 2 |
| sw standard r2 | 9 | 9 | 3 | 2 | 2 |
| sw quick | 8 | 8 | 2 | 2 | 1 |
| sw detailed | 9 | 9 | 6 | 4 | 3 |
| sw standard gömmeli | 9 | 9 | 3 | 3 | 3 |
| legacy r1 | 5 | – | – | 5 (eleme) | 3 |
| legacy r2 | 2 | – | – | 2 (eleme) | 2 |

Beklenti: havuz 6–9 / 9 / 9 (tuttu); okunan 1–2 / 1–2 / 5 (r2 ve `detailed` bir üstte); `include` 0–1 / 1–2 / 2–3
(`quick` ve `detailed` bir üstte); atıf 0–1 / 0–2 / 1–2 (`detailed` bir üstte). "Abstract only" dördünden hiçbiri
`include` olmadı (tuttu). E∖D'de havuzda olmayan eser `standard` ve `detailed`'da 0 (tuttu); `quick`'te 1 (e09, aramada
yok).

E∖D'nin kaybı (`standard` r1): e01 ve e08 PDF yok; e02 PDF var okunmadı (sıra); e03, e05, e06, e09 getirme sınırı. D∖E:
`standard` r1'in 13 `include`'undan 11'i, r2'nin 15'inden 13'ü, `detailed`'ın 42'sinden 38'i Elicit'in listesinde yok;
her birinin doğrulanmış bir alıntısı var (`measure/elicit-d-minus-e.json`). Bunlar yanlış sayılmaz; iki liste farklı
kapsamla kuruldu.

## Tıp (q-tre): referans küme

Kural (karar 6): PubMed'de harfi harfine sorgu, 2026/09/26'da 90 kayıt; en yeni üç uygun meta-analizin dahil edilen
çalışmalar tablosu. 10 aday incelendi: sıra 1 ve 4 uygun ama tablo açılamadı (OUP 403; Diabetologia ödeme duvarı, açık
ek dosyada çalışma tablosu yok), sıra 2, 3, 8 ağ meta-analizi (dışarıda), 6 ve 7 vücut ağırlığını havuzlamıyor, 5, 9, 10
tabloları okundu. Tablo satırları tekil denemelere indirildi: **R = 4** (Floyd 2026, Haganes 2022, Kotarsky 2021,
Feehan 2023), karşılaştırıcı farklı 10, bilinmiyor 0. Beklenti "|R| 10–40" idi (dayanağı zayıf); tutmadı. Üç
tablonun 29 satırından 11'i popülasyon dışı (sporcular, sağlıklı erkekler), 10'u karşılaştırıcısı farklı (çoğu kalori
kısıtlaması), 4'ü müdahale dışı (5:2 ya da gün aşırı oruç): en yeni meta-analizler dar alt grupları (TRE + egzersiz,
PKOS, MASLD) havuzluyor.

| Araştırma | havuz | yönlendirilen | planlanan | PDF'i olan | okunan | `include` | atıf |
|---|---|---|---|---|---|---|---|
| sw standard r1 | 3 | 2 | 2 | 0 | 0 | 0 | 0 |
| sw standard r2 | 3 | 2 | 2 | 0 | 0 | 0 | 0 |
| sw quick | 2 | 2 | 2 | 0 | 0 | 0 | 0 |
| sw detailed | 3 | 3 | 2 | 0 | 0 | 0 | 0 |
| sw standard gömmeli | 2 | 2 | 1 | 0 | 0 | 0 | 0 |
| legacy r1 | 2 | – | – | – | – | 2 (eleme) | 0 |
| legacy r2 | 2 | – | – | – | – | 2 (eleme) | 0 |

`standard`'da havuz 3/4 (%75; beklenti %70–95, tuttu). Kayıp: Floyd 2026 (PKOS'lu kadınlarda çapraz deneme) hiçbir
`sw` koşusunda aramaya girmedi; bugün saklı PubMed sorgularının hiçbiri onu kapsamıyor (sorgu "overweight OR obesity"
bloğu istiyor, özet bu sözcükleri taşımıyor olmalı). Haganes ve Kotarsky her `sw` koşusunda planlandı ama PDF'leri yok.
Europe PMC: ürünün PDF bulamadığı 4 eserin 2'si (Kotarsky PMC8157764, Feehan PMC10708421) PMC'de açık tam metin olarak
duruyor. Bu, bir Europe PMC tam metin kaynağının bu kümede getirebileceği kazancın üst sınırıdır (Europe PMC kodda yok).

Karşılaştırıcısı farklı 10 deneme: `sw` `standard` havuzda 8, yalnız 2'si yönlendirildi, hiçbiri okunmadı.

## Tıp: Elicit'in 5 eseri

Kapsam etiketleri (özetten, Europe PMC'den birer istek): Lin 2023, Wilkinson 2026, Cienfuegos 2020 "kapsamda"; Liu 2022 ve
Jamshed 2022 "karşılaştırıcı farklı" (iki kolda da kalori kısıtlaması). Beşi de R'de yok, karşılaştırıcı farklı
listemizde de yok (üç meta-analizin tablolarında geçmiyorlar). Beklenti Lin ve Cienfuegos'un R'de olacağıydı; tutmadı.

| Araştırma | havuz | yönlendirilen | planlanan | PDF'i olan | okunan | `include` | atıf |
|---|---|---|---|---|---|---|---|
| sw standard r1 | 5 | 5 | 5 | 0 | 0 | 0 | 0 |
| sw standard r2 | 5 | 5 | 5 | 0 | 0 | 0 | 0 |
| sw quick | 4 | 4 | 4 | 0 | 0 | 0 | 0 |
| sw detailed | 5 | 5 | 4 | 0 | 0 | 0 | 0 |
| sw standard gömmeli | 5 | 5 | 2 | 0 | 0 | 0 | 0 |
| legacy r1 | 4 | – | – | – | – | 3 (eleme) | 2 |
| legacy r2 | 4 | – | – | – | – | 4 (eleme) | 2 |

Havuz beklentisi (`standard` ve `detailed` 4–5, `quick` 3–5) tuttu. Ama `sw` beşinin de PDF'ini bulamadı, hiçbirini
okumadı; `legacy` özetten ikisine atıf verdi. "Kapsamda olanlar okunursa `include`" beklentisi okunamadığı için
sınanamadı. D∖E: `sw` `standard` r1'in 7, r2'nin 4, `detailed`'ın 16 `include`'unun hiçbiri Elicit'in beşinde yok; her
birinin doğrulanmış alıntısı var.

## Tıp: ölçüt, yönlendirme, kuyruk

- **Yönlendirme:** her tıp `sw` koşusunda PubMed ve bioRxiv seçildi (alan payı 0,92–0,98), arXiv (0) ve IEEE (0,002)
  dışarıda kaldı; PubMed 2.368–2.985 kayıt getirdi. `quick`'te PubMed seçildi ama hiç PubMed arama satırı yok; nedeni ölçülmedi. Europe PMC aranmadı. Beklenti
  tuttu.
- **Ölçüt:** aranan şey (TRE ve vücut ağırlığı) beş koşunun beşinde ölçütte kaldı (`sought_term_in_criterion`). Ama
  ölçüt parçaları beşinde de "TRE müdahalesi, randomize tasarım, vücut ağırlığı sonucu" üçlüsü: popülasyon (aşırı kilolu
  ya da obez yetişkin) hiçbirinde ayrı parça değil, `sw` r1'in ölçüt cümlesinde hiç geçmiyor; karşılaştırıcı yalnız
  tasarım parçasının içinde. Beklenti "karşılaştırıcı bir ölçüt parçasıdır" diyordu; tutmadı.
- **Sorgu:** kod sorgusu beş koşunun beşinde `"time-restricted eating reduce body weight"` diye fiili içine almış bir
  ifade arıyor (SW17'nin Limits'te andığı kaynaşma); `detailed`'da `"randomised controlled trials"` bir sorgu bloğuna
  girdi (İngiliz yazımı).
- **Kuyruk:** `standard` 16 ve 12 (`part_without_evidence` 11 ve 8, `fulltext_runs_disagree` 4 ve 3); kuantumdan az
  `part_without_evidence`, çok `fulltext_runs_disagree` beklentisi tuttu. PDF bekleyen: `standard` r1 80, `detailed` 237.
- **Açık erişim:** modelin okuduğu özetlerin açık erişim payı tıpta 86/150 ve 94/150, kuantumda 61/150 ve 57/150
  (beklenti "tıpta yüksek", tuttu). Buna karşın planlanan 112 eserden PDF'i olan tıpta 29 ve 19, kuantumda 54 ve 54.
  `fetch_http_error` tıp `standard`'da 40 ve 42.

## Analist okuması (karar 10)

Her soruda iki `sw` `standard` koşusunun birleşiminden tohumla (2409261) çekildi. İlk okuyucu kampanya oturumu (kör
değil); ikinci okuyucu ilk hükmü görmeyen ayrı bir Sonnet oturumu, "ciddi" işaretli her birimi ve tohumla 5 ciddi olmayan
birimi okudu. İki okuyucu da modeldir.

| | q1 | q-tre |
|---|---|---|
| `include` (mevcut / okunan) | 21 / 10 | 8 / 8 |
| ciddi ölçüt hatası | 0 | 3 (ikisi iki okuyucuda da ciddi) |
| `criterion_not_met` (mevcut / okunan) | 2 / 2, ciddi 0 | 7 / 7, ciddi 0 (hepsi derleme ya da görüş yazısı) |
| `sw` iddiası (mevcut / okunan) | 26 / 10, ciddi 0 | 10 / 10, ciddi 0 |
| `legacy` iddiası (mevcut / okunan) | 24 / 10, ciddi 0 | 18 / 10, ciddi 0 |
| ikinci okuma | 5 birim, ayrılık 0 | 8 birim, ayrılık 1 |

Tıpta ciddi sayılan üç `include`:

1. Peeke 2021 (`10.1038/s41387-021-00149-0`): 14:10 TRE'yi 12:12 TRE ile ("active comparator") kıyaslıyor, iki kolda
   da kalorisi denetlenen diyet var. Serbest beslenme ya da olağan diyet kolu yok. İki okuyucu da ciddi dedi.
2. Xie 2022 (`10.1038/s41467-022-28662-5`): başlığı "healthy volunteers without obesity". Popülasyon soruya uymuyor. İki
   okuyucu da ciddi dedi.
3. Parr 2026 (`10.1007/s00125-026-06762-x`): TRE'yi bireysel diyetisyen rehberliğiyle kıyaslıyor (beş görüşmelik etkin
   bir program). İlk okuyucu ciddi, ikinci okuyucu "karşılaştırıcı tartışmalı, ciddi değil" dedi; kural gereği ciddi
   sayıldı ve ayrılık listelendi. Bu birim çıkarılsa da kapı 4 tıpta geçmez (2 ciddi).

Beklenti "ciddi PICO hatasının en olası yeri karşılaştırıcı, 10 `include`'da 0–1" idi: yer tuttu, sayı tutmadı. Üç
hatanın ortak kökü ölçütün kendisi: popülasyon ve karşılaştırıcı ayrı parça olmadığı için okuma bunları sormadı.

## G1: arXiv LaTeX kaynağı (karar 12)

Beş kuantum `sw` kütüphanesinde 58 arXiv makalesinin kaynağı indirildi; 40'ında okuma yerleşik blokla kaldı, 18'inde
hiçbir blok yerleşmediği için okuma geri çekildi. 1.160 numaralı denklem satırı, 878 aday, 642 yerleşik blok (tekil,
ürünün `read_source`'uyla yeniden üretildi 642/642). KaTeX 0.16.47 hatası 0. Tohumla (2409262) 40 blok çekildi (makale
başına en çok 2, dilim 22'nin örneğinden makale yok, 26 makale); 40'ı da görüntüde doğru grup ve doğru bölge (bir
okuyucu, kampanya oturumu). Bir notla: s06'da kutu bir sonraki metin satırına değiyor, ama saklı metin o satırı koruyor.
Kural dışı rapor: yerleşmeyen bloklar nedenlerine göre `macro_ambiguous` 141, `table_or_ocr_page` 58, `katex_unknown` 25,
`not_in_page_text` 11, `continues_after_number` 6, `ref_or_cite` 1, `foreign_text` 1; eşleşmeyen numaralı satır yaklaşık
275. Yerleşmeyenlerden tohumla 20'si okundu: hiçbiri yanlış gruba ait değil; 14'ü `macro_ambiguous` (12'sinde grubun
kendisinde kullanıcı makrosu yok, arşiv bütünüyle sınırsız sayıldığı için reddedildi), 2'si sayfada tam da kaynak
denklemi dururken çıkarmada reddedildi, 1'i tablo/OCR sayfası sayıldı ama sıradan bir denklem. Hepsi temkinli kuralın
kaybı, yerleştirme hatası değil. Yanlış blok olmadığı için yanlışların makalelere dağılımı yok.

Sınır: 40 blokluk görüntü örneği genel bir güvenilirlik sınırı değildir; bir okuyucu, bir model ailesi.

## `probe_report.py` satırları (ayrı eşleme)

Bu tablo `probe_report.py`'nin DOI / OpenAlex kimliği / başlıktan herhangi birine göre eşlemesidir; sözlüğün aşama
sayımlarıyla ve kapılarla karıştırılmaz. Referans eser sayısı (kol başına, yeni katkı):

| Araştırma | anahtar sözcük | genişleme (yeni) | zincir (yalnız zincir) |
|---|---|---|---|
| q1 standard r1 | 29 | 19 (0) | 7 (2) |
| q1 standard r2 | 30 | 26 (1) | 7 (1) |
| q1 quick | 17 | 17 (1) | 13 (5) |
| q1 detailed | 25 | 26 (3) | 7 (1) |
| q1 gömmeli | 27 | 3 (0) | 12 (3) |
| q-tre standard r1 | 3 | 3 (0) | 1 (0) |
| q-tre standard r2 | 3 | 3 (0) | 1 (0) |
| q-tre quick | 2 | 2 (0) | 2 (0) |
| q-tre detailed | 3 | 3 (0) | 2 (0) |
| q-tre gömmeli | 2 | 1 (0) | 1 (0) |

Sinyal satırları (bir-dışarıda, ilk 200'e etkisi, %95 aralık): kuantum `standard`'da blocks 0 ve +1, bm25 −1 ve 0, graph 0
ve +2, aralıkların hepsi 0'ı kapsıyor; gömmeli koşuda embedding +3 [−1, 7]. Tıpta bütün sinyaller 0 ya da ±1.

## Elle seçilmiş eşiklerin payları

- `FULLTEXT_WORK_LIMIT` (80 / 100 / 300): kuantum `standard`'da 31'in 10 ve 12'si yönlendirilip getirme sınırı yüzünden
  planlanmadı, en büyük tek kayıp. `detailed` (300) 23'ünü planladı, 22'sini okudu.
- `ABSTRACT_READ_LIMIT` (K3'ün N'i, 40 / 100 / 300): yukarıda; hepsini okumak için N ≈ 1.800.
- `SW_READ_LIMIT`: sınıra varan sorgu kuantum `standard`'da 5 ve 5, `quick` 4, `detailed` 5, gömmeli 3.
- Özet tamamlama (200 istek): kuantum `standard` r1 ve gömmeli koşuda sınıra varıldı (196 ve 179 kayıt sınır dışında).
- `ROUTE_SHARE` 0,25: iki soruda alan payları eşikten uzak (seçilenler 0,85–0,98, dışarıda kalanlar 0–0,005).
- Kimlik eşikleri: referans birimlerinde DOI ile başlığın farklı eserlere işaret ettiği çatışma ve bölünme bayrakları
  var (kuantumda g034 ve g047 her `sw` koşusunda, tıpta t02 `legacy`'de); ±0,05 bandındaki birleşmeler ölçülmedi.
- Alıntı alt sınırı 12 karakter: kısa diye reddedilen alıntı tıp `detailed`'da 1 (tam metin), diğer koşularda 0.
- Ölçüt önerisi 3 koşu / 2 çoğunluk: 10 `sw` koşusunun hepsinde üç koşu da geçerli döndü. Blok etiketleme eşikleri
  (3 / 2 / 40) protokolün `thresholds`'unda yazılı değil (planın kod bulgusu, SW19); `routing.THRESHOLDS` okunmuyor (SW20).

## `protocol.md`'den sapmalar ve kendi kararlarım

- **Sürücü çöktü, düzeltildi.** `q1-sw-standard-r1`'in okuma koşusu bittikten sonra `drive.py` bir `TypeError` ile
  düştü (kendi betiğimin hatası, ürünün değil). Hatayı düzelttim (dondurulmuş kopya `drive-frozen.py`), araştırmaya aynı
  veri dizininde devam ettim; yanıt koşusu 14:29'da başladı, 14:32'de bitti. Ürüne elle müdahale yok.
- **Ağ teşhisi yarım kaldı.** Kampanyanın sonunda `missed.py`'nin OpenAlex sorgu denetimleri 429 aldı: günün anahtarsız
  OpenAlex bütçesi kampanyanın kendi ürün trafiğiyle bitmişti (`x-ratelimit-remaining: 0`, sıfırlanma ~8,4 saat). Yalnız
  `q1-sw-standard-r1` tamamlandı (2 kaçan birimin 3 sorgu denetiminden 2'si bilinmiyor). Tıp için yalnız PubMed adımını
  koşan küçük bir yardımcı yazdım (`missed_pubmed.py`, donmadan sonra). Başlıkları okumak için OpenAlex'e tek bir ücretsiz
  tekil istek attım.
- **Donmadan sonra yazılan yardımcılar:** `report.py`, `packets.py` (biçimlendirme), `unplaced.py` (yerleşmeyen blok
  raporu), `missed_pubmed.py`. Hiçbiri kapıya giren bir sayıyı hesaplamaz.
- **Analist dosyası iki yerde.** `sample.py` okumayı `analyst/analyst-reading.jsonl`'dan, `gates.py` kök klasörden okur;
  dosyayı köke kopyaladım.
- **Durma kuralı yorumu:** model dışı duraklamalar kampanyayı durdurmaz (protokolde yazılı). Gömmeli tıp koşusunun
  yanıtsız bitişi bu yüzden kampanyayı durdurmadı.
- **İnceleyici rolü:** boş veri dizininin varsayılanı (yok), bu yüzden `answer_review` çağrısı yok.
- **Tıp referans kümesi:** "üç tablo" üç uygun ve açılabilen tablo diye okundu; tablosu açılamayan iki uygun meta-analiz
  (sıra 1 ve 4) atlandı. Yayıncının açık ek dosyasına bakıldı. Tablo satırlarının 7'si için PubMed'de ikinci bir arama
  (yazar, yıl, başlık sözcükleri) gerekti. Kararlar: Stratton ve sporcu popülasyonları dışarıda (popülasyon); Feehan'ın
  "standart bakım (diyet ve yaşam tarzı önerisi)" kolu olağan bakım sayıldı (R); Cai'nin TRF kolu tablodaki kalori
  kısıtlaması karşılaştırmasıyla "karşılaştırıcı farklı"; Lin (Tayvan) özetine göre "karşılaştırıcı farklı".
- **Elicit etiketleri:** özetten, Europe PMC'den birer istekle; Wilkinson 2026'nın standart diyet danışmanlığı kolu olağan
  bakım sayıldı ("kapsamda").
- **Analist okumasında karşılaştırıcı çizgisi:** kalori kısıtlaması, başka bir TRE takvimi ya da etkin bir diyet
  programı karşılaştırıcıyı "uygun değil" yapar; kısa standart diyet önerisi olağan bakım sayılır (Phillips 2021
  ciddi değil, Parr 2026 ciddi). Parr'da ikinci okuyucu ayrıldı.
- **Yerleşmeyen blok örneği:** 20'lik örnek için tohum `2409262-unplaced` (planda tohum yok).

## Ne ölçülmedi

- Gömmesiz tıp koşularında ve iki gömmeli koşuda `answer_review` (inceleyici yok).
- OpenAlex sorgularının kaçan eserleri bugün kapsayıp kapsamadığı (429; yalnız bir koşuda kısmen).
- 08c model terim önerisi, 13a şemaya uymayan modeller, 13b Crossref, 18a kurum vekili (planda "ölçülmez").
- Tıp sorusunda kapı 2 (|R| = 4). "Kapsamda" Elicit eserlerinin okununca `include` olup olmadığı (PDF yok).
- Kimlik eşiklerinin ±0,05 bandı.
- Bir yanıtın bilimsel doğruluğu. Analist okuması yalnız kendi alıntısına ve çapasına karşı okur.

## Yeni SW girişleri

`search-workflow-review-2026-09-18.md`'de SW18–SW25: tıp referans küme kuralı (SW18), blok etiketleme eşikleri
`thresholds`'ta yok (SW19), `routing.THRESHOLDS` okunmuyor (SW20), tıpta açık tam metin yok ve Europe PMC (SW21),
`include`'suz `sw` araştırmasının yanıtsız kalması (SW22), ölçütte popülasyon ve karşılaştırıcı (SW23), getirme sınırı ve
süre (SW24), kod sorgusunda kaynaşmış ifade (SW25). Anahtarsız OpenAlex günlük bütçesi de SW25'in altında not edildi.
