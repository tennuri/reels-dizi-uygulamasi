# Adım 4: Diziden senaryo ve çekim dili çıkarma

Hazır bir dizi bölümünü izletip her çekimin plan boyunu, açısını, kamera hareketini, aksiyonunu ve diyaloğunu çıkarır. Çıktı [adim2](../adim2/senaryo-sablonlari.md) Adım 3'teki shot list formatında ve `bible.json` biçiminde olur.

> **Telif:** Bu çıktıyı yapıyı, tempoyu ve çekim dilini öğrenmek için kullan (ortalama çekim süresi, hangi anda yakın plana geçiliyor, diyalog sahnesi nasıl kesiliyor gibi). Başka bir dizinin sahnelerini, karakterlerini veya diyaloglarını kendi dizine taşıma.

Neden bu yolu seçtiğimiz: [secenekler.md](secenekler.md)

## Zincir

| Adım | Araç | Çıktı |
|---|---|---|
| `kes` | ffmpeg + PySceneDetect | `ses.wav`, `cekimler.json`, `kareler/0001_1.jpg` ... |
| `ses` | WhisperX large-v3 + pyannote | `diyalog.json` (zaman, konuşmacı, metin) |
| `analiz` | Qwen3-VL (vLLM sunucusu) | `cekim_analizi.jsonl` (her çekim için bir satır) |
| `birlestir` | betik | `cekim_listesi.json`, `ozet.json` |
| `bible` | metin LLM'i (varsayılan: aynı Qwen3-VL) | `sahneler.json`, `bible_taslak.json` |

Her adım kaldığı yerden devam eder. `analiz` yarıda kesilirse tekrar çalıştır, bitmiş çekimleri atlar.

## Kurulum (RunPod, A40 48 GB)

ComfyUI ile aynı pod'u kullanacaksan önce ComfyUI'yi durdur, ikisi aynı anda GPU'ya sığmaz.

```bash
cd /workspace
git clone https://github.com/tennuri/reels-dizi-uygulamasi.git
cd reels-dizi-uygulamasi/adim4
bash kurulum.sh          # 10-15 dk
export HF_TOKEN=hf_...   # https://huggingface.co/settings/tokens
```

Konuşmacı ayrımı için Hugging Face'te şu iki sayfada "Agree" butonuna bir kere bas (aynı hesapla):
- https://huggingface.co/pyannote/speaker-diarization-3.1
- https://huggingface.co/pyannote/segmentation-3.0

WhisperX'in yeni sürümü farklı bir pyannote modeli isterse hata mesajında linki verir, onu da onayla.

## Çalıştırma

**1. Videoyu pod'a koy** (RunPod'un Jupyter arayüzünden sürükle bırak veya `wget`), örneğin `/workspace/videolar/bolum1.mp4`.

**2. Kes ve sesi çöz** (vLLM'den önce, GPU boşken):

```bash
python3 diziden_senaryo.py /workspace/videolar/bolum1.mp4 --cikti /workspace/analiz/bolum1 --adim kes,ses
```

**3. Qwen3-VL sunucusunu başlat** (ayrı terminal, ilk seferde model iner):

```bash
/workspace/venv-vlm/bin/vllm serve Qwen/Qwen3-VL-8B-Instruct \
  --max-model-len 32768 --gpu-memory-utilization 0.85 \
  --limit-mm-per-prompt '{"image": 8}'
```

"Application startup complete" yazınca hazırdır.

**4. Önce 5 çekimle dene**, sonuçlara bak:

```bash
python3 diziden_senaryo.py /workspace/videolar/bolum1.mp4 --cikti /workspace/analiz/bolum1 --adim analiz --sinir 5
cat /workspace/analiz/bolum1/cekim_analizi.jsonl
```

**5. Beğendiysen tamamını çalıştır ve birleştir:**

```bash
python3 diziden_senaryo.py /workspace/videolar/bolum1.mp4 --cikti /workspace/analiz/bolum1 --adim analiz,birlestir,bible
```

## Konuşmacılara isim vermek

pyannote konuşmacıları `SPEAKER_00`, `SPEAKER_01` diye ayırır, isim bilmez. `cekim_listesi.json` içinde birkaç replik okuyup kimin kim olduğunu bul, çıktı klasörüne `konusmaci.json` yaz:

```json
{"SPEAKER_00": "Kadın başrol", "SPEAKER_01": "Baba"}
```

Sonra `--adim birlestir,bible` ile tekrar çalıştır (dosyayı otomatik bulur). Bunu yapmadan önce `sahneler.json` ve `bible_taslak.json` varsa sil, yoksa eski isimlerle kalır.

## Daha iyi sonuç için

- **Daha büyük model:** `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8` (yaklaşık 32 GB, A40'a sığar). Kamera hareketinde ve ayrıntıda daha iyi, yaklaşık 2 kat yavaş. Sunucuyu bu adla başlat ve betiğe `--vlm-model Qwen/Qwen3-VL-30B-A3B-Instruct-FP8` ver.
- **Çok fazla / az kesme:** `--esik` değerini düşür (daha çok kesme) ya da yükselt (daha az). Varsayılan 27.
- **Hareket kaçıyorsa:** `--kare-sayisi 6` ile çekim başına daha çok kare gönder.
- **Bible adımı için başka model:** OpenAI uyumlu herhangi bir uç nokta olur: `--llm-url ... --llm-model ...`, anahtar `LLM_API_KEY` ortam değişkeninden okunur.

## Çıktılar

- `cekim_listesi.json`: adim2 shot list alanları (`size`, `angle`, `movement`, `action`, `lighting`, `dialogue`) + gerçek zamanlar (`start_s`, `end_s`) + `composition`.
- `ozet.json`: çekim sayısı, ortalama/medyan çekim süresi, plan boyu/açı/hareket dağılımı. Kendi bölümlerinin temposunu ayarlarken en çok bu işine yarar.
- `bible_taslak.json`: `title`, `style`, `characters`, `locations`, `beats`. Kendi `bible.json`'ın için doğrudan kullanma, yapı örneği olarak oku.

## Süre (tahmin, gerçek bir bölümde henüz denenmedi)

45 dakikalık bölüm, 600-800 çekim, Qwen3-VL-8B ile: kesme 2-3 dk, ses 3-5 dk, analiz 20-40 dk. A40 saati 0,62 $ olduğundan bölüm başı yaklaşık 0,30-0,60 $.

## Test durumu

Betiğin `kes`, `analiz`, `birlestir`, `bible` adımları sentetik bir videoda ve sahte bir model sunucusuyla uçtan uca denendi. Gerçek Qwen3-VL, WhisperX ve pyannote ile henüz çalıştırılmadı. İlk gerçek denemede hata çıkarsa çıktıyı bana gönder.
