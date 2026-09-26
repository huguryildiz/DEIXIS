# SW dilim 25 — Ölçütte popülasyon ve karşılaştırıcı, `include`'suz yanıt, Europe PMC tam metni, tıp sorusunun yeniden ölçümü

**Tarih:** 26 Eylül 2026. **Durum:** plan yazıldı; Sol r1 (yalnız yüksek) "hazır değil", 4 yüksek bulgu işlendi; r2 dördünü kapalı buldu, 2 yeni yüksek bulgu verdi, ikisi işlendi (son bölüm); r3 (son plan turu) ikisini kapalı buldu, 1 yeni yüksek bulgu (uyarı metni) verdi, sahip kuralı gereği turu açmadan metin düzeltildi (son bölüm); G2 sahibin seçimi (2026-09-26: SW21
dilim 25'e alındı); A1, B1, C1, D1, E1, F1, H1 önerildiği gibi (sahip soru sorulmadan ilerlenmesini istedi, 2026-09-26). **İnceleme kuralı (sahibin kararı, D105):** Sol
(`gpt-6-sol` · high) yalnız **yüksek** önemdeki bulguda durdurur; plan en çok **3**, kod en çok **4** tur. Orta ve düşük
bulgular işlenir ya da gerekçesiyle bırakılır, tur açtırmaz; üçüncü plan turundan ya da dördüncü kod turundan sonra açık
kalan yüksek bulgu sahibe gider. **Prompt:** [sw-slice25-prompt.md](sw-slice25-prompt.md). **Ana dosya:**
[sw-status.md](sw-status.md). **Karar:** D106 (en yüksek D105); yeniden ölçümün kararı D107. **Migration:** `0055`
(en yüksek `0054`; yalnız PDF bulma sağlayıcı listesine `europepmc`, karar 3a). **Önkoşul:** 24a bitti (D105). **Tür:** 25a Kur, 25b Ölç. **Uygulayan:** 25a Opus · high; 25b
Fable · high (dilim 24'ün kuralı: dondurma ve yorum muhakeme işidir), uzun koşan betik Sonnet arka plan ajanına
verilebilir. **İnceleme:** 25a tam (Sol · high, yukarıdaki kuralla); 25b'nin sonucu sahibe. **Plan:** Opus 5.5 · high.
**Ölçüm:** `.local/sw-slice25-plan-2026-09-26/`: `criteria.py` → `criteria.json`, `criteria.txt`; `includes.py` →
`includes-tre.json`; `flips.py` → `flips-tre.json`; `baseline.py` → `baseline.json`. Hepsi dilim 24a'nın saklı
kütüphanelerini (`.local/sw-slice24-campaign-2026-09-26-134050/data-*`) `immutable=1` ile okur; model çağrısı ve sağlayıcı
araması yok. SW21 için ayrıca `epmc_gain.py` → `epmc-gain.json`, `xml_check.py` → `xml-check.json`, `oa_pdf_check.py` →
`oa-pdf-check.json`: Europe PMC ve PMC'ye salt okunur istekler (DOI başına bir arama, 1,2 sn arayla, ürünün
User-Agent'ı, anahtar ve e-posta yok; toplam ~190 istek). Port 8765'e ve canlı kütüphaneye dokunulmadı. **Kapsam:** SW23,
SW22 ve SW21 (ürün), SW18 (ölçüm tarafı), dilim 24'ün tıp yarısının aynı kapılarla yeniden okunması, kapılar geçerse 24b.

**Goal:** Dilim 24a'nın tıp sorusunda düşürdüğü iki kapının ürün tarafındaki iki nedenini gidermek ve tıp sorusunu dilim
24'ün dondurulmuş kapılarıyla yeniden ölçmek. (1) SW23: sorunun adını koyduğu popülasyon ve karşılaştırıcı, önerilen
ölçütte kendi parçası olur; tam metin okuması her parçayı ayrı sorduğu için onları da sorar; kod, üç öneriden en az ikisinin
adını koyduğu bir öğeyi taşımayan bir çalışmayı ölçütün temeli yapamaz. (2) SW22: tam metin okumasından hiçbir `include`
çıkmayan bir `sw` araştırması, 422 ile reddedilmek yerine açık bir yanıtla biter: "yanıt başladığında tam metinde dahil
edilen iş yoktu", yanıtın başladığı andaki sayılarla, model çağrısı olmadan. (3) SW21 (sahibin seçimi): açık PDF'i bulunamayan
bir iş Europe PMC'nin açık erişim alt kümesindeyse tam metni oradan gelir; yeni arama kolu yok, yalnız tam metin bulma
sırasına bir kaynak. (4) SW18: tıp referans kümesinin kuralı genişler
ve ilk araştırmadan önce donar. Sonra yalnız tıp sorusunun 7 araştırması yeniden koşar (kuantumun sonuçları kalır), kapılar
yeniden okunur ve geçerse 24b koşar. Yeniden ölçüm bu dosyanın kararlarıdır; sonradan yeni plan gerekmez.

## Bugün kod ne yapıyor

Kod 26 Eylül 2026'da `822ac93` üzerinde okundu.

- **SW23'ün nedeni ürünün kendi istemidir, model gürültüsü değil.** Ölçüt önerisi yöntem dosyası popülasyonu açıkça
  "setting" sayar ve ondan parça yapılmasını yasaklar: "The **setting** is the population, system, domain, material or
  environment the question is asked about. … Make no part out of the setting"
  (`methods/deixis-research/references/criterion-proposal.md:17-20`). Kural 6 da "the aspects the question wants compared
  or reported are not parts" der (`:27-28`, zor durum `:45-46`); karşılaştırıcı bu yüzden ya hiç yazılmaz ya tasarım
  parçasının tanımına gömülür. Şema aynı şeyi söyler: "The setting the question asks about is not a part"
  (`contracts/research/criterion-proposal.schema.json:32`). D78 bunu Limits'ine yazmıştı: "Because the setting is no part,
  a paper doing the thing sought in another setting meets every part; only the search blocks keep it out"
  (`docs/decisions.md:873`). Setting kuralı, D78'in ölçümünde modelin aranan şeyi düşürmesini önlemek için kondu; o kazanç
  (kural 5, aranan şeyin kendi parçası) korunmalıdır.
- **Uzlaşma.** `criterion.consensus` (`backend/deixis/workflow/criterion.py:44-87`) ifadeleri oylar, ölçüt cümlesini ve
  parçaları tek bir koşudan alır: en çok tutulan ifadeyi paylaşan koşu, eşitlikte ilk soru (`:59-61`). Bir öneride 2–5
  parça, parça başına 6–15 ifade (`:23-24`). Nereden geldiğinin kaydı `criterion_origin`'e yazılır
  (`workflow/protocol.py:27`, `:147`); aynı soru için dondurulmuş ölçüt geri okunur (`workflow/store.py:596-622`); onay
  kartında düzeltilen ölçüt bu kaydı taşır (`workflow/approval.py:262-287`). Adım `flow._criterion`'dır
  (`workflow/flow.py:837-881`): üç isteğe bağlı çağrı, geçersiz öneri bütünüyle düşer (`:870-874`).
- **Sözleşme denetimi.** `_check_criterion_proposal(draft, report)` parça sayısını, ifade sayısını ve boyunu, yinelenen
  adları denetler (`backend/deixis/domain/contracts.py:898-926`); adım girdisini almaz (`:495-496`), bu yüzden soruyla
  karşılaştırma yapamaz. Sürüm `deixis.criterion_proposal.v1` (`:60`, şema `:18`).
- **Tam metin okuması parçaları tek tek sorar ve karar kodda.** `adjudication.verdict` (`workflow/adjudication.py:264-275`):
  bütün parçalar `present` → `include`; en az biri `present` → `partial`; hiçbiri `present` değil ve biri `absent` →
  `not_met`. `combine` (`:288-305`) iki koşu `partial`'da anlaşırsa `part_without_evidence` yazar: `unresolved`, insan
  kuyruğu. Yani yeni bir popülasyon ya da karşılaştırıcı parçası `absent` iken öbür parçalar `present` ise iş
  `criterion_not_met` olmaz, kuyruğa gider. Bu dilim D85'in bu kuralını değiştirmez (karar 2.6).
- **Özet aşaması ölçütü okumaz.** Yalnız soruyu okur (`methods/deixis-research/references/abstract-screening.md:7-20`);
  bu dilim özet aşamasına dokunmaz.
- **SW22'nin 422'si API'dedir.** `start_run`, `answer` ve `pdf_collection` için dahil edilmiş iş yoksa 422 "Include at
  least one source before generating an answer" döner (`backend/deixis/api/app.py:956-957`); bu `legacy`'de de böyledir.
  Bir araştırmada etkin koşu (`queued`, `running`, `pause_requested`) varken yeni koşu açılmaz
  (`workflow/store.py:23`, `:634-639`).
- **Ürün "yanıt yok" durumunu zaten biliyor.** `answers.status` dört değer alır, biri `no_evidence`
  (`storage/migrations/0001_initial.sql:265`). `_answer` (`workflow/flow.py:2457-2481`) `sw`'de önce başlangıç
  fotoğrafını yazar (`_answer_start_snapshot`, `:2505-2523`: akış sayıları, dahil edilen sayısı), sonra pasaj yoksa
  `no_evidence` ve bir not saklar (`:2477-2481`). Görünüm `validation`'ı olduğu gibi verir (`workflow/views.py:391-404`).
  Arayüzde `no_evidence` bir uyarı ve altında başlangıç fotoğrafının sayı satırıdır (`apps/web/src/ResearchView.tsx:631-633`,
  `apps/web/src/FlowReport.tsx:59-78`); bildirim `ResearchView.tsx:211`. Yanıt düğmesi dahil edilen yoksa kapalıdır
  (`ResearchView.tsx:491`).
- **Tam metin bulma yalnız PDF tanır.** `acquisition.acquire_for_source` (`backend/deixis/documents/acquisition.py:253-321`)
  DOI'yi sırayla Unpaywall, OpenAlex, Crossref ve CORE'a sorar (`:269-277`), her aday satırını kaydeder, sonra yalnız
  `doi_verified` + sürümü `match` olan adayları sırayla getirir (`:281-296`); başka sürüm yalnız `other_versions` ile
  kendi satırına (`:298-300`, `:327-355`, D4); belirsiz sürüm kişiyi bekler. Getirme `fetch.fetch_pdf`'tir: `%PDF`
  olmayan cevap `not_pdf` (`documents/fetch.py:108`). Ekleme `_attach_pdf` → `pdf.extract_pdf` → `add_asset_with_pages`
  (`acquisition.py:358-367`), varlık `media_type` sabit `'application/pdf'` (`workflow/store.py:1368-1371`); PDF
  görüntüleyici `application/pdf` sunar (`api/app.py:1534`); tam metin okuması alıntıyı sayfa numarasıyla doğrular
  (`workflow/adjudication.py:245`). `physical_page` ya da `pdf_page` 14 dosyada ~70 kez geçer (grep). Sağlayıcı adı iki
  tabloda CHECK'tir (`pdf_discovery_runs`, `pdf_candidates`: `unpaywall`, `openalex`, `crossref`, `core`, `web_search`;
  son hâli `0018_core_pdf_provider.sql` + `0025`). Getirme bir iş için en çok 3 kez başlar (`workflow/fulltext.py:183`);
  her istek konak başına tek (`fetch.host_gate`, `fetch.py:52`). `sw` getirmesi bu fonksiyonu `flow._find_other_copy`
  üzerinden çağırır (`workflow/flow.py:2790-2815`). Europe PMC kodda hiç yok.
- **Sahte model ve fikstürler.** `tests/fakes.py:75-90` iki parçalı sentetik bir v1 önerisi döndürür (kabul sunucusu da
  bunu kullanır, `tests/acceptance/fixture_server.py:53`); `tests/fixtures/research/step-inputs.json:1642-1656`
  (`E_criterion_proposal`), `tests/fixtures/research/fake-outputs.json:764-960` (beş ölçüt vakası); v1'i sınayan testler
  `tests/test_criterion_proposal.py:44`, `:110`, `tests/test_criterion_flow.py:56`.

## Elimizdeki sayılar

Hepsi dilim 24a'nın saklı verisinden, bir M1 Pro'da `gpt-5.6-luna` · medium ile koşmuş araştırmalardan; hücre başına bir
koşu (`standard` iki). Dağılım değil, gözlenen değer.

1. **Tıp ölçütleri** (`criteria.txt`; 5 araştırma × 3 öneri = 15 öneri). Popülasyonu kendi parçası yapan öneri **0/15**.
   Karşılaştırıcıyı kendi parçası yapan 1/15 (`emb` r3, "eligible comparator"); bir öneri onu sonuçla kaynaştırmış (`quick`
   r3, "eligible comparison and body-weight measurement"). Beş uzlaşmanın beşi de aynı üç parça: TRE müdahalesi, randomize
   tasarım, vücut ağırlığı sonucu. Popülasyon ölçüt cümlesinde 4/5 (r1'de yok) ama hiçbir parçada değil; sorunun
   karşılaştırıcı sözcükleri tasarım parçasının tanımında 2/5 (`standard` r2, `emb`), öbür üçünde yalnız "eligible
   comparison group" ya da "comparator groups". Müdahale ve sonuç parçası uzlaşmada 5/5; sonuç parçası 15 önerinin 3'ünde
   eksik ama hiçbir temel koşuda eksik değil.
2. **Kuantum ölçütleri** (aynı dosya; 15 öneri). 2–4 parça; hiçbirinde popülasyon ya da karşılaştırıcı parçası yok; aranan
   şey 5/5 uzlaşmada (`sought_term_in_criterion`). Soru bir popülasyon ya da "compared with" adlandırmıyor.
3. **Hangi `include` düşerdi** (`includes-tre.json`, `flips-tre.json`). Beş tıp `sw` araştırmasında 30 `include` satırı,
   **17 tekil iş** (`standard` r1 7, r2 4, `quick` 3, `detailed` 16, `emb` 0). Her birini bu plan oturumu saklı özetten ve
   tasarım parçasının saklı alıntısından okudu (bir model okuması, kör değil, insan doğrulaması değil; PDF sayfası
   açılmadı). 17'nin **10'u** bir popülasyon ya da karşılaştırıcı parçasını karşılamazdı: popülasyon 3 (obez olmayan
   sağlıklı gönüllüler, ergenler, normal kilolu aktif yetişkinler), karşılaştırıcı 8 (12:12 TRE, bireysel diyetisyen
   rehberliği, egzersiz programı, kalori kısıtlamalı Akdeniz diyeti, kalori kısıtlaması ve direnç egzersizi, düşük
   karbonhidratlı diyet, hacimsel diyet, etkin diyet danışmanlığı kolu); biri ikisini birden karşılamıyor. Bu 10'un 2'si
   tartışmalı (diyetisyen rehberliği ve danışmanlık kolu). Popülasyonu belirsiz 2 (metabolik sendrom bileşeni ile seçilmiş
   yetişkinler; normal BMI'lı "gizli obezite"). Geçen 5. Kapı 4'ün örneklendiği iki `standard` koşusunun birleşimi 8 tekil
   iş: 3'ü düşer (24a'nın analist okumasının "ciddi" dediği aynı üçü), 1'i belirsiz, 4'ü geçer. Ayrıca 17'nin 3'ü sonuç
   bildirmeyen deneme protokolü; ikisi karşılaştırıcıdan zaten düşer, biri (PKOS protokolü) popülasyon ve karşılaştırıcıyı
   geçer: bu bir sonuç parçası hatasıdır, bu dilimin konusu değil ("Bu dilimde yok").
4. **Bugünkü tam metin kodları** (`baseline.json`, sürüm düzeyinde). Tıp: `part_without_evidence` 8–28, `criterion_absent`
   1–8, `fulltext_runs_disagree` 3–8; kuantum: `part_without_evidence` 8–75. Popülasyon ve karşılaştırıcı parçası eklenince
   madde 3'ün düşen işleri büyük olasılıkla `include`'dan `part_without_evidence`'a geçer (öbür parçalar `present`
   kaldığı için, `adjudication.py:264-275`): tıpta kuyruk büyür, `include` küçülür.
5. **SW22 vakası** (`qtre-sw-standard-emb-r1`). 24 sürüm tam metinden okundu: 0 `include`, `criterion_absent` 5,
   `fulltext_runs_disagree` 5, `part_without_evidence` 14, `no_fulltext` 28; `answers` tablosu boş.
6. **Kapılar için öngörü (SW21 eklenmeden önceki hâli; SW21 ile güncellemesi karar 7.7'de).** Tıpta dilim 24a'nın beş `sw` koşusunda 4 referans denemenin 0'ı ve Elicit'in "kapsamda" 3
   eserinin 0'ı PDF'e ulaştı (SW21). İki `legacy` koşusu da Elicit'in Lin 2023'üne (`10.7326/m23-0052`, TRE'yi kısıtsız
   kontrol koluyla kıyaslayan yetişkin obez RCT) özetten atıf verdi. Genişletilmiş R Lin 2023'ü içerirse Kapı 2'nin atıf
   kuralı iki `sw` `standard` koşusunun ikisinde de en az bir R atfı ister; 24a'da bu hiç olmadı. Kapı 4'ün alt sınırı iki
   `standard` koşusunun birleşiminde 8 tekil `include`'dur; madde 3'e göre bugünkü 8'in 4–5'i kalır. Bu dilim PDF
   erişimini değiştirmez. Öngörü: yeniden ölçümde tıpta Kapı 2 ve Kapı 4 büyük olasılıkla geçmez (dondurulmuş beklenti,
   karar 7.7).
8. **Europe PMC'nin kazancı (SW21; `epmc-gain.json`, `xml-check.json`, `oa-pdf-check.json`; 26 Eylül 2026'da bu
   makineden).** Örnek: `qtre-sw-standard-r1`'in planladığı 112 işin PDF'i bulunamayan **83**'ü (bir koşu), ayrıca 24a'nın
   4 referans denemesi ve Elicit'in 5 eseri. DOI başına bir Europe PMC araması: 83'ün 68'i DOI ile bulundu, 43'ünün PMCID'i
   var, 32'si açık erişim alt kümesinde. REST `fullTextXML` açık erişimli 33 tekil PMCID'in **33'ünde** gövdeli XML
   döndürdü, açık erişimli olmayan 11'in 0'ında (HTTP 500). Açık erişimli 32'nin 2'si yazar el yazması (`authMan = Y`:
   PMC9691536, PMC9877119) ve ürünün aday kuralı onları almaz (karar 3a.2). Yani bu koşuda PDF'i olmayan planlı işlerin
   tam metin kazanabileceği üst sınır **30 / 83** (%36; `sample_epmc.py` → `epmc-sample.json`); 24a'nın NCBI PMC bağlantısı olan 12 işinin (hepsi `not_pdf` ya da denenmedi: NCBI HTML bir
   doğrulama sayfası döndürüyor) 9'u da bunların içinde. Referans denemeler **2 / 4** (Kotarsky 2021, Feehan 2023;
   Haganes ve Floyd'un PMCID'i yok). Elicit **1 / 5** (Wilkinson 2026, TREAD); Lin 2023 ve Cienfuegos 2020 Europe PMC'de
   yazar el yazması (`authMan = Y`), açık erişim alt kümesinde değil, `fullTextXML` 500. **PDF yolu bu makineden çalışmıyor:**
   Europe PMC'nin PDF adresi (`europepmc.org/articles/<PMCID>?pdf=render`) 8 / 8 istekte 403 ve bir Cloudflare "Just a
   moment…" sayfası; PMC'nin OA hizmeti (`oa.fcgi`) 33 / 33 istekte 404; NCBI makale PDF'leri 24a'da 24 aday satırında
   `not_pdf`. Kazanç tek koşuda sayıldı; hangilerinin okunup `include` olacağı ölçülmedi.
