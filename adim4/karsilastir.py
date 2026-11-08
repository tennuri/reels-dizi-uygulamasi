#!/usr/bin/env python3
"""Orijinal çekimleri ve H3 ile üretilenleri yan yana tek bir videoda gösterir.

    python3 karsilastir.py /root/videolar/bolum1.mp4 /root/analiz/bolum1 \
        /workspace/runpod-slim/ComfyUI/output/deneme1 karsilastirma.mp4 --cekimler 1-9

Sol: orijinal (16:9), sağ: H3 klibi (9:16). Her H3 klibi orijinal çekimin süresine
kırpılır, böylece kurgu temposu aynı kalır. Üretilmemiş çekimin yerinde siyah kare durur.
Ses varsayılan olarak orijinalden gelir (--ses h3 ile H3'ün sesi).
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

Y = 720            # panel yüksekliği
SOL_G = 1280       # orijinal panel genişliği (16:9)
SAG_G = 406        # H3 panel genişliği (9:16, çift sayı)


def calistir(komut):
    r = subprocess.run(komut, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg hatası:\n{' '.join(komut)}\n{r.stderr[-1500:]}")


def yazi_var():
    r = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], stdout=subprocess.PIPE, text=True)
    return " drawtext " in r.stdout


def aralik(metin):
    secim = set()
    for parca in metin.split(","):
        if "-" in parca:
            a, b = parca.split("-")
            secim |= set(range(int(a), int(b) + 1))
        elif parca:
            secim.add(int(parca))
    return secim


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("orijinal", help="orijinal bölüm videosu")
    p.add_argument("analiz", help="diziden_senaryo.py çıktı klasörü")
    p.add_argument("uretilen", help="H3 kliplerinin klasörü (shot_01_*.mp4 ...)")
    p.add_argument("cikti", help="karşılaştırma videosu, örn. karsilastirma.mp4")
    p.add_argument("--cekimler", default="", help="örn. 1-9 (varsayılan: üretilmiş klibi olan çekimler)")
    p.add_argument("--ses", choices=["orijinal", "h3"], default="orijinal")
    p.add_argument("--sahne", action="store_true",
                   help="klipler h3_toplu_uret.py --sahne ile üretildiyse: her klip birden çok çekimi kapsar")
    a = p.parse_args()

    cekimler = json.load(open(os.path.join(a.analiz, "cekim_listesi.json"), encoding="utf-8"))["shots"]

    def klip(n):
        bul = sorted(glob.glob(os.path.join(a.uretilen, f"shot_{n:02d}*.mp4")))
        return bul[-1] if bul else None

    if a.cekimler:
        secili = aralik(a.cekimler)
    else:
        secili = {c["shot"] for c in cekimler if klip(c["shot"])}
    if not secili:
        sys.exit(f"{a.uretilen} içinde shot_XX*.mp4 bulunamadı; --cekimler ile aralık ver")

    etiket = yazi_var()
    gecici = tempfile.mkdtemp(prefix="karsilastir_")
    parcalar = []
    secilen = [c for c in cekimler if c["shot"] in secili]
    if a.sahne:
        # --sahne ile üretilen her klip, ilk çekiminden bir sonraki klibin başladığı çekime kadar uzanır
        bolumler = []
        uretilmis = [i for i, c in enumerate(secilen) if klip(c["shot"])]
        for j, i in enumerate(uretilmis):
            son = (uretilmis[j + 1] - 1) if j + 1 < len(uretilmis) else len(secilen) - 1
            bolumler.append((secilen[i]["shot"], secilen[son]["shot"], secilen[i]["start_s"], secilen[son]["end_s"]))
    else:
        bolumler = [(c["shot"], c["shot"], c["start_s"], c["end_s"]) for c in secilen]
    for n, son_n, bas, bit in bolumler:
        c = {"start_s": bas, "end_s": bit}
        ad = f"{n}" if son_n == n else f"{n}-{son_n}"
        sure = max(0.2, c["end_s"] - c["start_s"])
        h3 = klip(n)
        hedef = os.path.join(gecici, f"{n:04d}.mp4")

        girdiler = ["-ss", f"{c['start_s']:.3f}", "-t", f"{sure:.3f}", "-i", a.orijinal]
        if h3:
            girdiler += ["-t", f"{sure:.3f}", "-i", h3]
        else:
            girdiler += ["-f", "lavfi", "-t", f"{sure:.3f}", "-i", f"color=black:s={SAG_G}x{Y}:r=24"]

        sol = (f"[0:v]scale={SOL_G}:{Y}:force_original_aspect_ratio=decrease,"
               f"pad={SOL_G}:{Y}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24")
        sag = (f"[1:v]scale={SAG_G}:{Y}:force_original_aspect_ratio=decrease,"
               f"pad={SAG_G}:{Y}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,"
               f"tpad=stop_mode=clone:stop_duration={sure:.3f}")
        if etiket:
            yazi = "drawtext=fontcolor=white:fontsize=26:box=1:boxcolor=black@0.5:x=12:y=12:text="
            sol += f",{yazi}'Orijinal - cekim {ad}'"
            sag += f",{yazi}'H3'" if h3 else f",{yazi}'uretilmedi'"
        filtre = f"{sol}[s];{sag}[g];[s][g]hstack=inputs=2,trim=duration={sure:.3f}[v]"

        ses_kaynak = "0:a?" if a.ses == "orijinal" or not h3 else "1:a?"
        calistir(["ffmpeg", "-y", "-loglevel", "error", *girdiler, "-filter_complex", filtre,
                  "-map", "[v]", "-map", ses_kaynak, "-t", f"{sure:.3f}",
                  "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-ar", "48000", "-ac", "2", hedef])
        parcalar.append(hedef)
        print(f"çekim {ad}: {sure:.1f} sn {'(H3 yok)' if not h3 else ''}", flush=True)

    liste = os.path.join(gecici, "liste.txt")
    with open(liste, "w") as f:
        for x in parcalar:
            f.write(f"file '{x}'\n")
    calistir(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", liste,
              "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac",
              "-movflags", "+faststart", a.cikti])
    shutil.rmtree(gecici)
    print(f"Hazır: {a.cikti} ({len(parcalar)} çekim)")


if __name__ == "__main__":
    main()
