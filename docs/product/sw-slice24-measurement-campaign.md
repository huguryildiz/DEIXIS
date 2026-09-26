# SW dilim 24 — Ölçüm kampanyası, varsayılanı değiştir ve kapat

**Tarih:** 26 Eylül 2026. **Durum:** plan hazır; A1, B1, C1, D1, E1, F1, G1, H1, I1 önerildiği gibi (sahip soru sorulmadan
ilerlenmesini istedi). **İkinci görüş:** `gpt-6-sol` · high r1 "hazır değil", 9 bulgu ve 6 değişiklik; r2 "hazır
değil", r1'in 4'ü kapandı, 5'i kısmen, 6 değişiklik; r3 "hazır değil", 4 madde; r4 "düzeltmeyle hazır", 2 düzeltme,
işlendi (son dört bölüm); r5–r8 "düzeltmeyle hazır" (kampanya klasörünün adı ve `.local/sw-slice24-active`'in yazılma
anı, eşgüdümcü düzeltti); r9 "hazır". Sahibin kendi eli ya da parası gereken işler ayrı listede
("Sahibin yapacağı"); bunlar soru değil, yapılacak iştir. **Prompt:** [sw-slice24-prompt.md](sw-slice24-prompt.md).
**Ana dosya:** [sw-status.md](sw-status.md). **Karar:** D105 (en yüksek D104). **Migration:** yok. **Önkoşul:** 23
dışındaki bütün dilimler; satır 17, 18a, 18b ve 19'un durumu karar 2'de. **Tür:** Ölç. **Uygulayan:** Fable · high
(ana dosyanın "Bir tur" notundaki kural: protokolü dondurmak ve sonucu yorumlamak muhakeme işidir); uzun koşan betik Sonnet arka plan
ajanına verilebilir. **İnceleme:** 24a'nın sonucu sahibe gider; 24b toplu (Sol · high). **Plan:** Opus 5.5 · high.
**Ölçüm:** `.local/sw-slice24-plan-2026-09-26/`: `cost_time.py` → `cost-time.json`, `truth_in_runs.py` →
`truth-in-runs.json`, `k3_oa.py` → `k3-oa.json`, `elicit_vs_ledger.py` → `elicit-vs-ledger.json`, `elicit_in_runs.py`
→ `elicit-in-runs.json`, `queue.txt`, `legacy-live.txt`; kuantum Elicit dosyalarının salt okunur kopyaları
`elicit-quantum/` (`SHA256SUMS`); tıp sorusunda sahibin yapıştırdığı Elicit cevabı ve tablo dışa aktarımı `elicit-tre/`
(`elicit-answer-2026-09-26.md`, `elicit-included-2026-09-26.csv`, `README.txt`, `SHA256SUMS`). Saklı kütüphaneler
`immutable=1` ile, canlı kütüphane `mode=ro` ile açıldı; model çağrısı, sağlayıcı araması ve ağ erişimi yok; port 8765'e
dokunulmadı. **Kapsam:** ana planın §3'ündeki dilim 24 paragrafı ([sw-implementation-plan.md](sw-implementation-plan.md)
satır 171–173) ve K4, K5.

**Goal:** `sw` akışını ürünün kendisiyle, gerçek modelle, iki soruda uçtan uca koşturup ölçmek: (a) kuantum sorusu, 31
eserlik prob setine ve Elicit'in 9 eserine karşı; (b) mühendislik dışı yeni soru (zaman kısıtlı beslenme), yayımlanmış
meta-analizlerden kurallı çıkarılan bir dış referans kümesine ve Elicit'in listesine karşı; (c) iki soruda Elicit ile
çalışma düzeyinde karşılaştırma. Beklentiler bu dosyada, koşudan önce, git'te dondurulur. Sonuç sahibe gider; değişmesi
gereken eşik ve kurallar yeni SW girişi olur. Varsayılanın `sw` olup olmayacağını dondurulmuş kapılar (karar 11) söyler;
kapılar geçerse 24b varsayılanı değiştirir, belgeleri günceller ve kalan SW maddelerini D girişlerine taşır. `legacy`
yolunun kaldırılması ayrı karardır, bu dilimde yok.

## Bugün kod ne yapıyor

Kod 26 Eylül 2026'da `01dbccb` üzerinde okundu.

- **Bayraklar.** `Settings.search_workflow` sınıfta `"legacy"` (`config.py:28`), `load_settings` de `DEIXIS_SEARCH_WORKFLOW`
  yoksa `"legacy"` okur (`config.py:114-116`). Öbür `sw` bayrakları: `protocol_approval` `"ask"` (`config.py:32`,
  `DEIXIS_PROTOCOL_APPROVAL`, `as_proposed` duraklamadan onaylar), `fulltext_fetch` ve `fulltext_adjudication` `"auto"`
  (`config.py:36`, `:40`), `search_query` `"model"` (`config.py:44`), `citation_chaining` sınıfta `"off"` ama
  `load_settings`'te `"auto"` (`config.py:49`, `:129`), `arxiv_source` ikisinde de `"off"` (`config.py:54`, `:132`).
  Gömme bir `Settings` alanı değil; `PUT /api/semantic-search` ile saklanan bir ayar (`app.py:830`); yerleşik model
  `POST /api/semantic-search/builtin/install` ile kurulur (`app.py:855`). Araştırmanın varsayılan eforu `standard`
  (`app.py:83`).
- **Efor sınırları** (`domain/rules.py`): sorgu başına okuma `SW_READ_LIMIT` 400 / 1.000 / 1.000 (`:34`); özet okuma
  `ABSTRACT_READ_LIMIT` 40 / 100 / 300 (`:75`; K3'ün N'i), çağrı başına 20, iki koşu, alıntı en az 12 karakter
  (`:76-78`); zincirin kendi özet okuması 20 / 50 / 50 (`:109`), bu yüzden saklı koşularda okunan özet 60 / 150 / 350;
  getirme `FULLTEXT_WORK_LIMIT` 80 / 100 / 300 (`:89`, D94), okuma `FULLTEXT_READ_LIMIT` 40 / 50 / 150 (`:95`), çağrıda
  12 pasaj ve 8 ölçüt pasajı (`:97`, `:117`); 15 zincir tohumu (`:105`); yönlendirme payı `ROUTE_SHARE = 0.25` (`:55`),
  OpenAlex ve Semantic Scholar her zaman (`:56`), PubMed ve bioRxiv yaşam bilimi alanlarında (`:57-65`).
  `GET /api/effort-limits` bunları bayrağa göre döndürür (`app.py:1193-1195`).
- **Protokolün `thresholds` alanı** `build_protocol`'da (`workflow/protocol.py:205-247`): tarama partisi, RRF, parça
  boyu, kimlik eşikleri (0,85 / 0,8 / 0,6 / 0,5 / 5 yıl), ölçüt pasajları, derleme (150 referans), özet tamamlama, ölçüt
  önerisi (3 koşu, 2 çoğunluk), sıralama (BM25, 15 çizge tohumu, kurtarma 200 / 50), efor sınırları, sözlük, model
  sorgusu, genişleme, zincir. Yönlendirme payı `source_routing` bloğuna ayrı yazılır (`protocol.py:183-186`).
  **Yazılmayan iki elle seçilmiş eşik:** blok etiketlemenin `LABEL_RUNS = 3`, `LABEL_MAJORITY = 2` ve
  `MAX_LABELLED_PHRASES = 40`'ı (`workflow/vocabulary.py:24-26`) `vocabulary.THRESHOLDS`'ta yok (`:30-36`); ana planın
  §2.7'si her elle seçilmiş eşiğin `thresholds`'a yazılmasını ister. `routing.THRESHOLDS` (`workflow/routing.py:22-23`)
  hiçbir yerden okunmuyor; yazılan değer `route()`'un kendi dönüşünden geliyor (`routing.py:105-107`).
- **Europe PMC yok.** `providers/registry.py:77-103`'teki bağlayıcılar `openalex`, `semantic_scholar`, `crossref`,
  `arxiv`, `biorxiv`, `pubmed`, `ieee_xplore`, `scopus`, `core`, `serpapi`; `backend/deixis` içinde `europe_pmc` ya da
  `europepmc` geçmiyor. Europe PMC ne arama kolu ne tam metin kaynağı olarak kuruldu (dilim 10 onu dilim 14'e bıraktı,
  dilim 14 kurmadı). PubMed anahtarsız (`registry.py:92`).
- **Maliyet kaydı.** Her model çağrısı `model_sessions` satırıdır; `token_usage_json` ve başlangıç / bitiş zamanını
  taşır (`storage/migrations/0001_initial.sql:83-100`). Para karşılığı hiçbir yerde hesaplanmıyor; Codex aboneliğinde
  çağrı başına fiyat da yok.
- **Kuyruk.** Kuyruk kodları `REASON_CODES`'tan `next_step == "human_queue"` olanlardır (`workflow/queue.py:36`);
  araştırma görünümü açık satır sayısını `queue_counts` ile verir (`queue.py:357-361`, `views.py:566-568`).
- **Prob seti ve rapor.** Ürünün prob seti yalnız kişinin kararlarından türer (`workflow/probes.py:46`, D101);
  kampanyada kuyruğa kimse cevap vermediği için boş kalır. `scripts/probe_report.py` bir saklı kütüphaneyi dış bir
  referans kümesine (ilk satırı `{"origin", "completeness"}` başlığı olan JSONL) karşı okur, kol ve sinyal satırlarını
  yazar, kütüphaneye dokunmaz (`scripts/probe_report.py:1-26`, CLI `:293-309`). `PROBE_JUDGE_MIN = 30` bir görüntü
  sabitidir, protokol eşiği değil (`probes.py:30`).
- **Dışa aktarım.** PRISMA-S dökümü `GET /api/researches/{id}/prisma-s` (`app.py:1182-1189`); akış kutuları
  `workflow/flow_counts.py:103`.
- **OpenAlex sayımı.** `openalex.count_works` ürünün arama parametresiyle `per_page` sayımı yapar (`providers/openalex.py:205-220`);
  DOI süzgeci almaz. Kampanyanın kaçırılan eser teşhisi aynı sabitlerle (`SEARCH_PARAM`, `WORKS_URL`) bir `filter=doi:`
  ekleyerek kendi isteğini kurar (karar 9).
- **Belgeler.** README ve CLAUDE.md `search_workflow`'u hiç anmıyor; CLAUDE.md'nin "Runs and steps" bölümü yalnız
  `discovery` ve `answer` koşularını anlatıyor (`CLAUDE.md:33-35`). `docs/README.md:17` SW belgesini "not implemented"
  diye tanıtıyor. `docs/product/implementation-plan.md` §9 (satır 284-355) P0–P10 fazlarını anlatır, `sw` / `legacy`
  geçmez.

## Elimizdeki sayılar

Bütün sayılar saklı koşulardan okundu; koşular Apple M1 Pro (10 çekirdek, 32 GB) üzerinde, `codex` / `gpt-5.6-luna` ·
medium ile, gömme kapalı, protokol olduğu gibi onaylanarak koştu. "Dilim 15 sonrası" 15, 16 ve 17a kabul koşularıdır
(zincir açık; bugünkü mimariye en yakın olanlar); kopyalar (18a, 18b, 21 kabul kütüphaneleri) bir kez sayıldı. Her
efor için örnek 2–5 koşu; hepsi tek soru, tek model. Dağılım değil, gözlenen aralık.

1. **Süre ve çağrı** (`cost-time.json`, 31 tamamlanmış `sw` araştırması). Dilim 15 sonrası, kuruluştan yanıtın bitişine:
   `quick` 12,9–13,7 dk ve 67–71 çağrı (2 koşu); `standard` 19,9–24,5 dk ve 111–125 çağrı (2); `detailed` 41,6–42,4 dk
   ve 292–320 çağrı (2). 17a'nın yanıtsız kabulünde keşif + getirme + okuma `quick` 7,9, `standard` 14,0 dk (sw-status
   satır 17a); yanıt aşaması önceki ölçümlerde 1,7–2,8 dk. Çağrı başına giriş 10,1–11,2 bin, çıkış 0,8–0,9 bin jeton
   (örnek: `detailed` 320 çağrıda 3,25 M giriş, 0,26 M çıkış). `deepseek-flash` · high ile üç `quick` koşusu (duman 4, 5
   ve 13ö'nün ilki): 45–52 çağrı, 0,44–0,46 M giriş, **0,45–0,55 M çıkış** (çağrı başına ~10 bin; Luna'nın on katından
   fazla), 16,3–37,6 dk. DeepSeek bakiyesi 22 Eylül'de `standard`'ın ortasında bitti (`HTTP 402`, D88).
