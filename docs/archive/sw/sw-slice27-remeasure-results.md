# SW dilim 27 — Tıp sorusunun yeniden ölçümü, sonuç

**Tarih:** 27 Eylül 2026. **Plan:** [sw-slice27-medicine-remeasure.md](sw-slice27-medicine-remeasure.md), commit
`bc64236b893ac38d085375cee41d9bfc6d42ca7a` (plandaki "Frozen expectations" bölümü o commit'le dondu). **Prompt:**
sw-slice27-prompt.md, Part B. **Sınanan kod:** `142dfa1` (25a ve 26),
`skill_package_hash` `sha256:a633e9c7091ed3338b0a51d3c7bdb99e524678f5cc4bdb60e1049d8b4a68028a`. **Kuantum yarısı:** dilim
24'ün klasöründen, `65a7ec8`. **Karar:** D108. **Klasör:** [.local/archive/sw/sw-slice27-remeasure-2026-09-27-043237/](../local-runs.md#run-archive-sw-sw-slice27-remeasure-2026-09-27-043237)
(`protocol.md`, `ledger.jsonl`, `gates.json`, `gate2-one-unit.json`, `analyst-reading.jsonl`). **Makine ve model:** bir M1
Pro, Python 3.12 arm64; her araştırmanın her rolünde Codex `gpt-5.6-luna` · medium. Her sayı tek koşudur.

## Kısa özet

Yedi tıp araştırması sırayla koştu ve yedisi de yanıtıyla bitti. Dört kapıdan ikisi geçti (1 tamamlanma, 3 kanıt
bütünlüğü), ikisi geçmedi (2 iş akışı karşılaştırması, 4 analist okuması). **Varsayılan `legacy` kalır.**

Referans kümesi (R) iki noktada sonradan seçilmiş kurallara dayanıyor ve bu yüzden kapı 2'nin tıp hükmü betimleyicidir:

- (b) koşulunda BMI vücut ağırlığı sayıldı. Bu genişlemeyi sahip, 25b |R| = 7'de durduktan ve kural dışı tahmini gördükten
  sonra seçti. Önceden sabitlenmiş bir kural değildir.
- Cienfuegos 2020 aynı deneme olduğu hâlde iki birim sayıldı (uyku yayını PMID 33759620 ve ana yayın PMID 32673591; ikisini
  bağlayan kayıt numarası yok, dilim 24'ün birim kuralı onları ayrı tutar). Tek birim sayılsaydı |R| = 11, bilinmiyor payı
  4 / 15 = %26,7 olurdu ve kâğıt denetimi hiçbir araştırma koşmadan dururdu.

Bu koşu varsayılanı değiştirmez; kapılar geçseydi de değiştirmeyecekti (planın 6. değişikliği). 24b bu dilimden koşmadı.

Kapı 2 tıpta havuzda geçti ama atıfta geçmedi: `sw` iki `standard` koşusunda R'den birer denemeye atıf verdi (ortalama 1),
`legacy` 4 ve 3 (ortalama 3,5). Tek birim okuması da aynı sonucu veriyor. Kayıp PDF aşamasında: `sw`'nin okumak için
seçtiği R denemelerinin çoğunun açık PDF'i yok ve bunlar Europe PMC'nin açık erişim alt kümesinde de değil. Kapı 4 tıpta,
okunan 10 `include`'un 3'ünde karşılaştırıcı hatasıyla geçmedi: üçünde de iki kol aynı kalori kısıtlamasındaydı.

Koşu sırasında PubMed'in arama arka ucu çöktü ("Search is temporarily unavailable ... Cannot connect to SOLR"). Yalnız ilk
araştırma (`sw` `standard` r1) PubMed kaydı aldı; sonraki altı araştırmada PubMed araması hata verdi ve ürün öbür
kaynaklarla devam etti. Bu, protokolde öngörülmemiş bir dış sapmadır ve havuz sayılarını etkiler (aşağıda).

## Referans kümesi (görev 2)

Kural: dilim 25'in karar 8'i, (b) "vücut ağırlığı ya da BMI havuzlanan sonuçlardan biri" diye genişletilmiş hâliyle;
deneme düzeyindeki "vücut ağırlığı raporlanmış" adımı genişletilmedi (D1). **Bu genişleme 25b durduktan sonra seçildi.**
25b'nin 26 Eylül sorgusu (90 kayıt) ve sırası, 1–30 arası aday kararları ve iki tablosunun 30 satırı kopyalandı, sha256
değerleri plana karşı denetlendi, yeniden okunmadı (A1, B1). Yalnız sıra 25 (PMID 41346676, PMC12672340) yeniden karar
aldı; onun tablosu plan zamanındaki ön işte okunmuştu ve koşuda yeniden okunmadı (C1). Kurucu, model oturumlarıdır
(25b ve plan ön işi); bir insan doğrulamadı.

| Adım | Okunan tablo | \|R\| | Bilinmiyor | Durma |
|---|---|---|---|---|
| sıra 9'dan sonra (PMC13215861) | 1 | 2 | 0 | hayır |
| sıra 25'ten sonra (PMC12672340) | 2 | 8 | 4 | hayır |
| sıra 30'dan sonra (PMC12479299) | 3 | 12 | 4 | evet |

Sonuç: **|R| = 12**, karşılaştırıcısı farklı 8, **bilinmiyor 4, pay %25,0**. Ön işin `r-estimate.json`'u ile sayıca ve
PMID bazında birebir aynı; kâğıt denetimi payla geçti (sınır "%25'ten fazla"), ama hiç payı yok. Açılamayan tablolar:
sıra 1, 18, 27, 28 (OUP 403, Cochrane PMC ambargolu ve site 403, ScienceDirect 403, OUP 403).

## Kapılar

Her kapının kuantum yarısı `65a7ec8`'de ölçülen dilim 24 sonucudur ve buraya taşındı (F1). Sade söylemek gerekirse: 25a ve
26'nın kod değişiklikleri saklı kuantum verisinde hiçbir şeyi değiştirmedi (yeniden oynatmalar), model tarafındaki yeni
metinler yalnız küçük kuru koşularda denendi ve orada da bir şey değiştirmedi; `142dfa1`'de tam bir kuantum araştırması
koşmadı. Yani her kapı hükmü iki farklı commit'in ölçümünü birleştiriyor.

| Kapı | Hüküm | Tıp (bu koşu, `142dfa1`) | Kuantum (`65a7ec8`, taşındı) |
|---|---|---|---|
| 1 tamamlanma (10 `sw`) | **geçti** | 5 / 5 `structurally_valid`; gömmeli ve `standard` r2 birer kez izinli sürdürmeyi kullandı (`client_timeout`, 10 dk bekleme) | 5 / 5 |
| 2 iş akışı karşılaştırması | **geçmedi** (tıp) | seçilen kuralla okunabilir; havuz geçti, atıf geçmedi; betimleyici ve sonradan seçilen kurala bağlı | geçti |
| 3 kanıt bütünlüğü | **geçti** | 5 `sw` yanıtında kötü bağ 0, `model_isolation_violation` 0, başka modelin oturumu 0 | geçti |
| 4 analist okuması | **geçmedi** (tıp) | 10 `include`'da 3 ciddi (sınır 1), 10 `sw` iddiasında 0 | 0 / 10 ve 0 / 10 |

### Kapı 2, iki okuma yan yana

Pay en büyüğü (2, ⌈0,1 × |R|⌉) = 2, her iki okumada da.

| | `sw` r1 | `sw` r2 | `legacy` r1 | `legacy` r2 | `sw` ort. | `legacy` ort. | Havuz | Atıf |
|---|---|---|---|---|---|---|---|---|
| Havuzda R, iki birim (\|R\| = 12) | 12 | 11 | 9 | 7 | 11,5 | 8,0 | geçti (11,5 ≥ 6,0) | |
| Atıf alan R, iki birim | 1 | 1 | 4 | 3 | 1,0 | 3,5 | | geçmedi (1,0 < 2,5) |
| Havuzda R, tek birim (\|R\| = 11) | 11 | 11 | 9 | 7 | 11,0 | 8,0 | geçti | |
| Atıf alan R, tek birim | 1 | 1 | 4 | 3 | 1,0 | 3,5 | | geçmedi |

Seçilen kuralla kapı 2 tıpta **geçmedi**; tek birim okumasında da kuralın aritmetiği geçmiyor (orada kâğıt denetimi zaten
dururdu). Bu betimleyici bir karar kuralıdır, istatistiksel bir sınama değildir. İki `sw` koşusu da yalnız Kotarsky 2021'e
(t02) atıf verdi. `legacy` iki koşuda da Lin 2023'e (t08) ve Maruthur 2024'e (t12), r1 ayrıca Cienfuegos 2020'nin ana
yayınına (t03) ve Lowe 2020'ye (t06), r2 Lowe 2020'ye atıf verdi; hepsi özetten.

**Kaybın yeri (kapı 2).** `sw` `standard` r1'de 12 R biriminin 12'si havuzda, 11'i tam metne yönlendirildi, 9'u okuma
planına girdi, ama yalnız 2'sinin PDF'i vardı (t02 ve t07, ikisi de `include`). Planlanıp PDF bulunamayan 7 birim
(`planned_no_pdf:no_fulltext`) ve getirme sınırında kalan 2 birim (t11, t12) okunmadı. r2'de 5 planlı, 2 PDF'li. Europe PMC
sayımı (`epmc.py`, R'nin PDF'siz her birimi için tek salt okunur istek): PDF'siz 10 birimin yalnız biri (t09, Domaszewski
2020) Europe PMC'nin açık erişim alt kümesinde, onu da `sw` hiç okuma planına almadı (N sınırı ya da havuz dışı). Yani kayıp
**Europe PMC'nin açık erişim alt kümesinin dışında**: PDF'i açık değil, Europe PMC'de de açık metni yok. Lin 2023 (t08)
bilindiği gibi yazar el yazması ve Europe PMC onu sunmuyor. Sonraki adım sahibin.

### Kapı 4

Tohum `2409261`, iki `sw` `standard` koşusunun birleşimi. Mevcut: 13 tekil `include`, 2 `criterion_not_met`, 12 `sw`
iddiası, 17 `legacy` iddiası. Okunan: 10 / 2 / 10 / 10. İlk okuyucu bu koşunun oturumu (kör değil); ikinci okuyucu ilk
hükmü görmeyen ayrı bir Sonnet oturumu, 3 ciddi ve tohumla 5 ciddi olmayan birimi okudu. İkisi de modeldir.

| | Okunan | Ciddi | İkinci okuma |
|---|---|---|---|
| `include` | 10 | **3** | 3 ciddinin 2'sinde aynı, 1'de ayrıldı (kural gereği ciddi) |
| `criterion_not_met` | 2 | 0 (ikisi de derleme ya da görüş yazısı) | 1 okundu, aynı |
| `sw` iddiası | 10 | 0 | 1 okundu, aynı |
| `legacy` iddiası | 10 | 0 | 2 okundu, aynı |

Ciddi üç `include`, üçü de karşılaştırıcı:

1. Cell Reports Medicine 2024 (`10.1016/j.xcrm.2024.101801`): dört kollu, sağlanan öğünlerle yürüyen bir "isocaloric-restricted"
   besleme denemesi; s. 14 TRE'yi aynı kalori kısıtlamasıyla kıyaslıyor. İkinci okuyucu "kontrol kolu olağan düzen, ciddi
   değil" dedi; ayrılık listelendi ve kural gereği ciddi sayıldı.
2. Life Medicine 2022 (`10.1093/lifemedi/lnac017`): TREATY denemesi üzerine bir yorum; TRE artı kalori kısıtlaması, yalnız
   kalori kısıtlamasına karşı. İki okuyucu da ciddi dedi.
3. Alimentary Pharmacology & Therapeutics 2025 (`10.1111/apt.70044`): MASLD'li, BMI ≥ 25 hastalar; üç kol da aynı hipokalorik
   Akdeniz diyetinde (s. 3: dinlenme harcamasının 500 kcal altında). İki okuyucu da ciddi dedi.

Birinci madde çıkarılsa da kapı 4 tıpta geçmez (2 ciddi). Üç hatada ölçüt parçası vardı (karşılaştırıcı, D106'nın
getirdiği), ama okuma "zaman kısıtlaması olmayan kontrol grubu" alıntısını parçayı karşılamaya yeterli saydı; iki kolda da
kalori kısıtlaması olduğunu sormadı. Bu kayıp PDF aşamasında değil, okumada. Ayrıca `include`'lardan ikisi (TREATY ve
IMIFASTT) denemenin kendisi değil, deneme üzerine yazılmış kısa yorumlar; kapı 4'ün tanımı yayın türünü ciddi saymadığı
için yalnız not edildi.

