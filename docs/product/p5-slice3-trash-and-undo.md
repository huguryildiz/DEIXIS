# P5 dilim 3 — Tablo ve kaynak için çöp kutusu, geri alma ve seçili kaynaklardan tablo: tasarım notu

**Tarih:** 16 Eylül 2026. **Durum:** §8'deki yedi soru sahibin yanıtıyla kapandı; her birinde önerilen seçenek seçildi ([D50](../decisions.md)). §9'un 1–4. alt adımları uygulandı (migration `0029_trash_and_corpus_removal.sql`); 5–8 bekliyor. Uygulama farkları §9'un sonunda.

**Kısaca:** Bugün yalnız araştırma çöpe gider ve geri gelir. Tablo çöpe atılabiliyor ama yalnız API ile ve geri getirme yolu yok. Bir kaynağı araştırmadan çıkarmanın hiçbir yolu yok. Bu dilim üç şey ekler. (1) Tablo, tablo şablonu ve "araştırmadan çıkarılan kaynak" da çöp kutusuna gider, oradan geri gelir. (2) Çöpe atma ve çıkarma işlemlerinden hemen sonra "Geri al" bildirimi çıkar. (3) Sources sekmesinde seçilen kaynaklarla tablo başlatılır. Hiçbir işlem pasajı, dosyayı, hücre revizyonunu ya da yanıt kanıtını silmez; kalıcı silme ayrı ve açıkça onaylanan bir eylemdir. Bir kaynağı araştırmadan çıkarmak kütüphanedeki kaydına ve ortak PDF'ine dokunmaz (T15).

## 1. Kodda zaten olanlar

Aşağıdakiler 16 Eylül 2026'da çalışma ağacındaki koddan okundu (D45–D49 dahil, commit'lenmemiş). Canlı kütüphane sayıları salt okunur bir SQLite bağlantısıyla alındı.

| Parça | Doğrulanan durum | Dilim 3 için anlamı |
|---|---|---|
| Araştırma çöpü (0010, `Store.trash_research`, `restore_research`, `purge_research`) | Etkin run varsa 409. `GET /api/trash` yalnız araştırmaları listeler. Kalıcı silme `research_purge_authorizations` satırı yazar; `step_inputs`, hücre revizyonu, sütun revizyonu ve hücre kanıtı silme tetikleyicileri yalnız bu satır varken açılır. Paylaşılan kaynak (başka araştırmada üyelik ya da aday) ve başka asset'in gösterdiği dosya kalır. | Kalıp hazır. Çöp listesi türlere genişler. |
| Tablo çöpü (`evidence_tables.trashed_at`, `TableStore.trash_table`, `DELETE …/tables/{tid}`) | Beklenen sürümle yazılır, `table_changed` olayı atar. Arayüzde düğmesi yok; `api.ts`'de istemci işlevi yok. Geri getirme ve tek tablo kalıcı silme yok. Tetikleyiciler yüzünden tek bir tablonun revizyonları bugün silinemez. | Geri getirme kolay (`trashed_at = NULL`). Tek tablo kalıcı silme yeni bir yetki satırı ve tetikleyici yeniden kurulumu ister (§8, soru 3). |
| Şablon çöpü (`table_templates.trashed_at`, `DELETE /api/table-templates/{id}`) | Arayüzde yok. Şablon kanıt taşımaz (yalnız sütun tanımları). | Tam silme serbest; geri getirme eklenir. |
| Tablo satırı (`table_rows.removed_at`) | "Remove from table" var; bildirim "Hücreleri saklanır, kaynağı yeniden eklerseniz geri gelir" der. Yeniden ekleme `removed_at` temizler. | Geri alma bildirimi aynı yolu kullanır; çöp listesine girmez. |
| Tablo sütunu (`table_columns.removed_at`) | "Remove column" var; geri getirme ucu ve arayüzü yok. Yeniden eklemek yeni sütun ve boş hücre demektir. | `POST …/columns/{cid}/restore` eklenir; geri alma bildirimi bunu çağırır. |
| Yanlış PDF çekme (`remove_asset`, `removal_reason = 'wrong_file'`, D45) | Geri getirme yok. Dahil kaynakta seçim revizyonunu artırır. Kaynak sürümü başına tek kullanılan PDF indeksi (0027) var. | Geri alma, yalnız yerine başka PDF eklenmediyse mümkün (§8, soru 4). |
| Araştırmadan kaynak çıkarma | **Yok.** `corpus_memberships` satırı yalnız kalıcı silmede gider. Library'de de çıkarma yok (D41 Limits). Kullanıcının tek aracı Exclude'dur; o bir tarama kararıdır ve gerekçesiyle saklanır. | Yeni işlem. Exclude ile karıştırılmamalı. |
| `Store.is_member` | Pasaj görünümü (`passage_view`) ve `GET …/assets/{aid}` bununla araştırma sınırını denetler. | Çıkarma üyelik satırını silerse eski yanıt alıntısı ve hücre kanıtı 404 verir. Bu yüzden çıkarma yumuşak olmalı: "şu an kaynak mı" ile "bu araştırmanın kanıtı buna bağlanabilir mi" ayrılır. |
| `corpus_memberships` sorguları | `store.py` ve `views.py`'de 16 yer; `candidates` 8 yer. `included_sources` yalnız `selections` okur, üyeliğe bakmaz. | Çıkarılan kaynağın yanıt girdisine, doldurmaya ve PDF toplamaya girmemesi için `included_sources` ve kaynak listeleri etkin üyeliğe bağlanmalı. Her sorgu tek tek gözden geçirilir. |
| Tablo oluşturma (`create_table(rows=…)`) | API `rows` alır ve üyelik denetler. Arayüz her zaman `rows` göndermez, yani tablo dahil edilen kaynaklarla başlar. | "Seçili kaynaklardan tablo başlat" için backend hazır; eksik olan Sources'ta çoklu seçim. |
| Arayüz çöp sayfası (`App.tsx`, `#trash`) | Yalnız araştırmalar: Restore ve onaylı "Delete permanently". Geri alma bildirimi hiçbir yerde yok. | Sayfa türlere göre gruplanır. |

