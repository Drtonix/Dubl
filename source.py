"""Видео по ссылке: сведения, обложка, загрузка. Всё через yt-dlp."""
import json
import re
import subprocess

from i18n import t, tf
import sys
from pathlib import Path
from urllib.request import urlopen

URL = re.compile(r"^https?://\S+$")


def is_url(text):
    return bool(URL.match((text or "").strip()))


# Обычный веб-клиент YouTube упирается в «подтвердите, что вы не робот»:
# и обычные ролики, и шортсы отваливаются одинаково. Клиент приложения
# для Android такой проверки не требует и отдаёт всё то же самое.
YT_CLIENT = "youtube:player_client=default,android"
COOKIES = ""            # браузер для закрытых площадок вроде Instagram


def _ytdlp():
    """Модуль, а не бинарник: тот распаковывает себя на каждый запуск."""
    import importlib.util
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    return ["yt-dlp"]


# Где какой браузер держит cookies. Safari лежит в защищённой папке и без
# полного доступа к диску не читается; остальные доступны сразу, если
# установлены.
COOKIE_STORES = {
    "safari": ["Library/Containers/com.apple.Safari/Data/Library/Cookies/"
               "Cookies.binarycookies"],
    "chrome": ["Library/Application Support/Google/Chrome/*/Cookies",
               "Library/Application Support/Google/Chrome/*/Network/Cookies"],
    "firefox": ["Library/Application Support/Firefox/Profiles/*/cookies.sqlite"],
    "brave": ["Library/Application Support/BraveSoftware/Brave-Browser/*/Cookies",
              "Library/Application Support/BraveSoftware/Brave-Browser/*/Network/"
              "Cookies"],
    "edge": ["Library/Application Support/Microsoft Edge/*/Cookies",
             "Library/Application Support/Microsoft Edge/*/Network/Cookies"],
}


def cookie_browsers():
    """Браузеры, чьи cookies читаются прямо сейчас."""
    out = []
    for name, patterns in COOKIE_STORES.items():
        for pat in patterns:
            for path in Path.home().glob(pat):
                try:
                    with open(path, "rb") as f:
                        f.read(1)
                    out.append(name)
                except OSError:
                    pass
                break
            if name in out:
                break
    return out


def ytdlp(*args):
    cmd = [*_ytdlp(), *args, "--extractor-args", YT_CLIENT]
    if COOKIES:
        cmd += ["--cookies-from-browser", COOKIES]
    return cmd


class SourceError(Exception):
    """Ошибка ссылки: показывается человеку как есть."""


class NeedsCookies(SourceError):
    """Площадка требует вход, а cookies браузера недоступны."""


# Приметы отказа, который лечится cookies: и «докажите, что вы не робот»,
# и прямое требование войти в аккаунт.
LOGIN_WALL = ("cookies", "logged-in", "log in", "sign in", "empty media response")


def meta(url):
    """Название, длительность и обложка одним запросом."""
    r = subprocess.run(ytdlp("--no-warnings", "--skip-download",
                             "--no-playlist", "-J", url),
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout or "")
    except ValueError:
        d = None
    if not isinstance(d, dict):
        low = " ".join((r.stderr or "").split()).lower()
        if any(x in low for x in LOGIN_WALL) and not cookie_browsers():
            raise NeedsCookies("Этот сервис отдаёт видео только с разрешением.\n"
                               "Дайте полный доступ к диску и перезапустите "
                               "приложение.")
        raise SourceError("По этой ссылке видео не нашлось.")
    return {"title": d.get("title") or "Видео",
            "channel": d.get("channel") or d.get("uploader") or "",
            "duration": int(d.get("duration") or 0),
            "thumbnail": d.get("thumbnail") or ""}


def thumbnail(url, dst):
    """Обложка на диск. Не получилось — не беда, покажем одно название."""
    try:
        data = urlopen(url, timeout=15).read()
    except Exception:
        return None
    Path(dst).write_bytes(data)
    return Path(dst)


PROGRESS = re.compile(r"\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+)(\w+)"
                      r"(?:\s+at\s+(\S+))?(?:\s+ETA\s+(\S+))?")


def download(url, workdir, log=lambda m: None, should_stop=lambda: False,
             progress=lambda done, total: None):
    """Видео целиком. H.264 в приоритете: дорожку потом подменяем без
    перекодирования, а видеопоток копируется как есть."""
    out = str(Path(workdir) / "source.%(ext)s")
    cmd = ytdlp("--no-warnings", "--no-playlist", "--newline",
                "-f", "bv*[vcodec^=avc1][height<=1080]+ba/b[height<=1080]/bv*+ba/b",
                "--merge-output-format", "mp4", "-o", out, url)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        m = PROGRESS.search(line)
        if m:
            pct, size, unit, speed, eta = m.groups()
            progress(float(pct), 100.0)
            log(tf("  {pct}% из {size} {unit}", pct=f"{float(pct):.0f}",
                   size=size, unit=unit)
                + (f", {speed}" if speed else "")
                + (tf(", осталось {eta}", eta=eta) if eta else ""))
        if should_stop():
            proc.terminate()
            raise SourceError("Отменено")
    proc.wait()
    got = sorted(Path(workdir).glob("source.*"))
    if proc.returncode or not got:
        raise SourceError("Видео скачать не удалось.")
    return got[0]
