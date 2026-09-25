# SW dilim 22 — arXiv LaTeX kaynağından denklem okuma

**Tarih:** 25 Eylül 2026. **Durum:** plan hazır (Sol r9 "hazır"); A1, B1, C1, D3, E1, F1 önerildiği gibi
(sahip soru sorulmadan ilerlenmesini istedi, 2026-09-25; D'nin önerisi Sol r1 bulgu 2 üzerine D1'den D3'e değişti).
**İkinci görüş:** `gpt-6-sol` · high r1 "hazır değil", 11 bulgu; r2 "hazır değil", r1'in 7'si kapandı, 4'ü kısmen,
5 kalan çelişki; r3 "hazır değil", 4 bulgu ve 5 değişiklik; r4 "hazır değil", 4 bulgu; r5 "hazır değil", 3 bulgu; r6 "düzeltmeyle
hazır", 3 bulgu; r7 "düzeltmeyle hazır", 2 bulgu; r8 "düzeltmeyle hazır", 2 bulgu; hepsi işlendi (son sekiz bölüm "Sol r1
bulguları" … "Sol r8 bulguları"). r9 "hazır" (r8'in iki bulgusu kapandı, yeni çelişki yok). **Prompt:** [sw-slice22-prompt.md](sw-slice22-prompt.md). **Ana dosya:** [sw-status.md](sw-status.md).
**Karar:** yeni D numarası (dilim yazar; en yüksek D103, yani D104). **Migration:** `0054` (en yüksek `0053`).
**Önkoşul:** 10 (D83), kapandı; D52 / D62'nin Marker yolu, D45'in yeniden çıkarım kuralı ve D48 / D100'ün sürüm seçimi
bu dilimin girdisidir. **Tür:** Kur (ölçülmedi): eşlemenin bir ön-örneği saklı veride ölçüldü ve bir örneklemi sayfa
görüntüsünden okundu; ürün yolu ölçülmedi. **Uygulayan:** Opus · high. **İnceleme:** toplu (Sol · high). **Plan:**
Opus 5.5 · high. **Ölçüm:** `.local/sw-slice22-plan-2026-09-25/`. r1: `inventory.py` → `inventory.json`,
`fetch_sources.py` → `fetch.json` ve `fetch-export-host-406.json`, `src/` 53 kaynak dosyası, `match_equations.py` →
`match-recall0.9-m0.2.json` (ana), `-guard.json`, `-pagetext.json`, `match-f10.8-m0.1.json`, `classify_disagreements.py`,
`macro_check.py` → `macro-check.json`, `export_groups.py` + `katex_check.cjs` / `katex_check2.cjs` → `katex-check*.json`,
`tar_sizes.py` → `tar-sizes.json`, `summary.py` → `summary.json`. r2: `match_r2.py` → `match-r2.json`, `summary_r2.py`
→ `summary-r2.json`, `summary_r2_final.py` → `summary-r2-final.json`, `foreign_words.py`, `image_sample2.py` +
`match_r2.py` → `img/`, `img2/`, `image-sample*.json`, `image-check.json` (görüntüden okuma kararları), `region_lines.py`,
`record_versions.py` → `record-versions.json`, `expansion_sizes.py` → `expansion-sizes.json`,
`migration/draft_0054_passages.sql` + `migration/check_rebuild.py` → `migration/rebuild-check.json`. Canlı kütüphane
salt okunur açıldı (`mode=ro`) ya da SQLite yedek API'siyle geçici bir kopyaya alındı (kopya işten sonra silindi);
ürünün kodu, venv'i ve `uv.lock` değişmedi; model, port ve Marker koşturulmadı; tek ağ erişimi r1'deki arXiv
istekleri (r2'de ağ yok). **Kapsam:** SW10 madde 6 (a)'nın denklem kısmı, madde 7'nin eşleme kısmı ve madde 8, yalnız
Marker kurulu olmayan kişi için. Düzyazı, 6 (c), Marker'lı kişi için kaynak ve tam metin koşuları bu dilimde yok;
nedenleri "SW10'dan sapmalar"da.

**Goal:** Bir PDF arXiv'in bir sürümüyse ve denklem okuyucusu (Marker) kurulu değilse, yazarların o sürüme ait LaTeX
kaynağı indirilir, makroları açılır ve her numaralı görüntü denklemi PDF sayfasındaki numarasıyla bulunup harfleriyle o
sayfaya eşlenir. Eşleme planın eşiğini geçerse denklem, sayfanın metin katmanındaki bozuk hâlinin yerine yazarların
LaTeX'i olarak girer; geçmezse o denklem metin katmanında kalır. Marker kuruluysa hiçbir şey değişmez: Marker bugünkü
sayfaları bugünkü gibi okur (D3). Kaynaktan gelen denklem hangi arXiv sürümünden geldiğini taşır. Bu dilim hız
getirmez; getirisi, Marker'ı kurmamış kişiye bayrak açıldığında yazarların numaralı denklemlerini vermektir (soru A, F).

## Bugün kod ne yapıyor

Kod 25 Eylül 2026'da `af9d0ce` üzerinde okundu (`documents/pdf.py`, `documents/math_reader.py`,
`documents/inline_math.py`, `documents/fetch.py`, `documents/acquisition.py`, `workflow/equations.py`,
`workflow/flow.py`, `workflow/store.py`, `workflow/views.py`, `providers/arxiv.py`, `config.py`, `api/app.py`,
`storage/db.py`, `domain/contracts.py`, `contracts/research/step-input.schema.json`, `report-section-draft.schema.json`,
yöntem paketi, `apps/web/src/labels.ts`, `PassageSheet.tsx`, `MathText.tsx`, `api.ts`; migration `0001`, `0030`;
canlı şema).

- **Metin katmanı.** `pdf.extract_pdf` (`pdf.py:213`) PyMuPDF'i alt süreçte, 90 sn zaman aşımı ve 1 GB bellek
  bekçisiyle koşturur (`:47-49`, `:198-210`); sayfa metni blok düzeninden kurulur (`_blocks` `:83`, `_page_text` `:140`,
  sürüm `pymupdf-1.28.2-layout-v2`, `:42`). Döndürülmüş satırlar atılır (`:89`), arXiv'in kenar damgası da bu yüzden sayfa
  metnine girmez. Görüntü denklemleri harf harf ama bozuk gelir: simge fontlarında `(`→`p`, `)`→`q`, `=`→`“` (canlı
  kütüphanede `2005.00948v1` s. 3: `PXT pxT “ N0q “ … 1 / 2 / (1)`). `chunk_page` (`:244`) 1.400 karakterde keser ve
  `(başlangıç, bitiş, metin)` döndürür; D54'ün tablo satırı kuralı dışında `$$…$$` bloğunu korumaz.
- **Pasaj yazımı.** `store._write_extraction` (`store.py:1336`) her parçayı `payload_ref = "chars:<başlangıç>-<bitiş>"`
  ile yazar ve etiketi sayfadan alır (`getattr(page, "text_source", "text_layer")`, `:1343`): bir sayfanın bütün
  parçaları aynı etiketi taşır.
- **Marker yolu (D52, D62).** `EquationService._read` (`equations.py:109`) Marker kurulu değilse
  `MathReaderUnavailable` verir (`:118`); kuruluysa metin katmanını yeniden çıkarır, `math_pages` (60 matematik fontu
  karakteri ya da 12 simge, `math_reader.py:189`) ∪ `table_pages` (`:206`) ∪ OCR sayfalarını seçer (`equations.py:130`),
  okutur, `merge` (`math_reader.py:124`) Marker'ın sayfa metnini koyar, sürüm `…+marker-1.10.2-math-v2` olur
  (`math_reader.py:68`), yazma `store.reextract_asset` (`equations.py:153`). Durum `equation_state` (`:45`) güncel sürümü
  `target_version` (`:39`) ile karşılaştırır; D45'in reddettiği okuma deneme sayısı taşımaz ve kendiliğinden yeniden
  denenmez (`:62-63`). Arka plan okuyucu (`run_forever`, `:217`) yalnız Marker kuruluyken iş alır (`:222`), `next_asset`
  (`:200`) etkin koşusu olan araştırmanın PDF'ine dokunmaz. Yanıt koşusu (`flow.py:2465`), tablo doldurma (`:4360`) ve
  hücre yeniden denetimi (`:4465`) `_read_equations` (`:2634`) ile bekler: Marker yoksa hiç beklemez (`:2641`); adım
  `succeeded` ya da `failed` ise atlanır (`:2648`); `failed` durum koşuyu duraklatır (`:2660`), öbür her durum adımı
  `succeeded` bitirir (`:2663`).
- **D45.** `reextract_asset` (`store.py:1353`) yeni çıkarımı durumu daha kötüyse, sayfa sayısı farklıysa ya da daha az
  sayfada metin varsa reddeder ve eski metni tutar (`:1373-1379`); aynı sürüm zaten varsa `unchanged` döner (`:1364`);
  başka bir araştırmanın etkin koşusu varsa `RunInProgress` verir (`:1393-1398`).
- **Metin kaynağı etiketi.** `passages.text_source` `CHECK (text_source IN ('text_layer', 'ocr', 'marker'))`
  (migration `0030`, `ALTER TABLE … ADD COLUMN`); `passages_fts` `content='passages', content_rowid='rowid'` ile dış
  içerikli FTS5 (`0001_initial.sql:189`), iki tetik (`passages_fts_insert`, `passages_no_update`), `passages_source`
  dizini. `cell_evidence_links` üzerindeki `cell_evidence_same_source` tetiği `passages`'a başvurur (canlı şema). Etiket
  StepInput'a gider (`flow.py:4596`, `store.py:521`); rapor taslağının `equation_origin.text_source`'u aynı üç değerle
  sınırlıdır (`report-section-draft.schema.json:76`, sürüm `deixis.report_section_draft.v1`, `domain/contracts.py:66`).
  Şemanın açıklaması "checked in code" der (`:89`), ama hiçbir kod `equation_origin`'i denetlemez
  (`_check_report_section`, `contracts.py:1055`; depoda yalnız yazılıyor, `report/store.py:198`). Arayüz Marker
  sayfasına uyarı koyar (`PassageSheet.tsx:150`), kaynak satırında denklem durumunu yazar (`labels.ts:230-235`);
  `$$…$$`'ı KaTeX 0.16.47 `throwOnError: false` ile çizer (`MathText.tsx:16`). Görünüm reddedilen yeniden çıkarımı
  gösterir, `+marker-` sürümlerini hariç tutarak (`views.py:440-442`).
- **Migration yöneticisi.** `-- deixis:foreign-keys-off` ile başlayan dosyada yabancı anahtarlar kapanır, deyimler tek
  işlemde koşar, `foreign_key_check` işlemden önce ve sonra denetlenir (`db.py:15`, `:70-87`).
- **arXiv kayıtları ve sürümler.** arXiv sağlayıcısının kaydı `arXiv vN` etiketini taşır (`providers/arxiv.py:53`); bir
  ön baskının bütün sürümleri tek DOI altında tek iştir (D46); OpenAlex'in arXiv konumundan ya da D83'ün başka sürüm
  aramasından gelen satırın etiketi sağlayıcının beyanıdır (`submittedVersion`; `acquisition.py:327`). Yanıtın okuduğu
  sürümü `store.answer_version` seçer (`store.py:1857`, D48, dilim 18b).
- **İndirme.** `fetch.fetch_pdf` (`fetch.py:105`) genel adres denetimi, sabitlenmiş bağlantı, en çok 5 yönlendirme, 30 MB
  (`:24`), 30 sn zaman aşımı (`:25`), e-posta taşımayan bir User-Agent (`:27`) ve ana makine başına tek istek
  (`host_gate`, `:48`) uygular, yanıtı bellekte döndürür ve yalnız PDF kabul eder. arXiv araması 3 sn aralık kuralını
  kendi kilidiyle tutar (`providers/arxiv.py:29`, `:40-41`) ve 406'yı hız sınırı gibi okur (`:33-36`).
- **Kaynak getiren kod yok.** Depoda `e-print`, `arxiv.org/src` ya da kaynak arşivi okuyan hiçbir satır yok.
- **Bayrak deseni.** Keşif dışı akışlar `Settings` alanı ve ortam değişkeniyle açılıp kapanır (`fulltext_fetch`,
  `config.py:36`, `:115`; `citation_chaining` sınıfta `off`, `:49`).

## Elimizdeki sayılar

Ölçüm Apple M1 Pro (10 çekirdek, 32 GB), yerel arm64 Python 3.12, PyMuPDF 1.28.2, httpx 0.28.1, Node + KaTeX 0.16.47
(web uygulamasının kopyası). Veri: varsayılan veri dizinindeki canlı kütüphane (şeması migration `0036`'da; depo `0053`'te)
ve onun arXiv PDF'leri, üç alan (moleküler iletişim, kuantum ağları, kablosuz algılayıcı ağları ve rastgele çizgeler).
Tek bilgisayar, tek kütüphane. "Sürüm" aşağıda bir arXiv sürümü başına bir PDF demektir (aynı sürümü taşıyan ikinci PDF
sayılmaz).

1. **Hangi sürüm okundu.** Canlı kütüphanede arXiv'den gelen ya da arXiv DOI'li 56 PDF (53 ayrı sürüm) var. 48'inin
   adresi sürümü adlandırıyor (`arxiv.org/pdf/<id>vN`); 51'inin ilk iki sayfasının metin katmanında arXiv damgası var
   (`arXiv:2005.00948v1 [cs.ET] 2 May 2020` biçimi). İkisini de taşıyan 43'ün 43'ünde sürüm aynı; adresinde sürüm olmayan
   8'in 8'inde damga var; hiçbirini taşımayan PDF yok (`inventory.json`).
2. **Kaydın sürümü.** Aynı 56 PDF'in 48'i `arXiv vN` etiketli bir kayda bağlı ve N dosyanınkiyle aynı; 8'i
   `submittedVersion` etiketli kayda bağlı (7'sinin DOI'si arXiv DOI'si, 1'inin yayıncı DOI'si); yayımlanmış ya da kabul
   edilmiş sürüm kaydına bağlı olan yok; 56'sı da sağlayıcıdan, kişinin yüklediği yok (`record-versions.json`). 56
   kaydın 56'sı DOI'sinde (`10.48550/arXiv.<id>`) ya da `landing_url` / `oa_pdf_url`'sinde bir arXiv kimliği taşıyor ve
   56'sında bu kimlik dosyanınkiyle aynı (`record_ids.py` → `record-ids.json`). Kaydın etiketi tek başına kimlik
   taşımaz; karar 1 kimliği ayrıca ister.
3. **Kaynağı getirmek.** `https://arxiv.org/e-print/<id>vN` adresine 53 istek, 3,5 sn aralıkla, httpx ile: 53'ü 200. 45'i
   `.tex` taşıyan arşiv (%85), 5'i yalnız PDF, 3'ü `.tex`'siz (yalnız DVI ve EPS). Süre ortanca 0,93 sn, en çok 17,2 sn;
   boyut ortanca 0,91 MB, en çok 19,8 MB, toplam 89,8 MB (`fetch.json`). Yanıt başlığındaki dosya adı istenen sürümü
   adlandırıyor (`arXiv-2005.00948v1.tar.gz`). **`export.arxiv.org` httpx'e 406 veriyor:** aynı istemciyle 53 istekte
   52 kez 406 ve başlıklar, TLS bağlamı ve User-Agent değiştirilerek yapılan 7 tekil denemede 7 kez 406; aynı dosyaları
   curl ve Python'un `urllib`'i 200 aldı. Neden bilinmiyor; `arxiv.org` üzerinde sorun görülmedi.
4. **Arşivin şekli.** 48 tar'da en çok 234 üye, açılmış toplam en çok 27,7 MB, `.tex` dosyası en çok 13, `.tex` baytı en
   çok 0,28 MB; sembolik ya da sert bağlantı 0, mutlak ya da `..` içeren ad 0 (`tar-sizes.json`). Bunlar zararsız
   arşivlerin ölçüsüdür; kötü niyetli bir arşiv için sınır değildir (karar 3 sınırları ayrıca koyar).
5. **Makro açma.** 45 kaynakta 1.184 tanım (`\newcommand`, `\renewcommand`, `\providecommand`, `\def`,
   `\DeclareMathOperator`); açıldıktan sonra kaynağın kendi makrosunu hâlâ taşıyan görüntü grubu 2.189'da 0
   (`macro-check.json`), ama bu beş biçim dışındaki tanımlar (`\DeclarePairedDelimiter`) sayılmadı: görüntü örneğinde
   `1808.04273v1`'in `\paren`'i açılmadan kaldı (karar 3'ün KaTeX kapısı onu yerleştirmez). Açıcı makale başına en çok 377
   kez çağrıldı ve en çok 0,021 sn sürdü; açılmış 2.189 grubun %99'u en çok 903 karakter, 4.000'i aşan 2 grup var ve
   ikisi de numarasız (en uzunu 36.554, `expansion-sizes.json`).
6. **KaTeX.** Temizlenmiş 2.188 görüntü grubunun 200'ü (%9,1; 23 kaynakta) KaTeX 0.16.47'de çizilemedi. Yedi kurallık bir
   yeniden yazma tablosuyla (`\mbox`→`\text`, `\mathds`→`\mathbb`, `\buildrel`→`\overset`, `\mathlarger` / `\mathsmaller`
   / `\lefteqn` / `\sl` / `\em` / `\hfill` / `\hfil` / `\displaybreak` silinir, `\iffalse…\fi`, `\cite{…}`, `\ding{…}`
   silinir) 57 (%2,6; 15 kaynakta) (`katex-check.json`, `katex-check-rewrite.json`).
7. **r1'in eşleme kuralı ve Marker'la uyum.** r1 kuralı (karar 4'ün eski hâli: geri çağırma ≥ 0,90 ve sıranın izin verdiği
   gruplara karşı F1 farkı ≥ 0,20), kaynağı ve Marker okuması olan 44 sürümün Marker'ın okuduğu 369 sayfasında: 1.494
   numara satırının 900'ü eşiği geçti (%60); Marker'ın aynı numaraya bir denklem bulduğu 835'in 786'sında (%94,1)
   seçilen grup Marker'ın okumasına en yakın grupla aynı ya da ona en az 0,85 benzer. Marker ölçüt değildir (D52'de %96'sı
   tam doğru bir başka okuyucu); eşikler bu veride seçildi.
8. **Sıra kısıtı farkı boşaltıyor (Sol r1 bulgu 1).** Aynı kural 43 sürümün bütün sayfalarında 1.520 numara satırının
   924'ünü geçiriyor. Bunların 774'ünde (%84) sıranın o noktada izin verdiği pencerede hiçbir rakip grup yok, 111'inde
   tek rakip var: r1'in 0,20 farkı çoğu yerde sıfıra karşı ölçülmüş, yani fiilen yalnız geri çağırma denetlenmiş. Fark
   makalenin bütün öbür gruplarına karşı (LaTeX'i seçilenle aynı olanlar hariç) ölçülünce 924'ün 448'i (%48) geçiyor;
   kalan 477'yi harfler değil sıra seçmiş. 477'nin 38'inde sıra harfleri ezmiş: seçilen grubun F1'i makaledeki bir başka
   grubun F1'inden düşük (`summary-r2.json`, `summary-r2-final.json`).
9. **Sayfa görüntüsünden okuma (Sol r1 bulgu 1'in istediği bağımsız denetim).** 118 eşleme, sayfanın 150 dpi görüntüsünde
   bölgesi çizilerek plan yazarının gözüyle okundu; basılı denklem seçilen grubun LaTeX'iyle karşılaştırıldı
   (`image-check.json`). **Örneklem 1** (tohum 22, r2 kurallarından önce çekildi; makale başına en çok 3): makale geneli
   farkı ≥ 0,20 olan 40 eşleme ve yalnız sırayla seçilmiş 20 eşleme: 60'ın 60'ında grup doğru. **Örneklem 2** (bölge
   kırpması yazıldıktan sonra, harfleri-ezmeme kuralından önce çekildi): sıranın harfleri ezdiği 38 eşlemenin tamamı ve
   rastgele 20 sıra-kararlı eşleme: 58'in 57'sinde grup doğru. **Tek yanlış:** `1911.01822v1` s. 14 (102): basılı denklem
   tildeli (p̃ₙ, β̃ₙ); sıra (101)'in tildesiz grubunu verdi, çünkü aksanlar harf sayımında düşünce iki grup aynı harfleri
   taşıyor; seçilen grubun F1'i 0,649, bir başka grubun 0,681 (sıranın harfleri ezdiği 38'den biri). Son kural (karar 4)
   altında görüntüsü okunan eşlemelerden 77'si geçiyor (40 makale geneli farkla, 37 sırayla) ve 77'si de doğru; yanlış
   olan son kuralla dışarıda kalıyor. **Bu 77/77 bir doğruluk sınırı değildir:** kural, bu görüntüler ve içlerindeki tek
   yanlış görüldükten sonra seçildi; aynı veride, aynı okuyucunun kararına uydurulmuş bir kuralın kendi örnekleminde
   hatasız çıkması beklenir. Bu sayıdan başka veriye, başka makalelere ya da başka bir okuyucuya taşınabilecek bir hata
   oranı çıkarılamaz. **Sınırlar:** okuyan tek kişi ve planın yazarı; örneklem 1 kurallardan önce çekildi ama kurallar
   görüntüleri gördükten sonra yazıldı; ayrılmış bir sınama kümesi yok (bütün 43 sürüm kullanıldı); kod bittikten sonra
   kabul (f) 40 yeni yerleşmeyi görüntüden okutur; o da aynı makalelerden gelir.
10. **Bölge başka metni siliyordu.** r1 bölgesi (numara satırından geriye, ilk düzyazı satırına kadar) 924 eşlemenin
    240'ında (%26) denklemin yanındaki bir metin satırını ya da sözcüğünü de kapsıyordu ("where", "is given by",
    satır içi matematik taşıyan bir cümle satırı); yerleşme bunları silecekti (örneklem 1'de 60'ın 14'ü). Karar 4'ün
    kırpma ve emme kuralından sonra 118 görüntüde tek bir metin satırı bölgede kaldı (örneklem 2 no. 1, "section of
    Gq(n, Kn, Pn) and G(n, pn), i.e.,"), onu da yabancı sözcük kuralı ayırıyor (924'te yalnız 3 eşlemeye dokunuyor, üçü de
    gerçek metin). Emme son kuralı geçen 873 adayın 85'inde işledi; emilen satırlardaki sözcükler yalnız `lim`, `max`,
    `min`, `sin`, `lim sup`. Aynı denklemin bazı parçaları (bir `{`, `pn ∼`) bölgenin dışında kalıp blokla yan yana metin
    olarak görünebiliyor: bu yineleme, kayıp değil.
11. **Numarası ilk satırda olan denklem.** Kaynakta numara ilk satırda, devam satırları `\nonumber` ise (grup yalnız ilk
    satırı kapsar) devam satırları metin katmanında kalır ve yerleşen blok denklemin bir parçası olur (örneklem 1 no. 42,
    `2005.00948v1` (39)). Son kurala giren eşlemelerde 12 tane; karar 4 bunları yerleştirmez.
12. **Son kuralı geçen adaylar.** Karar 4'ün eşleme kuralını (atama, eşik, harfleri-ezmeme, devam eden grup, yabancı
    sözcük) 43 sürümün 1.520 numara satırından **873 aday** geçiyor (849'u Marker'ın bugün okuduğu sayfalarda), 246 sayfada,
    43 sürümün 43'ünde en az bir tane (`summary-r2-final.json`). Bu bir yerleşme sayısı değildir: ön-örnek yerleştirmeyi
    yapmadı; KaTeX kapısı, `\ref` / `\cite` taşıyan grup, 4.000 karakter sınırı, tablo başlıklı ve OCR sayfaları,
    `not_in_page_text` ve `chunk_page`'in yazımı bu sayıya girmedi. Ürünün gerçekten yerleştirdiği ve her yerleşmeme
    nedeni kabul (a)'da ayrı sayılır.
13. **Marker'ı atlayacak sayfalar (r1, artık kullanılmıyor).** r1'in "tamam sayfa" kuralı 369 sayfanın 14'ünü (%3,8)
    Marker'dan çıkarıyordu ve bunların birinde Marker, rotanın yerleştireceğinden fazla görüntü denklemi buldu; o sayfalar
    görüntüden okunmadı. D62'nin hızıyla 14 sayfa yaklaşık 10 dakika eder (tahmin, ölçüm değil). Bu bir bilinen kaçırma
    ve küçük bir tahmini kazanç demek; D3 bu yüzden seçildi: hiçbir sayfa Marker'dan çıkmaz.
14. **Nereden okunmalı.** Aynı kurallar ürünün kendi `layout-v2` sayfa metni üzerinde (simge fontu maskesiz) koşunca r1'in
    900'ü 462'ye düştü (`-pagetext.json`). Eşleme PyMuPDF'in satırlarında, simge fontu harfleri maskelenerek yapılmalı
    (`inline_math.line_text`, `inline_math.py:56`).
15. **Süre.** Kaynağı açma, grupları kurma ve bir PDF'in bütün sayfalarını eşleme makale başına ortanca 0,56 sn, en çok
    4,6 sn (Python, tek iş parçacığı, r1).
16. **Migration provası (Sol r1 bulgu 6).** Canlı kütüphanenin SQLite yedek API'siyle alınmış kopyasında (şema `0036`,
    17.448 pasaj) karar 7'nin `passages` yeniden kuruluşunun taslağı (`migration/draft_0054_passages.sql`) 0,35–0,53 sn
    sürdü. `rowid`, `id`, `text_sha256` ve `text_source` satır satır aynı; FTS'de "channel" sorgusu aynı 3.756 satırı
    döndü; FTS5 `integrity-check` geçti; `foreign_key_check` boş; yeni DDL eskisinden yalnız CHECK'te (ve SQLite'ın
    yeniden adlandırmada adı tırnaklamasında) farklı; şemada `passages` dışında değişen nesne yok; yeni bir
    `latex_source` pasajı FTS'de bulundu, metni güncellenemedi, bilinmeyen bir değer reddedildi. **Bulunan:** ilk denemede
    `ALTER TABLE passages_new RENAME TO passages` "error in trigger cell_evidence_same_source: no such table:
    main.passages" hatası verdi; `cell_evidence_same_source` tetiği düşürülüp yeniden kuruluşun sonunda aynen yeniden
    yazılınca geçti (`migration/rebuild-check.json`). Kopya şema `0036`'daydı; `0038` `stage_decisions.quote_passage_id` ile
    bir yabancı anahtar daha ekliyor. Ürün migration'ı `0053`'e taşınmış bir kopyada denenmeli.

