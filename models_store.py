"""Каталог моделей: наличие, размер на диске, скачивание и удаление.

Веса лежат в общем кэше Hugging Face, а не в бандле: они большие и переживают
обновление приложения.
"""
import os
from pathlib import Path
from i18n import t

CACHE = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"

# role — ключ перевода, а не готовый текст: язык переключается на лету.
CATALOG = [
    {"kind": "llm", "repo": "mlx-community/Qwen3.6-35B-A3B-4bit",
     "role": "Перевод, режим «Быстро»", "gb": 19.0},
    {"kind": "llm", "repo": "mlx-community/Qwen3.8-27B-4bit",
     "role": "Перевод, режим «Качественно»", "gb": 15.0},
    {"kind": "asr", "repo": "mlx-community/whisper-large-v3-mlx",
     "role": "Распознавание речи", "gb": 2.9},
    {"kind": "tts", "repo": "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16",
     "role": "Озвучка голосом оригинала", "gb": 4.2},
    {"kind": "tts", "repo": "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16",
     "role": "Озвучка подобранным голосом", "gb": 4.2},
]

DEMUCS_REPO = "adefossez/HTDemucs"


def short_name(repo):
    return repo.split("/")[-1]


DEMUCS_GB = 0.1


def demucs_ready():
    return size_on_disk(DEMUCS_REPO) > DEMUCS_GB * 0.75 * 1024 ** 3


def demucs_download(on_progress=lambda done, total: None,
                    should_stop=lambda: False):
    """Просим модель у demucs, а не тянем репозиторий целиком: там лежат все
    варианты весов, а нужен один."""
    import subprocess, sys, tempfile
    code = "from demucs.pretrained import get_model; get_model('htdemucs')"
    log = tempfile.TemporaryFile()
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=log, stderr=log)
    expected = DEMUCS_GB * 1024 ** 3
    while proc.poll() is None:
        if should_stop():
            proc.terminate()
            return False
        on_progress(size_on_disk(DEMUCS_REPO), expected)
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
    if proc.returncode:
        log.seek(0)
        lines = [x.strip() for x in
                 log.read().decode("utf-8", "replace").splitlines() if x.strip()]
        raise RuntimeError((lines[-1] if lines else "скачивание не удалось")[:300])
    on_progress(size_on_disk(DEMUCS_REPO), expected)
    return True


def _dir_for(repo):
    return CACHE / ("models--" + repo.replace("/", "--"))


def human(n):
    if n <= 0:
        return "—"
    for unit in (t("Б"), t("КБ"), t("МБ"), t("ГБ")):
        if n < 1024 or unit == t("ГБ"):
            return f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024


GRAB = ("import sys\n"
        "from huggingface_hub import snapshot_download\n"
        "snapshot_download(repo_id=sys.argv[1])\n")


# Общее хранилище моделей всех приложений (models_home): папка на выбор,
# одна очередь загрузок на все приложения, загрузчик докачивает с места и при
# закрытом окне. Определения ниже заменяют прежние с теми же именами.
import time as _time  # noqa: E402

import models_home as home  # noqa: E402


def size_on_disk(repo):
    p = home.resolve(repo)
    if p is None:
        return home.on_disk(repo)
    if home.shared(repo):
        return home._size(home.cache_dir(repo) / "blobs")
    return home._size(p)


def size_ready(repo):
    return size_on_disk(repo) if home.resolve(repo) is not None else 0


def is_ready(repo, gb=None):
    return home.resolve(repo) is not None


def delete(repo):
    home.remove(repo)


def download(repo, on_progress=lambda done, total: None, should_stop=lambda: False, where=None):
    """В общую очередь; where — своя папка для этой модели, иначе папка по
    умолчанию. Ход — из файла хода загрузчика."""
    expected = next((m["gb"] for m in CATALOG if m["repo"] == repo), 1.0) * 1024 ** 3
    home.enqueue(repo, where)
    while True:
        st = home.state(repo)
        if st == "ready":
            on_progress(expected, expected)
            return True
        if should_stop():
            home.cancel(repo)
            return False
        if st not in ("queued", "downloading"):
            err = home.status().get("errors", {}).get(repo)
            raise RuntimeError(err or "скачивание не удалось")
        p = home.progress(repo)
        if p:
            on_progress(int(p[0] * expected), expected)
        _time.sleep(0.5)
