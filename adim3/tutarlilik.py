"""Karakter ve mekan tutarlılığı: sabit referans görseller ve her çekim için başlangıç karesi.

Fikir: H3 her klibi sıfırdan çizdiği için yüzler ve odalar bölümden bölüme değişir.
Bunun yerine her karakterin ve her mekanın BİR KEZ onaylanmış bir görselini tutarız,
her çekimin ilk karesini bu görsellerden bir görüntü düzenleme modeliyle (Qwen-Image-Edit)
kurarız, H3 de klibi bu kareden başlatır. Böylece 1. bölümdeki Derin ile 9. bölümdeki
Derin aynı referanstan gelir.

Alt komutlar (RunPod'da, ComfyUI açıkken, bible.json'un olduğu klasörde):

    durum     Hangi karakterin/mekanın referansı eksik, listeler.
    karakter  Karakter kartı adayları üretir (Qwen-Image, metinden görsel).
    mekan     Boş mekan karesi adayları üretir. Varsayılan kare varsa diğer açıları
              ondan türetir (aynı eşyalar, farklı kamera).
    duzelt    Seçili kartı/kareyi tarif ettiğin yerden düzeltir (ör. tablo, ben, sakal).
    sec       Beğendiğin adayı referans yapar ve bible.json'a yazar.
    kare      Bir bölümün her çekimi için başlangıç karesini kurar
              (mekan karesi + o çekimdeki karakterlerin kartları).

Örnek:

    python3 tutarlilik.py durum --bible bible.json
    python3 tutarlilik.py karakter --bible bible.json --t2i workflow_qwen_t2i_api.json --kim C1 C2 --aday 4
    python3 tutarlilik.py sec --bible bible.json C1 2
    python3 tutarlilik.py mekan --bible bible.json --t2i workflow_qwen_t2i_api.json --kim L1 --aday 4
    python3 tutarlilik.py sec --bible bible.json L1 3
    python3 tutarlilik.py mekan --bible bible.json --edit workflow_qwen_edit_api.json --kim L1 \
        --aci ters --tarif "reverse angle from the window side, looking toward the entrance door"
    python3 tutarlilik.py sec --bible bible.json L1 1 --aci ters
    python3 tutarlilik.py kare --bible bible.json --edit workflow_qwen_edit_api.json --shots bolum1.json --out bolum1
"""

import argparse
import json
import re
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
import uuid

COMFY = "http://127.0.0.1:8188"

# Qwen-Image'ın önerdiği boyutlar
DIKEY = (928, 1664)   # 9:16, mekan ve çekim kareleri
YATAY = (1664, 928)   # 16:9, karakter kartı (üç görünüş yan yana)

NEG_PEOPLE = ("No people, no characters, no portraits or photographs of people on the walls "
              "(wall art shows only landscapes or still lifes), no text, no logos, no watermark.")


# ---------- ComfyUI ----------

def post(path, data):
    req = urllib.request.Request(COMFY + path, json.dumps(data).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def upload_image(path):
    """Görseli ComfyUI'ın input klasörüne yükler, LoadImage'a yazılacak adı döndürür."""
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        data = f.read()
    # Aynı adlı farklı dosyalar (ör. iki bölümün shot_01.png'si) karışmasın diye ada klasörü ekle
    name = "_".join(os.path.normpath(path).split(os.sep)[-3:])
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
        f"filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(COMFY + "/upload/image", body,
                                 {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    res = json.load(urllib.request.urlopen(req))
    return f'{res["subfolder"]}/{res["name"]}' if res.get("subfolder") else res["name"]


def run_and_fetch(wf, dest):
    """Workflow'u çalıştırır, çıkan ilk görseli `dest` yoluna indirir."""
    prompt_id = post("/prompt", {"prompt": wf, "client_id": str(uuid.uuid4())})["prompt_id"]
    while True:
        with urllib.request.urlopen(f"{COMFY}/history/{prompt_id}") as r:
            hist = json.load(r)
        if prompt_id in hist:
            break
        time.sleep(2)
    h = hist[prompt_id]
    if h.get("status", {}).get("status_str") == "error":
        raise RuntimeError(json.dumps(h["status"].get("messages", []))[:2000])
    for out in h.get("outputs", {}).values():
        for img in out.get("images", []):
            if img.get("type", "output") != "output":
                continue
            q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                        "type": "output"})
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with urllib.request.urlopen(f"{COMFY}/view?{q}") as r, open(dest, "wb") as f:
                f.write(r.read())
            return dest
    raise RuntimeError("Workflow görsel üretmedi (SaveImage düğümü var mı?)")


