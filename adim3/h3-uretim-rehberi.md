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

## 7. Mekanı birebir sabitlemek: referans kare

Metin ne kadar detaylı olursa olsun, H3 her klipte odayı yeniden çizer ve eşyalar kayabilir. Kesin çözüm, klibi her seferinde **aynı başlangıç karesinden** başlatmak. Şablondaki `MiniMaxH3ImageToVideo` düğümü ve `fl2va` model dosyası başlangıç karesi alabildiğini gösteriyor, ama senin şablonunda şu an bağlı değil.

**a) Referans kareleri hazırla.** Odanın doğru çıktığı bir klipten bir kare al:

```bash
mkdir -p /workspace/dizi/refs
ffmpeg -ss 1 -i $COMFY/output/bolum1/shot_01_00001_.mp4 -frames:v 1 /workspace/dizi/refs/salon_genis.png
```

Her mekan için farklı kamera açılarına 2–3 kare yeterli (ör. geniş plan, kapıya bakan açı, ters açı). Klip bu karenin aynısıyla başlayacağı için karede kimin durduğu önemli. Ya boş oda karesi kullan ya da o çekimdeki karakterlerin olduğu bir kare.

**b) bible.json'a ekle.** Mekana `refs` alanını ekle (yollar bible.json'un bulunduğu klasöre göre):

```json
{"id": "L1", "name": "Salon", "visual": "...", "layout": "...",
 "refs": {"default": "refs/salon_genis.png", "kapi": "refs/salon_kapi.png"}}
```

Çekim listesinde (`bolum1.json`) farklı bir kare isteyen çekime `"ref": "kapi"` yaz. `ref` yazmayan çekimler `default` karesini kullanır.

**c) Referanslı ikinci şablonu hazırla.** ComfyUI'da şablona bir **Load Image** düğümü ekle, çıkışını `MiniMaxH3ImageToVideo` düğümünün görüntü (başlangıç karesi) girişine bağla. Bir kez Run'a basıp çalıştığını gör, sonra **Export (API)** ile `workflow_ref_api.json` adıyla ayrı kaydet. Eski `workflow_api.json`'u silme, referansı olmayan çekimler onu kullanır.

**d) Çalıştır:**

```bash
python3 h3_toplu_uret.py --workflow workflow_api.json --ref-workflow workflow_ref_api.json \
  --bible bible.json --shots bolum1.json --out bolum1
```

Betik başta `ref kare -> [('…', 'image')]` yazmalı. Kareyi ComfyUI'a kendisi yükler. `--sahne` ile birlikte kullanırsan her grup ilk çekiminin karesiyle başlar.

---

## 8. Karakter ve mekanı bütün dizi boyunca sabitlemek

Metin tarifi ne kadar ayrıntılı olursa olsun, H3 her klipte yüzü ve odayı yeniden çizer. Bu yüzden Derin 1. bölümde başka, 5. bölümde başka çıkıyor. Çözüm, her karakterin ve her mekanın **bir kez onaylanmış görselini** tutmak ve her çekimin ilk karesini bu görsellerden kurmak. H3 klibi o kareden başlattığı için yüz, kıyafet ve eşyalar hep aynı kaynaktan gelir.

Akış şöyle:

1. **Karakter kartı:** Her karakter için bir kez, düz gri fonda önden, yarı yandan ve profilden tam boy görsel üretilir. Beğendiğini seçersin, bu kart bütün dizi boyunca o karakterin kimliği olur.
2. **Mekan karesi:** Her mekan için bir kez, boş oda görseli üretilir (eşya yerleşimi bible'daki `layout`'tan). Farklı kamera açıları bu kareden türetilir, böylece eşyalar açıdan açıya da değişmez.
3. **Çekim karesi:** Her çekim için mekan karesi + o çekimdeki karakterlerin kartları bir görüntü düzenleme modeline (Qwen-Image-Edit) verilir, model karakterleri odaya yerleştirip çekimin ilk karesini kurar.
4. **H3:** 7. maddedeki referanslı şablon bu kareyle başlar.

Hepsini [tutarlilik.py](tutarlilik.py) yapar.

