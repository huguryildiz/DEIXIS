# SW dilim 30 — Son tıp ölçümü, sonuç

**Tarih:** 29–30 Eylül 2026. **Plan:** [sw-slice30-medicine-final.md](sw-slice30-medicine-final.md), commit `a04eaa0`
(plandaki "Frozen expectations" o commit'le dondu). **Prompt:** sw-slice30-resume-prompt.md
(sürdürme). **Sınanan kod:** `a04eaa0` (D109 ve SW19/SW20 dahil), `skill_package_hash`
`sha256:1122205caf88fe87b4baad10dc529df93e391150b9b6ea0502e018a380baa2d8`. **Kuantum yarısı:** dilim 24'ün klasöründen,
`65a7ec8`. **Karar:** D114. **Klasör:** `.local/archive/sw/sw-slice30-medicine-final-2026-09-28/` (`protocol.md`, `ledger.jsonl`,
`runs.json`, `gates.json`, `gate2-one-unit.json`, `analyst-reading.jsonl`, `analyst/`). **Makine ve model:** bir M1 Pro,
Python 3.12 arm64; her araştırmanın her rolünde Codex `gpt-5.6-luna` · medium. Her sayı tek koşudur.

## Kısa özet

Yedi tıp araştırmasının yedisi de koştu. Dört kapıdan yalnız 3. kapı (kanıt bütünlüğü) geçti. Bu hüküm, sahibin anahtarsız dört araştırmanın
beş geçersiz klasöründeki 145 oturumu 1.000'lik sınırdan çıkarma kararına dayanır; o oturumlar sayılsaydı toplam 1.043 olurdu
ve plan hüküm vermezdi (sapma 4). Kapı 1 geçmedi: ikinci `sw`
`standard` koşusunun yanıtı, bir atıf çapası pasajında bulunamadığı için `unverified_draft` olarak kaldı. Kapı 2 ve kapı
4 tıpta okunamadı, bu da plana göre geçmemek demek. **Varsayılan bu izde kalıcı olarak `legacy` kalır; 24b yapılmadan
kapanır ve SW izi biter (D114).**

Kapı 2 okunabilseydi de aritmetiği tutmuyordu: `sw` iki `standard` koşusunda R'den 2 ve 0 denemeye atıf verdi (ortalama
1,0), `legacy` 4 ve 5 (ortalama 4,5). Havuz yarısı geçiyordu (12,0 ve 9,5). Kayıp, dilim 27'deki gibi atıf tarafında.
Kapı 4'te iki `sw` `standard` koşusunun birleşiminde yalnız 6 tekil `include` var, eşik 8. Okunan 6 `include` ve 8 `sw`
iddiasının hiçbirinde ciddi hata çıkmadı (iki model okuyucu da). D109'un karşılaştırıcı düzeltmesi, dilim 27'deki üç
karşılaştırıcı hatasını örneklemden çıkarmış görünüyor. Ama `include` sayısını da eşiğin altına düşürdü.

Kapıların tıp hükmü, dilim 27'deki gibi sonradan seçilmiş bir referans kuralına dayanıyor (BMI vücut ağırlığı sayılır,
Cienfuegos 2020 iki birim). Bu yüzden betimleyicidir. Her hüküm iki commit'i birleştirir: kuantum `65a7ec8`, tıp
`a04eaa0`.

## Kapılar

`gates25.py`'nin çıktısı (`gates.json`), `check_reading30.py` boşluk bulmadıktan sonra (24 birim çekildi, 24 okundu, 5
ikinci okuma, sorun yok).

