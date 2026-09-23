# SW dilim 15 — Atıf zinciri

**Tarih:** 23 Eylül 2026. **Durum:** plan yazıldı, sahip onayı bekliyor (aşağıdaki altı karar). **Ana dosya:**
[sw-status.md](sw-status.md). **Karar:** D95 (dilim yazar). **Önkoşul:** 14a (kapandı, `8f86f54`, D94). **Tür:** Kur.
**Uygulayan:** Opus · high (satırdaki gibi; yeni istekler, yeni adımlar, planın dördüncü grubu). **İnceleme:** satırda
toplu; tam öneriyorum (Sol · high), çünkü dilim kütüphaneye kayıt ekliyor ve tam metin planına grup ekliyor.
**Plan:** Opus · high, 23 Eylül 2026 (prompt Fable · high diyordu; bu oturum Opus'ta koştu). **Yeniden oynatma:**
`.local/sw-slice15-chain-replay-2026-09-23/` (`protocol.md`, `result.md`, betikler, `cache/`).

**Goal:** SW4 ve SW3.6 atıf zincirini kurar: aramadan sonra kodun seçtiği eserlerin referansları ve onlara atıf yapan
eserler OpenAlex'ten alınır, geniş bir metin süzgecinden geçenler taranır. Yeniden oynatma üç şey gösterdi. Zincir,
havuzda olmayan doğrulanmış eserlerin bir kısmına ucuza ulaşıyor. Ama zincir eserleri bugünkü sınırların içine konunca
plan kazanmıyor, çünkü D94'ün bulduğu darboğaz yer. Zincire ayrıca yer açılınca kazanç geliyor, ama aynı yeri anahtar
sözcük eserlerine vermek de hemen hemen aynı kazancı veriyor. Bu yüzden dilim zinciri kendi özet okuması ve plan
içindeki kendi yeriyle kurar (karar 4). Asıl getirisi, anahtar sözcüğün hiç bulamadığı eserlerle tavanı yükseltmesi.

## Elimizdeki sayılar

Hepsi yeniden oynatmadan: on üç kütüphane (kuantum on, paket üç), 407 OpenAlex isteği (başarısız 0, ortanca 0,41 sn),
1 Semantic Scholar isteği, model çağrısı yok. Doğru eser ölçüsü 31 kuantum ve 6 paket eseri. Ayrıntı `result.md`'de.

1. **Havuzda eksik olan doğrulanmış eser:** kuantum `quick` dört koşuda 12–14, `standard` 3–6, `detailed` 1–6; paket
   2–5.
2. **Kod tohumlarının ulaştığı** (ulaşılanların hepsi süzgeçten geçiyor), koşuların toplamı:

   | | eksik | 5 tohum | 10 | 15 | 25 |
   |---|---:|---:|---:|---:|---:|
   | kuantum `quick` (4 koşu) | 52 | 10 | 15 | **16** | 21 |
   | kuantum `standard` (3) | 15 | 3 | 5 | **8** | 9 |
   | kuantum `detailed` (3) | 11 | 0 | 0 | **0** | 1 |
   | paket (3) | 10 | 2 | 2 | 2 | 2 |

   Ulaşımın yarısı geri yönden (referans), yarısı ileri yönden (atıf yapan) geliyor; 32 satırın 5'i iki yönden.
3. **Maliyet:** 15 tohum 17–24 istek (~10 sn), 25 tohum 29–38 istek. Süzgeçten geçen yeni eser 15 tohumda kuantumda
   54–241, pakette 848–955; 25 tohumda 79–362 ve 1.047–1.353. **Erken durma hiç tetiklenmezdi:** son beş tohum her
   kütüphanede en az 4 yeni eser ekledi.
4. **Başka tohumlar:** derlemeler (`survey_title_word`) 52 eksiğin 1'ine ulaştı ve en çok eseri ekledi (paket: 3.564).
   Modelin tuttuğu eserler `quick` ve `standard`'da koda yakın (19 / 52, 7 / 15), `detailed`'da daha iyi (5 / 11'e
   karşı 1 / 11). Tam metin aşamasının kapsamda bulduğu eserler tohum başına en verimlisi (iki `quick` koşusunda 5 ve 11
   tohumla 4 / 12 ve 6 / 13). `criterion_not_met` kütüphane başına 0–2 eser, karar için az.
5. **Plana giriyor mu** (on kütüphane, D94 sınırları, 15 kod tohumu; plandaki doğrulanmış eser, koşuların toplamı; iki
   sayı, modelin zincir eserlerini tutmadığı / hepsini tuttuğu sınır):

   | tasarım | `quick` (3) | `standard` (2) | `detailed` (2) | paket (3) |
   |---|---:|---:|---:|---:|
   | bugün | 30 | 20 | 41 | 0 |
   | P1 tek havuz: zincir eserleri sıralamaya ve özet okumasına katılır | 30 / 29 | 20 / 18 | 39 / 38 | 0 |
   | P2 en sona: zincir eserleri üç grubun arkasında | 30 | 20 | 41 | 0 |
   | P3 sınırın içinden pay (¼ plan yeri, ½ özet okuması) | 32 / 31 | 21 / 20 | 41 / 37 | 1 |
   | **P4 zincire ayrıca yer** (sonradan hesaplandı) | **36** | **25** | **41** | **1** |
   | aynı yeri anahtar sözcük eserlerine vermek (sonradan) | 35 | 24 | 44 | 0 |

   P1 bir koşuda 13'ten 11'e düşürdü. P2 hiçbir şey kazandırmıyor, çünkü üç grup her eforda sınırdan uzun. P4 koşu
   başına `quick` +2 / +2 / +2, `standard` +3 / +2, `detailed` +0 / +0. Anahtar sözcük eserleri `detailed`'da zaten
   plana aday 22 eserin 20–21'ini alıyor: orada eklenecek şey ancak zincirden gelir, kod tohumları da oraya ulaşmıyor.
6. **Semantic Scholar:** OpenAlex zincirinin ulaşmadığı eksiklerden dördüne bağ buldu. İkisi (g106, g158) 2025 ön
   baskısı ve OpenAlex'te referans listeleri boş. Dört `quick` koşusunda ileri yönden ulaşılıyor.
7. **İkinci halka** (ilk halkanın ulaştığı doğrulanmış eserlerden bir halka daha): on üç kütüphanede toplam 3 eser.
8. **Süre** (D94 kabulü, kuantum `quick`): 9,8 dk, hedef 10. Getirme 1,4 dk / 80 iş, okuma 2,1 dk / 46 adım. Okuma
   sınırı hiçbir ölçüm koşusunda bağlamadı: okunan iş `quick` 24 / 40, `standard` 42 / 50, `detailed` 125 / 150.

## Sahibin vereceği kararlar

1. **Üç efor da zincir kurar; `quick`'in hedefi 10 → 12 dk olur, `standard` 15 ve `detailed` 20 aynı kalır.** Önerim
   bu. Gerekçe: zincirin istekleri ~10 sn; süreyi büyüten ayrılan yer (karar 4). Tahmin (ölçülmedi): `quick` +1,3–1,7
   dk (istek 0,2, zincirin özet okuması 2 çağrı ~0,3, 20 iş getirme ~0,35, okuma 0,4–0,8), yani ~11–11,5 dk.
   `standard` ve `detailed` +1,5–2,5 dk; ikisi zaten hedefin üstünde (17,9 ve 39,7) ve bu dilim onu düzeltmiyor.
   Seçenekler: (a) `quick` zincir kurmaz ve 10 dk'da kalır; (b) `detailed` zincir kurmaz, çünkü kod tohumları orada
   11 eksikten 1'ine ulaştı. (b)'yi önermiyorum: eforlara ayrı kural tek konuya ayar olur, maliyet de `detailed`'ın
   süresinin ~%5'i.
2. **Tohum: sıralamanın 15 kod tohumu, artı kullanıcının adlandırdığı ya da yüklediği her makale.** Önerim bu. Kod
   tohumu bugün çizge sinyalinin kullandığı listenin aynısı (`ranking.rank_records`: BM25 ve blokların RRF'i, ilk 15).
   Kullanıcının tohumları `ranking.verified_seeds`. İş düzeyinde tekilleştirme (birleşmenin işi, sonra normalleştirilmiş
   başlık). Derleme tohum olmaz. Erken durma kurulmaz: hiç tetiklenmedi. Gerekçe: 25 tohum havuzda `quick`'te 5 eser
   daha buluyor ama `quick` ve `standard`'da plana eser eklemiyor (`detailed`'da bir koşuda 1) ve 10–14 istek daha
   istiyor. Seçenek: 25 tohum (SW4'ün üst ucu); ya da
   15 kod tohumu + özet aşamasından sonra modelin tuttuğu ilk 10 eser (`detailed`'da daha iyi; tek konu, ölçülmedi).
3. **İki yön, yalnız OpenAlex; Semantic Scholar bu dilimde yok.** Önerim bu. Geri yön: tohumun saklı referans listesi
   (`record_references`, istek yok), kütüphanenin tanımadığı eserlerin künyesi 100'lük toplu isteklerle. İleri yön:
   `cites:<W>`, tohum kimliği başına en çok 400 eser (2 sayfa). Gerekçe: iki yönden biri eksik olsa ulaşımın yarısı
   gider. Semantic Scholar 2025 ön baskılarına ulaşıyor (dört `quick` koşusunda 2 eser), ama tohum başına bir istek ve
   2 sn aralık (D67) 15 tohumda ≥ 30 sn ekler; dilim 14'te de 429 verdi. Ayrı iş olarak yazılsın.
4. **Zincir eserleri kendi özet okumasıyla ve planda kendi yeriyle girer (P4).** Önerim bu. Süzgeçten geçen yeni
   eserler: özet aşamasının kodu (`code_outcome`) hepsine uygulanır, model zincir sırasının ilk `C` eserini okur
   (`quick` 20, `standard` 50, `detailed` 50). Aday olanlar tam metin planının dördüncü grubudur (`chain`). Bu grup
   bugünkü sınırın **üstüne** `R` yer alır (`quick` 20, `standard` 25, `detailed` 25). Anahtar sözcük eserlerinin
   sırası, özet okuması ve planı olduğu gibi kalır. Zincir sırası bugünkü sıralamanın havuz + zincir üzerinde yeniden
   hesaplanmış hâlidir, yalnız zincir eserleri için saklanır. Gerekçe: P1 bir koşuda 2 eser kaybettirdi, P2 hiç
   kazandırmadı, P3 `standard`'da yerinde saydı ve `detailed`'da kaybettirdi (41 → 37); P4 `quick`'te koşu başına +2, `standard`'da +2–3.
   `detailed` için 50 / 25 yeniden oynatılmadı (oynatılan 150 / 75; oradaki tek zincir eseri zincirde 3. sıradaydı).
   Seçenek: zinciri kurmadan aynı yeri anahtar sözcük eserlerine vermek (bir sabit değişikliği; `quick` 35'e karşı 36,
   `standard` 24'e karşı 25). Bunu önermiyorum: yer tek başına tavana çarpar, `detailed`'da çarptı bile; havuzda
   olmayan esere yalnız zincir ulaşır.
5. **İkinci halka bu dilimde yok.** Önerim bu. İlk halkanın ulaştığı doğrulanmış eserlerden bir halka daha on üç
   kütüphanede toplam 3 eser ekledi. Tam metinde kapsamda bulunan eserler daha iyi tohum (iki `quick` koşusunda 4 / 12
   ve 6 / 13), ama onlar ancak tam metin okumasından sonra var olur: ikinci bir keşif, özet ve tam metin turu ister ve
   süresi ölçülmedi. Ayrı dilim ya da "devam et" eylemi olarak yazılsın.
6. **Onay kartı ve protokol zinciri yazar, kullanıcı kartta kapatamaz.** Önerim bu. Kartta kaynakların altına bir
   satır: kaç tohum, nasıl seçildiği, iki yön, süzgeç, `C` ve `R`. Tohumlar aramadan sonra seçildiği için kart
   listesini gösteremez; koşu görünümü gösterir. Protokol gövdesi `citation_chaining` bloğunu dondurur (kural sürümü,
   tohum sayısı, kullanıcı tohumları, yönler, kaynak, 400 sınırı, süzgeç, `C`, `R`), sabitler `thresholds.chain`'e
   girer. Koşu görünümü zincir satırını gösterir: tohumlar (başlıklarıyla), yön başına bağlanan, yeni, süzgeçten geçen,
   modelin okuduğu, aday, planda. Kapatma `DEIXIS_CITATION_CHAINING` (`auto` | `off`) ayarındadır. Seçenek: kartta bir
   anahtar (bu dilime arayüz işi ekler).

## Global constraints

- **Yalnız `sw`.** `legacy` araştırma zincir kurmaz; gövdesi, bütçesi, istekleri byte byte aynı kalır.
- **Anahtar sözcük yolu değişmez** (karar 4). `ranking` adımı, özet aşamasının anahtar sözcük okuma planı ve planın ilk
  üç grubu, zincir eseri olsa da olmasa da aynı çıkar. Bunu bir test sınar.
- **Model sözleşmesi değişmez.** Zincirin özet okuması `abstract_screening` sözleşmesini ve aynı istemi kullanır;
  `skill_package_hash` aynı kalır. Model zincirden haber almaz.
- **Dondurulmuş plan, tekrarlanan çağrı.** Tohum listesi, zincir listesi ve zincirin okuma planı adım çıktısında
  donar. Sürdürülen koşu onları geri okur ve OpenAlex'e yeniden sormaz. Adım anahtarları yer değil kimlik taşır:
  tohumun W kimliği, sayfa, parti numarası.
- **Başarısız istek koşuyu durdurmaz** (D18). Kaydedilir ve gösterilir, öbür istekler sürer. Zincir koşuyu hiçbir
  durumda duraklatmaz.
- **Donmuş bütçeye saygı.** Bu değişiklikten önce kuyruğa girmiş koşu zincir kurmaz ve bütçesini korur. Model bütçesi
  yalnız `sw` keşif koşusunda `2 × ceil(C / 20)` artar; getirme bütçesi `R` artar; okuma sınırı değişmez (hiç bağlamadı).
- **Kayıt yolu tek.** Zincir kayıtları aramanın kayıt yolundan geçer (normalleştirme, kimlik, birleştirme D46,
  `record_references`). Birleştirme yolu değişmez. Mevcut bir işe birleşen kayıt zincir eseri sayılmaz.
- **Konuya özgü hiçbir şey yok.** Süzgeç onaylı sözcük dağarcığının iki kapı bloğunu okur.
- Testlerde ağ yok. Canlı çalışan yalnız Task 8'in kabulü.

## Task 1: sabitler ve protokol

- `domain/rules.py`: `CHAIN_SEEDS = 15`, `CHAIN_CITING_CAP = 400`,
  `CHAIN_ABSTRACT_READ = {"quick": 20, "standard": 50, "detailed": 50}`,
  `CHAIN_PLAN_ROOM = {"quick": 20, "standard": 25, "detailed": 25}`. Yorumda tarih, D95 ve yeniden oynatmanın klasörü:
  "15 tohum = çizgenin kod tohumları; 25 plana eser eklemedi; `detailed` 50 / 25 oynatılmadı".
- `workflow/protocol.py`: `sw` gövdesine `citation_chaining` bloğu ve `thresholds.chain`. Ayar `off` ise blok
  `{"enabled": false}` olur. `legacy` gövdesi değişmez.
- `Settings.citation_chaining` (`DEIXIS_CITATION_CHAINING`, varsayılan `auto`).

## Task 2: OpenAlex'in iki isteği

- `providers/openalex.py`: `citing_works(work_id, cursor)` (`filter=cites:<W>`, `per-page=200`) ve
  `works_by_ids(ids)` (en çok 100 kimlik, `filter=openalex:W1|…`). Her ikisi de `sw` okumasının `select` alanlarını
  kullanır, `referenced_works` dahil, böylece zincir kayıtlarının referans listesi de yazılır.
- İstekler mevcut konak kapısından geçer (13e). İkinci bir eşzamanlılık düzeneği eklenmez.
- Sayfa 2 yalnız `CHAIN_CITING_CAP`'e varılmadıysa istenir.

## Task 3: zincir adımları (`flow._chaining`)

`_discovery`'de `_abstract_stage`'den sonra çalışır. Yalnız `sw`, ayar `auto` ve koşunun bütçesi zinciri taşıyorsa.

1. `code:chain_seeds`: `code:ranking` adımının saklı `seeds` listesinden `kind = code` olanlar ve
   `ranking.verified_seeds`. İş düzeyinde tekilleştirilir, çıktıda donar. OpenAlex kimliği olmayan tohum yalnız geri
   yön alır; referans listesi olmayan yalnız ileri yön alır. İkisi de sayılır.
2. `chain:backward:<n>`: tohumların referanslarından kütüphanenin tanımadığı kimlikler, 100'lük partiler.
3. `chain:forward:<W>:<sayfa>`: tohum kimliği başına atıf yapanlar.
4. Kayıtlar aramanın yoluyla yazılır: `search_runs` satırı (sağlayıcı `openalex`, tür `chain_backward` ya da
   `chain_forward`), üyelik, aday, `candidate_hits`. Şema izin vermiyorsa yeni migration `0050` eklenir. Uygulayan önce
   `search_runs` ve adım türlerinin `CHECK` kısıtlarını okur.
5. `code:chain_filter`: bu koşunun zincir kayıtlarının iş başlarından, anahtar sözcük havuzunda olmayanlar; süzgeç iki
   kapı bloğundan birinin biçimi başlıkta ya da özette (`ranking.blocks_in`, sözcük başı). Özeti olmayan başlığıyla
   yargılanır. Süzgeçten geçemeyen kayıt kütüphanede kalır ama aday değildir: `stage_decisions`'a `chain_filter_out`
   gibi bir kod yazılmaz, yalnız adımın çıktısında sayılır. Liste donar.
6. `code:chain_ranking`: `rank_records`'un saf kısmı havuz + zincir üzerinde koşar. Satırlar yalnız zincir eserleri için
   yeni bir sıralama adımına yazılır. `ranking` adımına dokunulmaz.
7. Zincirin özet aşaması: `code_outcome` her zincir eserine yazılır. `read_plan` zincir sırası üzerinde
   `CHAIN_ABSTRACT_READ` ile çalışır, anahtarlar `abstract_screening:chain:<parti>:<koşu>`. Geri kalanlar
   `abstract_not_read`. Zincir kayıtları için ikinci kaynaktan özet sorulmaz (`no_abstract` olarak kalır; bu dilimde
   getirilmezler). Derleme bayrağı (`flag_and_decide`) zincir kayıtlarına da uygulanır.
8. Adımın çıktısı sayar: tohum, tohum başına ve yön başına bağlanan, yeni, süzgeçten geçen, modelin okuduğu, aday,
   istek, başarısız istek.

## Task 4: tam metin planının dördüncü grubu

- `fulltext.GROUPS` sonuna `chain` eklenir. Bir iş, revizyonun en son `code:chain_filter` listesindeyse ve özet sonucu
  onu getirmeye yönlendiriyorsa bu gruptadır. Kullanıcının dahil ettiği zincir eseri `user` grubunda kalır.
- `fetch_plan`: ilk üç grup `FULLTEXT_WORK_LIMIT` ile aynı kalır. `chain` grubu zincir sırasıyla ve `CHAIN_PLAN_ROOM`
  kadar alır. Kullanılmayan yer anahtar sözcük eserlerine verilmez: ilk üç grubun planı byte byte aynı kalır.
- `fetch_budget` `R` artar. Okuma planı getirme sırasını izler, `FULLTEXT_READ_LIMIT` değişmez.

## Task 5: kart, protokol görünümü, koşu görünümü

- Onay kartına zincir satırı (karar 6). Metinler `i18n.ts` ve `labels.ts`'e, iki dilde.
- Koşu görünümü (`views.py`, `Transcript.tsx`): zincir satırı ve açılınca tohum listesi. `candidate_hits` sayıları
  zinciri kaynak olarak gösterir ("yalnız zincirin getirdiği").
- Protokol raporu zinciri "citation searching" olarak sayılarıyla yazar.

## Task 6: testler

- Yeni `tests/test_chaining.py` (saf):
  `test_seeds_are_the_rankings_code_seeds_plus_the_users_own`,
  `test_seeds_are_deduplicated_at_work_level_before_the_count`,
  `test_a_seed_without_an_openalex_id_gets_backward_links_only`,
  `test_the_filter_passes_a_setting_or_a_task_form_in_title_or_abstract`,
  `test_a_work_without_an_abstract_is_judged_on_its_title`,
  `test_a_linked_work_the_library_already_holds_is_not_chained`,
  `test_the_chain_ranking_orders_chained_works_only`.
- Yeni `tests/test_chaining_flow.py` (`create_app`, sahte `httpx`):
  `test_an_sw_run_chains_after_the_abstract_stage`,
  `test_backward_links_the_library_holds_send_no_request`,
  `test_a_failed_citing_request_is_recorded_and_the_others_go_on`,
  `test_a_resumed_run_asks_openalex_nothing_again`,
  `test_the_chain_read_reads_at_most_its_limit_and_leaves_the_rest_unread`,
  `test_the_keyword_ranking_read_plan_and_fetch_plan_are_unchanged_by_chaining`,
  `test_chaining_off_sends_nothing_and_writes_no_step`,
  `test_a_legacy_research_never_chains`,
  `test_a_run_queued_before_this_change_keeps_its_budget`,
  `test_a_chained_record_that_merges_into_a_pool_work_is_not_chained`.
- `tests/test_fulltext_plan.py`: `test_the_chain_group_comes_last_with_its_own_room`,
  `test_the_first_three_groups_are_the_same_with_and_without_chained_works`; bütçe testinin beklenen listesi
  `[100, 125, 325]`.
- `tests/test_protocol_record.py`: `sw` gövdesinde `citation_chaining`, `legacy` gövdesi değişmedi.
- Fikstürler SYNTHETIC ve birden çok alandan. Arayüze dokunulduğu için `npm run build && npm run lint` ve Playwright
  A–G.

## Task 7: modelsiz denetim

Canlı koşudan önce yeni kodun saf işlevleri a14a `quick` kütüphanesinin bir kopyası ve bu klasörün `cache/` yanıtlarıyla
(ağ yok) koşturulur. Tohumlar `result.md`'deki `code` 15 listesiyle aynı çıkmalı. Süzgeçten geçen yeni eser sayısı
175'ten iş düzeyi tekilleştirme kadar sapabilir. Fark bir kurala dayanmıyorsa canlı koşuya geçilmez.

## Task 8: canlı kabul ve kapanış

- Düzen D94 kabulünün kampanyası: kendi sunucusu, boş veri dizini, `DEIXIS_SEARCH_WORKFLOW=sw`,
  `DEIXIS_FULLTEXT_FETCH=auto`, `DEIXIS_FULLTEXT_ADJUDICATION=auto`, `DEIXIS_SEARCH_QUERY=model`,
  `DEIXIS_CITATION_CHAINING=auto`, gömme `off`, onay `as_proposed`. Model `gpt-5.6-luna` · medium. Klasör
  `.local/sw-slice15-acceptance-<tarih>/`. Beklenti ilk istekten önce `protocol.md`'ye yazılır.
- Koşular (tam koşu, yanıt dahil): kuantum `quick`, `standard`, `detailed`; paket `quick`.
- **Karşılaştırılan önceki koşular ve sayıları** (doğrulanmış eser: havuzda / planda / okunan; süre):
  - kuantum `quick` ↔ D94 kabulü (`.local/sw-slice14a-acceptance-2026-09-23/`): 18 / 8 / 4; 9,8 dk.
  - kuantum `standard` ↔ üçüncü D88 ölçümü (`.local/sw-measure-2026-09-24/`): 25 / 8 / 7; 17,9 dk.
  - kuantum `detailed` ↔ üçüncü D88 ölçümü: 30 / 19 / 17; 39,7 dk.
  - paket `quick` ↔ D94 kabulü: havuzda 1, planda 0; 8,4 dk.
- **Kabul (K8):** tek koşu tek önceki koşuyla kıyaslanır. Havuz, plan ve okunan her biri en çok 2 eser eksik
  kalabilir. Daha büyük bir düşüş, sebebi zincirse dilimi düşürür; zincir ilk üç grubun planına dokunamadığı için bu
  ancak bir hata olabilir, o yüzden kabul koşusunda ilk üç grubun planı zincirsiz yeniden oynatmayla karşılaştırılır
  (`replay.py` A sırası, D94 sınırları). Düşüş başka bir adımdan geliyorsa dilim geçer, sebep ayrı iş olarak yazılır.
  Tartışmalı durumda o taraf iki kez koşulur, iyisi alınır.
- **Süre, zincirin kendi payı:** zincirin adımları, zincirin özet okuması, `chain` grubunun getirmesi ve okuması
  toplamı `quick`'te ≤ 2,0 dk, `standard` ve `detailed`'da ≤ 3,0 dk. Aşarsa ve fazlası zincirin kendi adımlarındaysa
  dilim düşer. Baştan sona süre yeni hedefle yan yana yazılır (karar 1: `quick` ≤ 12 dk).
- **Yazılan, kabul koşulu olmayan sayılar:** yalnız zincirin getirdiği doğrulanmış eser (havuzda, `chain` grubunda,
  okunan, atıf alan); tohum başına istek, başarısız istek; süzgeçten geçen yeni eser; `chain` grubunda PDF oranı;
  derleme bayrağı alan zincir eseri.
- D95 `docs/decisions.md`'nin en üstüne yazılır (Status / Date / Context / Decision / Limits). SW4 ve SW3.6'nın durum
  satırı güncellenir. SW5.4'ün "derleme tohum havuzuna" kuralı için bulgu yazılır: bu iki soruda derleme tohumları
  eksiklere ulaşmadı.
- Tam pytest; `git diff --check`; satır 15 → `uygulandı, inceleme bekliyor`; tek commit; push.

## Bu dilimde yok

- Semantic Scholar'ın atıf çizgesi (karar 3). Ayrı iş: 2025 ön baskılarına ulaşıyor, maliyeti ve 429 riski ölçülmeli.
- İkinci halka ve tam metinde kapsamda bulunan eserlerden zincir (karar 5).
- Derlemeleri tohum yapmak (SW5.4), erken durma kuralı (SW4.2), 25 tohum.
- Zincir kayıtları için ikinci kaynaktan özet (SW5.5), zincirin ikinci keşif koşusu, zinciri kartta kapatma.
- İnsan kuyruğu (dilim 16), özet aşamasının okuma sınırı ve `blocks_in_title` (D94'ün açık bıraktıkları), Europe PMC,
  dilim 14'ün açık bıraktığı iki iş.

## Ölçülmedi

- Süre: zincirin istekleri ölçüldü (ortanca 0,41 sn). Zincirin model çağrıları, ek getirme ve ek okuma tahmindir; Task 8
  ölçer.
- Model etiketleri: modelin zincir eserlerini tutup tutmayacağı bilinmiyor. Doğrulanmış zincir eserleri tutulmuş
  sayıldı (iyimser).
- P4 sonradan hesaplandı (P3'ün zincir sayıları + bugünkü plan). `detailed` için 50 / 25 oynatılmadı.
- Plana giren zincir eserinde PDF bulunma oranı, okunan ve atıf alan sayısı.
- Doğru eser ölçüsü iki eksik listedir (31 kuantum, 6 paket). Zincirin getirdiği ama listede olmayan ilgili eserler
  sayılmadı. Paket sorusunda eksik 2–5 eser ve ulaşılan tek eser var; ulaşımı değil, süzgecin başka bir alanda çok daha
  fazla eser geçirdiğini gösteriyor (15 tohumda 848–955). Üçüncü bir alan, birbirine az atıf yapan eserlerin olduğu
  bir soru ve modelin koşudan koşuya değişen etiketleri ölçülmedi.