## Araştırmalar

| Araştırma | Durum | Süre (dk) | 24a | Çağrı | 24a | Giriş / önbellek / çıkış jetonu | Havuz (eser) |
|---|---|---|---|---|---|---|---|
| qtre-sw-standard-r1 | bitti | 15,7 | 12,8 | 122 | 82 | 1.334.010 / 175.360 / 133.857 | 4.536 |
| qtre-legacy-standard-r1 | bitti | 7,9 | 7,8 | 9 | 9 | 276.503 / 5.888 / 19.499 | 184 |
| qtre-sw-quick-r1 | bitti | 12,5 | 8,3 | 82 | 47 | 842.890 / 174.080 / 75.716 | 3.684 |
| qtre-sw-detailed-r1 | bitti | 43,0 | 30,2 | 330 | 173 | 3.439.303 / 606.720 / 331.333 | 4.031 |
| qtre-sw-standard-emb-r1 | bitti | 42,2 (10 dk bekleme dahil; kurulum 3 dk 11 s ayrı) | 21,7, yanıtsız | 90 | 71 | 900.323 / 128.000 / 79.293 | 8.008 |
| qtre-sw-standard-r2 | bitti | 31,5 (10 dk bekleme dahil) | 13,1 | 124 | 62 | 1.184.565 / 179.712 / 112.007 | 3.747 |
| qtre-legacy-standard-r2 | bitti | 7,5 | 7,1 | 9 | 9 | 279.535 / 81.152 / 21.197 | 188 |

