# Diziden senaryo çıkarma: iki yolun ayrıntısı

Amaç: hazır bir dizi bölümünü izletip şunları çıkarmak:
sahneler, diyaloglar (kim konuşuyor), her çekimin plan boyu, açısı ve kamera hareketi.
Çıktı bizim formatlarımızda olacak: `bible.json` (karakter, mekan, beat) ve
`senaryo-sablonlari.md` Adım 3'teki shot list alanları (size / angle / movement / action / audio / dialogue).

> Telif notu: Çıktıyı yapıyı, tempoyu ve çekim dilini öğrenmek için kullan.
> Başka bir dizinin sahnelerini, karakterlerini veya diyaloglarını kendi dizine taşıma.

---

## Seçenek 1: RunPod'da yerel zincir (önerim)

Her iş için en iyi aracı ayrı ayrı çalıştırırız. Hepsi senin A40 (48 GB) pod'unda çalışır, video dışarı çıkmaz.

### Adımlar

| # | Araç | Ne yapar | Çıktı |
|---|------|----------|-------|
| 1 | **ffmpeg** | Bölümü 720p'ye indirir, sesi ayrı WAV olarak çıkarır | `bolum.mp4`, `ses.wav` |
| 2 | **PySceneDetect** | Kesme noktalarını bulur, bölümü çekimlere böler | `cekimler.csv` (başlangıç/bitiş), her çekim için kısa klip + 3 kare |
| 3 | **WhisperX (large-v3)** | Türkçe konuşmayı kelime düzeyinde zaman damgasıyla yazıya döker | `diyalog.json` |
| 4 | **pyannote** (WhisperX içinde) | Kim konuşuyor ayrımı: SPEAKER_00, SPEAKER_01... | `diyalog.json` içine konuşmacı etiketi |
| 5 | **Qwen3-VL** (vLLM ile) | Her çekim klibini izler, sabit bir JSON şablonuyla doldurur: plan boyu, açı, hareket, kimler var, mekan, aksiyon | `cekim_analizi.jsonl` |
| 6 | **Metin LLM'i** (Claude veya Qwen3) | Çekimleri sahnelere gruplar, konuşmacıları karakter adlarıyla eşler, beat'leri çıkarır | `bible.json` + bölüm shot list'i |

### Model boyutu seçimi

- **Qwen3-VL-8B**: yaklaşık 17 GB, hızlı. Plan boyu ve açı için genelde yeterli.
- **Qwen3-VL-30B-A3B (FP8)**: yaklaşık 32 GB, A40'a sığar. Kamera hareketi ve ince ayrıntıda daha iyi.
- İlk denemede 8B ile başlayıp 3-4 çekimi 30B ile karşılaştırmayı öneririm.
- Adımlar sırayla çalıştığı için WhisperX ve Qwen3-VL aynı anda belleğe yüklenmez.

### Neden kare yerine kısa klip?

Tek bir kareden "kamera sağa kayıyor" ya da "yavaşça yaklaşıyor" anlaşılmaz.
Qwen3-VL her çekimin klibini saniyede 2 kare hızında izler, böylece hareketi de görür.

### Konuşmacıyı karaktere bağlama

pyannote sadece "SPEAKER_00" der, adını bilmez. Bunu iki şekilde çözeriz:
1. Konuşma anındaki çekimde Qwen3-VL'nin "ekranda kim var, kimin ağzı oynuyor" cevabı.
2. Bölüm başında senin elle yazdığın kısa bir eşleme: `SPEAKER_00 = kadın başrol` gibi. Bir kere yazılır, kalan bölümlerde kullanılır.

### Gerekenler

- Pod'a kurulacaklar: `ffmpeg`, `scenedetect`, `whisperx`, `vllm` (pip ile).
- Hugging Face hesabı ve token. pyannote modelinin sayfasında kullanım şartlarını bir kere onaylaman gerekir.
- Disk: modeller için yaklaşık 60-80 GB. 200 GB container disk'in yeterli. Kalıcı volume olmadığı için pod kapanınca modeller silinir, her seferinde yeniden inmesi 10-15 dakika sürer.

### Süre ve maliyet (tahmin, henüz denenmedi)

