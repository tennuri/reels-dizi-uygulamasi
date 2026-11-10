"""Qwen-Image ve Qwen-Image-Edit modellerini indirir, tutarlilik.py'nin kullandığı iki
ComfyUI şablonunu (API formatında) kendisi yazar. ComfyUI'da şablon aramana gerek kalmaz.

RunPod Web Terminal'de, ComfyUI açıkken, /workspace/dizi içinde:

    python3 qwen_kurulum.py

Çıktı: workflow_qwen_t2i_api.json ve workflow_qwen_edit_api.json (bulunduğun klasöre).
Modeller (~45 GB) ComfyUI'ın models/ klasörüne iner; varsa tekrar inmez.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.request

COMFY = "http://127.0.0.1:8188"

# (hf deposu, klasör, dosya seçme kuralı)
MODELS = {
    "t2i_unet": ("Comfy-Org/Qwen-Image_ComfyUI", "diffusion_models",
                 lambda p: "diffusion_models/" in p and "qwen_image_fp8" in p and "edit" not in p.lower()
                 and "distill" not in p.lower()),
    "edit_unet": ("Comfy-Org/Qwen-Image-Edit_ComfyUI", "diffusion_models",
                  lambda p: "diffusion_models/" in p and "2509" in p and "fp8" in p),
    "te": ("Comfy-Org/Qwen-Image_ComfyUI", "text_encoders",
           lambda p: "text_encoders/" in p and "qwen_2.5_vl_7b_fp8" in p),
    "vae": ("Comfy-Org/Qwen-Image_ComfyUI", "vae", lambda p: p.endswith("vae/qwen_image_vae.safetensors")),
    "t2i_lora": ("lightx2v/Qwen-Image-Lightning", "loras",
                 lambda p: "edit" not in p.lower() and "8steps" in p and "/" not in p),
    "edit_lora": ("lightx2v/Qwen-Image-Lightning", "loras",
                  lambda p: "Edit-2509" in p and "8steps" in p),
}
OPTIONAL = {"t2i_lora", "edit_lora"}


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def running_comfy_dir():
    """Çalışan ComfyUI sürecinin klasörü (pod'da birden fazla ComfyUI kopyası olabiliyor)."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            args = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            continue
        for arg in args:
            arg = arg.decode(errors="ignore")
            if arg.endswith("main.py"):
                d = os.path.dirname(os.path.join(cwd, arg))
                if os.path.isdir(os.path.join(d, "models")):
                    return d
    return None


def comfy_dir():
    d = running_comfy_dir()
    if d:
        return d
    res = subprocess.run(["find", "/workspace", "/", "-maxdepth", "4", "-type", "d", "-name", "custom_nodes"],
                         capture_output=True, text=True)
    hits = [os.path.dirname(p) for p in res.stdout.split()
            if os.path.isdir(os.path.join(os.path.dirname(p), "models"))]
    if not hits:
        raise SystemExit("ComfyUI klasörü bulunamadı. --comfy-dir /yol/ComfyUI ile ver.")
    return sorted(set(hits), key=len)[0]


def pick(repo, rule):
    files = [s["rfilename"] for s in get_json(f"https://huggingface.co/api/models/{repo}")["siblings"]]
    cands = sorted(p for p in files if p.endswith(".safetensors") and rule(p))
    return cands[-1] if cands else None  # en yeni sürüm adı genelde alfabetik olarak sonda


def download(key, comfy, skip_lora):
    repo, folder, rule = MODELS[key]
    if key in OPTIONAL and skip_lora:
        return None
    try:
        path = pick(repo, rule)
    except Exception as e:
        if key in OPTIONAL:
            print(f"  {key}: liste alınamadı ({e}), LoRA'sız devam")
            return None
        raise SystemExit(f"{repo} dosya listesi alınamadı: {e}")
    if not path:
        if key in OPTIONAL:
            print(f"  {key}: uygun dosya yok, LoRA'sız devam")
            return None
        raise SystemExit(f"{repo} içinde {key} için dosya bulunamadı. Bu satırı gönder.")
    name = os.path.basename(path)
    dest = os.path.join(comfy, "models", folder, name)
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        print(f"  {name}: zaten var")
        return name
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print(f"  {name}: iniyor -> {dest}", flush=True)
    url = f"https://huggingface.co/{repo}/resolve/main/{path}"
    tmp = dest + ".part"
    subprocess.run(["curl", "-L", "--fail", "-C", "-", "-o", tmp, url], check=True)
    os.rename(tmp, dest)
    return name


def fill_defaults(wf, info):
    """object_info'ya göre şablonda eksik kalan zorunlu girişlere varsayılan değer yazar
    (ComfyUI sürümleri arasında düğümlere yeni ayar eklenebiliyor)."""
    for nid, node in wf.items():
        spec = info.get(node["class_type"], {}).get("input", {}).get("required", {})
        for k, v in spec.items():
            if k in node["inputs"]:
                continue
            if isinstance(v, list) and len(v) > 1 and isinstance(v[1], dict) and "default" in v[1]:
                node["inputs"][k] = v[1]["default"]
            elif isinstance(v, list) and isinstance(v[0], list) and v[0]:
                node["inputs"][k] = v[0][0]


def loaders(unet, te, vae, lora):
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": te, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": vae}},
    }
    model = ["1", 0]
    if lora:
        wf["4"] = {"class_type": "LoraLoaderModelOnly",
                   "inputs": {"model": model, "lora_name": lora, "strength_model": 1.0}}
        model = ["4", 0]
    wf["5"] = {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": model, "shift": 3.1}}
    return wf


def sampler(positive, negative, latent, lora):
    steps, cfg = (8, 1.0) if lora else (30, 2.5)
    return {"class_type": "KSampler", "inputs": {
        "model": ["5", 0], "seed": 1, "steps": steps, "cfg": cfg, "sampler_name": "euler",
        "scheduler": "simple", "positive": positive, "negative": negative, "latent_image": latent,
        "denoise": 1.0}}


def t2i_workflow(unet, te, vae, lora):
    wf = loaders(unet, te, vae, lora)
    wf.update({
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "placeholder prompt", "clip": ["2", 0]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 928, "height": 1664, "batch_size": 1}},
        "9": sampler(["6", 0], ["7", 0], ["8", 0], lora),
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"filename_prefix": "qwen", "images": ["10", 0]}},
    })
    return wf