**Canlı kütüphane (salt okunur, 16 Eylül 2026):** 23 araştırma, 6'sı çöpte. 1 kanıt tablosu (çöpte değil), 0 şablon, çıkarılmış satır ve sütun 0. 2.526 üyelik; 510 kaynak sürümü birden çok araştırmada. Kullanılan PDF 69. Exclude edilmiş seçim 559. Yani tablo çöpü canlıda henüz boş bir ihtiyaç; asıl sık kullanılacak yol kaynak çıkarma ve seçili kaynaklardan tablo.

## 2. Senaryolar

### S1. Tabloyu çöpe at, geri getir, kalıcı sil

- Çöpe atma bugünkü gibi `trashed_at` yazar. Etkin tablo run'ı (`table_fill`, `cell_recheck`, `table_columns`) o tabloyu hedefliyorsa 409.
- Geri getirme `trashed_at = NULL`, tablo sürümü artar. Satırlar, sütunlar, hücreler, öneriler aynen döner. Araştırma çöpteyse tablo tek başına geri getirilemez; önce araştırma.
- Araştırma çöpe gidince tabloları ayrıca listelenmez; araştırmayla birlikte gider ve gelir.
- Kalıcı silme (soru 3'e bağlı): tablonun hücreleri, revizyonları, kanıt bağları, satır ve sütunları silinir; pasajlar, dosyalar, StepInput'lar ve run kayıtları kalır (başka kanıtın da dayanağıdır). Onay ekranı insan düzenlemesi sayısını ayrıca yazar.

### S2. Kaynağı araştırmadan çıkar

Exclude'dan farkı: Exclude "bu kaynak soruma uymuyor" kararıdır, kaynak listede gerekçesiyle durur. Çıkarma "bu kayıt bu araştırmaya hiç ait değil" demektir: yanlış yüklenen dosya, Library'den yanlışlıkla sürüklenen eser, gürültü.

- `corpus_memberships` satırı silinmez; `removed_at` alır. Etkin kaynak listeleri, yanıt girdisi, PDF toplama (D49), doldurma planı ve Library'nin proje grupları çıkarılmış üyeliği görmez.
- Seçim satırı değişmez, ama `included_sources` çıkarılmış kaynağı vermez. Kaynak dahil idiyse seçim revizyonu artar (yanıt `stale_selection` gösterir; bu durumda o metin doğrudur).
- Kanıt yolu açık kalır: eski yanıt alıntısı ve hücre kanıtı pasajı açar; PDF sekmesi bu araştırmanın kanıtı o asset'e bağlıysa açılır (D45'teki `research_cites_asset` kalıbı). Alıntı ve hücrede "Bu araştırmadan çıkarıldı" etiketi görünür.
- Kütüphane kaydı, `source_assets`, pasajlar, gömme vektörleri ve dosya hiç değişmez. Kaynak başka araştırmada kullanılıyorsa orada hiçbir şey fark etmez (T15).
- Çıkarılan kaynağın tablodaki satırı gizlenir, hücreleri kalır; doldurma onu planlamaz (soru 6).
- Aynı eserin öteki sürümleri (D46/D48): başı olmayan bir sürüm tek başına çıkarılır. Eserin başı çıkarılırsa eserin bu araştırmadaki bütün sürümleri birlikte çıkar; onay metni sürüm sayısını yazar (soru 2).
- Yeni arama çıkarılmış kaynağı yeniden bulursa üyelik çıkarılmış kalır; Sources özetinde "n kaynak yeniden bulundu, sizin çıkardığınız için gösterilmiyor" yazar (soru 2).
- Etkin run varken 409.

