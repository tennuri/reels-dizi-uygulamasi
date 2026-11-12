# Reels dizi uygulaması

Bir kitabı senaryoya, çekim listesine ve LTX-2.5 ile üretilen dikey (9:16) Reels bölümlerine çeviren, bunları uygulama içinde paylaşmayı hedefleyen proje.

## Klasörler

| Klasör | İçerik |
|---|---|
| [adim1](adim1/) | Video modelini RunPod'da (ComfyUI ile) çalıştırma rehberi: [LTX-2.5](adim1/runpod-ltx-kurulum.md) (güncel), [MiniMax H3](adim1/runpod-h3-kurulum.md) (eski) |
| [adim2](adim2/) | Kitap → bölümler → çekimler → H3 promptları için LLM şablonları |
| [adim3](adim3/) | Çekim listesini toplu üreten betik (`h3_toplu_uret.py`, LTX-2.5 ve H3 şablonlarıyla çalışır; LTX şablonları `adim3/workflows/`), karakter/mekan tutarlılığı için referans ve başlangıç karesi betiği (`tutarlilik.py`), klipleri birleştiren betik (`birlestir.sh`) ve kullanım rehberi |
| [adim4](adim4/) | Hazır bir dizi bölümünden çekim listesi, diyalog ve bible taslağı çıkaran zincir (PySceneDetect + WhisperX + Qwen3-VL) |

## Akış

1. `adim2` şablonlarıyla kitaptan `bible.json` ve bölüm çekim listelerini (`bolum1.json` ...) çıkar.
2. `adim1/runpod-ltx-kurulum.md` rehberiyle RunPod'da ComfyUI + LTX-2.5 kur.
3. `adim3` rehberiyle karakter kartlarını ve mekan karelerini bir kez hazırla (8. madde), sonra bölümün kliplerini üret ve tek videoda birleştir.

## Model geçmişi

- 22.10.2026 – 11.11.2026: MiniMax H3.
- 11.11.2026'dan beri: **LTX-2.5** (Lightricks). H3'e göre daha hızlı, ses üretiyor ve ComfyUI'da yerel olarak destekleniyor. H3 model dosyaları pod'dan silindi, H3 şablonları ve rehberi başvuru için duruyor.
