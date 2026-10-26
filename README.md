# Reels dizi uygulaması

Bir kitabı senaryoya, çekim listesine ve MiniMax H3 ile üretilen dikey (9:16) Reels bölümlerine çeviren, bunları uygulama içinde paylaşmayı hedefleyen proje.

## Klasörler

| Klasör | İçerik |
|---|---|
| [adim1](adim1/) | H3'ü RunPod'da (ComfyUI ile) çalıştırma rehberi |
| [adim2](adim2/) | Kitap → bölümler → çekimler → H3 promptları için LLM şablonları |
| [adim3](adim3/) | Çekim listesini toplu üreten betik (`h3_toplu_uret.py`), klipleri birleştiren betik (`birlestir.sh`) ve kullanım rehberi |

## Akış

1. `adim2` şablonlarıyla kitaptan `bible.json` ve bölüm çekim listelerini (`bolum1.json` ...) çıkar.
2. `adim1` rehberiyle RunPod'da ComfyUI + H3 kur.
3. `adim3` rehberiyle bölümün kliplerini üret ve tek videoda birleştir.