| Kapı | Kuantum (24a, `65a7ec8`) | Tıp (bu koşu, `a04eaa0`) | Hüküm |
| --- | --- | --- | --- |
| 1 tamamlanma | 5/5 | 4/5: `qtre-sw-standard-r2` yanıtı `unverified_draft` | **geçmedi** (9/10) |
| 2 iş akışı karşılaştırması | geçti | okunamadı: dört `standard` koşusunun biri yanıtsız | **geçmedi** |
| 3 kanıt bütünlüğü | geçti | sorun yok (geçerli yanıtlarda 0 kötü bağ, 0 yalıtım ihlali, başka modelin çıktısı yok) | **geçti** |
| 4 analist okuması | 0/10, 0/10 | okunamadı: 6 tekil `include` (en az 8 gerekir), 8 `sw` iddiası | **geçmedi** |

Kuantum bu commit'te yeniden koşmadı. Bilinenler planın 4. değişikliğinde (D109'un işareti 625 kuantum okuma
StepInput'unun 625'ini bayt bayt değiştirmedi, koruması 304 kararın 0'ını değiştirdi). Tam bir kuantum araştırması bu
commit'te ölçülmedi.

### Kapı 1: ikinci `sw` `standard` koşusunun yanıtı

`qtre-sw-standard-r2` baştan sona koştu (keşif, getirme, okuma, yanıt; 125 model oturumu, 20,8 dk) ve yanıt adımı
başarıyla bitti. Kaydedilen yanıtın durumu `unverified_draft`: doğrulama `anchor_not_in_passage` verdi
(`c3:psg_gDxyrrsw03h19PVYTUnF`: alıntılanan cümle atıf verilen pasajda bulunamadı, `/citation_anchors/4/quote`) ve sınırlı
onarım bunu düzeltemedi. Ürün burada doğru davrandı (doğrulanmamış taslağı geçerli saymadı); kapı 1 ise yalnız geçerli
yanıtı ya da `no_includable_source` gerekçeli `no_evidence` yanıtını tamamlanmış sayar. Dilim 24a ve 27'de hiçbir `sw` yanıtı
bu yüzden geçersiz kalmamıştı. Bir koşuda görüldü; sıklığı ölçülmedi.

### Kapı 2, iki okuma yan yana (betimleyici)

`gates25.py` kapıyı okumadı, çünkü dört `standard` koşusundan biri yanıtsız. Aritmetik `gate2_oneunit.py`'den
(`gate2-one-unit.json`):

| Koşu | Havuz (R'den, iki birim / tek birim) | Atıf (R'den) |
| --- | --- | --- |
| `sw` r1 | 12 / 11 | 2 |
| `sw` r2 | 12 / 11 | 0 (yanıt `unverified_draft`) |
| `legacy` r1 | 10 / 10 | 4 |
| `legacy` r2 | 9 / 9 | 5 |

İki birim (|R| = 12): havuz ortalaması `sw` 12,0, `legacy` 9,5, eşik 2 (geçer); atıf ortalaması `sw` 1,0, `legacy` 4,5
(1,0 < 3,5, geçmez). Tek birim (|R| = 11): havuz 11,0 ve 9,5, atıf 1,0 ve 4,5, aynı sonuç. Tek birim sayımında bilinmeyen
payı %26,7 olur ve kâğıt denetimi hiçbir araştırma koşmadan dururdu; bu satır yalnız aritmetiktir.

### Kapı 4