9. **Yeniden ölçümün maliyeti** (24a'nın tıp satırları). 7 araştırma: 453 model çağrısı, ~5,25 M giriş jetonu, koşular
   ve araları ~1 sa 53 dk; referans kümesi, ölçüm ve analist okuması ayrıca bir oturum. Luna aboneliği; para yok.

Sayıların gösteremediği: yeni istemle modelin popülasyon ve karşılaştırıcıyı gerçekten yazıp yazmadığı (canlı çağrı bu
planda yok; kabuldeki kuru koşu ölçer, karar 5); tam metin okumasının yeni parçaları nasıl etiketlediği; genişletilmiş
R'nin boyu (tablolar açılmadı).

## SW maddeleri

- **SW23** (ürün, 25a): kapanır (D106), kabulde kuru koşu ve 25b'de canlı ölçümle.
- **SW22** (ürün, 25a): kapanır (D106).
- **SW21** (ürün, 25a; sahibin seçimi G2): Europe PMC açık erişim tam metni, yalnız tam metin bulma kaynağı olarak kapanır
  (D106). Europe PMC'nin arama kolu SW21'in parçası değildir ve kurulmaz.
- **SW18** (ölçüm, 25b): genişletilmiş kural dondurulunca kapanır (karar 8).
- Kapsam dışı, sırayla bekleyen: SW19, SW20 (24b'nin görev 11'i), SW24, SW25, dilim 23, D96
  (b)–(c), SW6.6; ayrıca madde 3'ün protokol bulgusu (yeni SW26, yalnız kayıt).

## Kararlar

1. **Üç aşama.** **25a** kodu yazar (SW23, SW22); Sol incelemesinden sonra koordinatör tek commit'ler, satır 25
   `kapandı` olur. **25b** yalnız 25a kapandıktan sonra yeniden ölçer (karar 7). **24b** yalnız 25b dört kapıyı geçirirse ve
   satır 17 `kapandı` ise koşar (karar 10). Üçü bir prompt'un üç bölümüdür; hangisinin koşacağını satır 25 ve 24 söyler.

2. **SW23, ölçütte popülasyon ve karşılaştırıcı (A1, B1).**
   1. **Yöntem dosyası** (`criterion-proposal.md`). Kural 4'ün setting tanımından "population" çıkar: setting "the system,
      domain, material or environment" olur ve kural sona "The people, patients or animals a study must be done in are
      not setting: see rule 8." cümlesini alır. Kural 6 daralır: "The aspects the question asks to compare across the
      papers (their variables, methods or results) are not parts; a comparator the question names for the thing sought
      is (rule 8)." Yeni kural 8 (eski 8, yankı kuralı, 9 olur): "When the question names the **population** a study must
      be done in (people, patients or animals with a stated characteristic) or the **comparator** the thing sought must
      be compared with (no intervention, usual care, a placebo or another named alternative), give each its own part.
      Its `definition` says what the paper must state about its own participants or its own comparison group, so that a
      study done in other participants, or compared with something else, does not meet it. List each such part in
      `question_elements`: its `role` (`population` or `comparator`), the question's own `words` that name it, copied
      exactly, and the `part` name. Give an empty list when the question names neither." Zor durumlara iki madde: "A
      system, network, material or device the question is about is setting, not a population, even when the question
      says 'in'." ve "A comparator named as no treatment, usual care or an unrestricted alternative is not met by a
      comparison group that receives something the question's comparator does not name, such as another active treatment
      or another variant of the same one." Kural 5 (aranan şeyin kendi parçası) olduğu gibi kalır. İfade ve kural sayısı
      sınırları değişmez. Metnin son hâli uygulayanındır; bu anlam ve bu ayrımlar korunur, alan adı (TRE, kuantum) geçmez.
   2. **Sözleşme `deixis.criterion_proposal.v2`.** Şemaya zorunlu `question_elements`: 0–2 öğe, her biri
      `{role: "population" | "comparator", words: 1–300 karakter, part: 1–60 karakter}`, `additionalProperties: false`.
      `parts` açıklaması: "The setting (system, domain, material, environment) is not a part: the search blocks hold it. A
      population of participants and a comparator the question names are parts, listed in `question_elements`." Parça
      sınırı 2–5 kalır (P, I, C, O ve tasarım beşe sığar). `SCHEMA_VERSIONS` v2.
   3. **Kodda denetim** (hepsi hata; onarım yolu bir, sonra öneri düşer, `flow.py:870-874`). `_check_criterion_proposal`
      adım girdisini de alır. `question_element_unknown_part`: `part` (normalleştirilmiş) önerinin bir parça adı değil.
      `question_element_not_in_question`: `words` normalleştirilmiş hâliyle sorunun metninde ya da bir `user_steering`
      girdisinde sözcük sınırında geçmiyor. `duplicate_question_element`: bir rol iki kez. `question_elements_share_part`:
      popülasyon ve karşılaştırıcı aynı parçayı gösteriyor. Normalleştirme ölçütün kendi `norm`'udur
      (`criterion.py:31-36`).
   4. **Uzlaşma.** `required_roles` = geçerli koşuların en az `PROPOSAL_MAJORITY`'sinin (2) `question_elements`'ında
      geçen roller. Temel koşu yalnız bu rollerin hepsini taşıyan koşular arasından, bugünkü kuralla (en çok tutulan
      ifade, eşitlikte ilk koşu) seçilir. Böyle bir koşu her zaman vardır: üç koşuda iki rolün her biri en az iki koşudaysa
      en az bir koşu ikisini birden taşır (2 + 2 − 3 = 1), iki koşuda ikisi de her ikisindedir; kod bunu `assert` eder.
      Çıktıya iki alan: `question_elements` (temel koşununki, role göre sıralı) ve `required_roles` (sıralı). **Değişmezlik:**
      hiçbir rol çoğunluğa ulaşmazsa temel koşu, ölçüt, parçalar, ifadeler ve dışlama sözcükleri bugünkü fonksiyonun
      verdiğiyle bayt bayt aynıdır; yalnız iki yeni alan (`[]`) eklenir. Bir v1 çıktısı (alan yok) `[]` okunur.
   5. **Kayıt.** `CRITERION_ORIGIN_FIELDS`'e (`protocol.py:27`) `question_elements` ve `required_roles` eklenir; ikisi de
      `decisions.CRITERION_FIELDS`'in dışında kalır, yani aynı ölçüt geri okununca karar eskimez (D78 madde 5).
      `store.frozen_criterion` (`store.py:612-621`) ikisini `origin`'den `[]` varsayımıyla döndürür;
      `approval.apply_criterion` (`approval.py:282-287`) ikisini önerinin kaydı olarak taşır, kişinin düzeltmesine göre
      yeniden denetlemez (kişi parçayı silebilir; kişinin sözü geçer).
   6. **Tam metin okuması değişmez.** Yöntem dosyası, şema ve `verdict` / `combine` olduğu gibi. Popülasyon ya da
      karşılaştırıcı `absent` iken öbürleri `present` olan iş kuyruğa (`part_without_evidence`) gider, otomatik
      `criterion_not_met` olmaz. Neden: D85'in "yalnız kod dışlar" dengesini bu dilim açmaz; iş yanlışlıkla `include`
      olmaz, kişi kuyrukta görür. Bedel: tıpta kuyruk büyür (sayı 4).
   7. **`skill_package_hash` değişir** (yöntem dosyası). Bu dilimden önce dondurulmuş ölçütler olduğu gibi kalır (D78
      madde 6); saklı v1 adım çıktıları sürdürülen bir koşuda `[]` ile okunur.
   8. **Roller yalnız popülasyon ve karşılaştırıcı (B1).** Müdahale kural 5 ile zaten kendi parçasıdır; sonuç parçası
      tıp uzlaşmalarının 5/5'inde vardı (sayı 1). İkisini rol yapmak kuantumda temel koşuyu değiştirebilirdi (regresyon
      riski), ölçülmüş bir kazancı yok.

