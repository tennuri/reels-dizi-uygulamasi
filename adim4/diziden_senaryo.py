#!/usr/bin/env python3
"""Bir dizi bölümünden çekim listesi ve bible taslağı çıkarır.

Adımlar (her biri ayrı çalıştırılabilir, yarıda kalırsa kaldığı yerden devam eder):

  kes        ffmpeg + PySceneDetect: sesi ayırır, bölümü çekimlere böler, her çekimden kare alır
  ses        WhisperX + pyannote: Türkçe diyalog + konuşmacı (ayrı sanal ortamda çalışır)
  analiz     Qwen3-VL (vLLM sunucusu): her çekimin plan boyu, açısı, hareketi, aksiyonu
  birlestir  Hepsini adim2 Adım 3 shot list formatında cekim_listesi.json'a yazar
  bible      Metin LLM'i: çekimleri sahnelere gruplar, bible_taslak.json (karakter, mekan, beat) çıkarır

Örnek:
  python3 diziden_senaryo.py bolum1.mp4 --cikti analiz/bolum1
  python3 diziden_senaryo.py bolum1.mp4 --cikti analiz/bolum1 --adim analiz --sinir 5

Not: Çıktıyı yapıyı ve çekim dilini öğrenmek için kullan; başka bir dizinin sahnelerini
veya diyaloglarını kendi dizine taşıma.
"""
import argparse
import base64
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

BURADA = os.path.dirname(os.path.abspath(__file__))
ADIMLAR = ["kes", "ses", "analiz", "birlestir", "bible"]

# adim2/senaryo-sablonlari.md Adım 3 ile aynı sözlük
SIZES = ["extreme close-up", "close-up", "medium close-up", "medium", "medium wide", "wide", "extreme wide"]
ANGLES = ["eye level", "low angle", "high angle", "high side angle", "overhead",
          "over-the-shoulder", "POV", "dutch angle"]
MOVES = ["static", "slow push-in", "pull-out", "pan", "tilt", "tracking", "handheld", "zoom"]


def log(msg):
    print(msg, flush=True)


def yaz_json(yol, veri):
    tmp = yol + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
    os.replace(tmp, yol)


def oku_json(yol):
    with open(yol, encoding="utf-8") as f:
        return json.load(f)


