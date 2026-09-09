"""Каталог моделей: наличие, размер на диске, скачивание и удаление.

Веса лежат в общем кэше Hugging Face, а не в бандле: они большие и переживают
обновление приложения.
"""
import os
import shutil
from pathlib import Path
from i18n import t

CACHE = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"

# role — ключ перевода, а не готовый текст: язык переключается на лету.
CATALOG = [
    {"kind": "llm", "repo": "mlx-community/Qwen3-30B-A3B-4bit",
     "role": "Перевод, режим «Быстро»", "gb": 16.0},
    {"kind": "llm", "repo": "mlx-community/Qwen3-32B-4bit-DWQ",
     "role": "Перевод, режим «Качественно»", "gb": 17.0},
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


def size_on_disk(repo):
    """Байты в blobs: snapshot — это ссылки на них."""
    d = _dir_for(repo) / "blobs"
    if not d.exists():
        return 0
    total = 0
    for f in d.iterdir():
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total


def is_ready(repo, gb):
    """Точного размера заранее нет: считаем готовой от 75% ожидаемого."""
    return size_on_disk(repo) >= gb * 1024 ** 3 * 0.75


def human(n):
    if n <= 0:
        return "—"
    for unit in (t("Б"), t("КБ"), t("МБ"), t("ГБ")):
        if n < 1024 or unit == t("ГБ"):
            return f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024


def delete(repo):
    shutil.rmtree(_dir_for(repo), ignore_errors=True)


GRAB = ("import sys\n"
        "from huggingface_hub import snapshot_download\n"
        "snapshot_download(repo_id=sys.argv[1])\n")


def download(repo, on_progress=lambda done, total: None, should_stop=lambda: False):
    """Скачивание отдельным процессом; ход считается по размеру на диске.

    Процессом, а не потоком: остановку huggingface_hub не умеет, поток
    продолжал качать и после отмены. Процесс снимается целиком.
    """
    import subprocess, sys, tempfile

    env = {**os.environ, "HF_HUB_DISABLE_PROGRESS_BARS": "1"}
    log = tempfile.TemporaryFile()      # не канал: он забьётся и всё встанет
    proc = subprocess.Popen([sys.executable, "-c", GRAB, repo],
                            stdout=log, stderr=log, env=env)
    expected = next((m["gb"] for m in CATALOG if m["repo"] == repo), 1.0) * 1024 ** 3
    while proc.poll() is None:
        if should_stop():
            proc.terminate()
            return False        # недокачанное докачается при следующем запуске
        on_progress(size_on_disk(repo), expected)
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass
    if proc.returncode:
        log.seek(0)
        lines = [x.strip() for x in
                 log.read().decode("utf-8", "replace").splitlines() if x.strip()]
        # Последняя строка трассировки бывает подсказкой про пароль; берём саму ошибку.
        why = next((x for x in reversed(lines) if "Error" in x), lines[-1] if lines else "")
        raise RuntimeError(why[:300] or "скачивание не удалось")
    on_progress(size_on_disk(repo), expected)
    return True