3. **SW22, `include`'suz `sw` araştırmasının yanıtı (C1).**
   1. **API.** `start_run`'da (`app.py:956-957`) `pdf_collection` ve `legacy` araştırması için 422 aynen kalır. `sw`
      araştırmasında `answer`, dahil edilen iş olmasa da güncel kapsam revizyonunda `completed` bir `discovery` koşusu varsa
      kabul edilir; yoksa aynı 422. Etkin koşu kuralı (`store.py:634-639`) değişmez: okuma sürerken yanıt açılmaz.
   2. **Akış.** `_answer`'da `sw` için başlangıç fotoğrafı yazıldıktan hemen sonra, `_inspect`'ten önce: dahil edilen iş
      yoksa `save_answer(..., "no_evidence", None, {"ok": true, "issues": [], "reason": "no_includable_source", "note":
      "No work was included at full text when this answer started; no model was asked."})` ve dönüş. Model çağrısı,
      `answer_review` ve rapor sürümü yok (rapor sürümü yalnız `structurally_valid`'e verilir, `store.py:2599-2601`).
      Sayılar yanıtın kendisindedir: başlangıç fotoğrafının akış sayıları (dahil 0, kuyrukta, PDF bekleyen, okunmamış,
      ölçüt karşılanmadı) ve dahil edilen 0.
   3. **Arayüz.** `api.ts`'de `validation.reason?: 'no_includable_source'`. `ResearchView`: `sw` araştırmasında güncel
      revizyonun tamamlanmış bir keşfi varsa yanıt düğmesi dahil edilen olmadan da açık (etkin koşu yokken); `no_evidence`
      bloğu `reason` bu ise ayrı bir uyarı gösterir: "No work was included at full text when this answer
      started, so no answer was written and no model was asked. The line below says where the works stand." ve altında
      `AnswerFlowNote`; bildirim "No answer: no work was included at full text when this answer started."; iki metnin Türkçesi
      `i18n.ts`'e. Yeni bileşen, yeni bağımlılık yok (`.impeccable.md`).
   4. **Migration yok.** `no_evidence` zaten izinli (`0001_initial.sql:265`); ayrım `validation_json`'dadır. Ayrı bir
      durum (C2) `answers` tablosunu yeniden kurmayı gerektirirdi.
   5. **Sınır.** Kişi okuma koşusu duraklatılmışken yanıt isterse yanıt "başladığı anda" dahil edilen olmadığını söyler;
      okunmamış iş sayısı satırda görünür. Bu bir "kaynak yok" hükmü değil, o andaki durumun kaydıdır.

3a. **SW21, Europe PMC açık erişim tam metni (G2 sahibin seçimi; yol H1).**
   1. **Yol: REST `fullTextXML`, yerelde PDF'e çizilerek.** PDF yolu ölçüldü ve bu makineden çalışmıyor (sayı 8: Europe PMC
      PDF'i 8 / 8 Cloudflare 403, `oa.fcgi` 33 / 33 404, NCBI PDF'leri `not_pdf`); `fullTextXML` açık erişimli 33 / 33'te
      döndü. XML'i `section` pasajı olarak saklamak `physical_page` ve `pdf_page` üzerine kurulu ~70 yeri (sayı değil
      grep; `adjudication.py:245`, `app.py:1534`, `store.py:1368-1371`, OCR, Marker, denklem okuma) değiştirirdi. Bunun
      yerine XML sade bir HTML'e, oradan PyMuPDF `Story` ile bir PDF'e çizilir (kurulu PyMuPDF 1.28.2'de var) ve
      `_attach_pdf` (`acquisition.py:358-367`) ile, var olan çıkarma ve parçalamadan geçerek eklenir. Sonraki her aşama
      (okuma, doğrulama, yanıt, görüntüleyici) değişmez.
   2. **Arama.** `acquisition.europepmc_lookup(client, doi, source_version)`: Europe PMC REST
      `search?query=DOI:"<doi>"&resultType=core&format=json` isteği, `fetch.host_gate` içinde, `core_lookup`'ın durum
      eşlemesiyle (404, 429, 401 / 403, başka, ayrıştırma hatası). Aday yalnız sonuç DOI'si kaydın DOI'sine eşitse
      (`doi_verified`), PMCID varsa, `isOpenAccess = Y`, `inEPMC = Y` ve `authMan = N` ise: adres
      `https://www.ebi.ac.uk/europepmc/webservices/rest/<PMCID>/fullTextXML`, açılış sayfası
      `https://europepmc.org/article/PMC/<PMCID>`, sürüm `publishedVersion` (açık erişim alt kümesinde yayıncının bıraktığı
      kopya), lisans sonuçtan, sürüm durumu `_version_status` ile (D4 / D22 / D35 kuralları olduğu gibi: yalnız `match`
      kaydın kendisine, `different` yalnız `other_versions` ile kendi satırına, `uncertain` hiç). Yazar el yazması
      (`authMan = Y`) aday olmaz: `fullTextXML` onları vermiyor (sayı 8) ve `acceptedVersion`'ın kimliği ayrı bir iştir.
      PMID ile arama yok: 83 işin 83'ünde DOI vardı ve `acquire_for_source` DOI'siz kaydı zaten reddeder (`:265-266`).
   3. **Sıra.** Europe PMC, var olan dört aramadan ve onların doğrulanmış adaylarının getirilmesinden **sonra**, yalnız
      kaydın hâlâ varlığı yoksa sorulur (bir istek); adayı kaydedilir ve aynı döngü kuralıyla denenir. Böylece "başka açık
      PDF yoksa" kuralı koddadır ve Europe PMC'ye yalnız PDF'siz işler için gidilir. `other_versions` yolu Europe PMC
      adayını da görür (`different` ise).
   4. **Getirme.** Europe PMC adayı `fetch.fetch_file(url, ("application/xml", "text/xml"))` ile gelir (`fetch.py:154`:
      yalnız açık adresler, sabitlenen adres, en çok 5 yönlendirme, `MAX_BYTES`, User-Agent, `host_gate`); sonuç
      `store.record_pdf_attempt` ile kaydedilir. `fetch_file` beklenmeyen içerik türünde `wrong_type` döndürür
      (`fetch.py:192`) ve `record_pdf_attempt` durumu olduğu gibi yazar (`store.py:1676`); bugünkü CHECK bunu kabul etmez
      (`0018_core_pdf_provider.sql:28`), yani bir HTML cevabı kısıt hatası atardı. Bu yüzden migration `0055`
      `pdf_candidates.access_status`'a `wrong_type`'ı ekler (madde 7). Çizim tarafının iki reddi var olan `failed`
      durumuyla ve ayrı hata koduyla yazılır: `jats_entity_refused`, `jats_render_failed`. Üçünün her biri bir testle
      sınanır: aday kaydı yazılır, istisna yok, varlık yok, sıradaki adaya geçilir. İş başına 3 deneme kuralı
      (`fulltext.py:183`) ve konak kuralı değişmez.
      Enjekte edilebilir: `acquire_for_source`'a `xml_fetcher` (varsayılan `fetch.fetch_file`), `FlowDeps`'e aynısı;
      testler ağsız sahte verir.
   5. **Çizim** (`documents/jats.py`, yeni): `render_pdf(xml: bytes, *, timeout, max_memory, max_pages, max_output) ->
      Rendition`. `<!ENTITY` içeren belge reddedilir, ayrıştırma standart kütüphanenin `xml.etree`'si (dış varlık
      yüklenmez). Sırayla makale başlığı, özet, gövdenin bölüm başlıkları ve paragrafları, tablo başlığı ve hücre metni,
      şekil başlıkları; kaynakça, ekler ve MathML'in işaretlemesi yok (MathML'in düz metni kalır). Her metin HTML'e
      kaçırılarak girer.
      **Kaynak sınırı** (Sol r2 bulgu 2). Getirme 30 MiB'e kadar XML kabul eder (`fetch.py:25`), çıkarıcının sınırları
      ise ancak çizimden sonra işler (`pdf.py:48-52`, çocuk süreç `pdf.py:273-300`). Bu yüzden çizim de sınırlı bir çocuk
      süreçte, `extract_pdf`'in kalıbıyla koşar:
      - *Girdi sınırı, ayrıştırmadan önce, üst süreçte:* `MAX_XML_BYTES = 5 MiB`. Ölçülen 35 `fullTextXML` cevabı
        30–283 KB (`xml-check.json`), sınır en büyüğün ~18 katı. Aşarsa `jats_too_large`.
      - *Çocuk süreç:* `python -m deixis.documents.jats <girdi.xml> <çıktı.pdf> <max_memory> <max_pages> <max_output>`,
        girdi ve çıktı geçici dosyada, ortam `extract_pdf`'inki gibi yalnız `PYTHONPATH`. Ayrıştırma, `<!ENTITY`
        denetimi dışındaki her iş ve çizim çocukta olur. Üst süreç onu `asyncio.to_thread` ile çağırır (çıkarıcının
        `acquisition.py:365`'teki çağrısı gibi), olay döngüsü beklemez.
      - *Süre:* `RENDER_TIMEOUT_SECONDS = 60`, `subprocess.run(timeout=...)`; aşarsa çocuk öldürülür, `jats_render_timeout`.
      - *Bellek:* `MAX_MEMORY_BYTES` 1 GiB, çocuk `pdf._watch_memory`'yi kullanır (`pdf.py:256-270`, aynı bekçi, aynı
        `MEMORY_EXIT_CODE = 3`; `MemoryError` da 3 ile çıkar). Çıkış 3 → `jats_render_memory`. Windows'ta bellek sınırı
        yok, `extract_pdf` gibi (DEIXIS zaten POSIX'te ölçülür).
      - *Sayfa:* `MAX_RENDER_PAGES = 200`; çocuk `Story`'yi sayfa sayfa yerleştirir ve 201. sayfaya geçmeden çıkış 4 ile
        durur → `jats_render_pages`. Çıkarıcının 400 sayfalık sınırının altında, böylece çizilen belge hiç kesilmez.
      - *Çıktı boyu:* `MAX_RENDER_BYTES = 30 MiB` (`fetch.MAX_BYTES` ile aynı, yani indirilen bir PDF'ten büyük olamaz);
        çocuk yazdıktan sonra boyu denetler, aşarsa çıkış 5; üst süreç dosya boyunu yeniden denetler. İkisi de
        `jats_render_output_too_large`.
      - *Diğer:* sıfırdan farklı başka bir çıkış, boş ya da `%PDF-` ile başlamayan çıktı → `jats_render_failed`.
      Her durumda aday `failed` durumu ve bu hata koduyla kaydedilir, istisna yok, varlık yok, geçici dosyalar silinir ve
      sıradaki adaya geçilir. Başarılı çıktı `_attach_pdf`'e gider ve oradan bugünkü sınırlı çıkarıcıdan geçer. Sınır
      değerleri girdi boyu dışında ölçülmedi (çizim süresi, belleği ve sayfa sayısı 25a'nın canlı denemesinde yedi eser
      için yazılır, karar 5.4).
   6. **Kanıt sınırı ve görünüm.** Çizilen PDF'in sayfaları yayıncının sayfaları değildir.
      - **Kayıt.** `_attach_pdf` (`acquisition.py:358-367`) bir `filename` alır ve `add_asset_with_pages`'e geçirir
        (bugün `None`); Europe PMC varlığı `origin = 'download'`, `retrieved_from` = `fullTextXML` adresi,
        `original_filename = <PMCID>.europepmc.pdf` ile saklanır. Tanıma tek yerde: `jats.RENDITION_SQL` (üçü birden:
        `origin`, `retrieved_from` kalıbı, dosya adı), kişinin yüklediği `x.europepmc.pdf` onu tetiklemez.
      - **Taşıma.** Her pasajın `rendition`'ı kendi varlığından (`passages.asset_id`) okunur, varlık kaldırılmış ya da
        değiştirilmiş olsa da (eski atıflar). Görünüm modelinin sayfa taşıyan her yeri alanı taşır: yanıt kanıtı
        (`views.py:365-375`'in sorgusu zaten `source_assets a`'yı birleştiriyor), pasaj ve PDF metin belgesi, kuyruk
        satırının ayrıntısı (alıntı, en yakın metin, ipucu cümleleri), denetim örneği ve PDF bekleyen listedeki alıntılar.
      - **Tek biçimleyici.** `apps/web/src/labels.ts`'deki `locatorText` (`:203-205`) sayfa ve `rendition` alan tek
        biçimleyici olur (`pageLocator`): `PDF p. {page}` ya da `Europe PMC text, rendered p. {page}`, basılı etiketle
        birlikte olanı da. Sayfa yazan her yüzey onu kullanır, cümle içinde sayfa geçen iletiler `{page}` yerine
        `{locator}` alır: yanıtın atıf etiketi ve Markdown dışa aktarımı (`ResearchView.tsx:641-644`), PDF metin belgesi
        (`PdfTextDocument.tsx:134-144`), kuyruk (`HumanQueue.tsx:56-64`, `:456`, `:464`, `:479`), denetim örneği
        (`AuditSample.tsx:95`), PDF bekleyen liste (`WaitingForPdf.tsx:225`), pasaj yaprağı ve PDF görüntüleyicinin
        başlığı. Türkçesi `i18n.ts`'te. Arka uç sayfa metni yazmaz (grep: `backend/deixis`'te "p." biçimleyicisi yok).
      - **Test.** Her yüzey için bir sınama: `rendition` taşıyan bir sentetik pasajla "rendered p." ve taşımayanla "PDF
        p."; yanıtın Markdown dışa aktarımı dahil; kaldırılmış bir Europe PMC varlığına atıf yapan eski yanıt da
        "rendered" der. Model girdisi değişmez (model sayfa yazmaz). OCR ve Marker bu varlıkta tetiklenmez: metin katmanı tamdır; tetiklenirse (boş sayfa)
      bu bir hatadır ve test onu dışarıda tutar.
   7. **Migration `0055_europepmc_pdf_provider.sql`.** `pdf_discovery_runs` ve `pdf_candidates`, `0018`'in yöntemiyle
      bugünkü sütunlarıyla (`0025`'in `other_title_count`'u dahil) yeniden kurulur; iki fark: iki tablonun sağlayıcı
      CHECK'ine `europepmc`, `pdf_candidates.access_status` CHECK'ine `wrong_type` (madde 4). Veri olduğu gibi kopyalanır, dizinler yeniden kurulur, `tests/test_migrations.py` ile sınanır.
   8. **Oran.** Europe PMC'nin yayımlanmış bir istek sınırı bulunmadı; ürünün kuralı geçerli: konak başına tek istek
      (`host_gate`), 429 → `rate_limited` kaydı ve o iş için geçiş, yeniden deneme yok.

4. **Testler.** Hepsi sentetik ve alandan bağımsız (CLAUDE.md "Tests").
   - Sözleşme: v2 sabiti; şemada `question_elements` zorunlu; dört yeni hata kodunun her biri için bir
     `fake-outputs.json` vakası ve geçerli bir v2 vakası (`E_criterion_proposal`'ın `output_schema_versions`'ı v2); yöntem
     metni testi: setting tanımında "population" yok, kural 8 var, alan adı yok.
   - `consensus`: (i) hiçbir rol çoğunlukta değil → bugünkü çıktıyla bayt bayt aynı (bugünkü fonksiyonun çıktısı testte
     sabit beklenen değer olarak yazılır); (ii) popülasyon 2/3 koşuda, ifade sırasıyla seçilecek koşuda yok → temel koşu
     onu taşıyan koşu; (iii) iki rol farklı koşu çiftlerinde → temel koşu ikisini taşıyan; (iv) koşuların ve öğelerin
     sırası sonucu değiştirmez; (v) v1 çıktısı `[]` okunur.
   - Akış: v2 zarfı; protokol gövdesinin `criterion_origin`'inde iki alan; dondurulmuş ölçütün geri okunması ikisini
     taşır; onay kartında düzeltilen ölçüt ikisini taşır.
   - SW22: tamamlanmış keşfi olan, `include`'suz `sw` araştırması → `POST runs {kind: answer}` 202 → yanıt `no_evidence`,
     `validation.reason = no_includable_source`, `start_snapshot.included = 0`, `grounded_answer` görevli model çağrısı yok;
     keşfi tamamlanmamış `sw` → 422; `legacy` → 422 (`tests/test_corpus_removal.py:131` aynen geçer); `pdf_collection` →
     422.
   - Playwright: bir vaka, `include`'suz bir `sw` araştırmasında düğme açık, yanıt açık uyarı ve akış satırı, 1440 ve 390
     px'te yatay kaydırma yok. Kabul sunucusunda böyle bir araştırma kuran soru işareti yoksa en küçük sentetik senaryo
     eklenir (sentetik diye işaretli).
   - `tests/fakes.py:75-90`: v2 zarfı ve `"question_elements": []` (sentetik, alandan bağımsız).
   - SW21 (sahte `httpx` taşıyıcısı ve sahte `xml_fetcher`, ağ yok, sentetik JATS): `europepmc_lookup`'ın durum eşlemesi
     ve aday kuralları (DOI eşit değil → aday yok; `isOpenAccess = N` ya da `authMan = Y` → aday yok; sürüm durumu);
     Europe PMC'ye yalnız dört kaynaktan sonra ve varlık yokken gidilmesi (varlık varsa istek yok); başarılı XML → çizilen
     PDF → sayfalı pasajlar, `retrieved_from` ve dosya adı; HTML cevabı → `wrong_type` kaydı; `<!ENTITY` →
     `failed` + `jats_entity_refused`; çizim hatası → `failed` + `jats_render_failed`; üçünde istisna yok, varlık yok;
     kaynak sınırlarının her biri için bir test (madde 3a.5), sınır parametreyle küçültülerek: 5 MiB'i aşan girdi
     çocuk başlamadan `jats_too_large`; `timeout=0.001` ile `jats_render_timeout`; `max_memory` 100 MiB ve belleği
     şişiren sentetik bir belgeyle `jats_render_memory` (30 s içinde, `test_documents.py:112-119` gibi); `max_pages=2`
     ve uzun bir gövdeyle `jats_render_pages`; `max_output` küçük tutularak `jats_render_output_too_large`; bozuk XML
     ile `jats_render_failed`; her birinde aday kaydı yazılır, varlık yok, geçici dosya kalmaz, sıradaki aday denenir; `different` sürüm yalnız `other_versions` ile kendi satırına; migration `0055` eski satırları
     korur, `europepmc`'yi ve `wrong_type`'ı kabul eder; `rendition`'ın her görünüm alanında taşınması ve karar 3a.6'nın her
     arayüz yüzeyi için bir sınama.

5. **25a'nın kabulü.**
   1. Tam pytest ("bilinen tek hata ayrı, gerisi geçti", sayılarla; bilinen:
      `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`), `npm run build`,
      `npm run lint` (uyarı 17'yi aşmaz), Playwright tümü, `git diff --check`; en yüksek migration `0055`; `uv.lock`
      değişmemiş; `skill_package_hash` değişmiş ve yeni değeri raporda.
   2. **Yeniden oynatma** (salt okunur, model yok): 24a'nın 10 `sw` kütüphanesindeki saklı üç öneri yeni `consensus`'tan
      geçer; `criterion`, `parts`, `cue_phrases`, `exclusion_title_words`, `base_run`, `runs_ok`,
      `sought_term_in_criterion` saklı `criterion` adımının çıktısıyla bayt bayt aynı, iki yeni alan `[]`. 10/10 değilse dur.
   3. **Kuru koşu** (F1): ürünün kendi ölçüt adımı (`flow._criterion`, `.local/sw-criterion-dry-run-2026-09-21/run.py`'nin
      yöntemi), Codex `gpt-5.6-luna` · medium, kendi veri dizini, sağlayıcı isteği yok; iki soru × iki kez × üç çağrı = 12
      çağrı. Geçme: tıpta iki uzlaşmanın ikisinde de `required_roles = ["comparator", "population"]`, iki öğenin `words`'ü
      sorunun sözcükleri, iki parçanın tanımı kendi katılımcısını ve kendi karşılaştırma grubunu soruyor. Kuantumda iki
      uzlaşmanın `required_roles`'ı `[]` ise kuantumun 24a sonuçları kalır (sahibin kararı); biri boş değilse dur, satır
      25'e yaz: kuantumun sonuçları artık bu kodu anlatmıyor, sahip karar verir (kuantumun 7 araştırması da koşsun mu).
      Tek tek önerilerde rol yazan kuantum koşusu sayılır ve raporlanır, durdurmaz.
   4. **Europe PMC canlı denemesi** (salt okunur, kendi veri dizini, sağlayıcı araması yok). Örnek dondurulmuş
      (`.local/sw-slice25-plan-2026-09-26/sample_epmc.py` → `epmc-sample.json`): aday kuralını geçen ve `fullTextXML`'i
      gövdeyle dönen 30 PMCID'den iki referans denemesi (PMC8157764, PMC10708421) çıkarılır, kalan 29 dizgi olarak
      sıralanır, `random.Random(2409263).sample(havuz, 5)`, sonra iki referans eklenir: **PMC7262456, PMC10609268,
      PMC8308240, PMC11279456, PMC6682944, PMC8157764, PMC10708421**. Ürünün `europepmc_lookup` + getirme + çizim +
      çıkarma yolu her birinin DOI'siyle; geçme: 7 / 7'de varlık ve sayfalı pasaj, çizilen metinde makalenin başlığı ve
      özetinin ilk cümlesi bulunur, her yerde "rendered" etiketi, 1440 px'te bir sayfa görüntüsü göze okunur. Hepsi
      kuralı geçtiği için tek bir hata bile nedeni yazılarak durdurur (Europe PMC'nin o gün değişen kaydı dahil).

6. **D106** (25a'nın sonunda, `docs/decisions.md`'nin başına): SW23, SW22 ve SW21'in kararı (SW21 için: yol ve PDF
   yolunun ölçülen reddi, Europe PMC'nin sıradaki yeri, çizilen sayfanın etiketi, migration `0055`); kuru koşu ve yeniden oynatmanın
   sayıları; Limits: popülasyon ve karşılaştırıcıyı hiçbir koşunun yazmaması kodla yakalanmaz (kod yalnız çoğunluğun
   yazdığını taşımayan temeli reddeder); rol yalnız iki; tam metin okuması eksik parçayı kuyruğa atar, dışlamaz;
   `include`'suz yanıt bir o-anki durum kaydıdır; Europe PMC yalnız açık erişim alt kümesi, yazar el yazması yok, çizilen
   sayfa yayıncının sayfası değildir ve MathML işaretlemesi düşer; ölçümler bir makine, bir model, iki soru.

7. **25b, tıp sorusunun yeniden ölçümü.** Dilim 24a'nın dondurulmuş protokolü
   (`.local/sw-slice24-campaign-2026-09-26-134050/protocol.md`, plan `65a7ec8`) temeldir; aşağıdakiler dışında hiçbir şey
   değişmez.
   1. **Aynen alınanlar.** Tıp sorusunun metni bayt bayt; 7 araştırmalık matris ve sıra (`sw` `standard` r1, `legacy`
      `standard` r1, `sw` `quick`, `sw` `detailed`, yerleşik gömmeli `sw` `standard`, `sw` `standard` r2, `legacy`
      `standard` r2), aralarında 2 dk; sunucu ortamı (`protocol.md` "Server environment"), portlar 8858–8864; model Codex
      `gpt-5.6-luna` · medium, bütün roller; durma kuralları ("Stop rules"); ölçüm sözlüğü (plan 24'ün "Ölçüm sözlüğü");
      Elicit'in beş eseri ve kapsam etiketleri (`elicit-tre.jsonl`, `elicit-tre/`, özetleri 24a'nın `frozen-sha256.json`'u
      ile denetlenir); analist örneği tohumu `2409261` ve `sample.py`; ölçüm ve kapı betikleri (`measure.py`, `gates.py`,
      `post.py`, `missed.py`, `epmc.py`, `missed_pubmed.py`, `net.py`, `ledger.py`) bayt bayt kopyalanır ve özetleri
      24a'nın `frozen-sha256.json`'uyla karşılaştırılır (`missed_pubmed.py` orada yok, onunki kopyada yazılır);
      `measure.py`, `gates.py` ve `post.py` yalnız farkın tabanıdır, 25b onları çalıştırmaz (madde 7.2(c)); sürücü `drive.py`'nin 24a'da 13 araştırmayı süren düzeltilmiş hâli, özeti yeniden
      yazılır. Ret ve kaçırılan eser teşhisi, Europe PMC sayımı, analist okuması ve ikinci okuma kuralı aynı.
   2. **Değişen yalnız üç şey.** (a) Tıp referans kümesi, karar 8'in kuralıyla, ilk araştırmadan önce kurulur ve donar.
      (b) Sınanan kod: 25a'nın commit'i (SW23, SW22 ve SW21); donma anında `git diff --stat <25a commit> -- backend apps/web contracts methods`
      boş. (c) `include`'suz yanıtın Kapı 1 ve 2'deki okuması (karar 9, D1): `measure25.py`, `gates25.py` ve onları
      çağıran koşucu `post25.py`. Başka her fark bir sapmadır ve sonuca yazılır.
   3. **Klasör ve etkin işaretçi.** `.local/sw-slice25-remeasure-<YYYY-MM-DD>-<HHMMSS>/` (adı daha önce yok);
      `.local/sw-slice25-active` yalnız o klasörün `protocol.md`'si yazıldıktan sonra yazılır; sürdürme ve yeniden
      başlatma dilim 24'ün karar 13'üyle aynı (bu dosya ve bu işaretçiyle).
   4. **Dondurma sırası.** Klasör; 24a dosyalarının kopyaları ve özet denetimi; karar 8'in R'si (`reference-tre.jsonl`,
      `comparator-differs-tre.jsonl`, `unknown-tre.jsonl`, her adımı `ledger.jsonl`'da); `measure25.py`, `gates25.py`,
      `post25.py` ve öz sınama (karar 9);
      `protocol.md` (bu planın commit'i, 25a'nın commit'i, `skill_package_hash`, soru, matris, ortam, durma kuralları,
      kapılar, tohum, her donan dosyanın sha256'sı); sonra işaretçi. İlk `POST /api/researches` bundan sonradır. |R| < 10
      ya da bilinmiyor payı %25'i aşarsa hiçbir araştırma koşmaz (karar 8.7).
   5. **Kapıların yeniden okunması** (`gates25.py`; karar 9'un değişiklikleri; farklar `measure25.diff`,
      `gates25.diff` ve `post25.diff` olarak donar): kuantumun her ölçüsü 24a klasöründen olduğu gibi okunur, tıbbınki yeni klasörden.
      - *Kapı 1:* 10 `sw` araştırması = 24a'nın 5 kuantum araştırması (hepsi `structurally_valid` bitti, biri izinli
        sürdürmeyle) + 25b'nin 5 tıp araştırması. Tıp araştırması yanıtıyla bitmeli: `structurally_valid`, ya da (D1)
        `no_evidence` + `reason = no_includable_source`. `unverified_draft` ya da yanıtsızlık geçmez. İzinli sürdürme
        dışında elle müdahale yok.
      - *Kapı 2:* kuantum 24a'da geçti, kalır. Tıp yeni R ile, dört `standard` koşusunun dördü de yanıtla bittiyse
        okunur; "yanıtla bitti" Kapı 1'in aynı ortak denetimidir ve `include`'suz yanıtın atfı 0 sayılır; havuz payı en büyüğü (2, ⌈0,1 × |R|⌉), atıf payı 1 ve
        `legacy` ortalaması ≥ 1 ise iki `sw` koşusunun ikisinde de en az bir R atfı. Betimleyici karar kuralı,
        istatistiksel sınama değil.
      - *Kapı 3:* 25b'nin tıp `sw` yanıtlarında (atıf taşıyanlar) çözülemeyen bağ, bulunamayan çapa,
        `model_isolation_violation` ya da başka modelin çıktısı yok; kuantumunki 24a'dan kalır.
      - *Kapı 4:* tıp örneği 25b'nin iki `sw` `standard` koşusunun birleşiminden aynı tohumla; en az 8 tekil `include` ve
        8 tekil iddia, her birinde en çok 1 ciddi hata, ikinci okuma kuralı aynı; ciddi hatanın tanımı plan 24'ün Kapı
        4'ü. Kuantumun 0/10 ve 0/10'u kalır.
      Dördü de geçerse satır 24 `24a bitti; dört kapı geçti (tıp 25b'nin yeniden ölçümüyle)` olur ve 24b koşabilir
      (karar 10). Biri geçmezse satır 24 `24a bitti; kapı N geçmedi (25b); sahip kararı bekliyor`, D107 "varsayılan hâlâ
      `legacy`" diye yazılır (kapı, sayılar, Limits), sonuç `docs/product/sw-slice25-remeasure-results.md`'ye.
   6. **Raporlanan, kapıya girmeyen.** Plan 24'ün listesi; ayrıca: 5 tıp `sw` uzlaşmasının `required_roles`'ı; madde 3'ün
      17 işinden yeniden `include` olanlar ve olmayanların yeni kodu; `include`'suz biten araştırma sayısı;
      `part_without_evidence` boyu 24a ile yan yana.
   7. **Dondurulmuş beklentiler** (bu dosyanın commit'iyle donar; "dayanağı zayıf" yazanın saklı karşılığı yok):
      - Tıp `sw` uzlaşmalarının 5/5'inde popülasyon ve karşılaştırıcı parçası; öğelerin sözcükleri sorudan.
      - Europe PMC: `standard` koşusunda PDF'siz planlı işlerin %20–40'ı tam metni Europe PMC'den alır (sayı 8: bir
        koşuda üst sınır 30 / 83, %36; getirme ve çizim hatası bunu düşürür); PDF'i olan planlı iş 24a'nın 29 ve 19'undan
        (112'de) belirgin çok, 40–65.
      - `standard` koşusu başına `include` 3–9, iki `standard` koşusunun birleşimi 5–12 tekil iş (**dayanağı zayıf**:
        sayı 3'ün 8'den 4–5'i kalır, Europe PMC okunan işi artırır). Kapı 4'ün 8'lik alt sınırının tutup tutmadığı
        belirsiz.
      - Çekilen `include`'larda ciddi PICO hatası 0–1.
      - `include`'suz biten `sw` araştırması 0–2 / 5; her biri açık yanıtla biter.
      - `part_without_evidence` 24a'dakinden (8–28) büyük (**dayanağı zayıf**).
      - |R| 10–30, bilinmiyor ≤ %25 (**dayanağı zayıf**; tablolar açılmadı).
      - Kapı 2 havuzda geçer (24a'da `sw` 3/4, `legacy` 2/4 buldu; **dayanağı zayıf**). Atıfta belirsiz: 24a'nın R'sinin
        2 / 4'ü Europe PMC'den okunabilir hâle gelir, ama `legacy`'nin iki koşuda da atıf verdiği Lin 2023 yazar el
        yazmasıdır ve gelmez (sayı 8); genişletilmiş R'nin ne kadarının açık erişim alt kümesinde olduğu ölçülmedi.
      - Kapılar: 1 ve 3 geçer; 2 ve 4 belirsiz (sayı 6'nın PDF engeli kısmen kalktı); 24b'nin koşup koşmayacağı açık.
      - Süre ve çağrı 24a'nın tıp satırlarının ±%30'u; okunan iş arttığı için okuma çağrısı üst uca yakın (sayı 9).

8. **SW18, genişletilmiş tıp referans kuralı (E1).** Plan 24'ün karar 6'sı, şu değişikliklerle, aynı ayrıntıyla
   uygulanır ve her adımı deftere girer:
   1. **Sorgu ve sıra.** Karar 6 adım 1–2 harfi harfine; `edat` aralığının sonu 25b'nin günü; sayfalama ve `esummary`
      aynı.
   2. **Uygunluk.** (a)–(e) aynı (ağ meta-analizi hâlâ dışarıda). Yeni **(f)**: derlemenin kendi popülasyonu aşırı kilolu
      ya da obez yetişkinlerdir ya da yetişkinlerin geneli; bir hastalık ya da durumla tanımlı bir alt grup (diyabet ya da
      prediyabet, PKOS, MASLD / NAFLD gibi) ya da antrenmanlı / sporcu kişiler değildir. Yeni **(g)**: derleme TRE'yi
      kısıtsız yeme, olağan beslenme, olağan bakım ya da müdahalesiz bir kontrolle kıyaslayan en az bir karşılaştırma
      havuzlar; yalnız "TRE + kalori kısıtlaması, kalori kısıtlamasına karşı" havuzlayan derleme uygun değildir. (f) ve
      (g) önce özetten; özet karar veremezse aday elenmez, tablodan karar verilir ((c) gibi).
   3. **Tablo.** Adım 4 aynı: PMC'deki açık tam metin ya da yayıncının açık sayfası; açılmazsa `table_unavailable`;
      kaynakça listesine geri dönüş yok.
   4. **Deneme kararı ve birleştirme.** Adım 5–6 ve sözlüğün referans birimi aynı.
   5. **Durma.** Her tablo bittiğinde: en az üç tablo okunduysa ve |R| ≥ 10 ise durulur. Değilse sıradaki adaya geçilir;
      30 aday incelenince her durumda durulur.
   6. **Başlık.** R'nin başlığı: analist kümesi, bir model oturumu kurdu, insan doğrulaması değil; kural bu karardır;
      okunamayan tablolar ve bilinmiyor sayısı.
   7. **Kâğıt denetimi.** Durmada |R| < 10 ya da bilinmiyor payı %25'i aşarsa 25b hiçbir araştırma koşmadan durur: Kapı 2
      tıpta okunamaz, dört kapı geçemez, 7 koşu hiçbir şeye karar vermez. Satır 25 `25b durdu: |R| = n`; sahip karar verir
      (ör. kayıt tabanlı bir kural, E3).
   8. **Başlıktan bir ön bakış** (yalnız başlık; özet, (b) ve tablo erişimi denetlenmedi): 24a'nın 90 adaylık listesinde
      11–45. sıralardaki 35 adayın 11'i (f)'yi geçer görünüyor (ör. "Intermittent fasting for adults with overweight or
      obesity", sıra 18). 24a'nın okuduğu üç tablo (PKOS, egzersizle birlikte TRE, MASLD) (f)'den düşer; 24a'nın 4
      denemelik R'si yeni kuralla baştan kurulur, eskisi kullanılmaz.

9. **Kapı 1'in `include`'suz yanıt okuması (D1).** Plan 24'ün Kapı 1'i "yanıta kadar biter ve yanıt
   `structurally_valid`" der. `include`'suz yanıt `no_evidence`'tır ve model çıktısı taşımaz; onu `structurally_valid`
   yazmak kanıt sözleşmesine aykırı olurdu (AGENTS.md). 25b'de Kapı 1, `reason = no_includable_source` taşıyan bir
   `no_evidence` yanıtını "araştırma yanıtıyla bitti" sayar ve Kapı 2 aynı denetimi kullanır; o yanıtın atfı 0'dır.
   **Betik değişiklikleri** (Sol r1 bulgu 3): 24a'nın `measure.py`'si yanıtın yalnız durumunu saklar
   (`measure.py:390`), `gates.py`'nin `answered` / `finished`'i yalnız `structurally_valid`'i kabul eder (`gates.py:30-46`)
   ve Kapı 2 dört `standard` koşusu için aynı `finished`'i çağırır (`gates.py:65`). Üç adlı değişiklik, başka yok:
   (i) `measure25.py` her yanıta `validation_reason`'ı (`json_extract(validation_json, '$.reason')`) ekler; (ii)
   `gates25.py`'de tek ortak `answered(slug)`: `structurally_valid`, ya da araştırma `sw` ise ve yanıt `no_evidence` ve
   `validation_reason = no_includable_source` ise evet; `legacy`'nin `no_evidence`'ı, başka nedenli `no_evidence` ve
   `unverified_draft` hayır; `finished` bunu kullanır, Kapı 1 ve Kapı 2 `finished`'i çağırır; (iii) kuantum 24a
   klasöründen, tıp yeni klasörden. Atıf sayısı ölçümün sayısıdır (kanıt bağı olmayan yanıtta 0). `answered`, tıp
   ölçümünün bir yanıtında `validation_reason` anahtarı yoksa (değeri `null` olabilir, anahtar olmalı) sessizce "hayır"
   demez, adıyla durur: eski `measure.py` ile üretilmiş bir ölçüm kapıya giremez. Kuantumun 24a ölçümleri bu anahtarı
   taşımaz ve gerekmez (hepsi `structurally_valid`, karar 7.5).
   **Koşucu** (Sol r2 bulgu 1): 24a'nın `post.py`'si `measure.py`'yi (`post.py:27`) ve `missed.py`'yi (`post.py:39`)
   çağırır. 25b'nin koşucusu `post25.py`'dir; `post.py`'den tam üç farkı var, başka yok: (a) `measure.py` yerine
   `measure25.py`; (b) ölçüm yazıldıktan hemen sonra, `probe_report.py` ve `missed.py`'den önce, `m-<slug>.json`'u okur
   ve `misc.answers`'ın her ögesinde `validation_reason` anahtarını arar; biri eksikse sıfırdan farklı çıkışla durur
   (yanıtsız araştırmada liste boştur, bu bir hata değildir, Kapı 1 onu ayrıca düşürür); (c) `HERE` yeni klasördür
   (24a'nınki gibi dosyanın kendi klasörü, yani kod aynı; fark yalnız kopyanın yeri). `missed.py` ve onun kullandığı
   `net.py` bayt bayt kopyalanır (madde 7.1), `missed.py`'nin girdisi olan ölçümün `references[<ad>].table` biçimi
   `measure25.py`'de değişmez. Sıra her araştırma için: `post25.py <slug>`; yedisi bitince `gates25.py`, o da her tıp
   ölçümünde anahtarı yeniden denetler. Bir sınama betiği (`gates25_selftest.py`) donmadan önce sahte ölçüm dosyalarıyla
   beş durumu sınar: geçerli yanıt, `sw` `include`'suz yanıt, `legacy` `no_evidence`, başka nedenli `sw` `no_evidence`
   (dördü `answered`'ın beklenen cevabını verir) ve `validation_reason` anahtarı olmayan yanıt (durur); ayrıca
   `post25.py`'nin (b) denetimi anahtarsız bir ölçümle sıfırdan farklı çıkar. Gerekçe: Kapı 1'i düşüren şey (D105) yanıt koşusunun 422 ile
   reddedilmesiydi; sahip SW22'yi bu yüzden istedi. Kapı 2 ve 4 `include` ve atıf ister, bu okuma onları gevşetmez. Bu
   dondurulmuş bir kapının adıyla yazılmış tek okumasıdır; 25b'nin `protocol.md`'sine ve sonucuna sapma olarak girer.

10. **24b.** Satır 24 `24a bitti; dört kapı geçti (…)` ve satır 17 `kapandı` ise dilim 24'ün prompt'unun Part B'si
    (görev 10–14) koşar, üç farkla: karar numarası D105 değil sıradaki boş D (25b kapıları geçirdiyse D107 yazmamıştır,
    yani D107; D105 tarihsel kayıt olarak kalır); tıp sayıları 25b'nin sonucundan; SW21, SW22 ve SW23 D106'da kapandığı için 24b'nin "açık SW" listesine girmez; 24b'nin
    sınamasındaki en yüksek migration `0055`'tir.
    Satır 17 `kapandı` değilse önce Sol · high son kontrolü (`80caa75`'in düzeltmeleri).

11. **Güvenlik.** Port 8765 ve canlı kütüphane yok; canlı veri dizininden yalnız `codex-home`. Her sunucu kendi veri
    dizini ve portuyla. Anahtar deftere, günlüğe, sonuca yazılmaz. Kimse commit'lemez; commit'i koordinatör yapar.

## Sahip kararları (26 Eylül 2026: G2 sahibin seçimi; A1, B1, C1, D1, E1, F1, H1 önerildiği gibi)

Sahip soru sorulmadan ilerlenmesini istedi; A–F ve H'de öneri kabul edilmiş sayılır. G'yi sahip kendisi seçti. Seçenekler
kayıt için duruyor. Hiçbiri sahibin parasını ya da elini gerektirmiyor.

- **A — SW23'ün mekanizması.** Öneri **A1**: yöntem kuralı + sözleşme v2'de `question_elements` + kodda dört denetim +
  çoğunluğun yazdığı rolü taşımayan koşunun temel olamaması (karar 2). *A2*: yalnız yöntem metni; AGENTS.md "prompt
  wording alone is not a strict rule" der, SW23'ün kodda denetim istemini karşılamaz. *A3*: kod sorunun metninden kalıpla
  ("In adults with…", "compared with…") öğe çıkarır; İngilizceye ve yazım biçimine bağlı, kırılgan.
- **B — Roller.** Öneri **B1**: yalnız popülasyon ve karşılaştırıcı (ölçülen boşluk; müdahale ve sonuç 5/5 uzlaşmada
  vardı). *B2*: P, I, C, O dördü; kuantumda temel koşuyu değiştirebilir, ölçülmüş kazancı yok.
- **C — `include`'suz yanıt.** Öneri **C1**: `no_evidence` + `reason = no_includable_source`, başlangıç fotoğrafının
  sayılarıyla, model çağrısı ve migration olmadan, yalnız `sw`'de ve güncel revizyonun keşfi tamamlandıysa (karar 3). *C2*:
  ayrı bir yanıt durumu; `answers`'ı yeniden kuran bir migration ister. *C3*: özet düzeyinde kanıtla model yanıtı (SW22'nin
  öbür seçeneği); okuma derinliği kurallarını açar, sahibin tarif ettiği yanıt değil.
- **D — Kapı 1 okuması.** Öneri **D1**: böyle bir yanıt "yanıtla bitti" sayılır; donmadan önce protokole yazılır, sapma
  olarak raporlanır (karar 9). *D2*: harfiyen: `structurally_valid` değil, Kapı 1 düşer; SW22 düzeltmesi hiçbir zaman
  Kapı 1'i değiştiremez.
- **E — Tıp referans kuralı.** Öneri **E1**: popülasyonu ve karşılaştırıcısı soruya uyan derlemeler, |R| ≥ 10 ve en az üç
  tabloya kadar, en çok 30 aday; tutmazsa koşmadan dur (karar 8). *E2*: ağ meta-analizlerinin deneme tablolarını da
  almak; daha çok aday, daha çok analist yargısı. *E3*: ClinicalTrials.gov gibi bir kayıttan aynı karar ağacıyla; yeni bir
  kaynak ve yeni betikler.
- **F — Kuantum koruması.** Öneri **F1**: kuru koşuda kuantum uzlaşmasının `required_roles`'ı boşsa kuantumun 24a
  sonuçları kalır; değilse dur, sahip karar verir (karar 5.3). *F2*: koruma yok; yeni istem kuantum ölçütünü değiştirse de
  kuantum sonuçları kalır sayılır.
- **G — Yeniden ölçümün zamanı ve SW21.** **Sahibin seçimi G2 (2026-09-26):** SW21 dilim 25'e alınır, tıbbın yeniden
  ölçümü eksik PDF'e harcanmasın; yalnız tam metin bulma, arama kolu yok (karar 3a). Planın önerisi G1'di (SW21'siz 25b,
  Kapı 2 ve 4'ün PDF yüzünden geçmeyeceği beklentisiyle). *G3*: 25b'yi SW21'e kadar ertelemek.
- **H — Europe PMC'nin yolu.** Öneri **H1**: REST `fullTextXML`, yerelde PDF'e çizilip var olan çıkarmadan geçer; sayfalar
  "Europe PMC text, rendered p. n" diye etiketli (karar 3a). *H2*: PMC / Europe PMC PDF'i; bu makineden ölçüldü, çalışmıyor
  (Cloudflare 403, `oa.fcgi` 404, NCBI `not_pdf`). *H3*: XML'i sayfasız `section` pasajları olarak saklamak; sayfa üzerine
  kurulu ~70 yeri değiştirir, "en az kod" değil.

## Sahibin yapacağı

Bunlar soru değil. Yalnız Luna kotası 25b'nin ilk gerçek çağrısında biterse: kotanın yenilenmesini beklemek (para yok).
İsteğe bağlı: karar 7'nin analist örneğini kendisinin okuması; okursa sonuç "insan okuması" diye ayrı yazılır.

## Global constraints

- **25a'da davranış değişikliği yalnız üç yerde:** ölçüt önerisi (yöntem, sözleşme v2, denetim, uzlaşma, kayıt),
  `sw`'nin `include`'suz yanıtı (API, akış, arayüz) ve tam metin bulma sırasının sonundaki Europe PMC kaynağı (arama,
  getirme, çizim, etiket). Tam metin okuması, özet aşaması, sıralama, arama kolları, `legacy`'nin yanıt kuralı ve
  `pdf_collection`'ın 422'si değişmez. Tek migration `0055`.
- **Europe PMC yalnız açık erişim alt kümesi, yalnız DOI'si doğrulanan kayıt, yalnız başka açık PDF yokken;** çizilen
  sayfa hiçbir yerde yayıncının sayfası gibi yazılmaz.
- **Kanıt sözleşmesi.** `include`'suz yanıt `structurally_valid` yazılmaz, model çağırmaz, atıf taşımaz; "kaynak yok"
  demez, "o anda dahil edilen yoktu" der.
- **Kimse karar vermez** (25b): onay kartı `as_proposed`, kuyruk cevapsız, terim, ölçüt, seçim düzeltilmez.
- **Referans küme ve Elicit doğruluk değildir;** analist okuması insan doğrulaması değildir.
- **Her sayı** örnek büyüklüğü, makine ve modelle yazılır; tek koşu tek koşu diye.
- **8765 ve canlı kütüphane yok.** Model değişmez, sessiz geri dönüş yok.
- **Donmuş dosya düzenlenmez;** sapma sonuca yazılır.
- **Sahibin dosyaları** (`TODO.md`, `.vscode/`, `scripts/local_index.py`) değişmez, sahnelenmez.

## Task taslağı

**25a — kod**

1. Satır 25 `uygulanıyor (25a)`.
2. Yöntem dosyası (karar 2.1); şema v2 ve `SCHEMA_VERSIONS` (2.2).
3. `_check_criterion_proposal(step_input, draft, report)` ve dört hata kodu (2.3).
4. `consensus` (2.4); `CRITERION_ORIGIN_FIELDS`, `frozen_criterion`, `apply_criterion` (2.5).
5. SW22: `start_run`, `_answer`, `api.ts`, `ResearchView.tsx`, `i18n.ts` (karar 3).
5a. SW21: `europepmc_lookup`, sıra, `xml_fetcher`, `documents/jats.py`, `_attach_pdf` çağrısı, migration `0055`, görünümün
   `rendition`'ı ve arayüz etiketi (karar 3a).
6. Fikstürler, sahte model ve testler (karar 4).
7. Kabul: sınamalar, yeniden oynatma, kuru koşu (karar 5); betikler ve çıktılar
   `.local/sw-slice25-acceptance-<tarih>/`'e.
8. Belgeler: D106; `search-workflow-review-2026-09-18.md`'de SW21, SW22 ve SW23'ün durum satırları ("implemented in slice 25,
   D106") ve yeni SW26 (sonuç bildirmeyen deneme protokolünün `include` olması; sayı 3; hangi dilime dönüleceği: tam metin
   okumasının sonuç parçası); satır 25 `uygulandı, inceleme bekliyor (25a)`.

**25b — yeniden ölçüm** (satır 25 `kapandı` iken)

9. Klasör, kopyalar ve özet denetimi (karar 7.1, 7.3).
10. Referans kümesi (karar 8); |R| < 10 ise dur.
11. `gates25.py`, `gates25.diff`, `protocol.md`, işaretçi (karar 7.4, 7.5, 9).
12. 7 araştırma, sırayla (karar 7.1).
13. Ölçüm, analist okuması ve ikinci okuma (plan 24 karar 9–10).
14. Kapılar (karar 7.5); `docs/product/sw-slice25-remeasure-results.md`; satır 24 ve 25; kapı geçmediyse D107; SW18'in
    durum satırı.

**24b** (satır 24 `24a bitti; dört kapı geçti (…)` ve satır 17 `kapandı` iken): karar 10.

## Kabul koşulları

- 25a: karar 5'in dört maddesi; tam pytest (bilinen tek hata ayrı), build, lint, Playwright, `git diff --check`; en yüksek
  migration `0055`; `uv.lock` aynı; `skill_package_hash` değişti ve yazıldı; yeniden oynatma 10/10 bayt bayt; kuru koşuda
  tıp 2/2 uzlaşmada iki rol, kuantum 2/2 uzlaşmada boş rol (değilse dur).
- 25b: donan her dosyanın özeti ilk araştırmadan önce defterde; |R| ≥ 10; 7 araştırmanın her biri için yazılı sonuç (bitmediyse
  nerede durduğu); kapıların hükmü sayılarıyla; beklentiyle yan yana tablo; ürün dosyası değişmemiş; 8765 kullanılmamış.

## Bu dilimde yok

- SW19 ve SW20 (24b'nin görev 11'i), SW24 (getirme sınırı ve süre), SW25 (kod
  sorgusunda kaynaşmış ifade), dilim 23 (kod kapısı), D96 (b)–(c), SW6.6: sırayla bekleyen iş.
- Tam metin kararının `partial` kuralını değiştirmek (D85); popülasyon ya da karşılaştırıcısı `absent` olan işin kodla
  dışlanması.
- Sonuç bildirmeyen protokolün `include` olması (SW26 yalnız kayıt).
- Europe PMC arama kolu; PMID ile ya da PMCID ile doğrudan tam metin arama; yazar el yazmaları (`authMan = Y`); XML'in
  sayfasız `section` pasajları (H3); MathML'in denklem olarak okunması; NCBI PMC PDF'lerinin doğrulama sayfasını aşmak.
- Özet aşamasına ölçüt vermek; ölçüt parçası sınırını (2–5) değiştirmek; müdahale ve sonuç rolleri (B1).
- Kuantumun yeniden koşması (F1'in durma dalı dışında); üçüncü bir soru; `legacy`'nin kaldırılması.

## Ölçülmedi

Yeni istemle modelin popülasyon ve karşılaştırıcıyı yazıp yazmadığı (25a'nın kuru koşusu ölçer); Europe PMC'den gelen
işlerin kaçının okunup `include` olacağı, ikinci `standard` koşusundaki ve öbür eforlardaki kazanç (yalnız bir koşu
sayıldı) ve genişletilmiş R'nin ne kadarının açık erişim alt kümesinde olduğu (25b ölçer); tam metin okumasının
yeni parçaları nasıl etiketlediği ve madde 3'ün tahmininin tutup tutmadığı (25b ölçer); madde 3'teki okumanın ikinci bir
okuyucuda tutup tutmadığı; genişletilmiş kuralın |R|'si (tablolar açılmadı; yalnız başlıktan ön bakış); `include`'suz
yanıtın canlı bir kişide nasıl okunduğu.

## Sol r1 bulguları ve yapılanlar

`gpt-6-sol` · high r1 (`.local/sw-slice25-plan-2026-09-26/sol/answer-r1.md`), yalnız yüksek önem: "hazır değil", 4 bulgu.

1. **Beklenmeyen XML türü aday yazımını düşürürdü.** `fetch_file`'ın `wrong_type`'ı `pdf_candidates.access_status`
   CHECK'inde yoktu. Migration `0055` onu ekler; çizimin iki reddi `failed` + ayrı hata koduyla; üçü de sınanır (karar
   3a.4, 3a.7, karar 4).
2. **Canlı denemenin örneği kuralın reddettiği işleri içeriyordu.** 32'nin 2'si yazar el yazması. Örnek artık kuralı
   geçen 30'dan, dondurulmuş algoritmayla (`sample_epmc.py`, liste yazılı); üst sınır 30 / 83; tek hata durdurur; 25b
   beklentisi %20–40'a çekildi (sayı 8, karar 5.4, 7.7).
3. **Kapı betiği `no_evidence` nedenini göremiyordu.** `measure25.py` nedeni saklar; `gates25.py`'de Kapı 1 ve 2'nin
   kullandığı tek ortak denetim yalnız `sw` + `no_evidence` + `no_includable_source`'u kabul eder; atıf 0; öz sınama betiği
   (karar 7.2, 7.5, 9). Sahibin onayladığı D1'in uygulamasıdır, yeni bir kapı kuralı değildir.
4. **Çizilen sayfanın kaynağı her yüzeyde görünmüyordu.** `rendition` her pasajın kendi varlığından (eski atıflar dahil)
   taşınır; tek biçimleyici (`labels.ts` `pageLocator`) yanıt etiketi ve Markdown dışa aktarımı, PDF metin belgesi,
   kuyruk, denetim örneği, PDF bekleyen liste, pasaj yaprağı ve görüntüleyicide; her yüzey sınanır. Yan not
   (`_attach_pdf`'in `original_filename`'i) aynı maddede kapandı (karar 3a.6).

## Sol r2 bulguları ve yapılanlar

`gpt-6-sol` · high r2 (`.local/sw-slice25-plan-2026-09-26/sol/answer-r2.md`): r1'in dört bulgusu kapalı; 2 yeni yüksek
bulgu, "hazır değil".

1. **25b'nin koşucusu `measure25.py`'yi atlıyordu.** Bayt bayt kopyalanan `post.py` eski `measure.py`'yi ve kopya
   listesinde olmayan `missed.py`'yi çağırıyordu. Artık koşucu `post25.py`: `measure25.py`'yi çağırır, `missed.py`
   kopyalanır, ölçüm yazılınca `validation_reason` anahtarını denetler ve yoksa durur; `gates25.py` anahtarı yeniden
   denetler; `post25.diff` donar, öz sınama anahtarsız ölçümü de sınar (karar 7.1, 7.2, 7.4, 7.5, 9).
2. **XML'den PDF çizimi sınırsızdı.** Çizim artık `extract_pdf`'in kalıbıyla sınırlı bir çocuk süreçte: ayrıştırmadan
   önce 5 MiB girdi sınırı, 60 s, 1 GiB bellek bekçisi, 200 sayfa, 30 MiB çıktı; her sınırın kendi hata kodu, aday
   `failed` kaydıyla düşer ve sıradaki denenir; her sınır için bir test (karar 3a.5, karar 4).

## Sol r3 bulguları ve yapılanlar

`gpt-6-sol` · high r3 (`.local/sw-slice25-plan-2026-09-26/sol/answer-r3.md`, son plan turu): r2'nin iki bulgusu kapalı;
1 yeni yüksek bulgu, "hazır değil".

1. **Dahil edilen olmayan yanıtın uyarısı kanıttan fazlasını söylüyordu.** "No source met the inclusion criterion"
   okunmamış ya da kararı verilmemiş işleri kaynakla ilgili olumsuz bir hükme çeviriyordu (ölçülen durumda 14 işin bir
   parçası için kanıtı yok, 28'inin tam metni yoktu). Uyarı, bildirim ve Türkçeleri artık saklanan cümleyi kullanır: "No
   work was included at full text when this answer started"; başlangıç fotoğrafının sayıları görünür kalır (karar 2.3).
   Metin düzeltmesi olduğu ve plan turu sınırına (3) ulaşıldığı için ayrı bir Sol turu açılmadı; kod incelemesi bunu
   da görür.

Yan not (bloklamaz): örnek havuzu 30 uygun kayıt, 29 ayrı PMCID'dir (bir PMCID iki kayıtta); havuz 29 PMCID olarak
okunmalı.
