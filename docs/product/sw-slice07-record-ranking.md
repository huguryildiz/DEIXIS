# SW dilim 07 — Kayıt düzeyinde sıralama: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): **SW7** (tümü), **SW8** madde 1–2 ve 5; SW1 madde 4; SW14 madde 6. **Önkoşul:** 02 (D71, `record_signal_ranks`), 04a, 04b, 04c, 05 (hepsi kapandı). **Tür:** Kur. **İnceleme:** toplu.

**Goal:** Bugün bir `sw` keşif koşusunda hangi adayın önce taranacağını sağlayıcının kendi sırası belirliyor (`candidates.rank`, 04c'nin `first_rank`'iyle sorgu içindeki yer) ve `max_candidates` o sıraya göre kesiyor. Bu dilim, taramadan önce kodla koşan bir sıralama adımı kurar: dört gömmesiz sinyal (BM25, başlıkta blok kapsaması, doğrulanmış tohumlara TF-IDF, atıf grafiği) ve varsa beşinci sinyal olarak gömme, sıra üzerinden RRF ile birleşir; gömmenin kurtarma kolu birleşik ilk 200'ün dışında kalıp gömmede ilk 50'ye giren kayıtları listenin başına alır. Her kaydın her sinyaldeki sırası ve sinyalin o kayıt için var olup olmadığı saklanır. Sıra yalnızca **inceleme sırasıdır**: hiçbir kaydı silmez, hiçbir karar yazmaz, hiçbir seçimi değiştirmez. Yeni model çağrısı yoktur.

**Ölçülen dayanak:** `.local/quantum-rank-fusion-2026-09-18/` (`fuse.py`, `fusion-result.json`, `missing_signal.py`, `embedding_rescue.py`). Tek konu, 1.369 kayıt, 20 pozitif: BM25 tek başına ortanca 189, dört sinyal 158, **TF-IDF'siz üç sinyal 121** (doğrulanmamış tohumla ürünün koşacağı durum budur). Fark gürültü içindedir; ölçüm birleşimin daha kötü olmadığını ve tek bir sinyalin çöküşünden koruduğunu gösterir, daha iyi olduğunu değil. `fuse.py` bu dilimin başvuru uygulamasıdır: sinyal tanımları oradan alınır, aşağıda adıyla yazılan sapmalar dışında değiştirilmez.

**Architecture:** Yeni `workflow/ranking.py` iki katmandır. Saf işlevler (`bm25_scores`, `block_scores`, `tfidf_scores`, `graph_scores`, `mean_ranks`, `fuse`, `inspection_order`) depo görmez ve yalnızca sözlük / liste alır. `rank_records(store, run, scope, vocabulary, expansion_terms)` havuzu tek sorguyla okur, saf işlevleri çağırır, sonucu `store.save_ranks` ile yazar. `flow._discovery`'nin `sw` dalında sıra şöyle olur: `_second_sources` → **`_source_similarity` (havuzun bütün iş başları için)** → **`_ranking`** → tarama. Tarama listesi `inspection_order`'a göre dizilir. Atıf grafiği için OpenAlex'in `referenced_works` alanı `sw` okumasında `select`'e eklenir ve yeni `record_references` tablosuna yazılır; ek istek atılmaz.

