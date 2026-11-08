#!/usr/bin/env bash
# RunPod pod'unda senaryo çıkarma zincirini kurar.
# WhisperX ve vLLM farklı torch sürümleri istediği için iki ayrı sanal ortam kullanır.
#
#   bash kurulum.sh            # ikisini de kur
#   bash kurulum.sh ses        # sadece WhisperX
#   bash kurulum.sh vlm        # sadece vLLM
set -euo pipefail

KOK=${KOK:-/workspace}
NE=${1:-hepsi}

apt-get update -qq && apt-get install -y -qq ffmpeg python3-venv >/dev/null

# Ana betik (kes/birlestir) sistem python'unda çalışır, sadece PySceneDetect ister
pip install -q "scenedetect>=0.6.4" opencv-python-headless

if [[ $NE == hepsi || $NE == ses ]]; then
  echo ">> WhisperX ortamı: $KOK/venv-ses"
  python3 -m venv "$KOK/venv-ses"
  "$KOK/venv-ses/bin/pip" install -q --upgrade pip
  "$KOK/venv-ses/bin/pip" install -q whisperx
  # pyannote.audio 3.x, torchaudio 2.9'daki AudioMetaData kaldırılınca bozuluyor
  # --isolated: RunPod imajındaki pip ayarlarını (torch 2.10 kilidi) yok say
  "$KOK/venv-ses/bin/pip" --isolated install -q --index-url https://download.pytorch.org/whl/cu128 \
    "torch==2.8.0" "torchaudio==2.8.0"
  "$KOK/venv-ses/bin/python" -c "import whisperx.asr" || { echo "WhisperX import edilemedi"; exit 1; }
fi

if [[ $NE == hepsi || $NE == vlm ]]; then
  echo ">> vLLM ortamı: $KOK/venv-vlm"
  python3 -m venv "$KOK/venv-vlm"
  "$KOK/venv-vlm/bin/pip" install -q --upgrade pip
  "$KOK/venv-vlm/bin/pip" install -q vllm
fi

cat <<EOF

Kurulum bitti.

1) Hugging Face token'ını ayarla (konuşmacı ayrımı için):
     export HF_TOKEN=hf_...
   ve tarayıcıda pyannote modellerinin sayfasında şartları kabul et
   (rehberde linkler var).

2) Qwen3-VL sunucusunu başlat (ayrı bir terminalde):
     $KOK/venv-vlm/bin/vllm serve Qwen/Qwen3-VL-8B-Instruct \\
       --max-model-len 32768 --gpu-memory-utilization 0.70 \\
       --limit-mm-per-prompt '{"image": 8}'

3) Çalıştır:
     python3 diziden_senaryo.py bolum1.mp4 --cikti analiz/bolum1 --ses-python $KOK/venv-ses/bin/python
EOF