def calistir(komut):
    r = subprocess.run(komut, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.exit(f"Komut başarısız: {' '.join(komut)}\n{r.stderr[-2000:]}")
    return r.stdout


# ---------------------------------------------------------------- kes
def adim_kes(a):
    wav = os.path.join(a.cikti, "ses.wav")
    if not os.path.exists(wav):
        log("[kes] ses ayrılıyor")
        calistir(["ffmpeg", "-y", "-loglevel", "error", "-i", a.video,
                  "-vn", "-ac", "1", "-ar", "16000", wav])

    cekim_yol = os.path.join(a.cikti, "cekimler.json")
    if os.path.exists(cekim_yol):
        cekimler = oku_json(cekim_yol)["shots"]
        log(f"[kes] {len(cekimler)} çekim zaten var, kesme atlandı")
    else:
        log("[kes] çekim kesmeleri aranıyor (PySceneDetect)")
        from scenedetect import ContentDetector, detect
        sahneler = detect(a.video, ContentDetector(threshold=a.esik, min_scene_len=a.min_kare),
                          show_progress=False)
        if not sahneler:  # hiç kesme yoksa tüm video tek çekim
            sure = float(calistir(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", a.video]).strip())
            araliklar = [(0.0, sure)]
        else:
            sn = lambda t: t.seconds if hasattr(type(t), "seconds") else t.get_seconds()
            araliklar = [(sn(s), sn(e)) for s, e in sahneler]
        cekimler = [{"id": i + 1, "start": round(s, 3), "end": round(e, 3)}
                    for i, (s, e) in enumerate(araliklar)]
        yaz_json(cekim_yol, {"video": os.path.abspath(a.video), "shots": cekimler})
        log(f"[kes] {len(cekimler)} çekim bulundu")

    kare_dir = os.path.join(a.cikti, "kareler")
    os.makedirs(kare_dir, exist_ok=True)
    for c in cekimler:
        hedef = os.path.join(kare_dir, f"{c['id']:04d}")
        if glob.glob(hedef + "_*.jpg"):
            continue
        sure = c["end"] - c["start"]
        n = max(1, min(a.kare_sayisi, int(sure * 2) or 1))  # saniyede en fazla 2 kare
        for k in range(n):
            t = c["start"] + sure * (k + 0.5) / n
            calistir(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", a.video,
                      "-frames:v", "1", "-vf", f"scale=-2:{a.kare_yukseklik}", "-q:v", "4",
                      f"{hedef}_{k + 1}.jpg"])
    log(f"[kes] kareler hazır: {kare_dir}")


# ---------------------------------------------------------------- ses
def adim_ses(a):
    hedef = os.path.join(a.cikti, "diyalog.json")
    if os.path.exists(hedef):
        log("[ses] diyalog.json zaten var, atlandı")
        return
    py = a.ses_python
    if not os.path.exists(py):
        sys.exit(f"WhisperX ortamı bulunamadı: {py}\nÖnce kurulum.sh çalıştır ya da --ses-python ver.")
    komut = [py, os.path.join(BURADA, "ses_coz.py"), os.path.join(a.cikti, "ses.wav"), hedef,
             "--dil", a.dil]
    if a.max_konusmaci:
        komut += ["--max-konusmaci", str(a.max_konusmaci)]
    log("[ses] WhisperX çalışıyor (bu adım GPU'yu kullanır, vLLM'i sonra başlat)")
    r = subprocess.run(komut)
    if r.returncode != 0:
        sys.exit("[ses] WhisperX hata verdi")


# ---------------------------------------------------------------- LLM çağrısı
def sohbet(url, model, mesajlar, max_tokens=800, deneme=3):
    govde = json.dumps({"model": model, "messages": mesajlar, "temperature": 0.2,
                        "max_tokens": max_tokens}).encode()
    istek = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=govde,
                                   headers={"Content-Type": "application/json",
                                            "Authorization": "Bearer " + os.environ.get("LLM_API_KEY", "yok")})
    for i in range(deneme):
        try:
            with urllib.request.urlopen(istek, timeout=600) as r:
                return json.load(r)["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, KeyError) as e:
            if i == deneme - 1:
                raise
            log(f"  istek hatası ({e}), tekrar deneniyor")
            time.sleep(3 * (i + 1))


def json_ayikla(metin):
    """Model çıktısındaki ilk JSON nesnesini bulur (```json bloklarını ve <think> kısmını atlar)."""
    metin = re.sub(r"<think>.*?</think>", "", metin, flags=re.S)
    bas = metin.find("{")
    if bas < 0:
        raise ValueError("JSON bulunamadı")
    derinlik, tirnak, kacis = 0, False, False
    for i in range(bas, len(metin)):
        ch = metin[i]
        if tirnak:
            if kacis:
                kacis = False
            elif ch == "\\":
                kacis = True
            elif ch == '"':
                tirnak = False
        elif ch == '"':
            tirnak = True
        elif ch == "{":
            derinlik += 1
        elif ch == "}":
            derinlik -= 1
            if derinlik == 0:
                return json.loads(metin[bas:i + 1])
    raise ValueError("JSON yarım kalmış")


def en_yakin(deger, liste, varsayilan):
    d = (deger or "").strip().lower()
    for x in liste:
        if d == x.lower():
            return x
    for x in sorted(liste, key=len, reverse=True):  # "slow push-in shot" -> "slow push-in"
        if x.lower() in d:
            return x
    return d or varsayilan


def cekim_diyalogu(c, segler):
    return [s for s in segler if s["start"] < c["end"] and s["end"] > c["start"]
            and min(s["end"], c["end"]) - max(s["start"], c["start"]) >= 0.3]


# ---------------------------------------------------------------- analiz
ANALIZ_PROMPT = """You are a film director and cinematographer analysing one shot of a TV episode.
The images are {n} frames taken in order from a single continuous shot lasting {sure:.1f} seconds.
{diyalog}
Describe the shot. Answer with JSON only, no other text:
{{
  "size": one of {sizes},
  "angle": one of {angles},
  "movement": one of {moves} (compare the frames: did the camera move?),
  "characters": [{{"label": "short stable visual label, e.g. 'woman, long dark hair, camel blazer'", "position": "left/center/right, foreground/background"}}],
  "speaker": "label of the person whose mouth is moving, or empty",
  "location": "short stable name of the place, e.g. 'living room with burgundy sofas'",
  "action": "one English sentence: what we see happening",
  "lighting": "short English description",
  "composition": "short note on framing, depth, eyeline"
}}"""


def adim_analiz(a):
    cekimler = oku_json(os.path.join(a.cikti, "cekimler.json"))["shots"]
    dy = os.path.join(a.cikti, "diyalog.json")
    segler = oku_json(dy)["segments"] if os.path.exists(dy) else []
    hedef = os.path.join(a.cikti, "cekim_analizi.jsonl")
    bitti = set()
    if os.path.exists(hedef):
        with open(hedef, encoding="utf-8") as f:
            bitti = {json.loads(l)["id"] for l in f if l.strip()}
    yapilacak = [c for c in cekimler if c["id"] not in bitti]
    if a.sinir:
        yapilacak = yapilacak[:a.sinir]
    log(f"[analiz] {len(bitti)} çekim hazır, {len(yapilacak)} çekim analiz edilecek ({a.vlm_model})")

    with open(hedef, "a", encoding="utf-8") as out:
        for i, c in enumerate(yapilacak, 1):
            kareler = sorted(glob.glob(os.path.join(a.cikti, "kareler", f"{c['id']:04d}_*.jpg")))
            if not kareler:
                sys.exit(f"Çekim {c['id']} için kare yok, önce --adim kes çalıştır")
            replikler = cekim_diyalogu(c, segler)
            diyalog = ""
            if replikler:
                diyalog = "Dialogue heard during this shot (Turkish):\n" + "\n".join(
                    f'- {s["speaker"]}: "{s["text"]}"' for s in replikler) + "\n"
            prompt = ANALIZ_PROMPT.format(n=len(kareler), sure=c["end"] - c["start"], diyalog=diyalog,
                                          sizes=SIZES, angles=ANGLES, moves=MOVES)
            icerik = [{"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(open(k, "rb").read()).decode()}}
                for k in kareler]
            icerik.append({"type": "text", "text": prompt})
            t0 = time.time()
            try:
                cevap = sohbet(a.vlm_url, a.vlm_model, [{"role": "user", "content": icerik}])
                sonuc = json_ayikla(cevap)
            except Exception as e:
                log(f"  çekim {c['id']}: hata ({e}), atlandı; tekrar çalıştırınca yeniden denenir")
                continue
            sonuc["id"] = c["id"]
            out.write(json.dumps(sonuc, ensure_ascii=False) + "\n")
            out.flush()
            log(f"  [{i}/{len(yapilacak)}] çekim {c['id']}: {sonuc.get('size')}, {sonuc.get('angle')}, "
                f"{sonuc.get('movement')} ({time.time() - t0:.1f} sn)")


# ---------------------------------------------------------------- birlestir
def esleme_oku(a):
    if a.esleme and os.path.exists(a.esleme):
        return oku_json(a.esleme)
    return {}


def adim_birlestir(a):
    cekimler = oku_json(os.path.join(a.cikti, "cekimler.json"))["shots"]
    dy = os.path.join(a.cikti, "diyalog.json")
    segler = oku_json(dy)["segments"] if os.path.exists(dy) else []
    analiz = {}
    yol = os.path.join(a.cikti, "cekim_analizi.jsonl")
    if os.path.exists(yol):
        with open(yol, encoding="utf-8") as f:
            for l in f:
                if l.strip():
                    d = json.loads(l)
                    analiz[d["id"]] = d
    esleme = esleme_oku(a)  # {"SPEAKER_00": "Derin"} gibi

    shots = []
    for c in cekimler:
        v = analiz.get(c["id"], {})
        replikler = cekim_diyalogu(c, segler)
        shot = {
            "shot": c["id"],
            "start_s": c["start"],
            "end_s": c["end"],
            "duration_s": round(c["end"] - c["start"], 2),
            "location": v.get("location", ""),
            "characters": [x.get("label", "") if isinstance(x, dict) else str(x)
                           for x in v.get("characters", [])],
            "size": en_yakin(v.get("size"), SIZES, ""),
            "angle": en_yakin(v.get("angle"), ANGLES, ""),
            "movement": en_yakin(v.get("movement"), MOVES, ""),
            "action": v.get("action", ""),
            "lighting": v.get("lighting", ""),
            "composition": v.get("composition", ""),
            "dialogue": [{"speaker": esleme.get(s["speaker"], s["speaker"]), "line": s["text"]}
                         for s in replikler],
            "on_screen_speaker": v.get("speaker", ""),
            "analysed": bool(v),
        }
        shots.append(shot)

    hedef = os.path.join(a.cikti, "cekim_listesi.json")
    yaz_json(hedef, {"source": oku_json(os.path.join(a.cikti, "cekimler.json"))["video"], "shots": shots})

    # Kısa istatistik: çekim dilini öğrenmek için asıl işe yarayan kısım
    def say(alan):
        sayac = {}
        for s in shots:
            if s["analysed"] and s[alan]:
                sayac[s[alan]] = sayac.get(s[alan], 0) + 1
        return dict(sorted(sayac.items(), key=lambda x: -x[1]))
    sureler = [s["duration_s"] for s in shots]
    ozet = {
        "shot_count": len(shots),
        "analysed": sum(s["analysed"] for s in shots),
        "avg_shot_s": round(sum(sureler) / max(1, len(sureler)), 2),
        "median_shot_s": sorted(sureler)[len(sureler) // 2] if sureler else 0,
        "sizes": say("size"),
        "angles": say("angle"),
        "movements": say("movement"),
        "speakers": sorted({d["speaker"] for s in shots for d in s["dialogue"]}),
    }
    yaz_json(os.path.join(a.cikti, "ozet.json"), ozet)
    log(f"[birlestir] {len(shots)} çekim -> {hedef}")
    log(f"[birlestir] ortalama çekim {ozet['avg_shot_s']} sn, konuşmacılar: {', '.join(ozet['speakers']) or '-'}")
    if ozet["speakers"] and not esleme:
        log("  İpucu: konuşmacı adları için konusmaci.json yaz, örn. {\"SPEAKER_00\": \"Kadın başrol\"}, "
            "sonra --adim birlestir'i --esleme konusmaci.json ile tekrar çalıştır")


# ---------------------------------------------------------------- bible
SAHNE_PROMPT = """Below are consecutive shots from a TV episode (JSON lines: id, time, location, characters, action, dialogue).
Group them into scenes. A scene = same location + continuous time.
Answer with JSON only:
{{"scenes": [{{"first_shot": 1, "last_shot": 9, "location": "short name", "characters": ["visual labels"], "summary": "2 sentences in English", "turning_point": "what changes, or empty"}}]}}

SHOTS:
{satirlar}"""

BIBLE_PROMPT = """Below is the scene list of a TV episode, extracted automatically from video and dialogue.
Build a draft series bible in this exact JSON shape, with ids C1.. and L1..:
{{
  "title": "",
  "style": "one paragraph: look, palette, lens feel, lighting, editing rhythm",
  "characters": [{{"id": "C1", "name": "speaker name if known, else a role", "role": "one sentence", "visual": "fixed English visual description", "labels": ["the visual labels used in the scene list for this person"]}}],
  "locations": [{{"id": "L1", "name": "", "visual": "fixed English description", "labels": ["location names used in the scene list"]}}],
  "beats": [{{"n": 1, "summary": "", "characters": ["C1"], "location": "L1", "scenes": [1, 2]}}]
}}
Speaker names from dialogue: {konusmacilar}
Answer with JSON only.

SCENES:
{sahneler}"""


def adim_bible(a):
    liste = oku_json(os.path.join(a.cikti, "cekim_listesi.json"))["shots"]
    sahne_yol = os.path.join(a.cikti, "sahneler.json")
    if os.path.exists(sahne_yol):
        sahneler = oku_json(sahne_yol)["scenes"]
        log(f"[bible] {len(sahneler)} sahne zaten var")
    else:
        sahneler = []
        for bas in range(0, len(liste), a.parca):
            parca = liste[bas:bas + a.parca]
            satirlar = "\n".join(json.dumps({
                "id": s["shot"], "t": f'{s["start_s"]:.0f}-{s["end_s"]:.0f}s', "location": s["location"],
                "characters": s["characters"], "action": s["action"],
                "dialogue": [f'{d["speaker"]}: {d["line"]}' for d in s["dialogue"]]}, ensure_ascii=False)
                for s in parca)
            log(f"[bible] çekim {parca[0]['shot']}-{parca[-1]['shot']} sahnelere ayrılıyor")
            cevap = sohbet(a.llm_url, a.llm_model,
                           [{"role": "user", "content": SAHNE_PROMPT.format(satirlar=satirlar)}],
                           max_tokens=3000)
            sahneler += json_ayikla(cevap).get("scenes", [])
        for i, s in enumerate(sahneler, 1):
            s["scene"] = i
        yaz_json(sahne_yol, {"scenes": sahneler})
        log(f"[bible] {len(sahneler)} sahne -> {sahne_yol}")

    konusmacilar = sorted({d["speaker"] for s in liste for d in s["dialogue"]})
    cevap = sohbet(a.llm_url, a.llm_model, [{"role": "user", "content": BIBLE_PROMPT.format(
        konusmacilar=", ".join(konusmacilar) or "-",
        sahneler=json.dumps(sahneler, ensure_ascii=False))}], max_tokens=6000)
    with open(os.path.join(a.cikti, "bible_ham_cevap.txt"), "w", encoding="utf-8") as f:
        f.write(cevap)
    bible = json_ayikla(cevap)
    # Model bazen {"bible": {...}} gibi sarıyor ya da anahtarları farklı adlandırıyor
    if "characters" not in bible:
        for v in bible.values():
            if isinstance(v, dict) and "characters" in v:
                bible = v
                break
    if not bible.get("characters"):
        log("  UYARI: bible'da karakter yok, modelin ham cevabı: bible_ham_cevap.txt")
    hedef = os.path.join(a.cikti, "bible_taslak.json")
    yaz_json(hedef, bible)
    log(f"[bible] {len(bible.get('characters', []))} karakter, {len(bible.get('locations', []))} mekan, "
        f"{len(bible.get('beats', []))} beat -> {hedef}")


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--cikti", required=True, help="çıktı klasörü")
    p.add_argument("--adim", default="hepsi", help="kes, ses, analiz, birlestir, bible, hepsi ya da virgüllü liste")
    p.add_argument("--esik", type=float, default=27.0, help="PySceneDetect hassasiyeti (düşük = daha çok kesme)")
    p.add_argument("--min-kare", type=int, default=12, help="bir çekim en az kaç kare (24fps'te 12 = 0,5 sn)")
    p.add_argument("--kare-sayisi", type=int, default=4, help="çekim başına modele gönderilecek en fazla kare")
    p.add_argument("--kare-yukseklik", type=int, default=448)
    p.add_argument("--dil", default="tr")
    p.add_argument("--max-konusmaci", type=int, default=None)
    p.add_argument("--ses-python", default="/workspace/venv-ses/bin/python")
    p.add_argument("--vlm-url", default="http://localhost:8000/v1")
    p.add_argument("--vlm-model", default="Qwen/Qwen3-VL-8B-Instruct")
    p.add_argument("--llm-url", default=None, help="bible adımı için (varsayılan: --vlm-url)")
    p.add_argument("--llm-model", default=None, help="bible adımı için (varsayılan: --vlm-model)")
    p.add_argument("--parca", type=int, default=80, help="bible adımında bir istekte kaç çekim")
    p.add_argument("--sinir", type=int, default=0, help="analizde en fazla kaç çekim (deneme için)")
    p.add_argument("--esleme", default=None, help='konuşmacı eşleme JSON, örn. {"SPEAKER_00": "Derin"}')
    a = p.parse_args()
    a.llm_url = a.llm_url or a.vlm_url
    a.llm_model = a.llm_model or a.vlm_model
    if a.esleme is None:
        aday = os.path.join(a.cikti, "konusmaci.json")
        a.esleme = aday if os.path.exists(aday) else None

    adimlar = ADIMLAR if a.adim == "hepsi" else [x.strip() for x in a.adim.split(",")]
    for x in adimlar:
        if x not in ADIMLAR:
            sys.exit(f"Bilinmeyen adım: {x} (seçenekler: {', '.join(ADIMLAR)}, hepsi)")
    if not os.path.exists(a.video):
        sys.exit(f"Video bulunamadı: {a.video}")
    os.makedirs(a.cikti, exist_ok=True)

    for x in adimlar:
        globals()["adim_" + x](a)


if __name__ == "__main__":
    main()