2. **31 eserlik prob seti aşama aşama** (`truth-in-runs.json`; eşleme DOI ya da normalleştirilmiş başlık, iş düzeyinde).
   Dilim 15 sonrası:

   | efor (koşu) | havuzda | özette aday (`candidate`) | okunan | `include` | atıf alan |
   |---|---|---|---|---|---|
   | `quick` (5) | 20–26 | 15–22 | 5–9 | 3–7 | 0–3 (2 yanıt) |
   | `standard` (3) | 29–30 | 20–24 | 7–8 | 5–7 | 4–5 (2 yanıt) |
   | `detailed` (2) | 29–30 | 24–26 | 18–19 | 11–13 | 0–2 |

   Kayıp aramada değil, özet aşamasından sonra: okuma sınırı ve sıra (D88'in üçüncü ölçümü, D94). "Özette aday" yalnız
   `candidate` sonucudur; özetin `unresolved` bırakıp tam metne yönlendirdiği işler (sözlük) bu sütunda yok. Sayılar
   referans eser sayısıdır, payda 31.
3. **Elicit'in 9 eseri** (`elicit-vs-ledger.json`, `elicit-in-runs.json`). 9'un 9'u da 18 Eylül'deki 160 eserlik
   karar defterimizde (`.local/quantum-work-adjudication-2026-09-18/adjudication.jsonl`) var. 5'i 31'lik sette; Elicit bu
   beşini "Full text" diye işaretlemiş. Öbür 4'ünü Elicit "Abstract only" demiş; bizim defterde 3'ü
   `unresolved_access_or_extraction` (tam metne erişilemedi), 1'i `algorithmic_optimization_without_formulation`. Yani
   kuantumda Elicit, 18 Eylül'deki defterimizin görmediği bir eser getirmedi. Elicit'in "Full text" etiketi ile defterin
   `confirmed_mathematical_model` / `high` sınıfının aynı 5 eserde örtüşmesi iki ayrı etiketin örtüşmesidir, ortak bir
   değerlendirme değildir: defterin sınıfı da model türevidir. Elicit bu koşuda "Elicit Research Agent, Balanced"
   ayarındaydı (`elicit-quantum/Elicit quantum network optimization search 2026-09-17.md:4`). Dilim 15 sonrası 5 koşuda
   Elicit'in 9'undan havuzda 6–9, özette aday 6–9, okunan 1–5, `include` 0–2, atıf alan 0–1.
4. **K3'ün N'i** (`k3-oa.json`). Bir eserin bütün sürümleri `abstract_not_read` ise o eser N yüzünden okunmadı sayıldı.
   Dilim 15 sonrası, havuzdaki 31'lik set eserlerinden okunmayan: `quick` 4–6 / 20–26 (5 koşu), `standard` 6–9 / 28–30
   (4), `detailed` 4–5 / 29–30 (2). N'in dışında kalan kayıtlar çok: 17a `standard`'da 1.743 kayıt `abstract_not_read`.
5. **SW10'un açık erişim fikri** ("for an open-access record, skip the abstract-stage model proposal and run the code gate
   on the full text directly", `search-workflow-review-2026-09-18.md:184`). Modelin özet okuduğu 32 ayrı saklı kuantum
   koşusunun (kopyalar bir kez sayıldı; 22 Eylül'ün iki duman koşusunda model hiç özet okumadı) hiçbirinde model, açık
   erişimli kopyası olan bir 31'lik set eserini kapsam dışı saymadı (0). Modelin okuduğu özetlerin açık
   erişimli payı: 17a `standard` 62 / 149, 15 `detailed` 130 / 350. N yüzünden okunmayan set eserlerinden açık erişimli
   kopyası olan dilim 15 sonrası koşu başına 1–3. Okunmayan kayıtların açık erişimlisi 17a `quick` 410 / 929, `standard`
   576 / 1.743. Fikrin "kod kapısı" yarısı dilim 23'tür ve kurulmadı.
6. **Kuyruk ve PDF bekleyen** (`queue.txt`; sürüm düzeyinde `next_step = 'human_queue'` karar satırı, kuyruk satırı
   değil). `quick` 7–17, `standard` 25–27, `detailed` 92–100; `standard` ve `detailed`'da çoğu
   `part_without_evidence` (77 / 92, 74 / 100: D96 (a)'nın ölçütte konu parçası sorunu). PDF bekleyen: `quick` 27–65,
   `standard` 55–58, `detailed` 169–173.
7. **Legacy.** `.local` altında bugünkü şemada tamamlanmış `legacy` araştırması yok. Canlı kütüphanede (şema `0036`, eski
   kod, 14–17 Eylül) yanıtı tamamlanmış 19 `standard` araştırması: 3–28 model oturumu, 1,4–10,2 dk (tek araştırma 6,4 sa:
   araya bekleme girmiş) (`legacy-live.txt`). Bugünkü `legacy` kodunun süresi ve sonucu ölçülmedi.
8. **Yeni soru için elimizde olan.** Sahip Elicit'i 26 Eylül'de tam olarak bizim sorumuzla (karar 5'teki metin),
   Elicit'in "balanced" ayarında koştu; cevabı (Türkçe çevirisiyle) ve tablo dışa aktarımını yapıştırdı. Sahibe göre
   Elicit bu soruda **yalnız beş çalışma** döndürdü ve cevabını bu beşinden kurdu; bu beşi Elicit'in dahil ettiği
   kümenin tamamıdır: Lin 2023 (Ann Intern Med, 10.7326/M23-0052), Wilkinson 2026 (Obesity, TREAD, 10.1002/oby.70228),
   Cienfuegos 2020 (Cell Metab, 10.1016/j.cmet.2020.06.018), Liu 2022 (NEJM, 10.1056/NEJMoa2114833), Jamshed 2022 (JAMA
   Intern Med, 10.1001/jamainternmed.2022.3050); her birinin kayıt numarası (NCT) da var
   (`elicit-tre/elicit-included-2026-09-26.csv`; özetleri çıkarılmış bir kopya, `README.txt`). Kuantumdaki CSV'lerden
   farkı: sorgu ve iş akışı dökümü yok, taranmış bir listenin denetim izi değil. Elicit'in kendi cevabına göre ve Liu
   2022'nin başlığına göre Liu 2022'de ve Jamshed 2022'de iki kolda da kalori kısıtlaması var: karşılaştırıcı "kısıtsız
   yeme ya da olağan beslenme" değil, kalori kısıtlaması. Yönlendirmenin tıp
   sorusunda nasıl davrandığını gösteren tek saklı örnek dilim 14 kabulündeki yenidoğan sepsisi sorusu (`quick`, yalnız
   onay kartına kadar): OpenAlex alan dağılımında Medicine 984 kayıt, PubMed ve bioRxiv seçildi; PubMed araması hiç
   koşmadı.

Sayıların gösteremediği: mühendislik dışı bir soruda `sw`'nin uçtan uca davranışı; PubMed kolunun kayıt getirip
getirmediği; bugünkü `legacy` kodunun aynı soruda ne bulduğu; yerleşik gömmenin açıkken sıralamaya katkısı; 31'lik setin
kendi koşularımızdan türemesinin (SW3 Limits, `search-workflow-review-2026-09-18.md:60`) sonuca ne kadar yansıdığı;
etiketlerin doğruluğu (hiçbirinde insan etiketi yok).

## Ölçülecekler

**"Kur (ölçülmedi)" diye giren parçalar ve D Limits'lerinin dilim 24'e bıraktıkları.** Her satır kampanyanın hangi
çıktısından okunacağını söyler. "Ölçülmez" satırı, kampanyanın o parçayı neden ölçemediğini söyler.

| Parça | Kaynak | Kampanyada |
|---|---|---|
| 04a / 04d / 13h sözlük, blok etiketleme, model sorgusu | D73, D74, D92 | Her referans eserin hangi sorgudan geldiği (model / kod / ikinci tur / zincir), ham sağlayıcı sayfasından (`sw-measure-2026-09-24/quality.py`'nin yöntemi); `legacy`'nin D44 planıyla aynı soruda yan yana |
| 04b veriden genişleme | D76 | İkinci turun tek başına getirdiği referans eserler ve eklediği kayıt |
| 04c okuma sınırı (`SW_READ_LIMIT`) | D75 | Sınıra varan sorgular; havuza girmeyen her referans eser için OpenAlex sorgusu onu kapsıyor mu (karar 9) |
| 05 derleme, özet tamamlama | D77 | Referans eserlerden derleme işareti alan; `lookup` sınırına (200) varılıp varılmadığı |
| 06 ölçüt önerisi | D78, D96 (a) | Aranan şey ölçütte kaldı mı (iki soru); konu parçası sayısı; `part_without_evidence` payı |
| 08c model terim önerisi | D82 | **Ölçülmez:** yalnız kişi isteyince koşar; kampanyada kişi yok. İlk turun büyüklüğü ve referans eser sayısı "ince tur" eşiği için kaydedilir, eşik önerilmez (iki soru yetmez) |
| 11 ölçüt pasajları | D84 | Yanıt girdisindeki 48 pasajın ölçüt ve konu kotasına dağılımı; atıf alan pasajların hangi kotadan geldiği |
| 12 tam metin kararı | D85 | `include` / `criterion_not_met` / `unresolved` dağılımı; karar 10'un denetim örneği (analist okuması) |
| 13a şemaya uymayan modeller | D86 | **Ölçülmez** B1'le (Luna şemayı zorlar); B2'ye geçilirse ilk koşuda bakılır |
| 13b Crossref aramadan çıktı | D87 | **Ölçülmez:** yalnız Crossref'in bulacağı eser için ayrı arama gerekir; kapsam dışı |
| 13c efor sınırları ve süre hedefleri | D88 | Efor başına duvar saati ve aşama süreleri, 10 / 15 / 20 dk hedefleriyle |
| 14 kaynak yönlendirme | D93 | Alan dağılımı, seçilen / dışarıda kalan kaynak ve paylar; kaynak başına bulunan ve yalnız onun bulduğu referans eser (`probe_report.py`) |
| 15 atıf zinciri | D95 | Yalnız zincirin getirdiği referans eserler |
| 17a getirmenin keşifle üst üste binmesi | D98 | Süre: getirmenin bitişi ile son model partisi arasındaki fark (`detailed` ve tıp sorusu ilk kez) |
| 18a kurum vekili | D99 | **Ölçülmez:** kurum ağı gerekir. PDF bekleyen listenin boyu iki soruda kaydedilir |
| 21 yerleşik gömme | D103, D101 | Karar 3'ün gömmeli koşuları: kurtarma kolunun getirdiği referans eserler, sinyal tablosu; D101'in "gömme koşarsa yeniden açılır" dediği iki açık gereksinim (maliyetli sinyalin kapanması, durma kuralı) için veri |
| 22 arXiv LaTeX kaynağı | D104 | Kuantum koşularında bayrak `auto`: indirilen / eşleşen / yerleşen denklem sayısı, KaTeX hatası, 40 yerleşmenin görüntüden okunması (karar 12) |

**Elle seçilmiş eşikler.** Her biri için kampanya bir "pay" okur: referans eserlerden kaçı eşiğin öbür yanına ne kadar
yakın. Eşiği değiştirmek bu dilimin işi değil; değişmesi gereken eşik SW girişi olur (karar 14).

| Eşik | Yeri | Okunan |
|---|---|---|
| `SW_READ_LIMIT` 400 / 1.000 / 1.000 | `rules.py:34` | Sınıra varan sorgu; sınırın ötesinde kalan referans eser (karar 9) |
| `ABSTRACT_READ_LIMIT` (K3'ün N'i) 40 / 100 / 300 | `rules.py:75` | N yüzünden okunmayan referans eser ve modelin havuzundaki yeri; hepsini okumak için gereken N |
| `FULLTEXT_WORK_LIMIT` 80 / 100 / 300, `FULLTEXT_READ_LIMIT` 40 / 50 / 150 | `rules.py:89`, `:95` | Özet aşamasını geçip planın ya da okumanın dışında kalan referans eser |
| `ROUTE_SHARE` 0,25 | `rules.py:55` | İki sorunun alan payları ve eşiğe uzaklıkları |
| Kimlik eşikleri 0,85 / 0,8 / 0,6 / 0,5 / 5 yıl | `domain/record_identity.py:18-22` | Eşiğin ±0,05'i içindeki birleşme ve bağlar; bir referans eserin bölünüp bölünmediği ya da yanlış birleşip birleşmediği |
| Derleme 150 referans | `domain/survey.py:20` | Yalnız referans sayısıyla işaretlenen referans eser |
| Zincir 15 tohum, 400 atıf, özet okuma 20 / 50 / 50 | `rules.py:105-109` | Yalnız zincirin getirdiği referans eser |
| Kurtarma 200 / 50 | `workflow/ranking.py:31-32` | Gömmeli koşularda "gömme kolundan" gelen referans eser |
| Alıntı alt sınırı 12 karakter (özet, tam metin) | `rules.py:78`, `:118` | Kısa diye reddedilen alıntı sayısı |
| Ölçüt önerisi 3 koşu / 2; blok etiketleme 3 / 2 | `workflow/criterion.py:18-19`, `vocabulary.py:24-25` | Anlaşma oranı; çoğunluk olmayan ifadeler |
| Genişleme (`MIN_FIELD_SHARE` 0,2, en çok 8 terim) | `workflow/expansion.py:29-31` | İkinci turun katkısı |
| Özet tamamlama 200 istek | `workflow/lookups.py:37` | Sınıra varıldı mı |

Ayrıca: K3'ün N'i (yukarıda), SW10'un açık erişim fikri (sayı 5'in üç ölçüsü, iki soruda), toplam model maliyeti ve süre,
kuyruk boyu.

## Ölçüm sözlüğü

Sol r1 bulgu 5'in istediği tanımlar. Kampanyanın aşama tabloları ve kapıları bu adları ve paydaları kullanır. Saklı
sayılar (sayı 2–6) bununla aynı değildir: plan oturumunun betikleri DOI **ya da** başlıkla eşledi ve "özette aday"ı yalnız
`candidate` diye saydı; kampanya bu sayıları sözlüğün kuralıyla yeniden hesaplamaz, yalnız kıyas için anar.

- **Referans birimi.** R'nin bir satırı **tekil bir denemedir** (kuantumda tekil bir eser). Tıpta üç derlemenin tablosunda
  geçen aynı deneme, birleştirme sırasıyla tek satırdır: PMID, sonra DOI, sonra kayıt numarası (NCT vb.), sonra
  normalleştirilmiş başlık; satır hangi derlemelerden geldiğini listeler. Aynı denemenin iki yayını (ör. ana sonuç ve
  ikincil analiz) aynı kayıt numarasını taşıyorsa tek birimdir; kayıt numarası yoksa ayrı kalır ve listelenir. Farklı
  kayıt numarası taşıyan iki satır, PMID ya da DOI paylaşsa bile **birleştirilmez**: paylaşılan yayın (iki denemeyi
  bildiren bir makale) iki denemenin de yayın listesine girer. Payda
  |R| tekil birim sayısıdır ve Kapı 2'nin payları ona bağlıdır. "Karşılaştırıcı farklı" ve "bilinmiyor" birimleri
  paydaya girmez, ayrı raporlanır.
- **Birimin yayınları.** Her R birimi kendi yayın listesini taşır: kuantumda eserin DOI'leri ve OpenAlex kimlikleri; tıpta
  denemenin R'de birleşen bütün satırlarının PMID ve DOI'leri (aynı kayıt numarasını taşıyan her yayın). Kayıt numarası
  havuzda aranmaz; bir denemenin listede olmayan başka bir yayını bulunsa da deneme bulunmuş sayılmaz ve bu sınır
  sonuçta yazılır.
- **Eşleme.** Birimin her yayını, araştırmanın havuzundaki bir sürümle önce DOI (küçük harf, `doi.org` öneki atılmış),
  sonra PMID (tıp), sonra normalleştirilmiş başlık (harf ve rakam dışı her şey boşluk, küçük harf) ile eşleşir. DOI'si ve
  PMID'si olmayan yayın yalnız başlıkla eşleşir ve tabloda işaretlenir. DOI bir işe, başlık başka bir işe gösteriyorsa DOI
  kazanır ve çatışma listelenir. Eşleşen sürümlerin işleri (`work_id`) ve o işlerin bütün sürümleri birimin işleridir.
- **Birim düzeyinde sayım.** Sayılan her zaman R birimidir, iş değil. Bir birim bir aşamada sayılır, eğer işlerinden
  birinin herhangi bir sürümü o aşamadaysa. Birimin yayınları iki ayrı işe eşleşirse (bölünmüş iş ya da aynı denemenin
  iki yayını) birim en ileri aşamasıyla bir kez sayılır ve bölünme listelenir. Farklı birimler **hiçbir zaman**
  birleştirilmez: tek bir iş iki birime eşleşirse (iki denemeyi bildiren bir yayın) iki birim de o işin aşamasıyla ayrı
  ayrı sayılır ve paylaşılan iş listelenir. Kapı 2'nin pay ve paydası bu birim sayımıdır.
- **`probe_report.py` ayrı tutulur.** O betik DOI, OpenAlex kimliği ya da başlıktan **herhangi biri** eşleşince sayar
  (`scripts/probe_report.py:125-126`), öncelik sırası yoktur. Onun kol ve sinyal satırları sonuçta kendi tablosunda,
  "probe_report eşlemesi" etiketiyle durur; aşama sayıları ve kapılar yalnız bu sözlüğün eşlemesiyle hesaplanır, iki
  tablo toplanmaz ve birbirine bölünmez.
- **Aşamalar** (her biri güncel kapsam revizyonunda, güncel satırlarla: `superseded_at IS NULL`):
  - *havuz*: bir `candidates` satırı;
  - *özette aday*: özet aşaması kararı `candidate`;
  - *tam metne yönlendirilen*: özette aday **ya da** özet kararı `unresolved` olup kod tarafından getirmeye yönlendirilen
    (`runs_agree_unresolved`, `abstract_not_found`; `workflow/fulltext.py:101-111`'in 2. ve 3. grubu). "Özet aşamasını
    geçen" adı bu planda kullanılmaz;
  - *N yüzünden okunmayan*: işin bütün sürümleri `abstract_not_read`;
  - *planlanan*: son `code:fulltext_plan` adımının iş listesinde;
  - *PDF'i olan*: kaldırılmamış bir `source_assets` satırı;
  - *okunan*: bir `fulltext` model önerisi;
  - *include*: tam metin kararı `include`;
  - *atıf alan*: son başarısız olmayan yanıtın bir kanıt bağı.
  `legacy` için yalnız havuz, tarama seçimi `included` ve atıf alan.
- **Paydalar.** Her aşama n / |R| diye yazılır. Geçiş payı yalnız iç içe bir zincirde verilir ve kesişimle hesaplanır:
  havuz → tam metne yönlendirilen → okunan → include → atıf alan; pay = |sonraki ∩ önceki| / |önceki|. "Özette aday",
  "N yüzünden okunmayan", "planlanan" ve "PDF'i olan" yalnız n / |R| ile yazılır, çünkü zincirle iç içe değildir. Tek koşu
  tek koşu diye yazılır; iki koşulu hücrelerde iki değer ve ortalama.
- **Zamana bağlı teşhis.** Kaçırılan eser teşhisi (karar 9) kampanya günü yapılır; "sorgu bugün kapsıyor" demektir, koşu
  anındaki arama sonucunu geriye dönük kanıtlamaz.

## Kararlar

1. **İki aşama.** **24a** kampanyadır: koşar, ölçer, sonucu yazar; ürün koduna dokunmaz. **24b** varsayılanı değiştirir ve
   kapatır; yalnız karar 11'in dört kapısı geçtiyse ve satır 17 `kapandı` ise koşar. Aynı prompt iki bölümdür; hangisinin
   koşacağını satır 24'ün durumu söyler. İkisi arasında koordinatör 24a'nın sonucunu commit'ler ve sahibe gösterir.
2. **Açık uçlar (H1).** Hiçbiri kampanyayı bekletmez.
   - **17** ("inceleme düzeltildi, son denetim bekliyor"): son denetimin düzeltmeleri `80caa75`'te; onları doğrulayan son
     kontrol yok. Kampanya kuyruğu arka uçtan sayar, ekranı kullanmaz, bu yüzden 24a'yı bekletmez. **24b'yi bekletir:**
     varsayılan `sw` olunca her yeni araştırma kuyruk sekmesini gösterir. 24b'den önce Sol · high son kontrolü koşar ve
     satır `kapandı` olur.
   - **18a** ("yayıncı PDF'iyle kabul yapılmadı"): 18b'nin kabulü tam bunu yaptı: 18a kabul kütüphanesinin kopyasında,
     listedeki bir yayıncı PDF'i (10.1109/jsac.2024.3380080, IEEE, 14 sayfa) DOI ile tek sürümüne eşlendi ve onaylandı,
     liste 65 → 64 (satır 18b). 18a bu kabule dayanarak `kapandı` yazılır; kurum vekili "ölçülmedi" kalır.
   - **18b, 19** ("uygulandı"): incelemeleri bitti (18b dört Sol turu, hepsi düzeltildi; 19 üçüncü tur "hazır"), commit'ler
     `926e01d` + `4a3354c` ve `d96e41d`. Satırları yalnız defter olarak eskimiş; `kapandı` yazılır.
   - **23** (kod kapısı, isteğe bağlı) ana plan gereği dışarıda. SW10'un açık erişim fikrinin "kod kapısı" yarısı ona
     bağlıdır; kampanya yalnız fikrin ölçülebilen yarısını okur (karar 9).
   - **D96'nın ayrı işleri** ((a) ölçütte konu parçası, (b) alıntı doğrulamasının satır numaraları, (c) kimlik denetimi,
     SW6.6) bu dilimde düzeltilmez; kampanya (a)'nın tıp sorusundaki boyunu ilk kez ölçer.
   Satır güncellemeleri 24a'nın ilk görevidir (yalnız `sw-status.md`; kod yok).
3. **Kampanya matrisi (A1).** Her soru için, aynı gün, aynı model, art arda:
   - `sw` × `quick`, `standard`, `detailed` (gömme kapalı; önceki üç D88 ölçümüyle karşılaştırılabilir);
   - `sw` × `standard`, yerleşik gömme açık (D103'ün `bge-small-en-v1.5`'i, araştırmanın kendi veri dizinine kurulur);
   - `legacy` × `standard` (bugünkü `legacy` kodu, aynı soru, aynı model): varsayılan kararının karşılaştırma tabanı.
   - **Kapı 2'nin iki hücresi iki kez:** gömmesiz `sw` `standard` ve `legacy` `standard` her soruda baştan iki kez koşar
     (r1, r2), sonuca bakmadan ve iki taraf için aynı kuralla; kapı dört koşunun hepsini kullanır (karar 11). Başka hiçbir
     hücre tekrarlanmaz; tartışmalı sonuç üzerine ek koşu yok (Sol r1 bulgu 3). K8 bu kampanyada kapı değildir: yalnız
     D88'in önceki ölçümüyle kıyas satırlarında, betimleyici olarak anılır.
   Toplam 14 araştırma. Her araştırma kendi boş veri dizininde ve kendi
   portunda (8851'den başlayarak) koşar; aynı anda tek araştırma. Sunucu ortamı: `DEIXIS_SEARCH_WORKFLOW` (`sw` ya da
   `legacy`), `DEIXIS_PROTOCOL_APPROVAL=as_proposed` (onay kartı değiştirilmeden onaylanır, kimse terim düzeltmez),
   `DEIXIS_SEARCH_QUERY=model`, `DEIXIS_FULLTEXT_FETCH=auto`, `DEIXIS_FULLTEXT_ADJUDICATION=auto`,
   `DEIXIS_CITATION_CHAINING=auto`, `DEIXIS_ARXIV_SOURCE=auto` (karar 12), `DEIXIS_CODEX_HOME` canlı veri dizinindeki
   oturum açılmış `codex-home`'u gösterir (satır 18b'nin dersi); `.env` anahtarları olduğu gibi. Veri dizinleri tazedir,
   Marker kurulu değildir (Marker veri dizinindeki `tools/`'a kurulur, `documents/math_reader.py:170`); önceki
   kampanyalarla aynı durum. Sıra: kuantum (`sw` `standard` r1, `legacy` r1, `quick`, `detailed`, gömmeli, `sw` `standard`
   r2, `legacy` r2), sonra tıp sorusu aynı sırayla; iki taraf araya girerek koşar ki saatin ve sağlayıcı durumunun etkisi
   bir tarafa yığılmasın. Araştırmalar arasında 2 dk ara.
4. **Model (B1).** `codex` / `gpt-5.6-luna` · reasoning medium, bütün roller. Neden: D88'in üç ölçümü ve dilim 14–18b'nin
   bütün canlı kabulleri bu modelle koştu; sayılar ancak aynı modelle yan yana konur. Aboneliktir, çağrı başına para
   yoktur. Ana planın §2.7'si ve K4 ölçüm modelini `deepseek-flash` · high diye yazıyor (Luna kotasının bittiği güne ait);
   22 Eylül'den beri her ölçüm Luna ile koştu ve DeepSeek bakiyesi bitti. Kampanya K4 satırını bu kararla günceller.
   **Durma kuralı:** bağlantının sağlığı (`adapter.health`, `models/adapter.py:115`) yalnız CLI'nin ve oturumun varlığını
   söyler, kotayı söylemez. Kota ilk gerçek model çağrısının sonucundan okunur: ilk araştırmanın ilk model adımı
   (etiketleme) bir kota ya da hız sınırı hatasıyla biterse kampanya durur, satır 24'e yazılır. Sonraki bir çağrıda kota
   biterse ya da bir koşu `model_call_failed` ile duraklarsa: `client_timeout` ise 10 dk sonra bir kez sürdürülür; kota ya
   da başka bir hata ise kampanya durur, nerede durduğunu yazar; yarım kalan araştırma sonuçlarda "yarım" diye durur. Başka modele ya da bağlantıya geçilmez (AGENTS.md).
   DeepSeek'e geçiş sahibin parasıyla ve ayrı bir kampanya olarak olur (Sahibin yapacağı 1).
5. **Sorular.** Metinler harfi harfine:
   - q1: `Which mathematical optimization models have been proposed for end-to-end entanglement distribution in quantum
     networks? Compare their decision variables, objectives, constraints, and treatment of routing, scheduling, memory
     capacity, fidelity, and decoherence. For each model feature, cite the supporting paper and state whether it was
     verified from the abstract or full text.` (Elicit'e 17 Eylül'de verilenle ve bütün önceki `sw` ölçümleriyle aynı.)
   - q-tre: `In adults with overweight or obesity, does time-restricted eating reduce body weight compared with
     unrestricted eating or usual diet? (randomised controlled trials)` (sahibin kararı, 26 Eylül 2026).
   **Tıp sorusu neden kalıyor.** Değiştirmeyi gerektiren somut bir neden bulunmadı. PICO'su açık, literatürü sınırlı,
   birden çok meta-analizi var, PubMed ağırlıklı ve yönlendirme onu PubMed'e götürmeli (sayı 8). İki bilinen risk ölçümün
   parçası sayılır, düzeltilmez: (i) parantezdeki İngiliz yazımı `randomised` bir sorgu bloğuna girerse Amerikan yazımlı
   kayıtları kaçırabilir; sözlük, model sorgusu ve sayımlar bunu gösterir, kampanya kaydeder; (ii) birçok deneme
   TRE'yi kalori kısıtlamasıyla karşılaştırır; ölçütün karşılaştırıcı parçası bunları ayırmalıdır, ayıramazsa bu bir
   ölçüt bulgusudur. Bizim metnimiz değişmez.
   DEIXIS bir meta-analiz yapmaz; yanıtın havuzlanmış etki büyüklüğü vermesi beklenmez.
6. **Referans kümeleri (D1).** Hiçbiri doğruluk ölçütü değildir; her biri "şunu kaçırdık mı" sorusunun bir listesidir.
   - **q1:** 31 eserlik set (`adjudication.jsonl`'da `confirmed_mathematical_model` ve `high`); kendi koşularımızdan
     türedi (SW3 Limits). Elicit'in 9'u ayrı liste.
   - **q-tre:** yayımlanmış meta-analizlerin **dahil ettiği** RCT'ler; aşağıdaki kural koşudan önce, yazıldığı gibi
     uygulanır ve her adımı deftere girer (Sol r1 bulgu 1, 4).
     1. **Sorgu.** PubMed E-utilities `esearch`, `db=pubmed`, `retmax=200`, `term` harfi harfine:
        `("time-restricted eating"[tiab] OR "time restricted eating"[tiab] OR "time-restricted feeding"[tiab] OR "time
        restricted feeding"[tiab]) AND ("meta-analysis"[pt] OR "meta-analysis"[ti] OR "meta-analyses"[ti]) AND
        ("2023/01/01"[edat] : "<kampanya günü>"[edat])`. Tarih alanı Entrez tarihidir (`edat`): PubMed'e girdiği gün;
        yayın tarihi (`dp`) gelecekteki sayı tarihlerini taşıyabildiği için kullanılmaz. `retmax` yalnız bir yanıtın
        döndürdüğü PMID sayısını sınırlar: `count` 200'ü aşarsa aynı sorgu `retstart` = 200, 400, … ile `count`'a
        ulaşılana kadar sorulur. Dönen PMID'lerin hepsi `esummary` ile okunur; sorgu, gün, `count`, sayfa sayısı ve PMID
        listesi deftere yazılır; toplanan PMID sayısı `count`'a eşit değilse durulur.
     2. **Sıra.** Entrez tarihine göre yeniden eskiye; aynı gün girenler büyük PMID önce.
     3. **Uygunluk, iki adımda (her aday için karar ve nedeni deftere).** Önce özetten (a)–(c); özet (a) ya da (b)'yi
        açıkça karşılamıyorsa aday elenir. Özet (c)'yi kararlaştıramıyorsa (TRE denemelerinin ayrılıp ayrılmadığını
        söylemiyorsa) aday **elenmez**: (c) de tablodan karar verilir. Geçen ya da (c)'si açık kalan aday için dahil
        edilen çalışmalar tablosu (adım 4'ün kaynağından) açılır ve (d)–(e), gerekirse (c), **tablodan** karar verilir;
        tablo açılamazsa aday `table_unavailable` olur. (a) Sistematik derleme ve en az bir
        havuzlanmış etki (meta-analiz); şemsiye derleme, ağ meta-analizi ve yalnız anlatı derlemesi değil. (b) Vücut
        ağırlığı havuzlanan sonuçlardan biri. (c) TRE denemeleri çalışma düzeyinde ayrılabiliyor: yalnız TRE'yi ya da
        TRE'yi alt grup olarak ayıran aralıklı açlık derlemeleri. (d) Tasarım: yalnız RCT havuzlayan ya da çalışma
        tablosunda her çalışmanın tasarımını veren derleme; tasarımı ayrılamayan karma derleme uygun değil
        (`design_not_separable`). (e) Nüfus: yetişkin; aşırı kilolu / obez olmayanları da içeren derleme, çalışma
        tablosu her çalışmanın nüfusunu (BMI ya da tanı) veriyorsa uygun, vermiyorsa değil (`population_not_separable`).
     4. **Tablo.** Dahil edilen çalışmalar tablosu (tablo, ek dosya ya da "included studies" listesi) PMC'deki açık tam
        metinden ya da yayıncının açık sayfasından okunur; adım 3'ün (d)–(e) kararı ve adım 5'in deneme listesi aynı
        tablodan gelir. Tablo açık değilse derleme `table_unavailable` diye deftere girer ve sıradaki adaya geçilir. **Kaynakça listesine geri dönüş yok:**
        bir makalenin kaynakçasında bulunmak dahil edilmiş olmak değildir. Üç tablo okunduğunda ya da 10 aday
        incelendiğinde durulur; üçten az tablo okunduysa küme o kadarla kalır ve başlıkta yazar.
     5. **Deneme kararı (her tablo satırı için).** Satır bir denemeye bir kez PubMed araması ile (başlık, ilk yazar, yıl ya
        da kayıt numarası) PMID ve DOI'ye çözülür. Karar ağacı, sırayla: randomize değil → dışarıda; yetişkin aşırı kilolu
        / obez değil → dışarıda; müdahale TRE değil (yalnız ADF, 5:2 ya da kalori kısıtlaması) → dışarıda; vücut
        ağırlığı raporlanmıyor → dışarıda; karşılaştırıcı kısıtsız yeme, olağan beslenme ya da aynı diyet danışmanlığı →
        **R**; karşılaştırıcı yalnız kalori kısıtlaması (iki kolda da aynı kısıtlama, TRE ek) → **karşılaştırıcı farklı**
        listesi; tablodan ve denemenin PubMed özetinden karar verilemiyor → **bilinmiyor** listesi. Her kararın tek
        cümlelik nedeni yazılır. Çözülemeyen satır (PMID yok) başlığıyla kalır ve eşlemesi yalnız başlıkla yapılır.
     6. **Birleştirme ve payda.** Üç tablonun R'ye giren satırları sözlüğün "referans birimi" kuralıyla tekil
        denemelere birleştirilir; |R| tekil deneme sayısıdır. "Karşılaştırıcı farklı" ve "bilinmiyor" ayrı raporlanır,
        paydaya girmez. **Bilinmiyor payı:** "bilinmiyor" tekil denemeleri, R ile "bilinmiyor"un toplamının %25'ini
        aşarsa Kapı 2 tıp sorusunda okunamaz. Gerekçe: dörtte birden fazlası belirsizken R'nin boyu Kapı 2'nin havuz
        payından fazla oynayabilir.
     Bu bir analist kümesidir (kampanya oturumu kurar, insan doğrulaması değil); başlığı `origin` ve `completeness`
     bunu, okunamayan tabloları ve "bilinmiyor" sayısını söyler. İstekler ürünün değil, kampanya betiğinin salt okunur
     istekleridir.
   Elicit'in listeleri referans kümesine eklenmez; ayrı karşılaştırılır (karar 7).
7. **Elicit karşılaştırması (C1).** Çalışma düzeyinde, cevap düzeyinde değil: kimin sonucunun doğru olduğu sorulmaz.
   Üç küme: Elicit'in dahil ettikleri (E), bizim her aşamadaki eserlerimiz (sözlükteki aşamalar) (D), referans küme (R).
   Eşleme ve birim düzeyinde sayım sözlükteki gibi. Yazılanlar: E∩D her aşamada; E∖D'nin her eseri için kaybın yeri (aramada yok, özet
   aşamasında kapsam dışı, N yüzünden okunmadı, getirme / okuma sınırı, PDF yok, ölçüt karşılanmadı, `include` ama atıf
   yok);
   D∖E'nin her `include` eseri için bizim doğrulanmış alıntımız (Elicit'in yanlış olduğu anlamına gelmez); E'nin R'ye
   göre durumu (R'de mi, "karşılaştırıcı farklı" listesinde mi, hiçbirinde mi).
   - **Kuantum Elicit dosyaları.** Kaynakları `~/Desktop/Elicit/` (iki CSV) ve `~/Documents/ChatGPT/Miscellaneous/`
     (rapor, arama günlüğü, tablo; 17 Eylül 2026). Plan oturumu beşini `.local/sw-slice24-plan-2026-09-26/elicit-quantum/`'a
     kopyaladı, yazmayı kapattı ve `SHA256SUMS` yazdı (iki CSV'nin özeti `968b5208…`, `e7e9e4b8…`). Kampanya kendi
     klasörüne yeniden kopyalar ve özetleri bu dosyayla karşılaştırır; tutmazsa durur. Git'e hiçbir Elicit dosyası girmez
     (`.local/` `.gitignore`'da, satır 8). Not: iki CSV'nin aynı baytları 17 Eylül'de `e3d6f26` commit'inde de var,
     ama o commit hiçbir dalda değil ve `main`'in geçmişinde yok.
   - **Tıp sorusunun Elicit tarafı (C1).** Elicit'in kümesi sayı 8'in beş çalışmasıdır; DOI'leri dışa aktarımda var,
     arama gerekmez. Dosyalar 26 Eylül'de, bizim hiçbir tıp araştırmamız açılmadan önce `elicit-tre/`'ye yazıldı ve
     özetlendi (`SHA256SUMS`: CSV `95211a49…`, cevap `287c16f2…`); kampanya kopyalar ve özetleri denetler, tutmazsa durur.
     Yani Elicit tarafı bizim koşumuzdan önce sabit; başka dışa aktarım beklenmez. **Ağırlığı:** beş eserlik, denetim izi
     olmayan küçük bir dış küme; "bunları bulduk mu" sorusuna iyi cevap verir, "neyi kaçırdık" sorusuna zayıf (neyi
     kaçırdığımızı asıl referans küme, karar 6, söyler). Sonuç bunu her tabloda söyler.
   - **Hangi eforumuz başlık sütunu.** Elicit iki soruda da "Balanced" ayarında koştu (kuantum:
     `elicit-quantum/Elicit quantum network optimization search 2026-09-17.md:4`, "Elicit Research Agent, Balanced";
     tıp: sahibin beyanı). Başlık sütunu **`standard`**'dır, çünkü bizim varsayılan eforumuzdur (`app.py:83`) ve Kapı
     2'nin eforudur; `quick` ve `detailed` yan sütunlarda durur. Bu bir sunum tercihidir: Elicit'in "Balanced"ının kaç
     kayıt taradığı ve kaçını tam metinden okuduğu bilinmiyor, bu yüzden iki tarafın eşit bütçeyle ya da eşit okuma
     derinliğiyle çalıştığı söylenmez. Karşılaştırma yalnız hangi eserlerin bulunduğu, elendiği, okunduğu ve dahil
     edildiğidir; cevabın derinliği, uzunluğu ya da sonucu karşılaştırılmaz.
   - **Kapsam farkı kayıp sayılmaz.** Her Elicit eseri, referans kümeyle aynı PICO kuralıyla, koşudan önce ve özetinden
     "kapsamda", "karşılaştırıcı farklı" ya da, özet karar vermeye yetmezse, **"belirsiz"** diye etiketlenir (Liu 2022 ve
     Jamshed 2022 için beklenen "karşılaştırıcı farklı"; etiket özetten doğrulanır). "Belirsiz" eser `include`
     karşılaştırmasına girmez, ayrı satırda yazılır. "Bulduk mu" beşinin hepsi için havuz düzeyinde sorulur. `include` karşılaştırması
     yalnız "kapsamda" olanlar için yapılır: "karşılaştırıcı farklı" bir eser bizde `criterion_not_met` olursa bu **kapsam
     farkıdır, kayıp değildir**; `include` olursa ölçüt bulgusudur (karşılaştırıcı parçası ayırmadı). Kuantumda da aynı
     ayrım: Elicit'in "Abstract only" dediği dört eserin bizde okunamaması erişim farkıdır.
8. **Dondurma ve Elicit'i görmenin etkisi.** Bu dosyanın "Dondurulmuş beklentiler" bölümü koordinatörün commit'iyle
   git'te donar; kampanya o commit'i doğrular (prompt). Koşudan önce kampanya klasöründe ayrıca donanlar: tıp referans
   kümesi, Elicit eserlerinin kapsam etiketleri, Elicit dosyalarının kopyaları, sorgu ve eşleme betikleri; her birinin sha256'sı deftere (`ledger.jsonl`) ilk
   araştırma çağrısından önce yazılır ve sonuçta tekrarlanır. Donmuş dosya koşudan sonra düzenlenmez; sapma sonuca
   yazılır. **Dondurmanın sınırladığı şey** DEIXIS'in sonucuna bakarak kümeyi, etiketleri ya da beklentiyi sonradan
   ayarlamaktır; Elicit'in cevabını ve meta-analiz seçimini görmüş olmanın yanlılığını gidermez. O yanlılığı karar 6'nın
   harfi harfine sorgusu ve karar ağacı sınırlar; okunamayan tablo `table_unavailable`, karar verilemeyen deneme
   "bilinmiyor" kalır, tahminle doldurulmaz (Sol r1 bulgu 4). **Elicit cevabını görmek neyi etkiler:** bizim arama, tarama ve yanıtımızı etkilemez; onları model ve kod
   yapar, protokol değiştirilmeden onaylanır, sahip ve analist hiçbir terimi, ölçütü ya da kararı değiştirmez. Etkilenmesi
   mümkün olanlar: (i) bu plandaki beklentiler; Elicit'in beş eseri için beklenti ayrı ve açık yazıldı, referans kümesi
   Elicit'ten değil kuraldan kurulur ve Elicit'in eserleri, kuralı geçmedikçe ona eklenmez; (ii) Elicit eserlerinin kapsam
   etiketi ve karar 10'un analist okuması; etiketleyen ve okuyan Elicit'in cevabını bilir, kör değildir, bu sonuçta
   yazılır; (iii) sahibin sonucu okuması. Sahibe göre Elicit'e tam olarak bizim sorumuz yazıldı (dosyalarda soru metni
   yok; bu sahibin beyanıdır).
9. **Ölçüm yöntemleri.**
   - **Aşama sayıları** sözlüğün tanımlarıyla (`sw-measure-2026-09-24/quality.py`'nin yöntemi, "tam metne
     yönlendirilen" aşaması eklenmiş), her referans küme için ayrı.
   - **Kol ve sinyal:** `scripts/probe_report.py <library> <reference.jsonl>` her `sw` araştırması için.
   - **Kaçırılan eser teşhisi:** havuza girmeyen her referans eser için (i) OpenAlex'te DOI ile var mı, (ii) araştırmanın
     saklı her OpenAlex sorgusu onu kapsıyor mu (`SEARCH_PARAM` = sorgu, `filter=doi:<doi>`, `per_page=1`; sonuç 1 ise
     sorgu eseri bugün kapsıyor ama okunan sayfalarda yoktu; 0 ise sorgu onu bugün kapsamıyor). Sonuç "bugün" diye
     yazılır (sözlük); OpenAlex'in dizini koşudan sonra değişmiş olabilir. Eser başına en çok sorgu sayısı kadar istek, 1 sn aralıkla, ürünün User-Agent'ıyla, anahtar kayda
     yazılmadan. PubMed'de de aynı soru `term=<sorgu> AND <PMID>[uid]` ile sorulur.
   - **K3 ve açık erişim fikri:** `k3_oa.py`'nin üç ölçüsü, her referans küme için.
   - **Süre, çağrı, jeton:** `cost_time.py` ve `sw-measure-2026-09-24/stages.py`'nin aşama yöntemi. Para: B1'de yok;
     B2'ye geçilirse jeton × DeepSeek'in o günkü fiyat sayfası, tarihiyle.
   - **Kuyruk:** API'nin `queue_counts`'u ve satırları (`GET` kuyruk uç noktası) ile `queue.txt`'nin sürüm düzeyindeki
     sayımı yan yana; PDF bekleyen liste boyu.
   - **Europe PMC (E1):** kurulmadı, ölçülemez. Yerine: tıp referans kümesinin ürünün PDF bulamadığı her eseri için
     Europe PMC REST API'sine salt okunur tek istek ("bu eserin PMC'de açık tam metni var mı"); sayı, Europe PMC tam metin
     kaynağının getireceği kazancın üst sınırıdır. Kazanç varsa yeni SW girişi olur.
10. **İnsan rolü (I1).** Kampanya boyunca kuyruğa kimse cevap vermez; ürünün prob seti boş kalır, bu beklenen şeydir. Onun
    yerine kampanya oturumu her soruda, gömmesiz `sw` `standard`'ın iki koşusunun birleşiminden, deftere yazılı bir
    tohumla 10 `include` kararı, 10 `criterion_not_met` kararı ve 10 atıflı iddia çeker; ayrıca `legacy` `standard`'ın iki
    koşusundan 10 atıflı iddia. Birim tekildir: iki koşuda da `include` olan iş bir kez sayılır (r1'in kararı okunur);
    iddia, yanıt başına bir iddia metni ve çapası. Her birini PDF sayfasında ve saklı alıntı / çapayla okur ve
    `analyst-reading.jsonl`'a bir satır yazar: birim, koşu, sayfa, alıntı ya da çapa, hüküm, ciddi mi, tek cümlelik
    gerekçe. Karar için "ölçüt parçaları alıntılarla karşılanıyor / karşılanmıyor (hangi parça)", iddia için "çapalı pasaj
    iddiayı söylüyor / söylemiyor" yazılır. **İkinci okuma:** "ciddi" işaretli her birim ve her soruda tohumla çekilmiş 5
    ciddi olmayan birim, ilk hükmü görmeyen ayrı bir model oturumunca yeniden okunur; iki hüküm de satıra yazılır. İki
    okuma bir birimin ciddi olup olmadığında ayrılırsa birim ciddi sayılır ve ayrılık listelenir (varsayılanı değiştirecek
    kapı için tutucu yön). Ciddi hatanın tanımı Kapı 4'tedir. Bu **analist okumasıdır**, insan doğrulaması değil
    (AGENTS.md "Evidence Contract"); iki okuyucu da model, ilki kör değil.
11. **Varsayılan kapıları (F1).** Kampanyadan önce dondurulur; sonuç kapılara göre okunur (Sol r1 bulgu 2, 3):
    - **Kapı 1, tamamlanma:** 10 `sw` araştırmasının hepsi keşif → getirme → okuma → yanıta kadar biter ve yanıt
      `structurally_valid`; karar 4'ün izin verdiği tek sürdürme dışında elle müdahale yok.
    - **Kapı 2, iş akışı karşılaştırması (`legacy`'den geri kalmama).** K8'den ayrı bir kuraldır: K8 bir koşuyu önceki
      koşusuyla kıyaslar, bu kapı iki iş akışını aynı soruda kıyaslar. Her soruda iki taraf da `standard`'da iki kez koşar
      (karar 3). Kapı yalnız dört koşunun dördü de yanıtıyla bittiyse okunur; biri bile bitmezse o soruda okunamaz.
      İki ölçü, her tarafın iki koşusunun ortalaması (sözlük):
      - *havuzdaki* R birimi: `sw` ≥ `legacy` − d_havuz, d_havuz = en büyüğü (2, ⌈0,1 × |R|⌉) (kuantumda 4). Gerekçe:
        havuz sayısı büyük (saklı `sw` `standard` koşularında 31'in 27–30'u) ve iki koşunun kendi arasında 1–3 oynaması
        beklenir (dondurulmuş beklenti); pay bu oynamanın biraz üstünde ve R'nin onda biri.
      - *atıf alan* R birimi: `sw` ≥ `legacy` − 1 **ve** `legacy`'nin ortalaması 1 ya da daha çoksa `sw`'nin iki koşusunun
        ikisinde de en az bir R birimine atıf var. Gerekçe: atıf sayıları seyrek (saklı `standard` yanıtlarında 4–5,
        `detailed`'da 0–7); havuz payı burada `sw`'nin sıfır atıfla geçmesine izin verirdi.
      |R| < 10 ya da karar 6'nın bilinmiyor payı %25'i aşarsa kapı o soruda okunamaz. Okunamayan kapı geçmemiş sayılır.
      Bu, iki koşuya dayanan betimleyici bir karar kuralıdır; istatistiksel bir "geri kalmama" (non-inferiority) sınaması
      değildir ve sonuç öyle sunulmaz. Sınır: kuantumun R'si kendi OpenAlex tabanlı koşularımızdan türedi (SW3 Limits);
      iki akış da OpenAlex'i aradığı için bu yanlılık bir tarafa yüklenmez ama sıfır da değildir.
    - **Kapı 3, kanıt bütünlüğü:** hiçbir `sw` yanıtında çözülemeyen alıntı bağı ya da bulunamayan çapa yayımlanmadı; hiçbir
      adımda `model_isolation_violation` yok; `model_mismatch` çıktısı kullanılmadı.
    - **Kapı 4, analist okumasında ciddi hata** (karar 10'un örneği). Ciddi PICO / ölçüt hatası: çekilen bir `include`
      kararının kendi saklı alıntıları ve sayfaları, işin bir ölçüt parçasını karşılamadığını gösteriyor (tıpta:
      randomize değil, nüfus yetişkin aşırı kilolu / obez değil, müdahale TRE değil ya da karşılaştırıcı yalnız kalori
      kısıtlaması; kuantumda: bir optimizasyon modeli kurulmamış ya da uçtan uca dolanıklık dağıtımı değil). Ciddi
      iddia–pasaj hatası: çekilen bir atıflı iddianın çapalı pasajı iddiayı söylemiyor, tersini söylüyor ya da başka bir
      eser veya sürüme ait. Asgari örnek: her soruda en az 8 tekil `include` ve en az 8 tekil iddia; daha azı varsa kapı
      o soruda okunamaz ve geçmemiş sayılır. Kapı, her soruda çekilen `include`'larda en çok 1 ciddi PICO hatası **ve**
      çekilen iddialarda en çok 1 ciddi iddia–pasaj hatası varsa geçer (karar 10'un ikinci okuma kuralıyla); 2 ya da daha
      fazlası 24b'yi durdurur. `criterion_not_met` örneği ve `legacy` iddiaları raporlanır, kapıya girmez.
    Dördü de geçerse 24b koşar ve varsayılan `sw` olur. Biri geçmezse varsayılan `legacy` kalır, nedeni SW girişi olur,
    D105 24a'nın sonunda yazılır ve satır 24 `24a bitti; kapı N geçmedi; sahip kararı bekliyor` yazar ("24a bitti"
    kaldığı için istem Part A'yı yeniden koşmaz). Kapıya girmeyen, yalnız raporlanan: efor süreleri (10 / 15 / 20 dk; D88:
    hedef, sınır değil), PubMed kolunun yönlendirilip kayıt getirmesi, kuyruk boyu ve PDF bekleyen liste. Sonuç bunları
    kapıların yanında yazar; sahip bunlardan biri yüzünden 24b'yi durdurabilir.
12. **arXiv kaynağının varsayılanı (G1).** Kuantum koşularında bayrak `auto`. Kural (Sol r1 bulgu 7), ikisi birden:
    (a) yerleşen blokların web uygulamasının KaTeX 0.16.47 kopyasında çizilemeyeni **0**; tek bir çizilemeyen blok
    varsayılanı `off` bırakır (listeleyip geçmek yok). (b) Yerleşen bloklardan deftere yazılı tohumla, makale başına en
    çok 2, dilim 22'nin kabul örneklemindeki makaleler hariç 40 blok çekilir, bölgesi çizili sayfa görüntüsünden okunur.
    Bu koşullarla 40 uygun blok çıkmazsa kural okunamaz ve hüküm `off`'tur.
    Yanlış = basılı denklem yerleşen LaTeX'le aynı grup değil, ya da bölge denklem olmayan bir metin satırını siliyor.
    En çok 1 yanlış geçer; tam 1 yanlış varsa o makalenin öbür bütün yerleşmeleri (en çok 10) da okunur ve ikinci bir
    yanlış kuralı düşürür. Kapıya girmeyen, raporlanan: eşiği geçip yerleşmeyen blokların nedenlere göre sayısı ve
    bunlardan 20'sinin okunması, eşleşmeyen numaralı denklem sayısı, yanlışların makalelere dağılımı. Tutarsa 24b
    `arxiv_source`'un varsayılanını `auto` yapar (`config.py:54`, `:132`); tutmazsa `off` kalır ve nedeni SW girişi
    olur. Okuyan bir model oturumudur (plan yazarından başka), tek okuyucu. Sınır: dilim 22'nin 40 / 40'ı gibi bu da aynı
    makinede, benzer arXiv makalelerinde bir kabul kanıtıdır; genel bir güvenilirlik sınırı değildir.
13. **Kesinti, sürdürme ve yeniden başlatma.** Part A yarıda durursa (kota, `model_call_failed`, makine) satır 24
    `24a durdu: <nerede>` yazar. **Etkin klasör:** klasörün yolu ve `protocol.md`'deki plan commit'i `.local/sw-slice24-active`
    dosyasına (tek satır) yalnız bir yerde, dondurmanın sonunda `protocol.md` yazıldıktan sonra yazılır; sürdürme denetimi yalnız bu dosyanın gösterdiği klasöre
    uygulanır, başka `sw-slice24-campaign-*` klasörü hiç okunmaz; yeniden başlatma her zaman adı daha önce olmayan yeni bir klasör açar (`sw-slice24-campaign-<tarih>-<saat>`) ve dosyayı ona ancak yeni klasörün `protocol.md`'si yazıldıktan sonra taşır; işaretçi taşınmadan önceki bir çökmede işaretçi ya yoktur (Part A baştan koşar) ya da eski klasörü gösterir; o durumda eski klasör için sürdürme ya da yeniden başlatma denetimi yeniden yapılır.
    Dosya yoksa ya da gösterdiği klasörde `protocol.md` yoksa Part A baştan koşar. Süreç `24a durdu` yazamadan çökerse
    satır `uygulanıyor (24a)` kalır; sonraki koşu bunu da kesinti sayar, etkin kampanya klasörünün `ledger.jsonl`'ının ve `log-*.md`'lerinin son kaydından nerede durduğunu bulur
    ve aynı kuralı uygular. Sonraki koşu **aynı donmuş protokolle sürdürür**: aynı kampanya klasörü; donmuş her
    dosyanın özeti yeniden hesaplanır ve `protocol.md`'dekiyle aynı olmalıdır; ürün kodu (`backend/`, `apps/web/`,
    `contracts/`, `methods/`) `protocol.md`'deki commit'ten beri değişmemiş olmalıdır (`git diff --stat <commit> --` o
    yollarda boş). Bitmiş araştırmalar kalır; duraklatılmış araştırma ürünün kendi sürdürmesiyle bir kez sürdürülür;
    yarıda çöken araştırma yeni bir veri dizininde baştan koşar ve eski dizini "yarım" diye saklanır. Özet ya da kod
    koşulu tutmazsa **yeniden başlatma**: yeni bir kampanya klasörü, yeni `protocol.md` ve dondurma; eski klasör olduğu gibi
    kalır ve sonuç ikisini de anar. Kapı başarısızlığı bir kesinti değildir: 24a biter (karar 11).
14. **Sonucun yeri.** Ham veri `.local/sw-slice24-campaign-<tarih>-<saat>/` (izlenmez). İzlenen sonuç
    `docs/product/sw-slice24-results.md` (Türkçe): kısa özet, beklentiyle yan yana tablolar, kapıların hükmü, her
    ölçülmeyen şey. Değişmesi gereken her eşik ya da kural `search-workflow-review-2026-09-18.md`'ye yeni bir SW girişi
    olur (en yüksek bugün SW17, yani SW18'den başlar); girişte bulgu, sayı, hangi dilime dönüleceği. Satır 24, K4 ve K5
    satırları güncellenir. D105 24b'de yazılır (kapılar geçmezse 24a'nın sonunda, "varsayılan `legacy` kalır" diye).
    Bulunmuş iki kod eksiği (etiketleme eşiklerinin `thresholds`'a yazılmaması, kullanılmayan `routing.THRESHOLDS`)
    SW girişi olarak yazılır; 24b'de düzeltilir (küçük, davranışı değiştirmez, protokol gövdesine iki alan ekler).
15. **Güvenlik.** Port 8765 ve canlı kütüphaneye dokunulmaz (canlı veri dizininden yalnız `codex-home` kullanılır, karar
    3). Her sunucu kendi veri dizini ve portuyla; bitince durdurulur. Anahtarlar deftere, günlüğe ve sonuca yazılmaz.
    Kampanya hiçbir şeyi commit'lemez.

## SW10'dan ve ana plandan sapmalar

1. **Europe PMC kolu denenmez** (ana plan: "PubMed ve Europe PMC kolları da denenir"): Europe PMC kurulmadı. Yalnız
   PubMed ve bioRxiv yönlendirmesi denenir; Europe PMC'nin tam metin kazancı karar 9'daki salt okunur sayımla tahmin edilir
   (E1).
2. **SW10'un açık erişim fikri yarım ölçülür:** "kod kapısını tam metinde koş" yarısı dilim 23'e bağlıdır ve kurulmadı;
   kampanya fikrin kazanabileceği ve kaybettirebileceği eserleri sayar, ürünü değiştirmez.
3. **Ölçüm modeli** ana planın §2.7'si ve K4'teki `deepseek-flash` · high değil, Luna · medium (B1).
4. **Tekrar:** ana plan dağılımdan söz etmiyor. Kampanya yalnız Kapı 2'nin iki hücresini, her iki tarafta ve sonuca
   bakmadan, iki kez koşar (karar 3); başka tekrar yok. İki koşu bir dağılım göstermez; sonuç bunu her tabloda söyler.

## Sahip kararları (26 Eylül 2026: A1, B1, C1, D1, E1, F1, G1, H1, I1 önerildiği gibi)

Sahip soru sorulmadan ilerlenmesini istedi; öneriler kabul edilmiş sayılır. Seçenekler kayıt için duruyor.

- **A — Kampanya matrisi.** Öneri **A1**: iki soru × üç efor `sw`, her soruda `standard`'da gömmeli bir `sw` ve bir
  `legacy`; gömmesiz `sw` `standard` ve `legacy` `standard` baştan iki kez, araya girerek; başka tekrar yok (karar 3;
  Sol r1'den sonra "tartışmalıysa tekrar" kuralının yerine geçti). *A2*: yalnız `standard`; ucuz, ama efor sınırlarını ve
  süre hedeflerini ölçmez. *A3*: her hücre iki kez; dağılım verir, süre ve çağrı iki katı.
- **B — Model.** Öneri **B1**: Luna · medium (karar 4). *B2*: `deepseek-flash` · high (K4'ün yazılı hâli): parayla,
  bakiye 22 Eylül'de bitmişti, sayılar D88'in üç ölçümüyle karşılaştırılamaz, çıktı jetonu çağrı başına ~10 bin.
- **C — Tıp sorusunda Elicit tarafı.** Öneri **C1**: sahibin 26 Eylül'de verdiği beş eserlik tablo, bizim koşumuzdan
  önce özetlenip dondurulmuş hâliyle Elicit'in kümesidir; küçük ve denetim izsiz olduğu için "bulduk mu" sorusunda
  kullanılır, "neyi kaçırdık" sorusunu referans küme cevaplar; karşılaştırıcısı farklı eser kapsam farkı sayılır;
  Elicit'in "balanced" ayarının karşılığı bizim `standard`'ımızdır ve karşılaştırma eser düzeyindedir (karar 7). *C2*: kuantumdaki gibi sorgu ve iş akışı dökümü de istenir; sahip böyle bir dışa aktarımın gelmeyeceğini
  söyledi.
- **D — Tıp referans kümesi.** Öneri **D1**: harfi harfine PubMed sorgusu, Entrez tarihine göre sıra, özetten uygunluk,
  açık dahil edilen çalışmalar tablosu okunabilen en yeni üç meta-analizin PICO karar ağacından geçen RCT'leri; kaynakça
  listesine geri dönüş yok (karar 6). *D2*: dış küme yok, yalnız Elicit ve kendi kararlarımız; Kapı 2 tıp sorusunda okunamaz hâle gelir.
- **E — Europe PMC.** Öneri **E1**: kurulmadı diye yazılır, kazancı salt okunur sayımla tahmin edilir (karar 9). *E2*:
  önce bir Europe PMC dilimi (arama kolu ve tam metin kaynağı), sonra kampanya; ölçülmemiş yeni kodu ölçümün içine
  koyar ve kampanyayı geciktirir.
- **F — Varsayılan kararı.** Öneri **F1**: dondurulmuş dört kapı: tamamlanma, iş akışı karşılaştırması (iki koşu, d
  payı), kanıt bütünlüğü, analist okumasında ciddi hata (karar 11). *F2*: sahip sonucu okuyup karar verir; 24b
  sahibin cevabını bekler.
- **G — arXiv kaynağının varsayılanı.** Öneri **G1**: karar 12'nin kuralı (KaTeX'te çizilemeyen 0; 40 blokta en çok 1
  yanlış, yanlışın makalesi ayrıca okunur). *G2*: sonuç ne olursa olsun `off`.
- **H — Açık uçlar.** Öneri **H1**: karar 2. *H2*: dördü de `kapandı` olmadan kampanya başlamaz; 17'nin son kontrolü
  kampanyayı gereksiz yere bekletir.
- **I — İnsan rolü.** Öneri **I1**: kuyruğa kimse cevap vermez, analist örneği (karar 10). *I2*: sahip denetim örneğini
  cevaplar (sahibin zamanı; Sahibin yapacağı 2'de isteğe bağlı).

## Sahibin yapacağı

Bunlar soru değil; sahibin eli, hesabı ya da parası gerekiyor. Tıp sorusunun Elicit dosyaları geldi (sayı 8); başka
dışa aktarım istenmiyor.

1. **Yalnız Luna kotası yoksa:** kampanyanın ilk gerçek model çağrısı (karar 4) kota hatasıyla biterse sahip ya kotanın
   yenilenmesini bekler ya da DeepSeek bakiyesini yükleyip B2'yi ayrı bir kampanya olarak açar (para). Tahmini DeepSeek
   jetonu tahmin bölümünde.
2. **İsteğe bağlı:** karar 12'nin 40 görüntüsünü ya da karar 10'un örneğini sahibin kendisinin okuması; okursa sonuç
   "insan okuması" diye ayrı yazılır. Okumazsa kampanya analist okumasıyla biter.

## Maliyet ve süre tahmini

**Tahmin**, ölçüm değil; kaba bir planlama sayısıdır (Sol r1 bulgu 8). Sayı 1'in dilim 15 sonrası kuantum aralıklarından,
tıp sorusu kuantumla aynı büyüklükte varsayılarak. Ölçülmeyen ve sayıyı değiştirebilecekler: tıp sorusunun havuz ve
okuma büyüklüğü, PubMed'in hızı, iki ayrı yerleşik gömme kurulumu (her soruda bir veri dizini), ilk çağrıda kota. `sw`
gömmesiz araştırma başına: `quick` 67–71 çağrı ve 13–14 dk, `standard` 111–125 çağrı ve 20–25 dk, `detailed` 292–320
çağrı ve 42 dk. Gömmeli `standard` gömmesizle aynı sayıda model çağrısı, üstüne yerel gömme ve kurulum. `legacy`
`standard`: 3–28 çağrı ve ~2–10 dk (eski koddan). Soru başına 7 araştırma, 698–822 çağrı; toplam 14 araştırma:
yaklaşık **1.400–1.650 model çağrısı**, **14–18 M giriş ve 1,1–1,5 M çıkış jetonu**, aralarla birlikte **~4,5–5,5 saat**
koşu, art arda. Luna'da para yok, haftalık kotadan düşer. B2'ye geçilirse DeepSeek'te aynı çağrı sayısı ~13–15 M giriş ve
~14–16 M çıkış jetonu eder (çıkış çağrı başına ~10 bin, sayı 1); para, o günkü fiyat sayfasından hesaplanır. Referans
kümenin kurulması, ölçüm, analist okuması ve sonuç yazımı ayrıca bir ya da iki oturum.

## Dondurulmuş beklentiler

Bu bölüm koordinatörün commit'iyle donar. Dayanak sayı 1–8'dir; "dayanağı zayıf" yazan satırın saklı bir karşılığı yok.

**Kuantum (q1), gömme kapalı `sw`:**

- Süre: `quick` 9–14 dk, `standard` 16–25 dk, `detailed` 38–46 dk; `standard` ve `detailed` hedefleri (15, 20) tutmaz.
- 31'lik set: havuz `quick` 19–26, `standard` 27–30, `detailed` 28–30; özette aday 13–22 / 20–24 / 21–26; okunan
  1–9 / 7–8 / 17–19; `include` 1–7 / 5–7 / 11–13; atıf alan 0–3 / 4–5 / 0–7.
- K3: N yüzünden okunmayan set eseri 4–6 / 6–9 / 4–5. SW10 fikri: model açık erişimli bir set eserini kapsam dışı saymaz
  (0); N yüzünden okunmayan açık erişimli set eseri 1–3.
- Elicit'in 9'u: havuzda 6–9 / 9 / 9; okunan 1–2 / 1–2 / 5; `include` 0–1 / 1–2 / 2–3; atıf alan 0–1 / 0–2 / 1–2.
  Elicit'in "Abstract only" dediği 4 eserden hiçbiri `include` olmaz (3'ü defterimizde erişilemez, 1'i formülasyonsuz).
  E∖D'de havuzda olmayan eser `standard` ve `detailed`'da 0.
- Çağrı: 60–80 / 105–130 / 280–330. Kuyruk (sürüm düzeyi): 7–17 / 25–30 / 90–105, `standard` ve `detailed`'da çoğu
  `part_without_evidence`. PDF bekleyen: 27–65 / 55–60 / 165–175.
- arXiv araması sıfır kayıt getirir (`rate_limited`); önceki bütün ölçümlerde öyleydi.
- arXiv kaynağı (G1): yerleşen blok var; KaTeX'te çizilemeyen 0 (dilim 22 kabulünde 776 blokta 0); görüntüden
  okumada en çok bir yanlış; 40 uygun blok çıkar; G1 tutar.
- Gömmeli `standard`: havuz gömmesizle aynı; kurtarma kolu özet aşaması sırasına 0–2 set eseri ekler (**dayanağı zayıf**).
- `legacy` `standard` (iki koşu): havuzda 31'lik setten `sw` `standard`'dan az, atıf alanda benzer (**dayanağı zayıf**;
  bugünkü `legacy` ölçülmedi). `sw` `standard`'ın iki koşusu arasındaki fark havuzda en çok 3, atıf alanda en çok 3.
- Analist okuması: 10 `include`'da ciddi ölçüt hatası 0–1, 10 iddiada ciddi iddia–pasaj hatası 0–1 (**dayanağı zayıf**;
  `include` kararlarının ve atıflı iddiaların doğruluğu daha önce hiç okunmadı).

**Tıp (q-tre):**

- Yönlendirme: PubMed ve bioRxiv seçilir, arXiv ve IEEE dışarıda kalır (sayı 8'in benzeri); PubMed'in en az bir sayfası
  kayıt getirir. Europe PMC aranmaz.
- Referans küme: üç tablo okunur, |R| 10–40 (**dayanağı zayıf**; meta-analizler seçilmedi); `standard` havuzda
  |R|'nin %70–95'i (**dayanağı zayıf**); kayıp çoğunlukla okuma sınırında ve PDF'te olur, aramada az (kuantumdaki desen).
- Analist okuması: ciddi PICO hatasının en olası yeri karşılaştırıcıdır (kalori kısıtlamalı denemenin `include`
  olması); 10 `include`'da 0–1 (**dayanağı zayıf**).
- Elicit'in beş eseri: havuzda `standard` ve `detailed`'da 4–5 (Wilkinson 2026 çok yeni olduğu için dizinde
  olmayabilir), `quick`'te 3–5. Kapsam etiketi: Lin 2023 ve Cienfuegos 2020 "kapsamda" (Elicit'in cevabına göre kontrol
  kolu var), Liu 2022 ve Jamshed 2022 "karşılaştırıcı farklı", Wilkinson 2026 özetinden karar verilir. "Kapsamda"
  olanlar okunursa `include`. Liu 2022 ve Jamshed 2022 okunursa `criterion_not_met` ya da `unresolved` (kapsam farkı);
  `include` çıkarsa ölçüt bulgusu. Referans kümede Lin 2023 ve Cienfuegos 2020'nin bulunması beklenir (2023 sonrası
  meta-analizlerin kapsadığı denemeler; **dayanağı zayıf**).
- Aranan şey (TRE ve vücut ağırlığı) ölçütte kalır; karşılaştırıcı bir ölçüt parçasıdır. `randomised` bir sorgu bloğuna
  girerse Amerikan yazımıyla kaçan kayıt olur (**dayanağı zayıf**).
- Süre ve çağrı kuantumun ±%30'u; açık erişim payı kuantumdan yüksek, PDF bekleyen payı düşük (**dayanağı zayıf**).
- Kuyruk: `part_without_evidence` kuantumdan az, `fulltext_runs_disagree` karşılaştırıcı yüzünden çok (**dayanağı zayıf**).
- Europe PMC sayımı: ürünün PDF bulamadığı referans eserlerin bir kısmının PMC'de açık tam metni var (**dayanağı zayıf**).

**Kapılar:** 1, 2, 3 ve 4 geçer; 24b koşar.

## Global constraints

- **Ürün kodu 24a'da değişmez.** Kampanya betikleri yalnız `.local/sw-slice24-campaign-<tarih>-<saat>/` altında; `scripts/`'e
  bir şey eklenmez.
- **Kimse karar vermez.** Onay kartı olduğu gibi (`as_proposed`); kuyruk cevapsız; terim, ölçüt, seçim düzeltilmez.
- **Referans küme doğruluk değildir, Elicit doğruluk değildir.** Sonuç "kaçırdık", "bulduk", "ikisi de" der; "doğru" ya
  da "yanlış" demez. Listede olmayan bir `include` yanlış sayılmaz.
- **Sayılar ayrı** (sözlük): bulunan, tekil, havuz, özette aday, tam metne yönlendirilen, planlanan, PDF'i olan, okunan, `include`, atıf alan,
  kuyrukta, PDF bekleyen.
- **Her sayı** örnek büyüklüğü, makine ve model ile yazılır; tek koşu tek koşu diye yazılır.
- **Model değişmez,** sessiz geri dönüş yok (karar 4).
- **8765 ve canlı kütüphane yok;** ayrı veri dizini ve port.
- **Donmuş dosya düzenlenmez;** sapma sonuca yazılır.
- **Hiçbir Elicit dosyası ve hiçbir kütüphane git'e girmez.**
- **24b:** davranış değişikliği yalnız varsayılanlar (`search_workflow`, G1'e göre `arxiv_source`) ve karar 14'ün iki
  küçük düzeltmesi; migration yok; `skill_package_hash` değişmez.

## Task taslağı

**24a — kampanya**

1. **Satırlar** (karar 2): 18a, 18b, 19 `kapandı` (nedenleriyle); 17 "24b'den önce son kontrol" notu; satır 24
   `uygulanıyor (24a)`.
2. **Hazırlık:** kampanya klasörü; bu dosyanın commit'i doğrulanır; Elicit kuantum kopyaları ve `SHA256SUMS` denetimi;
   `ledger.jsonl`; model bağlantısının `health`'i (kota ilk gerçek çağrıda okunur, karar 4).
3. **Tıp referans kümesi** (karar 6): harfi harfine sorgu ve dönen PMID listesi; sıra; her adayın uygunluk kararı;
   okunan tablolar ve `table_unavailable` olanlar; her tablo satırının karar ağacı sonucu; `reference-tre.jsonl`
   (başlık `origin`, `completeness`, okunamayan tablolar, "bilinmiyor" sayısı), `comparator-differs-tre.jsonl`,
   `unknown-tre.jsonl`; kuantum için `reference-q1.jsonl` (31 eser) ve `elicit-q1.jsonl` (9). Özetler deftere.
4. **Elicit tıp tarafı** (karar 7): `elicit-tre/` kopyası ve `SHA256SUMS` denetimi; beş eser `elicit-tre.jsonl`'a (DOI,
   NCT, başlık) ve her birinin kapsam etiketi, özetinden ve karar 6'nın PICO kuralıyla, nedeniyle birlikte. Özetleri
   almak için beş DOI'ye birer salt okunur Crossref ya da PubMed isteği.
5. **Betikler ve dondurma:** önce görev 7'nin bütün ölçüm betikleri yazılır ve plan oturumunun saklı bir kütüphanesinde
   (ör. `sw-slice17a-acceptance-2026-09-24/data-q1-standard-luna`) bir kez koşturulup çalıştığı görülür; sonra
   `protocol.md` (bu dosyanın beklentilerine atıf, commit hash'i, bütün donan dosyaların ve betiklerin özetleri, sunucu
   ortamı, durma ve sürdürme kuralları, tohumlar). İlk araştırma çağrısından önce. Dondurmadan sonra bir betiğe dokunmak
   sapmadır ve sonuca yazılır.
6. **Koşular** (karar 3): kuantum yedi araştırma, sonra tıp yedi araştırma, karar 3'ün sırasıyla; her biri kendi
   sunucusunda. Her araştırmadan
   sonra görünüm, PRISMA-S dökümü, kuyruk satırları, akış kutuları JSON olarak saklanır.
7. **Ölçüm** (karar 9, 10, 12): aşama tabloları, `probe_report.py`, kaçırılan eser teşhisi, K3 / açık erişim, süre ve
   jeton, kuyruk, Europe PMC sayımı, Elicit karşılaştırması, analist örneği, arXiv kaynağı sayıları ve 40 görüntü.
8. **Kapılar** (karar 11): dört kapının hükmü, sayılarıyla; ek koşu yok.
9. **Sonuç:** `docs/product/sw-slice24-results.md`; yeni SW girişleri; satır 24 (`24a bitti; dört kapı geçti` ya da
   `24a bitti; kapı N geçmedi; sahip kararı bekliyor`), K4, K5; kapı geçmediyse D105 (`docs/decisions.md`).

**24b — varsayılan ve kapanış** (yalnız dört kapı geçtiyse ve satır 17 `kapandı` ise)

10. `search_workflow` varsayılanı `sw` (`config.py:28`, `:114`); G1 tuttuysa `arxiv_source` `auto` (`config.py:54`,
    `:132`). Varsayılanı sınayan testler ve onları bekleyen fikstürler güncellenir; `legacy` araştırması açık kalır
    (bayrak araştırmada saklı, ana plan §2.1).
11. Karar 14'ün iki düzeltmesi: etiketleme eşikleri `vocabulary.THRESHOLDS`'a; `routing.THRESHOLDS` silinir ya da
    `route()` onu okur. Protokol gövdesi testleri buna göre.
12. Belgeler: README (akışın kısa anlatımı ve `DEIXIS_SEARCH_WORKFLOW`; ayrıca `README.md:238`'deki eskimiş "Real model
    execution, evidence review and production persistence are not implemented" cümlesi bugünkü duruma göre düzeltilir), CLAUDE.md (Runs and steps: `sw`'nin koşu
    türleri ve varsayılan), `docs/README.md:17-18` (SW belgesinin durumu), `implementation-plan.md` §9'a `sw` geçişinin
    bir satırı; `search-workflow-review-2026-09-18.md`'de her SW girişinin durum satırı.
13. D105 (varsayılan, kapıların sonucu, sapmalar, Limits) ve kalan SW maddeleri: her SW girişinin durum satırı okunur;
    bir D'ye taşınmamış uygulanmış madde kapanış D'sine yazılır, uygulanmamış madde "açık" listesine.
14. Sınamalar: tam pytest (bilinen tek hata ayrı), `npm run build`, `npm run lint`, Playwright A–O, `git diff --check`.
    Satır 24 `uygulandı, inceleme bekliyor (24b)`.

## Kabul koşulları

- 24a: 14 araştırmanın her biri için yazılı sonuç (bitmediyse nerede durduğu); karar 9'un her ölçüsü iki soruda ya
  da neden yapılamadığı; beklentiyle yan yana tablo; kapıların hükmü; donan dosyaların özetleri deftere ilk
  araştırmadan önce yazılmış; hiçbir ürün dosyası değişmemiş (`git status` yalnız belgeleri ve sahibin üç dosyasını
  gösterir); 8765 kullanılmamış.
- 24b: yukarıdaki sınamalar; varsayılan `sw` ile yeni araştırma açılıyor, eski `legacy` araştırması açılıp yanıt
  veriyor (yazılı tek canlı-olmayan sınama); `skill_package_hash` aynı; en yüksek migration `0054`.

## Bu dilimde yok

- `legacy` yolunun kaldırılması (ayrı karar).
- Eşik ve kural değiştirmek (SW girişi olur, ilgili dilime dönülür).
- Europe PMC'yi kurmak (E1).
- Kod kapısı (dilim 23) ve SW10 fikrinin kapı yarısı.
- Meta-analiz ya da havuzlanmış etki büyüklüğü.
- Kişinin kuyruk cevapları, model terim önerisi (08c), onay kartında düzeltme: kampanyada kişi yok.
- Üçüncü bir soru; `attached` araştırmaları; masaüstü paketi.
- D96'nın (a)–(c)'si ve SW6.6'nın düzeltilmesi.

## Ölçülmedi (bu planda)

Tıp sorusunda `sw`'nin hiçbir şeyi; bugünkü `legacy` kodunun süresi ve sonucu; yerleşik gömmenin açık olduğu bir koşu;
Luna kotasının bugünkü durumu; tıp referans kümesinin boyu (meta-analizler seçilmedi); Elicit'in tıp eserlerinin kapsam
etiketi (özetleri okunmadı; Liu 2022 ve Jamshed 2022 için yalnız başlık ve Elicit'in cevabı); Elicit'in tıpta neyi arayıp
neyi elediği (denetim izi yok); DeepSeek'in bugünkü fiyatı; dağılım (Kapı 2'nin iki hücresi dışında her hücre tek koşu; iki koşu
da dağılım göstermez). Tahmin bölümündeki her sayı kuantumdan taşındı. Kapı 2'nin d payının koşudan koşuya oynamaya göre
yeterli olup olmadığı; analist okumasının ikinci bir okuyucuda tutup tutmadığı.

## Sol r1 bulguları ve yapılanlar

`gpt-6-sol` · high r1 (`.local/sw-slice24-plan-2026-09-26/sol/answer-r1.md`), "hazır değil".

1. **TRE referans kümesi tek anlamlı değildi; kaynakça geri dönüşü dahil edilmemiş denemeleri katıyordu (yüksek).**
   Karar 6 yeniden yazıldı: harfi harfine `esearch` sorgusu, Entrez tarihi (`edat`), sıra ve eşitlik kuralı (aynı gün
   büyük PMID önce), özetten uygunluk (a)–(e) ile karma tasarım ve karma nüfus kuralı, yalnız dahil edilen çalışmalar
   tablosu, `table_unavailable` ile sıradaki derlemeye geçiş (en çok 10 aday), deneme karar ağacı ve "bilinmiyor"
   listesi, payda. Kaynakça listesine geri dönüş kaldırıldı.
2. **Kapılar varsayılanı taşımıyordu; analist okuması kapıya bağlı değildi (yüksek).** Kapı 4 eklendi: çekilen 10
   `include`'da ya da 10 atıflı iddiada 2 ya da daha fazla ciddi hata 24b'yi durdurur; "ciddi" önceden tanımlandı (karar
   11). Örnek karar 10'da `sw` `standard`'ın iki koşusundan çekilir. Süre, PubMed, kuyruk ve PDF bekleyen yük kapı
   değil, kapıların yanında raporlanır.
3. **K8 iş akışı karşılaştırmasına taşınmıştı; tekrar kuralı tek taraflıydı (yüksek).** Kapı 2 K8'den ayrıldı: iki taraf
   da `standard`'da baştan iki kez ve araya girerek koşar, dört koşunun hepsi kullanılır, ölçüler havuz ve atıf alan R
   girdisinin ortalaması, pay d = en büyüğü (2, ⌈0,1 × |R|⌉), |R| < 10 ya da bitmeyen taraf kapıyı okunamaz yapar ve
   okunamayan kapı geçmemiş sayılır. Tartışmalı sonuç üzerine ek koşu kaldırıldı (karar 3, 11; sapma 4; A1).
4. **Dondurmanın sınırı daha dar anlatılmalıydı (orta).** Karar 8: dondurma DEIXIS sonucuna bakıp ayarlamayı sınırlar,
   Elicit'i ve meta-analiz seçimini görmenin yanlılığını gidermez; onu karar 6'nın sorgusu ve karar ağacı sınırlar,
   okunamayan tablo ve karar verilemeyen deneme tahminle doldurulmaz.
5. **Aşama adları ve kayıp teşhisi (orta).** "Ölçüm sözlüğü" bölümü eklendi: referans girdisi, eşleme sırası ve
   çatışması, iş düzeyi, bölünmüş iş, her aşamanın tanımı, `candidate` ile yönlendirilen `unresolved` ayrımı
   (`fulltext.py:101-111`), paydalar. "Özet aşamasını geçen" adı "özette aday" oldu (sayı 2, 3, beklentiler); saklı
   sayıların yalnız `candidate`'i saydığı yazıldı. OpenAlex teşhisi "bugün kapsıyor" diye yazılır (karar 9).
6. **Kuantumdaki Elicit ayarı kayıtlıydı: "Balanced" (orta).** Sayı 3 ve karar 7 düzeltildi (arama günlüğü satır 4).
   `standard` yalnız başlık sütunu; eşit bütçe ya da eşit okuma derinliği söylenmez. "İki taraf tam metin okunabilen
   eserde anlaşıyor" cümlesi, iki ayrı etiketin (Elicit'in "Full text"i ve defterin model türevi sınıfı) örtüşmesi diye
   daraltıldı.
7. **G1 belirsizdi (orta).** Karar 12: KaTeX'te çizilemeyen blok 0, listeleyip geçmek yok; 40 blok makale başına en
   çok 2; tam 1 yanlışta o makalenin öbür yerleşmeleri de okunur, ikinci yanlış düşürür; yerleşmeyen ve eşleşmeyen
   bloklar raporlanır; sonuç genel güvenilirlik sınırı değildir.
8. **Kota denetimi ve süre tahmini (orta).** Karar 4: kota `health`'ten değil, ilk gerçek model çağrısının sonucundan
   okunur. Tahmin 14 araştırmaya göre yeniden hesaplandı (1.400–1.650 çağrı, ~4,5–5,5 saat) ve "kaba planlama sayısı"
   diye, ölçülmeyen etkenleriyle yazıldı.
9. **24b belge görevi README'nin eski iddiasını bırakıyordu (düşük).** Görev 12'ye `README.md:238`'in düzeltilmesi
   eklendi. Planın ve istemin commit'le donması koordinatörün işidir; istem commit'siz planla durur (değişmedi).

## Sol r2 bulguları ve yapılanlar

`gpt-6-sol` · high r2 (`.local/sw-slice24-plan-2026-09-26/sol/answer-r2.md`), "hazır değil": r1'in 1, 2, 3, 5 ve 7'si
kısmen kapanmıştı.

1. **TRE uygunluğu tabloyu uygunluktan sonraya bırakıyordu; sayfalama, belirsiz Elicit etiketi ve bilinmiyor payı yoktu
   (yüksek).** Karar 6 adım 3: (a)–(c) özetten, (d)–(e) dahil edilen çalışmalar tablosundan; adım 4 aynı tablodan. Adım 1:
   `count` 200'ü aşarsa `retstart` ile sayfalama, toplanan sayı `count`'a eşit değilse durma. Karar 7: üçüncü Elicit etiketi
   "belirsiz", `include` karşılaştırmasına girmez. Adım 6: bilinmiyor payı %25'i aşarsa Kapı 2 tıpta okunamaz.
2. **Kapı 2 tek koşuyla geçebiliyordu; atıf payı ayırt etmiyordu (yüksek).** Kapı 2 yalnız dört koşunun dördü de bitince
   okunur. Havuz payı d_havuz = en büyüğü (2, ⌈0,1 × |R|⌉); atıf için ayrı kural: `sw` ≥ `legacy` − 1 ve `legacy` atıf
   yapıyorsa `sw`'nin iki koşusunda da en az bir atıf. İkisinin gerekçesi yazıldı. Kapı betimleyici bir karar kuralı diye
   sunulur, istatistiksel geri kalmama sınaması diye değil.
3. **Kapı 4 küçük örnekle ve kayıtsız hükümle geçebiliyordu (yüksek).** Karar 10: birim tekil (iki koşuda da `include`
   olan iş bir kez), her hüküm `analyst-reading.jsonl`'a gerekçesiyle, ciddi işaretli her birim ve 5 ciddi olmayan birim
   ikinci bir model oturumunca kör okunur, ayrılıkta birim ciddi sayılır. Kapı 4: en az 8 tekil `include` ve 8 tekil
   iddia; azsa okunamaz, geçmemiş sayılır.
4. **Sözlük iki sayım üretiyordu (orta).** R'nin birimi tekil deneme (PMID, DOI, kayıt numarası, başlık sırasıyla
   birleştirilir); |R| ve Kapı 2'nin payı ona bağlı. Geçiş payı yalnız iç içe zincirde (havuz → yönlendirilen → okunan →
   include → atıf alan), kesişimle. `probe_report.py`'nin "herhangi biri" eşlemesi (`scripts/probe_report.py:125-126`)
   ayrı tabloda, kapılara girmez. Saklı sayıların "aynı tanımlarla okundu" cümlesi düzeltildi: onlar DOI ya da başlıkla
   ve yalnız `candidate` ile sayıldı.
5. **İstem kesintiyi ve dosya kapsamını çelişkili anlatıyordu (orta).** Kapı başarısızlığında satır 24 `24a bitti; kapı N
   geçmedi; sahip kararı bekliyor` (Part A yeniden koşmaz) ve Part A'nın izinli dosyalarına koşullu D105 için
   `docs/decisions.md` eklendi. Karar 13: kesintide `24a durdu` ve aynı donmuş protokolle sürdürme (özetler ve ürün kodu
   aynıysa), değilse yeni klasörde yeniden başlatma. Görev 5: ölçüm betikleri dondurmadan önce yazılır ve saklı bir
   kütüphanede denenir.
6. **G1'de 40 uygun blok çıkmazsa hüküm yoktu (düşük).** Karar 12: çıkmazsa kural okunamaz, hüküm `off`.

## Sol r3 bulguları ve yapılanlar

Sol r3 (gpt-6-sol high) "hazır değil" dedi; r2'nin 2, 3 ve 6. maddelerini kapalı, 1, 4 ve 5'i kısmen kapalı buldu.

1. **(c) özetten erken elenebiliyordu (yüksek).** Karar 6 adım 3: özet (c)'yi kararlaştıramıyorsa aday elenmez, (c) de
   tablodan karar verilir; yalnız (a) ya da (b)'yi açıkça karşılamayan özet eler.
2. **Kapı 2'de payda deneme, bulunan iş düzeyindeydi (yüksek).** Sözlük: her R birimi yayın listesini taşır, eşleme
   yayın başına yapılır ve sayılan birimdir; farklı birimler hiçbir zaman tek işte birleşmez, aynı birimin iki yayını
   bir kez sayılır. Kayıt numarası havuzda aranmadığı sınır olarak yazıldı.
3. **Satır 24 eski Kapı 2 payını taşıyordu (orta).** Satırda atıf payı 1, havuz payı ayrı yazıldı; `|R|` kaçırıldı.
4. **Ani çöküşten sonra dal yoktu (orta).** Karar 13 ve istem: satır `uygulanıyor (24a)` kalmışsa sonraki koşu bunu
   kesinti sayar, defterden ve günlükten nerede durduğunu bulur, özet ve kod koşuluyla sürdürür ya da yeniden başlatır.

## Sol r4 düzeltmeleri ve yapılanlar

Sol r4 (gpt-6-sol high) "düzeltmeyle hazır" dedi; iki düzeltme işlendi.

1. **Paylaşılan yayın iki denemeyi birleştirebiliyordu.** Sözlükteki referans birimi: farklı kayıt numarası taşıyan
   satırlar PMID ya da DOI paylaşsa da birleştirilmez; paylaşılan yayın iki denemenin de listesine girer.
2. **Sürdürülecek klasör tanımsızdı.** Karar 13: `.local/sw-slice24-active` etkin klasörü ve commit'i tutar; sürdürme
   denetimi yalnız ona uygulanır, yeniden başlatmada yeni klasöre taşınır.
