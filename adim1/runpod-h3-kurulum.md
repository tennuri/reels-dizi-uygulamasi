# MiniMax H3'ü RunPod'da çalıştırma rehberi

Amaç: Bilgisayarındaki ComfyUI şablonunun (`video_minimax_h3_t2v`) aynısını kiralık bir GPU üzerinde çalıştırıp ilk 9:16 sahneyi üretmek.

## 1. Hangi GPU?

RunPod'un liste fiyatları (saatlik, 23.10.2026):

| GPU | VRAM | Saatlik | Not |
|---|---|---|---|
| RTX 4090 | 24 GB | 0,89 $ | Sadece H3 için yeterli olmalı. TRIBE v2 sığmaz. |
| **L40S** | **48 GB** | **1,09 $** | **Önerim.** H3 rahat çalışır, TRIBE v2 (28-32 GB) de aynı makinede sırayla çalışabilir. |
| RTX Pro 6000 | 96 GB | 2,49 $ | Tam kalite (bf16) ve uzun klipler için. Şimdilik gereksiz. |

Toplulukta paylaşılan sonuçlar: 16 GB'lık bir kartta 5 saniyelik klip 2-7 dakika sürüyor. 48 GB'lık bir kartta bunun altına inmesini bekliyorum, ama bu henüz ölçülmedi.

**Kaba maliyet tahmini:** 5 bölüm × 60 saniye = yaklaşık 60 tane 5 saniyelik klip. Klip başına 5 dakika sayarsak yaklaşık 5 saat sürer, L40S'te bu da yaklaşık 5,5 $ eder. Tekrar çekimlerle 15-20 $ civarı olur. Bu bir tahmin, ilk denemede gerçek süreyi ölçeceğiz.

## 2. Lisans için lokasyon seçimi (önemli)

H3 lisansı ABD, AB, İngiltere ve Güney Kore'deki kullanım için MiniMax'tan ayrı izin istiyor. Pod'u oluştururken **bu ülkelerin dışında bir veri merkezi** seç (örneğin Kanada). Lisans metnini ürün yayına girmeden önce mutlaka birlikte okuyacağız.

## 3. Pod'u oluşturma

1. runpod.io'da hesap aç ve bakiye yükle (başlangıç için 10-20 $ yeterli).
2. **Storage → Network Volume** ile 100 GB'lık bir disk oluştur (yaklaşık 7 $/ay). Lokasyonu 2. maddeye göre seç. Model dosyaları burada kalacağı için pod'u kapatınca tekrar indirmek gerekmez.
3. **Pods → Deploy**: GPU olarak L40S'i, şablon olarak resmi **ComfyUI** şablonunu seç ve bu network volume'u bağla.
4. Pod açılınca **Connect** menüsünden önce **Web Terminal**'i, sonra **ComfyUI**'ı (genelde 8188 portu) aç.

## 4. Model dosyalarını indirme

Sadece şablonun kullandığı dosyaları indiriyoruz, 600 GB'lık reponun tamamını değil. Web Terminal'e şunları yapıştır:

```bash
pip install -U "huggingface_hub[cli]"
hf auth login        # Hugging Face token'ını yapıştır (huggingface.co/settings/tokens)

# ComfyUI klasörünü bul
COMFY=$(dirname "$(find /workspace / -maxdepth 4 -type d -name custom_nodes -path '*ComfyUI*' 2>/dev/null | head -1)")
echo "ComfyUI: $COMFY"

# Şablondaki dosyaları indir
hf download Comfy-Org/MiniMax-H3 --local-dir /workspace/h3 \
  --include "*minimax_h3_fl2va_pruned_int8_convrot*" \
            "*qwen3vl_32b_minimax_h3_nvfp4_awq*" \
            "*minimax_h3_video_vae_int8_convrot*" \
            "*minimax_h3_audio_vae_fp32*" \
            "*minimax_h3_fl2v_turbo_8step*"

# Doğru klasörlere bağla
mkdir -p $COMFY/models/{diffusion_models,text_encoders,vae,loras}
for f in $(find /workspace/h3 -name '*.safetensors'); do
  case "$f" in
    *qwen3vl*)  ln -sf "$f" $COMFY/models/text_encoders/ ;;
    *vae*)      ln -sf "$f" $COMFY/models/vae/ ;;
    *turbo*)    ln -sf "$f" $COMFY/models/loras/ ;;
    *)          ln -sf "$f" $COMFY/models/diffusion_models/ ;;
  esac
done
ls -la $COMFY/models/*/ | grep minimax
```

Sonra ComfyUI'ı güncelle: ComfyUI Manager'dan **Update ComfyUI** ve ardından **Restart**.

## 5. İlk sahne denemesi

1. ComfyUI'da **Templates** menüsünden MiniMax H3 metinden video şablonunu aç. Bu, bilgisayarında açtığın şablonun aynısı.
2. Ayarlar:
   - aspect_ratio: **9:16**
   - megapixels: **0.5** (yaklaşık 544x960)
   - duration: **5**
   - turbo_mode: **true**, turbo_steps: **8**
3. Prompt kutusundaki örneği bırak ya da kendi sahneni yaz. Format şöyle: genel stil, sahne özeti, `[0s-1.5s] Shot 1: ...` şeklinde çekim listesi ve kamera notu.
4. **Run**'a bas ve süreyi not et. Çıktı `output/video/` altına kaydedilir.

**Hata alırsan:** `int8_convrot` dosyaları yeni bir PyTorch sürümü (cu130) istiyor. Model yükleme sırasında hata çıkarsa aynı reponun `minimax_h3_fl2va_pruned_fp8_scaled` dosyasını indirip şablonda onu seç. Hata mesajını bana gönderirsen birlikte çözeriz.

## 6. İş bitince

Pod'u **Stop** et. Saatlik ücret durur, sadece disk ücreti devam eder.

## Kaynaklar

- [Comfy-Org/MiniMax-H3 dosyaları](https://huggingface.co/Comfy-Org/MiniMax-H3)
- [MiniMax H3 model kartı](https://huggingface.co/MiniMaxAI/MiniMax-H3)
- [RunPod H3 yazısı](https://www.runpod.io/blog/minimax-h3-the-open-weight-omni-modal-video-model-and-what-it-takes-to-run-it)
- [RunPod fiyatları](https://www.runpod.io/gpu-cloud/pricing)
- [Farklı VRAM'lerde H3 süreleri](https://dev.to/tf6cool/i-compared-minimax-h3-runs-from-6gb-to-20gb-vram-heres-what-i-learned-2jpj)