**Tech stack:** Python 3.12, yeni bağımlılık yok (numpy / scikit kullanılmaz; `fuse.py` de saf Python'dur). Migration **var** (`0044`). Sözleşme ve yöntem paketi değişmez; `skill_package_hash` **aynı kalır**.

## Global constraints

- `apps/web/` ve mevcut migration dosyalarına dokunma.
- **`legacy` aynı kalır:** OpenAlex isteğinin `select`'i, tarama sırası, `_source_similarity`'nin taramadan sonra ve yalnızca taranan adaylarla koşması, protokol gövdesi (`"signals": []`) ve özeti değişmez. Mevcut hiçbir testin beklentisi değişmez; istisna `sw` koşusunun adım sırasını sayan testlerdir ve her biri son iletide adlandırılır.
- **Yeni model çağrısı yok.** Sıralama adımı `code:ranking`'dir; `max_model_calls`'a dokunmaz. Ek sağlayıcı isteği de yok; tek yeni ağ işi, zaten var olan gömme çağrısının `sw`'de daha çok kayıtla koşmasıdır.
- **Sıra kayıt silmez** (SW7.2, SW8.2, ana plan §2.4): bu dilim `stage_decisions`, `model_proposals`, `selections`, `record_flags` ve `record_links`'e hiçbir satır yazmaz. `max_candidates` kesmesi bu dilimden önce de vardı ve dilim 09'a (K3) kadar kalır; değişen yalnızca kesmenin hangi sıraya uygulandığıdır. Kesmenin dışında kalan kayıt `pending` kalır ve sayılır.
- **Gömmenin yetkisi yok** (SW8.2): eşik değildir, kayıt eklemez, çıkarmaz. Gömme kapalıyken, modeli yokken ya da çağrısı başarısızken dört kod sinyali **aynı sıralarla** koşar (SW8.5); koşu durmaz ve duraklamaz.
- **Ham puanlar sinyaller arasında toplanmaz** (SW7.1); yalnızca sıralar birleşir.
- **Elle seçilen her eşik adlı sabittir** ve protokolün `thresholds.ranking` alanına girer (§2.7). Koda çıplak sayı olarak 15, 50, 200, 1,5 ya da 0,75 yazılmaz. `RRF_K` tek tanımından okunur (`thresholds.rrf_k` zaten gövdededir), yinelenmez.
- Belirlenimcilik (SW14.6): hiçbir sonuç küme yinelemesine, satırların okunma sırasına ya da hash tohumuna bağlı olamaz. Sinyal içi eşitlik ortalama sıra alır; son sıradaki eşitliği `source_version_id` bozar.
- Ürün koduna konuya özgü sözcük girmez. Testlerde ağ yok; fikstürler SYNTHETIC ve en az iki alandan.
- Başlamadan kontrol et: son karar `D78`, son migration `0043`. Bu dilim `D79` ve `0044` alır.

## Dosya yapısı

Yeni: `backend/deixis/storage/migrations/0044_record_references.sql`, `backend/deixis/workflow/ranking.py`, `tests/test_record_ranking.py` (saf işlevler), `tests/test_ranking_flow.py` (`create_app` ile), `.local/sw-ranking-replay-2026-09-21/` (Task 6; depoya girmez).

Değişecek: `backend/deixis/providers/common.py` (`ProviderRecord.references`), `providers/openalex.py`, `providers/registry.py` (`sw_options`), `backend/deixis/workflow/store.py` (`upsert_provider_source` yanında referans yazımı, `candidates` satırına `proposed`, kalıcı silme listeleri), `workflow/decisions.py` (`latest_ranking`), `workflow/flow.py`, `workflow/protocol.py`, `tests/determinism_stages.py`, `docs/decisions.md`, SW belgesi (SW7 ve SW8 durum satırları), `docs/product/sw-status.md`.

## Task 1: referans listeleri

`0044_record_references.sql`:

```sql
CREATE TABLE record_references (
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  referenced_id TEXT NOT NULL,          -- OpenAlex work id, short form (W…)
  PRIMARY KEY (source_version_id, referenced_id)
) WITHOUT ROWID;
ALTER TABLE source_versions ADD COLUMN references_read INTEGER NOT NULL DEFAULT 0;
```

`references_read = 1`, "bu kaydın listesi OpenAlex'ten okundu" demektir; liste boş da olabilir. Ayrım gereklidir: okunmamış liste ile boş liste aynı şey değildir, ama sinyal ikisinde de **yoktur** (aşağıda).

- `ProviderRecord.references: tuple[str, ...] | None = None`. `None` = sorulmadı ya da sağlayıcı vermiyor; `()` = OpenAlex listeyi boş verdi.
- `openalex.search_works(..., references: bool = False)`: `True` ise `select`'e `referenced_works` eklenir (`reference_count`'ın 05'te eklendiği kalıpla; `legacy` `select`'i bayt bayt aynı kalır). Kimlikler `provider_record_id` ile aynı kısa biçime indirilir. `registry.py`'de OpenAlex'in `sw_options`'ı `{"reference_count": True, "references": True}` olur.
- `store`: `_store_author_keywords` ve `set_reference_count`'un çağrıldığı yerde, aynı işlemde referanslar yazılır (`INSERT OR IGNORE`) ve `references_read` 1 yapılır; `references is None` ise hiçbir şey yazılmaz. 0042'nin tarih testi için konan sütun denetimi kalıbı (`_has_column`) burada da gerekir. Kaydın kendi OpenAlex kimliği zaten `identifier_mappings`'tedir (`scheme = 'openalex'`).
- Kalıcı silme: `purge_sources` (D65) ve `store.py`'deki iki tablo listesi okunur; kaynak sürümü silinirken referans satırları da silinir. Tablo araştırmaya değil kaynak sürümüne bağlıdır (`reference_count` gibi), bu yüzden araştırma purge'ü ona dokunmaz.
- 04c'nin Task 5 ölçümü yinelenir: 200'lük sayfada `record_search` referans yazımıyla ne kadar sürüyor (04c'de en yavaş sayfa 0,75 sn idi). Bir sayfa 1 saniyeyi aşarsa son iletide ilk satırlardan biri olur; yazım `executemany` ile tek seferde yapılır.

- [ ] **Tests first:** `sw` okuması `select`'te `referenced_works` ister, `legacy` okumasının `select`'i bu dilimden önceki dizgiyle aynıdır; listesi olan, listesi boş gelen ve alanı hiç taşımayan üç SYNTHETIC kayıt sırasıyla satır + `references_read = 1`, satırsız + 1, satırsız + 0 verir; aynı kayıt ikinci kez bulununca satır çoğalmaz; kaynak kalıcı silinince referansları da gider.

## Task 2: saf sinyaller (`workflow/ranking.py`)

```python
BM25_K1 = 1.5                 # fuse.py's values; not varied
BM25_B = 0.75
GRAPH_SEEDS = 15              # SW7 context: seeds code picks when the research has too few verified ones
RESCUE_OUTSIDE_TOP = 200      # SW8.1
RESCUE_EMBEDDING_TOP = 50     # SW8.1
THRESHOLDS = {"bm25_k1": BM25_K1, "bm25_b": BM25_B, "graph_seeds": GRAPH_SEEDS,
              "rescue_outside_top": RESCUE_OUTSIDE_TOP, "rescue_embedding_top": RESCUE_EMBEDDING_TOP}
CODE_SIGNALS = ("bm25", "blocks", "tfidf", "graph")
SIGNALS = (*CODE_SIGNALS, "embedding")
```

Havuzun bir satırı (saf işlevlerin gördüğü biçim): `{"id": <iş başının source_version_id'si>, "work_id", "title", "abstract": str | None, "own_ids": frozenset[str], "references": frozenset[str] | None}`. Sözcüklere ayırma her yerde `domain.vocabulary.words`'tür (`fuse.py`'nin ASCII düzenli ifadesi değil; adlı sapma 1).

