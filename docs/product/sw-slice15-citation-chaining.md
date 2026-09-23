# SW dilim 15 — Atıf zinciri

**Tarih:** 23 Eylül 2026. **Durum:** dosya hazır; altı karar Claude ile `gpt-6-sol` · medium arasında ortak karara bağlandı, sahip 23 Eylül 2026'da uygulamaya geçilmesini istedi. **Prompt:** [sw-slice15-prompt.md](sw-slice15-prompt.md). **Ana dosya:**
[sw-status.md](sw-status.md). **Karar:** D95 (dilim yazar). **Önkoşul:** 14a (kapandı, `8f86f54`, D94). **Tür:** Kur.
**Uygulayan:** Opus · high (satırdaki gibi; yeni istekler, yeni adımlar, planın dördüncü grubu). **İnceleme:** tam (Sol · high), çünkü dilim kütüphaneye kayıt ekliyor ve tam metin planına grup ekliyor.
**Plan:** Opus · high, 23 Eylül 2026 (prompt Fable · high diyordu; bu oturum Opus'ta koştu). **Yeniden oynatma:**
`.local/sw-slice15-chain-replay-2026-09-23/` (`protocol.md`, `result.md`, betikler, `cache/`).

**Goal:** SW4 ve SW3.6 atıf zincirini kurar: aramadan sonra kodun seçtiği eserlerin referansları ve onlara atıf yapan
eserler OpenAlex'ten alınır, geniş bir metin süzgecinden geçenler taranır. Yeniden oynatma üç şey gösterdi. Zincir,
havuzda olmayan doğrulanmış eserlerin bir kısmına ucuza ulaşıyor. Ama zincir eserleri bugünkü sınırların içine konunca
plan kazanmıyor, çünkü D94'ün bulduğu darboğaz yer. Zincire ayrıca yer açılınca kazanç geliyor, ama aynı yeri anahtar
sözcük eserlerine vermek de hemen hemen aynı kazancı veriyor. Bu yüzden dilim zinciri kendi özet okuması ve plan
içindeki kendi yeriyle kurar (karar 4). Asıl getirisi, anahtar sözcüğün hiç bulamadığı eserlerle tavanı yükseltmesi.

> **Uygulama notu (24 Eylül 2026):** bu dosyadaki `CHAIN_PLAN_ROOM` 20 / 25 / 25, kabulün iki başarısız denemesinden
> sonra, sonuç görüldükten sonra ve `gpt-6-sol` · medium ile ortak kararla 12 / 12 / 12 oldu (D95,
> `.local/sw-slice15-acceptance-2026-09-23/`). Kabul bu değere aittir, aşağıdaki 20 / 25 / 25 tasarımına değil.

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
   | **P4 zincire ayrıca yer** (sonradan, ayrı plan olarak oynatıldı: `p4.json`) | **36 / 35** | **25** | **41** | **0** |
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

Öneriler `gpt-6-sol` · medium'un incelemesinden sonra ortak karara bağlandı (23 Eylül 2026; inceleme ve yanıt
`.local/sw-slice15-chain-replay-2026-09-23/sol-review.md`). Sol altı kararın üçüne katıldı, üçüne (1, 2, 4) itiraz etti;
üçünde de düzeltme aşağıda. Sol'un itirazı üzerine P4 ayrı bir plan olarak yeniden oynatıldı (`p4.py` → `p4.json`):
zincir kendi içinde tekilleştirildi, sabitler dilimin önerdiği boyda (20 / 20, 50 / 25, 50 / 25). Sonuç türetilmiş
sayıyla aynı: `quick` 30 → 36 / 35, `standard` 20 → 25, `detailed` 41 → 41, paket 0 → 0.

1. **Üç efor da zincir kurar; süre hedefleri şimdilik değişmez.** Kabul koşusu ölçer, hedef ölçümden sonra sahip
   tarafından yazılır. İlk önerim `quick` hedefini şimdiden 12 dk yapmaktı. Sol itiraz etti: tahmin zincirin özet
   okumasını, getirmesini ve okumasını ölçmüyor. Ortak karar: `quick` için 10 dk karşılaştırma ölçütü olarak kalır.
   Kabulün süre koşulu zincirin kendi payıdır (Task 8). Tahmin (ölçülmedi): `quick` +1,3–1,7 dk, `standard` ve
   `detailed` +1,5–2,5 dk. Seçenek: `quick` zincir kurmaz. `detailed` için bir not: kod tohumlarıyla iki koşuda da plana
   eser eklemedi. Ama eforlara ayrı kural tek konuya ayar olur, maliyet de `detailed`'ın süresinin ~%5'i.
