#!/usr/bin/env python3
"""Sesi yazıya döker ve konuşmacıları ayırır (WhisperX + pyannote).

Bu betik WhisperX sanal ortamında çalışır. Genelde doğrudan değil,
diziden_senaryo.py tarafından çağrılır:

    /workspace/venv-ses/bin/python ses_coz.py ses.wav diyalog.json --dil tr

Çıktı:
    {"segments": [{"start": 1.2, "end": 3.4, "speaker": "SPEAKER_00", "text": "..."}]}
"""
import argparse
import gc
import json
import os
import sys


def guvenli_siniflari_ekle(torch):
    """torch >= 2.6 checkpoint'leri weights_only=True ile açıyor. pyannote checkpoint'leri
    omegaconf ve pyannote'un kendi meta veri sınıflarını içerdiği için reddediliyor.
    Güvenliği kapatmak yerine sadece bu bilinen sınıfları izin listesine ekliyoruz."""
    import collections
    import importlib
    import typing

    adlar = [
        ("omegaconf.listconfig", "ListConfig"),
        ("omegaconf.dictconfig", "DictConfig"),
        ("omegaconf.base", "ContainerMetadata"),
        ("omegaconf.base", "Metadata"),
        ("omegaconf.nodes", "AnyNode"),
        ("pyannote.audio.core.model", "Introspection"),
        ("pyannote.audio.core.task", "Specifications"),
        ("pyannote.audio.core.task", "Problem"),
        ("pyannote.audio.core.task", "Resolution"),
        ("torch.torch_version", "TorchVersion"),
    ]
    siniflar = [typing.Any, list, dict, int, collections.defaultdict]
    for mod, ad in adlar:
        try:
            siniflar.append(getattr(importlib.import_module(mod), ad))
        except Exception:
            pass
    if hasattr(torch.serialization, "add_safe_globals"):
        torch.serialization.add_safe_globals(siniflar)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("wav")
    p.add_argument("cikti")
    p.add_argument("--dil", default="tr")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--hf-token", default=os.environ.get("HF_TOKEN"))
    p.add_argument("--min-konusmaci", type=int, default=None)
    p.add_argument("--max-konusmaci", type=int, default=None)
    a = p.parse_args()

    import torch

    guvenli_siniflari_ekle(torch)
    import whisperx

    cihaz = "cuda" if torch.cuda.is_available() else "cpu"
    tur = "float16" if cihaz == "cuda" else "int8"

    print(f"[ses] {a.model} yükleniyor ({cihaz})", flush=True)
    model = whisperx.load_model(a.model, cihaz, compute_type=tur, language=a.dil)
    ses = whisperx.load_audio(a.wav)
    sonuc = model.transcribe(ses, batch_size=a.batch, language=a.dil)
    del model
    gc.collect()
    if cihaz == "cuda":
        torch.cuda.empty_cache()

    print("[ses] kelime zamanları hizalanıyor", flush=True)
    try:
        hiz_model, meta = whisperx.load_align_model(language_code=a.dil, device=cihaz)
        sonuc = whisperx.align(sonuc["segments"], hiz_model, meta, ses, cihaz,
                               return_char_alignments=False)
        del hiz_model
    except Exception as e:  # hizalama modeli yoksa kaba zamanlarla devam
        print(f"[ses] hizalama atlandı: {e}", flush=True)

    if a.hf_token:
        print("[ses] konuşmacılar ayrılıyor (pyannote)", flush=True)
        try:
            from whisperx.diarize import DiarizationPipeline
        except ImportError:  # eski WhisperX sürümleri
            DiarizationPipeline = whisperx.DiarizationPipeline
        diar = DiarizationPipeline(use_auth_token=a.hf_token, device=cihaz)
        konusmalar = diar(ses, min_speakers=a.min_konusmaci, max_speakers=a.max_konusmaci)
        sonuc = whisperx.assign_word_speakers(konusmalar, sonuc)
    else:
        print("[ses] HF_TOKEN yok, konuşmacı ayrımı atlandı", file=sys.stderr, flush=True)

    segs = [
        {
            "start": round(float(s["start"]), 2),
            "end": round(float(s["end"]), 2),
            "speaker": s.get("speaker", "SPEAKER_??"),
            "text": s["text"].strip(),
        }
        for s in sonuc["segments"]
        if s.get("text", "").strip()
    ]
    with open(a.cikti, "w", encoding="utf-8") as f:
        json.dump({"segments": segs}, f, ensure_ascii=False, indent=1)
    print(f"[ses] {len(segs)} konuşma parçası -> {a.cikti}", flush=True)


if __name__ == "__main__":
    main()
