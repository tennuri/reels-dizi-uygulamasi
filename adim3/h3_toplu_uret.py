"""Çekim listesindeki her çekimi ComfyUI üzerinden MiniMax H3 ile sırayla üretir.

RunPod Web Terminal'de, ComfyUI açıkken çalıştır:

    python3 h3_toplu_uret.py --workflow workflow_api.json \
        --bible bible.json --shots bolum1.json --out bolum1

Sadece bazı çekimleri yeniden üretmek için:  --only 3 9
Aynı sahnedeki çekimleri tek klipte üretmek için (mekan tutarlılığı):  --sahne
Sadece promptları görmek için (üretim yapmadan):  --dry-run
"""

import argparse
import json
import time
import urllib.request
import uuid

COMFY = "http://127.0.0.1:8188"


def join(parts):
    """Parçaları cümle olarak birleştirir; noktası olmayanın sonuna nokta koyar."""
    return " ".join(p if p.rstrip().endswith((".", '"', "!", "?", ":")) else p.rstrip() + "." for p in parts)


def setting_text(loc):
    """Mekan tarifi; varsa eşya yerleşimi ve ortam sesi de eklenir."""
    text = loc["visual"]
    if loc.get("layout"):
        text = join([text, f'Layout: {loc["layout"]}'])
    if loc.get("ambience"):
        text = join([text, f'Ambient sound: {loc["ambience"]}'])
    return text


def speech(d, chars):
    c = chars[d["speaker"]]
    who = f'{c["name"]} (voice: {c["voice"]})' if c.get("voice") else c["name"]
    return f'{who} says in Turkish: "{d["line"]}"'


def series_sound(bible):
    """Bütün klipler için sabit müzik ve ses tasarımı satırları."""
    parts = []
    if bible.get("music"):
        parts.append(f'Music: {bible["music"]}')
    if bible.get("sound"):
        parts.append(f'Sound design: {bible["sound"]}')
    return parts


def h3_prompt(shot, bible):
    chars = {c["id"]: c for c in bible["characters"]}
    locs = {l["id"]: l for l in bible["locations"]}

    parts = [
        f'Shot {shot["shot"]}: {shot["angle"]}, {shot["size"]}, {shot["movement"]}.',
        shot["action"],
    ]
    for cid in shot.get("characters", []):
        parts.append(f'{chars[cid]["name"]}: {chars[cid]["visual"]}')
    parts.append(f'Setting: {setting_text(locs[shot["location"]])}')
    if shot.get("lighting"):
        parts.append(f'Lighting: {shot["lighting"]}')
    if shot.get("dialogue") and shot["dialogue"].get("line"):
        d = shot["dialogue"]
        parts.append(speech(d, chars))
    if shot.get("audio"):
        parts.append(f'Audio: {shot["audio"]}')
    parts.append(f'Style: {bible["style"]}. Vertical 9:16.')
    parts += series_sound(bible)
    parts.append("No text, subtitles, logos or watermarks.")
    return join(parts)


def shot_line(shot, chars):
    line = f'Shot {shot["shot"]}: {shot["angle"]}, {shot["size"]}, {shot["movement"]}. {shot["action"]}'
    if shot.get("dialogue") and shot["dialogue"].get("line"):
        d = shot["dialogue"]
        line += " " + speech(d, chars)
    if shot.get("audio"):
        line += f' Audio: {shot["audio"]}.'
    return line


def h3_scene_prompt(group, bible):
    """Aynı mekandaki birkaç çekimi, H3'ün tek klipte kesme yaptığı storyboard formatında yazar."""
    chars = {c["id"]: c for c in bible["characters"]}
    locs = {l["id"]: l for l in bible["locations"]}
    cids = []
    for shot in group:
        for cid in shot.get("characters", []):
            if cid not in cids:
                cids.append(cid)

    parts = [f'Style: {bible["style"]}. Vertical 9:16.']
    parts += series_sound(bible)
    parts.append(f'Setting (identical in every shot, same furniture and layout): {setting_text(locs[group[0]["location"]])}')
    for cid in cids:
        parts.append(f'{chars[cid]["name"]}: {chars[cid]["visual"]}')
    parts.append("Storyboard (each shot its own angle, clean hard cuts, no dissolves):")
    t = 0
    for shot in group:
        d = shot.get("duration_s", 5)
        parts.append(f"[{t:g}s-{t + d:g}s] " + shot_line(shot, chars))
        t += d
    parts.append("No text, subtitles, logos or watermarks.")
    return join(parts)


def scene_groups(shots, max_s=15):
    """Art arda gelen aynı sahne+mekan çekimlerini, toplamı max_s'yi geçmeyecek şekilde gruplar."""
    groups = []
    for shot in shots:
        g = groups[-1] if groups else None
        if (g and g[-1].get("scene") == shot.get("scene")
                and g[-1]["location"] == shot["location"]
                and sum(s.get("duration_s", 5) for s in g) + shot.get("duration_s", 5) <= max_s):
            g.append(shot)
        else:
            groups.append([shot])
    return groups


