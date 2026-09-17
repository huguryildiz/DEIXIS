# P6 dilim 4 — rapor düzenleme, bayatlama işareti ve P6 kapanış ölçümü: tasarım notu

**Tarih:** 17 Eylül 2026. **Durum:** Taslak; sahibin yanıtı bekleniyor. Bu notta henüz kabul edilmiş bir tasarım yok; §11'deki sorular kapanmadan uygulamaya başlanmaz. Kod değişmedi.

**Kısaca:** Bugün rapor (P6 dilim 1) yalnız bir tasarım planıdır; `backend/deixis/workflow/report/` dizini ve migration `0034` henüz kodda yok (17 Eylül 2026'da doğrulandı, bkz. §1). Bu dilim üç şeyi tek notta toplar, çünkü üçü de aynı soruya dayanıyor: "rapor donduktan sonra ne olur". Birincisi, **düzenleme**: sahip bir bölümün tek bir iddiasını elle düzeltebilir ya da modele bölümü yeniden yazdırabilir; insanın yazdığı hiçbir zaman modelle ezilmez (T09), model sonucu insan düzenlemesi varken her zaman bekleyen bir öneri olarak gelir — P5'teki hücre kuralının (D37) aynısı, kanıt tablosundan rapor iddiasına taşınmış hâli. İkincisi, **bayatlama**: kanıt (hücre, PDF, kaynak, sütun, çizgi bağı, aday durumu, rapor planı) değiştiğinde hangi bölümün buna dayandığını kod bilir ve bölümü "bu kanıt değişti" diye işaretler; işaret hiçbir zaman kendiliğinden onarmaz, sahip ya yeniden yazdırır ya "böyle kalsın" der ya elle düzeltir. Üçüncüsü, bunların hepsinin üzerine oturan **kimlik kararlılığı** sorunu: rapor bölümü her yeniden yazıldığında `claim_key` ve `gap_id` yeniden verilir (dilim 1'in kendi kuralı); bu, insan düzenlemesini bir sonraki yazıma taşımayı ve dilim 3'ün aday kartının "aynı gerçek soru"ya sürekli işaret etmesini zorlaştırır. Bu not, per-revizyon kimliklerin üstüne kalıcı bir "kararlı kimlik" katmanı önerir ve nerede kırılabileceğini açıkça yazar. Son olarak, P6'yı kapatacak ölçüm P5 dilim 5'in deseniyle tanımlanır: tutulmuş bir soru, dondurulmuş beklentiler, korpus kapsamı ile rapor kalitesinin ayrı raporlanması, düzenleme/bayatlama davranışının senaryolu bir denetimi.

## 1. Kodda ve önceki dilimlerde bugün olanlar

**Önemli bulgu (17 Eylül 2026, doğrulandı):** `backend/deixis/workflow/report/` dizini yok, migration dosyaları `0033`'te duruyor (`0034_report_run_kind.sql` henüz uygulanmadı). Yani P6 dilim 1 kodda **hiç yok**; yalnız [`p6-slice1-report-run.md`](p6-slice1-report-run.md) adlı, checkbox'ları işaretlenmemiş bir uygulama planı var. Bu not, o planın verdiği tablo/sınıf/alan adlarını (`ReportStore`, `reports`, `report_sections`, `report_claims`, `report_claim_refs`, `report_citation_links`, `report_gaps`, `report_snapshot`, `report_phrase_repairs`, `build_snapshot`, `run_assembly_checks`, `run_report_review`, `/api/researches/{id}/reports`, `apps/web/src/report/ReportView.tsx`) olduğu gibi kullanıyor; dilim 1 yürütülürken bu adlardan biri değişirse bu not da güncellenmeli (bkz. §10). Aynı şekilde dilim 2 ([`p6-slice2-chain-of-ideas.md`](p6-slice2-chain-of-ideas.md)) ve dilim 3 ([`p6-slice3-kill-search.md`](p6-slice3-kill-search.md)) da taslak durumda; bu notun onlara bağımlı kısımları (§4.3, §11) o notlardaki tablo adlarını (`chain_links`, `chain_link_revisions`, `research_candidates`, `candidate_versions`) kullanır ve aynı uyarı geçerlidir.

| Parça | Doğrulanan durum | Bu dilim için anlamı |
|---|---|---|
| P5 dilim 1 kanıt tablosu (`backend/deixis/workflow/tables.py`, D37/D38) | `evidence_cells`/`cell_revisions` append-only revizyon zinciri; `edit_cell` insan yazısını `expected_version` ile korur (409 `RevisionConflict`), `keep_evidence_from` parametresiyle kanıtı isteyerek taşır ya da düşürür; `decide_proposal` bekleyen model önerisini kabul/red eder; model sonucu yalnız boş hücrede geçerli değer olur, aksi hâlde `model_proposal` bekler. | Rapor iddiası düzenlemesinin **tam kopyalanacağı** kalıp budur (§3, §4). `keep_evidence_from` → rapor tarafında `keep_citations_from`; `decide_proposal` → bölüm yeniden yazımı önerisinin kabul/red akışı. |
| `backend/deixis/api/app.py` (`ExpectedVersion`, `RevisionConflict`, `@app.exception_handler`) | Optimistic concurrency her mutasyon ucunda aynı desenle: `expected_version` gövdede/sorguda, uyuşmazlıkta 409 ve "sayfa son durumu gösteriyor" mesajı. | Rapor iddiası ve rapor planı düzenleme uçları aynı deseni birebir kullanır; yeni bir eşzamanlılık mekanizması icat edilmez. |
| P5 dilim 3 çöp ve geri alma (D50) | Çöpe atma/çıkarma görünürlük durumudur, silme değildir; "Geri al" bildirimi mevcut geri getirme ucunu çağırır, ayrı bir "undo günlüğü" yoktur. | Bu dilimde "undo" **trash değil, revizyon geçmişidir** (görev tanımının istediği gibi): eski bir revizyona dönmek, o revizyonun metnini kopyalayan **yeni** bir `human_edit` yazmaktır — D50'nin trash kalıbı burada kullanılmaz, çünkü hiçbir şey silinmiyor. |
| `answers.report_version` (migration `0023`) | Yalnız `structurally_valid` yanıtlar arasında sayılır, atanınca sabittir; D56 "yalnız alıntısız/tekrarlı/başıboş atıfları düşürerek nihai taslak yayımla" kararıyla, yapısal geçerlilik ile "yayımlanmış" olmak arasına bir ayrım koydu. | Dilim 1'in `reports.report_version`'ı da aynı kuralı taşıyor (yalnız `valid` durumdayken atanır). Bu dilim, düzenleme SONRASI bu numaranın ne olacağını sorar (§11 soru 2); D56'nın "yapısal geçerlilik ≠ yayım" ayrımı emsal olarak kullanılır. |
| `scripts/p4_eval/measure.py` (`snapshot`, `score`, `cells`, `cells-score`, `compare`, `review.md`) | P4/P5 ölçümünün tek aracı; alt komutlar bağlantı/kimlik denetimi, bilinen küme kapsamı, hücre inceleme sayfası üretir; çıktılar `.local/`'e gider, depoya girmez. | §9'daki `measure_report.py` (dilim 1'in planladığı) bu aracın alt komut deseninin devamıdır; bu dilim ona `stale`/`edit` senaryoları için yeni alt komutlar ekler, ayrı bir araç açmaz. |
| D55 (P5 kapanışı) | Dahil bilinen eserlerin DEIXIS yollarıyla PDF metni alma oranı 0/7 ve 0/5; tutulmuş soruda bilinen eser geri çağırımı 4/15. | P6 kapanış ölçümünün (§9) M3/M1 karşılığı; rapor kalitesi bu sayılardan **ayrı** raporlanır (AGENTS.md "evidence boundaries", "preserve reading depth"). |
| `docs/product/implementation-plan.md` §6.2, §10 | "İnsan düzeltmesi eski değeri yok etmez; yeniden inceleme bir öneri sürümü üretir... Kanıt veya iddia değişince bağımlı rapor, CoI bağlantısı ve kill-search sonucu `needs_review` olur." T09: "Recheck yeni öneri üretir; eski ekran veya model insan sürümünü ezmez" (P5–P6). P6 çıkış koşulu (§9 tablosu): "Yakın çalışma/karşı kanıt/erişim sınırı doğru iddiaya bağlanır; boş arama özgünlük sayılmaz; düzenlenmiş rapor korunur." | Bu dilimin adı zaten plandaydı (§12 madde 4: "Bölüm düzenleme (T09), bölüm düzeyinde `stale`, düzenleme sonrası kimlik kararlılığı, tutulmuş soruyla kapanış ölçümü"). `needs_review` terimi planda geçiyor; rapor tasarımı notu aynı kavramı `stale` diye adlandırdı (§4.2). Bu not `stale` terimini kullanır (rapor tasarımıyla tutarlı), ama ikisinin aynı şeyi kastettiğini kaydeder. |
| `p6-report-design.md` §4.2, §5, §8, §10 | Üç ayrı durum kümesi (run/bölüm/rapor); kanıt anlık görüntüsü (`report_snapshot`) donduktan sonra hiçbir canlı değişiklik raporun donmuş metnini etkilemez; tek bant "Bu rapordan sonra kanıt değişti" (rapor düzeyi, dilim 1); "plan değişirse sonraki bölümler yeniden yazılır, önceki bölümler `stale` işaretlenir" (§5 son cümle); montaj denetimi `body_refs`/`gap_refs`'in var olduğunu doğrular, ama bunların **rewrite sonrası hâlâ geçerli olduğunu** değil. | Bu dilim, rapor DÜZEYİ bandın (dilim 1, sayaç karşılaştırması) yanına BÖLÜM düzeyi işareti ekliyor; ikisi aynı mekanizma değil (§6). `claim_key`/`gap_id`'nin rewrite'ta yeniden verilmesi, montaj denetiminin `body_refs`/`gap_refs` doğrulamasını bir sonraki rewrite'ta kırabilir; bu notun kimlik katmanı (§5) tam olarak bunu önlemek için var. |
| `p6-slice2-chain-of-ideas.md` §4.2, §5 | Çizgi bağı düzenlemesi (insan siler/yeniden etiketler/alıntısız ekler) `cell_revisions`in aynısı olan `chain_link_revisions`'a append-only yazılır; "sonraki `chain_links` çalışması onu ezmez, yalnız yeni öneri üretir" (S6). III'ün "alanın gelişimi" alt bölümü ve VI'nın dördüncü aday türü (`chain_end_uncertainty`) bu bağlara dayanır. | Bir çizgi bağı düzenlendiğinde/silindiğinde III'ün ilgili cümlesi ve o çizgi ucundan doğan VI/VII adayı **stale** olmalı (§3, §4.3); dilim 2'nin notu bunu açıkça dilim 4'e bırakıyor. |
| `p6-slice3-kill-search.md` §5, §6 | "İki tablo, tek doğruluk kaynağı": `report_gaps.kill_search_status` kod tarafından `research_candidates.status` her değiştiğinde **aynı işlemde** kopyalanan bir görünüm sütunu; "rozet canlı, metin donuk" — rozet güncellenir ama VI/VII'nin **metni** (ör. "kill-search yapılmadı" cümlesi) değişmez. `research_candidates.source_gap_id TEXT UNIQUE REFERENCES report_gaps.id`. | Rozetin canlı olması metnin doğru kalmasını GARANTİ ETMEZ: durum `not_run`dan `narrowed`/`closed`/`open`a geçtiğinde, bölümün "kill-search yapılmadı" diyen cümlesi artık **yanlış bir iddia** olur (AGENTS.md "Never overstate what was established" — burada tersi: understatement da bir doğruluk hatasıdır). Bu, VI/VII metninin stale olması gerektiğinin somut nedenidir (§3 S-gap). Ayrıca `source_gap_id`'nin per-report-version `report_gaps.id`'ye değil, bu notun önerdiği kararlı kimliğe bağlanması gerekir (§5, "ne kırılıyor"). |
| `contracts/research/step-input.schema.json`, `domain/contracts.py::locate_anchor` | Kimlik desenleri (`col_`, `cel_`, `psg_`), zarf alanları, tek onarım kuralı, alıntı konumlandırma. | Yeni tablo/uç adları bu kalıpları izler; yeni bir doğrulama mimarisi kurulmaz. |

## 2. Senaryolar

### S1. Sahip bir iddiayı elle düzeltir

Rapor `valid`. Sahip IV bölümünde bir cümlenin yazımını ya da vurgusunu düzeltir (ör. "birçok çalışma" yerine "üç çalışma"). Ekran o iddianın geçerli sürümünü (`report_claims.version`) gösteriyordu; düzenleme isteği bunu taşır. Sunucu insanın metnini yeni bir `human_edit` revizyonu olarak yazar, kanıt bağlarını (`citation_anchors`) aynen taşır (sahip silmedikçe), banned-word/`count`/matematik denetimlerini kod tarafından tekrar çalıştırır (uyarı, ret değil) ve **kalıp (phrasebank) denetimini bir daha çalıştırmaz** (§3). Rapor `report_version`'ı değişmez; bölüm zaman çizelgesinde "elle düzenlendi" satırı görünür.

### S2. Aynı iddiaya iki sekme yarışır

A ve B aynı raporu, aynı iddia sürümünü görüyor. A düzenlemeyi kaydeder, sürüm artar. B'nin (arada yenilemediği) düzenlemesi 409 alır, mevcut ileti gösterilir ("Uygulanmadı… sayfa son durumu gösteriyor" — tables.py'nin bugünkü mesajı), B'nin taslağı formda kalır (D37/T09 desenlerinin birebir aynısı, rapor iddiasına taşınmış).

### S3. Sahip bir bölümü modele yeniden yazdırır, bölümde insan düzenlemesi var

IV'te iki iddia elle düzenlenmiş. Sahip "Bu bölümü yeniden yaz" der. `report_section` adımı yeniden çalışır (yeni `claim_key`'lerle, §5); sonuç doğrudan geçerli hâle **gelmez**, bir **bekleyen bölüm önerisi** olarak saklanır (`report_section_revisions`, kind=`model_rewrite`, durum `pending`). Ekran eski (insan düzenlemeli) bölümü göstermeye devam eder, üstte "Model bu bölüm için yeni bir taslak yazdı" bandı ve "Bu taslağı kullan" / "Mevcut kalsın" seçenekleri durur. Kabul edilirse eski iddialar (ve onların insan düzenlemeleri) geçmişte kalır, kimlik eşleştirmesi (§5) hangi eski düzenlemenin hangi yeni iddiaya karşılık geldiğini işaretlemeye çalışır; eşleşmeyen düzenlemeler "yeni bölümde karşılığı bulunamadı" diye ayrıca listelenir.

### S4. Sahip bölümde hiç insan düzenlemesi yokken yeniden yazdırır

Aynı istek, ama bölümde hiç `human_edit` yok. Yeni sonuç P5'in "boş hücreyi model doldurur" kuralının aynısıyla **doğrudan geçerli** olur, bekleyen öneri oluşmaz — çünkü ezilecek bir insan kararı yok.

### S5. Bir hücre düzeltilir, rapor bunu miras alır

Rapor donduktan sonra sahip kanıt tablosunda bir hücreyi `cell_recheck` ile düzeltir ya da elle `human_edit` yazar. Yazma işlemi aynı transaction içinde `report_citation_links`'ten o hücreye bağlı bütün `report_claims`'i bulur, her birinin `report_id`/`section_id` çiftine bir `report_stale_flags` satırı ekler. Rapor görünümü açıldığında IV (ve IV'e `body_refs` ile bağlı Abstract/IX gibi türetilmiş iddialar varsa onlar da) "bu bölüm bu rapordan sonra değişen bir kanıta dayanıyor" satırını gösterir; rapor donmuş metni, `report_version`'ı ve dışa aktarımı **aynen okunabilir kalır** (AGENTS.md: "preserve revisions... mark stale... instead of silently rewriting history").

### S6. PDF eklenir, okuma derinliği değişir

Sahip önceden yalnız özeti olan bir kaynağın PDF'ini yükler, `reextract_asset` tam metin pasajları üretir. O satırın okunma derinliği `abstract`'tan `full_text`'e çıkar. Bu, o satırın hücrelerine dayanan IV/V iddialarını stale yapar; ayrıca VI'nın `corpus_absence` adaylarının "üç tam-metinli satır" eşiğini de etkileyebilir — kod bu durumda yeni bir aday üretmeye **çalışmaz** (adaylar yalnız bölüm yazımında üretilir, dilim 1 kuralı), yalnız VI'yı stale işaretler ki sahip "yeniden yaz" derse yeni bir `corpus_absence` adayı doğabilir.

### S7. Kaynak araştırmadan çıkarılır ya da geri gelir

D50'nin "araştırmadan çıkarma" işlemi (P5 dilim 3) bir satırı `corpus_memberships.removed_at` ile işaretler. Bu satırın kanıt tablosundaki hücreleri kalır ama satır gizlenir (D50 kuralı); rapor tarafında bu satıra dayanan her iddia stale olur, çünkü II/VIII'in `corpus`/`included` sayıları artık donmuş anlık görüntüyle uyuşmuyordur (rapor düzeyi bant zaten bunu yakalar, §1); bölüm düzeyinde ek olarak, o satırın hücrelerine dayanan IV/V/VI iddiaları da ayrıca işaretlenir.

### S8. Bir çizgi bağı düzenlenir (dilim 2 varsa)

Sahip dilim 2'nin çizgi görünümünde yanlış bir bağı siler ya da yeniden etiketler (`chain_link_revisions`, kind=`human_edit`/`human_remove`). III'ün "alanın gelişimi" alt bölümündeki, o bağa dayanan cümle ve (bağ bir çizgi ucuna değiyorsa) VI'daki `chain_end_uncertainty` adayı stale olur. Dilim 2 henüz kodda yoksa bu senaryo inert kalır (§4.3).

### S9. Bir adayın kill-search durumu değişir (dilim 3 varsa)

Sahip dilim 3'te bir kill-search'ü bitirir, aday `not_run`dan `narrowed`a geçer. `report_gaps.kill_search_status` aynı işlemde (slice3'ün kendi tasarımı) güncellenir — bu **rozet**tir, ekranda anında görünür, stale değildir. Ama VI/VII'nin o adayı anlatan cümlesi hâlâ "kill-search yapılmadı" diyorsa, bu artık yanlış bir iddiadır; aynı işlem bölüme bir `report_stale_flags` satırı da yazar (rozet ile metin ayrı yollardan güncellenir, §3). Sahip "yeniden yaz" derse VI/VII'nin ilgili cümlesi yeni duruma göre yeniden yazılır; "böyle kalsın" derse bant kalır ama rozet zaten doğru durumu gösteriyordur.

### S10. Sahip bir stale işaretini onaylar ("böyle kalsın")

Sahip S5'teki bandı görür, PDF'i açıp değerin hâlâ makul olduğuna karar verir, "Böyle kalsın" der. Kod, o bölümün o anki bütün canlı (`acknowledged_at IS NULL`) `report_stale_flags` satırlarını "kabul edildi" diye damgalar (silmez, §4); bant kalkar. Bir sonraki bağımsız değişiklik (başka bir hücre düzenlemesi) yeni bir bayrak açar; eski kabul o yeni bayrağı kapatmaz.

### S11. Rapor yayımlanır

Sahip bir dizi düzenlemeden sonra "Yayımla" der (§11 soru 2). Kod montaj denetimini (dilim 1'in 14 kuralı, artık insan metniyle) yeniden çalıştırır; geçerse rapora yeni bir `report_version` atanır (ya da ilk kez atanır); geçmezse hangi bölümün hâlâ sorunlu olduğu listelenir, önceki yayımlı sürüm (varsa) değişmeden kalır.

## 3. Kurallar

- **İnsanın metni modelle asla ezilmez (T09).** Model sonucu yalnız hiç insan yazısı olmayan bir iddia/bölüm için doğrudan geçerli olur; aksi hâlde her zaman bekleyen bir öneridir. Kabul yalnız sahip kararıyla olur.
- **Düzenlenen bir iddia kalıp (phrasebank) denetiminden geçmez.** Kanıta sadakat kalıba sadakatten önce gelir (rapor tasarımı §2 karar 12); insan düzyazısı modelin biçimsel kalıbına uydurulmaz. Buna karşılık banned-word listesi, `count` üye/derinlik/sayı denetimi ve matematik aralığı iyi-biçimliliği **her zaman** tekrar çalışır — bunlar biçim değil, doğruluk denetimidir; ihlal ret değil uyarıdır ve ekranda görünür.
- **Kanıt bağı sahip silmedikçe kalır.** `keep_citations_from` deseni (tables.py'nin `keep_evidence_from`'unun aynısı): sahip yalnız yazımı düzeltiyorsa eski alıntılar taşınır; sahip bilerek bir alıntıyı kaldırırsa iddia `not_verified`e benzer bir "kanıtsız insan metni" durumuna düşer ve ekranda böyle görünür (rapor asla "kanıtlı" görünüp kanıtsız kalmaz).
- **Bayatlama bir bayraktır, bir durum değildir.** `reports.status`/`report_sections.status` (dilim 1) değişmez; stale, bunların üzerine binen ayrı, çoklu ve append-only bir kayıttır. Bir bölüm aynı anda hem `valid` hem stale olabilir.
- **Bayatlama kendiliğinden onarmaz.** Üç yol vardır: yeniden yazdır (modelle, §2 S3/S4 kuralı geçerli), böyle kalsın (kaydedilen bir kabul, hangi değişikliğe karşı verildiği damgalanır), elle düzelt (§ S1). Kod hiçbir zaman sessizce bir bölümü kendiliğinden yeniden yazmaz ya da bayrağı temizlemez.
- **Rozet ile metin ayrı yollardan güncellenir (dilim 3 varsa).** `kill_search_status` gibi kod tarafından türetilen görünüm sütunları canlı kalabilir; ama o sütunun anlattığı **düzyazı** (rapor bölümünün kendi cümlesi) ayrı bir kayıttır ve stale mekanizmasına tabidir (S9). Bir rozetin canlı olması, altındaki cümlenin doğru kaldığı anlamına gelmez.
- **Stale bir rapor okunabilir ve dışa aktarılabilir kalır.** Bant/işaretler ekranda görünür ama rapor gövdesini gizlemez; dışa aktarılan dosya hangi bölümlerin değişen kanıda dayandığını düz bir satırda söyler (§7).
- **Maliyet kontrolü: bayrak yazma-anında hesaplanır, okuma-anında yalnız okunur.** Tek SQLite bağlantısı ve kısa senkron işlem kuralı (CLAUDE.md) gereği, hangi bölümün neye bağlı olduğu zaten kayıtlı (`report_citation_links`, `report_claim_refs`) olduğundan, kanıtı değiştiren işlem (hücre düzenleme, PDF ekleme, kaynak çıkarma, çizgi bağı düzenleme, aday durumu değişimi, plan düzenleme, bölüm yeniden yazımı) **aynı transaction'da** etkilenen `(report_id, section_id)` çiftlerini bulur ve bayrak yazar; rapor görünümü açılışta yalnız "bu bölümde canlı bayrak var mı" diye ucuz bir SELECT yapar, karşılaştırma yapmaz. Dilim 1'in rapor-düzeyi bandı (canlı `evidence_tables.version` ile donmuş `report_snapshot.table_revision` karşılaştırması) ayrıca ve okuma-anında hesaplanmaya devam eder — o tek sayı karşılaştırması ucuzdur ve DEĞİŞTİRİLMEZ; bu dilim ona bölüm düzeyi bayrağı **ekler**, yerine geçmez.
- **Kimlik kararlılığı bir en iyi çabadır, garanti değildir.** Eşleşme bulunamazsa (§5) insan düzenlemesi yeni sürüme taşınmaz; bu durum sessiz kalmaz, ekranda "N düzenlemeniz yeni yazımda eşleşmedi" diye sayılır.

## 4. Veri modeli taslağı

SQL'in geçerli hâli migration dosyası olur; bu bir niyet taslağıdır ve dilim 1'in `0034`'ü uygulandıktan sonraki ilk boş numarayı alır (bu not yazılırken 0034 bile uygulanmamış; yürütme anında `ls backend/deixis/storage/migrations/` ile teyit edilir — muhtemelen `0035` ya da üzeri). Tablo adı önekleri (`rcv_`, `rsv_`, `rsf_`, `rsi_`, `rgs_`) önerilmiş kısaltmalardır; dilim 1'in gerçek `new_id()` kullanımıyla yürütme anında uzlaştırılır.

```sql
-- Human-authored and model-rewrite revisions of one report_claims row. Same append-only pattern as
-- cell_revisions (0020): the current text is a pointer, never an in-place update.
CREATE TABLE report_claim_revisions (
  id TEXT PRIMARY KEY,                 -- rcv_
  claim_id TEXT NOT NULL REFERENCES report_claims(id),
  kind TEXT NOT NULL CHECK (kind IN ('model_write', 'human_edit', 'human_restore')),
  author TEXT NOT NULL CHECK (author IN ('model', 'human')),
  based_on_revision_id TEXT REFERENCES report_claim_revisions(id),  -- human_restore: the earlier revision copied back
  text TEXT NOT NULL,
  keep_citations INTEGER NOT NULL DEFAULT 1,   -- 0 when the human explicitly dropped this claim's citations
  validation_json TEXT,                -- banned-word/count/math warnings recomputed at save time (never blocking)
  note TEXT,                           -- human's reason, optional
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  CHECK ((kind = 'model_write') = (author = 'model')),
  CHECK (kind <> 'human_restore' OR based_on_revision_id IS NOT NULL)
);
CREATE INDEX report_claim_revisions_claim ON report_claim_revisions(claim_id, created_at);
ALTER TABLE report_claims ADD COLUMN current_revision_id TEXT REFERENCES report_claim_revisions(id);
ALTER TABLE report_claims ADD COLUMN version INTEGER NOT NULL DEFAULT 0;
-- + no-update/no-delete trigger on report_claim_revisions (0020 pattern), purge authority excepted.

-- One attempted rewrite of a whole section, kept beside the section's current (possibly human-edited) claims
-- until the owner accepts or dismisses it — the section-level generalization of cell_revisions' model_proposal.
CREATE TABLE report_section_revisions (
  id TEXT PRIMARY KEY,                 -- rsv_
  report_section_id TEXT NOT NULL REFERENCES report_sections(id),
  step_id TEXT REFERENCES run_steps(id),
  status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'dismissed')),
  draft_json TEXT NOT NULL,            -- the new claims/citation_links/gaps, same shape as report_section_draft output
  claim_match_json TEXT,               -- §5: old claim_id -> new claim_key mapping this rewrite proposed, and unmatched old edits
  decided_at TEXT, decided_note TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX report_section_revisions_section ON report_section_revisions(report_section_id, created_at);

-- Section-level "evidence changed since this text was written" flags. Written by the SAME transaction that
-- changes the underlying record (cell edit, asset re-extraction, source removal/restore, column revision,
-- chain link edit, candidate status change, plan edit, or a sibling section's rewrite). Never deleted; an
-- acknowledgement stamps acknowledged_at instead, so a later independent change opens a fresh, live row.
CREATE TABLE report_stale_flags (
  id TEXT PRIMARY KEY,                 -- rsf_
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (reason IN (
    'cell_changed', 'asset_reextracted', 'source_removed', 'source_restored', 'column_revised',
    'chain_link_changed', 'candidate_status_changed', 'plan_edited', 'dependency_section_rewritten'
  )),
  detail_json TEXT NOT NULL,           -- which record (cell_id / source_version_id / column_id / chain_link_id / candidate_id / section_id)
  acknowledged_at TEXT,                -- NULL = live
  created_at TEXT NOT NULL
);
CREATE INDEX report_stale_flags_open ON report_stale_flags(report_id, section_id) WHERE acknowledged_at IS NULL;

-- Dependency edges recorded when a section is written, so a later mutation knows which (report_id, section_id)
-- pairs to flag without re-deriving the graph from citation_links each time (report_citation_links already
-- gives the passage/cell edges; this table adds the two edge kinds report_citation_links cannot express).
CREATE TABLE report_section_dependencies (
  report_section_id TEXT NOT NULL REFERENCES report_sections(id),
  dep_kind TEXT NOT NULL CHECK (dep_kind IN ('chain_link', 'candidate', 'body_ref_section')),
  dep_ref TEXT NOT NULL,               -- chain_link_id, candidate_id, or another report_sections.id (dep_kind='body_ref_section')
  PRIMARY KEY (report_section_id, dep_kind, dep_ref)
);
```

Rapor plan alanları (`scope_statement`) düzenlenebilir bir alan olarak `reports.plan_json` üzerinde doğrudan güncellenmez (append-only ilkesiyle çelişir); onun yerine aynı `report_claim_revisions` deseninin plan-düzeyi bir eşi:

```sql
CREATE TABLE report_plan_revisions (
  id TEXT PRIMARY KEY,                 -- rpv_
  report_id TEXT NOT NULL REFERENCES reports(id),
  kind TEXT NOT NULL CHECK (kind IN ('model_write', 'human_edit')),
  scope_statement TEXT NOT NULL,
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL
);
```

`reports.plan_json`'ın geçerli `scope_statement`'ı bu tablonun en son satırından okunur (görünüm hesaplar); bir `human_edit` yazıldığında rapor tasarımı §5'in kuralı ("plan değişirse sonraki bölümler yeniden yazılır, önceki bölümler stale") tetiklenir: kod, planın bu alanına bağlı bütün bölümler için `report_stale_flags(reason='plan_edited')` yazar. Yalnız `scope_statement` düzenlenebilir kılınıyor; `research_questions`/`glossary`/`axes` model çıktısıdır ve kanıta bağlıdır (bir tanımın hangi pasajdan geldiğini insan icat edemez), bu yüzden bu dilimde düzenlenmez — değişikliği isteyen sahip tüm planı yeniden ürettirir (§11 soru 8'e bağlı bir sınır, açıkça yazılıyor).

## 5. Kimlik kararlılığı: `claim_key` ve `gap_id`

Dilim 1'in kuralı şudur: `claim_key` ve `gap_id` **bir rapor içinde** benzersizdir ve **bölüm yeniden yazılınca yeniden verilir** (p6-report-design.md §4, "Bölüm şeması"). Bu, iki şeyi kırar: (1) bir bölüm yeniden yazıldığında, o bölüme `body_refs`/`gap_refs` ile bağlı başka bölümlerin (Abstract/I/IX, VII) referansları artık var olmayan eski `claim_key`/`gap_id`'lere işaret eder; (2) dilim 3'ün `research_candidates.source_gap_id` alanı doğrudan `report_gaps.id`'ye bağlanıyor (per-rapor-versiyon bir satır), oysa bir aday kartı raporun kendisinden bağımsız yaşıyor ve raporun ikinci, üçüncü versiyonunda da "aynı gerçek soru"yu göstermesi gerekiyor.

**Öneri: iki katmanlı kimlik.** Per-revizyon kimlikler (`claim_key`, `gap_id`) olduğu gibi kalır — model çıktısı bunları üretmeye devam eder, montaj denetimi bunları aynen kullanır. Bunların üstüne, hiçbir zaman değişmeyen bir **kararlı kimlik** eklenir; per-revizyon kimlikler bu kararlı kimliğe bir eşleştirme kaydıyla bağlanır.

```sql
-- Survives a section rewrite (scoped to one report_id): the same real claim keeps this id across rewrites of
-- the section that contains it, so human edits and stale-acknowledgements can be carried forward.
CREATE TABLE report_stable_claims (
  id TEXT PRIMARY KEY,                 -- rsi_
  report_id TEXT NOT NULL REFERENCES reports(id),
  section_id TEXT NOT NULL,
  first_seen_claim_key TEXT NOT NULL,
  created_at TEXT NOT NULL
);
-- Which per-revision report_claims row currently represents which stable claim (1:1 at any moment; the
-- historical mapping lives in report_claim_matches for audit).
ALTER TABLE report_claims ADD COLUMN stable_claim_id TEXT REFERENCES report_stable_claims(id);

CREATE TABLE report_claim_matches (
  id TEXT PRIMARY KEY,                 -- rcm_
  report_section_revision_id TEXT NOT NULL REFERENCES report_section_revisions(id),
  old_claim_id TEXT NOT NULL REFERENCES report_claims(id),
  new_claim_key TEXT,                  -- NULL when no match was found above the similarity floor
  stable_claim_id TEXT REFERENCES report_stable_claims(id),
  citation_overlap REAL NOT NULL,      -- Jaccard over {passage_id, cell_id} sets, 0..1
  paragraph_delta INTEGER,             -- |old.paragraph - new.paragraph|; NULL if unmatched
  text_similarity REAL,                -- normalized token-overlap ratio, tie-break only
  created_at TEXT NOT NULL
);

-- Survives across DIFFERENT reports.id rows of the same research (a research_candidates row outlives any one
-- report run). kind + basis_fingerprint together identify "the same real gap"; the fingerprint's claim
-- references use stable_claim_id, never a literal per-revision claim_key (see "ne kırılıyor" below).
CREATE TABLE report_stable_gaps (
  id TEXT PRIMARY KEY,                 -- rgs_
  research_id TEXT NOT NULL REFERENCES researches(id),
  kind TEXT NOT NULL,                  -- domain.contracts.GAP_KINDS, same open list as report_gaps.kind
  basis_fingerprint TEXT NOT NULL,     -- deterministic hash of the sorted basis set (see below)
  first_seen_report_id TEXT NOT NULL REFERENCES reports(id),
  last_seen_report_id TEXT NOT NULL REFERENCES reports(id),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (research_id, kind, basis_fingerprint)
);
ALTER TABLE report_gaps ADD COLUMN stable_gap_id TEXT REFERENCES report_stable_gaps(id);
```

**Eşleştirme kuralı — iddialar (kararlı, ama bulanık).** Bir bölüm yeniden yazıldığında, kod eski bölümün geçerli iddialarını (varsa insan düzenlemeleriyle) yeni bölümün taslak iddialarıyla eşleştirmeye çalışır:

1. Aday çiftler: `citation_overlap` (eski/yeni iddianın `passage_id ∪ cell_id` kümeleri arasındaki Jaccard benzerliği) ≥ **0.6** olan çiftler.
2. Bu eşiği geçen birden çok aday varsa, `paragraph_delta` en küçük olan (aynı ya da bitişik paragraf) tercih edilir.
3. Hâlâ eşitse `text_similarity` (basit normalize edilmiş token örtüşme oranı) ile tek bir en iyi eşleşme seçilir.
4. Hiçbir aday 0.6 eşiğini geçmezse, o eski iddia **eşleşmemiş** sayılır: `report_claim_matches.new_claim_key = NULL`, insan düzenlemesi yeni sürüme taşınmaz ve ekranda ayrıca listelenir (§3, §2 S3).
5. Bir eşleşme bulunursa, yeni `report_claims` satırı eski iddianın `stable_claim_id`'sini devralır; eski iddia insan tarafından düzenlenmişse (§4), o düzenleme yeni iddiaya **otomatik uygulanmaz** — sahibe "eski düzenlemeniz: '…'; yeni model metni: '…'" karşılaştırması gösterilir ve sahip "eskisini koru" ya da "yenisini kabul et" der (bu, §2 S3'ün "bekleyen bölüm önerisi" akışının bir parçasıdır, ayrı bir onay değildir).

Eşikler (0.6 Jaccard) **ölçülmemiş önerilen varsayılanlardır**; §9'daki kapanış ölçümü bunları gerçek bir rewrite üzerinde sınar.

**Eşleştirme kuralı — gap'ler (deterministik, çünkü temel küme yapılandırılmış veridir).** Aynı `kind` + aynı temel küme ⇒ aynı `stable_gap_id`:

- `corpus_absence`: temel küme = `{column_id}`.
- `stated_limitation`: temel küme = alıntının geldiği `{cell_id}` kümesi (ya da pasaj tabanlıysa `{passage_id}`).
- `conflicting_evidence`: temel küme = dayandığı V iddiasının **kararlı** kimliği (`stable_claim_id`), literal `claim_key` DEĞİL (bkz. "ne kırılıyor").
- `chain_end_uncertainty` (dilim 2): temel küme = `{chain_end_node_id}`.

`basis_fingerprint`, bu kümenin sıralanmış, kanonik bir JSON kodlamasının hash'idir. Bir bölüm yazıldığında (dilim 1'in `gaps.py`'si ya da bu dilimin genişlettiği hâli), her aday gap için önce temel küme kurulur, `report_stable_gaps`'te aynı `(research_id, kind, basis_fingerprint)` aranır; bulunursa `stable_gap_id` o satıra bağlanır ve `last_seen_report_id` güncellenir, bulunmazsa yeni satır açılır. Dilim 3'ün `research_candidates.source_gap_id` alanı bu notun önerisiyle **`report_gaps.id` yerine `report_stable_gaps.id`'ye** bağlanmalıdır; bu, dilim 3'ün notunda düzeltilmesi gereken bir noktadır (§10).

**Ne kırılıyor (dürüstçe).**

1. **Sıra bağımlılığı.** `conflicting_evidence` gap'inin temel kümesi V'nin **kararlı** iddia kimliğine dayanır; bu yüzden V bölümü yeniden yazıldığında önce V'nin iddia eşleştirmesi (yukarıdaki adım) tamamlanmalı, VI'nın gap fingerprint'i ondan SONRA hesaplanmalıdır. Sıra ters çevrilirse iki farklı gerçek çelişki aynı kararlı kimlikte birleşebilir ya da aynı çelişki iki ayrı kimlik alabilir. Bu dilim bu sırayı `sections.py::run_report`'un tur mantığına (VI, V'den sonraki turda zaten çalışıyor, dilim 1 §4) bir ön koşul olarak ekler, ama bunun her durumda doğru sırayı garanti ettiği **ayrıca test edilmeli**.
2. **İnsan alıntı düzenlemesi kendi geleceğini bozabilir.** Sahip bir iddianın alıntı kümesini değiştirirse (`keep_citations_from` ile bir kısmını düşürürse), bir SONRAKİ rewrite'ta o iddianın `citation_overlap` hesaplaması artık farklı bir kümeye dayanır; bu, kendi düzenlemesinin gelecekte kendisiyle eşleşmemesine (dolayısıyla düzenlemesinin kaybolmasına) yol açabilir. Kod bunu önleyemez, yalnız görünür kılabilir (§3 son madde).
3. **Zaten var olan veri yok.** Dilim 3 henüz kodda olmadığı için `source_gap_id`'nin `report_gaps.id`'ye mi `report_stable_gaps.id`'ye mi bağlanacağı konusunda geriye dönük bir geçiş sorunu **şimdilik yok**; ama dilim 3 bu dilimden önce uygulanırsa (bağımlılık sırası tersine dönerse), geriye dönük bir migration (`research_candidates.source_gap_id`'yi var olan `report_gaps.id`'lerden `report_stable_gaps.id`'lere birebir eşleyerek doldurma) gerekir. §11 soru 8, sıralamayı buna göre soruyor.
4. **Kararlılık bir garanti değil, bir en iyi çabadır.** Bu tasarım "aynı gerçek gap her zaman aynı kimliği alır" demez; "temel kümesi değişmeyen bir gap aynı kimliği korur" der. Temel kümenin kendisi değişirse (ör. sütun silinip yeniden eklenirse, farklı bir `column_id` ile), kimlik de değişir — bu bir hata değil, dürüst bir sınırdır.

## 6. Durum makineleri

Dilim 1'in üç durum kümesi (run/bölüm/rapor, p6-report-design.md §4.2) **değişmez**. Bu dilim iki şey ekler; ikisi de yeni bir `status` sütunu değil, ayrı işaretlerdir.

| Katman | Yeni alan | Değerler | Kim yazar | Kim okur |
|---|---|---|---|---|
| İddia (`report_claims`) | `current_revision_id`, `version` | — (append-only işaretçi) | `report_claim_revisions` yazan uç | Rapor görünümü, düzenleme formu |
| Bölüm yeniden yazımı (`report_section_revisions`) | `status` | `pending`, `accepted`, `dismissed` | Yeniden yazma isteği (`pending`), kabul/red ucu | Rapor görünümü (S3 bandı) |
| Bölüm bayatlaması (`report_stale_flags`) | `acknowledged_at` | `NULL` (canlı) / dolu (kabul edilmiş) | Kanıtı değiştiren her mutasyon (yazar), kabul ucu (damgalar) | Rapor görünümü, zaman çizelgesi |

Bölüm yeniden yazımının kabul edilmesi, dilim 1'in mevcut akışını (yeni claim'leri `report_claims`'e yazma, montaj denetimini çalıştırma) **yeniden kullanır**; tek fark, sonucun doğrudan `report_sections.status='valid'`e yazılması yerine önce `report_section_revisions`'ta bekletilmesidir (yalnız o bölümde canlı `human_edit` varsa; §2 S3/S4). Bir `report_section_revisions` kabul edildiğinde, o bölüme bağlı bütün açık `report_stale_flags` satırları da kapatılır (kabul, yeni kanıtla yeniden yazıldığı için o bayrakların nedeni ortadan kalkmıştır) — ama S3'ün "eşleşmeyen düzenlemeler" uyarısı ayrıca gösterilir.

`reports.report_version`'ın düzenleme sonrası davranışı (yeni numara mı, aynı numara mı) §11 soru 2'ye bağlıdır; bu notun veri modeli her iki seçeneği de destekler (`finalize()` dilim 1'de zaten var, bu dilim yalnız onu düzenleme sonrasında tekrar çağırılabilir hâle getirir).

## 7. Arayüz

`.impeccable.md`'ye uyulur: pil yalnız kısa durum için, renk tek başına anlam taşımaz, hiyerarşi düz, hareket yalnız canlı işi gösterir. Aşağıda yalnız metin ve davranış var, görsel maket yok.

1. **İddia düzenleme.** `ReportView.tsx`'te bir iddiaya tıklayınca (kanıt görünümü açıkken ya da ayrı bir "Edit" eylemiyle) düz metin alanı açılır; altında geçerli kanıt listesi (mevcut kanıt sayfasıyla aynı bileşen) ve her birinin yanında "Kaldır" bağlantısı durur (kaldırılan kanıt geri getirilebilir, kaydedilmeden önce). Kaydet düğmesi `expected_version`'ı taşır; 409'da tables.py'nin bugünkü ("Uygulanmadı… sayfa son durumu gösteriyor") mesajı aynen kullanılır ve taslak metin formda kalır. Kaydedilince "Elle düzenlendi" işareti (metinle, ayrı bir renk sözlüğü icat edilmeden) ve varsa uyarılar (banned word/count/math) düz metinle listelenir.
2. **Bölüm yeniden yazma bandı (S3).** Bölümün üstünde: "Model bu bölüm için yeni bir taslak yazdı · {n} iddiadan {k} tanesi elle düzenlenmişti" ve iki eylem: "Bu taslağı kullan" (yeni bölümü açar, eski/yeni karşılaştırmasını gösterir, insan düzenlemesi eşleşmeyen her iddia için ayrı bir satır: "Bu düzenleme yeni yazımda karşılığı bulunamadı: '…'") ve "Mevcut kalsın" (öneriyi `dismissed` yapar, bölüm değişmez).
3. **Stale bandı (bölüm düzeyi).** Rapor tasarımının rapor-düzeyi bandının ("Bu rapordan sonra kanıt değişti") **altında**, ilgili bölümlerin başında ayrı bir satır: "Bu bölüm bu rapordan sonra değişen kanıta dayanıyor" ve nedeni düz metinle ("bir hücre düzenlendi", "bir kaynak araştırmadan çıkarıldı", "bir çizgi bağı değişti", "bir adayın kill-search durumu değişti"). Üç eylem: "Yeniden yaz" (S3/S4 akışını başlatır), "Böyle kalsın" (kabul), "Elle düzelt" (§1'e gider). Kanıt görünümü açıkken hangi kayıtların (hücre/kaynak/çizgi bağı/aday) tetiklediği ayrıca listelenir; kapalıyken yalnız özet cümle görünür.
4. **Kanıt görünümü işaretleri (dilim 3 varsa).** VI/VII'deki bir adayın rozeti (`not_run`/`narrowed`/`closed`/`open`) her zaman canlı gösterilir (kod hesaplar, bekleme gerekmez); rozetin yanındaki cümle stale ise ayrı bir küçük not ("bu cümle güncel durumu yansıtmıyor olabilir") ile işaretlenir, rozetle karıştırılmaz.
5. **Yayımlama.** "Yayımla" eylemi yalnız bekleyen bölüm önerisi ve canlı stale bayrağı olmayan bir raporda tek adımdır; ikisinden biri varsa düğme devre dışıdır ve nedeni yazılır ("2 bölümde yeniden yazma önerisi bekliyor", "3 bölüm bayat işaretli").
6. Masaüstü ve 390 px, açık ve koyu tema; klavyeyle düzenleme formuna erişim ve kaydetme.

## 8. Testler (taslak)

**Depolama ve eşzamanlılık**

- `edit_claim` (adı önerilir, `edit_cell`in birebir eşi): boş revizyon yokken model sonucu geçerli olur; insan yazısı varken model sonucu öneri kalır; `expected_version` uyuşmazlığında 409, form korunur; aynı `Idempotency-Key` ile tekrar aynı revizyonu döner.
- `keep_citations_from` yalnız aynı iddianın bir revizyonundan kanıt taşır; başka iddianın kanıtını taşımaya çalışmak reddedilir.
- Düzenlenmiş iddiada banned-word/count/math denetimi çalışır (uyarı, ret değil); kalıp denetimi hiç çalışmaz (bir kalıba uymayan insan cümlesi hatasız kaydedilir).
- `report_claim_revisions`/`report_section_revisions` üzerinde güncelleme/silme tetikleyicisi reddeder; yalnız purge yetkisiyle silinir.

**Bölüm yeniden yazma**

- İnsan düzenlemesi olmayan bölüm: yeniden yazma doğrudan `valid` olur, `report_section_revisions` açılmaz.
- İnsan düzenlemesi olan bölüm: yeniden yazma `pending` bir `report_section_revisions` açar, eski bölüm değişmeden kalır; kabul eski iddiaları geçmişe taşır ve eşleşmeyenleri listeler; red eski bölümü hiç değiştirmez.
- Kabul, o bölümün açık stale bayraklarını kapatır; red kapatmaz.

**Kimlik eşleştirme (§5)**

- Aynı kanıt kümesiyle yeniden yazılan bir iddia aynı `stable_claim_id`'yi korur (yüksek `citation_overlap`).
- Kanıt kümesi tamamen değişen bir iddia eşleşmez (`new_claim_key = NULL`), insan düzenlemesi taşınmaz ve ayrı listelenir.
- İki eşit derecede iyi aday olduğunda `paragraph_delta` küçük olan seçilir; o da eşitse `text_similarity` karar verir.
- `corpus_absence` gap'i aynı `column_id` ile iki farklı rapor versiyonunda aynı `stable_gap_id`'yi alır; `column_id` değişince yeni kimlik açılır.
- `conflicting_evidence` gap'inin fingerprint'i V'nin kararlı kimliğine dayanır: V yeniden yazılıp aynı çelişki aynı kanıtla yeniden kurulduğunda `stable_gap_id` değişmez.

**Bayatlama**

- Hücre `human_edit`/`cell_recheck` sonrası: o hücreye `report_citation_links` ile bağlı her iddianın bölümüne canlı bir bayrak açılır; bağlı olmayan bölümlere açılmaz.
- Kaynak araştırmadan çıkarılır/geri gelir (D50): o satırın hücrelerine dayanan bölümler bayraklanır.
- Sütun revizyonu değişir: o sütuna dayanan eksen/bölümler bayraklanır.
- Çizgi bağı düzenlenir (dilim 2 varsa): III'ün ilgili cümlesi ve bağlı VI/VII adayı bayraklanır; dilim 2 kodda yokken bu test atlanır/inert kalır (`report_section_dependencies` boş).
- Aday durumu değişir (dilim 3 varsa): `kill_search_status` rozeti güncellenir (bayraksız); VI/VII'nin metni bayraklanır.
- Plan (`scope_statement`) düzenlenir: ona bağlı bütün bölümler bayraklanır (rapor tasarımı §5 son cümlesi).
- "Böyle kalsın": bütün canlı bayraklar `acknowledged_at` alır; bir sonraki bağımsız değişiklik yeni, ayrı bir canlı bayrak açar (eskisini yeniden açmaz).
- Bir bölümün rewrite'ı, ona `body_refs`/`gap_refs` ile bağlı diğer bölümleri (`report_section_dependencies(dep_kind='body_ref_section')`) bayraklar.

**T09 kabul senaryosu (raporlarda)**

- a. İnsan bir iddiayı düzenlerken aynı anda o bölüm için bir `cell_recheck` sonucu gelir: insanın metni değişmez, stale bandı açılır (öneri değil, çünkü bu bir bölüm yeniden yazımı değil bir kanıt değişimidir).
- b. İki sekme aynı iddiayı düzenler: ilk kaydeden kazanır, ikinci 409 alır ve taslağı korur.
- c. İnsan düzenlemesi olan bölüm yeniden yazılır, sahip "mevcut kalsın" der: eski bölüm ve insan düzenlemesi aynen kalır, öneri `dismissed` olarak saklanır (silinmez).
- d. İnsan düzenlemesi olan bölüm yeniden yazılır, sahip "bu taslağı kullan" der: eşleşen iddialar yeni metne geçer, eşleşmeyen insan düzenlemesi kaybolduğu açıkça bildirilir.
- e. Rapor yayımlanır, sonra bir hücre düzenlenir: yayımlı `report_version` değişmez, yalnız stale bandı açılır; dışa aktarılan eski kopya etkilenmez (yeni bir dışa aktarım isteği banda göre uyarı taşır).
- f. Kill-search durumu `not_run`dan `closed`a geçer (dilim 3 varsa): rozet hemen günceli gösterir, VI/VII metni bayraklanır, sahip "yeniden yaz" demeden metin değişmez.

**Web**

- `npm run build`, `npm run lint`.
- Playwright (fixture sunucusu, scriptlenmiş model): bir iddia düzenlenir → kaydedilir → "Elle düzenlendi" görünür → bölüm yeniden yazdırılır → bekleyen taslak bandı → "Bu taslağı kullan" → eski/yeni karşılaştırma → kabul. Ayrı bir senaryo: bir kanıt tablosu hücresi düzenlenir → rapor açılır → stale bandı görünür → "Böyle kalsın" → bant kapanır. Masaüstü ve 390 px, açık ve koyu.

**Bu dilimde geçmeyecekler:** rapor planının `research_questions`/`glossary`/`axes` alanlarının elle düzenlenmesi (§4); dilim 2/3 kodda yoksa onlara bağlı bayatlama yollarının gerçek model ile ölçülmesi (yalnız sentetik/inert testler); iddia metninin cümle-cümle düzenlenmesi (birim: iddia, §11 soru 1); toplu "bütün raporu yeniden yaz" eylemi (yalnız bölüm başına).

## 9. P6 kapanış ölçümü

P5 dilim 5'in kuralı aynen geçerli: beklenti koşudan önce yazılır ve commit'lenir; sonuç sonradan yorumlanıp beklentiye uydurulmaz; korpus kapsamı ile rapor kalitesi ayrı raporlanır ve biri iyileşince diğeri iyileşmiş sayılmaz; bütün değerlendirmeler aksi belirtilmedikçe Claude'undur, "insan denetimi" değildir.

### 9.1 Ne ölçülür

P6 dilim 1'in kendi ölçüm tablosu zaten var (p6-report-design.md §13, R1–R11; dilim 1'in kendi `docs/product/p6-slice1-report-expectations.md`'i ayrı, erken bir koşuda bunları dondurur). Bu dilimin kapanış ölçümü o tabloyu **tekrarlamaz**, üstüne ekler:

| # | Ne | Payda ve tanım | Kaynak |
|---|---|---|---|
| — | Korpus kapsamı (M1/M3, D55'in devamı) | Bilinen eserlerden bulunan/dahil edilen oranı; DEIXIS yollarıyla PDF metni alma oranı | P5 dilim 5 aracının aynısı, yeni koşu |
| — | Rapor kalitesi (R1–R11) | p6-report-design.md §13 | dilim 1'in kendi ölçümü, burada yalnız referans verilir, tekrar koşulmaz |
| — | Chain of Ideas metrikleri (R12–R17) | dilim 2'nin notu, §14 (dilim 2 kabul edilip uygulanmışsa) | dilim 2'nin ölçüm bölümü |
| — | Kill-search metrikleri | dilim 3'ün notu, §13 (dilim 3 kabul edilip uygulanmışsa) | dilim 3'ün ölçüm bölümü |
| R18 | Düzenleme bütünlüğü | T09 senaryolarının (§8) hepsi geçti mi/kaçı geçti; kaç insan düzenlemesi bir rewrite'tan sonra kayboldu (eşleşmedi) / toplam insan düzenlemesi | bu dilim |
| R19 | Bayatlama doğruluğu | senaryolu bir kanıt değişikliği dizisinde (§9.3), beklenen bayrağın kaçı gerçekten açıldı (yanlış negatif) ve beklenmeyen kaçı açıldı (yanlış pozitif) | bu dilim |
| R20 | Kimlik kararlılığı | bir rewrite'ta eşleşmesi beklenen N iddiadan kaçı gerçekten eşleşti (§5 eşiğinin gerçek verideki isabeti); `stable_gap_id`'nin rapor versiyonları arasında korunma oranı | bu dilim |
| R21 | Süre ve maliyet (düzenleme dahil) | bir bölüm rewrite'ının süresi; bayrak yazma işleminin eklediği ek gecikme (varsa) | bu dilim |

Payda sıfırsa metrik "ölçülemedi" yazılır (P5 dilim 5 kuralı), 0 ya da 1 diye değil.

### 9.2 P6 çıkış koşulu ile ölçüm satırlarının eşlemesi

`docs/product/implementation-plan.md` §9 tablosundaki P6 çıkış koşulu üç parçadır; her biri hangi ölçüm satırıyla gösterildiği aşağıda açıkça yazılır — plan yalnız bunu **iddia eder**, ölçüm bunu **gösterip göstermediğini** söyler:

| Çıkış koşulu parçası | Hangi ölçüm satırı | Ne gösterir, ne göstermez |
|---|---|---|
| "Yakın çalışma/karşı kanıt/erişim sınırı doğru iddiaya bağlanır" | dilim 3'ün kill-search metrikleri (S1–S8 senaryoları, "Kim neyi doğrular" tablosu) | Matris hücrelerinin yapısal olarak doğru kaynağa bağlandığını gösterir; ilişkinin (`explicit_support` vb.) **semantik olarak doğru** okunduğunu göstermez — bu Claude'un okumasıdır, bağımsız doğrulama değildir. |
| "Boş arama özgünlük sayılmaz" | dilim 3'ün S2/S3 senaryoları + bu dilimin R19 (VI/VII metninin `open` durumunda "novel"/"gap" sözcüğü taşımadığının montaj denetimi) | Yasak sözcük listesinin kod tarafından arandığını gösterir; adayın **gerçekten** özgün olup olmadığını hiçbir zaman göstermez (kill-search bir yokluk kanıtı değildir, AGENTS.md). |
| "Düzenlenmiş rapor korunur" | R18 (düzenleme bütünlüğü), T09 senaryoları (§8) | İnsan düzenlemesinin model tarafından ezilmediğini, eşleşme bulunamadığında bunun görünür olduğunu gösterir; kimlik eşleştirmesinin **her durumda** doğru eşleştiğini göstermez (R20 bunun isabet oranını ayrıca ölçer, %100 değildir). |

### 9.3 Senaryolar

**S1. Tutulmuş soru, uçtan uca.** P5 dilim 5'in S1/S2 desenini izleyen, sahibin literatürünü bildiği bir soru (Kurt 2017 kümesi yeniden kullanılabilir ya da yeni bir tutulmuş küme; §11 soru 9) kopya kütüphanede baştan çalıştırılır: arama → tarama → PDF toplama → kanıt tablosu doldurma (eş zamanlı, dilim 0) → rapor yazımı (dilim 1) → [varsa] Chain of Ideas (dilim 2) → [varsa] bir aday üzerinde kill-search (dilim 3) → sahip ya da Claude bir iddiayı elle düzenler → bir bölüm yeniden yazdırılır → bir hücre değiştirilir, stale bandı gözlenir.

**S2. Tekrar.** Rapor yazımı aynı girdilerle bir kez daha çalıştırılır (P5 dilim 5 S3 deseni); iki çalışma arasındaki fark, düzenleme etkisi sayılmadan önce bilinmesi gereken gürültüdür.

**S3. Düzenleme ve bayatlama senaryosu (yeni, dondurulmuş bir dizi).** Ölçümden ÖNCE yazılan, sabit bir olay dizisi (§8'deki testlerin gerçek-model karşılığı, ama burada model sonucu değil bayrak/eşleşme davranışı ölçülür):

1. Geçerli bir rapor üret.
2. IV'te bir iddiayı elle düzenle (kanıtı koru).
3. Kanıt tablosunda o iddianın dayandığı bir hücreyi `cell_recheck` ile değiştir → **beklenen: IV'te bayrak açılır, insan düzenlemesi değişmez.**
4. Bir kaynağı araştırmadan çıkar (D50) → **beklenen: o satırın hücrelerine dayanan bölümlerde bayrak; rapor düzeyi bant da açılır.**
5. IV'ü yeniden yazdır → **beklenen: 2. adımdaki düzenleme eşleşirse korunur (karşılaştırmalı gösterilir), eşleşmezse "eşleşmedi" diye sayılır; 3. ve 4. adımın açtığı bayraklar kapanır.**
6. [dilim 2 varsa] bir çizgi bağını sil → **beklenen: III'ün ilgili cümlesi ve varsa VI adayı bayraklanır.**
7. [dilim 3 varsa] bir adayın kill-search'ünü bitir → **beklenen: rozet hemen güncellenir, VI/VII metni bayraklanır.**
8. Raporu yayımla → **beklenen: canlı bayrak yokken yayım başarılı, `report_version` atanır/artar (§11 soru 2'nin cevabına göre).**

Her adımda "beklenen" ile "gerçekleşen" satır satır karşılaştırılır; R19/R20 buradan hesaplanır.

### 9.4 Kurallar (P5 dilim 5'ten aynen)

- Canlı kütüphaneye yazılmaz; kopya `DEIXIS_DATA_DIR`, ayrı port (8799 deseni).
- Bütün gerçek model adımları `gpt-5.6-luna` ile, her rol ayrı ayrı yazılarak.
- Beklenti çalıştırmadan önce dondurulur ve commit'lenir; sonradan değiştirilmez.
- Etiket (bilinen küme, dondurulmuş dizi) ile sonuç ayrılır.
- İnsan ve ajan etiketi ayrı raporlanır; ikisi aynı hücreye baktıysa uyuşma oranı yazılır (§11 soru 5).
- Ayar/kod değişikliği ölçüm değildir; değişiklikten önceki/sonraki çalışma ayrı raporlanır.
- Sonuç bir kalite iddiası değildir; tek soru ve tek model genelleme göstermez.

### 9.5 Araç

`scripts/p6_eval/measure_report.py` (dilim 1'in planladığı, henüz yazılmadı) genişletilir; ayrı bir araç açılmaz (P5'in "tek ölçüm aracı" tercihiyle tutarlı, dilim 1 §1n). Yeni alt komutlar:

- `measure_report.py edit-diff --report <id> --before <snapshot> --after <snapshot>`: bir rewrite öncesi/sonrası `report_claim_matches` tablosunu okuyup eşleşen/eşleşmeyen iddia sayısını, `citation_overlap` dağılımını yazar (R20).
- `measure_report.py stale-check --report <id> --events <events.json>`: §9.3'teki dondurulmuş olay dizisini uygular, her adımdan sonra `report_stale_flags`'i okuyup beklenen/gerçekleşen karşılaştırmasını (R19) `stale-review.md`'ye yazar.
- `measure_report.py edit-score --sheet <review.md>`: işaretlenmiş inceleme sayfasını okuyup R18/R19/R20 özetini üretir (mevcut `score`/`cells-score` deseninin aynısı).

Çıktılar `.local/p6-eval-<tarih>/` altında kalır, depoya girmez; özet `docs/decisions.md`'ye D-girdisi olarak yazılır.

### 9.6 Ön koşullar — sahipten önce alınması gerekenler

1. Hangi tutulmuş soru(lar) kullanılacağı (Kurt 2017'nin tekrarı mı, yeni bir küme mi; §11 soru 9).
2. Etiketleme sorumluluğu: sahip mi Claude mu, hangi oranda (§11 soru 5); P5 dilim 5'te sahip bunu Claude'a devretmişti (§11 D55'in kaydı), aynı devrin burada da geçerli olup olmayacağı sorulmalı.
3. Dilim 2 ve 3'ün bu ölçüme dahil olup olmayacağı — ikisi de henüz kabul edilmiş bir tasarım değil (§11 soru 6).
4. §9.3'teki dondurulmuş olay dizisinin sahip tarafından gözden geçirilmesi (adımların gerçekçi olup olmadığı).
5. Sayısal eşiklerin (§5'teki 0.6 Jaccard gibi) bu ölçümden önce mi sonra mı kesinleştirileceği (bu not önerilen bir varsayılan veriyor, ölçülmedi).

## 10. Varsayımlar

- Bu not, dilim 1'in **planındaki** adları kullanıyor; dilim 1 henüz uygulanmadığı için gerçek kod yürütme sırasında küçük farklar taşıyabilir (dilim 1'in kendi notunun "Uygulama farkları" bölümü gibi, bu not da yürütme sonunda güncellenmeli).
- Düzenleme birimi **iddiadır** (bölüm ya da cümle değil); bu, §11 soru 1'in önerilen cevabıdır ve veri modeli (§4) buna göre kuruldu. Sahip başka bir birim seçerse §4'ün `report_claim_revisions` tasarımı yeniden gözden geçirilmeli.
- Rapor planının yalnız `scope_statement` alanı düzenlenebilir; `research_questions`/`glossary`/`axes` bu dilimde düzenlenmez (§4).
- Kimlik eşleştirme eşikleri (0.6 Jaccard vb.) ölçülmemiş önerilen varsayılanlardır; §9.3'teki ölçüm bunları sınar, gerekirse yürütme sırasında ayarlanır.
- Dilim 2 ve 3 kodda yokken bu dilimin onlara bağlı kısımları (chain link/candidate bayatlaması, `stable_gap_id`'nin dilim 3 tarafından kullanılması) **inert** kalır: tablolar var ama hiçbir satır yazılmaz, testler sentetik veriyle veya atlanarak geçer. Bu, dilim 4'ün dilim 2/3'ten önce uygulanabileceği varsayımına dayanır (§11 soru 6).
- Bir bölümün yeniden yazılması hâlâ dilim 1'in "bağımlıları durdurur" kuralına tabidir (§2 karar 11); bu dilim yalnız YAYIMLANMIŞ bir raporun düzenleme-sonrası akışını ekliyor, ilk yazım sırasındaki tur/bağımlılık mantığını değiştirmiyor.
- "Yayımla" eylemi (§2 S11) bu notun **önerisidir**, dilim 1'in tasarımında yoktu; §11 soru 2 bunu sahibe soruyor. Sahip "her düzenlemede otomatik yeni versiyon" derse §6'daki durum makinesi basitleşir (yayımlama adımı kalkar).

## 11. Dilim 1, 2 ve 3'ten beklenenler

**Dilim 1'den (rapor çalışması) beklenenler** — bu not bunları olduğu gibi tüketir, üretmez:

- `ReportStore`, `reports`, `report_sections`, `report_claims`, `report_claim_refs`, `report_citation_links`, `report_gaps`, `report_snapshot`, `report_phrase_repairs` tabloları ve sütun adları.
- `report_claims.claim_key`, `report_gaps.gap_id`'nin per-rapor benzersizliği ve bölüm yeniden yazımında yeniden verilmesi kuralı (bu notun §5'i tam olarak bunun üstüne kurulur).
- `build_snapshot`, `run_assembly_checks`, `run_report_review` fonksiyonları ve montaj denetiminin 14 kuralı (bu dilim onlara dokunmaz, yalnız insan düzenlemesi sonrası yeniden çalıştırır).
- `report_sections.status` (`pending`/`running`/`valid`/`draft`/`failed`) ve `reports.status` (`in_progress`/`valid`/`draft`) durum makineleri; bu dilim bunları değiştirmez, üstüne ekler.
- `reports.report_version`'ın yalnız `valid` durumda atanma kuralı (D23/D56 paraleli).
- Rapor-düzeyi "kanıt değişti" bandı (`report_view`'daki `staleBand`) — bu dilim onu bölüm düzeyine tamamlayıcı olarak genişletir, yerine geçmez.
- `/api/researches/{id}/reports` uç ailesi ve `ReportView.tsx`/`reportMarkdown.ts` — bu dilim buraya düzenleme formu ve stale bandı ekler.

**Dilim 2'den (Chain of Ideas) beklenenler:**

- `chains`, `chain_members`, `chain_links`, `chain_link_revisions`, `chain_link_evidence`, `chain_end_uncertainties` tabloları (henüz taslak).
- Çizgi bağı düzenlemesinin `cell_revisions` deseniyle append-only olması (S6, dilim 2 §2) — bu notun §2 S8'i ve §4'ün `report_section_dependencies(dep_kind='chain_link')` satırı buna dayanır.
- `report_gaps.kind = 'chain_end_uncertainty'` değerinin dilim 1'in genişleyebilir `kind` alanına eklenmesi.
- **Dilim 2'nin notu bu dilimin konusuna hiç girmiyor** ("stale" kelimesi dilim 2'nin notunda hiç geçmiyor, doğrulandı); yani III/VI'nın çizgi bağı değişikliğinde bayatlaması tamamen bu notun önerisidir, dilim 2 tarafında bir karşılığı yok.

**Dilim 3'ten (kill-search) beklenenler:**

- `research_candidates`, `candidate_versions`, `kill_searches`, `claim_search_memberships`, `claim_matrix_cells`, `candidate_status_history` tabloları (henüz taslak).
- "İki tablo, tek doğruluk kaynağı" kuralı: `report_gaps.kill_search_status`'un `research_candidates.status`'tan aynı işlemde kopyalanması (rozet); metnin ayrı, donuk kalması (dilim 3 §5).
- `research_candidates.source_gap_id TEXT UNIQUE REFERENCES report_gaps.id` — **bu not bu alanın `report_gaps.id` yerine `report_stable_gaps.id`'ye bağlanmasını önerir** (§5); bu, dilim 3'ün notunda düzeltilmesi istenen tek somut değişikliktir ve dilim 3 kabul edilmeden önce ona iletilmeli.
- `undecided` durumunun (dilim 3 §6) `report_gaps.kill_search_status` CHECK listesine eklenmesi dilim 1'e bağımlıdır (dilim 3'ün kendi notunda zaten yazılı, §15.1); bu dilim ek bir bağımlılık getirmiyor.

## 12. Sahibe sorulanlar

Her soruda önerim ilk seçenektir; yanıt gelmezse ilk seçenek alınır ve uygulama ona göre başlar.

1. **Düzenleme birimi.**
   - a. İddia (`report_claims` satırı) — kanıt bağının zaten bu düzeyde tutulduğu, D37'nin hücre biriminin aynısı. (öneri)
   - b. Paragraf (birkaç iddianın birleşik okuma birimi) — insan gibi okur ama birden çok iddiayı tek metne indirip geri `claim_key`'lere bölmek gerekir, kanıt bağı belirsizleşir.
   - c. Cümle — `report_phrase_repairs`'in `sentence_id`'sini yeniden kullanır gibi görünür ama o mekanizma kalıp onarımı içindir, kanıt bağı taşımaz; bir cümlenin kendi alıntısı yoktur.
   
   *Yanıt yoksa alınacak:* a — bu notun §4/§5'i bu varsayımla kuruldu.

2. **Düzenlenmiş rapor `report_version`'ı ne olur.**
   - a. Düzenlemeler yeni bir "Yayımla" eylemiyle toplanır; montaj denetimi geçerse ilk kez ya da bir sonraki `report_version` atanır (D56'nın "yapısal geçerlilik ≠ yayım" ayrımına paralel). Ara düzenlemeler sırasında numara sabit kalır. (öneri)
   - b. Her kaydedilen düzenleme otomatik yeni bir `report_version` alır (answer'ın her structurally_valid sonucunun numara alması gibi).
   - c. `report_version` düzenlemeden hiç etkilenmez; düzenlenmiş rapor hep aynı numarayı taşır, dışa aktarımda "düzenlendi" notu yeter.
   
   *Yanıt yoksa alınacak:* a.

3. **İnsan düzenlemesi `report_review`'a gönderilsin mi.**
   - a. Hayır, otomatik değil; ayrı, isteğe bağlı bir "Bu düzenlemeyi denetle" eylemi olur (D14'ün "isteğe bağlı inceleme ayrı bir sürümdür" ilkesiyle tutarlı, maliyeti sahip kontrol eder). (öneri)
   - b. Evet, her kaydedilen düzenlemeden sonra otomatik çalışır.
   - c. Yalnız "Yayımla" anında bütün düzenlenmiş bölümler için toplu bir inceleme çalışır.
   
   *Yanıt yoksa alınacak:* a.

4. **"Böyle kalsın" kabulü ne zaman süresi dolar.**
   - a. Hiç dolmaz; yalnız o kabulden SONRAKİ bağımsız bir değişiklik yeni bir canlı bayrak açar (§3, §4). Kabulün kendisi asla otomatik geri alınmaz. (öneri)
   - b. Belirli bir süre (ör. 30 gün) sonra otomatik yeniden canlanır.
   - c. Rapor her "Yayımla" işleminde bütün kabuller sıfırlanır, sahip yeniden gözden geçirir.
   
   *Yanıt yoksa alınacak:* a.

5. **Model bir bölümü, o bölümde insan düzenlemesi varken yeniden yazabilir mi.**
   - a. Evet, ama sonuç her zaman bekleyen bir öneridir (§2 S3); tek bölümün elle "Yeniden yaz" istenmesi sahibin kendi eylemidir, engellenmez. (öneri)
   - b. Hayır; insan düzenlemesi olan bir bölüm önce "düzenlemeleri geri al" denmeden yeniden yazılamaz.
   - c. Yalnız tek tek iddialar için izin verilir (`claim_key` düzeyinde kısmi rewrite), bölüm bütünü asla yeniden yazılmaz.
   
   *Yanıt yoksa alınacak:* a.

6. **Bayatlama hesaplaması ne zaman yapılır.**
   - a. Yazma-anında (kanıtı değiştiren transaction bayrağı da yazar); okuma yalnız canlı bayrakları listeler (§3, §4). (öneri)
   - b. Okuma-anında (rapor her açıldığında donmuş anlık görüntü ile canlı kayıtlar karşılaştırılır, dilim 1'in rapor-düzeyi bandındaki gibi ama bölüm düzeyinde).
   - c. Zamanlanmış bir arka plan işiyle periyodik.
   
   *Yanıt yoksa alınacak:* a — CLAUDE.md'nin "tek bağlantı, kısa senkron işlem" kuralıyla en uyumlu olan ve hangi kaydın tetiklediğini kaybetmeyen seçenek budur.

7. **P6 kapanış ölçümü dilim 2 ve 3'ü bekler mi.**
   - a. Hayır; P6 dilim 0, 1, 4, 5 ile kapanır (bu notun R18–R21'i ve dilim 1'in R1–R11'i yeterli), dilim 2 ve 3 kendi kapanışlarını kendi notlarında tanımlar ve ayrı ölçülür. (öneri — dilim 2/3 henüz kabul edilmiş tasarım değil, onları beklemek P6'yı belirsiz süre asıntıya bırakır)
   - b. Evet; kapanış ölçümü dördünü birlikte (0,1,2,3 ve 4) tek bir tutulmuş soru koşusunda ölçer.
   - c. Kısmi: dilim 2/3 o ana kadar uygulanmışsa ölçüme dahil edilir, uygulanmamışsa §9.1'deki "dilim 2/3 varsa" satırları boş bırakılır (bu notun zaten varsaydığı davranış).
   
   *Yanıt yoksa alınacak:* c — bu, a ile b arasında bu notun zaten yazdığı orta yoldur ve ek bir karar gerektirmez.

8. **Kim etiketler (kapanış ölçümünde).**
   - a. Sahip küçük bir örneği etiketler, Claude kalanını; ikisi ayrı raporlanır ve örtüşen kısımda uyuşma yazılır (P5 dilim 5'in soru 2 önerisiyle aynı). (öneri)
   - b. Sahip P5 dilim 5'te olduğu gibi etiketlemeyi tamamen Claude'a devreder; rapor "ajan denetimi" der.
   - c. Sahip kendisi etiketler.
   
   *Yanıt yoksa alınacak:* b — P5 dilim 5'te sahip son anda tam bu devri seçti (§11 D55 kaydı); tekrarı en düşük sürtünmeli varsayımdır.

9. **Kapanış ölçümü hangi tutulmuş soru(lar)ı kullanır.**
   - a. Kurt 2017 kümesini (D34/D55) aynen tekrar kullan; karşılaştırılabilirlik korunur, yeni bir bilinen küme hazırlamaya gerek kalmaz. (öneri)
   - b. Yeni bir tutulmuş soru ve bilinen küme (sahip hazırlar).
   - c. İkisi birden (Kurt + yeni bir soru), D55'in S1/S2 desenini birebir tekrarlar.
   
   *Yanıt yoksa alınacak:* a — en az hazırlık gerektiren ve D55 ile doğrudan karşılaştırılabilen seçenek.

## 13. Alt adımlar

Her alt adımda önce testler yazılır ve kırmızı görülür, sonra uygulanır; sırayla bağımlıdır (1–4 depolama, 5–8 davranış, 9–11 arayüz, 12–14 kapanış). Dosya yolları dilim 1'in `backend/deixis/workflow/report/` paketini ve `apps/web/src/report/`'u genişletir; migration numarası yürütme anında `ls backend/deixis/storage/migrations/` ile teyit edilir (bu not yazılırken en yükseği `0033`, dilim 1'in `0034`'ü henüz uygulanmamış).

1. **Migration: iddia revizyonları.** `backend/deixis/storage/migrations/00NN_report_claim_revisions.sql` — `report_claim_revisions`, `report_claims.current_revision_id`/`version`. Test: `tests/test_migrations.py::test_migration_adds_report_claim_revisions` (tablo var, `runs`/`reports` etkilenmez). Çıkış: migration temiz bir veritabanında ve dilim 1'in test fixture'ında (varsa) hatasız çalışır.
2. **`ReportStore.edit_claim`/`decide_section_rewrite` iskeleti.** `backend/deixis/workflow/report/store.py`'ye eklenir (yeni dosya açılmaz). Test: `tests/test_report_store.py::test_edit_claim_keeps_citations_by_default_and_creates_human_edit_revision`, `test_edit_claim_conflicts_on_stale_expected_version`. Çıkış: D37'nin `edit_cell` testlerinin birebir karşılığı geçer.
3. **Migration: bölüm yeniden yazma önerisi ve bağımlılık/bayrak tabloları.** `00NN+1_report_stale_and_rewrite.sql` — `report_section_revisions`, `report_stale_flags`, `report_section_dependencies`. Test: `tests/test_migrations.py::test_migration_adds_stale_and_rewrite_tables`. Çıkış: foreign key denetimi temiz.
4. **Migration: kararlı kimlikler.** `00NN+2_report_stable_identity.sql` — `report_stable_claims`, `report_claim_matches`, `report_stable_gaps`, `report_gaps.stable_gap_id`, `report_claims.stable_claim_id`. Test: `tests/test_migrations.py::test_migration_adds_stable_identity_tables`. Çıkış: dilim 1'in `report_gaps`/`report_claims` tabloları (varsa) etkilenmeden yeni sütunları alır.
5. **Kanıt bağımlılığı ve bayrak yazma.** `backend/deixis/workflow/report/staleness.py` (yeni dosya): `flag_dependents_of_cell(store, reports, cell_id, reason)`, `flag_dependents_of_source(...)`, `flag_dependents_of_column(...)`, `flag_dependents_of_plan(...)`; her biri `report_citation_links`/`report_claim_refs`/`report_section_dependencies` üzerinden ilgili `(report_id, section_id)` çiftlerini bulup `report_stale_flags` yazar. Test: `tests/test_report_staleness.py` — §8'deki "Bayatlama" testlerinin her biri (hücre, kaynak, sütun, plan; çizgi bağı ve aday testleri dilim 2/3 sentetik veriyle ya da inert). Çıkış: tables.py'nin `edit_cell`/D50'nin `remove_sources`/`rename_column` gibi mevcut mutasyon noktalarına birer çağrı eklenir, mevcut testleri kırmaz.
6. **Bayrak kabul ucu.** `POST /api/researches/{rid}/reports/{report_id}/sections/{sid}/acknowledge-stale` — `ReportStore`'a `acknowledge_stale(report_id, section_id)`. Test: `tests/test_report_api.py::test_acknowledge_stale_closes_open_flags_but_not_future_ones`. Çıkış: §2 S10 senaryosu geçer.
7. **Bölüm yeniden yazma: bekleyen öneri akışı.** `backend/deixis/workflow/report/sections.py`'ye (dilim 1'in dosyası) eklenir: bir bölüm yeniden yazıldığında, o bölümde canlı `human_edit` varsa sonucu `report_section_revisions` (pending) olarak sakla, yoksa doğrudan yaz. Test: `tests/test_report_sections.py::test_rewrite_with_human_edits_creates_pending_proposal`, `test_rewrite_without_human_edits_applies_directly`. Çıkış: §2 S3/S4 geçer.
8. **Kimlik eşleştirme.** `backend/deixis/workflow/report/identity.py` (yeni dosya): `match_claims(old_claims, new_draft_claims) -> list[ClaimMatch]` (Jaccard + paragraf + metin benzerliği, §5), `fingerprint_gap(kind, basis) -> str`, `resolve_stable_gap(store, research_id, kind, basis) -> str`. Test: `tests/test_report_identity.py` — §8'deki "Kimlik eşleştirme" testlerinin hepsi. Çıkış: eşik değerleri (0.6 Jaccard) test sabiti olarak modülün başında, değiştirilebilir.
9. **Bölüm yeniden yazma önerisinin kabul/red ucu.** `POST .../sections/{sid}/rewrite-proposals/{rev}/accept` (eşleştirmeyi çalıştırır, eski iddiaları geçmişe taşır, eşleşmeyenleri `changed_claims` içinde döner), `.../dismiss`. Test: `tests/test_report_api.py::test_accept_rewrite_proposal_reports_unmatched_human_edits`. Çıkış: §8 T09 c/d senaryoları geçer.
10. **Arayüz: iddia düzenleme formu.** `apps/web/src/report/ReportView.tsx`'e düzenleme modu (§7 madde 1); `apps/web/src/api.ts`'e `api.editReportClaim`. Test: `npm run build && npm run lint`; Playwright: bir iddia düzenlenir, 409 senaryosu (iki sekme). Çıkış: masaüstü ve 390 px, açık/koyu ekran görüntüsüyle kendi doğrulanır.
11. **Arayüz: rewrite bandı ve stale bandı.** Aynı dosyaya §7 madde 2–5. Test: Playwright `apps/web/e2e/report-editing.spec.ts` (yeni dosya) — §8 Web senaryosu. Çıkış: fixture sunucusunda scriptlenmiş model ile uçtan uca geçer.
12. **Yayımlama ucu ve durum makinesi.** `POST .../reports/{report_id}/publish` — canlı bayrak/bekleyen öneri varsa 409 ve nedeni; yoksa `finalize()` çağrılır. Test: `tests/test_report_api.py::test_publish_blocked_by_open_stale_flags_or_pending_rewrites`. Çıkış: §2 S11, §6 tablosu geçer.
13. **Kapanış ölçümü aracı.** `scripts/p6_eval/measure_report.py`'ye `edit-diff`/`stale-check`/`edit-score` alt komutları (§9.5); önce modelsiz testlerle (`tests/test_measure_report_editing.py`, sentetik `report_claim_matches`/`report_stale_flags` JSON'u). Çıkış: alt komutlar sentetik veriyle çalışır, testler kırmızıdan yeşile döner.
14. **Kapanış ölçümü koşusu ve kayıt.** §9.6'daki ön koşullar sahiple netleştikten sonra: kopya kütüphane, port 8799, `gpt-5.6-luna`; §9.3'ün S1/S2/S3 senaryoları çalıştırılır; sonuç dondurulmuş beklentilerle (bu alt adımdan önce ayrı bir dosyada donmuş, P5 dilim 5 kuralı) satır satır karşılaştırılır; `docs/decisions.md`'ye D-girdisi, `docs/product/p6-report-design.md`'ye "Durum" güncellemesi. Çıkış: tam backend suite, `npm run build && npm run lint`, acceptance, `git diff --check`; canlı kütüphaneye hiçbir şey yazılmaz.