Sayıların gösteremediği: görüntüden okumanın plan yazarından bağımsız bir okuyucuda tuttuğu; kuralın başka veride
tuttuğu; ürünün yerleştirmesinin (bölgenin sayfa metnindeki yerini bulmak) ön-örneğin yerleştirdiğinin kaçını gerçekten
yazacağı; bir yayımlanmış sürümün denklemlerinin ön baskıdan ne kadar ayrıldığı; arXiv'in 406'sının nedeni ve yük altında
davranışı.

## SW maddeleri: kurulan, açık kalan

| Madde | Bugün | Bu dilimde |
|---|---|---|
| SW10.6 (a) arXiv kopyasında yazarların kaynağı metni ve denklemleri verir; makrolar açılır, düzen komutları atılır, sürüm kaydedilir | Yok | Numaralı görüntü denklemleri, yalnız Marker kurulu değilken (karar 2–5); düzyazı metin katmanından kalır (sapma 1) |
| SW10.6 (b) başka yerde PyMuPDF | Var | Değişmez |
| SW10.6 (c) Marker yalnız kod kapısının işaretlediği ve raporun alıntılayacağı sayfalarda | Marker bütün matematik ve tablo sayfalarını okur | Değişmez; hiçbir sayfa Marker'dan çıkmaz (D3, sapma 2); kod kapısı dilim 23 |
| SW10.7 denklem ancak sayfaya eşlenirse; numara metin katmanında, eşleme harf benzerliğiyle, sayarak değil | Yok | Kurulur (karar 4); sıra kısıtı sayma değildir ve harfleri hiçbir zaman ezmez (sapma 5) |
| SW10.7 güvenilmezse o sayfa Marker'la | Yok | Marker kuruluysa rota hiç koşmaz ve Marker bugünkü gibi okur; kurulu değilse eşiği geçmeyen denklem metin katmanında kalır (sapma 4) |
| SW10.8 ön baskıdan okunan denklem sürüm etiketini taşır; kişinin verdiği yayımlanmış sürüm önce gelir (D4) | Kayıt etiketi var, dosyanın sürümü yok | Kurulur (karar 1, 8); kaynak yalnız dosyanın ve kaydın aynı ön baskı sürümünü adlandırdığı PDF'e eklenir; öncelik `answer_version`'da zaten var, testle sabitlenir |

## Kararlar