45 dakikalık bir bölüm, yaklaşık 600-800 çekim:
- WhisperX: 3-5 dakika
- Qwen3-VL-8B ile çekim analizi: 20-40 dakika
- Toplam, kurulum hariç: 30-60 dakika, A40 ücretiyle (saati 0,62 $) bölüm başına yaklaşık 0,30-0,60 $

### Artıları ve eksileri

- ✅ Video senin pod'undan çıkmaz.
- ✅ Çıktı formatını tamamen biz belirleriz. `bible.json` ve shot list'e birebir uyar.
- ✅ Bölüm sayısı arttıkça ucuz kalır.
- ✅ Her adım ayrı olduğu için hangi adımın hata yaptığı görülür (yanlış diyalog mu, yanlış açı mı).
- ❌ Kurulum ve ilk ayar 1-2 akşam sürer.
- ❌ Qwen3-VL bazen plan boyunu karıştırır (yakın/orta plan). Birkaç örnekle prompt ayarı gerekebilir.

---

## Seçenek 2: Gemini API ile hızlı yol

Google'ın Gemini modeli videoyu **sesiyle birlikte** tek seferde izleyebiliyor. Ayrı ses tanıma, sahne bölme gerekmiyor.

### Adımlar

1. Google AI Studio'dan API anahtarı alınır.
2. Bölüm Files API ile yüklenir (dosya başına 2 GB'a kadar, 48 saat saklanır).
3. Tek bir prompt gönderilir: "Bu bölümü izle, her çekim için zaman, plan boyu, açı, hareket, kimler var, diyalog ve konuşmacı yaz, şu JSON şemasında ver."
4. Gelen JSON, Seçenek 1'in 6. adımındaki gibi `bible.json` ve shot list'e çevrilir.

Bir bölüm çok uzunsa (bağlam penceresini aşarsa) 10-15 dakikalık parçalara bölüp ayrı ayrı göndeririz.

### Süre ve maliyet (tahmin)

- Kurulum: yaklaşık 1 saat. Pod gerekmez, kendi bilgisayarından da çalışır.
- Bölüm başına işlem: birkaç dakika.
- Ücret: kullanılan modele ve video çözünürlüğüne göre değişir. 45 dakikalık bir bölüm için birkaç dolar civarı bekliyorum. Kesin rakam için güncel fiyat sayfasına birlikte bakarız.

### Artıları ve eksileri

- ✅ En hızlı başlangıç. GPU, model indirme, kurulum yok.
- ✅ Görüntü ve sesi birlikte anladığı için "kim konuşuyor" sorusunda genelde daha iyi.
- ✅ Tek prompt ile hikaye akışını ve beat'leri de doğrudan çıkarabilir.
- ❌ Video Google'a yüklenir. Ücretsiz katmanda yüklenen veri modeli geliştirmek için kullanılabilir, ücretli katmanda kullanılmaz.
- ❌ Çekim kesmelerini tek tek bulmada bir sahne algılayıcı kadar hassas değil, bazı kısa çekimleri atlayabilir.
- ❌ Bölüm sayısı arttıkça maliyet yerel yoldan yüksek olur.
- ❌ Projenin "her şey yerelde" hedefinden sapar (ama bu araç sadece analiz için, üründe yer almıyor).

---

## Karşılaştırma

| | Yerel zincir (RunPod) | Gemini API |
|---|---|---|
| Kurulum | 1-2 akşam | ~1 saat |
| Bölüm başına süre | 30-60 dk | birkaç dk |
| Bölüm başına maliyet | ~0,30-0,60 $ | birkaç $ (tahmin) |
| Video gizliliği | Pod'da kalır | Google'a yüklenir |
| Çekim kesme hassasiyeti | Yüksek (PySceneDetect) | Orta |
| Konuşmacı tanıma | Orta, eşleme gerekir | İyi |
| Format kontrolü | Tam | İyi (JSON şeması ile) |

## Önerim

Uzun vadede **yerel zincir**. Bir ara yol da var: önce Gemini ile bir bölümü hızlıca deneyip çıktının işine yarayıp yaramadığını görmek, beğenirsen yerel zinciri kurmak. İki yolda da 6. adımdaki "bizim formata çevirme" kısmı aynı olduğu için emek boşa gitmez.