### a) Bir kerelik: iki görsel şablonu

**Kolay yol:** ComfyUI açıkken `python3 qwen_kurulum.py` çalıştır. Modelleri (~45 GB) indirir ve iki şablonu (`workflow_qwen_t2i_api.json`, `workflow_qwen_edit_api.json`) kendisi yazar. Aşağıdaki elle yolu atlayabilirsin.

**Elle yol:** ComfyUI'da **Workflow → Browse Templates** içinden:

- **Qwen-Image** (metinden görsel) şablonunu aç, eksik modelleri şablonun gösterdiği linklerden indir, bir kez Run'a bas. Sonra **Export (API)** ile `workflow_qwen_t2i_api.json` olarak kaydet.
- **Qwen-Image-Edit 2509** (ya da listede varsa daha yeni sürümü) şablonunu aç. Bu şablonda **3 tane Load Image** olmalı ve üçü de `TextEncodeQwenImageEditPlus` düğümünün `image1`, `image2`, `image3` girişlerine bağlı olmalı. Bağlı değilse (mor/soluk görünüyorsa) bypass'ı kaldırıp bağla. Bir kez Run'a bas, **Export (API)** ile `workflow_qwen_edit_api.json` olarak kaydet.

Varsa 4 ya da 8 adımlık "Lightning" LoRA'lı sürümü seç, görsel başına birkaç saniyeye iner. Modeller toplam 40 GB civarı, 200 GB'lık disk yeter. Pod kalıcı volume'suz olduğu için pod silinirse yeniden inmeleri gerekir.

Betik başta bulduklarını yazar. Edit şablonu için şuna benzer bir satır görmelisin:

```
görsel -> ['78', '106', '108'] (sırasıyla image1, image2, ...)
```

### b) Karakter kartları

```bash
cd /workspace/dizi
python3 tutarlilik.py durum --bible bible.json
python3 tutarlilik.py karakter --bible bible.json --t2i workflow_qwen_t2i_api.json --kim C1 C2 --aday 4
```

Adaylar `refs/adaylar/C1_1.png ... C1_4.png` olarak çıkar. JupyterLab'de bak, en iyisini seç:

```bash
python3 tutarlilik.py sec --bible bible.json C1 3
```

Bu, `refs/karakter/C1.png`'yi oluşturur ve bible.json'a `"sheet": "refs/karakter/C1.png"` yazar (eski hali `bible.json.yedek`). Hiçbiri olmadıysa `--seed 500` ile yeni adaylar üret ya da önce bible'daki `visual` tarifini düzelt. `--kim` vermezsen bütün karakterleri üretir.

### c) Mekan kareleri

```bash
python3 tutarlilik.py mekan --bible bible.json --t2i workflow_qwen_t2i_api.json --kim L1 L7 --aday 4
python3 tutarlilik.py sec --bible bible.json L1 2
```

Eşyaların yeri bible'daki `layout` ile uyuşmuyorsa ya başka bir aday seç ya da `layout`'u düzelt. Elinde 7. maddeden kalan, odanın doğru çıktığı bir kare varsa onu da doğrudan `refs/mekan/L1_default.png` olarak koyup bible'a yazabilirsin.

Ters açı gibi başka açılar varsayılan kareden türetilir (aynı eşyalar, kamera döner):

```bash
python3 tutarlilik.py mekan --bible bible.json --edit workflow_qwen_edit_api.json --kim L1 \
  --aci ters --tarif "reverse angle from the window side, looking toward the entrance door at the back right" --aday 3
python3 tutarlilik.py sec --bible bible.json L1 1 --aci ters
```

Çekim listesinde bu açıyı isteyen çekime `"ref": "ters"` yaz.

### d) Bölümün çekim kareleri

```bash
python3 tutarlilik.py kare --bible bible.json --edit workflow_qwen_edit_api.json \
  --shots bolum1.json --out bolum1
```

Kareler `kareler/bolum1/shot_01.png ...` olarak çıkar. Karakteri olmayan çekimlerde mekan karesi aynen kullanılır. Üçten fazla kişili çekimlerde fazla kartlar yan yana tek görselde birleştirilir. Önce `--dry-run` ile promptlara bakabilirsin.

