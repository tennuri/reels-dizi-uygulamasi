# Kitaptan Reels dizisine: prompt şablonları

Bu dosyada dört adımın her biri için LLM'e verilecek hazır bir prompt var. Her adımın çıktısı bir sonrakinin girdisi oluyor. Çıktılar JSON olduğu için uygulama (veya bir Python betiği) bunları doğrudan okuyup H3'e gönderebilir.

`{{...}}` olan yerleri doldurman yeterli. H3 promptları İngilizce yazılıyor çünkü ComfyUI şablonundaki örnekler İngilizce. Diyalog ve dış ses Türkçe kalabilir.

---

## Adım 1: Dizi kutsal kitabı (karakter + mekan kartları)

Bütün kitap tek seferde verilir (1M bağlamlı bir modelde sorun olmaz). Açık model kullanıyorsan önce her bölümün özetini çıkar, sonra özetlerin hepsini bu prompta ver.

```text
Aşağıda bir kitabın tam metni var. Bu kitabı dikey (9:16) kısa video dizisine
uyarlayacağız. Video modeli her çekimi ayrı üretiyor ve önceki çekimleri
hatırlamıyor, bu yüzden görsel tarifler her seferinde aynen tekrar edilecek.

Görev: Bir "dizi kutsal kitabı" çıkar.

Kurallar:
- Her önemli karakter için İNGİLİZCE, tek paragraflık, değişmeyecek bir görsel
  tarif yaz: yaş, ten, yüz şekli, saç (renk/uzunluk/model), göz, boy/yapı,
  her zaman giydiği kıyafet ve renkleri, ayırt edici bir detay.
  "Güzel", "yakışıklı" gibi yoruma açık kelimeler kullanma; ölçülebilir yaz.
- Kitap bir görünüşü belirtmiyorsa döneme ve bölgeye uygun olanı seç ve
  "invented": true işaretle.
- Her tekrar eden mekan için İngilizce görsel tarif: dönem, ışık, renkler,
  dokular, saat.
- Genel görsel üslup: tek cümlelik "style" satırı (renk paleti, film dokusu,
  ışık karakteri). Bu satır tüm çekimlere eklenecek.
- Kitabın ana olay akışını 10-30 maddelik bir "beat" listesi olarak çıkar.

Çıktı yalnızca şu JSON olsun:
{
  "title": "",
  "style": "",
  "characters": [
    {"id": "C1", "name": "", "role": "", "visual": "", "voice": "", "invented": false}
  ],
  "locations": [
    {"id": "L1", "name": "", "visual": ""}
  ],
  "beats": [
    {"n": 1, "chapter": "", "summary": "", "characters": ["C1"], "location": "L1"}
  ]
}

KİTAP:
{{kitap_metni}}
```

---

## Adım 2: Beat'lerden Reels bölümlerine

```text
Aşağıda bir dizinin kutsal kitabı (JSON) var. Bunu Reels bölümlerine böl.

Kurallar:
- Her bölüm {{bolum_suresi_sn}} saniye civarı (60-90 arası öneriyorum).
- Her bölüm ilk 3 saniyede bir kancayla açılsın (merak, tehlike, çarpıcı görüntü).
- Her bölüm (sonuncusu hariç) cevapsız bir soruyla veya gerilimle bitsin.
- Bir bölüm 1-3 sahne içersin. Sahne = aynı mekan + kesintisiz zaman.
- Hikayeyi kısaltabilirsin ama karakterlerin temel kararlarını ve sonu değiştirme.
- Toplam bölüm sayısı en fazla {{max_bolum}}.

Çıktı yalnızca JSON:
{
  "episodes": [
    {
      "ep": 1,
      "title": "",
      "hook": "ilk 3 saniyede ne görüyoruz",
      "cliffhanger": "",
      "beats": [1, 2],
      "scenes": [
        {"scene": 1, "location": "L1", "characters": ["C1"], "summary": ""}
      ]
    }
  ]
}

KUTSAL KİTAP:
{{adim1_json}}
```

---

## Adım 3: Bölümden çekim listesine (shot list)

Bu adım her bölüm için ayrı çalıştırılır.