def find_inputs(wf, names):
    """(node_id, input_name) çiftleri: adı `names` içinde olan ve değeri sabit olan girişler."""
    hits = []
    for node_id, node in wf.items():
        for key, val in node.get("inputs", {}).items():
            if key in names and not isinstance(val, list):
                hits.append((node_id, key))
    return hits


def find_duration_inputs(wf):
    """H3 şablonunda süre, saniyeyi kareye çeviren bir ComfyMathExpression'a
    bağlı PrimitiveFloat'tır (ör. 'round(a * 24)'). Yoksa ada göre ara."""
    hits = []
    for node in wf.values():
        if node.get("class_type") != "ComfyMathExpression":
            continue
        if "24" not in str(node["inputs"].get("expression", "")):
            continue
        for val in node["inputs"].values():
            if isinstance(val, list) and wf.get(val[0], {}).get("class_type") == "PrimitiveFloat":
                hits.append((val[0], "value"))
    return hits or find_inputs(wf, {"duration", "length_seconds"})


def find_prompt_input(wf):
    """Şablondaki örnek prompt en uzun metin girişidir; onu bul."""
    best, best_len = None, 0
    for node_id, node in wf.items():
        for key, val in node.get("inputs", {}).items():
            if isinstance(val, str) and len(val) > best_len:
                best, best_len = (node_id, key), len(val)
    if best_len < 40:
        raise SystemExit("Workflow'da prompt metni bulunamadı. --prompt-node ile belirt.")
    return best


def post(path, data):
    req = urllib.request.Request(
        COMFY + path, json.dumps(data).encode(), {"Content-Type": "application/json"}
    )
    return json.load(urllib.request.urlopen(req))


def wait_done(prompt_id):
    while True:
        with urllib.request.urlopen(f"{COMFY}/history/{prompt_id}") as r:
            hist = json.load(r)
        if prompt_id in hist:
            status = hist[prompt_id].get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status.get("messages", []))[:2000])
            return
        time.sleep(5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True, help="ComfyUI'dan 'Export (API)' ile alınan JSON")
    ap.add_argument("--bible", required=True, help="Adım 1 çıktısı")
    ap.add_argument("--shots", required=True, help="Adım 3 çıktısı (bir bölüm)")
    ap.add_argument("--out", required=True, help="output/ altındaki klasör adı, ör. bolum1")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--only", type=int, nargs="*", help="sadece bu çekim numaraları")
    ap.add_argument("--prompt-node", help="prompt girişi elle: node_id:input_adi")
    ap.add_argument("--sahne", action="store_true", help="aynı sahnedeki çekimleri tek klipte üret")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    wf_template = json.load(open(args.workflow, encoding="utf-8"))
    bible = json.load(open(args.bible, encoding="utf-8"))
    shots = json.load(open(args.shots, encoding="utf-8"))["shots"]

    if args.prompt_node:
        prompt_at = tuple(args.prompt_node.split(":", 1))
    else:
        prompt_at = find_prompt_input(wf_template)
    duration_at = find_duration_inputs(wf_template)
    seed_at = find_inputs(wf_template, {"seed", "noise_seed"})
    prefix_at = find_inputs(wf_template, {"filename_prefix"})

    print(f"prompt   -> node {prompt_at[0]} ({wf_template[prompt_at[0]]['class_type']})")
    print(f"süre     -> {duration_at or 'BULUNAMADI (şablondaki süre kullanılır)'}")
    print(f"seed     -> {seed_at or 'bulunamadı'}")
    print(f"kayıt    -> {prefix_at or 'BULUNAMADI (dosya adları karışabilir)'}")

    if args.sahne:
        jobs = [(g[0]["shot"], [x["shot"] for x in g], h3_scene_prompt(g, bible),
                 sum(x.get("duration_s", 5) for x in g)) for g in scene_groups(shots)]
    else:
        jobs = [(x["shot"], [x["shot"]], h3_prompt(x, bible), x.get("duration_s", 5)) for x in shots]

    with open(f"{args.out}_promptlar.txt", "w", encoding="utf-8") as log:
        for n, covered, text, dur in jobs:
            if args.only and not set(covered) & set(args.only):
                continue
            label = "Shot " + "+".join(map(str, covered))
            log.write(f"--- {label} ---\n{text}\n\n")
            if args.dry_run:
                print(f"\n--- {label} ({dur:g} sn) ---\n{text}")
                continue

            wf = json.loads(json.dumps(wf_template))
            wf[prompt_at[0]]["inputs"][prompt_at[1]] = text
            for node_id, key in duration_at:
                wf[node_id]["inputs"][key] = float(max(4, min(15, round(dur))))
            for node_id, key in seed_at:
                wf[node_id]["inputs"][key] = args.seed + n
            for node_id, key in prefix_at:
                wf[node_id]["inputs"][key] = f"{args.out}/shot_{n:02d}"

            start = time.time()
            prompt_id = post("/prompt", {"prompt": wf, "client_id": str(uuid.uuid4())})["prompt_id"]
            print(f"{label}: kuyruğa alındı ({prompt_id})", flush=True)
            try:
                wait_done(prompt_id)
                print(f"{label}: bitti, {time.time() - start:.0f} sn", flush=True)
            except RuntimeError as e:
                print(f"{label}: HATA {e}", flush=True)

if __name__ == "__main__":
    main()
