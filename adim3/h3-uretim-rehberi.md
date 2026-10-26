# Çekim listesinden H3 videosuna

Elinde 4 adımın çıktıları var. Bu rehber onları RunPod'daki ComfyUI'da kliplere çevirip tek bir bölüm videosu yapmayı anlatıyor. İki dosya kullanacağız:

- [h3_toplu_uret.py](h3_toplu_uret.py): Bir bölümün bütün çekimlerini sırayla H3'e gönderir. Adım 4'teki prompt fonksiyonu da içinde.
- [birlestir.sh](birlestir.sh): Çıkan klipleri sırayla tek bir mp4'e birleştirir.

Mantık şu: **her çekim = bir H3 üretimi = bir klip.** Böylece kötü çıkan tek bir çekimi diğerlerine dokunmadan yeniden üretebilirsin.

---

## 1. Dosyaları pod'a koy

Pod'da `/workspace/dizi` diye bir klasör aç ve şu 5 dosyayı oraya koy:

| Dosya | Ne |
|---|---|
| `bible.json` | Adım 1 çıktısı |
| `bolum1.json` | Adım 3 çıktısı (1. bölümün çekim listesi, içinde `"shots": [...]` olan) |
| `workflow_api.json` | 2. maddede ComfyUI'dan alacağın dosya |
| `h3_toplu_uret.py`, `birlestir.sh` | Bu klasördeki betikler |

Pod'da JupyterLab açıksa (Connect menüsünde 8888 portu) dosyaları sürükleyip bırakabilirsin. Yoksa Web Terminal'de `nano /workspace/dizi/bible.json` yazıp içeriği yapıştır, Ctrl+O ve Enter ile kaydet, Ctrl+X ile çık.

JSON'ların geçerli olup olmadığını kontrol et:

```bash
cd /workspace/dizi
python3 -m json.tool bible.json > /dev/null && echo bible tamam
python3 -m json.tool bolum1.json > /dev/null && echo bolum1 tamam
```

## 2. Şablonu API formatında dışa aktar

1. ComfyUI'da ilk klibi ürettiğin H3 şablonunu aç.
2. Sabit kalacak ayarları yap: **aspect_ratio 9:16, megapixels 0.5, turbo_mode true, turbo_steps 8.**
3. Üst menüden **Workflow → Export (API)** seç ve dosyayı `workflow_api.json` adıyla kaydet. (Normal "Export" değil, "API" olanı.)
4. Bu dosyayı `/workspace/dizi` içine koy.

## 3. Önce tek çekimle dene

Toplu üretime geçmeden bir çekimin nasıl çıktığını gör:

```bash
python3 h3_toplu_uret.py --workflow workflow_api.json --bible bible.json \
  --shots bolum1.json --out bolum1 --only 1
```

Betik başta neleri bulduğunu yazar:

```
prompt   -> node 12 (...)
süre     -> [('15', 'duration')]
seed     -> [('20', 'seed')]
kayıt    -> [('30', 'filename_prefix')]
```

Bunlardan biri **BULUNAMADI** derse bu satırları bana gönder, betiği şablona göre ayarlarım. Prompt yanlış kutuya yazılıyorsa doğru kutuyu `--prompt-node 12:text` gibi elle verebilirsin. Sadece promptları görmek istersen `--dry-run` ekle, hiçbir şey üretmeden ekrana yazar.

Klip ComfyUI'ın `output/bolum1/` klasörüne `shot_01_00001_.mp4` adıyla kaydedilir. Karakter, açı ve ses beklediğin gibiyse devam et.

## 4. Bütün bölümü üret

```bash
cd /workspace/dizi
nohup python3 h3_toplu_uret.py --workflow workflow_api.json --bible bible.json \
  --shots bolum1.json --out bolum1 > bolum1_log.txt 2>&1 &
tail -f bolum1_log.txt
```

`nohup` sayesinde tarayıcıyı kapatsan da üretim devam eder. `tail -f`'ten Ctrl+C ile çıkabilirsin, üretim durmaz. Kullanılan bütün promptlar `bolum1_promptlar.txt` dosyasına da yazılır.

## 5. Kötü çıkan çekimleri yeniden üret

Klipleri ComfyUI'ın çıktı panelinden ya da JupyterLab'den izle. Örneğin 3. ve 9. çekim kötüyse önce eski dosyalarını sil, sonra farklı bir seed ile yeniden üret:

```bash
COMFY=$(dirname "$(find /workspace / -maxdepth 4 -type d -name custom_nodes -path '*ComfyUI*' 2>/dev/null | head -1)")
rm $COMFY/output/bolum1/shot_03_* $COMFY/output/bolum1/shot_09_*
python3 h3_toplu_uret.py --workflow workflow_api.json --bible bible.json \
  --shots bolum1.json --out bolum1 --only 3 9 --seed 1000
```

Sorun prompttaysa (yanlış aksiyon, yanlış açı) `bolum1.json`'da o çekimi düzelt ve aynı komutu çalıştır. Bir karakterin görünüşü sorunluysa `bible.json`'daki tarifi düzelt, değişiklik bütün çekimlere yansır.

## 6. Klipleri birleştir

```bash
which ffmpeg || (apt-get update && apt-get install -y ffmpeg)
bash birlestir.sh $COMFY/output/bolum1 /workspace/dizi/bolum1.mp4
```

Çıkan `bolum1.mp4`'ü JupyterLab'den indir. Bu, uygulamaya yükleyeceğin ilk bölüm.

---

## Bilmen gerekenler

- **Süre sınırı:** Betik her çekimin süresini 4–15 saniye arasına sıkıştırır (H3'ün klip aralığı). Şablondaki süre ayarı serbest sayı değil de bir liste ise (ör. sadece 5 ve 10) üretim hata verebilir. Öyle olursa haber ver.
- **Tutarlılık:** Her klip ayrı üretildiği için yüzler yine de biraz değişebilir. Bunu ilk bölümde göreceğiz. Çözüm yolları: tarifleri daha ayırt edici yapmak, ya da aynı sahnedeki 2–3 kısa çekimi senin ilk denemendeki gibi `[0s-3s] Shot 1: ... [3s-6s] Shot 2: ...` formatında tek üretimde birleştirmek. İlk denemendeki prompt da bir klibin içinde birden fazla çekim istiyordu.
- **Mekan her klipte değişiyorsa:** `--sahne` ekle. Betik aynı sahnedeki art arda çekimleri (toplam 15 saniyeyi geçmeyecek şekilde) tek bir H3 üretiminde `[0s-5s] Shot 1: ... [5s-11s] Shot 2: ...` formatıyla birleştirir. H3 tek klibin içinde aynı odayı korur. Ayrıca `bible.json`'daki mekan tarifine eşyaların yerini yaz (ör. "dining table against the left wall under the window, red sofa on the right wall, glass china cabinet in the back left corner").
- **Ses:** Türkçe diyaloğun nasıl çıktığına dikkat et. Kötüyse `bolum1.json`'daki `dialogue` satırlarını boşaltıp sesi sonradan ekleriz.
- **Maliyet:** Log'daki "bitti, X sn" sürelerine bak. Klip başına süreyi bilirsek bütün dizinin maliyetini hesaplayabiliriz.
- İş bitince pod'u **Stop** et.