```text
Sen bir film yönetmeni ve görüntü yönetmenisin. Aşağıdaki bölümü dikey (9:16)
bir Reels için çekim listesine çevir.

Kurallar:
- Toplam süre {{bolum_suresi_sn}} sn. Her çekim 4-10 sn (video modeli en fazla
  ~15 sn üretiyor; 5-8 sn en güvenlisi).
- Her çekimde: shot size (extreme close-up / close-up / medium / wide /
  extreme wide), açı (eye level / low angle / high angle / high side angle /
  overhead / over-the-shoulder / POV), kamera hareketi (static / slow push-in /
  pull-out / pan / tilt / tracking / handheld), ne olduğu, ışık, ses.
- Dikey kadraj düşün: konu ortada, yatay geniş panoramalar yerine derinlik kullan.
- Aynı açıyı arka arkaya tekrar etme. Diyalog sahnesinde shot/reverse-shot kullan.
- Bir çekimde en fazla bir net aksiyon olsun. Karmaşık hareketi iki çekime böl.
- Diyalog kısa olsun: bir çekimde en fazla bir cümle.
- İlk çekim bölümün kancası olsun.

Çıktı yalnızca JSON:
{
  "ep": 1,
  "shots": [
    {
      "shot": 1,
      "duration_s": 6,
      "scene": 1,
      "location": "L1",
      "characters": ["C1"],
      "size": "close-up",
      "angle": "low angle",
      "movement": "slow push-in",
      "action": "İngilizce, tek cümle, ne görüyoruz",
      "lighting": "",
      "audio": "ortam sesi / müzik tonu",
      "dialogue": {"speaker": "C1", "line": "Türkçe replik"},
      "voiceover": ""
    }
  ]
}

KUTSAL KİTAP:
{{adim1_json}}

BÖLÜM:
{{adim2_bolum_json}}
```

---

## Adım 4: Çekimden H3 promptuna

Bu adım LLM gerektirmez, basit bir betikle yapılır. Böylece karakter tarifi her prompta harfi harfine aynı girer ve tutarlılık bozulmaz.

```python
def h3_prompt(shot, bible):
    chars = {c["id"]: c for c in bible["characters"]}
    locs = {l["id"]: l for l in bible["locations"]}

    parts = [
        f'Shot {shot["shot"]}: {shot["angle"]}, {shot["size"]}, {shot["movement"]}.',
        shot["action"],
    ]
    for cid in shot["characters"]:
        parts.append(f'{chars[cid]["name"]}: {chars[cid]["visual"]}')
    parts.append(f'Setting: {locs[shot["location"]]["visual"]}')
    if shot.get("lighting"):
        parts.append(f'Lighting: {shot["lighting"]}')
    if shot.get("dialogue"):
        d = shot["dialogue"]
        parts.append(f'{chars[d["speaker"]]["name"]} says in Turkish: "{d["line"]}"')
    if shot.get("audio"):
        parts.append(f'Audio: {shot["audio"]}')
    parts.append(f'Style: {bible["style"]}. Vertical 9:16.')
    return " ".join(parts)
```

H3'ün Türkçe konuşmayı ne kadar iyi seslendirdiğini henüz test etmedik. Kötü çıkarsa diyalog satırını prompttan çıkarıp sesi ayrıca (TTS ile) ekleyebiliriz.

---

## Örnek: Ömer Seyfettin, "Kaşağı" (kamu malı)

Ömer Seyfettin 1920'de öldü, eserleri kamu malı. Kısa bir öykü olduğu için ilk tam dizi denemesi için uygun.

### Adım 1 çıktısından kesit

```json
{
  "title": "Kaşağı",
  "style": "warm late-afternoon Ottoman countryside, muted earth tones, soft 35mm film grain, natural light, intimate and melancholic",
  "characters": [
    {"id": "C1", "name": "Narrator (child)", "role": "anlatıcı, ağabey",
     "visual": "8-year-old Turkish boy, thin, olive skin, short dark brown hair, large dark eyes, wears a faded maroon wool vest over a cream linen shirt and grey short trousers",
     "invented": true},
    {"id": "C2", "name": "Hasan", "role": "küçük kardeş",
     "visual": "6-year-old Turkish boy, round face, rosy cheeks, light brown curly hair, wears an oversized pale blue cotton shirt and brown trousers, barefoot",
     "invented": true},
    {"id": "C3", "name": "Dadaruh", "role": "yaşlı seyis",
     "visual": "70-year-old man, deeply wrinkled tanned face, short white beard, black skullcap, worn dark green jacket, leather apron",
     "invented": true},
    {"id": "C4", "name": "Father", "role": "baba",
     "visual": "45-year-old Ottoman gentleman, trimmed black beard with grey streaks, red fez, dark navy frock coat",
     "invented": true}
  ],
  "locations": [
    {"id": "L1", "name": "Ahır", "visual": "old wooden stable, hay on the floor, dust in slanted sunbeams, a chestnut horse in a stall, tools hanging on the wall"},
    {"id": "L2", "name": "Konak bahçesi", "visual": "walled garden of a wooden Ottoman mansion, fruit trees, stone path, well in the corner"}
  ]
}
```