1. **Bayrak, uygunluk ve sürüm çatışmaları (Sol r1 bulgu 3).** Yeni `Settings.arxiv_source` (`off` | `auto`), ortam
   değişkeni `DEIXIS_ARXIV_SOURCE`, varsayılan hem sınıfta hem `load_settings`'te **`off`** (F1). Rota yalnız bayrak `auto`
   iken, Marker kurulu değilken (`service.available()` yanlış ve kurulum sürmüyor) ve PDF'in güncel çıkarımı `+marker-`
   taşımıyorken koşar (D3, C1). **Yalnız POSIX** (dilim 21 / D103 gibi): `fcntl` yoksa (Windows; `worker.py:22-26` orada
   `msvcrt` kullanır) bayrak `auto` olsa da rota kapalıdır, açılışta bir kez günlüğe yazılır ve kaynak satırı "not available
   on this system" der. Bir PDF varlığı için dosyanın kendi sürümü (a) `retrieved_from` `https://arxiv.org/pdf/<id>v<N>` biçiminden ve
   (b) ilk iki sayfanın metin katmanındaki damgadan (`arXiv:<id>v<N> [<kategori>] <tarih>`, `page.get_text()`,
   döndürülmüş satır dahil) okunur. Karar aşağıdaki tek tabloyla verilir; ilk uyan satır geçerlidir:

   | Dosyanın sürümü | Kaydın `version_label`'ı | Kaynağın yanıtı | Sonuç |
   |---|---|---|---|
   | adres ve damga farklı kimlik ya da sürüm | — | istenmez | `version_conflict` |
   | ikisi de yok | — | istenmez | `no_version` |
   | `<id>vN` | kaydın DOI'si, `landing_url`'i ve `oa_pdf_url`'si birbirinden farklı arXiv kimlikleri taşıyor | istenmez | `record_identity_conflict` (kalıcı) |
   | `<id>vN` | kaydın DOI'si, `landing_url`'i ya da `oa_pdf_url`'si bir arXiv kimliği taşımıyor | istenmez | `record_identity_unknown` |
   | `<id>vN` | kaydın taşıdığı arXiv kimliği `<id>` değil | istenmez | `record_version_conflict` |
   | `<id>vN` | `arXiv vM`, M ≠ N | istenmez | `record_version_conflict` |
   | `<id>vN` | `arXiv vN` ya da `submittedVersion` dışında her şey (yayımlanmış, kabul edilmiş, boş) | istenmez | `record_version_conflict` |
   | `<id>vN` | `arXiv vN` ya da `submittedVersion` | `Content-Disposition` dosya adı `<id>vN`'yi adlandırmıyor | `version_mismatch` (kalıcı) |
   | `<id>vN` | `arXiv vN` ya da `submittedVersion` | `<id>vN` | `eligible`, kaynak kullanılabilir |

   Sayı 2'ye göre canlı kütüphanede hiçbir PDF `record_identity_unknown` ya da `record_version_conflict` olmaz. Kimlik
   denetimi kaydın taşıdığı arXiv kimliğine dayanır (ölçülen 56 kaydın hiçbirinde üç alan birbirinden farklı bir kimlik
   taşımıyor; kural yine de çatışmayı kalıcı ret sayar); kaydın işe bağlanmasının (D46, D83) doğru olduğunu ayrıca denetlemez. Kişinin yayımlanmış bir kayda yüklediği
   damgalı arXiv PDF'i böylece kaynaktan denklem almaz (D4: ön baskının denklemi yayımlanmış kaydın pasajına girmez). Karar
   varlık başına bir kez, okuma sırasında verilir ve migration `0054`'teki `asset_arxiv_versions` tablosuna yazılır:
   `(asset_id PRIMARY KEY REFERENCES source_assets(id), eligibility CHECK IN ('eligible', 'no_version', 'version_conflict',
   'record_identity_unknown', 'record_identity_conflict', 'record_version_conflict'), arxiv_key NULL, version_from CHECK IN ('url', 'stamp', 'both') NULL, record_label NULL,
   checked_at)`. Kaydın kimliği ve etiketi yazmanın kendi SQLite işleminin içinde yeniden okunur (karar 6'nın son yazma
   koruması); tabloya uymazsa pasaj yazılmaz, uygunluk satırı yeni sonuçla güncellenir (neden `record_version_changed`, karar 6). `equation_state` (görünümde her varlık için çağrılır,
   `views.py:440`) böylece PDF açmadan karar verir.
   **Kayıt sonradan zenginleşince (Sol r5 bulgu 3).** Kaydın kimlik alanlarını (DOI, `landing_url`, `oa_pdf_url`,
   `version_label`) yazıldıktan sonra değiştiren tek yol `enrich_source`'tur ve yalnız boş `landing_url`'i doldurur
   (`store.py:1206-1218`, `COALESCE`). Kural: `enrich_source` kendi işleminde, `landing_url` boştan dolduysa, o kayıt
   sürümünün kaldırılmamış her PDF'i için uygunluk satırını karar 1'in tablosuyla (saklı dosya sürümü `arxiv_key` ve
   `version_from`'dan, PDF açmadan) yeniden hesaplar ve yazar. Satırı yoksa bir şey yapmaz. Sonuç `eligible` olursa PDF
   kural 3'e girer ve okunur (ör. `record_identity_unknown` → `eligible`). Sonuç bir ret ve güncel çıkarım
   `+arxiv-latex-v1` ise o okuma aynı işlemde, bu sırayla geri çekilir (tek `current` indeksi,
   `0027_asset_extractions.sql:24`): önce rotanın `asset_extractions` satırı `superseded` olur; sonra rotadan hemen önce
   güncel olan satır (aynı varlığın `superseded` satırlarından rotanınkinden önce yazılmış en yenisi) `current` olur ve
   `source_assets`'in `extraction_version`, `extraction_status`, `extraction_error` ve `page_count`'u o satırın `version`,
   `status`, `error` ve `page_count`'uyla birlikte yazılır (`store.py:1405`'in yazdığı alanların aynısı). Kaynak pasajları
   silinmez; güncel sürüm dışında kaldıkları için bugünkü kuralla gölgelenir (`store.py:29`, `text_superseded`) ve
   kanıtları D45'in gölgeleme yoluyla görünür. Durum kural 3'ün ret satırından `no_source` ve neden olur, bir
   `arxiv_source_withdrawn` olayı yazılır. Rotanın satırı durduğu için aynı sürüm yeniden yazılmaz (`store.py:1364`).