2. **Tohum: BM25 ve blok sırasının ilk 15 farklı eseri, artı kullanıcının adlandırdığı ya da yüklediği her makale,
   ayrı ayrı.** Sol'un bulgusu doğru: `rank_records` çizge tohumlarını kullanıcı tohumları önde olmak üzere toplam
   15'e tamamlıyor. Saklı `kind = code` listesi bu yüzden kullanıcı tohumu olduğunda 15'ten kısa kalıyor. Zincir bu
   listeyi okumaz. `fuse(("bm25", "blocks"))` sırasından kullanıcı tohumu olmayan ilk 15 farklı eseri alır,
   `verified_seeds`'i ayrıca ekler, listeyi dondurur. İş düzeyinde tekilleştirme. Derleme tohum olmaz, erken durma
   kurulmaz. 25 tohum `quick`'te havuza 5 eser daha getiriyor ama plana eser eklemiyor.
3. **İki yön, yalnız OpenAlex; Semantic Scholar bu dilimde yok.** Sol katıldı. Geri yön saklı referans listesinden
   (istek yok), tanınmayan eserlerin künyesi 100'lük toplu isteklerle. İleri yön `cites:<W>`, tohum kimliği başına
   en çok 400 eser. Tek yön ulaşımın yarısını kaybettirir. Semantic Scholar ayrı iş.
4. **Zincir eserleri kendi özet okumasıyla ve planda kendi yeriyle girer (P4), fayda kabulde okunan eserle
   ölçülür.** Model zincir sırasının ilk `C` eserini okur (20 / 50 / 50). Adaylar planın dördüncü grubudur, bugünkü
   sınırın **üstüne** `R` yer alır (20 / 25 / 25). Anahtar sözcük eserlerinin sırası, özet okuması ve planı değişmez.
   Sol'un itirazı: P4 türetilmiş bir plan sayısıydı ve plan okuma demek değil. Ortak karar iki adımlı. Birincisi,
   P4 ayrı plan olarak yeniden oynatıldı ve türetilmiş sayıyı doğruladı (yukarıda). İkincisi, varsayılan açık kalmak
   için kabul koşusu okunan eser ister (Task 8, fayda koşulu). O koşul tutmazsa zincir kurulu ama `off` kapanır.
   Seçenek: zincir yerine aynı yeri anahtar sözcük eserlerine vermek (`quick` 35, `standard` 24). Önermiyoruz: yer
   tek başına tavana çarpar, havuzda olmayan esere yalnız zincir ulaşır.
5. **İkinci halka bu dilimde yok.** Sol katıldı. On üç kütüphanede toplam 3 eser ekledi; tam metinde kapsamda bulunan
   eserlerden zincir ikinci bir tur ister ve süresi ölçülmedi. Ayrı iş.
6. **Onay kartı ve protokol zinciri yazar; kapatma ayarda.** Sol katıldı. Kartta kural ve sınırlar yazar, gerçek
   tohumlar koşu görünümünde gösterilir. Protokol gövdesi `citation_chaining` bloğunu (kural sürümü, tohum sayısı,
   kullanıcı tohumları, yönler, kaynak, 400 sınırı, istek sınırı, süzgeç, `C`, `R`) ilk dondurmada ve genişleme
   revizyonunda aynı biçimde taşır. Ayar (`DEIXIS_CITATION_CHAINING`, `auto` | `off`) koşu kuyruğa girerken bütçeye
   yazılır ve o koşu için donar.

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
- **Donmuş bütçeye saygı.** Bu değişiklikten önce kuyruğa girmiş koşu zincir kurmaz ve bütçesini korur. Yalnız `sw`
  keşif koşusunda model bütçesi `2 × ceil(C / 20)` artar ve zincirin **kendi istek sınırı** `max_chain_requests`
  eklenir. Zincirin istekleri `max_provider_requests`'ten düşmez: o bütçenin bitmesi koşuyu duraklatır, zincirinki
  duraklatmaz. Sınır dolunca kalan tohumlar `not_reached` sayılır, koşu sürer. Getirme bütçesi `R` artar, okuma
  sınırı değişmez (hiç bağlamadı).
- **Kayıt yolu tek.** Zincir kayıtları aramanın kayıt yolundan geçer (normalleştirme, kimlik, birleştirme D46,
  `record_references`). Birleştirme yolu değişmez. Mevcut bir işe birleşen kayıt zincir eseri sayılmaz.
- **Konuya özgü hiçbir şey yok.** Süzgeç onaylı sözcük dağarcığının iki kapı bloğunu okur.
- Testlerde ağ yok. Canlı çalışan yalnız Task 8'in kabulü.