### S3. Geri alma bildirimi

- Çöpe atma, çıkarma, satır ve sütun çıkarma, yanlış PDF çekme işlemlerinden sonra mevcut bildirim (toast) "Geri al" düğmesi taşır. Düğme, çöp ekranındaki geri getirme ucunun aynısını çağırır; ayrı bir "undo" günlüğü yoktur.
- Bildirim kaybolunca işlem çöp ekranından (ya da satır için "kaynağı tabloya yeniden ekle") geri alınır. Süre dolması hiçbir şeyi kalıcı silmez.
- Geri alma beklenen sürüm taşır. Arada başka bir yazı olduysa (ör. sütun yeniden eklendi, PDF değiştirildi) 409 ve açıklama.

### S4. Seçili kaynaklardan tablo başlat

- Sources sekmesinde her kaynak satırında seçim kutusu (başlık yanında), üstte "Tümünü seç (görünen)". Seçim varken alt çubuk: "{n} kaynak seçildi · Tablo başlat · Mevcut tabloya ekle · Araştırmadan çıkar".
- "Tablo başlat" `create_table(rows=seçilenler)` çağırır ve Evidence sekmesini açar. Satır sırası seçim sırası değil, Sources'taki sıradır.
- Dahil edilmemiş kaynak da seçilebilir (tablo satırları seçimden bağımsızdır, D37); onay satırında "{k} tanesi dahil değil" yazar (soru 5).
- Seçim URL'de ya da sunucuda saklanmaz; sekme değişince temizlenir.

## 3. Kurallar

- **Çöp bir görünürlük durumudur, silme değildir.** Çöpteki nesnenin her kaydı yedeklenir ve geri yüklenir; kanıt tetikleyicileri değişmez.
- **Kalıcı silme dar ve açıktır.** Yalnız çöpteki bir nesneye uygulanır, onay ister, etkin run'da 409 verir, silemediği dosyaları raporlar (bugünkü `files_not_removed` gibi).
- **Ortak şeye dokunulmaz.** Pasaj, asset, dosya, gömme, kütüphane kaydı yalnız araştırma kalıcı silmesinde ve yalnız başka hiçbir araştırma (çıkarılmış üyelik dahil, çünkü onun kanıtı hâlâ açılır) kullanmıyorsa silinir.
- **Kendiliğinden boşaltma yok.** Çöp süre dolunca temizlenmez (öneri; yerel araştırma kaydı ve provenance için).
- **Kanıt yeniden yazılmaz.** Çıkarma ve çöpe atma hücre revizyonu, yanıt, iddia, kanıt bağı üretmez ya da değiştirmez; yalnız görünümler etiket hesaplar.

## 4. Veri modeli taslağı

**0029 — çöp ve çıkarma.** SQL'in geçerli hali uygulamada migration dosyası olacak.

```sql
ALTER TABLE corpus_memberships ADD COLUMN removed_at TEXT;
ALTER TABLE corpus_memberships ADD COLUMN removal_note TEXT;          -- isteğe bağlı kullanıcı notu
CREATE INDEX corpus_memberships_active ON corpus_memberships(research_id) WHERE removed_at IS NULL;

-- Tek tablo kalıcı silmesi (soru 3 "a" ise): araştırma yetkisinin tablo düzeyindeki eşi.
CREATE TABLE table_purge_authorizations (table_id TEXT PRIMARY KEY);
-- column_revisions_no_delete, cell_revisions_no_delete, cell_evidence_links_no_delete tetikleyicileri
-- "research_purge_authorizations VEYA table_purge_authorizations" koşuluyla yeniden kurulur.
```

- `Store.is_member(research_id, svid)` iki işleve ayrılır: `is_active_member` (listeler, yeni iş, tabloya satır ekleme) ve `was_member` (kanıt açma, bugünkü davranış). Her `corpus_memberships` ve `candidates` sorgusu hangisine ait olduğu yazılarak gözden geçirilir.
- `evidence_status` gibi saklanmaz: alıntı ve hücre için `source_removed_from_research` görünümde hesaplanır.
- Olaylar: `table_trashed`, `table_restored`, `table_purged`, `source_removed`, `source_restored`, `column_restored`, `asset_restored`.

**Uçlar** (mevcut CSRF, Host/Origin ve üyelik 404 kuralları):

