# P6 dilim 0 — doldurma süresi beklentisi (koşudan önce dondu)

D55'te aynı araştırmanın (50 dahil kaynak, `MAX_FILL_SOURCES = 25` yüzünden iki ayrı doldurma çalışması) sıralı
doldurması 506–576 saniye sürdü (~10–23 s/kaynak, sütun sayısına ve pasaj uzunluğuna göre değişerek).

Bu ölçüm aynı araştırmayı, aynı kütüphane kopyasını, `gpt-5.6-luna`'yı ve `DEIXIS_MODEL_CONCURRENCY=6`'yı kullanır.

- **Beklenen kazanç aralığı:** 25 kaynaklık bir doldurma çalışması için 100–260 saniye (kabaca D55'in 4–5'te
  biri ile 2'de biri arası; model çağrısı gecikmesi baskınsa ve sınır fiilen 6'da kalıyorsa daha kısa uca,
  şema onarımı/kota düşmesi sıksa daha uzun uca yaklaşır).
- **"Kazanç yok" eşiği:** toplam süre D55 sıralı ortalamasının (yaklaşık 540 s / 2 = 270 s tek doldurma başına)
  %80'inden daha az düşüyorsa (yani 216 s'nin altına inmiyorsa), darboğaz model-çağrısı kuyruklanması değildir;
  muhtemel adaylar: `_read_equations` (Marker/OCR, bu dilimde eş zamanlı değil ve `_table_fill`'den önce
  tamamlanır), PDF indirme/erişim gecikmesi, ya da hız sınırının pratikte 1'e düşüp kalması.
- **Ne ölçülmüyor:** hücre değerlerinin doğruluğu; bu yalnız yürütme süresidir (R7).

Ham sonuçlar `.local/p6-slice0-fill/` altına gider (repo'ya girmez); bu dosya sonuca göre yeniden yazılmaz.