# ---------- Şablonda girişleri bulma ----------

def links(node):
    return [(k, v) for k, v in node.get("inputs", {}).items() if isinstance(v, list) and len(v) == 2]


def upstream(wf, start_id, want):
    """start_id'den geriye doğru ilk `want(node_id, node)` koşulunu sağlayan düğüm."""
    seen, queue = set(), [start_id]
    while queue:
        nid = queue.pop(0)
        if nid in seen or nid not in wf:
            continue
        seen.add(nid)
        if want(nid, wf[nid]):
            return nid
        queue += [v[0] for _, v in links(wf[nid])]
    return None


def has_text(_, node):
    return any(k in ("prompt", "text") and isinstance(v, str) for k, v in node.get("inputs", {}).items())


def locate(wf, path, need_images=False):
    """Pozitif prompt, seed, boyut, kayıt ve (düzenleme şablonunda) görsel girişlerini bulur."""
    at = {"prompt": None, "seed": [], "size": [], "prefix": [], "images": []}
    for nid, node in wf.items():
        inp = node.get("inputs", {})
        if "positive" in inp and isinstance(inp["positive"], list) and not at["prompt"]:
            enc = upstream(wf, inp["positive"][0], has_text)
            if enc:
                key = "prompt" if isinstance(wf[enc]["inputs"].get("prompt"), str) else "text"
                at["prompt"] = (enc, key)
        for k in ("seed", "noise_seed"):
            if k in inp and not isinstance(inp[k], list):
                at["seed"].append((nid, k))
        if "width" in inp and "height" in inp and "Latent" in node.get("class_type", ""):
            at["size"].append(nid)
        if "filename_prefix" in inp:
            at["prefix"].append(nid)

    if at["prompt"]:
        enc = wf[at["prompt"][0]]
        slots = sorted((k for k, v in links(enc) if k.startswith("image")), key=lambda k: (len(k), k))
        for k in slots:
            li = upstream(wf, enc["inputs"][k][0], lambda _, n: n.get("class_type") == "LoadImage")
            if li and li not in at["images"]:
                at["images"].append(li)
    if need_images and not at["images"]:
        at["images"] = sorted((nid for nid, n in wf.items() if n.get("class_type") == "LoadImage"), key=int_or_str)

    print(f"[{path}]")
    print(f"  prompt -> {at['prompt'] or 'BULUNAMADI'}")
    print(f"  seed   -> {at['seed'] or 'bulunamadı'}")
    if not need_images:
        print(f"  boyut  -> {at['size'] or 'bulunamadı (şablondaki boyut kullanılır)'}")
    else:
        print(f"  görsel -> {at['images'] or 'BULUNAMADI'} (sırasıyla image1, image2, ...)")
    if not at["prompt"]:
        raise SystemExit("Pozitif prompt bulunamadı. Bu satırları gönder, betiği şablona göre ayarlayalım.")
    if need_images and not at["images"]:
        raise SystemExit("Düzenleme şablonunda Load Image düğümü yok.")
    return at


def int_or_str(x):
    return (0, int(x)) if str(x).isdigit() else (1, str(x))


def fill(wf_template, at, prompt, seed, prefix, size=None, images=()):
    wf = json.loads(json.dumps(wf_template))
    wf[at["prompt"][0]]["inputs"][at["prompt"][1]] = prompt
    for nid, k in at["seed"]:
        wf[nid]["inputs"][k] = seed
    for nid in at["prefix"]:
        wf[nid]["inputs"]["filename_prefix"] = prefix
    if size:
        for nid in at["size"]:
            wf[nid]["inputs"]["width"], wf[nid]["inputs"]["height"] = size
    images = list(images)
    if images:  # boş kalan Load Image yuvalarını doldur, şablon eksik dosyayla hata vermesin.
        # Son görseli (karakter kartı) tekrarla: mekan karesi iki yuvada olunca model odanın
        # geniş planına kilitleniyor, istenen açı ve poz tutmuyor.
        images += [images[-1]] * (len(at["images"]) - len(images))
    for nid, name in zip(at["images"], images):
        wf[nid]["inputs"]["image"] = name
    return wf


# ---------- Bible ----------

def load_bible(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_bible(path, bible):
    shutil.copy(path, path + ".yedek")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bible, f, ensure_ascii=False, indent=2)
        f.write("\n")