2. **Kaynağı getirmek ve saklamak (Sol r1 bulgu 4).** Adres `https://arxiv.org/e-print/<id>v<N>` (sayı 3). Yeni
   `fetch.fetch_file(url, media_types)` `fetch_pdf`'in yolunu paylaşır (genel adres, sabitlenmiş bağlantı, en çok 5
   yönlendirme, 30 MB, 30 sn, `host_gate`, aynı User-Agent) ve yalnız `application/gzip` ile `application/pdf`'i kabul
   eder. **Aralık (süreçler arası):** bu rotanın `arxiv.org`'a gönderdiği iki HTTP isteğinin sunucuya varışı arasında,
   aynı veri dizinini kullanan bütün süreçlerde, en az 3 sn olur. **Her HTTP isteği bir istektir, yönlendirme adımları
   dahil** (Sol r5 bulgu 1): `fetch_file` her adımdan (ilk istek ve her yönlendirme) önce ve sonra rotanın geçit
   işlevlerini çağırır, `fetch_pdf` çağırmaz. Kilit bir getirmenin bütün adımları boyunca tutulur; beklemeler ve damgalar
   adım başınadır (Sol r3 bulgu 2, r4 bulgu 2 ve 3):
   - **Kilit, iş parçacığı olmadan.** `<veri dizini>/arxiv-sources/.rate.lock` üzerinde özel `fcntl.flock` bloklamayan
     biçimde (`LOCK_EX | LOCK_NB`) denenir; alınamazsa `await asyncio.sleep(0.1)` ve yeniden (D103'ün deseni,
     `local_embedding_service.py:48-76`). `asyncio.to_thread` kullanılmaz: iptal edilen bir bekleme arka planda kilidi
     sonradan alıp bırakmayan bir iş parçacığı bırakamaz. Kilit beklemesi en çok 120 sn ve bu **tek bir bütçedir**: süreç içi `asyncio.Lock`, sürüm anahtarı kilidi (aşağıdaki
     sıra, adım 1) ve hız kilidinin alınması tek bir `asyncio.timeout(120)` içindedir (Sol r7 bulgu 2, r8 bulgu 2); aşılırsa
     istek gitmez, hiçbir satır yazılmaz ve deneme sayılmaz (sayaç ancak iki kilit de alındıktan sonra yazılır, adım 3); adım o PDF için `rate_gate_busy` çıktısıyla biter, durum `pending` kalır ve arka plan
     sonra dener. Dosya tanıtıcısı açma, kilit, bekleme ve
     istek tek bir `try` içindedir; `finally` `LOCK_UN` yapar ve tanıtıcıyı kapatır, iptal (`CancelledError`) ve süre
     aşımında da.
   - **Kalıcı başlangıç damgası.** `.rate` `{"started_at", "ended_at"}` taşır (duvar saati). Kilit alınınca okunur:
     `ended_at` doluysa `ended_at + 3 sn`'ye, boşsa (bir önceki istek bitişi yazılmadan çöktü ya da iptal edildi)
     `started_at + 30 sn + 3 sn`'ye kadar `asyncio.sleep` ile beklenir (bekleme en çok 33 sn; gelecekteki bir damga da
     33 sn'yi aşan beklemeye yol açmaz). Sonra `{"started_at": şimdi, "ended_at": null}` geçici dosyaya yazılır, `fsync`,
     `os.replace`; **ancak bundan sonra** istek gönderilir. İstek bitince (başarı, yönlendirme yanıtı, hata, süre aşımı ya
     da iptal) `ended_at` aynı yolla yazılır (`finally`). Yönlendirmenin sonraki adımı aynı bekle-damga-gönder-bitiş
     sırasını, kilidi bırakmadan izler; son adımdan sonra kilit bırakılır. Çöken sürecin kilidi işletim sistemince bırakılır ve
     damgası `ended_at`'siz kalır.
   - **Toplam son tarih.** Bir getirmenin tamamı (adres denetimi, en çok 5 yönlendirmenin her biri, gövdenin parça parça
     okunması ve adımlar arasındaki 3 sn'lik beklemeler) tek bir `asyncio.timeout(30)` içindedir; ilk adımdan önceki
     bekleme (en çok 33 sn) son tarihin dışındadır; istemcinin bağlantı ve okuma zaman aşımları da kalır. Süre dolunca
     akış `async with` ile kapanır, sonuç `not_settled` (zaman aşımı). `fetch_pdf`'in bugünkü davranışı değişmez; son tarih
     yalnız `fetch_file`'ın yolundadır (bugün yalnız istemcinin istek başına zaman aşımı var, `fetch.py:108`,
     `fetch.py:131`).
   - **Neden yeter.** Bir isteğin sunucuya varışı, başlangıç damgasından sonra ve süreç yaşıyorsa son tarihten (başlangıç
     + 30 sn), çöktüyse çökme anından önce olur. Bir sonraki istek ya bir öncekinin bitişinden ya da başlangıç + 30 sn'den
     en az 3 sn sonra gönderilir; iki varış arası bu yüzden en az 3 sn'dir. İptal ve çökmeden sonraki bekleme en çok 33
     sn'dir; kilidin en uzun tutulma süresi bekleme ve son tarihle en çok 63 sn.
   Farklı sürümler için eşzamanlı istekler de böylece sıraya girer; bedeli, kaynak getirmelerinin birbirini beklemesidir. Başka veri dizinlerindeki DEIXIS kopyaları ve DEIXIS'in
   arXiv araması (`providers/arxiv.py:29-41`, ayrı kilit) bu sayıma girmez; plan bunu iddia etmez. **Satır:** migration
   `0054`'teki `arxiv_sources`, sürüm başına bir satır: `(arxiv_key PRIMARY KEY, arxiv_id, version, status CHECK IN
   ('downloaded', 'version_mismatch', 'too_large', 'unreadable', 'not_settled'), content CHECK IN ('tex', 'pdf_only',
   'no_tex', 'too_large', 'unreadable') NULL, sha256, byte_size, storage_path, http_status, attempts, last_attempt_at,
   fetched_at, inspected_at, repairs INTEGER NOT NULL DEFAULT 0)`: `status` indirmenin, `content` arşiv incelemesinin (karar 3) sonucudur. **Geçişler:**

   | Önce | Olay | Sonra |
   |---|---|---|
   | satır yok ya da `not_settled`, deneme < 3 | olağan getirme girişiminden önce | `attempts` +1, `last_attempt_at` (aynı durum) |
   | 〃 | zaman aşımı, kopan bağlantı, 403, 406, 429, 5xx | `not_settled` |
   | 〃 | 200, kabul edilen tür, ≤ 30 MB, dosya adı `<id>vN` | `downloaded`, `content` NULL (dosya ve satır, aşağıdaki sıra) |
   | 〃 | dosya adı başka sürüm ya da yok | `version_mismatch` (kalıcı, dosya saklanmaz) |
   | 〃 | 30 MB'ı aşan yanıt | `too_large` (kalıcı) |
   | 〃 | başka tür ya da başka 4xx | `unreadable` (kalıcı) |
   | `not_settled`, deneme = 3, `repairs` ≠ 1 | — | kalıcı (yeniden istenmez) |
   | `downloaded`, `content` NULL | karar 3'ün alt süreci | `content` = `tex`, `pdf_only`, `no_tex`, `too_large` ya da `unreadable`; `inspected_at` |
   | `downloaded`, `repairs` = 0 | okurken dosya yok ya da sha256 tutmuyor | `not_settled`, `content` NULL, `repairs` = 1 (onarım hakkı), `attempts` değişmez, olay |
   | `not_settled`, `repairs` = 1 | onarım isteğinden önce (deneme sayısından bağımsız) | `repairs` = 2, `attempts` değişmez |
   | `downloaded`, `repairs` ≥ 1 | okurken dosya yok ya da sha256 tutmuyor | `unreadable` (kalıcı, `cache_corrupt`), olay |
   | `content` `unreadable`, `status` `unreadable` ya da deneme bitmiş `not_settled` | kişinin "yeniden dene"si | `content` NULL ya da `attempts` 0 ve `repairs` 0 |

   Kaynak yalnız `status = 'downloaded'` ve `content = 'tex'` iken kullanılır; başka her bitmiş durum karar 6'da `no_source`
   olur. **Sıra:** (1) sürüm anahtarının kilidi alınır: süreç içinde anahtar başına bir
   `asyncio.Lock`, süreçler arasında `<veri dizini>/arxiv-sources/<anahtar>.lock` üzerinde `fcntl.flock` (D103'ün kilit
   deseni; hız kilidi gibi `LOCK_NB` ve `asyncio.sleep` ile, iş parçacığısız, `finally`'de bırakılır; `asyncio.Lock`
   dahil beklemesi hız kilidininkiyle ortak 120 sn bütçeden düşer); (2) kilit alındıktan sonra satır yeniden okunur,
   `downloaded` ya da kalıcı bir durumsa istek gitmez; (3) **hız kilidi de alınıp ilk hız beklemesi bittikten sonra, ilk
   HTTP isteğinden hemen önce** (geçidin ilk adımındaki "önce" çağrısında; Sol r8 bulgu 1) kısa bir işlemde olağan getirmede `attempts` bir artar, onarım getirmesinde (`repairs` = 1) `attempts` değişmez ve
   `repairs` 2 olur; ikisinde de `last_attempt_at` yazılır (iptal edilen ya da çöken girişim de sayılır); (4)
   yanıt bellekte gelir (en çok 30 MB), sha256'sı hesaplanır, `<anahtar>.src.part-<süreç>` dosyasına yazılır, `fsync`,
   `os.replace` ile `<anahtar>.src` olur; (5) ancak ondan sonra kısa bir işlemde satır `downloaded`, sha256, boyut ve yolla
   yazılır.
   Dosya yazılıp satır yazılmadan çökerse sonraki deneme dosyayı yeniden indirip üzerine yazar. Servis açılırken bir
   saatten eski `*.part-*` dosyaları silinir. **Okurken:** dosya satırın sha256'sıyla karşılaştırılır; dosya yoksa ya da
   tutmuyorsa bir `arxiv_source_corrupt` olayı yazılır ve kaynak bir kez daha getirilebilir (Sol r5 bulgu 2, r6 bulgu 2).
   **İki ayrı sınır:** `attempts` yalnız olağan getirme girişimlerini sayar (en çok 3); bozulma onarımı bunlara ek, sürüm
   başına tek bir getirme girişimidir ve `repairs` ile sayılır (0 yok, 1 hak var, 2 kullanıldı). 3 + 1 HTTP adımlarını
   değil **getirme girişimlerini** sınırlar; her girişim yönlendirmeleriyle birkaç HTTP isteği olabilir (en çok 6), her biri
   hız geçidinden geçer. Satır `not_settled`, `repairs` 1 olur; onarım girişimi `attempts`'a bakmadan ve onu artırmadan
   gider, `repairs` 2 olur, böylece üçüncü denemede indirilmiş bir dosya da bir kez yeniden getirilir. İkinci bozulma kalıcı `unreadable` (`cache_corrupt`) olur; kişinin "yeniden dene"si sıfırlar. **Yeniden deneme:** `downloaded` ve kalıcı durumlar yeniden istenmez;
   `not_settled` en çok `SOURCE_MAX_ATTEMPTS = 3` kez, aralarında en az `RETRY_AFTER`
   (10 dk, `equations.py:31`); üçüncüden sonra kalıcı sayılır. Aynı sürümü taşıyan iki PDF tek dosyayı paylaşır (canlı
   kütüphanede 3 sürüm iki kez saklı).
3. **Arşivi okumak (güvenilmez veri; Sol r1 bulgu 7).** Arşivi açma, makro açma ve eşleme olay döngüsünün dışında, ayrı
   bir alt süreçte koşar: `python -m deixis.documents.arxiv_source`, bellek bekçisi `pdf.py:198-210`'un deseniyle (1 GB).
   `pdf.extract_pdf`'in `subprocess.run(capture_output=True)`'undan (`pdf.py:213-219`) farklı olarak ebeveyn çıktıyı
   okurken sınırlar: `asyncio.create_subprocess_exec`; stdout ve stderr **aynı anda**, iki ayrı görevle boşaltılır (biri
   dolan borusunda beklerken çocuk takılmaz); stdout parça parça okunur ve 5 MB'ı geçtiği anda çocuk öldürülür; stderr
   sonuna kadar okunur ama yalnız son 4.000 karakteri tutulur (`OUTPUT_TAIL_CHARS`, `equations.py:33`); bütün iş 60 sn
   içinde bitmezse (ölçülen en çok 4,6 sn) çocuk öldürülür ve iki görev iptal edilir. Aşan her şey `content = 'unreadable'` olur ve okuma yazılmaz. Arşiv bellekte `tarfile` / `gzip` ile okunur, diske açılmaz, üye adı hiçbir zaman yol olarak
   kullanılmaz; yalnız düzenli dosyalar okunur (sembolik ve sert bağlantı, aygıt, FIFO atlanır). **Sınırlar:** gzip akışı
   açılırken sayan bir okuyucudan geçer, toplam açılmış bayt en çok 64 MB (ölçülen en çok 27,7 MB); en çok 1.000 üye; tek
   metin üyesi (`.tex`, `.sty`, `.def`) en çok 5 MB, metin üyelerinin toplamı en çok 5 MB (ölçülen en çok 0,28 MB); aşan
   `too_large`. `.tex` yoksa `no_tex`, PDF ise `pdf_only`. **Ana dosya** `\begin{document}` taşıyan (birden çoksa en
   uzunu); `\input`, `\include`, `\subfile` 5 derinliğe kadar içe alınır (kendini içe alan dosya bu sınırda durur);
   yorumlar silinir. **Makrolar** sayı 5'teki beş biçimden, arşivdeki `.sty` / `.def` dahil, 8 derinliğe kadar açılır;
   makale başına en çok 20.000 açıcı çağrısı (ölçülen en çok 377); açıldıktan sonra 4.000 karakteri aşan grup
   yerleştirilmez (`too_long`; ölçülen 2.189 grupta numaralı olan yok). Sınırı aşan açılma o grubu `macro_limit` ile
   dışarıda bırakır, makalenin öbür gruplarını değil. **Gruplar:** `equation`, `multline` tek grup; `align`, `gather`,
   `eqnarray`, `alignat`, `flalign`'da bir numara, ortamındaki bir önceki numaralı satırdan sonraki satırları kapsar;
   yıldızlı ortamlar, `\[…\]`, `$$…$$` ve `\nonumber` / `\notag` satırları numarasızdır; `\tag{…}` numara verir. Ortamı
   numaralı son satırından sonra numarasız satırlarla süren grup "devam eden" diye işaretlenir (sayı 11). **Temizlik:**
   `\label{…}`, `\nonumber`, `\notag`, `\hspace{…}`, `\vspace{…}`, `\setcounter{…}{…}`, `\displaybreak`, `\allowbreak`
   ve `\tag{…}` silinir; sayı 6'nın yeniden yazma tablosu uygulanır; `&` ya da `\\` taşıyan grup
   `\begin{aligned}…\end{aligned}` içine alınır. `\ref`, `\eqref`, `\pageref` ya da `\cite` taşıyan grup temizlikten önce
   işaretlenir ve yerleştirilmez. **KaTeX kapısı:** `scripts/katex_commands.mjs` web uygulamasının KaTeX'inden (0.16.47)
   komut ve ortam listesini `backend/deixis/documents/katex_commands.json`'a yazar (sürümüyle); temizlikten sonra listede
   olmayan bir komut ya da ortam taşıyan grup yerleştirilmez (`katex_unknown`).
4. **Eşleme (SW10.7; Sol r1 bulgu 1).** "Eşiği geçti" aşağıdaki işlemsel kuraldır; bir doğruluk güvencesi değildir (sayı
   9'un sınırları). Satırlar `pdf.py`'nin kendi `_blocks`'ından okunur (aynı bayraklar ve filtreler; her satır
   `inline_math.line_text` ile simge fontu harfleri maskelenmiş metnini ve kutusunu da taşır). **Numara satırı:** yalnız
   `(n)` / `(na)` olan satır, ya da düzyazı olmayan ve ` (n)` ile biten satır. **Düzyazı satırı:** en az `PROSE_WORDS = 3`
   tane üç ve daha uzun küçük harfli sözcük. **Aday bölge:** numara satırından geriye, ilk düzyazı satırına, bir önceki
   numara satırına ya da `MAX_REGION_LINES = 12`'ye kadar. **Skor:** bölgenin harf ve rakam çokkümesi ile grubun
   çokkümesi (`math_reader.latex_letters` / `_letters`): F1 ve geri çağırma. **Atama:** PDF'in bütün numara satırları
   okuma sırasıyla, bütün numaralı gruplar kaynak sırasıyla; numaralar arttıkça kaynak sırası da artacak biçimde
   `F1 − 0,5`'in toplamını en büyük yapan atama (dinamik programlama; bir numara atanmadan kalabilir). **Üç fark:**
   pencere farkı (seçilenin F1'i eksi sıranın o noktada izin verdiği öbür grupların en yükseği), makale farkı (seçilenin
   F1'i eksi makaledeki LaTeX'i farklı her öbür grubun en yükseği). **Eşiği geçer:** geri çağırma ≥ `MIN_RECALL = 0,90`
   ve (makale farkı ≥ `MIN_MARGIN = 0,20` ya da (pencere farkı ≥ 0,20 ve makale farkı ≥ 0)). Yani sıra yalnız harflerin
   ayıramadığı ya da az farkla ayırdığı gruplar arasında seçer; harflerin daha yüksek puan verdiği bir grubu hiçbir zaman
   ezmez (sayı 9'daki tek yanlış bu durumdaydı). **Bölge kırpma ve emme:** yerleşecek bölge, numara satırından geriye
   seçilen grubun en yüksek geri çağırmasına ulaşan en kısa satır dizisidir; sonra bu dizinin önündeki, düzyazı ve numara
   satırı olmayan, dizinin kutusuyla dikeyde boyunun en az yarısı kadar örtüşen satırlar bir önceki numara satırına kadar
   (12 satır sınırı olmadan) eklenir (aynı denklemin parçaları). **Yabancı sözcük:** kırpılmış ve emilmiş bölgede üç ve
   daha uzun küçük harfli bir sözcük, grubun LaTeX'inin harflerinde (komut adlarıyla ya da onlarsız) alt dizi olarak
   geçmiyor ve harfleri grubun harf çokkümesine sığmıyorsa eşleme yerleşmez (`foreign_text`). **Devam eden grup** (karar
   3) yerleşmez (`continues_after_number`). **Sayma değildir:** SW10'da sayma, n'inci numarayı kaynaktaki n'inci
   numaralı denkleme vermekti ve başarısızdı (11'e 8, 51'e 46, 163'e 77); burada hiçbir numara bir gruba yalnız sırasından
   dolayı verilmez. Sabitler `documents/arxiv_source.py`'de adlıdır ve her okumanın `math_json.source.params`'ına yazılır;
   bu verideki görüntü örneklemi gördükten sonra seçildiler, dilim 24 kampanyası yeniden bakar.
5. **Yerleştirme; Marker'a dokunulmaz (D3; Sol r1 bulgu 2).** Eşiği geçen her eşleme, kırpılmış ve emilmiş bölgesinin
   satırları sayfa metninden çıkarılıp numara satırının yerine `$$\n<latex>\n$$ (n)` bloğu (Marker'ın biçimi) konarak
   yerleşir. Yerleştirme `pdf.py`'nin alt sürecinde, `_page_text` satırları birleştirmeden önce yapılır (eşleme alt süreci
   karar 3'ün, çocuk sürece bir JSON dosyasıyla `(sayfa, blok, satır)` anahtarları ve LaTeX gider). Bölgenin bir satırı
   sayfa metnine hiç girmiyorsa (sayfa numarası ya da üst başlık bloğu) o eşleme yerleşmez (`not_in_page_text`).
   **Tek ofset uzayı (Sol r2 bulgu 2):** `chunk_page` (`pdf.py:244-262`) metni önce `re.sub(r"[ \t]+", " ", text).strip()`
   ile normalleştirir ve `(başlangıç, bitiş)`'i bu normal metne göre döndürür; `_write_extraction` bunları
   `payload_ref = "chars:<başlangıç>-<bitiş>"` olarak yazar (`store.py:1342`). Bu ifade `pdf.normalize_page_text(text)`
   adıyla ayrılır ve `chunk_page` onu çağırır (çıktısı bayt bayt aynı kalır). Yerleşen blokların ofsetleri de yalnız bu
   uzayda tutulur: ebeveyn, alt süreç döndükten ve `remove_download_notices` (`pdf.py:230`) uygulandıktan sonra, sayfanın
   son metnini `normalize_page_text`'ten geçirir ve her bloğu (kendisi de aynı işlevden geçmiş olarak) sayfa sırasıyla,
   bir öncekinin bitişinden sonra arar; `{page, n, start, end}` bu normal metnin ofsetleridir ve `math_json.source.placed`'e
   yazılır. Bir blok tam bir kez bulunamazsa o okuma yazılmaz (`offsets_unresolved`, karar 6'nın `failed`'ı). Bir parça
   bir bloğu ancak `başlangıç ≤ blok.start` ve `blok.end ≤ bitiş` ise taşır; `chunk_page` bu sürümün çıkarımında bir
   `$$…$$` bloğunun içinden kesmez (D54'ün tablo satırı kuralının eşi), dolayısıyla bir blok hep tek bir parçadadır. **D3:** hiçbir sayfa
   Marker'dan çıkmaz. Marker kuruluysa rota koşmaz ve Marker bugünkü sayfaları bugünkü gibi okur; kaynak ne getirilir ne
   kullanılır. Rota ile okunmuş bir PDF, Marker sonradan kurulunca bugünkü yoldan Marker'la yeniden okunur: Marker'ın
   seçtiği sayfalar Marker'ın, öbürleri kaynaksız metin katmanıdır (sayı 12'nin 873 adayının 24'ü Marker'ın seçmediği
   sayfalarda; o denklemler o zaman metin katmanına döner). Tablo başlıklı ve OCR sayfalarına yerleşme yapılmaz (metin
   katmanları yok ya da D54'ün satır kuralı geçerli). Numarasız görüntü denklemi hiçbir zaman kaynaktan alınmaz.
6. **Sürüm dizgesi ve durum makinesi (Sol r1 bulgu 4, 5).** `SOURCE_VERSION = "arxiv-latex-v1"`. Rota çıkarımının sürümü
   `<metin katmanı>[+ocr-…]+arxiv-latex-v1`; hiçbir zaman `+marker-` ile birleşmez. **Öncelik (Sol r2 bulgu 1): hedef ve
   durum tek kuralla, sırayla verilir; ilk uyan geçerlidir.** "Marker var" `service.available()` ya da
   `service.installing()` demektir.

   1. **Marker var:** `target_version` (`equations.py:39`) ve `equation_state` (`:45`) bugünkü koddur, değişmez. Güncel
      çıkarım `+arxiv-latex-v1` taşıyorsa bugünkü hedefe eşit değildir, `pending` olur ve Marker bugünkü yoldan okur
      (karar 5). Bayrağa bakılmaz.
   2. **Marker yok, güncel çıkarım `+arxiv-latex-v1`:** hedef güncel sürümün kendisidir; durum `read` + kaynak özeti,
      bayrak ne olursa olsun.
   3. **Marker yok, bayrak `auto`, POSIX, güncel çıkarım `+marker-` değil:** kaynak hedefi (uygunluk `eligible` ya da
      henüz yok) ya da bir uygunluk reddi; durum aşağıdaki tablodan.
   4. **Öbür her durum:** bugünkü hedef ve durum (Marker yokken bugün olduğu gibi `pending`; arka plan okumaz).

   **Kural 3'ün durumları** (hepsi saklı satırlardan, PDF açmadan):

   | Saklı durum | `state` | Arka plan okur mu | Koşunun `read_equations` adımı |
   |---|---|---|---|
   | uygunluk satırı yok | `pending` | evet | okur (uygunluk, getirme, eşleme) |
   | uygunluk bir ret: `no_version`, `version_conflict`, `record_identity_unknown`, `record_identity_conflict`, `record_version_conflict` | `no_source` (neden = uygunluk değeri) | hayır | atlanır, istek yok |
   | uygun, kaynak satırı yok | `pending` | evet | okur |
   | uygun, `not_settled`, deneme < 3, son deneme 10 dk'dan yeni | `source_waiting` (deneme, sonraki an) | hayır | beklemez; adım `succeeded`, çıktı `source_waiting` |
   | uygun, `not_settled`, deneme < 3, 10 dk geçti | `pending` | evet | bir kez daha dener |
   | uygun, `status` `downloaded`, `content` NULL | `pending` | evet | okur (inceleme ve eşleme; istek yok) |
   | uygun, `downloaded` + `tex`, kaynak hedefi için henüz `asset_extractions` satırı yok (inceleme ile yazma arasında çökme ya da eşleme alt sürecinin kesilmesi) | `pending` | evet | okur: saklı dosyadan eşleme ve yerleştirme yeniden koşar, ağ isteği yok |
   | uygun, `status` kalıcı (`version_mismatch`, `too_large`, `unreadable`), 3 deneme bitmiş `not_settled` ya da `content` `tex` dışında | `no_source` (neden) | hayır | atlanır |
   | `downloaded` + `tex`, rota hiçbir denklem yerleştirmedi | `no_source` (`nothing_placed`) | hayır | atlanır |
   | rota çıkarımı D45'le reddedildi ya da ofset çözülemedi | `failed` (neden, deneme sayısı yok) | hayır (kişi "yeniden dene" diyebilir, `equations.py:186`) | atlanır, duraklamaz |
   | okunuyor | `reading` | — | bekler (bugünkü kilit) |

   "Hiçbir denklem yerleştirmedi" bir çıkarım yazmaz; pasajsız bir `asset_extractions` reddi olarak kaydedilir (neden
   `nothing_placed`, `math_json` `{"engine": "arxiv_source"}`; bugünkü `NO_MATH` kaydının eşi,
   `_record_without_passages`, `equations.py:171`). **Son yazma koruması (Sol r3 bulgu 1):** `store.reextract_asset`
   (`store.py:1353`) isteğe bağlı bir `guard` alır; `guard(conn)` kendi işleminin içinde, `with transaction(self.conn)`
   (`store.py:1391`) açıldıktan hemen sonra ve ilk yazmadan önce çağrılır. `transaction` `BEGIN IMMEDIATE` ile başlar
   (`db.py:47`): yazma kilidi işlemin başından `COMMIT`'e kadar bu bağlantıdadır, başka bir süreç o arada kayıt ya da
   varlık satırını değiştiremez. Rotanın `guard`'ı bu işlemde önce (0) `source_assets.removed_at IS NULL` olduğunu denetler (bugün `reextract_asset`
   bunu işlemden önce yapar, `store.py:1362`; kaldırma `store.py:1491-1499`'da başka bir işlemdir), sonra (a)
   `source_versions` satırını yeniden okur ve karar 1'in
   kimlik ve etiket satırlarını yeniden uygular, (b) `source_assets.extraction_version`'ın okumanın başladığı değerle aynı
   olduğunu ve `+marker-` taşımadığını denetler, (c) bayrağın `auto` ve Marker'ın yok olduğunu (`available()` ve
   `installing()`, veritabanı dışı; aynı eşzamanlı çağrıda) denetler. Biri tutmazsa bir neden döner; `reextract_asset` o
   zaman hiç pasaj yazmadan ve güncel çıkarım sürümünü değiştirmeden `{"outcome": "refused", "reason": …}` döner.
   Nedeni (a) ise aynı işlemde yalnız iki satır yazılır: `asset_arxiv_versions` satırı karar 1'in tablosunun yeni sonucuyla
   güncellenir ve pasajsız bir red kaydı (`nothing_placed`'in biçimi, neden `record_version_changed`) eklenir; varlık artık
   uygun olmadığından kural 3'ün uygunluk reddi satırıyla `no_source` görünür (neden yeni uygunluk değeri), neden olay
   olarak da yazılır. Nedeni (0) ise hiçbir şey yazılmaz, adım o PDF için `asset_removed` sonucunu verir ve kaldırılan
   PDF görünümden bugünkü gibi düşer. Nedeni (b) ise hiçbir şey yazılmaz, adım
   `succeeded` ve `superseded` biter, durum yeni güncel çıkarıma göre dört kuraldan gelir. (c) ise hiçbir şey yazılmaz,
   adım `succeeded` ve `superseded_by_marker` biter, varlık kural 1'e göre `pending` olur ve Marker okur. Marker kurulumu `COMMIT`'ten hemen sonra biterse
   (Marker'ın varlığı bir veritabanı gerçeği değildir, işlem onu kilitleyemez) kural 1 aynı sonuca götürür: rota okuması
   `pending` olur ve Marker okur. İki sıra da Marker'ın sürümüyle biter. `guard` verilmeyen bugünkü çağrılar (Marker yolu,
   OCR) değişmez.
   **Koşu adımı** (`_read_equations`,
   `flow.py:2634`): bayrak `auto` ve Marker yokken `:2641`'deki erken dönüş yalnız kaynak hedefli varlıklar için kalkar.
   Rotanın hiçbir sonucu koşuyu duraklatmaz: kaynak gelmedi, beklemede, kalıcı olarak yok, hiçbir şey yerleşmedi, D45
   reddetti ya da başka bir araştırmanın etkin koşusu yazmayı engelledi (`RunInProgress`), hepsi adımı `succeeded`
   bitirir, çıktıya `route: "arxiv_source"` ve durumu yazar; koşu o anki güncel metinle sürer. Bir koşu bir PDF'in kaynağını
   en çok bir kez dener; adım bittikten sonra koşu duraklatılıp sürdürülse de yeniden denemez (adım saklıdır). Kaynak
   sonra gelirse arka plan okuyucu okur ve sonraki koşular görür. **Çökme:** yarım kalan adım bugünkü kurala göre yeniden
   girer; rota eş güçlüdür: kaynak satırı ve dosyası kilit altında yeniden okunur, `reextract_asset` aynı sürüm için
   `unchanged` döner (`store.py:1364`). **İptal ve duraklatma:** 30 sn son tarih yalnız HTTP getirmesini (adres denetimi,
   yönlendirme adımları, adımlar arası 3 sn beklemeler, gövde) kapsar; önünde sürüm anahtarı ve hız kilidi beklemeleri için ortak en
   çok 120 sn ve en çok 33 sn ilk hız beklemesi vardır (karar 2). Duraklatma bunları kesmez; bir PDF'in getirmesi koşuyu en çok 120 + 33 + 30 =
   183 sn bekletir, arşiv alt sürecinin 60 sn'si (karar 3) buna ayrıca eklenir; görevin iptali (`CancelledError`) yarım `.part` dosyası bırakabilir, deneme sayılmış olur, dosya servis
   açılışında silinir. **Arka plan okuyucu:** `run_forever` (`equations.py:217`) Marker kurulu değilken de, bayrak `auto`
   ise, `next_asset`'in (`:200`) kaynak hedefli `pending` varlıklarına bakar; başka bir koşu beklerken bugünkü gibi yol
   verir. **Bayrak kapanınca:** yeni uygunluk kararı, istek ve okuma olmaz; saklı `+arxiv-latex-v1` çıkarımları güncel
   kalır (D45 hiçbir şeyi geri almaz) ve Marker yokken kural 2'yle `read` görünür, pasajları `latex_source` etiketini
   taşımayı sürdürür. Yeniden açılınca kaldığı yerden sürer. **Marker kurulunca:** kural 1 (karar 5). **C1:** güncel çıkarımı `+marker-` taşıyan PDF, Marker sonradan
   kaldırılsa da, rotayla okunmaz. Görünüm reddedilmiş yeniden çıkarımı gösterirken `+arxiv-latex-` sürümlerini de hariç
   tutar ve onları denklem durumunda raporlar (`views.py:440-442`).
7. **Metin kaynağı etiketi, sözleşme ve migration (B1; Sol r1 bulgu 6, 9).** **Etiket parça başınadır:** bir parça
   (`chunk_page`'in çıktısı) ancak en az bir yerleşen bloğu karar 5'in içerme kuralıyla, aynı normal metin uzayında
   taşıyorsa `latex_source` olur; aynı sayfanın öbür parçaları `text_layer` kalır. `_write_extraction`
   (`store.py:1336-1343`) etiketi sayfadan değil parçadan alır; sayfa, yerleşen blokların normal metin ofsetlerini taşır. **Migration** `0054_arxiv_latex_source.sql`
   (`-- deixis:foreign-keys-off`): `passages_new` `0053`'teki `passages` DDL'inin aynısıyla, yalnız `text_source` CHECK'ine
   `'latex_source'` eklenerek kurulur; bütün sütunlar ve `rowid` açık sütun listesiyle kopyalanır;
   `cell_evidence_same_source` tetiği düşürülür (sayı 16), `passages` düşürülür, `passages_new` `passages` olur,
   `passages_source` dizini, `passages_fts_insert` ve `passages_no_update` tetikleri ve `cell_evidence_same_source` aynen
   yeniden yazılır. Uygulayan, `0053`'e taşınmış bir kopyanın `sqlite_master`'ında `passages`'a başvuran her tetik ve
   görünümü arar ve hepsini aynı biçimde ele alır; FTS5 tablosu dokunulmaz (içeriği `rowid`'le bağlı). Aynı dosyada
   `arxiv_sources` (karar 2) ve `asset_arxiv_versions` (karar 1). **Sözleşme:** `step-input.schema.json` `text_source`
   enum'u ve açıklaması; `report-section-draft.schema.json` `equation_origin.text_source` enum'u, şema sürümü
   `deixis.report_section_draft.v2` (`domain/contracts.py:66`). **Yeni denetim:** `_check_report_section`
   (`contracts.py:1055`) `equation_origin` verilmişse passage_id'nin StepInput'ta olduğunu (`unknown_passage_id`), aynı
   iddianın kendi `passage_ids` listesinde de bulunduğunu (`equation_origin_not_cited`; Sol r2 bulgu 4: bir iddia A'yı
   gösterip denklemin kökenini B'ye bağlayamaz) ve `text_source`'un o pasajın StepInput'taki `text_source`'uyla aynı
   olduğunu (`equation_origin_mismatch`) denetler; bu her değer için geçerlidir ve şemanın `:89`'daki "checked in code" sözünün pasaj ve köken kısmını gerçekleştirir ("pasaj bir
   matematik aralığı taşır" kısmı açık kalır). **Yöntem dosyaları** `references/source-grounded-answer.md` ve
   `references/evidence-table.md` yeni değeri anlatır: "`latex_source` is the PDF's own text of a passage in which one or
   more displayed equations numbered on the page were replaced by the authors' LaTeX from the arXiv source of the same
   version; code matched each one to the page by its number and letters and did not check that the source compiles to
   this page. Copy those equations as written. Everything else in the passage, including other mathematics, is the PDF's
   text layer." `skill_package_hash` değişir (yeni değer D104'e yazılır); `tests/fixtures/research/*.json` ve
   `tests/fakes.py::valid_response` aynı değişiklikte.
8. **Sürüm etiketi (SW10.8), D4 ve arayüz (Sol r1 bulgu 3, 9).** Okumanın `math_json.source`'u: `{arxiv_id, version,
   version_from: "url" | "stamp" | "both", record_label, status, content, sha256, placed: [{page, n, start, end, group,
   recall, f1, window_margin, paper_margin}], not_placed: {reason: count}, params}`; `start` / `end` karar 5'in normal
   metin uzayındadır. Kayıt satırının `version_label`'ı yeniden
   yazılmaz (D83: sağlayıcının beyanı); `submittedVersion` kaydında arayüz ikisini de gösterir. **Arayüz:** kaynak
   satırında "Equations from the arXiv source (v2) · {n} matched to {p} pages by their numbers"; `latex_source`
   parçasında pasaj görünümü "Equations ({a}), ({b}) in this passage are the authors' LaTeX from the arXiv source (v2),
   matched to the page by their numbers. The rest of this passage, including other mathematics, is the PDF's own text."
   der; numaralar, karar 5'in içerme kuralıyla parçanın `payload_ref` aralığındaki `placed` kayıtlarından hesaplanır; alıntı çipinde "arXiv source"
   rozeti (OCR rozetinin yanında, `ResearchView.tsx:732`'nin deseni). **D4:** `answer_version` (`store.py:1857`)
   değişmez; kişinin verdiği yayımlanmış sürüm PDF metni taşıdığında yanıt onu okur, arXiv sürümünün `latex_source`
   pasajları verilmez (testle sabitlenir). Yayımlanmış kayda bağlı damgalı arXiv PDF'i karar 1'le kaynak almaz.
9. **Kanıt ve hız sözcükleri (Sol r1 bulgu 11).** "matched to the page by its number", "the authors' LaTeX source";
   hiçbir metin "verified", "exact", "reliable" ya da "correct" demez, rota kaynağın bu PDF'e derlendiğini denetlemez.
   Bu dilim hız getirmez ve hiçbir yerde hız sözü yoktur; r1'in 14 sayfalık kazancı yalnız bir tahmindi (sayı 13).
   İndirilen, eşlenen (eşiği geçen) ve yerleşen ayrı durumlardır ve ayrı sayılır (AGENTS.md).

## SW10'dan sapmalar

Bu plan aşağıdaki yerlerde SW10'un metninden bilinçli olarak ayrılır; bu dilim için plan geçerlidir, D104 bunları
adıyla taşır:

1. **Düzyazı kaynaktan alınmaz** (SW10.6 (a) "text and equations"): pasajlar PDF sayfasına bağlıdır ve alıntı çapası
   PDF'te işaretlenir (D27); kaynağın paragrafları sayfalara bölünmez. Yalnız numaralı görüntü denklemleri kaynaktandır.
2. **Marker'ın sayfa seçimi daralmaz ve hiçbir sayfa Marker'dan çıkmaz** (SW10.6 (c), SW10.7'nin hız maddesi; D3): kod
   kapısı dilim 23'tür; r1'in tamam sayfa kuralı bilinen bir kaçırma taşıdığı ve görüntüden denetlenmediği için
   kurulmadı (sayı 13).
3. **Satır içi matematik kaynaktan alınmaz;** D62'nin yolu değişmez.
4. **Rota yalnız Marker kurulu değilken koşar** (SW10.7 "that page is read with Marker"): Marker kuruluysa kaynak hiç
   kullanılmaz; Marker yokken eşiği geçmeyen denklem metin katmanında kalır (A1, D3).
5. **Sıra kısıtı** (SW10.7 "not by counting"): karar 4; sayma değildir ve harfleri hiçbir zaman ezmez.
6. **Tam metin getirme ve okuma koşularında koşmaz** (SW10.6 "one reading step", E1): rota denklemlerin bugün okunduğu
   yerlerde koşar (arka plan, yanıt, tablo, hücre). D85'in okuma koşusu ve D98'in üst üste binen getirme kolu kaynak
   denklemlerini, ancak o PDF arka planda ya da bir yanıtta okunmuşsa görür; kendileri kaynağı istemez.

## Sahip kararları (25 Eylül 2026: A1, B1, C1, D3, E1, F1 önerildiği gibi)

Sahip soru sorulmadan ilerlenmesini istedi; eşgüdümcü önerileri kabul etti ve satır 22'ye yazdı. D'nin önerisi Sol r1'den
sonra D1'den D3'e değişti. Seçenekler kayıt için aşağıda duruyor.

- **A — Rota Marker kurulu değilken koşsun mu?** Öneri **A1**: evet, yalnız o zaman (D3 ile birlikte); eşiği geçen
  denklemler metin katmanına yerleşir, geçmeyenler metin katmanında kalır. Neden: Marker 4,4 GB'lık isteğe bağlı bir
  bileşendir; ön-örnekte 1.520 numara satırından 873 aday eşleme kuralını geçiyor (ürünün yerleştirmesi ölçülmedi). *A2*: yalnız Marker
  kuruluyken, Marker'ın önünde bir hızlandırıcı olarak (SW10.7'nin sözü); D3 ile hiçbir şey vermez, D1 ile bilinen bir
  kaçırma taşır.
- **B — Kaynaktan gelen denklemin etiketi nasıl taşınsın?** Öneri **B1**: yeni `text_source` değeri `latex_source`,
  parça başına; migration `0054` ile `passages`'ın yeniden kurulması, StepInput ve rapor taslağı şemaları (`v2`),
  `equation_origin` denetimi, yöntem dosyaları, `skill_package_hash` değişir (karar 7). *B2*: sözleşme değişmez; pasajlar
  `text_layer` kalır, köken yalnız `math_json`'da ve arayüzde; model, `$$` bloğunun metin katmanı olmadığını bilmez.
  Önerilmez (AGENTS.md "Preserve evidence boundaries").
- **C — Marker'ın okumuş olduğu saklı arXiv PDF'leri rotayla okunsun mu?** Öneri **C1**: hayır, Marker sonradan
  kaldırılsa da (karar 6). Canlı kütüphanede 56 arXiv PDF'inin 53'ü Marker'la okunmuş; C1'de bugünkü okumalar ve onlara
  bağlı alıntılar yerinde kalır. *C2*: Marker'ın okuduğu PDF'lerde numarası eşleşen Marker denklemi yazarların LaTeX'iyle
  değiştirilir; ölçülmedi, bu dilimde yok.
- **D — Bir sayfa hangi koşulla Marker'a gitmesin?** Öneri **D3**: hiçbir sayfa Marker'dan çıkmaz; rota yalnız Marker'sız
  kişiye denklem verir, Marker'lı kişi için hiçbir şey değişmez. Neden: r1'in önerdiği D1 (örtülmemiş matematik öbeği
  koruması dahil tamam sayfa) 369 sayfanın 14'ünü çıkarıyordu, bunların birinde Marker daha fazla görüntü denklemi
  buldu ve 14'ü görüntüden denetlenmedi; kazancı yaklaşık 10 dakikalık bir tahmin (sayı 13). *D1*: bu kural, bilinen
  kaçırma kabul koşuluna ve arayüze "heuristically complete" olarak girerek. *D2*: öbek koruması olmadan (45 sayfa,
  5'inde Marker'ın bulduğu bir denklem metin katmanında kalır): kanıtı bugünkünden kötüleştirir.
- **E — Rota nerede koşsun?** Öneri **E1**: denklemlerin bugün okunduğu yerlerde (arka plan okuyucu, yanıt, tablo, hücre)
  (karar 6, sapma 6). *E2*: ayrıca tam metin getirme koşusunda bir arXiv PDF'i gelir gelmez, böylece D85'in okuma koşusu da
  kaynaktan denklem görür; SW10.6'nın "one reading step" sözüne daha yakın, ama D98'in üst üste binen getirme koluna ve
  D85'in sayfa seçimine dokunur, ayrı ve tam incelenen bir iş ister.
- **F — Varsayılan açık mı?** Öneri **F1**: kapalı (`DEIXIS_ARXIV_SOURCE=off`), dilim 24'ün ölçümüne kadar; plan kuralı 7
  ("ölçülmemiş hiçbir şey kullanıcıya ya da canlı kütüphaneye ulaşmaz"). PDF'ler araştırmalar arasında paylaşıldığı için
  rota `sw` bayrağına bağlanamaz; kendi bayrağı olur. *F2*: açık; Marker'sız kişi hemen alır, ama ölçülmemiş eşleme
  canlı kütüphanenin pasajlarını değiştirir.

## Global constraints

- **Kazanç, gereklilik değil.** Kaynak yoksa, gelmezse, okunamazsa, eşleşmezse ya da D45 reddederse okuma bugünkü gibi
  sürer; hiçbir koşu kaynak yüzünden durmaz ya da duraklamaz.
- **Marker'lı kişi için hiçbir şey değişmez** (D3): Marker kuruluyken rota koşmaz, kaynak istenmez.
- **Kanıt sınırı.** Yalnız eşiği geçmiş, yerleşmiş, numaralı görüntü denklemleri kaynaktandır; parça etiketi,
  `math_json.source` ve arayüz bunu ve hangi numaraların kaynaktan geldiğini söyler. Düzyazı, satır içi matematik ve
  numarasız denklemler kaynaktan gelmez.
- **Sürüm kimliği.** Kaynak, PDF'in kendi adlandırdığı ve kaydın ön baskı olarak taşıdığı sürümdür; başka sürümün kaynağı
  hiçbir zaman kullanılmaz (karar 1'in tablosu). Rota başka bir kayda ve başka bir sürümün PDF'ine dokunmaz (D4, D48).
- **Güvenilmez içerik.** Arşiv ve LaTeX veridir, talimat değildir; diske açılmaz; alt süreçte, karar 3'ün sınırlarıyla
  okunur; getirme `fetch.py`'nin korumalarından geçer.
- **arXiv'e saygı.** Aynı veri dizinini kullanan bütün DEIXIS süreçlerinde bu rotanın `arxiv.org`'a iki isteğinin
  sunucuya varışı arasında en az 3 sn (karar 2'nin dosya kilidi, isteğin tamamı boyunca tutulur); aynı sürüm bir kez getirilir; en çok 3 olağan getirme girişimi ve bozulan saklı dosya için ayrıca tek bir onarım girişimi (girişim başına
  yönlendirmeleriyle en çok 6 HTTP isteği). Başka veri
  dizinleri ve DEIXIS'in arXiv araması bu sayıma girmez. Hiçbir isteğe kişinin e-postası ya da başka bir kimliği eklenmez.
- **Yalnız POSIX.** Rota `fcntl` gerektirir; Windows'ta bayrak ne olursa olsun kapalıdır (dilim 21 / D103 gibi).
- **Bayrak kapalıyken ne değişmez, ne değişir.** Kapalıyken hiçbir kaynak istenmez ve hiçbir PDF çıkarımı değişmez. Bayrak
  ne olursa olsun değişenler: migration `0054` (iki tablo ve `passages`'ın yeniden kuruluşu), `report_section_draft.v2`,
  StepInput enum'u, `equation_origin` denetimi, yöntem paragrafı ve `skill_package_hash`.
- **Tek migration:** `0054_arxiv_latex_source.sql`. Eski migration düzenlenmez.
- **Sözleşme değişikliği tek yerde:** `text_source` değeri, `report_section_draft.v2` ve `equation_origin` denetimi; başka
  şema değişmez.
- **Konuya özgü hiçbir şey yok;** eşikler adlı sabitlerde, her okumaya yazılı.
- **`uv.lock` değişmez;** yeni bağımlılık yok (`tarfile`, `gzip`, `fcntl` standart kütüphane).

## Task taslağı

1. **Kaynak arşivi** (`documents/arxiv_source.py`; karar 3). Saf işlevler ve alt süreç girişi. Testler bellekte kurulan
   sentetik tar ve gzip'lerle: iç içe `\input` ve kendini içe alan dosya; `%` ve `\%`; isteğe bağlı argümanlı
   `\newcommand`, `\def\x#1#2`, `\DeclareMathOperator*`; `\def\a{\a\a}` açıcı sınırında durur ve yalnız o grubu dışarıda
   bırakır; son satırı numaralı `align` tek grup, her satırı numaralı `align` üç grup, `\nonumber` satırları, yıldızlı
   ortamlar, `\tag{A1}`, numarası ilk satırda olan ortam "devam eden"; `\label` / `\hspace` / `\setcounter` silinir;
   `\eqref` taşıyan grup yerleşmez; 1.001 üyeli arşiv `too_large`; 1 KB'lık ama 100 MB'a açılan gzip 64 MB'ta ve süre
   sınırı içinde `too_large`; 6 MB'lık tek `.tex` `too_large`; sembolik bağlantı, sert bağlantı, `../evil.tex`,
   `/etc/evil.tex` ve aygıt üyesi okunmaz, diske hiçbir şey yazılmaz (geçici dizinin içeriği testten önce ve sonra aynı);
   alt süreç zaman aşımı ve bellek bekçisi `unreadable` verir; stdout'a yazmadan önce stderr'e 1 MB yazan sahte çocuk
   takılmadan biter (süre sınırının çok altında) ve stderr'den yalnız son 4.000 karakter kalır; PDF `pdf_only`, `.tex`'siz tar `no_tex`; listede olmayan
   komut (`\ket` yoksa, `\paren`) `katex_unknown`, `\mbox` yeniden yazılır. `katex_commands.json`'ı üreten betik ve
   dosyanın KaTeX sürümünü taşıdığını doğrulayan test.
2. **Sürüm ve getirme** (`documents/arxiv_source.py`, `documents/fetch.py`; karar 1, 2). Testler (`httpx.MockTransport`):
   karar 1'in tablosunun her satırı (adresten sürüm; damgadan sürüm, sentetik PDF'e döndürülmüş damga satırı; farklı →
   `version_conflict`; hiçbiri → `no_version`; arXiv kimliği taşımayan kayıt → `record_identity_unknown`; başka arXiv
   kimliği taşıyan kayıt → `record_version_conflict`; DOI'si bir arXiv kimliği, `landing_url`'i başka bir arXiv kimliği
   taşıyan kayıt → `record_identity_conflict`, istek yok ve yeniden denenmez; `arXiv v1` kaydında v2 dosyası → `record_version_conflict`;
   `publishedVersion` kaydında damgalı dosya → `record_version_conflict` ve istek yok; `submittedVersion` kaydında
   `eligible`); `/e-print/`'ten aynı ana makinedeki `/src/`'ye yönlendirme izlenir; `Content-Disposition` başka sürüm →
   `version_mismatch`; 406, 429, 503 ve zaman aşımı → `not_settled`, `attempts` olağan girişimden önce artar (onarım girişiminde artmaz, `repairs` 2 olur), `RETRY_AFTER`
   dolmadan yeniden istenmez, üçüncüden sonra istenmez; 30 MB'ı aşan yanıt `too_large`; özel ağ adresine çözülen ana makine
   reddedilir; iki ardışık getirme arasında en az 3 sn (saat monkeypatch'li); **iki ayrı süreç** (aynı geçici veri
   dizini, `multiprocessing`, yerel bir HTTP sunucusu her isteğin **varış anını sunucu tarafında** kaydeder ve yanıtı
   geciktirebilir) farklı sürümleri aynı anda ister: sunucunun gördüğü varışlar arasında en az 3 sn, ilk yanıt 2 sn
   geciktirildiğinde de; **çökme:** ilk süreç isteğini sunucuya ulaştırıp yanıt beklerken `SIGKILL` ile öldürülür, ikinci
   sürecin isteğinin sunucudaki varışı ilkinin varışından en az 3 sn sonradır ve `.rate`'teki `ended_at`'siz damga
   yüzünden başlangıç + 33 sn'den önce gönderilmez (saat yamalı süreçte); **iptal:** ilk sürecin getirme görevi istek
   sunucudayken iptal edilir, `ended_at` yazılır, kilit bırakılır ve ikinci varış ilkinden en az 3 sn sonradır; kilit
   beklerken iptal edilen görev kilidi hiçbir zaman almaz (iptalden sonra üçüncü bir süreç kilidi hemen alır); **son
   tarih:** gövdeyi yavaş gönderen ve dört kez yönlendiren sunucuda getirme 30 sn'de (yamalı saatle) `not_settled` biter
   ve kilit bırakılır; **yönlendirme:** `/e-print/` → `/src/` yönlendirmesinde sunucu iki varışı en az 3 sn arayla görür
   ve ikinci sürecin isteği ikisinden sonra, en az 3 sn arayla gelir; ilk adımın yanıtından sonra, ikinci adımdan önce
   öldürülen süreçten sonra da aralık tutar; **bozulma:** üçüncü denemede indirilmiş dosya silinince ya da bir baytı
   değişince bir kez yeniden getirilir ve okunur, ikinci bozulma `unreadable` (`cache_corrupt`) verir, istek gitmez; kilit
   beklemesi (sürüm anahtarı ve hız kilidi toplamı; başka bir süreç sürüm kilidini tutarken de) 120 sn'yi aşınca istek yok, satır yok, deneme sayılmaz ve durum `pending`; karar 2'nin geçiş tablosunun her satırı (`downloaded` → `content`
   `tex` / `pdf_only` / `no_tex` / `too_large` / `unreadable`; 403 → `not_settled`; 404 → `unreadable`; kişinin yeniden
   denemesi); `fcntl` yokken (yama) bayrak `auto` olsa da istek yok ve durum "not available on this system"; aynı sürümü
   taşıyan iki PDF aynı anda okunur, tek istek gider; dosya yazılıp satır yazılmadan "çökme" (yama) → sonraki okuma yeniden getirir; bozulmuş dosya
   (sha256 tutmuyor) → `not_settled`, olay, yeniden getirme; `.part` artığı servis açılışında silinir; bayrak `off` iken
   hiçbir istek yok (hiçbir çağrıya izin vermeyen taşıyıcı).
3. **Eşleme** (karar 4). Testler, PyMuPDF'le kurulan sentetik PDF'lerle (gövde metni, denklem satırları, sağda `(1)`,
   `(2)`; bir satırda simge fontu harfi): doğru grup seçilir; harfleri aynı iki grup sırayla ayrılır; geri çağırması 0,90
   altında kalan eşleme yerleşmez; pencere farkı 0,20'den küçük olan yerleşmez; pencerede rakip yokken makale farkı
   0,20'den küçük ve seçilenin F1'i başka bir grubunkinden düşükse yerleşmez (harfleri-ezmeme); düzyazı satırının sonundaki
   "(3)" numara sayılmaz; kaynağa numarasız bir grup eklenince atama değişmez; bölgenin önündeki "where" satırı kırpılır ve
   sayfa metninde kalır; aynı denklemin dikeyde örtüşen `max` parçası emilir; bölgede kalan "section of … and" satırı
   `foreign_text` ile yerleşmeyi durdurur; devam eden grup `continues_after_number`; sabitler `math_json.source.params`'ta.
4. **Yerleştirme** (`pdf.py`, `documents/arxiv_source.py`; karar 5). Testler: yerleştirme verilmeyen çıkarımın sayfa metni
   bugünküyle bayt bayt aynı (`_blocks`'a eklenen maskeli satır metni sayfa metnine girmez); yerleşen bölgenin yerine
   `$$…$$ (n)` bloğu, düzyazı ve öbür satırlar aynen; bölgesi sayfa metnine girmeyen eşleme yerleşmez; `placed` ofsetleri
   sayfa metnindeki bloğu tam gösterir; `chunk_page` yeni sürümde `$$` bloğunu bölmez, eski sürümde bugünkü gibi keser;
   `normalize_page_text`'e geçen `chunk_page` bütün mevcut testlerde bayt bayt aynı çıktıyı verir; **boşluk testi:** sekme,
   çift boşluk ve baştaki boşluklarla dolu, bir indirme uyarısı satırı taşıyan, bir bloğunun LaTeX'inde çift boşluk olan ve
   iki parçaya bölünen sentetik bir sayfada her `placed` aralığı `normalize_page_text(sayfa)[start:end]` ile bloğun
   normal hâlini tam verir, `latex_source` yalnız bloğu taşıyan parçadadır, parçanın kaynak numaraları doğrudur ve blok
   bulunamayınca okuma `offsets_unresolved` ile yazılmaz; tablo başlıklı ve OCR sayfalarına yerleşme yok.
5. **Okuma servisi ve akış** (`workflow/equations.py`, `flow.py`; karar 6). Testler (sahte Marker, sahte getirme, sahte
   saat): karar 6'nın dört öncelik kuralı ve kural 3'ün tablosunun her satırı; **yarış:** sahte Marker'ın
   `available()`'ı sahte getirme sırasında doğru olunca rota yazmaz, adım `superseded_by_marker`, varlık `pending` olur ve
   Marker bugünkü sürümü yazar; yazmadan hemen sonra doğru olunca rota okuması `pending` olur ve Marker yine okur;
   **uygunluk retleri:** Marker yok, bayrak `auto`; `record_identity_conflict`, `record_identity_unknown`,
   `record_version_conflict`, `no_version` ve `version_conflict` taşıyan her PDF için `equation_state` `no_source` ve
   nedeni döner (asla `pending` değil), araştırma görünümünün kaynak satırı nedeni gösterir, arka plan ve koşu adımı o
   PDF'e bakmaz ve istek gitmez; bayrak `off` iken aynı PDF bugünkü gibi `pending`;
   **kayıt zenginleşmesi, iki yön:** `record_identity_unknown` (`no_source`) bir PDF'in kaydına `enrich_source`
   `https://arxiv.org/abs/<id>` `landing_url`'i getirince uygunluk `eligible` olur, durum `pending`, sonraki okuma kaynağı
   yerleştirir; `+arxiv-latex-v1` ile okunmuş bir PDF'in boş `landing_url`'i başka bir arXiv kimliğiyle dolunca aynı
   işlemde uygunluk `record_identity_conflict`, güncel sürüm rotadan önceki sürüme döner (rotanın satırı `superseded`,
   öncekinin `current`; `source_assets`'in dört alanı önceki satırınkine eşit; tek `current` indeksi ihlal edilmez), kaynak pasajları güncel
   aramada ve StepInput'ta görünmez, onlara bağlı kanıt `text_superseded` görünür, durum `no_source`, istek gitmez;
   aynı kimliği taşıyan bir `landing_url` hiçbir şeyi değiştirmez;
   **son yazma koruması işlemin içinde:** `guard` `reextract_asset`'in `BEGIN IMMEDIATE` işleminde, ilk yazmadan önce
   çağrılır (yamalı `guard` çağrıldığında `conn.in_transaction` doğru); inceleme bittikten sonra, `guard` koşmadan hemen
   önce ayrı bir süreç PDF'i kaldırır (`store.py:1491-1499`'un yolu) → hiç pasaj ve çıkarım yazılmaz, sonuç
   `asset_removed`; aynı noktada **ikinci bir bağlantı** (ayrı süreç, aynı veritabanı dosyası) kaydın `version`'ını `publishedVersion` yapar ya da
   `landing_url`'ini başka bir arXiv kimliğine çevirir → hiç pasaj yazılmaz, güncel çıkarım sürümü aynı kalır,
   `asset_arxiv_versions` yeni sonucu (`record_version_conflict`) taşır ve pasajsız red kaydının nedeni
   `record_version_changed`; ikinci bağlantı `source_assets.extraction_version`'ı `+marker-` bir değere çevirirse → hiçbir
   şey yazılmaz, adım `superseded`; ikinci bağlantının yazması `guard` işlemi açıkken `database is locked` ile bekler ya da
   düşer, asla araya girmez; `guard`'sız çağrılar bugünkü gibi davranır; **çökme ara durumu:** `arxiv_sources` `downloaded` + `tex`
   yazılıp çıkarım yazılmadan süreç kesilince (yama) varlık `pending`, sonraki okuma ağ isteği yapmadan saklı dosyadan
   yerleştirir;
   `installing()` doğruyken rota koşmaz; Marker yokken uygun PDF `…+arxiv-latex-v1` olur, yerleşen bloğu taşıyan
   parçalar `latex_source`, aynı sayfanın öbür parçaları `text_layer`; Marker kuruluyken rota koşmaz ve istek gitmez,
   `test_equations.py` ile `test_math_reader.py` değişmeden geçer; Marker sonradan kurulunca rota okuması `pending` olur ve
   Marker bugünkü sürümü yazar; Marker'la okunmuş PDF, Marker kaldırılınca da rotayla okunmaz (C1); bir yanıt koşusu
   kaynak gelmeyince (`not_settled`), kalıcı yokken, hiçbir şey yerleşmeyince, D45 reddedince ve `RunInProgress`'te
   duraklamadan biter, adım çıktısı durumu taşır; aynı koşu duraklatılıp sürdürülünce yeniden istek gitmez; adım `running`
   kalmış "çökme" sonrası yeniden girişte istek gitmez ve `reextract_asset` `unchanged` döner; getirme sırasında görev
   iptali: `attempts` sayılmış, satır `downloaded` değil, `.part` açılışta silinir; bayrak açık→kapalı: yeni istek yok, saklı
   okuma `read` görünür; kapalı→açık: kalan PDF'ler okunur; uygun olmayan PDF'te hiçbir şey değişmez; rota tam metin
   getirme, okuma ve keşif koşularında çağrılmaz (E1); `asset_arxiv_versions` satırı PDF başına bir kez yazılır ve
   `equation_state` PDF açmaz (`pymupdf.open` hata verecek biçimde yamanınca araştırma görünümü yine döner); reddedilen
   rota çıkarımı görünümün "rejected extraction" alanında değil, denklem durumunda görünür.
6. **Migration ve sözleşme** (`0054`, şemalar, yöntem, fikstürler, `contracts.py`; karar 7). Testler: `0053`'te kurulmuş
   pasajlı, kanıt bağlı, gömülü ve FTS'li bir kütüphane migration'dan sonra: `passages`'ın `sqlite_master` DDL'i öncekinden
   yalnız CHECK'te farklı (adın tırnaklanması normalize edilerek); `cell_evidence_same_source` tetiğinin SQL'i aynı ve
   hâlâ çalışıyor (yanlış kaynaklı hücre kanıtı reddedilir); satır sayısı, `rowid`, `id`, `text_sha256`, `text_source`
   aynı; FTS sorguları aynı sonucu verir ve FTS5 `integrity-check` geçer; migration'dan sonra eklenen bir pasaj FTS'de
   bulunur; `passages_no_update` güncellemeyi reddeder; `foreign_key_check` boş; `evidence_links`, `cell_evidence_links`,
   `report_citation_links`, `passage_embeddings` ve `stage_decisions.quote_passage_id` çözülür; `arxiv_sources` ve
   `asset_arxiv_versions` boş açılır; CHECK `latex_source`'u kabul eder, bilinmeyen değeri reddeder; StepInput
   `latex_source` taşır; rapor taslağı `v2` `equation_origin.text_source: "latex_source"`'u kabul eder; `equation_origin`'i
   StepInput'ta olmayan pasaja, iddianın kendi `passage_ids`'inde olmayan bir pasaja ya da pasajın etiketinden farklı bir
   köken değerine veren taslak `unknown_passage_id` / `equation_origin_not_cited` / `equation_origin_mismatch` alır
   (`marker` ve `ocr` için de); `skill_package_hash` değişti ve fikstürlerde yenisi var.
7. **Sürüm etiketi ve D4** (`views.py`, `store.py`, `api/app.py`; karar 8). Testler: `math_json.source` alanları;
   `submittedVersion` kaydında `arXiv v2` kaynağı ikisini de gösterir, kayıt etiketi yeniden yazılmaz; kişinin verdiği
   yayımlanmış PDF'i (baş kayıtta PDF metni) olan işte yanıt o PDF'i okur ve arXiv sürümünün `latex_source` pasajları
   StepInput'ta yok; pasaj yükü (`api/app.py:1544-1548`) parçaya düşen kaynak numaralarını taşır.
8. **Arayüz** (karar 8, 9). `.impeccable.md` önce. `labels.ts` (kaynak satırı durumları: `read`, `source_waiting`,
   `no_source`, `failed`), `PassageSheet.tsx` (`latex_source` uyarısı, parçanın numaralarıyla), `ResearchView.tsx` (alıntı
   rozeti), `api.ts` (`text_source` türü, yeni durumlar), `i18n.ts` (Türkçe). Playwright: yeni **O**
   (`arxiv-source.spec.ts`), fikstür sunucusu `DEIXIS_FIXTURE_ARXIV_SOURCE=fake` ile sahte kaynak, Marker'sız ve bir
   sentetik arXiv PDF'i: kaynak satırı "Equations from the arXiv source (v2)", pasaj görünümünde parçanın numaralarını
   söyleyen uyarı ve KaTeX'le çizilmiş denklem, alıntı çipinde rozet. Mevcut A–N değişmeden geçer. Ekran görüntüsüyle
   masaüstü ve telefon genişliği.
9. **Kabul** (`.local/sw-slice22-acceptance-<tarih>/`; model yok). (a) Canlı kütüphanenin SQLite yedek API'siyle alınmış,
   oturum dizininde `0054`'e kadar taşınmış kopyasında (taşımanın `0053` → `0054` adımında sayı 16'nın denetimleri,
   yani `rowid` / `id` / `text_sha256` / `text_source` eşitliği, FTS sorgusu ve `integrity-check`, `foreign_key_check`,
   DDL farkı ve tetiklerin SQL'i, tekrarlanır ve yazılır), planın indirdiği 53 kaynak
   (`.local/sw-slice22-plan-2026-09-25/src/`) kopyanın `arxiv-sources/`'ına konarak (ağsız), ürünün kendi koduyla bir kuru
   koşu betiği (`scripts/arxiv_source_report.py`) her uygun PDF için eşleme kuralını geçen adayları, gerçekten yerleşen
   blokları ve her yerleşmeme nedenini (KaTeX, `\ref` / `\cite`, uzunluk, tablo / OCR sayfası, `not_in_page_text`,
   `offsets_unresolved`) ayrı sayar; adayları planın 873 adayıyla (43 sürüm, 1.520 numara satırı, bütün sayfalar)
   karşılaştırır, ±%10'u aşarsa nedeni yazar; yerleşenlerin sayısının plan tarafında bir karşılığı yoktur ve öyle
   raporlanır; Marker'ın saklı okumasıyla uyum sayı 7'nin yöntemiyle
   (ölçüt değil, karşılaştırma). (b) Yerleşen her grubun LaTeX'i Node ve web uygulamasının KaTeX'iyle çizilir: 0 hata
   beklenir, olursa listelenir. (c) Aynı kopyada Marker'sız bir okuma (`DEIXIS_ARXIV_SOURCE=auto`, oturum
   `DEIXIS_DATA_DIR`'i, Marker kurulu değil) üç PDF'e uygulanır: sürüm, parça etiketleri ve `math_json.source` yazılır,
   eski pasajlar ve onlara bağlı kanıtlar çözülür. (d) Ürünün getirme yoluyla `arxiv.org`'dan üç canlı getirme, 3 sn aralık
   tutulur, dosya adı ve sha256 kaydedilir (tek ağ erişimi). (e) Alt süreç süresi makale başına (ortanca, en çok). (f)
   **Görüntüden okuma:** kod ve sabitler donduktan sonra (a)'nın yerleştirmelerinden tohumu yazılı, makale başına en çok 3
   olan 40 yerleşme (20 makale farkıyla, 20 sırayla) sayfa görüntüsünde bölgesi çizilerek gözle okunur; her biri için
   grup doğru mu, bölge başka metni siliyor mu yazılır. Birden fazla yanlışsa dilim kapanmaz; yanlışlar ve nedenleri satır
   22'ye yazılır.
10. **Kapanış.** D104 (A–F'nin sahip cevabıyla, SW10'dan altı sapmayla ve sayı 9'un sınırlarıyla). Limits: tek bilgisayar,
    tek kütüphane, üç alan; kural bu verinin görüntü örneklemini gördükten sonra seçildi, ayrılmış sınama kümesi yok,
    görüntüden okuyan tek kişi ve görüntü örnekleminin 77/77'si bir doğruluk sınırı değil; 873 ön-örnek adayıdır,
    yerleşme sayısı değil; yalnız POSIX; hız sınırı yalnız aynı veri dizinindeki süreçler arasında; Marker ölçüt değil; hız kazancı yok (D3); ürünün yerleştirmesi yalnız kabul (a) ve (f)'de
    ölçülür; `export.arxiv.org`'un 406'sı ve nedeni; bayrak kapalı, canlı kütüphanede hiçbir şey değişmedi.
    `search-workflow-review-2026-09-18.md`'de SW10'un durum satırı: 6 (a)'nın denklem kısmı, 7'nin eşleme kısmı ve 8
    bayrak arkasında ve yalnız Marker'sız kişi için kuruldu; D85'in okuma koşusu bu denklemleri ancak PDF arka planda ya
    da bir yanıtta okunmuşsa görür; 6 (a)'nın düzyazısı, 6 (c), SW10.7'nin hız maddesi ve E2 açık. `sw-status.md` satır 22.

## Kabul koşulları

- Pytest tam koşu: bilinen tek hata (`test_extraction_is_stopped_when_it_exceeds_the_memory_limit`) ayrı, kalan tam koşu
  geçti; bayrak kapalıyken ve Marker kuruluyken mevcut denklem testleri değişmeden geçer; yeni testler ağa gitmez
  (modüllerinde `httpx` ve `socket` koruması); mevcut takımın ağ davranışı bu dilimde yeniden kanıtlanmaz; build temiz;
  lint uyarısı 17'yi aşmaz; Playwright A–O geçer.
- Task 9'un (a)–(f)'si yazılı; (b)'de yerleşen grupların KaTeX hatası 0 ya da listeli; (f)'de en çok bir yanlış.
- En yüksek migration `0054`; `skill_package_hash` yeni değerde ve D104'te yazılı; `uv.lock` aynı.

## Bu dilimde yok

- Düzyazının ve satır içi matematiğin kaynaktan alınması; numarasız görüntü denklemleri.
- Marker kuruluyken kaynak: Marker'ı atlayan sayfalar (D1, D2) ve Marker'ın okumasını kaynakla düzeltmek (C2).
- Tam metin getirme ve okuma koşularında rota (E2).
- Aksanları (`\hat`, `\tilde`, `\bar`, `\widetilde`) ayırt eden harf sayımı; sayı 9'daki yanlışın kökü bu, ama kural onu
  harfleri-ezmeme ile dışarıda bırakıyor.
- `\DeclarePairedDelimiter` ve beş biçim dışındaki makro tanımları (KaTeX kapısı onları yerleştirmez).
- Yayımlanmış sürümün PDF'ine ön baskı kaynağından denklem (karar 1).
- bioRxiv ve başka ön baskı sunucuları (kaynak sunup sunmadıkları ölçülmedi).
- Ayarlar'da bir anahtar; bayrak yalnız ortam değişkeni.
- Kaynağın derlenmesi; rota derlemez.
- `export.arxiv.org`'un 406'sının nedeni.
- `equation_origin` pasajının bir matematik aralığı taşıdığının denetimi (şemanın `:89`'daki sözünün öbür yarısı).

## Ölçülmedi

Görüntüden okumanın ikinci bir okuyucuda tuttuğu (tek okuyucu, planın yazarı). Kuralın ayrı veride tutması. Ürünün
yerleştirmesinin eşiği geçenlerin kaçını gerçekten yazabildiği (kabul (a), (f)). r1'in 14 tamam sayfasının görüntüye göre
doğruluğu (D3 onları kullanmadığı için bakılmadı). Bu kütüphanenin dışındaki alanlar ve daha yeni ya da daha eski LaTeX
alışkanlıkları. Planın 873 adayından ürünün kaçını gerçekten yerleştireceği. Görüntü örnekleminden başka veriye
taşınabilecek bir hata oranı. Yayımlanmış sürümle ön baskı arasındaki denklem farkı. Modelin `latex_source` denklemlerini nasıl
alıntıladığı. arXiv'in yük altındaki davranışı ve 406'nın nedeni. Migration'ın `0053` şemasında davranışı (prova `0036`
kopyasındaydı). Canlı hiçbir şey.

## Sol r1 bulguları ve yapılanlar

1. **Eşik doğruluk güvencesi değil; sıra farkı boşaltıyor.** Ölçüldü (sayı 8: 924'ün 774'ünde pencere boş); 118 eşleme
   görüntüden okundu (sayı 9: 1 yanlış, sıranın harfleri ezdiği bir eşleme); kural harfleri-ezmeme, kırpma, emme, yabancı
   sözcük ve devam eden grup kurallarıyla değişti (karar 4); "eşiği geçti" işlemsel tanım oldu; kabul (f) kod bittikten
   sonra 40 yeni eşlemeyi görüntüden okutur. Ayrılmış sınama kümesi kurulamadı: bütün 43 sürüm kullanıldı; bu açıkça
   yazılı (sayı 9, Ölçülmedi, D104 Limits).
2. **Tamam sayfa kuralı bilinen bir kaçırmayı geçiriyor.** D3'e geçildi: hiçbir sayfa Marker'dan çıkmaz, Marker kuruluyken
   rota koşmaz (karar 5, sapma 2, soru D).
3. **Kayıt sürümü.** Karar 1'e tek çatışma tablosu ve `record_version_conflict` eklendi; canlı kütüphanede ölçüldü (sayı
   2); testler task 2 ve 7'de.
4. **Hata ve sürdürme durum makinesi.** Karar 6'da durum tablosu, koşu adımının hiçbir rota sonucunda duraklamaması,
   bir koşunun en çok bir deneme yapması, çökme ve iptalde eş güçlülük; karar 2'de kilit, istekten önce sayılan deneme,
   `.part` + `fsync` + `os.replace`, sonra satır, okurken sha256; testler task 2 ve 5'te.
5. **D45 ve bayrak iddiası.** D45 reddi `failed` durumu, duraklamasız (karar 6); bayrak iddiası PDF çıkarımı ve kaynak
   isteğiyle sınırlandı, bayraktan bağımsız değişenler adıyla yazıldı (Global constraints); açık→kapalı ve kapalı→açık
   tanımlandı (karar 6).
6. **Migration güvenliği.** Kopyada prova yapıldı (sayı 16); tetik sorunu bulundu ve karar 7'ye girdi; DDL, FTS
   bütünlüğü, yeni eklemenin FTS'de bulunması ve her bağımlı tablo testleri task 6'da.
7. **Arşiv sınırları.** Karar 3'e toplam açılmış bayt, tek üye, açıcı çağrısı, grup uzunluğu ve alt süreç süre/bellek
   sınırları eklendi; ölçüldü (sayı 5); bomba, bağlantı, mutlak ad, `..`, döngü testleri task 1'de.
8. **E1 bir sapma.** Altıncı sapma olarak yazıldı; kapanış cümlesi D85'in bu denklemleri ne zaman gördüğünü söyler
   (task 10).
9. **Karışık sayfa ve köken denetimi.** Etiket parça başına oldu, arayüz metni parçanın numaralarını söyler, yöntem
   paragrafı düzeltildi; `equation_origin` denetimi eklendi (karar 7, 8).
10. **İstemin git kuralları.** İstem uygulayana commit, pull ve push yaptırmaz; commit'i kod incelemesinden sonra
    eşgüdümcü yapar; plan commit edilmiş olmalıdır, bu bir başlama şartıdır (istem).
11. **Hız dili.** Giriş, karar 9 ve satır 22 hız kazancından söz etmiyor; r1'in 14 sayfalık kazancı "tahmin" olarak
    yalnız sayı 13'te.

## Sol r2 bulguları ve yapılanlar

r1 tablosundaki kısmen kapanan dört bulgu (1, 4, 7, 9) ve beş kalan çelişki:

1. **D3 durum önceliği çelişkili; Marker yarışı.** Karar 6 hedef ve durumu dört öncelik kuralıyla, sırayla verir (Marker
   var → bugünkü kod; Marker yok ve rota okuması güncel → `read`; kural 3'ün tablosu; öbür her durum bugünkü gibi); tablonun
   "bayrak ne olursa olsun `read`" satırı kural 2'ye taşındı. Son yazma denetimi, arada `await` olmadan Marker'ı, bayrağı,
   C1'i ve kaydı yeniden denetler; iki yarış sırası da Marker'ın sürümüyle biter; test task 5'te.
2. **Ofset uzayı tanımsız.** Karar 5 tek uzayı seçer: `chunk_page`'in kendi normal metni (`normalize_page_text`),
   `remove_download_notices`'ten sonra; `placed` ofsetleri, `payload_ref` ve parça numaraları hep bu uzayda; blok tam bir
   kez bulunamazsa okuma yazılmaz. Boşluk testi task 4'te.
3. **873 yerleşme değil; 0/77 bir sınır değil.** Sayı 12 "son eşleme kuralını geçen 873 aday" der ve sayıya girmeyen
   kapıları sayar; kabul (a) gerçek yerleşeni ve her yerleşmeme nedenini ayrı sayar. Sayı 9'daki Clopper-Pearson sınırları
   kaldırıldı; 77/77'nin başka veriye ya da okuyucuya taşınamayacağı sayı 9'da, Ölçülmedi'de, D104 Limits'te (task 10) ve
   satır 22'de yazılı.
4. **`equation_origin` iddianın pasajlarında olmalı.** Karar 7'ye `equation_origin_not_cited` eklendi; test task 6'da.
5. **Süreçler arası hız sınırı, POSIX, kaynak geçişleri, alt süreç çıktısı.** Karar 2: veri dizini başına dosya kilitli
   3 sn kapısı (farklı sürümler dahil; başka veri dizinleri ve arXiv araması hariç, adıyla); `status` (indirme) ve
   `content` (inceleme) ayrı sütunlar ve bir geçiş tablosu; kaynak yalnız `downloaded` + `tex` iken kullanılır. Karar 1 ve
   Global constraints: yalnız POSIX, Windows'ta rota kapalı. Karar 3: ebeveyn stdout'u okurken 5 MB'ta keser, stderr'in
   son 4.000 karakteri, 60 sn. Testler task 1 ve 2'de (iki süreçli hız testi dahil).
6. **Kimlik iddiası (r1 bulgu 3'ün notu).** Karar 1'e kaydın taşıdığı arXiv kimliğinin dosyanınkiyle aynı olması şartı
   (`record_identity_unknown`, `record_version_conflict`) eklendi; 56 kaydın 56'sında aynı (sayı 2). Kaydın işe
   bağlanmasının doğruluğu ayrıca denetlenmez; bu açıkça yazılı.
7. **0053 provası (r1 bulgu 6'nın notu).** Kabul (a)'nın taşıma adımında sayı 16'nın denetimleri tekrarlanır ve yazılır.

## Sol r3 bulguları ve yapılanlar

1. **Son yazma koruması atomik değil.** Denetim `reextract_asset`'in önünden içine taşındı: `reextract_asset` isteğe
   bağlı bir `guard` alır ve onu kendi `BEGIN IMMEDIATE` işleminde (`store.py:1391`, `db.py:47`) ilk yazmadan önce
   çağırır; kimlik, etiket ve güncel çıkarım aynı işlemde yeniden okunur, başka bir süreç o arada yazamaz. Kayıt
   değişmişse pasaj yazılmaz, yalnız uygunluk satırı güncellenir ve red kaydı eklenir; güncel çıkarım değişmişse hiçbir
   şey yazılmaz. Marker'ın
   varlığı veritabanı dışıdır; `COMMIT`'ten sonraki kurulumu kural 1 karşılar (karar 1, karar 6). Test: ikinci bağlantının
   kayıt ve varlık değişiklikleri (task 5).
2. **Hız kapısı istek başlangıcını kilitlemiyor.** Kilit isteğin tamamı boyunca tutulur, bekleme bir önceki isteğin bitiş
   anına göre yapılır; iki süreçli test sunucunun gördüğü varış anlarını ölçer, yanıtı geciktirilmiş hâliyle de (karar 2,
   task 2).
3. **`downloaded + tex`, çıkarım yok.** Kural 3'ün tablosuna satır eklendi: `pending`, arka plan ve koşu adımı ağ isteği
   yapmadan saklı dosyadan eşler (karar 6); çökme testi task 5'te.
4. **İstemin görev 6'sı köken denetimini eksiltiyor.** İstemin Build 6'sına `equation_origin_not_cited` ve testi aynen
   eklendi; plan task 6'da zaten vardı.
5. **Çatışan kimlikler; eşzamanlı boşaltma.** DOI, `landing_url` ve `oa_pdf_url` farklı arXiv kimlikleri taşırsa kalıcı
   `record_identity_conflict` (karar 1'in tablosu, `asset_arxiv_versions` CHECK'i, task 2); ölçülen 56 kayıtta bu durum
   yok, kural yine de yazıldı. Alt sürecin stdout ve stderr'i iki görevle aynı anda boşaltılır; 1 MB stderr testi (karar
   3, task 1).

## Sol r4 bulguları ve yapılanlar

1. **Kalıcı uygunluk reddi `pending` görünüyor.** Kural 3 artık uygunluk retlerini de kapsar; tablosunda retler
   `no_source` ve nedenle görünür, arka plan ve koşu onlara bakmaz (karar 6). Kayıt değişince guard'ın yazdığı yeni ret de
   aynı satırdan görünür. Görünüm testi task 5'te; bayrak `off` iken bugünkü `pending` kalır.
2. **Çökmede 3 sn garantisi yok; `to_thread` iptali.** `.rate` artık başlangıç damgasını istekten önce, `fsync` ve
   `os.replace` ile yazar; bitişi yazılmamış bir damga sonraki isteği başlangıç + 33 sn'ye kadar bekletir. Kilit
   `to_thread` yerine `LOCK_NB` ve `asyncio.sleep` ile alınır (iş parçacığı yok, iptal edilen bekleme kilidi hiç almaz),
   `finally`'de bırakılır (karar 2). Test: öldürme ve iptalden sonra sunucunun gördüğü varış aralığı (task 2).
3. **Toplam süre sözleşmesi.** Adres denetimi, bütün yönlendirmeler ve gövde okuma tek bir `asyncio.timeout(30)`
   içinde; kilit beklemesi 120 sn ile sınırlı, aşılınca istek ve satır yok; bütün beklemeler `asyncio.sleep`; kilit ve
   HTTP akışı `finally` / `async with` ile bırakılır (karar 2, karar 6'nın iptal paragrafı). Test task 2'de.
4. **Guard kaldırılmış PDF'i dışlamıyor.** Guard önce `source_assets.removed_at IS NULL`'ı denetler; kaldırılmışsa hiçbir
   şey yazılmaz, sonuç `asset_removed` (karar 6). Ayrı süreçte kaldırma yarışı testi task 5'te.

## Sol r5 bulguları ve yapılanlar

1. **3 sn kuralı yönlendirmeleri kapsamıyor.** Tek kural: yönlendirme adımları dahil her HTTP isteği hız geçidinden
   geçer. `fetch_file` her adımdan önce ve sonra geçit işlevlerini çağırır; kilit bütün getirme boyunca tutulur, bekleme
   ve damgalar adım başınadır (karar 2). Sunucu varış testi yönlendirmeli getirmeyi ve adımlar arasında öldürülen süreci
   de ölçer (task 2).
2. **Üçüncü denemeden sonra bozulan dosya.** `arxiv_sources.repairs` sütunu: ilk bozulma bir getirme hakkı daha verir
   (r6'da `attempts`'tan ayrı bir onarım hakkına çevrildi), ikincisi kalıcı `unreadable` (`cache_corrupt`); kişinin "yeniden dene"si sıfırlar (karar 2).
   Test task 2'de.
3. **Uygunluk kayıt zenginleşmesiyle eskiyor.** Kimlik alanını yazıldıktan sonra değiştiren tek yol `enrich_source`'un boş
   `landing_url`'i doldurmasıdır. O işlemde uygunluk PDF açmadan yeniden hesaplanır; `eligible` olan okunur, ret olan ve
   rotayla okunmuş PDF'in okuması güncel sürümü önceki sürüme döndürerek geri çekilir, pasajlar silinmez, gölgelenir
   (karar 1). İki yönlü test task 5'te.

## Sol r6 bulguları ve yapılanlar

1. **Geri alma bütün alanları geri almıyor.** Karar 1'de sıra: önce rotanın satırı `superseded`, sonra önceki satır
   `current` ve `source_assets`'in sürüm, durum, hata ve sayfa sayısı birlikte (`store.py:1405`'in alanları). Test task 5'te.
2. **Onarım ile üç deneme çelişiyor.** `attempts` yalnız olağan denemeleri sayar (en çok 3); onarım `repairs` ile sayılan
   ek tek istektir (karar 2'nin tablosu ve metni, global kısıt, istem, satır 22).
3. **Koşunun bekleme sınırı.** 30 sn yalnız HTTP getirmesi; önünde 120 sn kilit ve 33 sn ilk hız beklemesi; koşu PDF
   başına en çok 183 sn, arşiv alt süreci ayrıca 60 sn (karar 6'nın iptal paragrafı).

## Sol r7 bulguları ve yapılanlar

1. **3 + 1 sayacı.** Karar 2'nin sırası (adım 3) ve tablosu olağan getirmeyi (`attempts` +1) onarımdan (`repairs` 1 → 2,
   `attempts` değişmez) ayırır; 3 + 1 HTTP adımlarını değil getirme girişimlerini sınırlar (girişim başına en çok 6 HTTP
   isteği). İstem ve satır 22 aynı dili kullanır.
2. **Sürüm kilidinin beklemesi.** Sürüm anahtarı ve hız kilidinin beklemeleri ortak 120 sn bütçeyi paylaşır; PDF başına en
   kötü bekleme böylece 120 + 33 + 30 = 183 sn, arşiv alt süreci ayrıca 60 sn (karar 2, karar 6'nın iptal paragrafı).

## Sol r8 bulguları ve yapılanlar

1. **Sayaç kilitlerden önce yazılıyordu.** `attempts` / `repairs` artık iki kilit de alınıp ilk hız beklemesi bittikten
   sonra, ilk HTTP isteğinden hemen önce yazılır; bütçe aşımı hiçbir şey saymaz (karar 2'nin sırası, adım 3).
2. **Süreç içi kilit bütçe dışındaydı.** `asyncio.Lock`, sürüm anahtarı kilidi ve hız kilidinin alınması tek bir
   `asyncio.timeout(120)` içindedir (karar 2).
