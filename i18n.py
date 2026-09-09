"""Язык интерфейса. Ключ перевода — сама русская строка."""
from PySide6.QtCore import QLocale, QSettings

LANGS = ("ru", "en")

EN = {
    # источник
    "Ссылка на видео": "Video link",
    "Выбрать файл…": "Choose file…",
    "Выберите видео": "Choose a video",
    "Видео (*.mp4 *.mov *.m4v *.mkv *.avi *.webm)":
        "Video (*.mp4 *.mov *.m4v *.mkv *.avi *.webm)",
    "Проверка ссылки…": "Checking the link…",
    "По этой ссылке видео не нашлось.": "No video was found at this link.",
    "Открыть в проигрывателе": "Open in the player",
    "Открыть перевод": "Open the dub",

    # настройки
    "Настройки": "Settings",
    "Куда переводим": "Translate into", "Точно": "Accurate",
    "Что нужно": "What to do",
    "Быстро": "Fast", "Качественно": "Best quality",
    "Как в оригинале": "Same voice", "Подобрать": "Pick one",
    "Сколько голосов": "How many voices",
    "Язык озвучки": "Dubbing language",
    "Б": "B", "КБ": "KB", "МБ": "MB", "ГБ": "GB",
    "  {pct}% из {size} {unit}": "  {pct}% of {size} {unit}",
    ", осталось {eta}": ", {eta} left",
    "Извлечение звука…": "Extracting audio…",
    "Распознавание речи…": "Speech recognition…",
    "  реплик: {n}, язык: {lang}": "  lines: {n}, language: {lang}",
    "Разделение голосов…": "Separating voices…",
    "  голосов: {a}, цельных реплик: {b}": "  voices: {a}, merged lines: {b}",
    "  фон и голос разделены": "  background and voice separated",
    "  отделить фон не удалось: {e}": "  could not separate the background: {e}",
    "  очистить образец не удалось: {e}": "  could not clean the sample: {e}",
    "  для голосов {v} чистого образца нет — берётся общий":
        "  no clean sample for voices {v} — using a shared one",
    "Перевод…": "Translating…",
    "  справка по ролику: ": "  video brief: ",
    "  голоса: ": "  voices: ",
    "Г{k} — {v}": "V{k} — {v}",
    "мужчина": "male", "женщина": "female",
    "  не перевелось реплик: {n} — ": "  lines left untranslated: {n} — ",
    "{sec} с": "{sec} s",
    "Подгонка длины реплик…": "Fitting line lengths…",
    "  переформулировано короче: {a} из {b}": "  shortened: {a} of {b}",
    "Озвучка…": "Voicing…",
    "  Г{spk}: {look}": "  V{spk}: {look}",
    "  подобрать голос не вышло: {e}": "  could not pick a voice: {e}",
    "    образец {n}: {gender} {f0} Гц, {dur} с":
        "    sample {n}: {gender} {f0} Hz, {dur} s",
    "  интонацию снять не удалось: {e}": "  could not read the intonation: {e}",
    "  образца голоса нет, реплика пропущена": "  no voice sample, line skipped",
    "  реплика {n} пропущена: {e}": "  line {n} skipped: {e}",
    "Сборка дорожки…": "Assembling the track…",
    "Готово: {out}": "Done: {out}",
    "  ускорено: {a}, переформулировано: {b}": "  sped up: {a}, reworded: {b}",
    "  с интонацией оригинала: {a} из {b}": "  with the original intonation: {a} of {b}",
    "  сильно ускорено ({n}): ": "  heavily sped up ({n}): ",
    "С интонациями": "With intonation",
    "Перенос интонации работает нестабильно": "Intonation transfer is unreliable",
    "Разбор интонации…": "Reading the intonation…",
    "Определить самому": "Detect automatically",
    "Убрать голос": "Strip the voice", "Только дубляж": "Dub only",
    "Оригинал фоном": "Original underneath",
    "Отделение фона": "Separating the background",
    "Отделение фона от голоса…": "Separating background from voice…",
    "Перевод, режим «Быстро»": "Translation, Fast mode",
    "Перевод, режим «Качественно»": "Translation, Best quality mode",
    "Озвучка голосом оригинала": "Voicing, same voice",
    "Озвучка подобранным голосом": "Voicing, picked voice",
    "Загрузка моделей синтеза…": "Loading the speech models…",
    "Распознавание речи": "Speech recognition",
    "Отделение голоса от фона": "Separating voice from background",
    "Скачать": "Download", "Удалить модель": "Delete model",
    "Удалить ": "Delete ", " с диска?": " from disk?",
    "нет, скачать ": "not installed, ", " ГБ": " GB", " из ": " of ",
    "Не скачалось": "Download failed",
    "Доступ к диску": "Disk access",
    "Нужно разрешение": "Permission required",
    "Этот сервис отдаёт видео только с разрешением.\nДайте полный доступ к диску и перезапустите приложение.":
        "This service serves video only with permission.\n"
        "Grant full disk access and restart the app.",
    "Открыть настройки доступа": "Open access settings",
    "Системные настройки → Конфиденциальность и безопасность → Полный доступ к диску":
        "System Settings → Privacy & Security → Full Disk Access",
    "Полный доступ к диску позволяет разбирать больше сервисов.":
        "Full disk access lets the app handle more services.",
    "Разрешите доступ в системных настройках и перезапустите Dubl.":
        "Grant access in System Settings and restart Dubl.",
    "Открыть настройки": "Open Settings", "Позже": "Later",
    "Язык": "Language",
    "Язык интерфейса": "Interface language",
    "Русский": "Русский", "English": "English",

    # работа
    "Озвучить": "Dub it",
    "Ход работы": "Progress",
    "Субтитры": "Subtitles",
    "Свернуть или показать левую панель": "Hide or show the left panel",
    "Изменить": "Edit", "Переозвучить": "Re-voice",
    "Перевод": "Translation", "Оригинал": "Original",
    "Сохранить перевод…": "Save the dub…", "Сохранить перевод": "Save the dub",
    "Видео": "Video",
    "Сохранить субтитры…": "Save subtitles…",
    "Сохранить субтитры": "Save subtitles", "Удалить": "Delete",
    "Видео (*.mp4)": "Video (*.mp4)",
    "Сохранено: ": "Saved: ",
    "Удалено": "Deleted",
    "Готово": "Done", "Ошибка": "Error",
    "Не получилось": "Something went wrong",
    "Исходное видео удалено": "The source video has been deleted",
    "Отменено": "Cancelled",
    "В ролике нет речи — переводить и озвучивать нечего.":
        "The video has no speech — nothing to translate or voice.",
    "Видео скачать не удалось.": "The video could not be downloaded.",
    "О программе {name}": "About {name}",
    "Закрыть": "Close",
    "Реплик: {u}, голосов: {v}": "Lines: {u}, voices: {v}",
    "Отмена": "Cancel", "Отменено.": "Cancelled.", "Остановка…": "Stopping…",
    "Скачивание видео": "Downloading the video",
    "Скачивание видео…": "Downloading the video…",
    "» заняло ": "» took ", "Всего ": "Total ",
    "Извлечение звука": "Extracting audio",
    "Распознавание речи": "Speech recognition",
    "Разделение голосов": "Separating voices",
    "Перевод": "Translating",
    "Подгонка длины": "Fitting length",
    "Озвучка": "Voicing",
    "Сборка дорожки": "Building the track",
}

_lang = None


def current():
    """Настройка важнее системного языка."""
    global _lang
    if _lang is None:
        saved = QSettings("local", "Dubl").value("lang", "")
        if saved in LANGS:
            _lang = saved
        else:
            _lang = "ru" if QLocale.system().language() == QLocale.Russian else "en"
    return _lang


def set_current(lang):
    global _lang
    if lang in LANGS:
        _lang = lang
        QSettings("local", "Dubl").setValue("lang", lang)


def key_of(text):
    """Русский ключ по видимой надписи — для перевода собранного окна."""
    return text if text in EN else _BACK.get(text)


_BACK = {v: k for k, v in EN.items() if v != k}


def tf(fmt, **kw):
    return t(fmt).format(**kw)


def t(s):
    return EN.get(s, s) if current() == "en" else s
