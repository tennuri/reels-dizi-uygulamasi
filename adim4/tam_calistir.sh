#!/usr/bin/env bash
# Bir bölüm için tüm zinciri tek komutla çalıştırır (RunPod, pod yeniden başladıktan sonra da).
#
#   export HF_TOKEN=hf_...            # konuşmacı ayrımı için (yoksa konuşmacısız devam eder)
#   bash tam_calistir.sh /root/videolar/bolum1.mp4 bolum1 [1-9]
#
# 1) /root/venv-ses ve /root/venv-vlm yoksa kurar (container diskine, ~15 dk)
# 2) kes + ses
# 3) Qwen3-VL sunucusunu arka planda açar, hazır olunca analiz + birlestir + bible, sonra kapatır
# 4) Üçüncü argüman verilirse (ör. 1-9) cekimden_h3.py ile H3 girdisini hazırlar
# 5) JSON çıktıları kalıcı volume'a yedekler: /workspace/dizi/analiz/<ad>/
set -euo pipefail

VIDEO=${1:?video yolu ver}
AD=${2:?bölüm adı ver, ör. bolum1}
CEKIMLER=${3:-}
KOK=${KOK:-/root}
CIKTI=$KOK/analiz/$AD
YEDEK=${YEDEK:-/workspace/dizi/analiz/$AD}
MODEL=${MODEL:-Qwen/Qwen3-VL-8B-Instruct}
BURADA=$(cd "$(dirname "$0")" && pwd)
cd "$BURADA"

[[ -f $VIDEO ]] || { echo "Video yok: $VIDEO"; exit 1; }

if [[ ! -x $KOK/venv-ses/bin/python || ! -x $KOK/venv-vlm/bin/vllm ]]; then
  echo "== Kurulum (ilk sefer ya da pod yeniden başladı)"
  KOK=$KOK bash kurulum.sh 2>&1 | tee "$KOK/kurulum.log" | grep -E "^>>|Kurulum bitti|HATA|edilemedi" || true
fi
python3 -c "import scenedetect" 2>/dev/null || pip install -q "scenedetect>=0.6.4" opencv-python-headless

# Önceki çalışmanın yedeği varsa geri yükle (biten adımlar atlanır)
if [[ -d $YEDEK && ! -d $CIKTI ]]; then
  echo "== Yedekten geri yükleniyor: $YEDEK"
  mkdir -p "$CIKTI" && cp "$YEDEK"/*.json* "$CIKTI"/ 2>/dev/null || true
fi

echo "== Kesme ve ses"
python3 diziden_senaryo.py "$VIDEO" --cikti "$CIKTI" --adim kes,ses --ses-python "$KOK/venv-ses/bin/python"

echo "== Qwen3-VL sunucusu başlatılıyor ($MODEL), ilk seferde model iner"
nohup "$KOK/venv-vlm/bin/vllm" serve "$MODEL" --max-model-len 32768 --gpu-memory-utilization 0.85 \
  --limit-mm-per-prompt '{"image": 8}' > "$KOK/vllm.log" 2>&1 &
VLLM=$!
trap 'kill $VLLM 2>/dev/null || true' EXIT
for i in $(seq 1 180); do
  curl -sf localhost:8000/v1/models >/dev/null && break
  kill -0 $VLLM 2>/dev/null || { echo "vLLM kapandı, son satırlar:"; tail -20 "$KOK/vllm.log"; exit 1; }
  sleep 10
done
curl -sf localhost:8000/v1/models >/dev/null || { echo "vLLM 30 dk'da hazır olmadı"; tail -20 "$KOK/vllm.log"; exit 1; }

echo "== Görüntü analizi, birleştirme, bible"
python3 diziden_senaryo.py "$VIDEO" --cikti "$CIKTI" --adim analiz,birlestir,bible --vlm-model "$MODEL"
kill $VLLM 2>/dev/null || true
wait $VLLM 2>/dev/null || true
trap - EXIT
echo "== vLLM kapatıldı, GPU H3 için boş"

if [[ -n $CEKIMLER ]]; then
  python3 cekimden_h3.py "$CIKTI" --cekimler "$CEKIMLER"
fi

mkdir -p "$YEDEK" 2>/dev/null && cp "$CIKTI"/*.json "$CIKTI"/*.jsonl "$YEDEK"/ 2>/dev/null \
  && echo "== JSON yedeği: $YEDEK" \
  || echo "== UYARI: $YEDEK'e yedeklenemedi (volume dolu olabilir)"

echo
echo "Bitti. Çıktılar: $CIKTI"
cat "$CIKTI/ozet.json" 2>/dev/null | head -20 || true