Tohum `2409261`, iki `sw` `standard` koşusunun birleşimi (`sample.py`): 6 `include` bulundu (6'sı da çekildi), 0
`criterion_not_met`, 8 `sw` iddiası, 17 `legacy` iddiasından 10'u. Birinci okuma bu oturumdu (Claude, kör değil). İkinci
okuma kör bir Claude Sonnet oturumuydu (bir alt ajan, oturum sınırının dışında): birinci okuma hiçbir birimi ciddi
bulmadığı için ikinci okuma tohumlu 5 ciddi olmayan birimi okudu ve hiçbirini ciddi bulmadı. Anlaşmazlık yok.

| | Okunan | Ciddi |
| --- | --- | --- |
| `include` | 6 | 0 |
| `sw` iddiası | 8 | 0 |
| `legacy` iddiası | 10 | 0 |

Sınırda notlar (ciddi sayılmadı): bir `include` (10.3390/nu13041155) kemik üzerine ikincil analiz; gruplar arası ağırlık
sonucunu ana yayından [27] aktarıyor, ağırlığı ise yalnız korelasyonlarda ölçüyor. İkinci okuyucu da bu parçayı "zayıf ama
açıkça karşılanmamış değil" buldu. Bir `include` (10.14814/phy2.14868) iki kolda ortak egzersiz eğitimi taşıyor; dilim 27
de aynı işi ciddi saymamıştı. Bir iddia (`sw` r1 003) makalenin özetindeki belirsiz ifadeyi aynen tekrarlıyor: −2,98 kg,
TRF grubunun kendi değişimi; kontrol +0,83 kg. Bir iddia (`sw` r1 002) gruplar arası testi çapada sözle göstermiyor.

Bu iki okuyucu da modeldir; okuma insan denetimi değildir.

## Araştırmalar

| Araştırma | Durum | Oturum | Süre (dk, oluşturma → yanıt) | Havuz (eser) | Okunan | `include` | Atıf |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `sw` `standard` r1 | yanıt geçerli | 124 | 22,3 | 4.438 | 50 | 5 | 5 |
| `legacy` `standard` r1 | yanıt geçerli (izinli bir `client_timeout` sürdürmesi) | 10 | 22,0 | 203 | — | — | 7 |
| `sw` `quick` r1 | yanıt geçerli | 92 | 11,8 | 1.518 | 39 | 4 | 4 |
| `sw` `detailed` r1 | yanıt geçerli (baştan koşu, aşağıda) | 309 | 41,1 | 7.493 | 131 | 9 | 7 |
| `sw` `standard` gömmeli r1 | yanıt geçerli | 124 | 23,0 | 6.387 | 49 | 4 | 4 |
| `sw` `standard` r2 | `unverified_draft` | 125 | 20,8 | 6.468 | 50 | 4 | 0 |
| `legacy` `standard` r2 | yanıt geçerli | 10 | 8,8 | 222 | — | — | 6 |

Sayılan toplam 898 model oturumu (yarıda bırakılan ilk `detailed` klasörünün 104 oturumu dahil). Anahtarsız geçersiz
klasörlerin 145 oturumu (`invalid-noenv-*`: 67 + 37 + 17 + 17 + 7) da sayılırsa toplam **1.043**, yani 1.000 sınırının
üstünde. Dondurulmuş plana göre bu bir sınır durmasıydı: hüküm yok, karar sahibin. Bu kayıttaki hüküm, sahibin 30 Eylül
kararına dayanıyor: o 145 oturum sınırdan çıkarıldı (sapma 4). İkinci okuma alt ajanı sınırın dışında, bir oturum. PubMed ilk araştırmadan
önce yanıt verdi (`esearch` HTTP 200, 1.982 kayıt); bu kez PubMed kesintisi yok.

## Dondurulmuş beklentiyle yan yana

Beklentiler plandaki gibi, değiştirilmedi.

| Beklenti | Gerçekleşen |
| --- | --- |
| Kapı 1 ve 3 geçer | Kapı 3 geçti; **kapı 1 geçmedi** (`sw` `standard` r2 `unverified_draft`). Beklenmiyordu. |
| Kapı 2 büyük olasılıkla atıf yarısında yine geçmez; `sw` koşu başına 0–2, `legacy` 2–4 atıf; havuz yarısı geçer | Atıf `sw` 2 ve 0 (aralıkta), `legacy` 4 ve 5 (üst sınırın bir üstü); atıf yarısı aritmetikte geçmiyor, havuz yarısı geçiyor (12,0 ve 9,5). Kapı ayrıca kapı 1'deki yanıtsız koşu yüzünden okunamadı. |
| Kapı 4: örneklenen `include`'larda 0–2 ciddi hata; `standard` koşu başına 4–9 `include`; 8'in altında tekil `include` varsa okunamaz | 0 ciddi; `include` 5 ve 4; tekil 6, **okunamadı**. Beklentiyle uyumlu. |
| 650–950 model oturumu; yaklaşık 3 saat | 898 oturum. Araştırma süreleri toplamı yaklaşık 150 dk; koşu iki güne bölündü (aşağıda). |

## Protokolden sapmalar

1. **`detailed` baştan koştu.** İlk `detailed` koşusu 29 Eylül 04:02'de Luna'nın `serverOverloaded` hatasıyla durdu ve
   dondurulmuş kural kampanyayı kesti (`b7eedc8`). Sahip sürdürmeyi seçti. Yarım klasör `-stopped1` adıyla saklandı ve
   oturumları sınırda sayıldı; `detailed` yeni boş klasörde baştan koştu (dilim 24 karar 13).
2. **Worktree ve klasör taşıma.** P6 commit'leri `main`'in kodunu planın dondurduğu yerden ilerlettiği için sürdürme
   `a04eaa0`'da ayrı bir worktree'de (`../DEIXIS-s30`) koştu. Koşu klasörü oraya taşındı, bitince geri getirildi,
   `check_copies30.py` yeniden koştu ve worktree kaldırıldı. Tek fark bilerek yazılan `runs.json`.
3. **Operatör durdurması.** Sürücü, 2 saat sınırlı bir kabuktan başlatılmıştı. Operatör onu `detailed`'ın keşfinin ilk
   dakikasında durdurdu (durdurma anında 3 oturum; sonradan anahtarsız koşuyla birlikte 37'ye çıkan `-stopped2` klasörü) ve `nohup` ile yeniden başlattı.
4. **Anahtarsız geçersiz koşular.** Worktree'ye `.env` kopyalanmadığı için dört araştırma (`detailed`, gömmeli, `sw` r2,
   `legacy` r2) 29 Eylül 23:50 ile 30 Eylül 00:29 arasında sağlayıcı anahtarları olmadan koştu. Sahibin kararıyla
   (30 Eylül) `.env` kopyalandı ve dördü yeniden koştu. Geçersiz klasörler `invalid-noenv-*` adını aldı ve sınır
   onları saymaz (o dönemin ara toplamı 475 oturumdu). **Bu sapma hükmü taşıyor:** 145 oturum sayılsaydı toplam 1.043
   olurdu; dondurulmuş sınır kuralı kampanyayı hükümsüz bırakırdı. Kapı hükümleri, sahibin bu oturumları sınırdan
   çıkarma kararına bağlıdır.
5. **Sürücünün eksik fark denetimi.** Plan, her araştırmadan önce `git diff` ile kodun değişmediğinin denetlenmesini
   istiyordu; `drive30.diff` bu denetimi içermiyor. Koşu, kodu `a04eaa0`'da sabit tutan worktree'de yapıldı.
6. **Ağ değişikliği.** Sahip 30 Eylül 00:42'de ULAKBIM VPN'ini açtı ve kalan dört araştırmanın (`detailed`, gömmeli,
   `sw` r2, `legacy` r2) bu ağda koşmasını seçti. İlk üç araştırma VPN'siz koştu. Böylece iki `sw` `standard` tekrarı ve
   iki `legacy` `standard` tekrarı farklı ağlarda ölçüldü. Geçişin sağlayıcı erişimini ve sonuçları ne kadar
   değiştirdiği ölçülmedi.

## Ölçülmedi

Bu commit'te bir kuantum araştırması; herhangi bir araştırmanın ikinci koşusu; `anchor_not_in_passage` hatasının sıklığı;
bir `include` ya da iddianın insan okuması (iki okuyucu da model); herhangi bir ürün değişikliği; varsayılan geçişi (24b).
