"""Окно Dubl: видео с диска или по ссылке, кнопка, готовая дорожка."""
import re, shutil, sys, tempfile, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from PySide6.QtGui import (QAction, QColor, QIcon, QPainter, QPainterPath,
                           QPen, QPixmap, QTextCursor)
from PySide6.QtCore import (Qt, QPointF, QRectF, QSettings, QSize, QThread,
                            QTimer, QUrl, Signal)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QPlainTextEdit, QFileDialog,
                               QMessageBox, QComboBox, QFrame, QSizePolicy, QLineEdit,
                               QStackedWidget, QMenuBar, QScrollArea,
                               QSplitter, QListWidget, QListWidgetItem,
                               QDialog, QTextEdit)
from _style import STYLE
from i18n import t, tf
import i18n

# Плотная модель переводит заметно лучше, но втрое медленнее: у смеси
# экспертов на слово работают 3 млрд параметров из 30, у плотной — все 32.
MODELS = {"fast": "mlx-community/Qwen3-30B-A3B-4bit",
          "good": "mlx-community/Qwen3-32B-4bit-DWQ"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
ACCENT = "#33b268"
AUTHOR, SITE, SITE_URL = "DrTonix", "bdub.space", "https://bdub.space"
DISK_ACCESS = ("x-apple.systempreferences:com.apple.preference.security"
               "?Privacy_AllFiles")

EXTRA = """
QLineEdit {
    background: rgba(255,255,255,0.07);
    border: none; border-radius: 10px;
    padding: 11px 13px; color: #e9ebef; font-size: 13px;
}
QLineEdit:focus { background: rgba(255,255,255,0.10); }
/* Цвет действия совпадает с цветом значка приложения. */
QPushButton#primary          { background: #33b268; }
QPushButton#primary:hover    { background: #3fc477; }
QPushButton#primary:disabled { background: rgba(51,178,104,0.28); color: rgba(255,255,255,0.45); }
QPushButton#send             { background: #33b268; }
QPushButton#send:hover       { background: #3fc477; }
QPushButton#seg:checked      { background: #33b268; }
QPushButton#danger {
    background: rgba(255,255,255,0.10);
    color: #e9ebef;
    font-weight: 500;
}
QPushButton#danger:hover { background: rgba(255,255,255,0.15); }
QListWidget::item:selected { background: rgba(51,178,104,0.30); }
QFrame#panel {
    background: #232327;
    border: none;
    border-radius: 14px;
}
QScrollArea#feed, QWidget#feedInner { background: transparent; border: none; }
QLabel#summary { color: #dfe3ea; }
QLabel#dim { color: #9aa0a8; font-size: 12px; }
QLabel#userMsg {
    background: #33b268;
    color: #ffffff;
    border-radius: 14px;
    padding: 10px 14px;
}
QLabel#botMsg { color: #dfe3ea; padding: 2px 2px 8px 2px; }
QFrame#divider { background: rgba(255,255,255,0.08); max-height: 1px; }

/* Меню рисуем сами: системное подсвечивает строку синим прямоугольником
   поверх скруглённой подложки. */
QMenu {
    background: #2c2c31;
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 9px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 22px 6px 11px;
    border-radius: 6px;
    color: #e9ebef;
    font-size: 13px;
}
QMenu::item:selected { background: #33b268; color: #ffffff; }
QMenu::item:disabled { color: #6b6f76; }
QMenu::item:disabled:selected { background: transparent; }

/* Список сохранённых — тот же фон и скругление, что у журнала рядом:
   иначе вкладки переключаются, а вид под ними скачет. */
QListWidget {
    background: #1a1a1d;
    border: none;
    border-radius: 12px;
    padding: 6px;
    color: #c3c8d0;
    font-size: 12px;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 8px;
}
QListWidget::item:hover    { background: rgba(255,255,255,0.06); }
QListWidget::item:selected { background: rgba(51,178,104,0.32); color: #ffffff; }
/* Строка ввода — видимая «пилюля» поверх панели чата: фон и рамка у неё
   самой, а поле внутри прозрачное, иначе получается рамка внутри рамки. */
QFrame#composer {
    background: rgba(255,255,255,0.06);
    border: none;
    border-radius: 16px;
}
QFrame#composer QLineEdit {
    background: transparent;
    border: none;
    padding: 0 4px 0 10px;
    font-size: 13px;
}
QWidget#composerWrap { background: transparent; }
QPushButton#iconbtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 0;
}
QPushButton#iconbtn:hover { background: rgba(255,255,255,0.08); }
QPushButton#send {
    border: none;
    border-radius: 14px;
    padding: 0;
    color: white;
    font-size: 15px;
    font-weight: 700;
}
QPushButton#send:disabled { background: rgba(255,255,255,0.12); color: rgba(255,255,255,0.35); }
QSplitter::handle { background: transparent; width: 14px; }

/* Своё сверх Konspekt: субтитры поверх кадра и ползунки проигрывателя. */
QLabel#subs {
    background: rgba(0,0,0,0.62);
    border-radius: 8px;
    color: #ffffff;
    font-size: 15px;
    padding: 6px 10px;
}
QLabel#linkTitle { font-size: 14px; color: #f4f5f7; }
QTextEdit#subEdit {
    background: rgba(255,255,255,0.06);
    border: none; border-radius: 8px;
    padding: 7px 9px;
    color: #e9ebef; font-size: 13px;
    font-family: "Helvetica Neue", Arial, sans-serif;
}
QTextEdit#subEdit:focus { background: rgba(255,255,255,0.10); }
QWidget#preview { background: #232327; border-radius: 14px; }
QWidget#preview QLabel { background: transparent; }
QSlider::groove:horizontal {
    height: 4px; background: rgba(255,255,255,0.14); border-radius: 2px;
}
QSlider::sub-page:horizontal { background: #33b268; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #ffffff; width: 12px; height: 12px;
    margin: -4px 0; border-radius: 6px;
}
QPushButton#iconbtn:checked { background: #33b268; color: #ffffff; }
"""


def _pixmap(px):
    """Холст в плотности экрана: иначе значок мылит на двукратном дисплее."""
    app = QApplication.instance()
    dpr = float(app.devicePixelRatio()) if app else 2.0
    pm = QPixmap(int(px * dpr), int(px * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    pm.setDevicePixelRatio(dpr)
    return pm


def _icon_sidebar(px=18, color="#9aa0a8"):
    """Прямоугольник с левой колонкой; рамка внутрь на полтолщины, иначе срез."""
    pm = _pixmap(px)
    pt = QPainter(pm)
    pt.setRenderHint(QPainter.RenderHint.Antialiasing)
    w = px * 0.09
    pen = QPen(QColor(color)); pen.setWidthF(w)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pt.setPen(pen)
    m = px * 0.13 + w / 2
    rect = QRectF(m, m, px - 2 * m, px - 2 * m)
    r = px * 0.14
    pt.drawRoundedRect(rect, r, r)
    x = rect.left() + rect.width() * 0.38
    # линию не ведём до самой рамки, иначе она наезжает на скругления
    pt.drawLine(QPointF(x, rect.top() + r * 0.5), QPointF(x, rect.bottom() - r * 0.5))
    pt.end()
    return QIcon(pm)


# Встраивание умеют не все площадки; без него остаётся обложка.
EMBEDS = [
    (re.compile(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/|live/)|youtu\.be/)"
                r"([A-Za-z0-9_-]{11})"),
     "https://www.youtube.com/embed/{0}?rel=0&modestbranding=1"),
    (re.compile(r"tiktok\.com/@[^/]+/video/(\d+)"),
     "https://www.tiktok.com/embed/v2/{0}"),
    (re.compile(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)"),
     "https://www.instagram.com/p/{0}/embed"),
    (re.compile(r"vk\.com/video(-?\d+)_(\d+)"),
     "https://vk.com/video_ext.php?oid={0}&id={1}"),
    (re.compile(r"rutube\.ru/video/([0-9a-f]{32})"),
     "https://rutube.ru/play/embed/{0}"),
]


def embed_url(url):
    """Адрес встраиваемого плеера для ссылки, если площадка это умеет."""
    for pat, tpl in EMBEDS:
        m = pat.search(url or "")
        if m:
            return tpl.format(*m.groups())
    return None


class _PlayerServer:
    """Локальный сервер под плеер: без источника страницы YouTube даёт ошибку 153."""

    PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{margin:0;height:100%%;background:#232327;overflow:hidden}
.box{height:100%%;border-radius:12px;overflow:hidden}
iframe{border:0;width:100%%;height:100%%;display:block}</style></head><body>
<div class="box">
<iframe src="%s"
 allow="accelerometer;autoplay;clipboard-write;encrypted-media;picture-in-picture"
 allowfullscreen></iframe></div></body></html>"""

    def __init__(self):
        self.embed = ""
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = (outer.PAGE % outer.embed).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, embed):
        self.embed = embed
        return f"http://127.0.0.1:{self.port}/?e={abs(hash(embed)) % 10**8}"


def app_icon():
    """Значок из бандла, при запуске из исходников — из проекта."""
    here = Path(__file__).resolve().parent
    for p in (here.parent / "AppIcon.icns", here / "icon" / "AppIcon.icns",
              Path("/Applications/Dubl.app/Contents/Resources/AppIcon.icns")):
        if p.exists():
            return QIcon(str(p))
    return QIcon()


class Bar(QWidget):
    """Полоса хода работы.

    Своя, а не QProgressBar: штатная обрезает бегущий отрезок по прямой.
    """

    H = 6

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self.H)
        self._busy = False
        self._pos = 0.0
        self._value = 0.0        # куда идём
        self._shown = 0.0        # что нарисовано
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_busy(self, on):
        self._busy = on
        self._timer.start(16) if on else self._timer.stop()
        self.update()

    def set_progress(self, cur, total):
        # Значение приходит раз в полсекунды рывками, полоса идёт к нему
        # плавно: иначе на многогигабайтной загрузке она выглядит стоящей.
        self._busy = False
        self._value = (cur / total) if total else 0.0
        if self._value <= self._shown:
            self._shown = self._value          # новая загрузка, откат к началу
        if not self._timer.isActive():
            self._timer.start(16)
        self.update()

    def _tick(self):
        if self._busy:
            self._pos = (self._pos + 0.011) % 1.0
        else:
            step = (self._value - self._shown) * 0.08
            if abs(self._value - self._shown) < 0.0002:
                self._shown = self._value
                self._timer.stop()
            else:
                self._shown += step
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2
        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, w, h), r, r)
        p.setClipPath(track)
        p.fillPath(track, QColor(255, 255, 255, 16))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        if self._busy:
            seg = w * 0.32
            x = self._pos * (w + seg) - seg
            p.drawRoundedRect(QRectF(x, 0, seg, h), r, r)
        elif self._shown > 0:
            p.drawRoundedRect(QRectF(0, 0, max(h, w * self._shown), h), r, r)
        p.end()


class _Call(QThread):
    """Долгий вызов в стороне от окна: yt-dlp думает пару секунд."""
    ready = Signal(dict)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.ready.emit(self.fn() or {})
        except Exception as e:
            self.ready.emit({"error": str(e)})


class DownloadWorker(QThread):
    # qint64, а не int: у Qt int тридцатидвухбитный, и 16 ГБ в него не влезают.
    progress = Signal("qint64", "qint64")
    done = Signal(bool, str)

    def __init__(self, repo):
        super().__init__()
        self.repo = repo
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            import models_store
            grab = (models_store.demucs_download
                    if self.repo == models_store.DEMUCS_REPO else
                    lambda **kw: models_store.download(self.repo, **kw))
            grab(on_progress=lambda a, b: self.progress.emit(int(a), int(b)),
                 should_stop=lambda: self._stop)
            self.done.emit(True, "")
        except Exception as e:
            self.done.emit(False, f"{type(e).__name__}: {e}")


class Redub(QThread):
    """Переозвучка по исправленному тексту: разбор и перевод уже сделаны."""
    line = Signal(str)
    tick = Signal(str)
    step = Signal(str, int, int)
    done = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, video, dst, utts, workdir, target="ru",
                 voice_mode="clone", background="strip", tone=False):
        super().__init__()
        self.video, self.dst, self.utts = video, dst, utts
        self.workdir, self.target = workdir, target
        self.voice_mode, self.background = voice_mode, background
        self.tone = tone
        self._stop = False
        self._stage_name, self._stage_t0 = "", 0.0

    def run(self):
        self._t0 = self._stage_t0 = time.monotonic()
        try:
            import pipeline
            out = Path(self.dst)
            tmp_out = out.with_name(out.stem + ".new" + out.suffix)
            r = pipeline.redub(self.video, str(tmp_out), self.utts, self.workdir,
                               target=self.target, voice_mode=self.voice_mode,
                               background=self.background, tone=self.tone,
                               should_stop=lambda: self._stop,
                               log=self._log, stage=self._stage)
            tmp_out.replace(out)       # подменяем на месте, чтобы кнопки не съехали
            r["out"] = str(out)
            self._log(t("Всего ") + Worker._span(time.monotonic() - self._t0))
            self.done.emit(r)
        except Exception as e:
            import pipeline
            if isinstance(e, pipeline.Cancelled):
                self.cancelled.emit()
            else:
                self.failed.emit(f"{e}\n\n{traceback.format_exc()}")

    def stop(self):
        self._stop = True

    _span = staticmethod(lambda sec: f"{int(sec)//60}:{int(sec)%60:02d}")

    def _log(self, msg):
        self.line.emit(f"[{self._span(time.monotonic() - self._t0)}] {msg}")

    def _stage(self, name, cur, total):
        self._stage_name = name
        self.step.emit(name, cur, total)


class Worker(QThread):
    line = Signal(str)
    tick = Signal(str)          # строка, которая переписывается на месте
    step = Signal(str, int, int)
    done = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()
    needs_access = Signal(str)

    def __init__(self, src, dst, speakers, background, voice_mode,
                 link="", workdir=None, target="ru", model_id="", tone=False):
        super().__init__()
        self.model_id = model_id or MODELS["good"]
        self.src, self.dst = src, dst
        self.speakers, self.background = speakers, background
        self.voice_mode, self.target = voice_mode, target
        self.tone = tone
        self.link, self.workdir = link, workdir
        self._stop = False
        self._stage_name, self._stage_t0 = "", 0.0

    def stop(self):
        self._stop = True

    @staticmethod
    def _span(sec):
        h, m, s = int(sec // 3600), int(sec // 60) % 60, int(sec) % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _log(self, msg):
        """Строка журнала со временем от начала работы."""
        self.line.emit(f"[{self._span(time.monotonic() - self._t0)}] {msg}")

    def _stage(self, name, cur, total):
        """Смена этапа — повод записать, сколько занял предыдущий."""
        now = time.monotonic()
        if name != self._stage_name:
            if self._stage_name:
                self._log(f"  ↳ «{t(self._stage_name)}" + t("» заняло ")
                          + self._span(now - self._stage_t0))
            self._stage_name, self._stage_t0 = name, now
        self.step.emit(name, cur, total)

    def run(self):
        self._t0 = self._stage_t0 = time.monotonic()
        try:
            import pipeline, source
            src = self.src
            if self.link:
                self._stage("Скачивание видео", 0, 1)
                self._log(t("Скачивание видео…"))
                src = str(source.download(
                    self.link, self.workdir, log=self.tick.emit,
                    should_stop=lambda: self._stop,
                    progress=lambda d, tt: self.step.emit("Скачивание видео",
                                                          int(d), int(tt))))
            work = str(Path(self.workdir) / "dub") if self.workdir else None
            r = pipeline.dub(src, self.dst, model_id=self.model_id, workdir=work,
                             target=self.target, fast=self.model_id == MODELS["fast"],
                             num_speakers=self.speakers,
                             original_volume=0.12, background=self.background,
                             voice_mode=self.voice_mode, tone=self.tone,
                             should_stop=lambda: self._stop,
                             log=self._log, stage=self._stage)
            if self.link:
                # Оригинал больше не нужен ни при каком исходе.
                Path(src).unlink(missing_ok=True)
                self._log(t("Исходное видео удалено"))
            if self._stage_name:
                self._log(f"  ↳ «{t(self._stage_name)}" + t("» заняло ")
                          + self._span(time.monotonic() - self._stage_t0))
            self._log(t("Всего ") + self._span(time.monotonic() - self._t0))
            self.done.emit(r)
        except Exception as e:
            import pipeline, source
            if isinstance(e, pipeline.NoSpeech):
                self.failed.emit(str(e))     # человеку хватит одной строки
            elif isinstance(e, source.NeedsCookies):
                self.needs_access.emit(str(e))
            elif isinstance(e, (pipeline.Cancelled,)) or "Отменено" in str(e):
                self.cancelled.emit()
            else:
                self.failed.emit(f"{e}\n\n{traceback.format_exc()}")



class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle("Dubl")
        self.setAcceptDrops(True)
        self.resize(1180, 880)
        self.setStyleSheet(STYLE + EXTRA)
        self.settings = QSettings("local", "Dubl")
        import source
        # Браузер не выбирают: берём тот, чьи cookies читаются.
        source.COOKIES = (source.cookie_browsers() or [""])[0]
        self.src = None          # файл, который будем озвучивать
        self.link = ""           # ссылка, если источник из сети
        self.link_meta = {}      # название и канал по ссылке
        self.worker = None
        self.tmp = None          # временная папка для работы по ссылке
        self.result = None       # готовый дубляж, ещё не сохранённый
        self._alive = []
        self._downloading = {}   # репозиторий -> поток загрузки
        self._ticking = False    # последняя строка журнала переписывается
        self.sub_rows = []       # (начало, конец, оригинал, перевод)
        self.sub_edits = []      # поля правки перевода по репликам
        self.shown = None        # файл, показанный в предпросмотре
        self.dub_file = None     # готовый дубляж, открывается кнопкой
        self.work_dir = None     # рабочая папка разбора: нужна переозвучке

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split)

        # ── слева: что делаем
        left = QWidget(); left.setObjectName("feedInner")
        root = QVBoxLayout(left)
        root.setContentsMargins(20, 18, 14, 18)
        root.setSpacing(0)

        lbl = QLabel(t("Ссылка на видео")); lbl.setObjectName("section")
        root.addWidget(lbl)
        root.addSpacing(8)
        top = QHBoxLayout(); top.setSpacing(8)
        self.url = QLineEdit()
        self.url.setPlaceholderText(t("Ссылка на видео"))
        self._url_wait = QTimer(self); self._url_wait.setSingleShot(True)
        self._url_wait.setInterval(600)          # не дёргать yt-dlp на каждую букву
        self._url_wait.timeout.connect(self.on_url)
        self.url.textChanged.connect(self._url_typed)
        top.addWidget(self.url, 1)
        self.pick = QPushButton(t("Выбрать файл…")); self.pick.clicked.connect(self.choose)
        self.pick.setFixedHeight(38)
        top.addWidget(self.pick)
        root.addLayout(top)
        root.addSpacing(18)
        lbl = QLabel(t("Что нужно")); lbl.setObjectName("section")
        root.addWidget(lbl)
        root.addSpacing(8)

        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card); cl.setContentsMargins(16, 14, 16, 14); cl.setSpacing(13)

        r0 = QHBoxLayout()
        self.lbl_lang = QLabel(t("Язык озвучки"))
        r0.addWidget(self.lbl_lang); r0.addStretch()
        self.lang = QComboBox()
        self.lang.view().setMinimumWidth(190)
        self._fill_langs()
        r0.addWidget(self.lang)
        cl.addLayout(r0)

        self.speeds = self._segment(cl, ((t("Быстро"), "fast"),
                                         (t("Качественно"), "good"),
                                         (t("С интонациями"), "tone")))
        self.speeds[1].setChecked(True)
        self.tone_note = QLabel(t("Перенос интонации работает нестабильно"))
        self.tone_note.setObjectName("dim")
        self.tone_note.setVisible(False)
        cl.addWidget(self.tone_note)
        for b in self.speeds:
            b.toggled.connect(lambda _on: self.tone_note.setVisible(
                self.speeds[2].isChecked()))

        self.modes = self._segment(cl, ((t("Как в оригинале"), "clone"),
                                        (t("Подобрать"), "design")))
        self.modes[1].setChecked(True)

        self.sound = self._segment(cl, ((t("Убрать голос"), "strip"),
                                        (t("Только дубляж"), "none"),
                                        (t("Оригинал фоном"), "quiet")))
        self.sound[0].setChecked(True)

        r1 = QHBoxLayout()
        self.lbl_voices = QLabel(t("Сколько голосов"))
        r1.addWidget(self.lbl_voices); r1.addStretch()
        self.spk = QComboBox()
        self.spk.addItem(t("Определить самому"), 0)
        for n in range(1, 7):
            self.spk.addItem(str(n), n)
        self.spk.view().setMinimumWidth(190)   # иначе всплывающий список режет текст
        r1.addWidget(self.spk)
        cl.addLayout(r1)
        root.addWidget(card)
        root.addSpacing(16)

        self.go = QPushButton(t("Озвучить")); self.go.setObjectName("primary")
        self.go.setEnabled(False); self.go.clicked.connect(self.start)
        self.go.setFixedHeight(46)
        root.addWidget(self.go)
        root.addSpacing(8)
        self.cancel = QPushButton(t("Отмена")); self.cancel.setObjectName("danger")
        self.cancel.setFixedHeight(40); self.cancel.setVisible(False)
        self.cancel.clicked.connect(self.stop)
        root.addWidget(self.cancel)

        # Готовый дубляж по ссылке лежит во временной папке: либо забрать,
        # либо стереть вместе с ней.
        # Скачанное по ссылке лежит во временной папке: кнопка стирает её,
        # не дожидаясь закрытия приложения.
        self.after = QWidget()
        av = QHBoxLayout(self.after); av.setContentsMargins(0, 10, 0, 0); av.setSpacing(8)
        self.drop_btn = QPushButton(t("Удалить"))
        self.drop_btn.setFixedHeight(40)
        self.drop_btn.clicked.connect(self.discard_result)
        av.addWidget(self.drop_btn)
        self.after.setVisible(False)
        root.addWidget(self.after)

        self.progress = QWidget()
        pv = QVBoxLayout(self.progress); pv.setContentsMargins(0, 14, 0, 0); pv.setSpacing(8)
        self.stage = QLabel(" "); self.stage.setObjectName("stage")
        pv.addWidget(self.stage)
        self.bar = Bar()
        pv.addWidget(self.bar)
        self.progress.setVisible(False)          # в простое ничего не висит
        root.addWidget(self.progress)
        root.addSpacing(16)

        tabs = QFrame(); tabs.setObjectName("segment")
        tl = QHBoxLayout(tabs); tl.setContentsMargins(3, 3, 3, 3); tl.setSpacing(3)
        self.tab_log = QPushButton(t("Ход работы"))
        self.tab_set = QPushButton(t("Настройки"))
        for b in (self.tab_log, self.tab_set):
            b.setObjectName("seg"); b.setCheckable(True); b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor); tl.addWidget(b, 1)
        self.tab_log.setChecked(True)
        self.tab_log.clicked.connect(lambda: self.bottom.setCurrentIndex(0))
        self.tab_set.clicked.connect(lambda: self.bottom.setCurrentIndex(1))
        root.addWidget(tabs)
        root.addSpacing(8)

        self.bottom = QStackedWidget()
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        self.bottom.addWidget(self.log)
        self.bottom.addWidget(self._build_settings())
        self.bottom.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.bottom, 1)

        # ── справа: видео и субтитры
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(10, 18, 20, 18); rv.setSpacing(0)

        head = QHBoxLayout()
        self.toggle = QPushButton(); self.toggle.setObjectName("iconbtn")
        self.toggle.setIcon(_icon_sidebar(18)); self.toggle.setIconSize(QSize(18, 18))
        self.toggle.setFixedSize(30, 30); self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setToolTip(t("Свернуть или показать левую панель"))
        self.toggle.clicked.connect(self.toggle_sidebar)
        head.addWidget(self.toggle); head.addStretch()
        self.open_dub = QPushButton(t("Открыть перевод"))
        # cardbtnAccent, а не primary: у того отступ 15 точек под большую
        # кнопку, и при высоте 30 надпись срезается целиком.
        self.open_dub.setObjectName("cardbtnAccent")
        self.open_dub.setCursor(Qt.PointingHandCursor)
        self.open_dub.setVisible(False)
        self.open_dub.clicked.connect(self.open_result)
        head.addWidget(self.open_dub)
        head.addSpacing(8)
        self.dub_save = QPushButton(t("Сохранить перевод…"))
        self.dub_save.setVisible(False)
        self.dub_save.clicked.connect(self.save_result)
        head.addWidget(self.dub_save)
        head.addSpacing(8)
        self.subs_save = QPushButton(t("Сохранить субтитры…"))
        self.subs_save.setVisible(False)
        self.subs_save.clicked.connect(self.save_subs)
        head.addWidget(self.subs_save)
        rv.addLayout(head); rv.addSpacing(10)

        self.preview = QStackedWidget()

        # Пустая рамка без подписей: что делать, видно по полю и кнопке рядом.
        self.drop = QFrame(); self.drop.setObjectName("drop")
        self.preview.addWidget(self.drop)

        # Площадки, умеющие встраивание, показываем плеером во всю карточку:
        # название и канал он выводит сам. Остальным остаётся обложка, и вот
        # под ней подпись нужна — иначе непонятно, та ли ссылка.
        self.srv = _PlayerServer()
        self.embed = QWebEngineView()
        self.embed.page().setBackgroundColor(QColor("#232327"))

        self.link_card = QWidget(); self.link_card.setObjectName("preview")
        cv = QVBoxLayout(self.link_card)
        cv.setContentsMargins(14, 14, 14, 14); cv.setSpacing(10)
        self.cover = QLabel(); self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setMinimumHeight(120)
        cv.addWidget(self.cover, 1)
        self.linkTitle = QLabel(); self.linkTitle.setObjectName("linkTitle")
        self.linkTitle.setAlignment(Qt.AlignCenter); self.linkTitle.setWordWrap(True)
        cv.addWidget(self.linkTitle)
        self.linkHint = QLabel(); self.linkHint.setObjectName("dropHint")
        self.linkHint.setAlignment(Qt.AlignCenter)
        cv.addWidget(self.linkHint)

        self.link_view = QStackedWidget()
        self.link_view.addWidget(self.embed)
        self.link_view.addWidget(self.link_card)
        self.preview.addWidget(self.link_view)

        # Своего проигрывателя нет: перемотка в нём работала хуже системного,
        # а окно от него подвисало. Файл открывается в проигрывателе macOS.
        self.file_card = QWidget(); self.file_card.setObjectName("preview")
        fv = QVBoxLayout(self.file_card)
        fv.setContentsMargins(14, 14, 14, 14); fv.setSpacing(10)
        fv.addStretch()
        self.shot = QLabel(); self.shot.setAlignment(Qt.AlignCenter)
        fv.addWidget(self.shot)
        self.file_name = QLabel(); self.file_name.setObjectName("linkTitle")
        self.file_name.setAlignment(Qt.AlignCenter); self.file_name.setWordWrap(True)
        fv.addWidget(self.file_name)
        orow = QHBoxLayout(); orow.addStretch()
        self.open_btn = QPushButton(t("Открыть в проигрывателе"))
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_outside)
        orow.addWidget(self.open_btn); orow.addStretch()
        fv.addLayout(orow)
        fv.addStretch()
        self.preview.addWidget(self.file_card)

        # Всё правое поле — одна панель, как лента конспекта: сверху кадр,
        # под ним субтитры. Отдельно висящие блоки выглядели чужеродно.
        panel = QFrame(); panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 14, 14, 14); pl.setSpacing(12)
        pl.addWidget(self.preview)
        # Реплики отдельными карточками, а не строками списка: перевод в них
        # правится на месте, а рядом видно, с чего он сделан.
        self.subs = QScrollArea(); self.subs.setObjectName("feed")
        self.subs.setWidgetResizable(True)
        self.subs.setFrameShape(QFrame.NoFrame)
        self.subs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget(); inner.setObjectName("feedInner")
        self.subs_box = QVBoxLayout(inner)
        self.subs_box.setContentsMargins(14, 12, 14, 12); self.subs_box.setSpacing(10)
        self.subs_box.addStretch(1)
        self.subs.setWidget(inner)
        pl.addWidget(self.subs, 1)
        rv.addWidget(panel, 1)

        # Панель в прокрутке: на невысоком окне карточка иначе сминается.
        self.left_panel = QScrollArea()
        self.left_panel.setObjectName("feed")
        self.left_panel.setWidgetResizable(True)
        self.left_panel.setFrameShape(QFrame.NoFrame)
        self.left_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_panel.setWidget(left)
        split.addWidget(self.left_panel); split.addWidget(right)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1)
        split.setCollapsible(0, False); split.setCollapsible(1, False)
        # Ширину слева берём из требований раскладки: при заданной на глаз
        # подпись «Оригинал фоном» обрезалась посреди слова.
        need = left.minimumSizeHint().width()
        right.setMinimumWidth(420)
        split.setSizes([need + 20, 700])
        self.setMinimumWidth(need + right.minimumWidth() + 60)
        self.setMinimumHeight(620)
        self._build_menu()
        QTimer.singleShot(0, self._fit_player)
        QTimer.singleShot(400, self._ask_disk_access)

    def toggle_sidebar(self):
        self.left_panel.setVisible(not self.left_panel.isVisible())
        QTimer.singleShot(0, self._fit_player)     # ширина меняется не сразу

    def _fit_player(self):
        """Кадр 16:9 во всю ширину панели: обычное видео такое и есть,
        а свободная высота уходит субтитрам."""
        room = max(240, self.preview.parentWidget().width() - 28)
        self.preview.setFixedHeight(int(room * 9 / 16))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_player()

    # ── сборка мелочей
    def _fill_langs(self):
        """Языки по алфавиту того языка, на котором сейчас интерфейс."""
        import pipeline
        keep = self.lang.currentData() if self.lang.count() else "ru"
        rows = sorted(((v["ui"][i18n.current()], code, v["flag"])
                       for code, v in pipeline.TARGETS.items()),
                      key=lambda r: r[0])
        self.lang.blockSignals(True)
        self.lang.clear()
        for name, code, flag in rows:
            self.lang.addItem(f"{flag}  {name}", code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(keep)))
        self.lang.blockSignals(False)

    def _segment(self, box, items):
        """Ряд переключателей, из которых нажат ровно один."""
        seg = QFrame(); seg.setObjectName("segment")
        sl = QHBoxLayout(seg); sl.setContentsMargins(3, 3, 3, 3); sl.setSpacing(3)
        made = []
        for label, key in items:
            b = QPushButton(label)
            b.setObjectName("seg"); b.setCheckable(True); b.setAutoExclusive(True)
            b.setProperty("key", key); b.setCursor(Qt.PointingHandCursor)
            sl.addWidget(b, 1); made.append(b)
        box.addWidget(seg)
        return made

    def _card(self, box, name, role):
        """Карточка настроек: название, роль, состояние справа."""
        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 11, 14, 11); cl.setSpacing(2)
        top = QHBoxLayout(); top.setSpacing(8)
        title = QLabel(name); title.setObjectName("cardName")
        state = QLabel(); state.setObjectName("dim")
        state.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(title); top.addStretch(); top.addWidget(state)
        cl.addLayout(top)
        sub = QLabel(role); sub.setObjectName("dim")
        cl.addWidget(sub)
        box.addWidget(card)
        return card, cl, state, sub

    def _card_buttons(self, cl, *buttons):
        row = QHBoxLayout(); row.setSpacing(8); row.addStretch()
        for b in buttons:
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        cl.addSpacing(6); cl.addLayout(row)

    def _build_settings(self):
        import models_store
        page = QScrollArea(); page.setObjectName("feed")
        page.setWidgetResizable(True)
        page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget(); inner.setObjectName("feedInner")
        box = QVBoxLayout(inner); box.setContentsMargins(2, 2, 2, 2); box.setSpacing(8)

        self.model_rows = {}
        rows = [(m["repo"], models_store.short_name(m["repo"]), m["role"], m["gb"], m)
                for m in models_store.CATALOG]
        rows.append((models_store.DEMUCS_REPO, "htdemucs",
                     "Отделение голоса от фона", models_store.DEMUCS_GB,
                     {"repo": models_store.DEMUCS_REPO,
                      "gb": models_store.DEMUCS_GB, "kind": "sep"}))
        for repo, name, role, gb, meta in rows:
            card, cl, state, _ = self._card(box, name, t(role))
            bar = Bar(); bar.setVisible(False)
            cl.addSpacing(6); cl.addWidget(bar)
            act = QPushButton()
            act.clicked.connect(lambda _=False, mm=meta: self._model_action(mm))
            self._card_buttons(cl, act)
            self.model_rows[repo] = {"state": state, "act": act, "bar": bar,
                                     "meta": meta}

        card = QFrame(); card.setObjectName("card")
        cl = QVBoxLayout(card); cl.setContentsMargins(14, 11, 14, 11); cl.setSpacing(2)
        title = QLabel(t("Язык")); title.setObjectName("cardName")
        cl.addWidget(title)
        sub = QLabel(t("Язык интерфейса")); sub.setObjectName("dim")
        cl.addWidget(sub)
        row = QHBoxLayout(); row.setSpacing(8); row.addStretch()
        self.lang_btns = []
        for code, label in (("ru", "Русский"), ("en", "English")):
            b = QPushButton(label)
            b.setObjectName("cardbtnAccent" if code == i18n.current() else "cardbtn")
            b.setCursor(Qt.PointingHandCursor)
            b.setEnabled(code != i18n.current())
            b.clicked.connect(lambda _=False, c=code: self._set_lang(c))
            row.addWidget(b); self.lang_btns.append(b)
        cl.addSpacing(6); cl.addLayout(row)
        box.addWidget(card)
        box.addStretch(1)
        sign = QLabel(f'Dubl · {AUTHOR} · <a href="{SITE_URL}">{SITE}</a>')
        sign.setObjectName("dim"); sign.setAlignment(Qt.AlignCenter)
        sign.setOpenExternalLinks(True)
        box.addWidget(sign)
        page.setWidget(inner)
        self._refresh_models()
        return page

    def _refresh_models(self):
        import models_store
        for repo, w in self.model_rows.items():
            if repo in self._downloading:
                continue          # у качающейся строки своя надпись и свой ход
            gb = w["meta"]["gb"]
            ready = (models_store.demucs_ready() if repo == models_store.DEMUCS_REPO
                     else models_store.is_ready(repo, gb))
            size = models_store.size_on_disk(repo)
            w["state"].setText(models_store.human(size) if ready
                               else t("нет, скачать ") + f"{gb:g}" + t(" ГБ"))
            w["act"].setText(t("Удалить") if ready else t("Скачать"))
            w["act"].setObjectName("cardbtn" if ready else "cardbtnAccent")
            w["act"].setStyleSheet("")

    def _model_action(self, m):
        import models_store
        repo = m["repo"]
        if repo in self._downloading:
            self._downloading[repo].stop()      # недокачанное докачается потом
            return
        ready = (models_store.demucs_ready() if repo == models_store.DEMUCS_REPO
                 else models_store.is_ready(repo, m["gb"]))
        if ready:
            if not self._confirm(t("Удалить модель"),
                                 t("Удалить ") + models_store.short_name(repo)
                                 + t(" с диска?"), t("Удалить")):
                return
            models_store.delete(repo)
            self._refresh_models()
            return
        w = self.model_rows[repo]
        w["act"].setText(t("Отмена")); w["act"].setObjectName("cardbtn")
        w["act"].setStyleSheet("")
        w["bar"].setVisible(True); w["bar"].set_progress(0, 1)
        dl = self._keep(DownloadWorker(repo))
        self._downloading[repo] = dl
        dl.progress.connect(
            lambda a, b, ww=w, g=m["gb"]: (
                ww["bar"].set_progress(a, b),
                ww["state"].setText(models_store.human(a) + t(" из ")
                                    + f"{g:g}" + t(" ГБ"))))
        dl.done.connect(lambda ok, msg, r=repo: self._download_done(r, ok, msg))
        dl.start()

    def _download_done(self, repo, ok, msg):
        self._downloading.pop(repo, None)
        w = self.model_rows[repo]
        w["bar"].setVisible(False)
        self._refresh_models()
        if not ok:
            QMessageBox.warning(self, t("Не скачалось"), msg)

    def _confirm(self, title, text, ok):
        """Свои надписи на кнопках: штатные Yes/No остаются английскими."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.NoIcon)
        box.setWindowTitle(title); box.setText(text)
        yes = box.addButton(ok, QMessageBox.YesRole)
        box.setDefaultButton(box.addButton(t("Отмена"), QMessageBox.NoRole))
        box.exec()
        return box.clickedButton() is yes

    def _build_menu(self):
        """Пункт «О программе»: на macOS уходит в меню приложения."""
        bar = QMenuBar(self)
        self.about_act = QAction(tf("О программе {name}", name="Dubl"), self)
        self.about_act.setMenuRole(QAction.AboutRole)
        self.about_act.triggered.connect(self.show_about)
        bar.addMenu("Dubl").addAction(self.about_act)

    def show_about(self):
        box = QMessageBox(self)
        box.setIconPixmap(app_icon().pixmap(72, 72))
        box.setTextFormat(Qt.RichText)
        box.setText("<b>Dubl</b>")
        box.setInformativeText(
            f'<nobr>{AUTHOR} · <a href="{SITE_URL}">{SITE}</a></nobr>')
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        for lab in box.findChildren(QLabel):
            lab.setOpenExternalLinks(True)
        box.addButton(t("Закрыть"), QMessageBox.AcceptRole)
        box.exec()

    def _keep(self, worker):
        """Ссылка на поток нужна до конца run(): без неё Qt валит приложение."""
        self._alive.append(worker)
        worker.finished.connect(lambda w=worker: self._alive.remove(w))
        return worker

    def _ask_disk_access(self):
        """Один раз при первом запуске. Cookies браузера открывают площадки,
        которые отдают видео только вошедшим; какой браузер — выясняем сами,
        а Safari вдобавок требует полного доступа к диску."""
        import source
        if self.settings.value("cookies_asked"):
            return
        self.settings.setValue("cookies_asked", "1")
        if source.cookie_browsers():
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.NoIcon)
        box.setWindowTitle(t("Доступ к диску"))
        box.setText(t("Полный доступ к диску позволяет разбирать больше сервисов."))
        box.setInformativeText(t("Разрешите доступ в системных настройках "
                                 "и перезапустите Dubl."))
        go = box.addButton(t("Открыть настройки"), QMessageBox.YesRole)
        box.setDefaultButton(box.addButton(t("Позже"), QMessageBox.NoRole))
        box.exec()
        if box.clickedButton() is go:
            import subprocess
            subprocess.run(["open", DISK_ACCESS])

    def _set_lang(self, code):
        if code == i18n.current():
            return
        i18n.set_current(code)
        self.retranslate()

    def retranslate(self):
        """Перевод собранного окна: ключ ищется по видимой надписи."""
        self.about_act.setText(tf("О программе {name}", name="Dubl"))
        for w in self.findChildren(QWidget):
            for get, put in ((getattr(w, "text", None), getattr(w, "setText", None)),
                             (getattr(w, "placeholderText", None),
                              getattr(w, "setPlaceholderText", None)),
                             (getattr(w, "toolTip", None), getattr(w, "setToolTip", None))):
                if not (get and put):
                    continue
                try:
                    cur = get()
                except TypeError:            # у некоторых text() требует аргумент
                    continue
                key = i18n.key_of(cur) if cur else None
                if key:
                    put(t(key))
        self.spk.setItemText(0, t("Определить самому"))
        self._fill_langs()
        self._refresh_models()
        for b, code in zip(self.lang_btns, ("ru", "en")):
            b.setObjectName("cardbtnAccent" if code == i18n.current() else "cardbtn")
            b.setEnabled(code != i18n.current())
            b.setStyleSheet("")

    # ── выбор источника
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = Path(u.toLocalFile())
            if p.suffix.lower() in VIDEO_EXT:
                self.set_src(p)
                break

    def choose(self):
        f, _ = QFileDialog.getOpenFileName(
            self, t("Выберите видео"), str(Path.home()),
            t("Видео (*.mp4 *.mov *.m4v *.mkv *.avi *.webm)"))
        if f:
            self.set_src(Path(f))

    def set_src(self, p):
        self.link = ""
        self.url.blockSignals(True); self.url.setText(p.name); self.url.blockSignals(False)
        self.src = p
        self._clear_result()
        self.show_file(p)
        self.go.setEnabled(True)

    def _url_typed(self, text):
        """Поле — единственное место, где видно выбранное: правка в нём снимает
        и файл с диска, иначе прикреплённое видео нечем убрать."""
        import source
        text = text.strip()
        if source.is_url(text):
            self._url_wait.start()
            return
        if self.src and text == self.src.name:
            return                               # имя файла на месте, всё как было
        self.src = None
        self.on_url()

    def on_url(self):
        """Обложка и название подтверждают, что ссылка та самая."""
        import source
        text = self.url.text().strip()
        self.link = text if source.is_url(text) else ""
        self.src = None
        self.link_meta = {}
        self._clear_result()
        if not self.link:
            self.embed.setUrl("about:blank")
            self.preview.setCurrentWidget(self.drop)
            self.go.setEnabled(False)
            return
        self.linkTitle.setText(t("Проверка ссылки…"))
        self.linkHint.setText(""); self.cover.clear()
        emb = embed_url(self.link)
        if emb:
            self.embed.setUrl(self.srv.url(emb))
            self.link_view.setCurrentWidget(self.embed)
        else:
            self.embed.setUrl("about:blank")
            self.link_view.setCurrentWidget(self.link_card)
        self.preview.setCurrentWidget(self.link_view)
        self.go.setEnabled(False)
        w = self._keep(_Call(lambda u=self.link: self._link_info(u)))
        w.ready.connect(lambda d, u=self.link: self._show_link(d, u))
        w.start()

    @staticmethod
    def _link_info(url):
        import source
        try:
            m = source.meta(url)
        except Exception as e:
            return {"error": str(e)}
        if m["thumbnail"]:
            m["cover"] = str(source.thumbnail(
                m["thumbnail"], Path(tempfile.gettempdir()) / "dubl_cover.jpg") or "")
        return m

    def _show_link(self, d, url):
        if url != self.link:
            return                      # ссылку уже сменили, ответ опоздал
        if d.get("error"):
            self.linkTitle.setText(t(d["error"])); self.linkHint.setText("")
            return
        self.link_meta = d
        self.linkTitle.setText(d["title"])
        mins, secs = divmod(d["duration"], 60)
        self.linkHint.setText(" · ".join(x for x in (d["channel"],
                                                     f"{mins}:{secs:02d}") if x))
        if d.get("cover") and self.link_view.currentWidget() is self.link_card:
            pm = QPixmap(d["cover"])
            if not pm.isNull():
                self.cover.setPixmap(pm.scaled(self.cover.width() or 420, 150,
                                               Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation))
        self.go.setEnabled(True)

    def _busy(self, on):
        for w in (self.go, self.pick, self.url, self.spk,
                  self.lang, *self.modes, *self.speeds, *self.sound):
            w.setEnabled(not on)

    # ── запуск
    def start(self):
        if not (self.src or self.link):
            return
        self._clear_result()
        import pipeline
        target = self.lang.currentData()
        way = pipeline.TARGETS[target]["ui"][i18n.current()]
        if self.link:
            self.tmp = Path(tempfile.mkdtemp(prefix="dubl_"))
            name = self._safe(self.link_meta.get("title", "")) or t("Видео")
            dst, src = self.tmp / f"{name} — {way}.mp4", ""
        else:
            dst = self._free_path(self.src.parent,
                                  f"{self._safe(self.src.stem)} — {way}",
                                  self.src.suffix)
            src = str(self.src)
        mode = next(b.property("key") for b in self.modes if b.isChecked())
        speed = next(b.property("key") for b in self.speeds if b.isChecked())
        self.log.clear(); self._ticking = False
        self.tab_log.setChecked(True); self.bottom.setCurrentIndex(0)
        self._busy(True)
        self.cancel.setVisible(True); self.cancel.setEnabled(True)
        self.progress.setVisible(True)
        sound = next(b.property("key") for b in self.sound if b.isChecked())
        self.worker = self._keep(Worker(
            src, str(dst), self.spk.currentData(), sound, mode,
            link=self.link, workdir=str(self.tmp) if self.tmp else None,
            target=target, model_id=MODELS.get(speed, MODELS["good"]),
            tone=speed == "tone"))
        self.worker.line.connect(self._plain)
        self.worker.tick.connect(self.on_tick)
        self.worker.step.connect(self.on_step)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.cancelled.connect(self.on_cancelled)
        self.worker.needs_access.connect(self.on_needs_access)
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.cancel.setEnabled(False)
            self.stage.setText(t("Остановка…"))

    def on_cancelled(self):
        self.bar.set_busy(False)
        self.stage.setText(" ")
        self._busy(False); self.cancel.setVisible(False)
        self.progress.setVisible(False)
        self._clear_result()
        self.log.appendPlainText(t("Отменено."))

    def on_tick(self, text):
        """Ход скачивания переписывает последнюю строку, а не плодит новые:
        иначе на большом файле журнал разрастается на тысячи строк и окно
        начинает подтормаживать."""
        cur = self.log.textCursor()
        cur.movePosition(QTextCursor.End)
        if self._ticking:
            cur.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
            cur.removeSelectedText()
        else:
            if not self.log.document().isEmpty():
                cur.insertBlock()
            self._ticking = True
        cur.insertText(text)
        self.log.setTextCursor(cur)

    def _plain(self, text):
        self._ticking = False
        self.log.appendPlainText(text)

    def on_step(self, name, cur, total):
        self.stage.setText(t(name) + "…" + (f"   {cur} / {total}" if total > 1 else ""))
        if total > 1:
            self.bar.set_progress(cur, total)
        else:
            self.bar.set_busy(True)

    def on_done(self, r):
        self.bar.set_busy(False); self.bar.set_progress(1, 1)
        self.stage.setText(t("Готово"))
        self._busy(False); self.cancel.setVisible(False)
        # Предпросмотр остаётся на оригинале: перевод открывается кнопкой.
        self.dub_file = Path(r["out"])
        self.open_dub.setVisible(True); self.dub_save.setVisible(True)
        self.log.appendPlainText(tf("Реплик: {u}, голосов: {v}",
                                    u=r["utterances"], v=r["voices"]))
        self.work_dir = r.get("workdir") or self.work_dir
        self._load_subs(self.work_dir)
        if self.link:
            self.result = out           # лежит во временной папке, ждёт решения
            self.after.setVisible(True)

    def on_needs_access(self, msg):
        """Отказ, который лечится разрешением: показываем, куда идти."""
        self.bar.set_busy(False)
        self.stage.setText(" ")
        self._busy(False); self.cancel.setVisible(False)
        self.progress.setVisible(False)
        self._plain(msg)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.NoIcon)
        box.setTextFormat(Qt.RichText)
        box.setWindowTitle(t("Нужно разрешение"))
        box.setText(msg.split("\n\n")[0].replace("\n", "<br>"))
        box.setInformativeText(
            f'<a href="{DISK_ACCESS}">' + t("Открыть настройки доступа") + "</a>"
            + "<br><br>" + t("Системные настройки → Конфиденциальность и "
                             "безопасность → Полный доступ к диску"))
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        for lab in box.findChildren(QLabel):
            lab.setOpenExternalLinks(True)
        box.addButton(t("Закрыть"), QMessageBox.AcceptRole)
        box.exec()

    def on_failed(self, msg):
        self.bar.set_busy(False); self.bar.set_progress(0, 1)
        self.stage.setText(t("Ошибка"))
        self._busy(False); self.cancel.setVisible(False)
        self.log.appendPlainText(msg)
        QMessageBox.critical(self, t("Не получилось"), msg.split("\n\n")[0])

    # ── что делать с готовым
    def show_file(self, path):
        """Кадр из середины и имя файла: смотреть — в системном проигрывателе."""
        import subprocess, tempfile
        self.shown = Path(path)
        self.file_name.setText(self.shown.name)
        self.shot.clear()
        thumb = Path(tempfile.gettempdir()) / "dubl_shot.jpg"
        try:
            import pipeline
            dur = pipeline.duration(self.shown)
            subprocess.run([pipeline.FFMPEG, "-y", "-v", "error", "-ss",
                            str(max(0.0, dur / 3)), "-i", str(self.shown),
                            "-frames:v", "1", "-vf", "scale=-2:220", str(thumb)],
                           capture_output=True)
            pm = QPixmap(str(thumb))
            if not pm.isNull():
                self.shot.setPixmap(pm)
        except Exception:
            pass
        self.preview.setCurrentWidget(self.file_card)

    def open_result(self):
        if getattr(self, "dub_file", None) and self.dub_file.exists():
            import subprocess
            subprocess.run(["open", str(self.dub_file)])

    def open_outside(self):
        """Отдаём файл системе: проигрыватель macOS умеет и перемотку,
        и полный экран, и субтитровые дорожки внутри файла."""
        import subprocess
        if getattr(self, "shown", None) and self.shown.exists():
            subprocess.run(["open", str(self.shown)])

    def _load_subs(self, workdir):
        """Реплики из разбора: перевод правится, оригинал рядом для сверки."""
        import json
        self._clear_subs()
        self.sub_rows, self.sub_edits = [], []
        if not workdir:
            return
        f = Path(workdir) / "utterances.json"
        if not f.exists():
            return
        try:
            utts = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return
        for u in utts:
            if not u.get("ru"):
                continue
            self.sub_rows.append((float(u["start"]), float(u["end"]),
                                  u["text"].strip(), u["ru"].strip()))
        for a, b, orig, tr in self.sub_rows:
            self.subs_box.insertWidget(self.subs_box.count() - 1,
                                       self._sub_card(a, orig, tr))
        self.subs_save.setVisible(bool(self.sub_rows))

    def _clear_subs(self):
        while self.subs_box.count() > 1:
            w = self.subs_box.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _sub_card(self, at, orig, tr):
        card = QFrame(); card.setObjectName("card")
        v = QVBoxLayout(card); v.setContentsMargins(14, 11, 14, 11); v.setSpacing(4)
        head = QLabel(self._clock(at)); head.setObjectName("dim")
        v.addWidget(head)

        cap = QLabel(t("Перевод")); cap.setObjectName("dim")
        v.addWidget(cap)
        # QTextEdit, а не QPlainTextEdit: у второго высота документа считается
        # в абзацах, а не в точках, и поле не подогнать под текст.
        edit = QTextEdit(tr); edit.setObjectName("subEdit")
        edit.setAcceptRichText(False)
        edit.setFrameShape(QFrame.NoFrame)
        edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        edit.setReadOnly(True)                    # правка начинается по кнопке
        edit.textChanged.connect(lambda e=edit: self._fit_edit(e))
        # Ширина меняется при свёртке панели — высоту пересчитываем следом.
        edit.resizeEvent = lambda ev, e=edit: (QTextEdit.resizeEvent(e, ev),
                                               self._fit_edit(e))
        v.addWidget(edit)
        self.sub_edits.append(edit)
        QTimer.singleShot(0, lambda e=edit: self._fit_edit(e))

        cap2 = QLabel(t("Оригинал")); cap2.setObjectName("dim")
        v.addSpacing(4); v.addWidget(cap2)
        src = QLabel(orig); src.setObjectName("dim")
        src.setWordWrap(True); src.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(src)

        row = QHBoxLayout(); row.setContentsMargins(0, 6, 0, 0); row.addStretch()
        btn = QPushButton(t("Изменить")); btn.setObjectName("cardbtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _=False, e=edit, b=btn: self._edit_card(e, b))
        row.addWidget(btn)
        v.addLayout(row)
        return card

    def _edit_card(self, edit, btn):
        """Первое нажатие открывает правку, второе — отправляет на переозвучку."""
        if edit.isReadOnly():
            edit.setReadOnly(False)
            edit.setFocus()
            btn.setText(t("Переозвучить")); btn.setObjectName("cardbtnAccent")
            btn.setStyleSheet("")
            return
        self.apply_edits()

    @staticmethod
    def _fit_edit(edit):
        """Поле растёт под текст: своей прокрутки у реплики быть не должно.
        Ширину берём с запасом — до первой раскладки viewport ещё нулевой."""
        doc = edit.document()
        doc.setTextWidth(max(200, edit.viewport().width()))
        edit.setFixedHeight(max(32, int(doc.size().height()) + 12))

    @staticmethod
    def _clock(sec):
        return f"{int(sec) // 60}:{int(sec) % 60:02d}"

    def apply_edits(self):
        """Переозвучка по тексту из карточек: правки уже внесены на месте."""
        if not self.sub_rows or not self.sub_edits:
            return
        self.sub_rows = [(a, b, orig, e.toPlainText().strip() or tr)
                         for (a, b, orig, tr), e in zip(self.sub_rows, self.sub_edits)]
        self.restart_voice()

    def restart_voice(self):
        """Разбор и перевод уже сделаны, повторяем только синтез."""
        if not self.work_dir or not self.dub_file:
            return
        import json
        f = Path(self.work_dir) / "utterances.json"
        try:
            utts = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return
        for u, (a, b, orig, tr) in zip([x for x in utts if x.get("ru")],
                                       self.sub_rows):
            u["ru"] = tr
        f.write_text(json.dumps(utts, ensure_ascii=False, indent=1),
                     encoding="utf-8")
        self.log.clear(); self._ticking = False
        self.tab_log.setChecked(True); self.bottom.setCurrentIndex(0)
        self._busy(True)
        self.cancel.setVisible(True); self.cancel.setEnabled(True)
        self.progress.setVisible(True)
        sound = next(b.property("key") for b in self.sound if b.isChecked())
        mode = next(b.property("key") for b in self.modes if b.isChecked())
        target = self.lang.currentData()
        self.worker = self._keep(Redub(
            str(self.dub_file), str(self.dub_file), utts, self.work_dir,
            target=target, voice_mode=mode, background=sound,
            tone=next(b.property("key") for b in self.speeds if b.isChecked()) == "tone"))
        self.worker.line.connect(self._plain)
        self.worker.tick.connect(self.on_tick)
        self.worker.step.connect(self.on_step)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.cancelled.connect(self.on_cancelled)
        self.worker.start()

    def save_subs(self):
        """Двойные субтитры одним файлом: сверху перевод, снизу оригинал."""
        if not self.sub_rows:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, t("Сохранить субтитры"),
            str(Path.home() / "Movies" / "subtitles.srt"), "SubRip (*.srt)")
        if not path:
            return

        def stamp(sec):
            h, m = int(sec) // 3600, int(sec) // 60 % 60
            s, ms = int(sec) % 60, int(sec * 1000) % 1000
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        out = []
        for i, (a, b, orig, tr) in enumerate(self.sub_rows, 1):
            out.append(f"{i}\n{stamp(a)} --> {stamp(b)}\n{tr}\n{orig}\n")
        Path(path).write_text("\n".join(out), encoding="utf-8")
        self._plain(t("Сохранено: ") + path)

    @staticmethod
    def _safe(name):
        return "".join(c for c in name if c not in '/\\:*?"<>|')[:80]

    @staticmethod
    def _free_path(folder, base, ext):
        """Свободное имя: «… 2», «… 3». Иначе система переспрашивает про замену."""
        path, n = Path(folder) / f"{base}{ext}", 1
        while path.exists():
            n += 1
            path = Path(folder) / f"{base} {n}{ext}"
        return path

    def save_result(self):
        """Готовый перевод на диск. По ссылке он лежит во временной папке и
        уносится оттуда, файлу с диска — просто копия рядом."""
        src = self.result or self.dub_file
        if not src or not Path(src).exists():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, t("Сохранить перевод"),
            str(self._free_path(Path.home() / "Movies", Path(src).stem, ".mp4")),
            t("Видео (*.mp4)"))
        if not path:
            return
        if self.result:
            shutil.move(str(self.result), path)
        else:
            shutil.copy(str(src), path)
        self._plain(t("Сохранено: ") + path)
        self.result = None
        self._clear_result()
        self.dub_file = Path(path)
        self.open_dub.setVisible(True); self.dub_save.setVisible(True)

    def discard_result(self):
        self._clear_result()
        self.preview.setCurrentWidget(self.link_view if self.link else self.drop)
        self.log.appendPlainText(t("Удалено"))

    def _clear_result(self):
        """Временную папку уносим целиком: в ней и дубляж, и рабочие файлы."""
        self.after.setVisible(False)
        self.open_dub.setVisible(False); self.dub_save.setVisible(False)
        self.dub_file = None
        self.result = None
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None

    def closeEvent(self, e):
        for w in list(self._alive):
            if hasattr(w, "stop"):
                w.stop()
            w.wait(3000)
        self.embed.setUrl("about:blank")
        self._clear_result()
        super().closeEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Dubl")
    w = Window(); w.show()
    sys.exit(app.exec())