| Uç | Gövde / sorgu | Sonuç |
|---|---|---|
| `GET /api/trash` (genişler) | — | `{researches, tables, sources, templates}`; her öğede araştırma adı, tarih ve etki sayıları |
| `POST /api/researches/{rid}/tables/{tid}/restore` | `expected_version` | Geri getirir; araştırma çöpteyse 404 |
| `DELETE /api/trash/tables/{tid}` | — | Kalıcı silme (soru 3); çöpte değilse 404, etkin run 409 |
| `DELETE /api/researches/{rid}/sources` | `{source_version_ids, note?}` | Toplu çıkarma; etkin run 409; üye olmayan 422 |
| `POST /api/researches/{rid}/sources/restore` | `{source_version_ids}` | Geri getirme; seçim revizyonu gerekirse artar |
| `POST …/tables/{tid}/columns/{cid}/restore` | `expected_version` | Sütunu geri getirir |
| `POST …/sources/{svid}/assets/{aid}/restore` | — | Yanlış çekilen PDF'i geri getirir (soru 4); başka PDF kullanılıyorsa 409 |
| `POST /api/table-templates/{id}/restore`, `DELETE /api/trash/templates/{id}` | — | Şablon |
| `POST /api/researches/{rid}/tables` (mevcut) | `rows` | Seçili kaynaklardan tablo; arayüz artık `rows` gönderir |

## 5. Arayüz

`.impeccable.md`'ye uyulur. Kırmızı yalnız kalıcı silmede; çıkarma ve çöpe atma nötr eylemdir. Her işaretin metni vardır.

1. **Çöp sayfası.** Başlık ve alt metin aynı çerçevede (`.collection`). Gruplar: Araştırmalar, Kanıt tabloları, Araştırmadan çıkarılan kaynaklar, Tablo şablonları; boş grup gösterilmez. Satırda ad, ait olduğu araştırma, çöpe atılma tarihi ve etki ("12 hücre · 3 insan düzenlemesi", "2 yanıt alıntısı bu kaynağı gösteriyor"), Restore ve (izin verilen türde) "Delete permanently". Kaynak grubu araştırmaya göre katlanır; grup başında "Hepsini geri getir".
2. **Evidence sekmesi.** Tablo menüsüne "Move to Trash". Seçici birden çok tablo gösteriyorsa çöpe atılan listeden çıkar; son tablo çöpe atıldıysa boş durum ve "Çöpte 1 tablo" bağlantısı.
3. **Sources sekmesi.** Seçim kutuları, alt çubuk (S4), satır menüsünde "Araştırmadan çıkar…". Onay: "{n} kaynak bu araştırmanın listesinden, yanıt girdisinden ve tablolarından çıkar. Kütüphanedeki kayıt ve PDF'i silinmez; {m} araştırma daha onu kullanıyor. Eski alıntılar açılmaya devam eder." Özet satırında "{k} kaynağı çıkardınız · Çöpte göster".
4. **Geri alma bildirimi.** Mevcut `Toast` bileşenine eylem düğmesi; klavyeyle ulaşılabilir, ekran okuyucuya `role=status` ile duyurulur, süre hareket azaltma tercihinden bağımsızdır.
5. **Alıntı ve hücre.** Çıkarılmış kaynağın alıntısı ve hücre panelinde "Bu araştırmadan çıkarıldı" etiketi; `PassageSheet` bandında aynı cümle ve geri getirme bağlantısı.
6. Masaüstü ve 390 px'te, açık ve koyu temada; alt çubuk dar ekranda sabit ve içerik üstüne binmez.

## 6. Testler (taslak; alt adımlar §9'da sıralanacak)

**Depolama ve migration**

- 0028'deki veritabanında 0029: üyelik, tablo ve kanıt sayıları değişmez; tetikleyiciler araştırma kalıcı silmesinde hâlâ çalışır.
- Tek tablo kalıcı silmesi yalnız o tablonun revizyonlarını siler; aynı araştırmanın öteki tablosuna ve yetki olmadan revizyon silmeye tetikleyici hâlâ izin vermez.

**T15: çöp ve ortak dosya**

- Kaynağı A'dan çıkar: B'de aynı kaynak listede, PDF açılır, yanıt ve doldurma girdisi onu taşır; asset, pasaj ve dosya hash'i aynı.
- A'dan çıkarılmış kaynak: A'nın yanıt girdisinde, PDF toplama planında (D49), doldurma planında ve Library proje grubunda yok; A'nın eski alıntısı pasajı ve (kanıt bağı varsa) PDF'i açar.
- A kalıcı silinir, kaynak B'de etkin: dosya kalır. A kalıcı silinir, kaynak yalnız A'da (çıkarılmış) idi: dosya ve kayıt bugünkü kurala göre silinir. B'de çıkarılmış üyelik varken A silinir: dosya kalır.
- Yedek ve geri yükleme: çöpteki tablo, çıkarılmış üyelik ve geri getirilebilir sütun aynen döner; geri getirme yedekten sonra da çalışır.
- Yeni arama çıkarılmış kaynağı bulur: üyelik çıkarılmış kalır, aday sayılır ama Sources'ta etkin görünmez (soru 2'ye bağlı).