## Task 1: sabitler ve protokol

- `domain/rules.py`: `CHAIN_SEEDS = 15`, `CHAIN_CITING_CAP = 400`,
  `CHAIN_ABSTRACT_READ = {"quick": 20, "standard": 50, "detailed": 50}`,
  `CHAIN_PLAN_ROOM = {"quick": 20, "standard": 25, "detailed": 25}`, `CHAIN_REQUEST_LIMIT = 40` (15 tohumda ölçülen
  17–24 istek ve iki sayfalı tohumlar için pay). Yorumda tarih, D95 ve yeniden oynatmanın klasörü:
  "15 kod tohumu; 25 tohum `quick` ve `standard`'da plana eser eklemedi (kuantum `detailed`'da 150 / 75 ile bir
  koşuda 1); 15 tohumla kuantum `detailed` 50 / 25 ve 150 / 75'te 0, paket `detailed` 150 / 75'te bir koşuda 1".
- `workflow/protocol.py`: `sw` gövdesine `citation_chaining` bloğu ve `thresholds.chain`, hem ilk dondurmada hem
  genişleme revizyonunda (`_freeze_expansion`) aynı değerle. Ayar `off` ise blok `{"enabled": false}` olur. `legacy`
  gövdesi değişmez.
- `api/app.py`: `sw` keşif bütçesine `max_chain_requests` ve zincir okumasının çağrıları; ayar bütçeye yazılır, koşu
  için donar. `fulltext.fetch_budget` `chain_room` alanını taşır.
- `Settings.citation_chaining` (`DEIXIS_CITATION_CHAINING`, varsayılan `auto`).

## Task 2: OpenAlex'in iki isteği

- `providers/openalex.py`: `citing_works(work_id, cursor)` (`filter=cites:<W>`, `per-page=200`) ve
  `works_by_ids(ids)` (en çok 100 kimlik, `filter=openalex:W1|…`). Her ikisi de `sw` okumasının `select` alanlarını
  kullanır, `referenced_works` dahil, böylece zincir kayıtlarının referans listesi de yazılır.
- İstekler mevcut konak kapısından geçer (13e). İkinci bir eşzamanlılık düzeneği eklenmez.
- Sayfa 2 yalnız `CHAIN_CITING_CAP`'e varılmadıysa istenir.

## Task 3: zincir adımları (`flow._chaining`)

`_discovery`'de `_abstract_stage`'den sonra çalışır. Yalnız `sw`, ayar `auto` ve koşunun bütçesi zinciri taşıyorsa.

