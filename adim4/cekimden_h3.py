#!/usr/bin/env python3
"""diziden_senaryo.py çıktısını adim3/h3_toplu_uret.py'nin okuduğu biçime çevirir.

    python3 cekimden_h3.py /root/analiz/bolum1 --cekimler 1-9

Çıktı (aynı klasöre):
    h3_bible.json     karakter/mekan tarifleri (bible_taslak.json'dan)
    h3_cekimler.json  her çekim: C/L kimlikleri, plan boyu, açı, hareket, aksiyon, tek replik

Not: Bu, başka bir dizinin sahnesini kendin üretip farkı görmek için bir çalışma
alıştırmasıdır. Üretilen klipleri uygulamada yayınlama.
"""
import argparse
import json
import os
import re
import sys


def oku(yol):
    with open(yol, encoding="utf-8") as f:
        return json.load(f)


def kelimeler(metin):
    return set(re.findall(r"[a-zçğıöşü]+", (metin or "").lower())) - {
        "a", "an", "the", "with", "and", "in", "of", "on", "wearing", "person"}


def esle(etiket, adaylar):
    """Görsel etiketi bible'daki kişi/mekan kimliğine bağlar: önce birebir, sonra kelime benzerliği."""
    for a in adaylar:
        if etiket in a.get("labels", []):
            return a["id"]
    k = kelimeler(etiket)
    en_iyi, puan = None, 0.0
    for a in adaylar:
        havuz = kelimeler(" ".join(a.get("labels", [])) + " " + a.get("name", "") + " " + a.get("visual", ""))
        if not havuz or not k:
            continue
        p = len(k & havuz) / len(k)
        if p > puan:
            en_iyi, puan = a["id"], p
    return en_iyi if puan >= 0.5 else None


def aralik(metin, en_fazla):
    if not metin:
        return set(range(1, en_fazla + 1))
    secim = set()
    for parca in metin.split(","):
        if "-" in parca:
            a, b = parca.split("-")
            secim |= set(range(int(a), int(b) + 1))
        else:
            secim.add(int(parca))
    return secim


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("klasor", help="diziden_senaryo.py --cikti klasörü")
    p.add_argument("--cekimler", default="", help="örn. 1-9 ya da 1-9,15 (varsayılan: hepsi)")
    p.add_argument("--esleme", default=None,
                   help='konuşmacı -> karakter kimliği, örn. {"SPEAKER_00": "C1"} (varsayılan: klasördeki konusmaci_c.json)')
    a = p.parse_args()

    liste = oku(os.path.join(a.klasor, "cekim_listesi.json"))["shots"]
    bible = oku(os.path.join(a.klasor, "bible_taslak.json"))
    if not bible.get("characters") or not bible.get("locations"):
        sys.exit("bible_taslak.json'da karakter ya da mekan yok, önce --adim bible çalıştır")
    chars, locs = bible["characters"], bible["locations"]
    for c in chars:
        c.setdefault("name", c["id"])
        c.setdefault("visual", "")
    for l in locs:
        l.setdefault("visual", l.get("name", ""))

    esleme_yol = a.esleme or os.path.join(a.klasor, "konusmaci_c.json")
    esleme = oku(esleme_yol) if os.path.exists(esleme_yol) else {}
    adla = {c["name"].lower(): c["id"] for c in chars}

    secili = aralik(a.cekimler, max(s["shot"] for s in liste))
    cikti, uyarilar = [], []
    for s in liste:
        if s["shot"] not in secili:
            continue
        cids = []
        for et in s["characters"]:
            cid = esle(et, chars)
            if cid and cid not in cids:
                cids.append(cid)
        lid = esle(s["location"], locs) or (cikti[-1]["location"] if cikti else locs[0]["id"])

        dialogue = None
        if s["dialogue"]:
            konusan = s["dialogue"][0]["speaker"]
            cid = esleme.get(konusan) or adla.get(konusan.lower())
            if not cid and s.get("on_screen_speaker"):
                cid = esle(s["on_screen_speaker"], chars)
            if not cid and cids:
                cid = cids[0]
            if cid:
                dialogue = {"speaker": cid, "line": " ".join(d["line"] for d in s["dialogue"])}
                if cid not in cids:
                    cids.append(cid)
            else:
                uyarilar.append(f"çekim {s['shot']}: konuşan karaktere bağlanamadı, replik atlandı")

        cikti.append({
            "shot": s["shot"],
            "duration_s": s["duration_s"],
            "orig_start_s": s["start_s"],
            "orig_end_s": s["end_s"],
            "location": lid,
            "characters": cids,
            "size": s["size"] or "medium",
            "angle": s["angle"] or "eye level",
            "movement": s["movement"] or "static",
            "action": s["action"],
            "lighting": s.get("lighting", ""),
            "dialogue": dialogue,
        })

    with open(os.path.join(a.klasor, "h3_bible.json"), "w", encoding="utf-8") as f:
        json.dump(bible, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.klasor, "h3_cekimler.json"), "w", encoding="utf-8") as f:
        json.dump({"ep": 1, "shots": cikti}, f, ensure_ascii=False, indent=1)

    toplam = sum(x["duration_s"] for x in cikti)
    print(f"{len(cikti)} çekim ({toplam:.0f} sn orijinal) -> {a.klasor}/h3_cekimler.json")
    print(f"bible -> {a.klasor}/h3_bible.json")
    kisa = sum(1 for x in cikti if x["duration_s"] < 4)
    if kisa:
        print(f"Not: {kisa} çekim 4 sn'den kısa; H3 en az 4 sn üretir, karşılaştırmada orijinal süreye kırpılır.")
    for u in uyarilar:
        print("  " + u)


if __name__ == "__main__":
    main()