Toplam 766 Luna çağrısı (24a'nın tıp satırları 453), 8,26 M giriş / 0,77 M çıkış jetonu; ilk araştırmanın başlangıcından
sonuncunun bitişine 2 sa 58 dk (04:38–07:36, iki 10 dakikalık bekleme ve altı 2 dakikalık ara dahil). Çağrı artışı neredeyse
tümüyle tam metin okumasında: okunan eser arttı (Europe PMC).

| Aşama, R üzerinden (n / 12) | sw std r1 | sw std r2 | quick | detailed | gömmeli | legacy r1 | legacy r2 |
|---|---|---|---|---|---|---|---|
| havuz | 12 | 11 | 11 | 12 | 9 | 9 | 7 |
| özet adayı / yönlendirilen | 11 / 11 | 9 / 9 | 9 / 9 | 12 / 12 | 8 / 8 | — | — |
| okumak için planlanan | 9 | 5 | 9 | 12 | 5 | — | — |
| PDF'li / okunan | 2 / 2 | 2 / 2 | 2 / 2 | 3 / 3 | 2 / 2 | — | — |
| `include` (`legacy`: taramada dahil) | 2 | 2 | 1 | 1 | 2 | 9 | 7 |
| atıf alan | 1 | 1 | 1 | 0 | 1 | 4 | 3 |

Elicit'in beşi (liste, doğruluk ölçütü değil): havuzda `sw` 4–5 / 5, `legacy` 4 / 5; `sw` hiçbirini `include` etmedi ve
hiçbirine atıf vermedi (PDF'li 0–1 / 5), `legacy` 3 / 5 ve 2 / 5 atıf verdi.

## Dondurulmuş beklentiyle yan yana

| Beklenti (plan, "Frozen expectations") | Ölçülen | Tuttu mu |
|---|---|---|
| 5 / 5 `sw` uzlaşmasında popülasyon ve karşılaştırıcı parçası, sözcükler sorudan | 5 / 5 `required_roles = ["comparator", "population"]`; parçalar "adult overweight or obesity population" ve "unrestricted eating or usual diet comparator" | tuttu |
| Europe PMC, `standard` koşusunda PDF'siz planlı işlerin %20–40'ına tam metin verir | Europe PMC'den inen: 112 planlı eserin 29'u ve 28'i (%26 ve %25; payda bütün planlılar, PDF'sizler üzerinden pay biraz daha yüksek); PDF'li planlı iş 48 ve 55 (24a: 29 ve 19) | tuttu |
| `standard` başına `include` 3–9, birleşim 5–12 tekil (zayıf) | 9 ve 9; birleşim 13 tekil | koşu başına tuttu, birleşim bir fazla |
| Çekilen `include`'larda ciddi PICO hatası 0–1 | 3 (karşılaştırıcı) | tutmadı |
| `include`'suz biten `sw` 0–2 / 5, her biri açık yanıtla | 0 / 5 | tuttu |
| `part_without_evidence` 24a'nın 8–28'inden büyük (zayıf) | `standard` 29 ve 28, `detailed` 107, `quick` 16, gömmeli 12 | `standard` ve `detailed`'da tuttu, öbür ikisinde tutmadı |
| Kapı 1 ve 3 geçer; 2 ve 4 belirsiz | 1 ve 3 geçti; 2 ve 4 geçmedi | tuttu |
| Süre ve çağrı 24a'nın ±%30'u | çağrı +%69 (766 / 453), süre `sw` satırlarında belirgin uzun | tutmadı |
| \|R\| = 12, bilinmiyor 4 (%25,0), birebir yeniden kurulur | birebir | tuttu |
| 5 / 5 `sw` kod sorgusunda `time-restricted eating` ve `body weight` ayrı, kaynaşık ifade yok | 5 / 5: `time-restricted eating` görev bloğunda, `body weight` üç etiketleme koşusunun üçünde `outcome`; `time-restricted eating reduce body weight` hiçbir arama satırında yok (beş araştırmanın 256 arama satırının 0'ı). Sonuç bloğu aranmıyor, yani `body weight` aranan bir blokta değil | tuttu |
| 24a'nın üç protokol eseri hiçbir araştırmada `include` olmaz | 0 `include`; ENSATI `detailed`'da `protocol_title` (kuyruk, `confirm_results`), öbür okumalarda modelin kendi `part_without_evidence` / `fulltext_runs_disagree` / `include_quote_unverified` kararı ya da okunmadı | tuttu |
| `detailed`'ın `include`'u 24a'dan az (zayıf) | 15 (24a 16) | tuttu (bir eksik) |
| Kapı 2: havuz belirsiz; `legacy` Lin 2023'e yine atıf verirse atıf yarısı zorlaşır | `legacy` iki koşuda da Lin 2023'e atıf verdi; `sw` iki koşuda birer R atfı; atıf yarısı geçmedi | tuttu |

## Raporlanan, kapıya girmeyen

- **`protocol_title` satırları:** yalnız `detailed`'da 2 (ENSATI ve "Isolated and combined effects of high-intensity
  interval training and time-restricted eating …"), ikisi de kuyrukta `confirm_results`.
- **Kod sorgusu:** beş `sw` araştırmasında da ayar bloğu `adults, obesity, overweight` (r1'de ek olarak `randomised
  controlled trials`), görev bloğu `time-restricted eating, usual diet, unrestricted eating`. Ölçüt ifadelerinde modelin
  ürettiği bozuk bir ifade (`自由 eating`) dört koşuda göründü; aramaya girmedi, ama bir not olarak kaydedildi.
- **Kuyruk** (API ile sürüm düzeyi aynı): `standard` 37 ve 35, `quick` 24, `detailed` 127, gömmeli 15; çoğu
  `part_without_evidence` (29, 28, 16, 107, 12). PDF bekleyen: 63, 56, 56, 162, 61.
- **Yönlendirme:** `sw` araştırmaları OpenAlex, Semantic Scholar, bioRxiv ve PubMed'i seçti; `quick`'te yine PubMed arama
  satırı yok (24a'daki gibi, nedeni ölçülmedi). Semantic Scholar `quick` ve `standard` r2'de bir kez `rate_limited`.
- **PubMed kesintisi:** PubMed yalnız `sw` `standard` r1'de 27 sayfa getirdi (01:41Z). Sonraki bütün araştırmalarda
  esearch ya HTTP 200 ile `esearchresult.ERROR` ("Search is temporarily unavailable ... Cannot connect to SOLR";
  ürün `parse_error` yazdı) ya da HTTP 500 döndü. Ürün hatayı kaydedip öbür kaynaklarla sürdü (D18). `legacy` iki koşuda da
  PubMed'siz. Bu, `sw` r2'nin, gömmelinin, `detailed`'ın ve iki `legacy`'nin havuzunu küçültmüş olabilir; ne kadar
  küçülttüğü ölçülmedi.
- **Kaçırılan eser teşhisi** (`missed.py`, "bugün" kapsıyor mu; koşunun gördüğü değil): `sw` r1 ve `detailed` 0 kaçan;
  `quick` 1 (t04, hiçbir OpenAlex sorgusu bugün kapsamıyor); `sw` r2 1 (t11, bir OpenAlex sorgusu bugün kapsıyor, PubMed
  yanıtları 500). Gömmeli ve iki `legacy` için teşhis tamamlanamadı: PubMed 08:40'a kadar yanıt vermedi (ölçülmedi).
- **K3:** R'nin havuzda bulunan birimlerini okumak için gereken N: `standard` r1 117, r2 527, `quick` 16, `detailed` 107,
  gömmeli 280; N'de kalan birimler r1 t09, r2 t09, `quick` t09 ve t11, gömmeli t03.
- **24a ile yan yana `part_without_evidence`:** yukarıdaki beklenti tablosunda.

## Protokolden sapmalar

1. **PubMed kesintisi** (dış, öngörülmemiş): yukarıda. Protokol ek koşuya izin vermediği için hiçbir araştırma
   tekrarlanmadı.
2. **İki izinli sürdürme:** gömmeli (06:36) ve `standard` r2 (07:13), ikisi de `client_timeout`, kurala göre 10 dakika
   sonra bir kez sürdürüldü. Başka elle müdahale yok.
3. **`net-cache/` klasörü yoktu:** kopyalanan `net.py` önbelleğini klasörde arıyor; yeni klasörde olmadığı için `missed.py`
   beş araştırmada ilk isteğinde durdu. Boş klasör açıldı ve `post25.py` o beşi için yeniden koştu; betik değişmedi.
4. **PubMed hata yanıtı önbelleğe yazıldı:** `missed.py`, HTTP 200 ile gelen `esearchresult.ERROR` yanıtında (`count`
   yok) duruyor ve `net.py` o yanıtı önbelleğe almıştı. Hatalı önbellek dosyaları silindi ki istekler yeniden denensin;
   betik değişmedi. Ayrıca PubMed'in açılıp açılmadığını görmek için `net.py` dışından birkaç tek istek atıldı.
5. **`gates25.py` mutlak yolla çalıştı:** `.` verildiğinde dilim 24 klasörünü göreli yoldan bulamadı; klasörün mutlak yolu
   verildi. Kod değişmedi.
6. **`compare_estimate.py` bir kez çöktü:** kendi kâğıt denetimi satırındaki bir biçim hatası yüzünden, R karşılaştırma
   kaydını yazdıktan sonra. Düzeltilip yeniden koştu; defterde karşılaştırma kaydı iki kez var (ikisi de "equal").
7. **Kapı 2'nin tek birim okuması ayrı bir betikte** (`gate2_oneunit.py`, `gate2-one-unit.json`); `gates25.py` dilim 25'in
   tarif ettiği hâliyle kaldı.
8. **`include`'suz yanıtın okuması** (dilim 25 karar 9): Kapı 1 ve 2'nin `include`'suz yanıt okuması dondurulmuş bir kapının
   adıyla yazılmış tek okumadır; bu koşuda hiçbir `sw` araştırması `include`'suz bitmediği için etkisi olmadı.

## Ölçülmedi

- `142dfa1`'de tam bir kuantum araştırması (F2 açık; sahibin kararı).
- PubMed kesintisinin havuz ve `include` sayılarına etkisi; PubMed'li bir ikinci koşu yapılmadı.
- Gömmeli araştırmanın ve iki `legacy` araştırmasının kaçırılan eser teşhisi: `missed.py` PubMed'in hata yanıtında
  duruyor; PubMed 07:43–08:40 arasında beş dakikada bir denendi ve açılmadı, bu üçünün `missed-*.json`'u yok.
- R'nin 12 biriminden kaçının Europe PMC'de yazar el yazması olarak durduğu (yalnız açık erişim alt kümesi soruldu).
- Rank 25'in 11 satır kararının ve 25b'nin 30 kararının ikinci bir okuyucuyla uyumu.
- Bölünmüş kod sorgusunun havuz büyüklüğüne etkisi (PubMed kesintisiyle karıştı).
- Kapı 4'ün `include` hatalarının kaç tanesinin yalnız karşılaştırıcı parçasının tanımı yüzünden olduğu (tek soruda,
  tek koşu).
