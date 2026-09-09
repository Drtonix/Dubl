#!/bin/zsh
# Веса разделения голосов: сотня мегабайт, в репозитории им не место.
# Запускается сборкой сама; отдельно нужна только для запуска из исходников.
set -e
cd "${0:A:h}"
mkdir -p models

if [ ! -f models/nemo_en_titanet_large.onnx ]; then
    print -P "%F{green}==>%f качаю nemo_en_titanet_large.onnx"
    curl -fL --progress-bar -o models/nemo_en_titanet_large.onnx \
      "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_large.onnx"
fi

if [ ! -f models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx ]; then
    print -P "%F{green}==>%f качаю сегментацию pyannote"
    curl -fL --progress-bar -o /tmp/pyannote-seg.tar.bz2 \
      "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
    tar xf /tmp/pyannote-seg.tar.bz2 -C models
    rm -f /tmp/pyannote-seg.tar.bz2
fi