### Adım 2 çıktısı: 4 bölümlük plan

| Bölüm | Başlık | Kanca | Merakta bırakan son |
|---|---|---|---|
| 1 | Yeni kaşağı | Güneş ışığında parlayan yeni kaşağı | Çocuk öfkeyle kaşağıyı taşla kırıyor |
| 2 | Yalan | Kırık kaşağı samanın içinde | "Hasan kırdı" diyor; Hasan'ın şaşkın yüzü |
| 3 | Ceza | Babanın sert sesi koridorda | Hasan ahıra bakarak ağlıyor, kapı kapanıyor |
| 4 | Pişmanlık | Boş ahır, tek bir kaşağı duvarda asılı | (Final) Yetişkin anlatıcı itiraf ediyor |

### Adım 3 çıktısı: 1. bölüm çekim listesi (≈57 sn)

| # | Süre | Açı / Boyut / Hareket | Ne oluyor | Ses |
|---|---|---|---|---|
| 1 | 5 sn | eye level, extreme close-up, slow push-in | Yeni kaşağı güneş ışığında parlıyor, bir elin içinde | Kuş sesleri, hafif ud |
| 2 | 6 sn | low angle, medium, static | Dadaruh (C3) yeni kaşağıyı rafa koyuyor, çocuklara dokunmamalarını söylüyor | Dadaruh: "Siz daha küçüksünüz, buna dokunmayın." |
| 3 | 6 sn | over-the-shoulder, close-up, static | Anlatıcı (C1) kapı aralığından hayranlıkla bakıyor | Dış ses: "O kaşağıyı görür görmez..." |
| 4 | 7 sn | high side angle, wide, slow pan | Ahır (L1): Dadaruh atı tımar ediyor, toz ışıkta uçuşuyor | At nefesi, kaşağı sesi |
| 5 | 6 sn | eye level, medium, tracking | Dadaruh ahırdan çıkıyor, kaşağıyı rafa bırakıyor | Ayak sesleri |
| 6 | 6 sn | POV, medium, handheld | Anlatıcının gözünden: raftaki kaşağıya yaklaşma | Kalp atışı, sessizlik |
| 7 | 5 sn | eye level, close-up, static | Anlatıcı kaşağıyı alıp atın yanına gidiyor, gülümsüyor | Saman hışırtısı |
| 8 | 6 sn | low angle, medium, static | Kaşağıyı ata sürtüyor; at huysuzlanıyor | Atın kişnemesi |
| 9 | 5 sn | overhead, extreme close-up, static | Çocuk öfkeyle kaşağıya taşla vurup kırıyor | Keskin metal sesi, müzik kesiliyor |
| 10 | 5 sn | eye level, close-up, slow push-in | Anlatıcının donmuş yüzü | Sessizlik, uzaktan Dadaruh'un sesi: "Neredesin?" |

Bu tablo öykünün genel akışına dayanan serbest bir uyarlama. Gerçek kullanımda Adım 1–3 promptları öykünün tam metniyle çalıştırılmalı ki detaylar metne sadık kalsın.

### Adım 4 çıktısı: 9. çekimin H3 promptu

```text
Shot 9: overhead, extreme close-up, static. On a stone stable floor, a
child's hand angrily smashes a shiny new currycomb with a rock until it breaks. Narrator
(child): 8-year-old Turkish boy, thin, olive skin, short dark brown hair,
large dark eyes, wears a faded maroon wool vest over a cream linen shirt and
grey short trousers. Setting: old wooden stable, hay on the floor, dust in
slanted sunbeams, a chestnut horse in a stall, tools hanging on the wall.
Lighting: warm slanted sunbeam on the floor. Audio: sharp metallic crack,
music cuts to silence. Style: warm late-afternoon Ottoman countryside, muted
earth tones, soft 35mm film grain, natural light, intimate and melancholic.
Vertical 9:16.
```

Not: Karakter tarifleri benim uydurduklarım (öykü dış görünüş vermiyor). Değiştirmek istersen bir kez kutsal kitapta değiştirmen yeterli, bütün promptlara yansır.

---

## Sıradaki adım

1. RunPod'da 9. çekimi tek başına üret; karakter tutarlılığına ve sese bak.
2. Sonuç iyiyse 1. bölümün 10 çekimini üretip uç uca ekle. Bu, "bir diziyi baştan sona çekmek" hedefinin ilk bölümü olur.
