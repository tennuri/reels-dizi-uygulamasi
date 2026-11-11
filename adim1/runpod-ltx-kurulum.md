# LTX-2.5'i RunPod'da çalıştırma rehberi

11.11.2026'dan beri projenin video modeli **LTX-2.5** (Lightricks). Ağırlıkları açık, 22B parametreli bir model. Görüntüyle birlikte sesi de üretiyor, bir klibin içinde birden fazla çekim yapabiliyor ve ComfyUI'da resmi şablonu var. Eski MiniMax H3 rehberi [runpod-h3-kurulum.md](runpod-h3-kurulum.md) dosyasında duruyor ama artık kullanılmıyor.

Model dosyalarının tam listesi, indirme adresleri ve şablonda yapılan değişiklikler: [adim3/workflows/LTX_MODELLER.txt](../adim3/workflows/LTX_MODELLER.txt).

## 1. GPU ve pod

- **A40 48 GB** yeterli. Kanada'daki (CA-MTL-1) A40 saatte yaklaşık 0,59 $. Bir klip grubu (4-10 sn, sesli, 704x1280) yaklaşık 3-4 dakikada çıkıyor. Modelin ilk yüklenmesi de bunun içinde.
- Pod'u resmi **ComfyUI** şablonuyla aç ve network volume'u `/workspace`'e bağla. Model dosyaları toplam yaklaşık 43 GB tutuyor. Volume'a koyarsan pod kapanıp açılınca tekrar inmeleri gerekmez.
- Durdurulan bir pod sadece kendi makinesinde açılabilir. O makinedeki GPU başkasına geçmişse aynı volume'a bağlı yeni bir pod açmak gerekir. Dosyalar volume'da olduğu için iş kaldığı yerden sürer.

## 2. Hugging Face izni (bir kerelik)

`Lightricks/LTX-2.5` deposu kilitli, yani token olmadan indirme reddedilir.

1. https://huggingface.co/Lightricks/LTX-2.5 sayfasında giriş yap ve lisansı kabul et.
2. https://huggingface.co/settings/tokens adresinde **Read** tipinde bir token oluştur.
3. Pod'un Web Terminal'inde token'ı dosyaya yaz. Token'ı hiçbir sohbete ya da depoya yapıştırma:

```bash
mkdir -p /workspace/.hf && echo hf_SENIN_TOKENIN > /workspace/.hf/token && chmod 600 /workspace/.hf/token
```

## 3. Model dosyalarını indir

```bash
M=/workspace/runpod-slim/ComfyUI/models     # çalışan ComfyUI hangisiyse onun models klasörü
H="Authorization: Bearer $(cat /workspace/.hf/token)"
R=https://huggingface.co/Lightricks/LTX-2.5/resolve/main
mkdir -p $M/diffusion_models $M/text_encoders $M/vae $M/latent_upscale_models
curl -fL -H "$H" -o $M/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors $R/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors
curl -fL -H "$H" -o $M/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors $R/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors
curl -fL -o $M/text_encoders/gemma4_e2b_it_int8_convrot.safetensors https://huggingface.co/Comfy-Org/gemma-4/resolve/main/text_encoders/gemma4_e2b_it_int8_convrot.safetensors
curl -fL -H "$H" -o $M/vae/ltx-2.5-video-vae-bf16.safetensors $R/vae/ltx-2.5-video-vae-bf16.safetensors
curl -fL -H "$H" -o $M/vae/ltx-2.5-audio-vae-bf16.safetensors $R/vae/ltx-2.5-audio-vae-bf16.safetensors
curl -fL -H "$H" -o $M/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors $R/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors
```

İndirme bitince ComfyUI'ı yeniden başlat. Sonra **Workflow → Browse Templates** menüsünde "LTX-2.5 Image to Video" şablonunu açıp kırmızı (eksik) düğüm kalmadığını kontrol et.

## 4. İş akışları

Üretim betiğinin kullandığı iki şablon API formatında hazır, bunları pod'da `/workspace/dizi/` altına kopyala:

| Dosya | Ne |
|---|---|
| [workflow_ltx_api.json](../adim3/workflows/workflow_ltx_api.json) | Metinden video (başlangıç karesi olmayan çekimler) |
| [workflow_ltx_ref_api.json](../adim3/workflows/workflow_ltx_ref_api.json) | Görselden video (`tutarlilik.py kare` ile kurulan başlangıç karesiyle) |

Ayarlar: 704x1280 (9:16), 24 fps, ses açık, prompt enhance kapalı. Süre saniye cinsinden yazılır, kare sayısını şablonun kendisi `süre x 24 + 1` olarak hesaplar.

## 5. İlk deneme

```bash
cd /workspace/dizi
python3 h3_toplu_uret.py --workflow workflow_ltx_api.json --ref-workflow workflow_ltx_ref_api.json \
    --bible bible.json --shots bolum1.json --out deneme --sahne --kareler kareler/bolum1 --only 1
```

Betiğin adı tarihsel olarak `h3_toplu_uret.py` kaldı, ama hem H3 hem LTX şablonlarıyla çalışıyor. Başında yazdığı `süre -> ...` ve `fps -> 24` satırları LTX şablonunun doğru tanındığını gösterir.

## 6. İlk testte görülenler (11.11.2026)

- Klip, verilen başlangıç karesinden birebir başlıyor. `--sahne` grubunun içindeki çekimler arasında gerçek kesmeler yapıyor.
- Türkçe dış ses ve diyalog net. Yabancı isimler bazen bozuluyor ("Harrington" → "Hardington").
- Sadece ilk kare sabit olduğu için klibin ilerleyen çekimlerinde yüzler karakter kartlarından uzaklaşabiliyor. Bir testte bir karakter çizgi film tarzına kaydı. Önemli bir çekim grubun ortasında kalıyorsa onu ayrı bir gruba (kendi başlangıç karesiyle) almak daha güvenli.

## 7. Lisans

LTX-2.5'in lisansını ürün yayına girmeden önce birlikte okuyacağız, özellikle ticari kullanım ve olası gelir ya da bölge sınırları açısından. Bu henüz kontrol edilmedi. Pod'lar şimdilik yine Kanada'da açılıyor.