- **`bm25_scores(pool, query_words)`**: belge = başlık + özet; `fuse.py` satır 17–21'in formülü, `BM25_K1` ve `BM25_B` ile. `query_words`, soru metninin ve sorguya giren bütün terimlerin (`expansion.term_rows`'un verdiği `phrase` ve `form`, ikinci turun kabul ettiği ifadeler dâhil) sözcüklerinin kümesidir. Durak sözcüğü ayıklanmaz (IDF halleder; `fuse.py` de ayıklamıyor).
- **`block_scores(pool, blocks)`**: `blocks`, blok adı → o bloğun sorguya giren biçimleri (`vocabulary.GATE_BLOCKS`; ikinci turun ifadeleri görev bloğundadır). Puan bir **çifttir**: (başlıkta en az bir biçimi geçen blok sayısı, başlık + özette geçen ayrı biçim sayısı). `fuse.py`'nin `* 100`'ü yerine çift karşılaştırılır (adlı sapma 2; sıra aynıdır, 100'den çok terimde taşma olmaz). Eşleşme sözcük **başında** aranır: dolgulu metinde `" " + biçim`, sondaki boşluk olmadan; böylece "repeater" kökü "repeaters"ı da tutar. Bu, `expansion.count_yields`'in iki uçlu eşleşmesinden bilerek farklıdır (adlı sapma 3): orada sayım, burada sıra vardır ve sağlayıcının araması da kök bulur.
- **`tfidf_scores(pool, seeds)`**: `fuse.py` satır 27–30'un vektörleri ((1 + log tf) · log(N / df), birim uzunluk), puan = kaydın **kendi işi olmayan** tohumlara en büyük kosinüsü. `df` yalnızca havuzdan sayılır; havuzda olmayan tohumun havuzda geçmeyen sözcükleri yok sayılır.
- **`graph_scores(pool, seeds)`**: `fuse.py` satır 48–49: her tohum için bibliyografik eşleşme `|R_i ∩ R_s| / sqrt(|R_i| · |R_s|)` artı doğrudan atıf (tohumun kimliklerinden biri kaydın listesinde, ya da kaydınkilerden biri tohumun listesinde; her yön 1). Kendi işinin tohumu sayılmaz. Ortak atıf (co-citation) yoktur: alıntılayan işler için istek ister (SW7 Limits).
- **Sinyalin varlığı (`available`)**: `bm25` ve `blocks` her kayıt için vardır (başlık her zaman var). `tfidf` özeti olmayan kayıt için **yoktur**. `graph`, `references` `None` ya da boş olan kayıt için **yoktur** (SW7.4). `embedding`, saklı benzerliği olmayan kayıt için yoktur. Özetsiz kayıt `bm25`'te başlığıyla puanlanır ve var sayılır: `fuse.py` böyle ölçtü; SW7.4'ün parantezindeki "özet yok" örneği TF-IDF'e uygulanır, BM25'e değil (adlı sapma 4, D kaydında yazılır).
- **`mean_ranks(scores, available)`**: 1 = en iyi; eşit puanlar ortalama sırayı paylaşır (`fuse.py::ranks`). `available = False` olanlar puanlarına bakılmadan **en sona** konur ve o kuyruğun ortalama sırasını paylaşır. Dönen: `{id: (rank: float, available: bool)}`. Eşit puanların kendi içinde dizilişi sonucu etkilemez, çünkü sırayı paylaşırlar.
- **`fuse(ranks, signals, k=RRF_K)`**: `{id: Σ 1 / (k + rank)}` verilen sinyaller üzerinden; sonuç `(-puan, id)` ile dizilmiş kimlik listesidir. Eksik sinyal toplamdan **çıkarılmaz**, son sırasıyla girer (`missing_signal.py`: çıkarmak ortancayı 158'den 171'e kötüleştirdi).
- **`inspection_order(fused, fused_code, embedding_ranks)`**: `fused` koşan bütün sinyallerin, `fused_code` yalnızca kod sinyallerinin birleşik sırasıdır (Task 3). Gömme koşmadıysa (`embedding_ranks is None`) `fused` olduğu gibi döner ve kimse kurtarılmaz. Koştuysa, `fused_code`'daki yeri `RESCUE_OUTSIDE_TOP`'tan büyük **ve** gömme sırası `RESCUE_EMBEDDING_TOP`'a eşit ya da küçük olan kayıtlar, gömme sırasıyla (eşitlikte kimlik) listenin **başına** alınır; geri kalanlar `fused`'daki sıralarını korur (SW8.1: "birleşik dört sinyal sırasının ilk 200'ü dışında"). Dönen: `(order, rescued)`.

`flow.fuse_rankings`'e dokunulmaz: o işlev pasaj sıralarını konumdan birleştirir (D27) ve eşitlik tanımaz; kayıt düzeyinde ortalama sıra gerektiği için yeni `fuse` ayrı durur. İkisi de aynı `RRF_K`'yı okur.

- [ ] **Tests first** (`tests/test_record_ranking.py`): iki alandan SYNTHETIC küçük havuzla her sinyalin beklenen sırası; eşit puan ortalama sıra alır; `available = False` kayıt puanı en yüksek olsa da sondadır; kendi işinin tohumu sayılmaz (tek tohum kaydın kendi işiyse puan 0); doğrudan atıf iki yönde de sayılır; listesi boş kayıt grafikte yoktur; sözcük başı eşleşmesi çoğulu tutar, sözcük ortasını tutmaz; tek sinyalde sonuncu olan kayıt birleşimde batmaz (SW7'nin g016 durumu, SYNTHETIC); kurtarma yalnızca iki koşul birlikte sağlanınca olur, sınır değerleri (200 / 201, 50 / 51) ayrı ayrı sınanır; havuz satırlarının sırası karışınca bütün çıktılar bayt bayt aynıdır.

## Task 3: tohumlar ve `rank_records`

**Doğrulanmış tohum:** araştırmada kullanıcının dahil ettiği kayıt (`selections.origin = 'user'` ve `state = 'included'`) ve kapsamın tohumu (`scope["seed_snapshot"]["source_version_id"]`, varsa). Modelin dahil ettiği kayıt doğrulanmış **değildir**. Havuzda olmayan tohumun metni kendi başlığı + özet pasajlarıdır; referansları varsa onlar da okunur.

- `tfidf` yalnızca en az bir doğrulanmış tohum varken koşar (SW7.5). Yoksa sinyal **hiç koşmaz**: satırı yazılmaz, birleşime girmez, adım çıktısında `"tfidf": {"ran": false, "reason": "no_verified_seeds"}` yazar.
- `graph` tohumları: doğrulanmış tohumlar, artı toplam `GRAPH_SEEDS`'e tamamlayacak kadar **kod tohumu**: `fuse(bm25, blocks)` sırasının başındakiler (`fuse.py::seedsB`), doğrulanmış tohumların işleri atlanarak. Grafik, referans listesi olan hiçbir tohum yoksa koşmaz (`"reason": "no_seed_with_references"`). Doğrulanmış ve kod tohumlarını karıştırmak ölçülmedi (ölçüm ya 15 kod tohumu ya 5 doğrulanmış tohum kullandı); plan kararıdır, D kaydında adıyla yazılır.

**Havuz:** kapsam revizyonunun adayları içinde `origin != 'user'` olan **iş başları** (`store.work_heads`), 05'in taramadan tuttuğu kayıtlar **dâhil** (sıralanırlar; tarama listesinden süzülmeleri bugünkü yerinde kalır; dilim 15 tohum havuzunu bu sıradan okuyacak). Bir işin satırı: başlık başın başlığı; özet önce başın, yoksa araştırmadaki başka bir sürümünün özeti; `references` ve `own_ids` işin araştırmadaki **bütün sürümlerinin** birleşimi (ön baskının listesi var, yayımlanmış başınki yoksa sinyal kaybolmasın). Birleşim yalnızca sıralar; hiçbir sürüm mantığına dokunmaz. Havuz **tek sorguyla** (en çok birkaç sorguyla, kayıt başına sorgu olmadan) okunur: 05 incelemesinde `held_from_screening` kayıt başına sorguyla 2.000 adayda 1,1 sn sürmüştü.

`rank_records(store, run, scope, vocabulary, expansion_terms) -> dict` adımları: havuzu ve tohumları oku → `bm25`, `blocks` → tohumları seç → `tfidf`, `graph` → gömme benzerliklerini `source_similarities`'ten oku (seçili gömme modeli için; yoksa sinyal koşmaz) → `fused_code` = koşan kod sinyallerinin birleşimi, `fused` = koşan **bütün** sinyallerin birleşimi → `inspection_order` → yaz.

Saklama, mevcut `store.save_ranks(ranking_step_id, research_id, rows)` ile tek çağrıda: koşan her sinyal için kayıt başına bir satır (`signal` = sinyal adı, `rank` = ortalama sıra, `available`), artı `fused_code`, `fused` ve `inspection` satırları (sıra = listedeki 1 tabanlı yer, `available = 1`). `save_ranks` zaten `INSERT OR IGNORE`'dur: yeniden oynatılan adım yeni satır yazmaz. Tablo değişmez.

Adım çıktısı (kanonik sıralı, kimlikler alfabetik): `{"pool", "signals": {ad: {"ran", "reason"?, "available"}}, "seeds": [{"source_version_id", "kind": "verified" | "code"}], "no_reference_list", "no_reference_list_share", "no_abstract", "embedding_model", "rescued": [...]}`. `no_reference_list_share` SW7.4'ün "her sıralamayla raporlanır" dediği sayıdır.

`decisions.py`'ye `latest_ranking(research_id, scope_revision) -> list[str] | None`: o kapsam revizyonunun **en son başarılı** `code:ranking` adımının `inspection` sırası (`record_signal_ranks` → `run_steps` → `runs.scope_revision`). Dilim 10 ve 15 bunu okuyacak; bu dilimde tek çağıranı akıştır.

- [ ] **Tests first:** doğrulanmış tohum yokken `tfidf` satırı yazılmaz ve `fused`'a girmez; kullanıcı bir kaydı dahil edince sonraki koşuda `tfidf` koşar ve o kaydın kendi işi tohumu saymaz; modelin dahil ettiği kayıt tohum olmaz; listesi yalnızca ön baskı sürümünde olan işin `graph` sinyali vardır; tutulan (05) kayıt sıralanır; sorgu sayısı havuz büyüklüğüyle artmaz (20 ve 200 SYNTHETIC kayıtta aynı sorgu sayısı).

## Task 4: akışa bağlama

`flow._ranking(run, scope, vocabulary, more) -> list[str]`, `sw` dalında `_second_sources`'tan sonra, tarama başlamadan önce:

- `code:ranking` adımı (`operation_key = "ranking"`) `succeeded` ise **yeniden hesaplanmaz**: sıra `record_signal_ranks`'ten o adımın `inspection` satırlarıyla okunur. Duraklatılıp sürdürülen koşu böylece aynı tarama partilerini görür (`screening:N` anahtarları başlangıç dizinine bağlıdır).
- Aynı kapsamda **yeni** bir keşif koşusu yeni adım açar ve yeniden sıralar (havuz büyümüş, kullanıcı tohum vermiş olabilir); eski adımın satırları durur.
- Önce `_checkpoint`. Havuz boşsa adım boş çıktıyla `succeeded` olur.
- Depo okuması ve yazması kısa eşzamanlı işlemlerdir; arada `await` yoktur. Saf hesap (Task 2 işlevleri) depo görmediği için, Task 6'daki ölçüm 1 saniyeyi aşarsa **yalnızca o kısım** `asyncio.to_thread` ile koşar; aşmıyorsa eklenmez.

**Gömme (SW8.1–2, "mevcut `_source_similarity` yeniden kullanılır"):** `sw`'de `_source_similarity`, `_ranking`'den **önce** ve havuzun bütün iş başlarıyla çağrılır; taramadan sonraki çağrı `sw`'de kalkar (aynı kayıtları bir daha saymasın), `legacy`'de olduğu yerde ve olduğu gibi kalır. İşlevin kendisi değişmez: zaten puanı olanı atlar, hata verince adımı `failed` yazar ve döner. Başarısız ya da kapalı gömme = sinyal koşmaz, kurtarma kolu koşmaz, dört kod sinyalinin sıraları gömmesiz koşuyla **aynıdır** (testi zorunlu).

**Tarama listesi:** `store.candidates` satırı `proposed` (`s.proposal IS NOT NULL`) alanını da döndürür; SQL sırası değişmez, `legacy` onu olduğu gibi kullanır. `sw`'de `_discovery` süzgeçten (kullanıcı kökenli değil, iş başı, tutulmuyor) geçen adayları `(proposed, inspection konumu)` ile dizer, sonra `[: max_candidates]` keser. Sırada olmayan aday (olmamalı; sürdürülen koşuda sıralamadan sonra eklenen sürüm başı olabilir) sona, `candidates`'ın kendi sırasıyla konur.

**Protokol:** `build_protocol(..., embedding_model: str | None = None)`. `sw` gövdesinde `signals` dolar:

```json
[{"signal": "bm25"}, {"signal": "blocks"},
 {"signal": "tfidf", "seeds": "verified"},
 {"signal": "graph", "seeds": "verified_then_code"},
 {"signal": "embedding", "model": "<stored_model ya da null>", "rescue": true}]
```

ve `thresholds.ranking = ranking.THRESHOLDS` (yalnızca `sw`'de). Protokol aramadan önce donduğu için burada **yapılandırma** durur; hangi sinyalin gerçekten koştuğu sıralama adımının çıktısındadır. `embedding_model`, akışın `embeddings.chosen(self.store.setting("semantic_search"))` ile okuduğu `stored_model`'dir (kapalıysa `None`); `build_protocol` depo görmediği için akış verir. **`_discovery`'deki `protocol` adımı ve `_freeze_expansion` aynı değeri vermelidir**; ikincisi vermezse genişleme revizyonu gömmeyi `null`'a çevirir (dilim 06'daki ölçüt tuzağının aynısı; testi zorunlu). `signals` `CRITERION_FIELDS`'te değildir, yani gömme ayarını değiştirmek hiçbir kararı eskitmez; bu istenen davranıştır ve testle sabitlenir.

- [ ] **Tests first** (`tests/test_ranking_flow.py`): `sw` koşusunda tarama adayları sağlayıcı sırasıyla değil `inspection` sırasıyla gider (sağlayıcının sonda verdiği ama sinyallerde önde olan SYNTHETIC kayıt ilk partidedir); `max_candidates` kesmesinin dışında kalan kayıt `pending` kalır ve hiçbir tabloda satırı silinmez; bu dilimin adımından sonra `stage_decisions`, `model_proposals`, `record_flags`, `record_links` ve `selections` satır sayıları ve içerikleri adımdan öncekiyle aynıdır; model her çağrıda hata verirken sıralama yine koşar ve satırları yazar; gömme kapalı, gömme başarısız ve gömme açık üç koşuda dört kod sinyalinin satırları bayt bayt aynıdır; gömme açıkken kurtarılan kayıt listenin başındadır ve `rescued`'da adı geçer; duraklatılıp sürdürülen koşu yeniden sıralamaz ve aynı partileri tarar; aynı kapsamda ikinci keşif koşusu yeni adım açar, eski satırlar durur, `latest_ranking` yenisini verir; genişleme revizyonu `signals`'ı taşır; `legacy` araştırmada sıralama adımı açılmaz, `_source_similarity` eski yerinde koşar ve protokol özeti bu dilimden önceki değerle aynıdır; gömme ayarı değişince `decisions.is_stale` hiçbir kararı eskimiş saymaz.

## Task 5: tekrar aşaması

`tests/determinism_stages.py`'ye `record_ranking` aşaması: sabit SYNTHETIC havuz (eşit puanlı çiftler, referanssız ve özetsiz kayıtlar, iki tohum), karıştırılmış satır sırası, iki hash tohumu; tek özet. `rows` yolu küme yinelemesi tuzağını (referans kümeleri, sorgu sözcükleri kümesi) sınamalıdır.

## Task 6: dilimi kapat

- [ ] **Ağsız yeniden oynatma (zorunlu, istek yok, model yok):** `.local/quantum-rank-fusion-2026-09-18/round.json` (1.369 gerçek kayıt, referans listeleri, blok terimleri ve prob etiketleriyle) ürünün **saf işlevlerinden** geçirilir; betik ve çıktı `.local/sw-ranking-replay-2026-09-21/`'e yazılır. Beklenti koşudan **önce** aynı klasörde `expectation.md`'ye dondurulur: doğrulanmış tohum yok, yani üç sinyal (BM25, bloklar, 15 kod tohumuyla grafik); `fuse.py`'nin `rrf_no_tfidf` sonucu 20 pozitifte ortanca 121, ilk 100'de 9, ilk 200'de 12. Sözcüklere ayırma ve eşleşme kuralı farklı olduğu için birebir eşitlik beklenmez; beklenti "ortanca 100–160 aralığında ve BM25 tek başına sonuçtan (189) kötü değil"dir. Son iletiye: ortanca, ilk 100 / 200 sayıları, referans listesi olmayan kayıt payı, `fuse.py` ile fark ve **süre** (saf hesabın toplamı; 1 saniyeyi aşıyorsa Task 4'teki `to_thread` eklenir ve süre yeniden yazılır). Sonuç beklentiyi tutmazsa sabitler ve kurallar **ayarlanmaz**; son iletinin ilk cümlesi bu olur. Bu tek konuluk bir tutarlılık denetimidir, ölçüm değildir (ölçüm dilim 24'te, iki konuda).
- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `git diff --check`.
- [ ] `docs/decisions.md` en üste `## D79 — Order the inspection list by rank fusion of four code signals and an optional embedding signal, store every record's rank in every signal, and never cut by it`. Limits adıyla söylemeli: yalnızca `sw`; sıra kayıt silmez ama `max_candidates` hâlâ keser ve artık bu sıraya göre keser (dilim 09, K3); tek konuda, 20 pozitifle ölçüldü ve birleşimin BM25'ten iyi olduğu gösterilmedi; doğrulanmış tohum yokken TF-IDF koşmaz; doğrulanmış ve kod tohumlarının karışımı, sözcük başı eşleşmesi, özetsiz kaydın BM25'te başlıkla puanlanması ve sürümler arası referans birleşimi ölçülmedi; ortak atıf yok; referans listesi yalnızca OpenAlex'ten, başka sağlayıcının tek başına bulduğu kayıtta grafik sinyali yok; k = 60 değiştirilmedi; 200 ve 50 tek veri kümesinde seçildi; gömme `sw`'de artık taramadan önce ve bütün havuz için koşuyor (daha çok istek, ücretsiz anahtarın hız sınırı ölçülmedi, tek parti başarısız olursa sinyal bütünüyle yok); sinyal verimi (SW7.6, SW8.7) raporlanmıyor (dilim 19); sıra hiçbir ekranda yok.
- [ ] SW belgesinde SW7 ve SW8 **Status** satırlarına birer cümle. `sw-status.md` satır 07: `uygulandı, inceleme bekliyor` + açık kalanlar. Tek commit, `git push origin main` (ana plan §2.11).

## Son ileti

Yeniden oynatma beklentiyi tutmadıysa önce o. Eklenen ve değişen dosyalar; temel ve son test sayıları ve komut; `skill_package_hash`'in değişmediği; yeniden oynatmanın dökümü ve süre; referans yazımıyla sayfa başına `record_search` süresi; gömme kapalıyken dört sinyalin aynı koştuğunu ve sıranın kayıt silmediğini gösteren testlerin adları; adım sırası yüzünden güncellenen her mevcut test; yazıldığı gibi yapılamayan her şey ve seçilen her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: yok; `sw` protokol gövdesi `signals` ve `thresholds.ranking` kazanır, tarama sırası değişir); canlı servise ve ürün veritabanına dokunulmadığı; commit özeti.

## Açık noktalar

- **Kesme artık sıraya göre:** dilim 09 (K3) `max_candidates`'ı `sw` için kaldırana kadar, sıranın dışında bıraktığı pozitif taranmaz. SW7'nin ölçümünde en iyi sıra bile 20 pozitifin 12'sini ilk 100'ün dışında bıraktı; bu dilim o kaybı sağlayıcı sırasına göre azaltabilir ya da artırabilir, ölçülmedi.
- **Özetsiz kayıt ve BM25** (adlı sapma 4): SW7.4 "özet yok"u eksik sinyal örneği sayıyor; plan bunu TF-IDF'e uyguladı, BM25'e değil, çünkü ölçüm başlıkla puanladı ve blok sinyali zaten başlığı okuyor. Sahip başka türlü isterse tek satırlık değişikliktir.
- **Gömmenin yeri ve bedeli:** bugün gömme taramadan sonra, en çok `max_candidates` kayıtla koşuyor; `sw`'de binlerce kayıtla ve taramadan önce koşacak. Yerel sağlayıcıda SW8 1.369 kayıt için yaklaşık iki dakika ölçtü. `_source_similarity` partiler arasında kısmi sonuç saklamıyor ve 429'da beklemiyor (SW8 Limits bunu uygulamaya bıraktı); bu dilim işleve dokunmuyor, düzeltme dilim 21'le birlikte düşünülmeli.
- **Arayüz:** sinyal sıraları, "gömme kolundan" etiketi ve referans listesi payı hiçbir ekranda yok (dilim 08 / 20); kaynak listesinin "Most relevant" sırası hâlâ yalnızca gömme benzerliğini okuyor. `views.py`'ye bu dilimde dokunulmaz.
- **Sinyal verimi ve kapatma** (SW7.6, SW8.7) dilim 19'dadır; bu dilim yalnızca onun okuyacağı satırları yazar.
- **Zincirlenen kayıtlar** (dilim 15) ve başka kolların getirdikleri aynı havuza girer ve bir sonraki keşif koşusunda sıralanır; koşu içinde ikinci bir sıralama yoktur.