Kötü çıkan kareyi silmeden yeniden üretmek için: `--only 4 7 --yeniden --seed 300`. **Kareleri H3'e geçmeden önce kontrol et**: bir kare iki dakikada düzelir, bir H3 klibi çok daha pahalı.

`--sahne` ile üreteceksen burada da `--sahne` ekle. O zaman her grup için bir kare kurulur ve içine grubun bütün karakterleri konur.

### e) H3 ile üret

```bash
python3 h3_toplu_uret.py --workflow workflow_api.json --ref-workflow workflow_ref_api.json \
  --bible bible.json --shots bolum1.json --out bolum1 --kareler kareler/bolum1
```

Betik başta `kareler -> 12/12 üretim için hazır başlangıç karesi` yazar. Karesi olmayan çekim mekan karesine, o da yoksa karesiz üretime düşer.

Önce bütün bölümün karelerini, sonra bütün klipleri üret. İki model 48 GB'a birlikte sığmayabilir, ComfyUI aralarında geçerken birini bellekten atar ve bu her çekimde tekrarlanırsa çok zaman kaybettirir.

### Bilmen gerekenler

- **`refs/` klasörü ve `bible.json` dizinin kimliği.** Pod silinirse gider. Her seçimden sonra bilgisayarına indir, yeni pod'da `/workspace/dizi`'ye geri koy.
- **Seed karakteri sabitlemez.** Aynı seed farklı promptla farklı yüz verir. Sabitleyen şey kart görseli. Seed sadece aynı karenin tekrar aynı çıkmasını sağlar.
- **Kıyafet değişirse** (düğün, hastane) o karakter için ikinci bir kart üret, ör. bible'a `"id": "C1-dugun"` adında ayrı bir karakter olarak ekle, aynı `visual`'i kıyafet kısmını değiştirip kullan.
- **Klip içinde yüz yine kayarsa** sonraki adım ana karakterler (Derin, Barış) için LoRA eğitmek: onayladığın 20–30 kareden Qwen-Image LoRA'sı, A40'ta birkaç saat. Önce bu sistemle bir bölüm üretip sonucu görelim.

---

## Bilmen gerekenler

- **Süre sınırı:** Betik her çekimin süresini 4–15 saniye arasına sıkıştırır (H3'ün klip aralığı). Şablondaki süre ayarı serbest sayı değil de bir liste ise (ör. sadece 5 ve 10) üretim hata verebilir. Öyle olursa haber ver.
- **Tutarlılık:** Her klip ayrı üretildiği için yüzler değişebilir. Asıl çözüm 8. madde (karakter kartı + çekim karesi). Ek olarak: tarifleri daha ayırt edici yapmak, ya da aynı sahnedeki 2–3 kısa çekimi senin ilk denemendeki gibi `[0s-3s] Shot 1: ... [3s-6s] Shot 2: ...` formatında tek üretimde birleştirmek. İlk denemendeki prompt da bir klibin içinde birden fazla çekim istiyordu.
- **Mekan her klipte değişiyorsa:** `--sahne` ekle. Betik aynı sahnedeki art arda çekimleri (toplam 15 saniyeyi geçmeyecek şekilde) tek bir H3 üretiminde `[0s-5s] Shot 1: ... [5s-11s] Shot 2: ...` formatıyla birleştirir. H3 tek klibin içinde aynı odayı korur. Ayrıca `bible.json`'daki mekan tarifine eşyaların yerini yaz (ör. "dining table against the left wall under the window, red sofa on the right wall, glass china cabinet in the back left corner").
- **Ses:** Türkçe diyaloğun nasıl çıktığına dikkat et. Kötüyse `bolum1.json`'daki `dialogue` satırlarını boşaltıp sesi sonradan ekleriz.
- **Maliyet:** Log'daki "bitti, X sn" sürelerine bak. Klip başına süreyi bilirsek bütün dizinin maliyetini hesaplayabiliriz.
- İş bitince pod'u **Stop** et.
