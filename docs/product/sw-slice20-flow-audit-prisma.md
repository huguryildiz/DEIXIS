# SW dilim 20 — Akış sayıları, denetim örneği, ezme sayısı, PRISMA-S dökümü

**Tarih:** 25 Eylül 2026. **Durum:** plan; Sol iki tur işlendi (ikinci tur "düzeltmeyle hazır"). Sahip A ve B'yi cevaplamadan
uygulama başlamaz. **İkinci görüş:** `gpt-6-sol` · high, salt okunur (`sol-plan.md`; "hazır değil", 8 bulgu; testleri
koşmadı). Eşgüdümcünün hükmüyle sekizi de kabul edildi ve aşağıya işlendi: (1) denetim cevabı D96 yazıcısının açık
satırına sığmıyor → ayrı denetim dalı ve uç noktaları, üyelik, karar sürümü ve jeton işlem içinde (karar 6); (2) yanıt
başındaki görüntü ile modele verilen girdi ayrı (karar 3); (3) ezmenin karşılaştırma anı insan satırından kesin önce,
liste düzenlemesinde `selection_history` anı (karar 4); (4) A1'de özet katmanları "gösterim ve elle seçim", denetim
toplamlarının dışında (karar 6, soru A); (5) örnek durumsuz kalır, migration yok; "güncel örnek" ile "önceki denetim
cevapları" ayrı, oran yok, kayma sınır olarak yazılı; işlem içi denetimin süresi kabulde 0,5 sn bütçeyle ölçülür (karar
5, 7, 10); (6) PRISMA-S madde 2, 7, 9, 12, 15, 16 daraltıldı, toplu sayı ile satır izi ayrı, "kayıt yok" hiçbir zaman
"yapılmadı" diye yazılmaz (karar 8); (7) madde 15'in birimi ve başarısızlık tanımı sabitlendi, sayılar yeniden
hesaplandı (sayı 7; `item15.py` → `item15.json`); (8) süreler "plan yardımcısı ölçümü" diye etiketlendi, gerçek süreler
kabulde; prompt deponun git adımlarını korur ama yalnız dilimin dosyalarını açık yolla sahneler. **İkinci tur**
(`sol-plan-2.md`): "düzeltmeyle hazır", 4 bulgu (ilk sekizi kapandı, Sol `item15.py`'yi yeniden koşup aynı sonucu
aldı); dördü de Sol'un önerdiği gibi işlendi: (1) denetim cevabı D96'nın geri alma yolundan erişilemez; kökeni karar
kimliğiyle doğrulanır, D96'nın "karar verilenler" listesine girmez, D96 geri alması onu 409 ile reddeder (karar 6);
(2) madde 16'da `candidate_hits` "ayrı dönen kayıt" değil, "izlenen aday sürümleri / isabetleri"; ayrı dönen
sağlayıcı kaydı sayısı `null` / kayıt yok (karar 8); (3) koddaki yokluktan çıkan `not_performed` olgusu sürümlü ayrı
bir `code_source` alanında, `trace` yalnız satır kimliği (karar 8); (4) uyarı daraltıldı (karar 3). **Üçüncü tur** (`sol-plan-3.md`):
"düzeltmeyle hazır", 3 bulgu, üçü de işlendi: (1) iki geri alma yolu da kökeni karar kimliğine bağlı olaydan pozitif
doğrular, olay yok ya da çelişkiliyse ikisi de 409, `via`'sız eski D96 olayı D96 kökenlidir; (2) uyarı "dahil
kaynakların durumu değişti" (PDF kaldırma da `selection_revision`'ı artırır); (3) `code_source` kaynak dosyanın içerik
özetini (`sha256`) taşır. **Dördüncü tur** (`sol-plan-4.md`): "düzeltmeyle hazır", 2 bulgu, ikisi de işlendi:
(1) D96'nın geri alma yoluna köken denetimi eklendiği açık yazıldı (geçerli eski kararların sonucu korunur), `via`'sı
`audit` dışında bir değer taşıyan olay `origin_unknown`; (2) `code_source.sha256` modül yüklenirken sabitlenir, dökümde
disk farklıysa kod kökeni doğrulanmış gösterilmez. **Prompt:** [sw-slice20-prompt.md](sw-slice20-prompt.md). **Ana dosya:** [sw-status.md](sw-status.md).
**Karar:** yeni D numarası (dilim yazar; en yüksek D101). **Önkoşul:** 16 (D96) ve 19 (D101), ikisi de kapandı / uygulandı.
**Tür:** Kur. **Uygulayan:** Opus · high (satır 20 medium diyordu; denetim satırları D96'nın cevap yazıcısını, jetonunu ve
geri almasını kullandığı ve yanıt koşusuna bir kod adımı eklendiği için köşe durumlarında yargı gerekir). **İnceleme:**
toplu (Sol · high). **Plan:** Opus 5.5 · high (plan turunun kuralı Fable · high; bu oturum Opus'ta koştu). **Ölçüm:**
`.local/sw-slice20-plan-2026-09-25/` (`protocol.md` önce yazıldı; `measure.py` → `measure.json`, `summary.py` →
`summary.txt`, `extra.py` → `extra.json`, `item15.py` → `item15.json` (Sol'dan sonra), `result.md`; kopyalar oturum dizininde 0052'ye göç ettirildi, ürün kodu
`d96e41d` ile okundu, silindi; model, ağ, port ve canlı veri dizini yok). **Kapsam:** SW11.8, SW11.12, SW11.13; PRISMA-S
dökümü (SW belgesinde yok, sahibin 20 Eylül 2026 isteği, ana planın 20. maddesi); ana ekrandaki derinlik metni (satır
20'nin 21 Eylül plan notu).

**Goal:** Bir `sw` araştırması bugün kaç eserin dahil edildiğini, kuyrukta kaç satır olduğunu ve kaç eserin PDF beklediğini
ayrı ayrı sayıyor, ama bir eserin akışın neresinde durduğunu tek yerde söylemiyor; yanıt kuyruk boşalmadan istenebiliyor
ve yanında bunu söyleyen bir satır yok. Kişinin kodu ya da modeli kaç kez değiştirdiği hiçbir yerde sayılmıyor ve
kuyruğa gitmemiş kararlara bakmanın bir yolu yok. Arama yöntemini bir makaleye yazmak için saklı kayıtlardan bir döküm
yok. Bu dilim beş şey kurar: (1) revizyonun her eserini tek bir kovaya koyan akış sayıları, araştırma görünümünde ve her
yanıtın yanında o anki haliyle; (2) kişinin kararlarının kodun ya da modelin kararına göre sayımı (ezme sayısı); (3)
kuyruk dışında kod ya da modelin kapattığı kararlardan, tekrarlanabilir bir özetle çekilen küçük bir denetim örneği;
(4) saklı kayıtlardan üretilen, 16 maddelik PRISMA-S kontrol listesine eşlenmiş bir döküm (Markdown ve JSON); (5) ana
ekranın derinlik açıklamasını `sw` akışının gerçek sınırlarıyla söyleten metin.

## Bugün kod ne yapıyor

Kod 25 Eylül 2026'da okundu (`workflow/flow.py` `_answer`, `views.py`, `queue.py`, `probes.py`, `decisions.py`,
`waiting.py`, `report/review_methodology.py`, `domain/reason_codes.py`, `domain/rules.py`, `api/app.py`,
`apps/web/src/Home.tsx`, `ResearchView.tsx`, `Transcript.tsx`; migration `0038`, `0049`, `0051`, `0052`).

- **Yanıt.** `_answer` `store.included_works` ile seçimi `included` olan işlerin başlarını okur. `sw`'de seçim
  `DecisionStore.derive_selections` ile işin sonucundan türer (`include` → `included`; D71) ya da kişinindir. Kuyruk
  doluyken yanıt istemeyi engelleyen bir şey yok. Yanıt, dayandığı akışın sayılarını saklamıyor ve göstermiyor. D96'nın
  planı "eskimiş bir insan `include`'u yanıtta dahil kalır; yanıtın bunu işaretlemesi dilim 20'nin akış sayılarının
  işidir" diye bırakmıştı.
- **Sayılar.** `research_view.counts`: `found`, `unread`, `unique`, `included` / `excluded` / `pending` (başın seçimi),
  `inspected`, `cited`; `sw`'de `queue`, `look_again` (D96) ve `waiting_for_pdf` (D99). `probes` (D101) kişi probunu,
  anlaşarak dahil edilenleri ve getirilen eserleri sayar. Eserleri aşama ve nedene göre bölen bir sayım yok. Transcript'in
  tarama evresi "X included · Y excluded · Z undecided" yazar (seçim sayıları).
- **Kişinin kararları.** Kuyruk cevabı `stage_decisions`'a `decided_by = human` bir tam metin kararı, başın seçimine
  `origin = user` ve `human_selection_links`'e bir bağ yazar (D96). Cevaplar: `include`, `criterion_not_met`, `not_sure`,
  `pdf_wrong`, `pdf_confirmed` (SW11.11 D96'da kuruldu; SW11'in durum satırı "kurulmadı" diyor, kapanışta düzeltilir).
  Kaynak listesindeki düzenleme yalnız seçimdir, `selection_history`'ye `origin = user` satırı yazar; baş kopyasının
  satırı ayrılmış gerekçe metniyle tanınır (D101). İnsan kararının kapattığı kod ya da model kararı saklıdır:
  `DecisionStore._insert` kapananın `superseded_at`'ini yeninin `created_at`'iyle aynı damgayla yazar; `undo_human`
  bunu okur. Ezme sayısı yok. Dilim 16'nın notu: "Dilim 20'nin ezme sayısı iki kaynağı da okumalı."
- **Denetim.** Kuyruk yalnız `human_queue` yönlü altı kod ve `versions_disagree` satırlarını gösterir. İki koşunun
  anlaşarak dahil ettiği ya da dışladığı bir eseri, ya da özet aşamasında kapsam dışı sayılan bir kaydı kişiye gösteren
  bir yol yok.
- **PRISMA-S.** Üründe döküm yok. `report/review_methodology.py` (P6 raporu) sağlayıcıları, sorguları ve zincir
  paragrafını (PRISMA-S madde 5) bir yöntem paragrafına yazar. `scripts/isolated_hybrid_search.py:402-427`'deki sabit
  liste ürün kodu değildir ve kopyalanmaz. Saklı olan: `protocol_records` (`compiled_queries` köken ve sağlayıcıyla,
  `budget`, `citation_chaining`, `approval`, `code_version`, iki kayıt: donma ve veri genişlemesi), `search_runs` (sayfa
  başına: `query_text`, `request_description` alan / sayfa boyu / sıralama, anahtar yok; `status`, `result_count`,
  `provider_total`, `read_limit`, `unread_count`, `stop_reason`, `retrieved_at`), `candidate_hits` (D93), `record_links`
  (kural ve kaynakla), `code:chain_summary` adımı, `corpus_memberships.added_by`, bağlayıcı tablosu (`registry.py`).
- **Ana ekran.** `Home.tsx` `effortOptions` her efor için tek bir sabit metin gösterir ("Up to 3 searches of 400
  results, 20 candidates, 16 passages" …). Bunlar `legacy` sınırlarıdır. Hangi akışın kullanılacağı sunucunun ortam
  değişkenidir (`DEIXIS_SEARCH_WORKFLOW`); ana ekran bunu bilmiyor. `sw`'nin sınırları `rules.py`'de: sorgu başına okuma
  400 / 1.000 / 1.000 (`SW_READ_LIMIT`), özet okuma 40 / 100 / 300, tam metin getirme 80 / 100 / 300, okuma 40 / 50 /
  150 iş (iş başına iki çağrı), zincirin özet okuması 20 / 50 / 50, yanıt pasajı 16 / 48 / 80.

## Elimizdeki sayılar

46 saklı `sw` araştırması okundu; 18a ve iki 18b kütüphanesi 17a `quick`'in kopyası, 43 kaldı. Güncel revizyonunda eser
olan 40 (üç sepsis araştırması özet aşamasından önce durdu); 30'unda tam metin okuması var.

1. **Akış bölümlemesi her araştırmada tutuyor.** Aşağıdaki karar 1'in geçici kuralıyla her eser tam bir kovaya düşüyor
   (46 / 46) ve aynı anlık görüntüde ürünün kendi sayılarına eşit: anlaşarak dahil = D101 `included` sütunu, kişi onayı
   = D101 `verified`, kuyrukta = D96 `queue`, bakılacak = D96 `look_again`, PDF bekliyor = D99 `waiting_count`; 46'da
   0 fark.
2. **Kovalar** (okuması olan araştırmalar, en az–en çok): kuantum `quick` (12; 695–7.270 eser) anlaşarak dahil 1–14,
   ölçüt yok 0–5, kuyrukta 0–21, PDF bekliyor 0–67, okunmayı bekliyor 0–13, tam metni hiç denenmemiş aday 117–927, özeti
   okunmamış 237–1.715, özetten karar çıkmamış 36–2.592, derleme 8–61, kapsam dışı (model) 1–12, (kod) 1–1.928 (üst uç 22
   Eylül duman kütüphaneleri); `standard` (8) dahil 2–19, ölçüt yok 0–12, kuyruk 3–40, PDF 55–77; `detailed` (5) dahil
   16–37, kuyruk 34–100, PDF 32–225; paket `quick` (5) dahil 1–3, ölçüt yok 2–4, kuyruk 1–4. "Özetten karar çıkmamış"
   43 araştırmada toplam `no_abstract` 13.565, `abstract_not_found` 8.018, `runs_agree_unresolved` 11.
3. **Örnek, 17a `standard` (2.592 eser):** 19 anlaşarak dahil, 7 ölçüt yok, 25 kuyrukta, 58 PDF bekliyor, 1 okunmayı
   bekliyor, 414 tam metni denenmemiş aday, 1.739 özeti okunmamış, 218 özetten karar çıkmamış, 30 derleme, 30 + 51 kapsam
   dışı (model + kod). PRISMA'ya benzer kutular: dönen 5.336 satır → 2.592 eser → modelin okuduğu 149 özet → tam metni
   aranan 112 → alınamayan 58 → okunan 50.
4. **Kişinin kararı neredeyse yok.** Açık insan kararı 4, 2 araştırmada (dilim 16 kabul çifti: birer `human_include`,
   birer `human_criterion_not_met`); dördü de makinenin açık bıraktığı kuyruk satırını kapattı, hiçbiri bir makine
   kararını değiştirmedi. Kişinin kendi liste düzenlemesi hiçbir yerde yok; eskimiş kişi kararı yok. Ezme sayısı bugün
   her saklı araştırmada "0–2 kararın 0'ında değiştirdiniz" der; kategorileri yalnız sentetik testlerle sınanır.
5. **Denetim katmanları** (okuması olan 30): anlaşarak dahil 1–37 (hiç boş değil), anlaşarak ölçüt yok 0–12 (13'ünde
   boş), özet aşamasında kapsam dışı (model) 1–90, (kod) 0–1.928 (güncel akış kütüphanelerinde 12–587). Katman başına 3'lük
   özet örneği 6–12 satır verir; başlar ters sırayla okununca örnek aynı (46 / 46).
6. **Yanıt zaten yalnız `include` işlere dayanıyor.** Seçimi `included`, sonucu `include` olmayan ve seçimi kişinin
   olmayan baş 46'da 0. Ayrı 43 araştırmanın 24'ünde saklı yanıt var (19 `structurally_valid`, 5 `unverified_draft`);
   bunların 23'ünde kuyruk bugün boş değil. Hiçbiri yanıt anındaki akışı saklamadı.
7. **PRISMA-S'in girdileri saklı.** Her arama satırında istek açıklaması var. 40 revizyonun 390 ayrı anahtar sözcük
   sorgusunun 390'ı bir protokol kaydının `compiled_queries`'inde. **Birim (Sol bulgu 7'den sonra sabit):** bir anahtar
   sözcük sorgu grubu = (koşu, sağlayıcı, `query_text`) ve sayfaları, sayfa sırasıyla; grup son sayfası `completed` ya da
   `zero_results` ise "tamam" biter, herhangi bir sayfası kayıt döndürdüyse "okudu" sayılır. Zincir istekleri
   (`query_text` `chain:…`) aynı biçimde ama ayrı gruplanır. 390 anahtar sözcük grubundan 261'i tamam bitti (250
   okudu, 11 sıfır sonuç), **129'u bitmedi**: 88 hız sınırı yüzünden hiçbir şey okumadı, 22 okuduktan sonra hız sınırına
   takıldı, 11 başarısız, 6 yetki eksik (3'ü okumadan), 2 zaman aşımı. Araştırma düzeyinde: tamam bitmeyen grup **40 /
   40**'ta var (madde 15 kuralıyla hepsi `incomplete`); hız sınırı yüzünden hiçbir şey okumayan grup 33 / 40'ta; herhangi
   bir nedenle hiçbir şey okumayan grup 37 / 40'ta; okuyup sonra duran grup 17 / 40'ta; en az bir hız sınırı satırı 40 /
   40'ta. Zincirin 294 grubunun hiçbiri hata ile bitmedi (15 araştırma). Okuma sınırı 400 (17), 1.000 (17), 2.000 (6);
   hepsinde sınır yüzünden okunmadan kalan kayıt var (bu bir sınırdır, hata değil). Zincir özeti 15'inde, veri genişlemesi 40'ında; revizyon başına tek
   keşif koşusu, iki protokol kaydı. Onay `user` 37, `setting` 3. Kişinin getirdiği eser hiçbirinde yok. bioRxiv (OpenAlex
   üzerinden) 7'sinde. Kayıt defteri (registry) bağlayıcısı yok.
8. **Maliyet, plan yardımcısı ölçümü** (en büyük dört ayrı araştırma, 6.173–7.270 eser; bir ısınma çağrısı, 5 tekrarın
   ortancası): bir kuyruk bağlamı ve prob seti 0,131–0,156 sn (dilim 19'dan beri `research_view` zaten ödüyor); bağlam
   verilmişken `measure.py`'nin geçici akış + ezme + denetim işlevleri 0,007–0,015 sn; `prisma()` veri özeti 0,002–0,005
   sn. Bunlar ön fizibilitedir: ürünün gerçek görünüm, 16 maddelik Markdown / JSON dökümü ve denetim cevabının yazma
   işlemi ölçülmedi; kabulde ölçülür (karar 10).

Sayıların gösteremediği: kişinin bunları okuyup kullanıp kullanmadığı; denetim örneğinin yanlış karar bulup bulmadığı
(hiç cevaplanmadı); üçüncü bir alan; canlı hiçbir şey.

## SW maddeleri: kurulan, açık kalan

| Madde | Bugün | Bu dilimde |
|---|---|---|
| SW11.8 kuyruk boyu ve neden dağılımı | Var (D96 `counts.by_reason`) | Akış bloğunda ve PRISMA-S dökümünde de (karar 1, 8) |
| SW11.8 kuyruk dışı kararlardan küçük denetim örneği | Yok | Tam metin katmanları için kurulur, ayrı denetim dalıyla (karar 5–7); özet katmanları A1'de yalnız gösterim ve elle seçim, denetim toplamlarının dışında; özet dışlamasını tam metne geri gönderme açık gereksinim (soru A) |
| SW11.12 yanıt yalnız `include` işlere dayanır | Tutuyor (sayı 6) | Değişmez; bir testle sabitlenir (karar 3) |
| SW11.12 kuyruk boşalmadan yanıt; akış sayıları | Yanıt istenebiliyor, sayı yok | Yanıt koşusu başındaki seçim ve akış görüntüsünü bir kod adımında saklar; modele verilen girdi ayrı gösterilir (karar 3) |
| SW11.13 kişinin kodu / modeli kaç kez ezdiği | Yok | Kurulur, iki kaynaktan (karar 4); denetim örneğindeki ayrı (karar 7) |
| SW11.13 insan kararı prob setine girer | D101 | Aynen |
| SW16.4 kapının kapattığı işler denetim örneğine | Kapı yok | Yok (dilim 23 bu katmanı ekler) |
| SW11.11 "emin değilim" / "PDF yanlış" | D96'da kuruldu | Durum satırı düzeltilir |
| PRISMA-S dökümü (SW dışı) | Yok | Kurulur (karar 8) |
| Ana ekran derinlik metni (satır 20 notu) | `legacy` sınırları | `sw` için `rules.py`'den (karar 9) |

## Kararlar

1. **Akış sayıları: revizyonun her eseri tek bir kovada** (`workflow/flow_counts.py`, okunurken türetilir, saklanmaz;
   kuyruk ve prob seti gibi). Birim iştir: güncel revizyonun üye işleri (`facts["heads"]`). Öncelik:
   - **Önce kişi, D101'in tek öncelik kuralıyla** (`probes.probe_set`): `confirmed` (onaylı pozitif: kuyrukta `include`
     ya da listede `included`), `person_not_met` (kuyrukta `criterion_not_met`), `person_excluded` (listede `excluded`,
     türü kaydedilmedi), `look_again` (eskimiş kuyruk cevabı).
   - **Sonra işin sonucu** (`work_outcome`, aynı bağlamın sonucu), aşama ve neden koduyla. Kova neden kodundan ve
     tablonun `next_step`'inden gelir, çağıranın yorumundan değil:

   | Kova | Kural | Ekran adı (i18n, İngilizce kaynak) |
   |---|---|---|
   | `included` | tam metin `include`, `model_agreement` | Included by two agreeing runs |
   | `not_met` | tam metin `criterion_not_met`, `model_agreement` | Criterion not met (two agreeing runs) |
   | `queued` | `next_step = human_queue` ya da `versions_disagree` | In your queue, not looked at |
   | `person_unsure` | `human_not_sure` | You were not sure |
   | `waiting_for_pdf` | `next_step = waiting_for_pdf` (`no_fulltext`, `text_unreadable`, `human_pdf_wrong`) | Waiting for a PDF |
   | `not_read_yet` | `not_read_yet` | Text in hand, not read yet |
   | `candidate_not_fetched` | özet `candidate`, tam metin kararı yok | Passed the abstract stage, full text not tried |
   | `abstract_open` | `no_abstract`, `abstract_not_found`, `runs_agree_unresolved` | Abstract could not decide |
   | `abstract_not_read` | `abstract_not_read`, `abstract_not_proposed` | Abstract not read |
   | `survey` | `survey_title_word` | Survey, kept for citation chaining |
   | `out_of_scope_model` / `out_of_scope_code` | özet `out_of_scope`, karar vericiye göre | Out of scope (model runs / code rule) |
   | `not_screened` | hiç karar yok | Not screened |
   | `other` | yukarıdakilerin dışı (tam metin `unresolved` başka bir yönle, kişinin seçimi sonradan `pending` yapılmış insan kararı) | Other |

   Kovaların toplamı eser sayısına eşittir; eşit değilse görünüm hatadır (testle sabit). `other` saklı veride 0; boş
   değilse neden kodlarıyla listelenir. **D93 / D101 / D96 / D99 ile tutarlılık:** `included` = D101 `included` sütunu,
   `confirmed` = D101 `verified`, `queued` = D96 `queue`, `look_again` = D96 `look_again`, `waiting_for_pdf` = D99
   `waiting_count`; beşi de aynı bağlamdan ve aynı `work_outcome`'dan okunur (sayı 1). Ayrıca `look_again_in_answer`:
   eskimiş kişi kararı olan ve seçimi hâlâ `included` olan iş sayısı; yanıt bunları okur ve bu yazılır (D96'nın bıraktığı
   iş). SW11.12'nin beşlisi bu kovalardan toplanır: dahil = `included` + `confirmed`; ölçüt karşılanmıyor = `not_met` +
   `person_not_met`; PDF bekliyor = `waiting_for_pdf`; kuyrukta bakılmamış = `queued`; tam metni okunmamış =
   `not_read_yet` + `candidate_not_fetched`. Kuyruğun neden dağılımı (D96 `by_reason`) akış bloğuna eklenir.
   **Neden:** SW11.12; eserin tek bir yerde durduğunu söylemenin en ucuz yolu var olan kararları okumak. **Sınır:**
   "okunmamış" iki kovadır ve ayrı gösterilir; `abstract_not_read`'in eseri "dışlanmadı, okunmadı"dır, olumsuz sayılmaz.
2. **PRISMA 2020'ye benzer kutular, eksik diye işaretli.** Aynı modülde, revizyon için: dönen satır (`search_runs`
   `result_count` toplamı, zincir istekleri ayrı), bir arama ya da zincir isteğinin bulduğu eser (`candidate_hits`; D93
   öncesi koşuda `null`, "sayılmadı"), revizyonun eseri, modelin özetini okuduğu eser (`model_proposals`, özet aşaması),
   özet aşamasında kapsam dışı (model / kod), tam metni aranan (bir `code:fulltext_plan`'da olan), alınamayan
   (`waiting_for_pdf`), okunan (okuma olan taze tam metin kararı; D101'in `NOT_A_READING` listesi dışında), ölçüt
   karşılanmıyor, kuyrukta, dahil. Her kutu `flow_status: "incomplete_no_human_screening"` ile gelir: taramayı kod ve
   model yaptı, insan yalnız kuyruğa ve denetim örneğine baktı. Kutular toplanmaz ve bir diyagram çizilmez. **Neden:**
   ana planın 20. maddesinin kabulü.
3. **Yanıt başındaki seçim ve akış görüntüsü, yanıt koşusunda saklanır; modele verilen girdi ayrı.** `sw` yanıt koşusu,
   `included_works` ve `selection_revision` okunduktan hemen sonra, aralarında ve adımın yazılmasına kadar `await`
   olmadan, `answer_start_snapshot` işlem anahtarlı bir kod adımı açar (`code:answer_start_snapshot`). Çıktısı: koşunun
   `scope_revision`'ı, okunan `selection_revision`, karar 1'in sayıları (kovalar, beşli, `look_again_in_answer`, kuyruğun
   nedenleri), seçimi `included` olan iş sayısı ve bunlardan `answer_version`'ı `None` olanlar (kişinin okunmamış dosyası
   yüzünden yanıta metin veremeyecek işler, D100; `included_without_answer_text`). Adım bir **görüntüdür**, yanıtın
   dayandığı eser listesi değildir: `_inspect`'ten sonra hangi eserlerin ve pasajların modele gittiğini mevcut
   `inputs_given` (`sources`, `passages`, StepInput'tan) söyler ve ekranda ayrı satırdır. Başarılı adım sürdürülen
   koşuda yeniden hesaplanmaz (koşunun başındaki hal kalır). `legacy` yanıt koşusu bu adımı açmaz. `research_view`'da
   her yanıt `start_snapshot` alanını kendi koşusunun adımından okur; adım yoksa (bu dilimden önceki 24 yanıt)
   `start_snapshot: null` ve ekran "Bu yanıtın başındaki akış kaydedilmedi" der, bugünün sayısını o yanıtın sayısı diye
   göstermez. Kuyruk doluyken yanıt istemek engellenmez, onay penceresi açılmaz (SW11.12). Yanıtın altındaki iki satır:
   "Yanıt başladığında: X eser dahildi (iki koşu Y, sizin onayınız Z); kuyrukta bakılmamış Q, PDF bekleyen P, tam metni
   okunmamış R (okuma sırasında r1, denenmemiş r2), ölçüt karşılanmıyor N." ve "Modele verilen: S eser, T pasaj."
   Görüntünün `selection_revision`'ı yanıtın kaydettiği `selection_revision`'dan farklıysa üçüncü satır "Yanıt
   sürerken dahil kaynakların durumu değişti" der. `selection_revision` bir işin `included`'a girip çıkmasıyla ve dahil
   bir kaynağın PDF'i kaldırılınca da artar (eser kümesi aynı kalabilir; `store.py`), `excluded → pending` ya da aynı
   durumda sahiplik değişimiyle artmaz; bu yüzden metin ne "seçim değişti" ne "eser kümesi değişti" der (Sol üçüncü tur
   bulgu 2); kümenin kendisini karşılaştırmak ayrı bir iş, bu dilimde yok; yanıtın mevcut `applicability` işareti aynen kalır. `look_again_in_answer > 0` ise uyarı:
   "K eser önceki ölçütle verdiğiniz bir karara dayanıyor." **Neden:** geçmiş yanıtlar yeniden yazılmaz (AGENTS.md);
   migration gerektirmeyen tek saklama yeri koşunun adımı; Sol bulgu 2. **Test:** kuyruk doluyken yanıt koşusu başlar,
   adımın sayıları o anın sayılarıdır ve adımın `scope_revision` / `selection_revision`'ı koşunun okuduğudur; koşu
   `_inspect` sırasında duraklatılıp bir iş `included` yapılır ve sürdürülür → adım aynı kalır, yanıtın kendi
   `selection_revision`'ı yenisidir ve üçüncü satır çıkar (`excluded → pending` değişiminde çıkmaz; dahil bir kaynağın PDF'i
   kaldırılınca eser kümesi aynı kalsa da çıkar ve "dahil kaynakların durumu değişti" der); kişinin okunmamış dosyası olan dahil iş
   `included_without_answer_text`'te sayılır ve `inputs_given.sources`'ta yoktur; sonra verilen bir kuyruk cevabı eski
   yanıtın görüntüsünü değiştirmez; yanıt girdisi yalnız seçimi `included` işler (sayı 6'nın sabitlenmesi).
4. **Ezme sayısı: kişinin kararı, makinenin o iş için verdiği karara göre** (`workflow/overrides.py`, okunurken). Kişi
   kararları D101'in prob setidir (onaylı pozitif → `included`, olumsuz → `excluded`); `look_again`, `not_sure` ve
   `pdf_wrong` bu sayıya girmez, ayrı sayılır. **Makinenin görüşü, kişinin karar verdiği anda** (Sol bulgu 3). İşin bütün
   sürümlerinin `stage_decisions` satırları o anki haliyle okunur (o andan önce yazılmış ve o anda henüz kapanmamış
   satırlar), insan satırları çıkarılır, kişi dosyası istisnası olmadan `work_outcome` ile çözülür. Eskime o anın
   anahtarıyla sınanır: o an geçerli kapsam revizyonu (`scope_revisions.created_at`) ve o revizyonda o ana kadar yazılmış
   son protokol kaydının ölçüt özeti. "An" iki yoldan gelir:
   - **Kuyruk ve denetim cevabı** (kişinin karar satırı `stage_decisions`'ta): aynı tablo olduğu için sıra kesindir;
     `(created_at, rowid)` sırasında insan satırından **kesin önce** yazılmış satırlar, ve o insan satırından önce
     kapanmamış olanlar. Aynı milisaniyedeki satırı `rowid` ayırır. İnsan → insan değişikliğinde karşılaştırma işin
     ilk insan kararından önceki makine görüşüyledir.
   - **Liste düzenlemesi** (aşama kararı yazmaz): başın güncel `user` seçimini yazan `selection_history` satırının
     `created_at`'i. Kararlar ile seçim geçmişi ayrı tablolardır, `rowid` karşılaştırılamaz: `created_at`'i bu anla
     aynı milisaniyeyi taşıyan bir karar varsa sınıf `time_unknown` olur (D101'in `moved_up_time_unknown` kuralı gibi).
   Böylece kişinin düzenlemesinden sonra başka bir sürüme gelen makine kararı, kişinin o gün değiştirdiği şey diye
   sayılmaz. Üç ayrık sınıf ve `time_unknown`:
   - `overruled`: makinenin görüşü bir karardı (`include`, `criterion_not_met`, `out_of_scope`) ve seçim durumu
     (`SELECTION_STATE`) kişininkinden farklı. Karar veren (`code` / `model_agreement`), aşama ve yön (`included →
     excluded`, `excluded → included`) ile ayrılır.
   - `agreed`: makine karar verdi, kişi aynı durumu seçti.
   - `settled_open`: makine açık bıraktı (`unresolved`, `candidate`, karar yok), kişi karar verdi. Bir kuyruk cevabı
     neredeyse her zaman budur; ezme sayılmaz.
   Her sınıf yola göre de ayrılır (`queue`, `audit`, `list`; `audit` karar 6'nın satırları). Ekran: "N kararınızdan M'inde
   kodun ya da modelin kararını değiştirdiniz (kod m1, model m2)". N = 0 ise "Henüz bir karar vermediniz; bu satır kodun ya
   da modelin doğruluğu hakkında bir şey söylemiyor." Yüzde yazılmaz: liste düzenlemesinde ve kuyrukta hangi esere
   bakılacağını kişi ya da kural seçti, oran değildir (karar 7 örneği ayrı gösterir). **Neden:** SW11.13 ve dilim
   16'nın "iki kaynağı da oku" notu. **Sınır:** bir işte kişi önce kuyrukta cevap verip sonra listede değiştirdiyse yalnız
   son hali sayılır (D101 önceliği), anı da liste düzenlemesinin anıdır; geçmişteki ara cevaplar sayılmaz. Baş o andan
   bu yana değiştiyse güncel baş kullanılır (`work_outcome`'da baş yalnız adlandırmayı etkiler, sonucu değil).
5. **Denetim örneği: katmanlı, özetle çekilen, durumsuz** (`workflow/audit.py`). Katmanlar (kişi probu olmayan işler,
   `work_outcome` ile): F1 tam metin `include` / `model_agreement` (`all_parts_verified`); F2 tam metin
   `criterion_not_met` / `model_agreement` (`criterion_absent`); A1 özet `out_of_scope` / `model_agreement`; A2 özet
   `out_of_scope` / `code` (`both_blocks_missing`, `notice_record`, `artifact_of_paper`). Kod kapısı katmanı yok (dilim
   23). **Genişletilmiş üyelik:** kişinin bir denetim cevabıyla kapattığı iş, cevabın kesin öncesindeki makine kararı
   (karar 4) o katmandaysa katmanda kalır. **Çekiliş:** her katmanda
   `sha256("{research_id}|{scope_revision}|{criterion_hash or 'none'}|{katman}|{work_id}")` onaltılık özetine göre en
   küçük `AUDIT_PER_STRATUM = 3` iş (adlı gösterim sabiti, protokol eşiği değil). Rastgele durum, saklı tohum ve yazılan
   satır yok: aynı saklı durum her okumada aynı örneği verir, sıra ve sözlük düzeni etkilemez (sayı 5). Revizyon ya da
   ölçüt değişince örnek yeniden çekilir. **Durumsuz kalır, migration yok** (eşgüdümcü hükmü, Sol bulgu 5): örnek
   kalıcı bir kohort değildir. Katmana sonradan daha küçük özetli bir iş girerse (sonraki okuma koşusu) örnekteki bir
   işin yerini alır; cevaplanmış bir iş örnekten düşebilir. Bu yüzden ekran iki şeyi ayrı gösterir: **güncel örnek**
   (bugünkü çekilişin satırları, cevaplı ya da cevapsız) ve **önceki denetim cevapları** (karar 6'nın uç noktalarından
   verilmiş bütün cevaplar, "şu an örnekte" ya da "örnekten çıktı" işaretiyle). İkisi toplanmaz; hiçbirinden oran ya da
   hata tahmini çıkmaz. **Sınır (yazılı):** örnek kayar; "3 satırın 2'sine baktınız" bir sonraki okuma koşusundan sonra
   değişebilir. Sonucu zaman içinde izlenecek bir denetime çevirmek çekilen kimlikleri ve anı dondurmayı, yani bir
   tabloyu ister; açık gereksinim.
6. **Denetim cevabı: ayrı bir dal, D96'nın işlem ve geri alma kurallarıyla** (Sol bulgu 1 ve 4; soru A'nın A1
   önerisi). F1 / F2'deki makine kararı açık kuyruk satırı değildir: `_state_of` ona satır üretmez, `decide` 409 verir,
   `_detail` açık satıra bağlıdır. Bu yüzden `queue.py`'ye ayrı bir denetim dalı eklenir. D96'nın uç noktaları aynı kalır ve geçerli
   eski D96 kararlarının geri alma sonucu korunur; D96'nın geri alma yolu yalnız aşağıdaki köken denetimini kazanır:
   - **Uç noktalar** (`sw`'ye özel; `legacy` ve üye olmayan kayıt 422, CSRF mevcut ara katmanda):
     `GET /api/researches/{rid}/audit` (güncel örnek, önceki denetim cevapları, katman sayıları, karar 7'nin sonucu),
     `GET …/audit/{svid}` (ayrıntı), `POST …/audit/{svid}/decision` (`{decision, note, audit_token}`),
     `POST …/audit/{svid}/undo` (`{audit_token}`).
   - **Satır ve ayrıntı.** Satır: iş, baş, sürüm, katman, makinenin kararı (`decision_id`, `reason_code`), `kind`
     (`audit_include` / `audit_not_met`), soru "Bu eser ölçütü karşılıyor mu?", `audit_token`. Ayrıntı, kuyruğun parça
     işlevleriyle (`_runs`, `_cues`, `_closest`, `_versions`) makine kararının adımından kurulur: iki koşunun etiketleri,
     alıntıları, doğrulamaları, sayfaları, gösterilen sayfalar ve pasajlar. Okuma hiçbir şey yazmaz.
   - **Jeton.** D96'nın `_token` alanları (revizyon, ölçüt özeti, işin bütün tam metin karar kimlikleri, baş ve seçim
     sürümü, üyelik, dosya ve metin izi) + katman + makine kararının kimliği.
   - **Yazma, tek işlem.** İşlemin içinde tam bağlam yeniden kurulur ve sırayla denetlenir: (i) iş hâlâ o katmanın
     güncel örneğinde; (ii) o sürümün güncel tam metin kararı hâlâ jetondaki makine kararı (karar sürümü); (iii) jeton
     eşit. Biri tutmazsa 409 `row_changed` ve hiçbir şey yazılmaz. Sonra D96'nın yazımı: `decide`'ın cevap gövdesi
     (karar, seçim, `human_selection_links`, geçmiş, olay, `derive_selection`) ortak bir iç işleve alınır ve iki dal onu
     çağırır; D96'nın dalının davranışı ve testleri aynı kalır. Cevaplar: `include`, `criterion_not_met`, `not_sure`,
     `pdf_wrong` (`pdf_confirmed` yok). Olay `stage_decision_recorded`'a `via: "audit"` eklenir; olay kararla aynı
     işlemde yazıldığı için bir kararın denetimden geldiği **karar kimliğiyle** olaylar tablosundan doğrulanır
     (`events`, `stage_decision_recorded`, `decision_id` ve `via = audit`); migration gerekmez.
   - **D96'dan ayrılık** (Sol ikinci tur bulgu 1). Denetim kökenli bir karar D96'nın kuyruk görünümündeki "karar
     verilenler" (`decided`) listesine girmez ve orada geri alma jetonu verilmez; "Önceki denetim cevapları"nda durur.
     **İki geri alma yolu da kendi kökenini pozitif doğrular** (Sol üçüncü tur bulgu 1): güncel insan kararının kimliğine
     bağlı `stage_decision_recorded` olayı okunur. `via: "audit"` → denetim kökeni; `via` alanı olmayan olay (dilim 20'den
     önce yazılmış bütün D96 olayları ve bu dilimden sonra D96 yolunun yazdıkları) → D96 kökeni. D96'nın
     `POST …/queue/{svid}/undo`'su yalnız D96 kökenli kararı geri alır; denetim kökenliye 409 `audit_decision`. Denetimin
     geri alması yalnız denetim kökenliyi geri alır; D96 kökenliye 409 `not_an_audit_decision`. Karar kimliğine bağlı
     olay yoksa, birden çok olay çelişiyorsa (biri `audit`, biri değil) ya da olayın `via`'sı var ama `audit` değilse
     **iki yol da** 409 `origin_unknown` verir,
     hiçbir şey yazmaz; hiçbir yol öbürüne geri düşmez. D96'nın uç noktaları aynı kalır ve geçerli eski D96 kararlarının
     geri alma sonucu korunur (olayları `via`'sız olduğu için D96 kökenlidir; saklı 6 insan tam metin kararının 6'sında D96
     olayı var, Sol dördüncü tur); D96'nın geri alma yoluna yalnız köken denetimi eklenir.
   - **Geri alma.** Sürümün güncel kararı denetim kökenli (karar kimliğiyle) bir insan kararı, onun `(created_at, rowid)`
     sırasında kesin öncesindeki insan dışı karar F1 / F2 kodu ve jeton eşitse: D96'nın kuralı (`undo_human` makine kararını geri getirir, bağ geçerliyse seçimi
     bırakır, olay `stage_decision_undone`). Değilse 409.
   - **Etkisi.** `include` cevabı işi D101'in `verified` sütununa taşır ve `included` sütunundan çıkarır (kişi baktı).
     Karar verilmiş iş modele yeniden gitmez (D96 kuralı).
   - **Özet katmanları (A1'de):** A1 ve A2 satırları "gösterim ve elle seçim" adıyla ayrı bir bölümdür: başlık, neden
     kodu, modelin iki koşusunun özet alıntıları. Denetim cevabı ve sonucu toplamlarına girmez. Tek eylem kaynak
     listesindeki mevcut dahil / dışla düğmesidir ve ekran bunun işi tam metne göndermediğini, doğrudan yanıt girdisine
     aldığını söyler; böyle bir seçim ezme sayısında `list` yoluyla sayılır. Denetimin bulduğu yanlış bir özet dışlaması
     böylece ölçüte göre okunmuş hale gelmez. "Tam metne geri gönder" **açık gereksinim**: bir insan özet kodu ister
     (sahip A3'ü seçerse ya da dilim 23 özet kapısını kurarsa yeniden açılır).
7. **Denetim sonucu ayrı ve oransız.** Yalnız F1 ve F2 için, katman başına: katman boyu, güncel örneğin boyu, güncel
   örnekte cevaplanan, bunlardan cevabı makineden farklı olan (karar 4'ün `overruled` sınıfı, yol `audit`); ayrıca önceki
   denetim cevapları ve farklı olanlar, ayrı satırda. Ekran "F1, güncel örnek: 3 satırın 2'sine baktınız, 1'inde farklı
   karar verdiniz" der; yüzde, aralık ya da "hata oranı" yazmaz (3 satırdan oran çıkmaz). Bu satırlar kişinin seçmediği
   tek karar kümesidir; oranı dondurulmuş bir kohortla sonraki bir dilim kurabilir.
8. **PRISMA-S dökümü** (`workflow/prisma_s.py`, `GET /api/researches/{id}/prisma-s?format=md|json`, ek olarak indirilir,
   `sw`'ye özel; `legacy` 422). Yalnız saklı kayıtlardan, güncel revizyon için; istek, model çağrısı ya da yazma yok.
   Etkin bir koşu varken de üretilir ve başlığa "koşu sürüyor; sayılar değişebilir" yazılır. Dil İngilizce (soru B).
   JSON: `checklist: "PRISMA-S"`, kaynak künyesi (Rethlefsen ve ark., Syst Rev 2021;10:39,
   doi:10.1186/s13643-020-01542-z), `generated_at`, `code_version`, `research_id`, `scope_revision`, `protocol_hash`,
   `statement`, `items` (16), `search_table`, `flow` (karar 1–2). Her madde: `number`, `name`, `status`, `text`, `values`,
   `trace`, `aggregates`, `code_source`.
   - **Durumlar.** `reported` (saklı kayıttan dolduruldu); `incomplete` (dolduruldu ama saklı kayıt bir eksik söylüyor
     ya da maddenin istediği bir parça, ör. gerekçe, saklı değil); `not_performed` (ürünün böyle bir yöntemi yok ya da
     protokol onu kapattı: protokolde okunan bir olgu `trace`'te protokol kaydının kimliğiyle; koddaki bir yokluktan çıkan
     olgu, ör. kayıt defteri bağlayıcısı ya da yayımlanmış süzgeç özelliği olmaması, `code_source`'ta); `not_recorded`
     (yapılmış olabilir, kayıt yok). Boş madde yok. **"Kayıt yok" hiçbir zaman "yapılmadı" diye yazılmaz:** ürünün
     dışında yapılabilecek her şey (gezinti, yazarla iletişim, önceki çalışmadan uyarlama, akran incelemesi, güncelleme)
     `not_recorded`'dur. Markdown ikisini farklı sözcüklerle yazar: "Not performed by DEIXIS (…)" / "Not recorded".
   - **İz.** `trace` yalnız çözülebilir satır kimlikleridir (`protocol_records:<id>`, `search_runs:<id>`,
     `run_steps:<id>`, `record_links:<id>`, `corpus_memberships:<research>/<svid>`); her biri bir tabloda tek satıra
     çözülür. `aggregates` toplu sayılardır: `{table, filter, count}` (ör. `record_links`, `link_kind = same_work AND
     merged = 1 AND closed_at IS NULL`, araştırmanın etkin üyeleri); yeniden koşulabilir bir tanımdır, kimlik değildir.
     `search_table`'ın her satırı (sorgu grubu, sayı 7'nin birimi) bütün sayfa kimliklerini taşır. **`code_source`**
     (Sol ikinci ve üçüncü tur bulgu 3): koddan okunan bir olgunun yöntem kökeni: `{code_version, source, sha256, fact, verified}`;
     `sha256` olguyu veren kaynak dosyanın (ya da dosyaların, her biri için) içerik özetidir ve **modül yüklenirken**
     sabitlenir, yani çalışan kodun kaynağıdır (Sol dördüncü tur bulgu 2); döküm anında diskteki dosya yeniden özetlenir,
     farklıysa (kod çalışırken dosya değişti) kod kökeni doğrulanmış gösterilmez (`verified: false`) ve madde metni bunu
     söyler; özet, çünkü
     `code_version` (paket sürümü ve sorgu derleyici sürümü) aynı ad altında değişen bir bağlayıcı tablosunu ayırmaz ve
     çalışma anında git commit kimliği yok; ör. `{"code_version": "deixis/0.1.0 …", "source":
     "backend/deixis/providers/registry.py", "sha256": "…", "verified": true, "fact": "no_registry_connector", "connectors": [...]}`. Yokluğa karşılık gelen bir satır olmadığı için bu olgu `trace`'e girmez; `trace` yalnız satır
     kimliği kalır.
   - **Cümle.** Markdown'ın başında "The search is reported against the PRISMA-S checklist items. This is not a
     PRISMA-compliant review: screening was done by code and model runs, and a person looked only at queued and audited
     records." "PRISMA uyumlu" hiçbir yerde yazmaz.

   | # | Madde | Kaynak | Durum kuralı |
   |---|---|---|---|
   | 1 | Database name | revizyonun `search_runs.provider`'ları, bağlayıcı tablosundan erişim ("direct API") | `reported` |
   | 2 | Multi-database searching | bağlayıcı tablosu: her veritabanı kendi API'siyle ayrı sorgulanır; bioRxiv ayrı bir OpenAlex sorgusuyla (bir eşzamanlı çoklu veritabanı araması değildir) | `not_performed` ("each database was queried separately through its own interface"); bioRxiv aranmışsa bu cümle `values`'ta |
   | 3 | Study registries | kayıt defteri bağlayıcısı yok (`code_source`: bağlayıcı tablosu ve listesi) | `not_performed` |
   | 4 | Online resources and browsing | ürün gezinti yapmaz; kişinin kendi gezintisi kaydedilmez | `not_recorded` |
   | 5 | Citation searching | `code:chain_summary` (tohum, yön, istek, başarısız, yeni eser, okunan), protokolün `citation_chaining`'i | zincir koştuysa `reported`; bir zincir grubu hata ile bittiyse `incomplete`; protokolde kapalıysa `not_performed` |
   | 6 | Contacts | yok | `not_recorded` |
   | 7 | Other methods | kişinin getirdiği eserler (`added_by` ≠ `search`, sayıyla) ve kapsamın tohumu. Veri genişlemesi turu bir arama yinelemesidir, burada değil madde 8 ve 13'tedir | getirilen eser varsa `reported`; yoksa `not_recorded` ("no other source was recorded in DEIXIS") |
   | 8 | Full search strategies | `search_table`: sağlayıcı, köken (`model` / `code` / `expansion` turu), tur, `query_text` aynen, `request_description`'dan alan ve parametreler; model terim önerileri ve kişinin düzeltmeleri (onay kaydı) | `reported` |
   | 9 | Limits and restrictions | sorgu başına `read_limit`, sıralama (S2 `citationCount:desc`), istekteki `filter=`, protokolün `budget`'ı, sınır yüzünden okunmadan kalan sayı | `incomplete`: sınırlar yazılır, gerekçeleri araştırma başına saklı değil ("limits listed; their justification is not recorded") |
   | 10 | Search filters | ürünün yayımlanmış süzgeç özelliği yok (`code_source`: sorgu derleyicisinin sürümü ve süzgeç kuralının olmaması) | `not_performed` |
   | 11 | Prior work | yok | `not_recorded` |
   | 12 | Updates | revizyonun keşif koşuları ve tarihleri; önceki revizyonların sayısı | revizyonda birden çok keşif koşusu varsa `reported` (tarihleriyle); tek koşuda `not_recorded` ("no update run was recorded in DEIXIS"), "not updated" yazılmaz; önceki revizyon varsa ayrıca "N earlier question revisions; their searches are not in this export" ve durum en az `incomplete` |
   | 13 | Dates of searches | sorgu grubu başına ilk / son `retrieved_at`, tur, protokolün donma tarihi | `reported` |
   | 14 | Peer review | protokol onayı (`approval.approved_by`, tarih) bir akran incelemesi değildir | `not_recorded`; onay `values`'ta olgu olarak |
   | 15 | Total records | sorgu grubu başına dönen kayıt, sağlayıcı toplamı, okuma sınırı yüzünden okunmayan, bitiş durumu; zincir grupları ayrı | tamam bitmeyen (son sayfası `completed` / `zero_results` olmayan) bir anahtar sözcük ya da zincir grubu varsa `incomplete`: neden başına grup sayısı, hiç okumayanlar ile okuyup duranlar ve okudukları kayıt ayrı; sınır yüzünden okunmayan eksik sayılmaz, madde 9'da |
   | 16 | Deduplication | metin tekilleştirme kurallarını anlatır: aynı normalleştirilmiş DOI birleştirir (D46), sürüm başı kuralı (D48), DOI yoksa başlık, yazar ve özet birlikte, yalnız ön baskı ile yayımlanmış birleşir, her bağ kuralı ve kaynağıyla saklanır ve geri alınabilir (D72), yazılım DEIXIS'in kendisi (`code_version`). Sayılar ayrı: bütün dönen satırlar (`result_count` toplamı, sayfalar ve sorgular arası tekrarla); **izlenen aday sürümleri / isabetleri** (`candidate_hits`; bir sorgunun aynı sürüme eşlenen birden çok sağlayıcı kaydı tek isabettir ve aday yapılmadan eklenen sürümler burada yoktur, bu yüzden "ayrı dönen kayıt" değildir; D93 öncesinde "sayılmadı"); **ayrı dönen sağlayıcı kaydı: `null`, kayıt yok** (ham yanıtlar dosyada, sayılmış bir tabloda değil; bu dilim dosyaları okumaz); araştırmanın etkin üyeleri; eser; etkin üyeler üzerindeki `record_links` tür / kural / birleşti mi sayıları (`aggregates`) | `reported` (süreç ve var olan sayılar); ayrı dönen kayıt sayısı `values`'ta `null` ve metinde "not recorded" |

   **Neden:** ana planın 20. maddesi; dökümün her satırı bir saklı kayda izlenebilir olmalı; Sol bulgu 6. Saklı veride
   madde 15, 40 araştırmanın 40'ında `incomplete` çıkar (sayı 7: tamam bitmeyen anahtar sözcük grubu hepsinde var); madde
   9 her `sw` araştırmasında `incomplete`; bunlar gerçek durumdur ve gizlenmez.
9. **Ana ekranın derinlik metni.** Yeni salt okunur uç nokta `GET /api/effort-limits` →
   `{"search_workflow": "sw" | "legacy", "efforts": {quick: {...}, standard: {...}, detailed: {...}}}`; `sw` değerleri
   `rules.py`'nin sabitlerinden (`SW_READ_LIMIT`, `ABSTRACT_READ_LIMIT`, `FULLTEXT_WORK_LIMIT`, `FULLTEXT_READ_LIMIT`,
   `FULLTEXT_RUNS`, `CHAIN_SEEDS`, `CHAIN_ABSTRACT_READ`, `max_answer_passages`). `Home.tsx` `sw`'de efor açıklamasını
   bu sayılarla ve i18n şablonuyla yazar: "Each search reads up to {read} records; the model screens {abstracts}
   abstracts, fetches up to {fetch} full texts and reads {reads} of them twice; the answer uses up to {passages}
   passages." `legacy` metinleri değişmez. Uç nokta cevap vermeden ya da hata verirse açıklama sayısız kalır; `legacy`
   sayıları `sw` için gösterilmez. **Neden:** satır 20'nin notu; sayılar tek kaynaktan gelsin ki bir sonraki sınır
   değişikliğinde metin yine eskimesin. En geç dilim 24'ten önce kapanmalı.
10. **Veri akışı ve maliyet.** `research_view` dilim 19'un tek anlık görüntüsünde ve tek kuyruk bağlamıyla: `counts.flow`
    (karar 1), `counts.flow_boxes` (karar 2), `counts.overrides` (karar 4), her yanıtta `start_snapshot` (karar 3).
    Denetim ayrı uç noktalarda (karar 6); kuyruk sekmesi onları okur, `GET …/queue` değişmez. **Bütçe, kabulde ürünün
    kendi koduyla ölçülür** (planın süreleri yalnız plan yardımcısı ölçümüdür, sayı 8): en büyük dört ayrı kütüphanenin
    göç ettirilmiş kopyalarında, bir ısınma çağrısı ve 5 tekrarın ortancasıyla, bağlam verilmişken akış + kutular + ezme
    türetmesi en çok 0,05 sn; `GET …/audit` en çok 0,5 sn; PRISMA-S dökümünün iki biçimi, uç noktadan, en çok 1 sn;
    denetim cevabının ve geri almasının **yazma işlemi** (işlem içindeki tam bağlam ve örnek denetimi dahil, planda
    ölçülmedi, bağlam tek başına 0,13–0,16 sn) en çok 0,5 sn. `research_view` süresi önceki commit'te ve sonra aynı
    yöntemle yazılır. Yazma bütçesi aşılırsa üyelik denetimi yalnız o katmanın işleriyle sınırlanır (katmanı kuran
    sorgu işin sonucunu yalnız o katmanın neden kodlarıyla okur) ve bu satır 20'ye yazılır. **Yazılan yeni şeyler:**
    yanıt koşusunun kod adımı ve denetim cevaplarının D96 tablolarına yazdıkları. Migration yok (en yüksek `0052`), yeni neden kodu yok, protokol gövdesi ve `skill_package_hash` aynı.
11. **Arayüz yerleşimi.** `.impeccable.md` önce. Kaynaklar sekmesinin başında, dışa aktarma bağlantılarının yanında
    katlanabilir "Akış" bloğu: SW11.12 beşlisi tek satırda, açılınca bütün kovalar ve kutular; aynı yerde "Arama raporu
    (PRISMA-S)" `.md` / `.json` bağlantıları. Her yanıtın altında karar 3'ün iki (gerekirse üç) satırı (ya da
    "kaydedilmedi"). Kuyruk sekmesinde, satırlardan sonra "Denetim örneği" bölümü: F1 / F2'nin güncel örneği ve karar 7'nin
    sayısı, altında "Önceki denetim cevapları", en altta ayrı başlıkla "Özet aşamasında dışlananlardan örnek (gösterim ve
    elle seçim)"; sekmenin başında karar 4'ün satırı. Transcript'in tarama evresindeki seçim sayıları satırı değişmez. Metinler `i18n.ts` /
    `labels.ts`'ten; "iki koşu anlaştı" ile "onayladınız" ayrı; model kararına "doğrulanmış" denmez.

## Sahibin vereceği kararlar (geçici; kabul edilmedi)

Dosya aşağıdaki önerilerle yazıldı. Sahip farklı karar verirse satır 20'ye yazılır ve etkilenen karar ve task değişir.
Uygulama bu iki cevap satır 20'de yazılı olmadan başlamaz.

- **A — Denetim satırlarına nasıl cevap verilir?** Bedel açıkça: denetimin en değerli yeri özet aşamasındaki
  dışlamalardır (bir yanlış dışlama kayıptır, SW11.4), ama bugün kişinin o kararı "tam metne gönder" diye düzeltmesinin
  yolu yok. Öneri **A1**: tam metin katmanları (F1, F2) ayrı denetim uç noktalarından cevaplanır (karar 6); özet
  katmanları (A1, A2) yalnız gösterilir, tek eylem mevcut liste düzenlemesidir ve iş tam metne değil doğrudan yanıt
  girdisine gider; bu katmanlar denetim sonucuna girmez. Yani A1 özet aşamasındaki yanlış dışlamayı **onarmaz**, yalnız
  görünür kılar; "tam metne geri gönder" açık gereksinim kalır. *A2*: bütün katmanlar yalnız gösterilir, cevap yalnız
  kaynak listesinden; daha az kod, ama tam metin denetimi de ölçüte bağlı bir karar olmaz. *A3*: A1 + özet aşamasına iki
  insan kodu (`human_in_scope` → tam metne, `human_out_of_scope`); dört katmanın hepsi cevaplanabilir olur, ama özet
  aşamasının yeniden koşusu, getirme planı ve `HumanDecisionStands` ile etkileşimi yüzünden ayrı ve tam incelenen bir
  dilim ister; bu dilimde önerilmez.
- **B — PRISMA-S dökümünün dili.** Öneri: yalnız İngilizce (maddelerin adları kontrol listesinin kendi adları, dergiler
  İngilizce ister, tek dil test yükünü yarıya indirir). *Seçenek:* yanıt dili gibi `tr` / `en` şablonları (P6
  raporunun `review_methodology.py`'si gibi).

## Global constraints

- **Yalnız `sw`.** `legacy` araştırmada yeni alanlar `null`, eski alanlar ve `legacy` yanıt koşusu aynı.
- **Okuma türetmedir.** `research_view`, kuyruk görünümü, denetim okumaları ve PRISMA-S dökümü hiçbir tabloya yazmaz.
  Yazan yalnız yanıt koşusunun `code:answer_start_snapshot` adımı, D96'nın mevcut cevap / geri alma uç noktaları ve
  denetimin cevap / geri alma uç noktaları (D96'nın tablolarına).
- **Model sözleşmesi değişmez.** `skill_package_hash`
  `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca` kalır; yöntem paketi, şemalar ve model adımları
  dokunulmaz. Migration yok. Neden kodu tablosu aynı. Protokol gövdesi aynı.
- **Birim iştir**, sonuç `work_outcome`'la; D101'in prob seti tek kişi tanımıdır.
- **Belirlenimcilik.** Her liste kalıcı kimlikle sıralanır; denetim örneği özetle çekilir, rastgele sayı üreteci yok.
- **Konuya özgü hiçbir şey yok.** Kova, katman, sağlayıcı ve madde adları koddaki tablolardan.
- **Kanıt sözcükleri.** Akış "dahil" ile "onayladınız"ı ayırır; ezme sayısı bir doğruluk oranı gibi sunulmaz; döküm
  "PRISMA uyumlu" demez; `abstract_not_read` olumsuz sayılmaz (AGENTS.md).

## Task taslağı

1. **Akış sayıları** (`workflow/flow_counts.py`, karar 1–2). Testler: her kovaya düşen bir iş (sentetik akışta her neden
   kodu için); toplam = eser; D101 / D96 / D99 eşitlikleri aynı bağlamda; `look_again_in_answer` (R1'de kuyruk `include`,
   revizyon R2, seçim hâlâ `included`); `abstract_not_read` olumsuzlarla toplanmaz; `other` boşken yok, bir tam metin
   `unresolved` başka yönle yapay olarak yazılınca `other` 1 ve neden koduyla; kutular: D93 öncesi koşuda
   `found_by_search: null`; `flow_status` her zaman `incomplete_no_human_screening`; `legacy` `None`.
2. **Yanıt başındaki görüntü** (karar 3). Testler: kuyruk doluyken yanıt koşusu başlar, `code:answer_start_snapshot` o anın
   sayılarını, koşunun `scope_revision`'ını ve okunan `selection_revision`'ı yazar; koşu `_inspect` sırasında duraklatılır,
   bir iş `included` yapılır, sürdürülür → adım aynı kalır, yanıtın `selection_revision`'ı yenisi, "dahil kaynakların
   durumu değişti" satırı çıkar; `excluded → pending` değişiminde satır çıkmaz; dahil bir kaynağın PDF'i kaldırılınca
   eser kümesi aynı kalır ama satır çıkar; kişinin okunmamış dosyası olan dahil iş `included_without_answer_text`'te ve `inputs_given.sources`'ta
   değil; sonra verilen kuyruk cevabı eski yanıtın görüntüsünü değiştirmez; adımı olmayan yanıt `start_snapshot: null`;
   `legacy` yanıt koşusunda adım yok; yanıt girdisi yalnız seçimi `included` işler (sonucu `include` olmayan, seçimi
   kişinin olmayan baş yanıt girdisine girmez).
3. **Ezme sayısı** (`workflow/overrides.py`, karar 4). Testler: kuyrukta `include`, makine `fulltext_runs_disagree` →
   `settled_open`; denetimde F1 işine `criterion_not_met` → `overruled` (model, tam metin, `included → excluded`); listede
   özet `out_of_scope` (kod) işi `included` → `overruled` (kod, özet, `excluded → included`); listede anlaşarak dahil işi
   `included` → `agreed`; kişi cevabı değiştirdi (insan → insan) → makine görüşü ilk insan kararından kesin önceki;
   **aynı milisaniye:** insan satırıyla aynı `created_at`'i taşıyan ama `rowid`'i sonra olan makine satırı görüşe girmez;
   **liste anı:** kişi listede `included` yaptıktan sonra başka bir sürüme `criterion_absent` gelir → sınıf düzenleme
   anındaki görüşle (`settled_open` ya da `agreed`), sonradan gelen kararla değil; düzenlemeyle aynı milisaniyede bir karar
   → `time_unknown`; **eski ölçüt:** R1'de yazılmış makine kararı, R2'de ölçüt değişti, kişi R2'de listede karar verdi →
   o anın anahtarıyla eskimiş sayılır, görüş özet sonucuna düşer; **çok sürüm:** iki sürümün karşıt taze kararı →
   görüş `versions_disagree` (açık) → `settled_open`; `not_sure`, `pdf_wrong`, `look_again` sınıflara girmez, ayrı sayılır;
   sıfır kararla metin durumu.
4. **Denetim örneği ve cevabı** (`workflow/audit.py`, `queue.py`'nin denetim dalı, dört uç nokta; karar 5–7). Testler:
   katmanlar; aynı durum iki okumada aynı örnek, başlar karıştırılıp sözlük sırası değişince de; ölçüt değişince yeni
   örnek; cevaplanan F1 işi güncel örnekte kalır; daha küçük özetli yeni iş katmana girince yer değişimi, cevaplanmış işin
   "önceki denetim cevapları"nda "örnekten çıktı" işaretiyle kalması ve ezme sayısında kalması; ayrıntı uç noktası iki
   koşunun alıntılarını ve sayfalarını verir, hiçbir şey yazmaz; F1 satırına dört cevap; işlem içi denetimlerin üçü ayrı
   ayrı 409 verir (iş örnekten çıktı; sürümün kararı değişti, ör. yeni okuma; jeton eski) ve hiçbir şey yazmaz; geri alma
   makine kararını ve seçimi geri getirir, öncesi F1 / F2 kodu değilse 409; D96'nın `decide` / `undo` / ayrıntı testleri
   değişmeden geçer ve açık kuyruk satırı denetim uç noktasından cevaplanamaz (ya da tersi); **iki yönlü köken testi:**
   denetimden cevaplanan F1 işi `GET …/queue`'nun `decided` listesinde yok, D96'nın `POST …/queue/{svid}/undo`'su onu
   409 `audit_decision` ile reddeder ve hiçbir şey yazmaz; kuyruktan cevaplanmış bir işi denetimin geri alması reddeder;
   köken karar kimliğine bağlı olaydan pozitif okunur: `via`'sız eski bir D96 olayının kararı D96 geri almasıyla önceki
   gibi geri alınır ve `decided` listesinde durur; olayı olmayan bir insan kararında ve biri `audit` biri `via`'sız iki
   çelişen olaylı kararda ve `via`'sı `audit` dışında bir değer taşıyan olaylı kararda **iki geri alma yolu da** 409
   `origin_unknown` verir ve hiçbir şey yazmaz; `counts.queue` denetim
   satırlarını saymaz; A katmanı işi denetim cevap uç noktasında 422; kişinin karar verdiği iş kuyruğa ve modele yeniden
   gitmez (D96 kuralı bozulmaz).
5. **PRISMA-S** (`workflow/prisma_s.py`, uç nokta, karar 8). Testler: sentetik akışta 16 maddenin hepsi dolu ve durumlu;
   her `trace` girdisi tek bir saklı satıra çözülür, her `aggregates` girdisi yeniden koşulunca aynı sayıyı verir;
   `search_table` revizyonun her sorgu grubunu bir kez, bütün sayfa kimlikleriyle taşır; zincir grupları ayrı; hız
   sınırıyla hiçbir şey okumayan grup ve okuyup duran grup madde 15'i `incomplete` yapar, ikisi ve okudukları kayıt ayrı
   sayılır; yalnız okuma sınırıyla okunmadan kalan kayıt madde 15'i `incomplete` yapmaz; zincir kapalı akışta madde 5
   `not_performed`; bioRxiv aranmış akışta madde 2 yine `not_performed` ve ayrı sorgu cümlesi `values`'ta; kişinin
   getirdiği eser varsa madde 7 `reported` ve sayıyla, yoksa `not_recorded`; veri genişlemesi madde 7'de değil, 8 ve
   13'te; madde 9 `incomplete` ve "justification not recorded"; tek keşif koşusunda madde 12 `not_recorded` ve metinde
   "not updated" yok, önceki revizyonlu akışta en az `incomplete`; madde 16: bir sorgunun iki sağlayıcı kaydı aynı sürüme
   eşlenince "izlenen aday isabeti" 1, dönen satır 2, ayrı dönen kayıt `null` ve metinde "not recorded", metin D46 / D48 /
   D72 kurallarını anlatır; **`code_source`:** madde 3 ve 10'un `not_performed` olgusu `code_source`'tan okunur
   (`fact`, `source`, `code_version`, `sha256`, `verified`; özet yükleme anındaki içeriğin özeti; dosya yüklemeden sonra
   değiştirilince döküm `verified: false` verir ve madde metni kod kökeninin doğrulanmadığını söyler), `trace`'lerinde satır kimliği dışında bir şey yok; **"kayıt yok" ≠
   "yapılmadı":** `not_performed` olan her maddenin izi bir kod ya da protokol olgusunu gösterir, 4 / 6 / 11 / 14
   `not_recorded`'dır ve Markdown iki durumu farklı sözcükle yazar; Markdown'da "PRISMA-compliant" yok, başlık cümlesi var; istekte anahtar yok (bir
   sahte anahtar yazılıp dökümde aranır); `legacy` 422; aynı durumla iki döküm (`generated_at` dışında) bayt bayt aynı.
6. **Derinlik metni** (karar 9). Testler: uç nokta `rules.py` sabitlerini döndürür (bir sabit değişince cevap değişir);
   ortam `legacy` iken `search_workflow: "legacy"`.
7. **Görünüm ve maliyet** (karar 10). Tek bağlam; `research_view` öncesi / sonrası bütün tabloların satır sayıları aynı;
   bütçe ölçümü.
8. **Arayüz** (karar 11). Playwright: J'ye denetim bölümü (F1 satırına cevap, geri alma, sayının değişmesi) ve ezme satırı;
   yeni **M** (`flow-prisma.spec.ts`): Kaynaklar'daki akış satırı, PRISMA-S `.md` ve `.json` indirmesi (içerikte madde
   sayısı 16, başlık cümlesi), yanıtın altında akış satırı; fikstür bir `sw` yanıtına varamıyorsa yanıt satırı pytest'te
   ve bir `research_view` anlık görüntüsüyle sınanır ve bu yazılır. Ana ekran: `sw` sunucusunda derinlik açıklaması yeni
   sayılarla (M ya da H'ye tek iddia). Ekran görüntüsüyle masaüstü ve telefon genişliğinde kendim doğrularım.
9. **Kabul** (model ve ağ yok; `.local/sw-slice20-acceptance-<tarih>/`). (a) Planın 46 kütüphanesinin oturum dizinindeki
   göç ettirilmiş kopyalarında ürünün kovaları `measure.json`'un `flow`'uyla eşit (ad eşlemesi: `included_by_agreement` →
   `included`, `not_met_by_agreement` → `not_met`, `person_confirmed` → `confirmed`, `candidate_no_fulltext` →
   `candidate_not_fetched`, `abstract_unresolved_other` → `abstract_open`, `survey_seed_pool` → `survey`,
   `out_of_scope_by_agreement` / `_by_code` → `out_of_scope_model` / `_code`); fark beklenmez, olursa neden koduyla yazılır.
   (b) Denetim örneği `measure.json`'un `audit_sample`'ıyla aynı işler (katman adları eşlenir). (c) Ezme sınıfları iki
   dilim 16 kütüphanesinde `settled_open:queue` 2, öbürlerinde boş. (d) 40 eserli araştırmanın PRISMA-S JSON'unda her
   `trace` çözülür, anahtar sözcük sorgu grubu toplamı 390 ve zincir grubu 294 (`item15.json`), tamam bitmeyen anahtar
   sözcük grubu 129 (88 hız sınırı / hiç okumadı, 22 okuyup durdu, 11 başarısız, 6 yetki, 2 zaman aşımı), madde 15
   `incomplete` 40 / 40, hız sınırıyla hiç okumayan grubu olan araştırma 33, herhangi bir nedenle hiç okumayan grubu olan
   37; madde 9 40 / 40 `incomplete`. (e) Karar 10'un bütçeleri, ürünün koduyla (görünüm türetmesi, `GET …/audit`, iki
   biçim döküm, denetim cevabı ve geri almasının yazma işlemi). (f) `research_view` ve döküm hiçbir tablonun satır sayısını değiştirmez.
10. **Kapanış.** Yeni D numarası (A ve B'nin sahip cevabıyla; açık gereksinimler: özet aşamasına insan kodu ve "tam
    metne geri gönder", dondurulmuş denetim kohortu ve katman başına oran). `search-workflow-review-2026-09-18.md`'de SW11'in durum satırı (8, 12, 13 kuruldu, sınırlarıyla; 11 D96'da
    kurulmuştu). `sw-status.md` satır 20.

## Kabul koşulları

- Pytest tam koşu: bilinen tek hata (`test_extraction_is_stopped_when_it_exceeds_the_memory_limit`) ayrı, kalan tam koşu
  geçti; mevcut testler değişmeden geçer; build temiz; lint uyarı sayısı 17'yi aşmaz; Playwright A–M geçer.
- Task 9'un (a)–(f)'si yazılı; (a), (b) ve (d)'nin sorgu toplamı eşit.
- `skill_package_hash` aynı; migration yok; neden kodu tablosu aynı; protokol gövdesinin özeti sentetik bir akışta
  dilimden öncekiyle aynı.

## Bu dilimde yok

- Özet aşamasına insan kodu ve "tam metne geri gönder" (soru A3; açık gereksinim).
- Denetimden oran, aralık ya da hata tahmini; dondurulmuş denetim kohortu (çekilen kimlikleri ve anı saklayan tablo);
  katman başına örnek boyunu duruma göre büyütmek.
- Kod kapısı katmanı ve SW16.4'ün "tek yanlış kapatma kapıyı kapatır" kuralı (dilim 23).
- PRISMA 2020 akış diyagramı çizimi; kontrol listesinin tam metnini üründe yeniden üretmek.
- Önceki revizyonların aramalarını aynı dökümde raporlamak (madde 12 yalnız sayısını söyler).
- P6 raporunun yöntem paragrafını bu döküme bağlamak.
- `legacy`'de hiçbir şey; `legacy` derinlik metni.

## Ölçülmedi

Kişinin akış satırını, ezme sayısını ya da denetim bölümünü okuyup bir şeye karar verip vermediği. Denetim örneğinin
yanlış bir kararı bulup bulmadığı: saklı veride hiçbir denetim satırı cevaplanmadı, kişinin açık kararı 43 araştırmanın
2'sinde 2'şer. `AUDIT_PER_STRATUM = 3`'ün yeterliliği (elle seçildi). Dökümün bir dergi ya da kütüphaneci gözüyle yeterli
olup olmadığı; dışarıdan doğrulanmadı. Üçüncü bir alan (sepsis araştırmalarında eser yok). Eskime ve liste düzenlemesi
durumları saklı veride yok; yalnız testlerle. Ürünün görünüm, döküm ve denetim yazma süreleri (planın süreleri yardımcı
işlevlerindir; gerçekleri kabulde). Canlı hiçbir şey.