def by_id(bible):
    return {c["id"]: c for c in bible["characters"]}, {l["id"]: l for l in bible["locations"]}


def sentence(p):
    p = p.strip()
    return p if p.endswith((".", "!", "?", '"')) else p + "."


def photo_visual(text):
    """Kart için tarifteki rakamları kelimeye çevirir: model "55 years / 175 cm" gibi
    rakamları görselin üstüne etiket olarak yazıyor."""
    def age(m):
        n = int(m.group(1))
        tens = {2: "twenties", 3: "thirties", 4: "forties", 5: "fifties", 6: "sixties", 7: "seventies"}.get(n // 10)
        if not tens:
            return "adult"
        part = "early" if n % 10 <= 3 else "mid" if n % 10 <= 6 else "late"
        return f"in {'his' if 'man' in text.lower().split(',')[0] and 'woman' not in text.lower().split(',')[0] else 'her'} {part} {tens}"
    text = re.sub(r"(\d+) years old", age, text)
    text = re.sub(r"\s*\(about [^)]*\)", "", text)
    text = re.sub(r"\b\d+\s*cm tall,?\s*", "", text)
    return text


def sheet_prompt(c, bible):
    # "character sheet" ifadesi modeli 3D render + yazılı tasarım sayfasına itiyor, kullanma
    return " ".join([
        "Studio photograph, shot on a full-frame DSLR with an 85mm lens: three photos side by side "
        "of the same real person against a seamless plain light-grey backdrop: front view, "
        "three-quarter view and side profile, full body head to shoes.",
        sentence(photo_visual(c["visual"])),
        "Same person, same outfit and hairstyle in all three photos; neutral relaxed expression.",
        "Natural skin texture with pores, realistic fabric, soft even studio light, fashion lookbook photography.",
    ])


def plate_prompt(l, bible):
    parts = [f'Empty {l["name"]}.', sentence(l["visual"])]
    if l.get("layout"):
        parts.append("Layout: " + sentence(l["layout"]))
    parts += [
        "Wide establishing shot, eye-level camera, the whole room visible, every piece of furniture clearly readable.",
        f'Style: {sentence(bible["style"])}',
        "Vertical 9:16 film still, photorealistic.",
        NEG_PEOPLE,
    ]
    return " ".join(parts)


def angle_prompt(l, tarif):
    parts = [
        f'Same room as image 1 ({l["name"]}): keep every wall, window, piece of furniture, color, '
        "material and object exactly as in image 1, only the camera moves.",
        f"New camera: {sentence(tarif)}",
    ]
    if l.get("layout"):
        parts.append("Room layout for reference: " + sentence(l["layout"]))
    parts += ["Vertical 9:16 film still, photorealistic.", NEG_PEOPLE]
    return " ".join(parts)


def keyframe_prompt(shot, chars, loc, slots):
    """slots: [(görsel_no, [karakter, ...]), ...]"""
    parts = [
        f'Image 1 is the room ({loc["name"]}). Keep the room exactly as in image 1: same walls, window, '
        "furniture, positions, colors and materials. Do not add, remove or move furniture.",
    ]
    for no, group in slots:
        if len(group) == 1:
            parts.append(f'{group[0]["name"]} is the person in image {no}: keep exactly the same face, '
                         "hairstyle, body and outfit.")
        else:
            names = ", ".join(c["name"] for c in group)
            parts.append(f"Image {no} shows, from left to right: {names}. Keep each one's face, hairstyle, "
                         "body and outfit exactly.")
    parts.append(f'Camera: {shot["angle"]}, {shot["size"]}.')
    parts.append("Moment: the very first instant of this action: " + sentence(shot["action"]))
    if shot.get("lighting"):
        parts.append("Lighting: " + sentence(shot["lighting"]))
    for c in (c for _, g in slots for c in g):
        parts.append(f'{c["name"]}: {sentence(c["visual"])}')
    parts.append("Photorealistic vertical 9:16 film still, natural skin texture, cinematic depth of field. "
                 "Only the listed people are in the frame. No text, no logos, no watermark.")
    return " ".join(parts)


def stitch(paths, dest):
    """Fazla karakter kartını yan yana tek görsele birleştirir (son görsel yuvasına sığsın diye)."""
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("3'ten fazla kişili çekimler için Pillow gerekli: pip install pillow")
    ims = [Image.open(p).convert("RGB") for p in paths]
    h = min(i.height for i in ims)
    ims = [i.resize((round(i.width * h / i.height), h)) for i in ims]
    out = Image.new("RGB", (sum(i.width for i in ims), h), "white")
    x = 0
    for i in ims:
        out.paste(i, (x, 0))
        x += i.width
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    out.save(dest)
    return dest


# ---------- Komutlar ----------

def cmd_durum(a, bible, bdir):
    chars, locs = by_id(bible)
    print("KARAKTERLER")
    for c in chars.values():
        p = c.get("sheet")
        ok = p and os.path.exists(os.path.join(bdir, p))
        print(f'  {c["id"]:4} {"tamam " if ok else "EKSİK "} {c["name"]}' + (f"  ({p})" if p else ""))
    print("MEKANLAR")
    for l in locs.values():
        refs = l.get("refs", {})
        ok = refs.get("default") and os.path.exists(os.path.join(bdir, refs["default"]))
        extra = ", ".join(k for k in refs if k != "default")
        print(f'  {l["id"]:4} {"tamam " if ok else "EKSİK "} {l["name"]}' + (f"  (+ {extra})" if extra else ""))


def cmd_karakter(a, bible, bdir):
    chars, _ = by_id(bible)
    wf = json.load(open(a.t2i, encoding="utf-8"))
    at = locate(wf, a.t2i)
    for cid in a.kim or list(chars):
        c = chars[cid]
        text = sheet_prompt(c, bible)
        for i in range(1, a.aday + 1):
            dest = os.path.join(bdir, "refs", "adaylar", f"{cid}_{i}.png")
            if a.dry_run:
                print(f"\n--- {cid} aday {i} ---\n{text}")
                break
            run_and_fetch(fill(wf, at, text, a.seed + i, f"adaylar/{cid}", size=YATAY), dest)
            print(f"{cid} aday {i}: {dest}", flush=True)


def cmd_mekan(a, bible, bdir):
    _, locs = by_id(bible)
    aci = a.aci or "default"
    if aci != "default" and not a.tarif:
        raise SystemExit("--aci ile yeni açı isterken --tarif ile kameranın nereye baktığını yaz (İngilizce).")
    wf_t2i = json.load(open(a.t2i, encoding="utf-8")) if a.t2i else None
    wf_edit = json.load(open(a.edit, encoding="utf-8")) if a.edit else None
    at_t2i = locate(wf_t2i, a.t2i) if wf_t2i else None
    at_edit = locate(wf_edit, a.edit, need_images=True) if wf_edit else None

    for lid in a.kim or list(locs):
        l = locs[lid]
        base = l.get("refs", {}).get("default")
        base = os.path.join(bdir, base) if base else None
        derive = aci != "default" and base and os.path.exists(base)
        if derive and not wf_edit:
            raise SystemExit("Yeni açıyı varsayılan kareden türetmek için --edit şablonu ver.")
        if not derive and not wf_t2i:
            raise SystemExit(f"{lid}: türetilecek varsayılan kare yok, --t2i şablonu ver.")
        text = angle_prompt(l, a.tarif) if derive else plate_prompt(l, bible)
        if not derive and aci != "default":
            text = text.replace("Wide establishing shot, eye-level camera", f"Camera: {a.tarif}")
        for i in range(1, a.aday + 1):
            dest = os.path.join(bdir, "refs", "adaylar", f"{lid}_{aci}_{i}.png")
            if a.dry_run:
                print(f"\n--- {lid} {aci} ({'varsayılandan' if derive else 'metinden'}) ---\n{text}")
                break
            if derive:
                wf = fill(wf_edit, at_edit, text, a.seed + i, f"adaylar/{lid}", images=[upload_image(base)])
            else:
                wf = fill(wf_t2i, at_t2i, text, a.seed + i, f"adaylar/{lid}", size=DIKEY)
            run_and_fetch(wf, dest)
            print(f"{lid} {aci} aday {i}: {dest}", flush=True)


def cmd_duzelt(a, bible, bdir):
    """Seçili referans görseli (karakter kartı ya da mekan karesi) tarif edilen yerden düzeltir."""
    chars, locs = by_id(bible)
    aci = a.aci or "default"
    if a.id in chars:
        rel = chars[a.id].get("sheet")
        name = lambda i: f"{a.id}_{i}.png"
        keep = "the same person, face, hairstyle, body, outfit, poses, background and lighting"
    elif a.id in locs:
        rel = locs[a.id].get("refs", {}).get(aci)
        name = lambda i: f"{a.id}_{aci}_{i}.png"
        keep = "the same camera, framing, lighting, walls, window and every other piece of furniture"
    else:
        raise SystemExit(f"{a.id} bible'da yok.")
    if not rel:
        raise SystemExit(f"{a.id} için önce bir referans seç (sec).")
    src = os.path.join(bdir, rel)
    text = f"Edit image 1: {sentence(a.tarif)} Change nothing else: keep {keep} exactly as in image 1."
    if a.id in locs:
        text += " " + NEG_PEOPLE
    wf = json.load(open(a.edit, encoding="utf-8"))
    at = locate(wf, a.edit, need_images=True)
    if a.dry_run:
        print(f"\n--- {a.id} ({rel}) ---\n{text}")
        return
    up = upload_image(src)
    for i in range(1, a.aday + 1):
        dest = os.path.join(bdir, "refs", "adaylar", name(i))
        run_and_fetch(fill(wf, at, text, a.seed + i, f"adaylar/{a.id}", images=[up]), dest)
        print(f"{a.id} düzeltme adayı {i}: {dest}", flush=True)
    print(f"Beğendiğini 'sec {a.id} N" + (f" --aci {aci}'" if a.id in locs and aci != "default" else "'") + " ile seç.")


def cmd_sec(a, bible, bdir, bible_path):
    chars, locs = by_id(bible)
    if a.id in chars:
        src = os.path.join(bdir, "refs", "adaylar", f"{a.id}_{a.no}.png")
        rel = f"refs/karakter/{a.id}.png"
    elif a.id in locs:
        aci = a.aci or "default"
        src = os.path.join(bdir, "refs", "adaylar", f"{a.id}_{aci}_{a.no}.png")
        rel = f"refs/mekan/{a.id}_{aci}.png"
    else:
        raise SystemExit(f"{a.id} bible'da yok.")
    if not os.path.exists(src):
        raise SystemExit(f"{src} yok.")
    os.makedirs(os.path.join(bdir, os.path.dirname(rel)), exist_ok=True)
    shutil.copy(src, os.path.join(bdir, rel))
    if a.id in chars:
        chars[a.id]["sheet"] = rel
    else:
        locs[a.id].setdefault("refs", {})[a.aci or "default"] = rel
    save_bible(bible_path, bible)
    print(f"{a.id}: {rel} referans yapıldı, bible.json güncellendi (eski hali bible.json.yedek).")


def cmd_kare(a, bible, bdir):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from h3_toplu_uret import scene_groups

    chars, locs = by_id(bible)
    wf = json.load(open(a.edit, encoding="utf-8"))
    at = locate(wf, a.edit, need_images=True)
    n_slots = len(at["images"])
    shots = json.load(open(a.shots, encoding="utf-8"))["shots"]
    if a.sahne:
        # grup tek klip olacağı için ilk karede grubun bütün karakterleri olsun
        lead = []
        for g in scene_groups(shots):
            cast = []
            for x in g:
                cast += [c for c in x.get("characters", []) if c not in cast]
            lead.append(dict(g[0], characters=cast))
    else:
        lead = shots
    outdir = os.path.join(bdir, "kareler", a.out)
    missing = set()

    for shot in lead:
        n = shot["shot"]
        if a.only and n not in a.only:
            continue
        dest = os.path.join(outdir, f"shot_{n:02d}.png")
        if os.path.exists(dest) and not a.yeniden:
            print(f"Shot {n}: kare zaten var, atlandı (yeniden üretmek için --yeniden)")
            continue
        loc = locs[shot["location"]]
        plate = loc.get("refs", {}).get(shot.get("ref", "default")) or loc.get("refs", {}).get("default")
        if not plate:
            print(f"Shot {n}: {loc['id']} için mekan karesi yok, atlandı")
            missing.add(loc["id"])
            continue
        cast = [chars[cid] for cid in shot.get("characters", [])]
        no_sheet = [c["id"] for c in cast if not c.get("sheet")]
        if no_sheet:
            print(f"Shot {n}: {', '.join(no_sheet)} için karakter kartı yok, atlandı")
            missing.update(no_sheet)
            continue

        # image1 = mekan; image2.. = karakterler; yuva yetmezse kalanlar son yuvada yan yana
        files = [os.path.join(bdir, plate)]
        slots = []
        free = n_slots - 1
        if cast and free < 1:
            raise SystemExit("Düzenleme şablonunda en az 2 Load Image olmalı (mekan + karakter).")
        for i, c in enumerate(cast):
            if i < free - 1 or len(cast) <= free:
                files.append(os.path.join(bdir, c["sheet"]))
                slots.append((len(files), [c]))
            else:
                rest = cast[i:]
                files.append(stitch([os.path.join(bdir, r["sheet"]) for r in rest],
                                    os.path.join(outdir, "_birlesik", f"shot_{n:02d}.png")) if not a.dry_run
                             else "(birleşik)")
                slots.append((len(files), rest))
                break

        text = keyframe_prompt(shot, chars, loc, slots) if cast else None
        if a.dry_run:
            print(f"\n--- Shot {n} | görseller: {files} ---\n{text or '(kişisiz çekim: mekan karesi aynen kullanılır)'}")
            continue
        if not cast:
            os.makedirs(outdir, exist_ok=True)
            shutil.copy(files[0], dest)
            print(f"Shot {n}: kişisiz çekim, mekan karesi kopyalandı", flush=True)
            continue
        start = time.time()
        names = [upload_image(p) for p in files]
        try:
            run_and_fetch(fill(wf, at, text, a.seed + n, f"kareler/{a.out}/shot_{n:02d}", images=names), dest)
            print(f"Shot {n}: {dest} ({time.time() - start:.0f} sn)", flush=True)
        except RuntimeError as e:
            print(f"Shot {n}: HATA {e}", flush=True)

    if missing:
        print("\nEksik referanslar: " + ", ".join(sorted(missing)) + "  ->  önce 'karakter' / 'mekan' + 'sec' çalıştır.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--bible", required=True)
        p.add_argument("--seed", type=int, default=100)
        p.add_argument("--dry-run", action="store_true", help="üretmeden promptları yaz")
        return p

    common(sub.add_parser("durum"))
    p = common(sub.add_parser("karakter"))
    p.add_argument("--t2i", required=True, help="Qwen-Image (metinden görsel) şablonu, Export (API)")
    p.add_argument("--kim", nargs="*", help="karakter id'leri (boşsa hepsi)")
    p.add_argument("--aday", type=int, default=4)
    p = common(sub.add_parser("mekan"))
    p.add_argument("--t2i", help="Qwen-Image şablonu (varsayılan kare için)")
    p.add_argument("--edit", help="Qwen-Image-Edit şablonu (yeni açıyı varsayılan kareden türetmek için)")
    p.add_argument("--kim", nargs="*", help="mekan id'leri (boşsa hepsi)")
    p.add_argument("--aci", help="açı adı, ör. ters, kapi (boşsa default)")
    p.add_argument("--tarif", help="yeni açıda kameranın nereye baktığı (İngilizce)")
    p.add_argument("--aday", type=int, default=4)
    p = common(sub.add_parser("duzelt"))
    p.add_argument("id", help="C1, L1 ...")
    p.add_argument("--edit", required=True, help="Qwen-Image-Edit şablonu")
    p.add_argument("--tarif", required=True, help="ne değişecek (İngilizce)")
    p.add_argument("--aci", help="mekan açısı (boşsa default)")
    p.add_argument("--aday", type=int, default=3)
    p = common(sub.add_parser("sec"))
    p.add_argument("id", help="C1, L1 ...")
    p.add_argument("no", type=int, help="aday numarası")
    p.add_argument("--aci", help="mekan açısı (boşsa default)")
    p = common(sub.add_parser("kare"))
    p.add_argument("--edit", required=True, help="Qwen-Image-Edit şablonu, 3 Load Image bağlı")
    p.add_argument("--shots", required=True)
    p.add_argument("--out", required=True, help="ör. bolum1 -> kareler/bolum1/shot_01.png")
    p.add_argument("--only", type=int, nargs="*")
    p.add_argument("--sahne", action="store_true", help="h3_toplu_uret --sahne ile aynı gruplar: grup başına bir kare")
    p.add_argument("--yeniden", action="store_true", help="var olan kareleri de yeniden üret")

    a = ap.parse_args()
    bible = load_bible(a.bible)
    bdir = os.path.dirname(os.path.abspath(a.bible))
    if a.cmd == "durum":
        cmd_durum(a, bible, bdir)
    elif a.cmd == "karakter":
        cmd_karakter(a, bible, bdir)
    elif a.cmd == "mekan":
        cmd_mekan(a, bible, bdir)
    elif a.cmd == "duzelt":
        cmd_duzelt(a, bible, bdir)
    elif a.cmd == "sec":
        cmd_sec(a, bible, bdir, a.bible)
    elif a.cmd == "kare":
        cmd_kare(a, bible, bdir)


if __name__ == "__main__":
    main()