def edit_workflow(unet, te, vae, lora):
    wf = loaders(unet, te, vae, lora)
    enc = {"clip": ["2", 0], "vae": ["3", 0]}
    wf.update({
        "20": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "21": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "22": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
        "23": {"class_type": "ImageScaleToTotalPixels",
               "inputs": {"image": ["20", 0], "upscale_method": "lanczos", "megapixels": 1.0}},
        "24": {"class_type": "TextEncodeQwenImageEditPlus",
               "inputs": dict(enc, prompt="placeholder prompt", image1=["23", 0], image2=["21", 0], image3=["22", 0])},
        "25": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": dict(enc, prompt="", image1=["23", 0])},
        "26": {"class_type": "VAEEncode", "inputs": {"pixels": ["23", 0], "vae": ["3", 0]}},
        "27": sampler(["24", 0], ["25", 0], ["26", 0], lora),
        "28": {"class_type": "VAEDecode", "inputs": {"samples": ["27", 0], "vae": ["3", 0]}},
        "29": {"class_type": "SaveImage", "inputs": {"filename_prefix": "qwen_edit", "images": ["28", 0]}},
    })
    return wf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy-dir", help="ComfyUI klasörü (bulunamazsa)")
    ap.add_argument("--lorasiz", action="store_true", help="Lightning LoRA'sını indirme (daha yavaş, 30 adım)")
    a = ap.parse_args()

    try:
        info = get_json(f"{COMFY}/object_info")
    except Exception as e:
        raise SystemExit(f"ComfyUI'a ulaşılamadı ({e}). ComfyUI açık mı?")
    need = ["UNETLoader", "CLIPLoader", "ModelSamplingAuraFlow", "EmptySD3LatentImage",
            "TextEncodeQwenImageEditPlus", "ImageScaleToTotalPixels", "LoraLoaderModelOnly"]
    missing = [n for n in need if n not in info]
    if missing:
        raise SystemExit(f"ComfyUI bu düğümleri tanımıyor: {missing}. ComfyUI'ı güncellemek gerekiyor, bu satırı gönder.")
    clip_types = info["CLIPLoader"]["input"]["required"]["type"][0]
    if "qwen_image" not in clip_types:
        raise SystemExit(f"CLIPLoader'da qwen_image tipi yok ({clip_types}). ComfyUI'ı güncellemek gerekiyor.")

    comfy = a.comfy_dir or comfy_dir()
    print(f"ComfyUI: {comfy}\nModeller:")
    m = {k: download(k, comfy, a.lorasiz) for k in MODELS}

    out = {
        "workflow_qwen_t2i_api.json": t2i_workflow(m["t2i_unet"], m["te"], m["vae"], m["t2i_lora"]),
        "workflow_qwen_edit_api.json": edit_workflow(m["edit_unet"], m["te"], m["vae"], m["edit_lora"]),
    }
    info = get_json(f"{COMFY}/object_info")  # yeni inen dosyalar listeye girsin
    for name, wf in out.items():
        fill_defaults(wf, info)
        with open(name, "w", encoding="utf-8") as f:
            json.dump(wf, f, indent=2)
        print(f"yazıldı: {name}")
    for k in ("t2i_unet", "edit_unet"):
        listed = info["UNETLoader"]["input"]["required"]["unet_name"][0]
        if m[k] not in listed:
            print(f"UYARI: ComfyUI {m[k]} dosyasını henüz görmüyor. ComfyUI'ı yeniden başlatman gerekebilir.")
    print("\nHazır. Sıradaki komut:\n  python3 tutarlilik.py karakter --bible bible.json "
          "--t2i workflow_qwen_t2i_api.json --kim C1 C2 --aday 4")


if __name__ == "__main__":
    sys.exit(main())