1. `code:chain_seeds`: `code:ranking` adımının saklı `bm25` ve `blocks` sıralarından `ranking.fuse` ile kurulan sıranın,
   kullanıcı tohumu olmayan ilk 15 farklı eseri, ayrıca `ranking.verified_seeds`. Saklı `seeds` listesi okunmaz
   (kullanıcı tohumu varken 15'ten kısadır). İş düzeyinde tekilleştirilir, çıktıda donar. OpenAlex kimliği olmayan tohum yalnız geri
   yön alır; referans listesi olmayan yalnız ileri yön alır. İkisi de sayılır.
2. `chain:backward:<n>`: tohumların referanslarından kütüphanenin tanımadığı kimlikler, 100'lük partiler.
3. `chain:forward:<W>:<sayfa>`: tohum kimliği başına atıf yapanlar.
4. Kayıtlar aramanın yoluyla yazılır: istek başına bir `search_runs` satırı (sağlayıcı `openalex`; `search_runs`'ta tür
   sütunu yok, yön `query_text` ve `request_description`'da yazılır), üyelik, aday, `candidate_hits`. Migration
   `0050_chain_links.sql` tohumdan esere bağı saklar: `chain_links(research_id, scope_revision, run_id,
   seed_source_version_id, linked_openalex_id, direction, passed_filter, source_version_id NULL)`, anahtar
   `(run_id, seed_source_version_id, linked_openalex_id, direction)`. Sürdürülen koşu yazılmış satırı yeniden yazmaz.
   **Süzgeç kayıttan önce çalışır:** yanıttaki başlık ve özet üzerinde. Süzgeçten geçemeyen eser için kayıt, üyelik
   ya da aday yazılmaz; yalnız `chain_links` satırı (`passed_filter = 0`, `source_version_id` boş) kalır.
5. Süzgeç: iki kapı bloğundan birinin biçimi başlıkta ya da özette (`ranking.blocks_in`, sözcük başı); özeti olmayan
   başlığıyla yargılanır. `code:chain_filter` süzgeçten geçip yazılan kayıtların iş başlarını (kayıt yolunun
   birleştirmesinden sonra, yani zincirin kendi içindeki DOI ve başlık eşleri tek iş) ve anahtar sözcük havuzunda
   olmayanları listeler, sayar, dondurur.
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
- `fetch_plan(works, order, limit, chain_order=(), chain_room=0)`: ilk üç grup bugünkü gibi `limit` alır, `chain` grubu
  `chain_order` sırasıyla en çok `chain_room` alır. Tek bir toplam sınır kullanılmaz; kullanılmayan zincir yeri anahtar
  sözcük eserlerine verilmez. İlk üç grubun planı byte byte aynı kalır.
- İki çağıran da değişir: `_fulltext_plan` (koşunun kendi planı) ve keşiften sonra getirme koşusunu kuyruğa koyan yol.
  İkisi de `fetch_budget`'tan `max_fulltext_works` ve `chain_room`'u ayrı ayrı okur; kullanıcının başlattığı getirme
  koşusu da aynı işlevden bütçe alır.
- Okuma sırası: `adjudication.read_plan` bugün `latest_ranking` sırasını okur ve orada olmayan işi kimliğe göre sona
  koyar. Zincir eserleri anahtar sözcük sırasından sonra, zincir sırasıyla okunur (`order + chain_order`). Okuma
  sınırı değişmez.

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
  `test_a_chained_record_that_merges_into_a_pool_work_is_not_chained`,
  `test_the_chain_request_limit_stops_chaining_without_pausing_the_run`,
  `test_user_seeds_do_not_shorten_the_fifteen_code_seeds`,
  `test_the_expansion_revision_carries_the_same_chain_policy`,
  `test_chain_links_are_written_once_on_resume`.
- `tests/test_fulltext_plan.py` ve `tests/test_adjudication.py`: `test_the_chain_group_comes_last_with_its_own_room`,
  `test_a_user_started_retrieval_run_gets_the_same_chain_room`, `test_chained_works_are_read_after_the_keyword_order`,
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
- **Aynı kodla zincirsiz karşılaştırma:** her koşuda ilk üç grubun planı, zincir kapalıyken yeniden oynatılan planla
  (`replay.py` A sırası, D94 sınırları) karşılaştırılır. Fark varsa zincir anahtar sözcük yoluna dokunmuştur: dilim
  düşer. Bir düşüşün sebebi zincir sayılır ancak bu karşılaştırma ya da zincirin kendi adımları onu gösterirse; bu
  kural koşudan önce `protocol.md`'ye yazılır, sonuç görüldükten sonra değiştirilmez.
- **Fayda koşulu (varsayılan için):** üç kuantum koşusunda toplam en az 1 doğrulanmış eser yalnız zincirle gelip
  tam metinde okunmalı. Tutmazsa davranış kabul edilir ama fayda kanıtlanmamış sayılır: zincir kurulu kalır,
  `DEIXIS_CITATION_CHAINING` varsayılanı `off` olur ve bulgu D95'e yazılır. "İki koşu, iyisi" kuralı yalnız süre ve
  K8 sayılarında kullanılır, fayda koşulunda kullanılmaz.
- **Süre, zincirin kendi payı:** zincirin adımları, zincirin özet okuması, `chain` grubunun getirmesi ve okuması
  toplamı `quick`'te ≤ 2,0 dk, `standard` ve `detailed`'da ≤ 3,0 dk. Aşarsa ve fazlası zincirin kendi adımlarındaysa
  dilim düşer. Baştan sona süre bugünkü hedeflerle (10 / 15 / 20 dk) yan yana yazılır; karar 1 gereği yeni hedefi
  sahip bu ölçümden sonra yazar.
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
- P4 sayılar görüldükten sonra tanımlandı; Sol incelemesinden sonra ayrı plan olarak oynatıldı (`p4.py`). Okuma,
  PDF ve atıf oynatılamaz.
- Plana giren zincir eserinde PDF bulunma oranı, okunan ve atıf alan sayısı.
- Doğru eser ölçüsü iki eksik listedir (31 kuantum, 6 paket). Zincirin getirdiği ama listede olmayan ilgili eserler
  sayılmadı. Paket sorusunda eksik 2–5 eser ve ulaşılan tek eser var; ulaşımı değil, süzgecin başka bir alanda çok daha
  fazla eser geçirdiğini gösteriyor (15 tohumda 848–955). Üçüncü bir alan, birbirine az atıf yapan eserlerin olduğu
  bir soru ve modelin koşudan koşuya değişen etiketleri ölçülmedi.