**Tablo ve şablon**

- Çöpe at → geri getir: hücreler, insan düzenlemeleri, bekleyen öneriler, sürüm artışı; etkin run 409; araştırma çöpteyken tablo geri getirme 404.
- Kalıcı silme: onaysız yol yok, çöpte olmayan tablo 404, CSRF.
- Sütun geri getirme: hücreler ve revizyonları geri döner; arada aynı adla yeni sütun eklendiyse iki sütun ayrı kalır.

**Seçili kaynaklardan tablo**

- `rows` ile oluşturma yalnız etkin üyeleri kabul eder; çıkarılmış kaynak 422; dahil olmayan kaynak satır olur (soru 5'e bağlı); idempotency anahtarı tekrarında aynı tablo.

**Geri alma**

- Her geri alma ucunda beklenen sürüm çatışması 409; yanlış çekilen PDF, yerine başka PDF eklenmişse 409 ve tek kullanılan PDF indeksi korunur.

**Web**

- `npm run build`, `npm run lint`.
- Playwright (fixture sunucusu): Sources'ta iki kaynak seç → tablo başlat → satırlar doğru; bir kaynağı çıkar → bildirimde Geri al → döner; tekrar çıkar → çöp sayfasında görünür → geri getir; tabloyu çöpe at → çöpten geri getir → hücre değeri aynı; yanıt alıntısı çıkarılmış kaynakta etiketle açılır.
- Chrome'da masaüstü ve 390 px.

**Gerçek model:** Bu dilim model girdisinin kapsamını değiştirir ama model davranışını değiştirmez; zorunlu değil.

**Bu dilimde geçmeyecekler:** kütüphane düzeyinde bir eseri ya da dosyayı tümden silme; çöpün süreyle kendiliğinden boşalması; hücre revizyonu düzeyinde geri alma (revizyonlar zaten değişmez, "önceki değere dön" ayrı iş); not/Annotation çöpü (notlar henüz yok); Library'den çoklu seçimle tablo başlatma; OCR (dilim 4); aynı dosyanın ayrı eserlerde kayıtlı olması (kimlik eşleştirme).

## 7. Varsayımlar

- Kalıcı silme tek kullanıcılı yerel uygulamada da geri dönüşsüzdür; yedek dışında kurtarma yolu yoktur ve onay metni bunu söyler.
- "Geri al" bildirimi bir oturum içi kolaylıktır; kaynağı çöp ekranıdır. Bildirim kapanınca hiçbir şey değişmez.
- Çıkarma, arama adaylarını silmez: bulunan/tekil/taranmış sayıları (AGENTS.md sayım ayrımı) geçmiş run'lar için değişmez; yalnız etkin kaynak ve dahil sayıları değişir.

## 8. Sahibe sorulanlar

Her soruda önerim ilk seçenekti; sahip yedisinde de onu seçti (16 Eylül 2026).

1. **Çöp ekranı nerede.**
   - a. Mevcut global Trash sayfası türlere göre gruplanır; her öğe araştırmasını adlandırır. (öneri)
   - b. Araştırma içinde ayrı bir Trash bölümü; global sayfa yalnız araştırmalar.
   - c. İkisi birden.
2. **Kaynağı araştırmadan çıkarmanın anlamı.**
   - a. Yumuşak çıkarma: kanıtı açık kalır, dahil idiyse seçim revizyonu artar, yeni arama bulursa çıkarılmış kalır ve özet sayısında görünür. Eser başının çıkarılması eserin bütün sürümlerini birlikte çıkarır. (öneri)
   - b. Aynı, ama yeni arama bulursa kaynak geri gelir.
   - c. Yalnız dahil edilmemiş kaynak çıkarılabilir; dahil olan önce Exclude edilir.
3. **Kalıcı silme kapsamı.**
   - a. Tablo ve şablon çöpten tek tek kalıcı silinebilir (tablo için yeni yetki tetikleyicisi); çıkarılmış kaynak yalnız araştırmayla birlikte kalıcı silinir. (öneri)
   - b. Tek nesne kalıcı silmesi yok; yalnız araştırma kalıcı silinir, gerisi çöpte bekler.
   - c. Çıkarılmış kaynak da araştırmadan tek tek kalıcı silinebilir (üyelik, aday ve seçim silinir; kanıtı olan kaynakta 409).
4. **Geri alma bildirimi kapsamı.**
   - a. Çöpe atma, kaynak çıkarma, satır ve sütun çıkarma ve yanlış PDF çekmede "Geri al"; PDF geri getirme ancak yerine başka PDF eklenmediyse. (öneri)
   - b. Aynı, PDF çekme hariç (D45 bugünkü gibi kalır).
   - c. Bildirim yok; yalnız çöp ekranı.
5. **Seçili kaynaklardan tablo: hangi kaynaklar.**
   - a. Sources sekmesinde her etkin kaynak seçilebilir; dahil olmayanlar onayda sayılır. (öneri)
   - b. Yalnız dahil edilen kaynaklar seçilebilir.
   - c. a'ya ek olarak Library'de çoklu seçim.
6. **Tabloda satırı olan kaynak araştırmadan çıkarılınca.**
   - a. Satır görünümde gizlenir, hücreleri kalır, doldurma planlamaz; kaynak geri gelince satır da döner. (öneri)
   - b. Tabloda satırı olan kaynak çıkarılamaz (409); önce tablodan çıkarılır.
7. **Kirli çalışma ağacı.** Dilim 3 `store.py`, `views.py`, `tables.py`, `app.py`, `App.tsx`, `ResearchView.tsx`, `api.ts`, `i18n.ts` dosyalarına dokunur; bunlarda D45–D49'un commit'lenmemiş değişiklikleri var.
   - a. Önce D45–D49 commit'lenir, dilim 3 kodu temiz ağaçta başlar. (öneri)
   - b. Commit beklemeden başlarım; commit'te hunk'lar el ile ayrılır.

## 9. Alt adımlar

Her alt adımda önce testler yazılır ve kırmızı görülür, sonra uygulanır; sonunda backend suite (`PYTHONPATH=backend:. uv run pytest`) çalışır. Başlamadan önce D45–D49 commit'lenir (soru 7).

1. **Migration ve üyelik ayrımı.**
   - Kırmızı: 0028'deki veritabanında 0029 (sayılar aynı, araştırma kalıcı silmesi hâlâ çalışır); çıkarılmış üyelikli kaynak `included_sources`, yanıt girdisi, PDF toplama planı, doldurma planı, `research_view` kaynak listesi ve Library proje grubunda yok; eski yanıt alıntısı ve hücre kanıtı pasajı açar; PDF yalnız kanıt bağı varsa açılır.
   - Yeşil: `0029_trash_and_corpus_removal.sql` (`removed_at`, `removal_note`, kısmi indeks, `table_purge_authorizations`, üç tetikleyicinin yeniden kurulumu); `is_active_member` / `was_member`; `corpus_memberships` ve `candidates` sorgularının tek tek sınıflanması.
2. **Kaynak çıkarma ve geri getirme (T15).**
   - Kırmızı: A'dan çıkarılan kaynak B'de etkin, asset/pasaj/dosya hash'i aynı; dahil kaynakta seçim revizyonu artar, geri getirmede yeniden artar; eser başı çıkarılınca bütün sürümler çıkar; yeni arama çıkarılmış üyeliği etkinleştirmez ve özet sayısında görünür; tabloda satır gizlenir, hücreler kalır, doldurma planlamaz, geri gelince döner; etkin run 409; üye olmayan 422; CSRF; A kalıcı silinir, B'de çıkarılmış üyelik varken dosya kalır.
   - Yeşil: `Store.remove_sources`, `Store.restore_sources`, olaylar, `DELETE /api/researches/{rid}/sources`, `POST …/sources/restore`, `purge_research` paylaşım denetimi.
3. **Tablo, şablon ve sütun çöpü.**
   - Kırmızı: çöpe at → geri getir (hücre, insan düzenlemesi, öneri aynı; sürüm artar); tablo run'ı hedefliyorsa 409; araştırma çöpteyken 404; tek tablo kalıcı silmesi yalnız o tablonun revizyonlarını siler, aynı araştırmanın öteki tablosu ve yetkisiz silme tetikleyiciyle reddedilir; pasaj, StepInput, run kalır; şablon geri getirme ve silme; sütun geri getirme hücreleriyle döner, beklenen sürüm çatışması 409.
   - Yeşil: `TableStore.restore_table`, `purge_table`, `restore_template`, `purge_template`, `restore_column`; uçlar; `GET /api/trash` gruplu yanıt ve etki sayıları.
4. **Geri alma ve PDF geri getirme.**
   - Kırmızı: yanlış çekilen PDF geri gelir (dahilse seçim revizyonu artar); yerine başka PDF eklendiyse 409 ve tek kullanılan PDF indeksi korunur; kanıt durumu (`evidence_status`) geri getirmeden sonra `current`.
   - Yeşil: `Store.restore_asset`, `POST …/assets/{aid}/restore`.
5. **Seçili kaynaklardan tablo (API tarafı).**
   - Kırmızı: `rows` yalnız etkin üyeleri kabul eder; çıkarılmış kaynak 422; dahil olmayan kaynak satır olur; idempotency tekrarı aynı tablo; `add_rows` çıkarılmış kaynağı reddeder.
   - Yeşil: `_check_members` → `is_active_member`.
6. **Yedek ve geri yükleme.**
   - Kırmızı: çöpteki tablo, çıkarılmış üyelik, çıkarılmış sütun ve çekilmiş PDF yedekten aynen döner; geri yüklenen kütüphanede geri getirme çalışır; manifest hash'leri doğru.
   - Yeşil: gerekiyorsa `storage/backup.py`.
7. **Arayüz.**
   - Trash sayfası grupları; Evidence tablo menüsünde "Move to Trash" ve boş durum; Sources seçim kutuları, alt çubuk, çıkarma onayı ve özet sayısı; `Toast` eylem düğmesi; alıntı, hücre paneli ve `PassageSheet`'te "Bu araştırmadan çıkarıldı" etiketi; `api.ts`, `i18n.ts` (TR).
   - Doğrulama: `npm run build`, `npm run lint` (yeni uyarı yok); Playwright senaryosu (§6 Web); Chrome'da masaüstü ve 390 px, açık ve koyu tema; ekran görüntüleriyle kendim denetlerim.
8. **Kapanış.** Tam backend suite, acceptance, `git diff --check`; D50'ye Evidence ve Limits, bu nota uygulama farkları. Canlı kütüphaneye yazılmaz; gerekirse kopya veri dizini ve başka portta denenir.

### Uygulama farkları (1–2. adımlar, 16 Eylül 2026)

- **Ek kolon `found_again_at`.** Özet sayısı ("n kaynak yeniden bulundu") için çıkarılmış üyeliğe sonraki aramanın bulduğu zaman yazılır; `candidates` satırında güvenilir bir "sonra bulundu" izi yoktu (aynı soru revizyonunda daha kötü sırayla bulunursa `search_run_id` değişmez). Çıkarma ve geri getirme onu temizler. `research_view.counts` iki sayı taşır: `removed` ve `removed_found_again` (ikisi de eser sayısı).
- **Çıkarılmış eserin yeni sürümü.** Arama, bu araştırmada bütün sürümleri çıkarılmış bir eserin yeni sürümünü bulursa sürüm çıkarılmış olarak eklenir ve yeniden bulunmuş sayılır; yoksa kaydı olmayan bir sürüm listede tek başına görünürdü.
- **Geri getirme grubu.** Bir sürüm, aynı işlemde (aynı `removed_at`) çıkarılan eser sürümleriyle birlikte döner; eserin başı çıkarılmışsa baş ve onun grubu da döner. Ayrı işlemle çıkarılmış bir sürüm, başı geri gelince kendiliğinden dönmez.
- **Zaten çıkarılmış ya da zaten etkin kaynak** hata değildir; uç `changed_source_version_ids` ile gerçekten değişenleri döner (yanıtın geri kalanı `research_view`). Hiç üye olmamış kaynak 422. Etkin run 409, geri getirmede de.
- **Çıkarılmış kaynağı yeniden ekleme.** Kural: kullanıcının tek bir kaynağı bilerek eklediği yol geri getirir, toplu ekleme getirmez. Aynı dosyayı yeniden yüklemek ve eseri Library'den sürüklemek `restore_sources` çağırır (aynı işlemde çıkarılan sürümler ve seçim revizyonu dahil; Library yanıtında `restored: true`; etkin run varsa 409). Arama ve Zotero koleksiyonu içe aktarma kaynağı çıkarılmış bırakır ve `removed_found_again` sayısına ekler; Zotero yanıtı her biri için bir not yazar ve PDF'ini eklemez. Gerekçe: gürültü diye çıkarılan bir kayıt, koleksiyonu yeniden içe aktarınca geri gelmemeli; `INSERT OR IGNORE` yüzünden eskiden bu yollar sessizce hiçbir şey yapmıyordu.
- **`_check_members` şimdiden `is_active_member`.** `is_member` kaldırıldığı için 5. adımın bu tek satırı burada yapıldı; `add_rows` ve `create_table(rows)` çıkarılmış kaynağı 422 ile reddeder. 5. adımın testleri (idempotency vb.) yazılmadı.
- **Tablo satırı.** Çıkarılmış kaynağın satırı ne `rows` ne `removed_rows` listesinde görünür; `tables()` satır sayısı onu saymaz; `edit_cell`, öneri kararı ve yeniden kontrol 422 verir; `cell_view` hücreyi ve kanıtını açmaya devam eder.
- **Eski migration testleri.** `test_evidence_tables` (23'te) ve `test_provider_records` (25'te) bugünkü kodla üyelik yazdığı için eski migration klasörlerine 0029 da kopyalanır.

**Sorgu sınıflaması.** *Etkin üyelik:* `included_sources`, `work_heads` (geri getirmede `include_removed`), `_settle_work_head` (başka sürümün seçimi), `work_versions`, `quick_search`, `research_view` kaynak listesi, `library_view` proje grupları, `library_work_view` araştırmaları, tablo satırları (`active_rows`, `_active_row`, `table_view`, `tables`), `_check_members`, ve API'de yükleme, PDF arama, aday PDF ekleme, PDF çekme, değiştirme, yeniden çıkarma, etki. *Herhangi bir üyelik:* `passage_view`; PDF ve düz metin açma (etkin üyelik ya da bu araştırmanın kanıtı o dosyaya bağlıysa); `purge_research` kaynak listesi ve paylaşım denetimi; `reextract_asset` ve `replace_asset` etkin run denetimi ve olayları; `asset_impact` araştırma listesi (orada da eski alıntılar dosyayı gösterir); `_join_if_same_publication`; `library_work_view` eserin varlığı; Library'den ekleme reddi. *`candidates` sorguları* (`_work_candidate`, `_flag_suspected_duplicates`, `candidates()`, `add_to_corpus`, `purge_research`) çıkarmaya bakmaz: tarama listesi etkin eser başlarıyla süzülür, aday ve sayılar geçmiş run'lar için değişmez.

### Uygulama farkları (3. adım, 16 Eylül 2026)

- **Tablo çöpe atma artık 409 verebilir.** Önceden run denetimi yoktu; şimdi bu tabloyu hedefleyen `table_fill`, `cell_recheck` ya da `table_columns` run'ı etkinse 409. Olay `table_changed` yerine `table_trashed`.
- **Tek tablo kalıcı silmesi** araştırmada herhangi bir etkin run varken 409 verir (araştırma kalıcı silmesiyle aynı kural), yalnız tablo run'ında değil. Araştırması çöpteki tablo 404: araştırmayla gider. Yanıt `{deleted, cells, human_edits}`; "insan düzenlemesi" `human_edit` ve `accept_proposal` revizyonlarıdır. Research ve tek tablo silmesi aynı `_delete_tables` işlevini kullanır.
- **Şablon kalıcı silmesi** onu kullanan tabloların `template_id` alanını boşaltır (`tables_unlinked` sayısı döner). Şablon yalnız sütun tanımı taşır ve tablo sütunları oluşturulurken kopyalanmıştır (`origin = 'template'`); başka seçenek, kullanılan şablonu hiç silinemez yapmaktı.
- **Geri getirme uçları** beklenen sürümü gövdede (`{expected_version}`) alır, hücre yeniden kontrolü ve öneri kararı gibi. Sütun geri getirme, sütun çıkarmada olduğu gibi tablo sürümünü artırmaz; sütun sürümünü artırır.
- **Çöp listesi sayıları.** Tablo satır sayısı tablodan çıkarılmamış bütün satırları sayar, kaynağı araştırmadan çıkarılmış olanlar dahil (çöp ekranı tablonun ne taşıdığını söyler). Kaynak öğesi sürüm başınadır (`work_id` ile gruplanabilir), `found_again_at` taşır.
- **`GET /api/trash` yanıtı değişti**; arayüz 7. adıma kadar yalnız `researches` okur (`api.ts`'de tek satır). Mevcut Trash sayfası acceptance'ta çalışmaya devam ediyor.
- Yeni olay adları (`table_trashed`, `table_restored`, `table_purged`, `column_restored`, `source_removed`, `source_restored`) Activity'de henüz etiketsiz, ham adıyla görünür; etiketler 7. adımda.

### Uygulama farkları (4. adım, 16 Eylül 2026)

- **Yalnız `wrong_file` geri gelir.** Değiştirilmiş (`replaced`) bir PDF bu uçla geri getirilmez (404); onu geri almak, eski dosyayla yeniden değiştirmektir. Kullanımdaki PDF'e ve başka kaynağın dosyasına da 404.
- **Beklenen sürüm yok.** Asset'in sürüm alanı olmadığı için çatışma durumdan anlaşılır: kaynakta başka PDF kullanılıyorsa 409 (`PdfInUse`), dosya zaten geri gelmişse 404.
- **Etkin run denetimi** kaynağı kullanan bütün araştırmalara bakar (`RunInProgress`, 409), değiştirme ve yeniden çıkarmadaki gibi; `remove_asset`'te bu denetim yoktu ve eklenmedi.
- **Seçim revizyonu** yalnız isteği yapan araştırmada, kaynak orada dahilse artar; `remove_asset`'in bugünkü davranışının aynısı. Aynı kaynağı dahil eden öteki araştırmalarda revizyon ne çekmede ne geri getirmede değişir (mevcut asimetri, bu adımda değiştirilmedi).
