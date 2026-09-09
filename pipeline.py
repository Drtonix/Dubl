"""Дубляж видео: распознавание -> разделение голосов -> перевод -> озвучка -> сборка.

Всё считается локально: mlx-whisper распознаёт речь, sherpa-onnx разделяет
голоса, demucs отделяет музыку, mlx-lm переводит, Qwen3-TTS озвучивает.
"""
import json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

from i18n import t, tf

HERE = Path(__file__).resolve().parent


def _tool(name):
    """Программа из бандла, затем из PATH, затем из обычных мест установки."""
    inside = HERE / "bin" / name
    if inside.exists():
        return str(inside)
    found = shutil.which(name)
    if found:
        return found
    for base in ("/opt/homebrew/bin", "/usr/local/bin"):
        if (Path(base) / name).exists():
            return str(Path(base) / name)
    return name          # пусть падает с внятным «not found», а не с чужим путём


FFMPEG, FFPROBE = _tool("ffmpeg"), _tool("ffprobe")
# Куда переводим. Проверки на язык нужны обе: что нужный текст появился и что
# чужой не остался — модель любит бросить непереведённое слово посреди фразы.
# Языки озвучки. Список ограничен синтезом: он знает эти десять и больше ничего.
# Исходный язык не ограничен — его определяет распознавание.
#
# cps — знаков в секунду, из них считается бюджет длины реплики. Замерено
# 9 сентября 2026: одна и та же фраза, синтез, обрезка тишины по краям.
# Русский и английский оставлены на прежних значениях, они проверены работой.
LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")
HAN = re.compile(r"[\u4e00-\u9fff]")
KANA = re.compile(r"[\u3040-\u30ff]")
HANGUL = re.compile(r"[\uac00-\ud7af\u1100-\u11ff]")

TARGETS = {
    "ru": {"name": "русский", "loc": "русском", "iso": "rus", "ui": {"ru": "Русский", "en": "Russian"}, "flag": "🇷🇺", "tts": "Russian",
           "script": CYRILLIC, "cps": 14, "num": "ru",
           "leftover": re.compile(r"(?<![A-Za-z])[a-z]{3,}(?![A-Za-z])"),
           "left_msg": "В русской фразе остались английские слова: ",
           "gender": "Говорит {g}, используй соответствующий род глаголов.\n"},
    "en": {"name": "английский", "loc": "английском", "iso": "eng", "ui": {"ru": "Английский", "en": "English"}, "flag": "🇬🇧", "tts": "English",
           "script": LATIN, "cps": 15, "num": "en",
           "leftover": re.compile(r"[а-яё]{3,}", re.I),
           "left_msg": "В английской фразе остались русские слова: "},
    "es": {"name": "испанский", "loc": "испанском", "iso": "spa", "ui": {"ru": "Испанский", "en": "Spanish"}, "flag": "🇪🇸", "tts": "Spanish",
           "script": LATIN, "cps": 17, "num": "es",
           "gender": "Говорит {g}, согласуй прилагательные и причастия по роду.\n"},
    "fr": {"name": "французский", "loc": "французском", "iso": "fra", "ui": {"ru": "Французский", "en": "French"}, "flag": "🇫🇷", "tts": "French",
           "script": LATIN, "cps": 18, "num": "fr",
           "gender": "Говорит {g}, согласуй прилагательные и причастия по роду.\n"},
    "de": {"name": "немецкий", "loc": "немецком", "iso": "deu", "ui": {"ru": "Немецкий", "en": "German"}, "flag": "🇩🇪", "tts": "German",
           "script": LATIN, "cps": 17, "num": "de"},
    "it": {"name": "итальянский", "loc": "итальянском", "iso": "ita", "ui": {"ru": "Итальянский", "en": "Italian"}, "flag": "🇮🇹", "tts": "Italian",
           "script": LATIN, "cps": 15, "num": "it",
           "gender": "Говорит {g}, согласуй прилагательные и причастия по роду.\n"},
    "pt": {"name": "португальский", "loc": "португальском", "iso": "por", "ui": {"ru": "Португальский", "en": "Portuguese"}, "flag": "🇵🇹", "tts": "Portuguese",
           "script": LATIN, "cps": 15, "num": "pt",
           "gender": "Говорит {g}, согласуй прилагательные и причастия по роду.\n"},
    "ja": {"name": "японский", "loc": "японском", "iso": "jpn", "ui": {"ru": "Японский", "en": "Japanese"}, "flag": "🇯🇵", "tts": "Japanese",
           "script": re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]"), "cps": 5, "num": "ja"},
    "ko": {"name": "корейский", "loc": "корейском", "iso": "kor", "ui": {"ru": "Корейский", "en": "Korean"}, "flag": "🇰🇷", "tts": "Korean",
           "script": HANGUL, "cps": 7, "num": "ko"},
    # Китайские числительные — те же иероглифы, что и цифры: num2words не нужен.
    "zh": {"name": "китайский", "loc": "китайском", "iso": "zho", "ui": {"ru": "Китайский", "en": "Chinese"}, "flag": "🇨🇳", "tts": "Chinese",
           "script": HAN, "cps": 6, "num": None},
}

# Какие письменности считать чужими. У японского и корейского список свой:
# кандзи, кана и латиница в именах там законны.
_ALIEN = {"ru": (HAN, KANA, HANGUL),
          "ja": (CYRILLIC, HANGUL),
          "ko": (CYRILLIC, KANA),
          "zh": (CYRILLIC, KANA, HANGUL)}

for _code, _t in TARGETS.items():
    _t["alien"] = _ALIEN.get(_code, (CYRILLIC, HAN, KANA, HANGUL))
    _t.setdefault("gender", "")
    _t.setdefault("leftover", None)
    _t.setdefault("left_msg", "")
    _t["native"] = f"Native {_t['tts']} speaker, no accent."
    _t["traits"] = ["calm, natural", "lively, energetic",
                    "warm, friendly", "confident, composed"]
    _t["insist"] = (f"ВЕСЬ ответ должен быть на {_t['loc']} языке, целиком, "
                    "без слов на других языках.")


def _alien(text, own, others):
    """Доля букв чужих письменностей. Латиница у испанского и французского одна
    и та же, поэтому по алфавиту их не различить — но кириллицу или иероглифы
    посреди испанской фразы видно сразу. Список чужих у каждого языка свой:
    в японском кандзи и кана свои, а латиница в именах законна."""
    mine = len(own.findall(text)) or 1
    return max(len(r.findall(text)) for r in others) / mine


def _same_text(a, b):
    """Ответ совпал с оригиналом — значит фразу не перевели, а переписали."""
    def words(x):
        return {w for w in re.findall(r"\w+", x.lower()) if len(w) > 2}
    wa, wb = words(a), words(b)
    return bool(wa) and len(wa & wb) / len(wa | wb) > 0.7

MAX_SPEEDUP = 1.25       # предел ускорения, дальше слышно тараторку
MAX_SPEEDUP_TIGHT = 1.4  # крайний случай: лучше быстрее, чем перебить следующего
MAX_BORROW = 1.5         # сколько секунд тишины перед репликой можно занять
MAX_DRIFT = 1.2          # насколько реплика может опоздать, если предыдущая затянулась


def _free_gpu():
    """Отдать память видеоядра. Соседние этапы держат свои модели, и без
    явной уборки они соревнуются за одну и ту же память."""
    import gc
    gc.collect()
    try:
        import mlx.core as mx
        mx.clear_cache()
    except Exception:
        pass


class Cancelled(Exception):
    """Пользователь нажал «Отмена»."""


class NoSpeech(Exception):
    """В ролике нет речи: озвучивать нечего."""


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)

def duration(path):
    out = run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)]).stdout.strip()
    return float(out)


# ---------------------------------------------------------------- этапы

def extract_audio(video, wav):
    run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])


def extract_audio_hq(video, wav):
    """Дорожка под образцы голоса. Распознаванию хватает 16 кГц, но клонировать
    по ней нельзя: всё выше восьми килогерц срезано, и голос выходит глухим и
    непохожим. Синтез работает на 24 кГц — столько и берём."""
    run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(wav)])

# Полная large-v3, а не turbo: у turbo заметно больше ошибок в словах и он
# договаривает несуществующее в конце записи. Замерено 9 сентября 2026 —
# «long fronts» вместо «long trunks», плюс две минуты выдуманного текста за
# краем часового ролика. По скорости разницы нет, на длинном файле полная даже
# быстрее: 15.1x против 12.2x реального времени.
def local_model(repo):
    """Путь к уже скачанной модели вместо её имени на хабе.

    По имени и mlx-whisper, и mlx-lm каждый раз идут на huggingface сверять
    версию. Через прокси этот запрос рвётся с RemoteProtocolError, и работа
    падает на модели, которая давно лежит на диске.
    """
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(repo, local_files_only=True)
    except Exception:
        return repo          # не скачана — пусть тянет обычным путём


def transcribe(wav, model="mlx-community/whisper-large-v3-mlx"):
    import mlx_whisper, re as _re
    total = duration(wav)
    r = mlx_whisper.transcribe(str(wav), path_or_hf_repo=local_model(model), verbose=False)
    lang = r.get("language", "en")
    segs = []
    for s in r["segments"]:
        t = s["text"].strip()
        if not t or s["end"] - s["start"] < 0.2:
            continue
        # Whisper дорисовывает несуществующую речь за концом звука — в замерах
        # он выдал 96 секунд на 75-секундной дорожке, вместе с иероглифами.
        if s["start"] >= total - 0.5:
            continue
        # На тишине и шуме Whisper дорисовывает иероглифы. Отбрасываем только те,
        # что не совпадают с языком записи: на китайском ролике иероглифы — это
        # и есть речь. Язык, которого нет в таблице, не проверяем вовсе.
        own = TARGETS.get(lang)
        if own and _alien(t, own["script"], own["alien"]) > 0.5:
            continue
        # На ролике без речи Whisper всё равно что-нибудь напишет. Порог тот же,
        # что у самой модели: тишина вероятнее речи и текст низкой уверенности.
        if (s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -1.0):
            continue
        if segs and segs[-1]["text"] == t and s["start"] - segs[-1]["end"] < 1.0:
            continue                      # и зацикливание на затухании
        segs.append({"start": s["start"], "end": min(s["end"], total), "text": t})
    return segs, lang

def diarize(wav, num_speakers=0):
    import sherpa_onnx, soundfile as sf
    seg_model = HERE / "models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
    emb_model = HERE / "models/nemo_en_titanet_large.onnx"
    clustering = (sherpa_onnx.FastClusteringConfig(num_clusters=num_speakers)
                  if num_speakers else sherpa_onnx.FastClusteringConfig(threshold=0.95))
    # 0.95 подобран по замерам: меньший порог дробит одного человека на несколько
    # голосов, и тогда он звучит разными тембрами — это заметнее, чем слияние двоих.
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(seg_model)), num_threads=4),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(emb_model), num_threads=4),
        clustering=clustering, min_duration_on=0.3, min_duration_off=0.5)
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    audio, _ = sf.read(str(wav), dtype="float32")
    out = [{"start": r.start, "end": r.end, "speaker": r.speaker}
           for r in sd.process(audio).sort_by_start_time()]
    return out if num_speakers else _keep_real_speakers(out)


def _keep_real_speakers(diar, min_share=0.06, min_seconds=20.0):
    """Отсев случайных голосов. На ролике с одним ведущим разделение находит
    второго на одну секунду из одиннадцати минут — и тот получает свой тембр
    в дубляже. Короткие голоса приписываем ближайшему настоящему."""
    if not diar:
        return diar
    talk = {}
    for d in diar:
        talk[d["speaker"]] = talk.get(d["speaker"], 0.0) + d["end"] - d["start"]
    total = sum(talk.values())
    keep = {k for k, v in talk.items() if v >= max(min_seconds, total * min_share)}
    if not keep:
        keep = {max(talk, key=talk.get)}
    if len(keep) == len(talk):
        return diar
    kept = [d for d in diar if d["speaker"] in keep]
    for d in diar:
        if d["speaker"] in keep:
            continue
        m = (d["start"] + d["end"]) / 2
        near = min(kept, key=lambda k: 0 if k["start"] <= m <= k["end"]
                   else min(abs(m - k["start"]), abs(m - k["end"])))
        d["speaker"] = near["speaker"]
    order = {k: i for i, k in enumerate(sorted(keep))}
    for d in diar:
        d["speaker"] = order[d["speaker"]]
    return diar

def _embedder():
    import sherpa_onnx
    return sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(HERE / "models/nemo_en_titanet_large.onnx"), num_threads=4))


def _embed(ext, audio, sr, a, b):
    """Отпечаток голоса на отрезке [a,b]. None, если отрезок слишком короткий."""
    import numpy as np
    i, j = max(0, int(a * sr)), min(len(audio), int(b * sr))
    if j - i < int(0.35 * sr):
        return None
    st = ext.create_stream()
    st.accept_waveform(sample_rate=sr, waveform=audio[i:j])
    st.input_finished()
    if not ext.is_ready(st):
        return None
    v = np.array(ext.compute(st), dtype="float32")
    n = np.linalg.norm(v)
    return v / n if n else None


def assign_speakers(segs, diar, wav=None):
    """Кто говорит в реплике. Пересечение по времени промахивается на стыках,
    поэтому решает сам голос: сравниваем отпечаток реплики с эталоном каждого."""
    import numpy as np, soundfile as sf

    def by_time(a, b):
        best, ov_ = None, 0.0
        for d in diar:
            ov = min(b, d["end"]) - max(a, d["start"])
            if ov > ov_:
                best, ov_ = d["speaker"], ov
        if best is not None:
            return best
        m = (a + b) / 2
        return min(diar, key=lambda d: 0 if d["start"] <= m <= d["end"]
                   else min(abs(m - d["start"]), abs(m - d["end"])))["speaker"]

    if not diar:
        for s in segs:
            s["speaker"] = 0
        return segs

    centroids = {}
    if wav is not None:
        try:
            audio, sr = sf.read(str(wav), dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            ext = _embedder()
            acc = {}
            for d in sorted(diar, key=lambda d: d["start"] - d["end"]):   # длинные первыми
                v = _embed(ext, audio, sr, d["start"], d["end"])
                if v is not None:
                    acc.setdefault(d["speaker"], []).append(v)
            for spk, vs in acc.items():
                c = np.mean(vs, axis=0)
                n = np.linalg.norm(c)
                if n:
                    centroids[spk] = c / n
        except Exception:
            centroids = {}

    for s in segs:
        spk = by_time(s["start"], s["end"])
        if centroids:
            v = _embed(ext, audio, sr, s["start"], s["end"])
            if v is not None:
                sim = {k: float(v @ c) for k, c in centroids.items()}
                best = max(sim, key=sim.get)
                second = sorted(sim.values())[-2] if len(sim) > 1 else -1.0
                # Доверяем голосу, только когда он уверенно ближе к одному эталону.
                if sim[best] - second > 0.05:
                    spk = best
        s["speaker"] = spk
    return segs

def group_utterances(segs):
    """Обрывки Whisper -> цельные реплики: по обрывкам перевод разваливается."""
    out, cur = [], None
    for s in segs:
        if cur:
            same = s["speaker"] == cur["speaker"]
            gap = s["start"] - cur["end"] > 1.0
            open_ = not re.search(r"[.!?]\s*$", cur["text"]) or len(cur["text"]) < 40
            if same and not gap and open_:
                cur["text"] += " " + s["text"]; cur["end"] = s["end"]; continue
            out.append(cur)
        cur = dict(s)
    if cur:
        out.append(cur)
    return out

def _yin_f0(seg, sr, lo_hz=70, hi_hz=400, thresh=0.15):
    """Основной тон по YIN. Обычная автокорреляция цепляется за гармонику и
    ошибается ровно вдвое: то мужской голос читается женским, то наоборот.
    Здесь берётся первый провал разностной функции ниже порога — он и есть
    настоящий период, а не самый глубокий, который часто кратен ему."""
    import numpy as np
    n = len(seg)
    lo, hi = int(sr / hi_hz), min(int(sr / lo_hz), n // 2)
    if hi <= lo:
        return None
    corr = np.correlate(seg, seg, mode="full")[n - 1:][:hi + 1]
    cs = np.concatenate(([0.0], np.cumsum(seg.astype(np.float64) ** 2)))
    tau = np.arange(hi + 1)
    head = cs[n - tau]          # энергия начала окна
    tail = cs[n] - cs[tau]      # энергия сдвинутой копии
    d = head + tail - 2 * corr
    dn = np.ones_like(d)
    run = np.cumsum(d[1:])
    dn[1:] = d[1:] * tau[1:] / np.maximum(run, 1e-12)   # нормировка YIN
    below = np.where(dn[lo:hi + 1] < thresh)[0]
    i = int(below[0] + lo) if len(below) else int(dn[lo:hi + 1].argmin() + lo)
    # Порог пересекается на спуске, поэтому сползаем до самого дна ямы —
    # иначе период выходит короче настоящего и тон завышается на несколько процентов.
    while i + 1 <= hi and dn[i + 1] < dn[i]:
        i += 1
    k = float(i)
    if 0 < i < hi:                     # уточняем дно параболой по соседям
        a0, b0, c0 = dn[i - 1], dn[i], dn[i + 1]
        den = a0 - 2 * b0 + c0
        if abs(den) > 1e-12:
            k = i + 0.5 * (a0 - c0) / den
    return sr / k if k > 0 else None


def estimate_gender(wav_path):
    """Пол по основному тону. Мужской обычно 85-165 Гц, женский 165-255.
    Нужен для перевода: в русском прошедшее время зависит от рода говорящего,
    и без этого модель пишет «я пришла» про мужчину."""
    import numpy as np, soundfile as sf
    a, sr = sf.read(str(wav_path), dtype="float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    win = int(0.045 * sr)
    f0s = []
    for i in range(0, len(a) - win, win):
        seg = a[i:i + win]
        if np.abs(seg).max() < 0.02:
            continue
        seg = seg - seg.mean()
        f0 = _yin_f0(seg, sr)
        if f0 and 70 <= f0 <= 400:
            f0s.append(f0)
    if len(f0s) < 8:                  # на паре кадров медиана ничего не значит
        return None, None
    med = float(np.median(f0s))
    return ("женщина" if med > 165 else "мужчина"), round(med)


def pick_voice_refs(utts, wav, outdir):
    """По чистому куску речи на каждого: синтез клонирует по паре звук+расшифровка."""
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    best = {}
    for u in utts:
        d = u["end"] - u["start"]
        if not (3.0 <= d <= 10.0):
            continue
        spk = str(u["speaker"])
        if spk not in best or d > best[spk]["dur"]:
            best[spk] = {"start": u["start"], "dur": d, "text": u["text"]}
    # Ни одна реплика не уложилась в окно 3-10 с — в коротком ролике вся речь
    # бывает одной длинной репликой. Тогда берём её целиком: звук и расшифровка
    # обязаны совпадать, иначе синтез повторяет чужой текст вместо перевода.
    if not best:
        for u in utts:
            spk = str(u["speaker"])
            d = min(u["end"] - u["start"], 25.0)
            if d < 1.0:
                continue
            if spk not in best or d > best[spk]["dur"]:
                best[spk] = {"start": u["start"], "dur": d, "text": u["text"]}

    good = {}
    for spk, v in best.items():
        f = outdir / f"speaker{spk}.wav"
        try:
            run([FFMPEG, "-y", "-v", "error", "-ss", str(v["start"]), "-i", str(wav),
                 "-t", str(v["dur"]), "-ac", "1", "-ar", "24000", str(f)])
            # Кусок у самого конца дорожки даёт пустой файл — такой образец бесполезен
            # и валит озвучку пятисоткой, поэтому проверяем на месте.
            if duration(f) < 1.0:
                continue
        except Exception:
            continue
        v["file"] = str(f)
        v["gender"], v["f0"] = estimate_gender(f)
        good[spk] = v
    return good


def clean_refs(refs, log=print):
    """Убирает музыку из образцов голоса. Нужно, когда разделения дорожек не
    было: по миксу тон меряется по басовой партии, а не по певцу — на песне
    выходило 127 Гц вместо 253, то есть мужчина вместо женщины. Образцы
    короткие, поэтому проход занимает секунды, а не минуты."""
    for v in refs.values():
        f = Path(v["file"])
        try:
            _, voice = split_voice(f, f.with_name(f"{f.stem}_rest.wav"),
                                   f.with_name(f"{f.stem}_voice.wav"),
                                   log=lambda _m: None)
            run([FFMPEG, "-y", "-v", "error", "-i", str(voice),
                 "-ac", "1", "-ar", "24000", str(f)])
            voice.unlink(missing_ok=True)
            f.with_name(f"{f.stem}_rest.wav").unlink(missing_ok=True)
            v["gender"], v["f0"] = estimate_gender(f)
        except Exception as e:
            log(tf("  очистить образец не удалось: {e}", e=e))
    return refs


# ---------------------------------------------------------------- перевод

# Реплики переводятся по одной. Партиями быстрее на треть (замерено на
# шестнадцати репликах: 51 секунда против 74), но текст заметно портится —
# «дно из картофеля дафинойз» вместо «пюре из картофеля в стиле дафинойз».

TRANSLATE_RULES = (
    "Ты профессиональный переводчик кино и интервью. Переводишь для озвучки поверх видео.\n"
    "— живая разговорная речь, как реально говорят;\n"
    "— идиомы и термины передавай принятыми эквивалентами, не буквально;\n"
    "— названия фильмов, сериалов, игр, компаний и продуктов оставляй в "
    "оригинале, как они написаны, и не придумывай им перевод;\n"
    "— имена людей передавай привычным написанием;\n"
    "— НИЧЕГО не добавляй от себя: если в оригинале нет слова, его нет и в переводе;\n"
    "— числа, проценты и символы пиши СЛОВАМИ в нужном падеже "
    "(«в ста процентах случаев», «через двадцать лет»), а не цифрами;\n"
    "— в ответе только перевод, без вступлений и кавычек.\n")

# Имена и названия: подряд идущие слова с заглавной, не в начале фразы.
# Общее правило «не переводи названия» модель игнорирует, а перечень
# конкретных слов держит.
NAME_RUN = re.compile(r"\b([A-Z][\w'’-]*(?:\s+(?:of|the|and|de|la)\s+|\s+)"
                      r"?(?:[A-Z][\w'’-]*)?(?:\s+[A-Z][\w'’-]*)*)")
STOP_WORDS = {"i", "the", "a", "an", "but", "and", "so", "if", "he", "she",
              "it", "they", "we", "you", "this", "that", "there", "then",
              "when", "what", "why", "how", "now", "well", "yeah", "okay",
              "did", "do", "does", "is", "was", "were", "in", "on", "at"}


def proper_names(text, limit=8):
    """Названия и имена из фразы. Первое слово предложения не берём: заглавная
    там ничего не значит."""
    found, out = [], []
    for m in NAME_RUN.finditer(text):
        run = m.group(1).strip()
        if not run:
            continue
        before = text[:m.start()].rstrip()
        if not before or before[-1] in ".!?":
            words = run.split()
            if len(words) < 2:
                continue                  # одиночное слово в начале — не имя
            run = " ".join(words[1:]) if words[0].lower() in STOP_WORDS else run
        if run.lower() in STOP_WORDS or len(run) < 3:
            continue
        if run not in found:
            found.append(run)
    for run in found:
        if not any(run != o and run in o for o in found):
            out.append(run)
    return out[:limit]


_PREAMBLE = re.compile(r"^\s*(вот\s+)?(перевод|возможный перевод|результат)\s*[:：]?\s*$", re.I)

def _pick(text):
    for line in text.splitlines():
        line = line.strip().strip('"«»')
        if line and not _PREAMBLE.match(line):
            return re.sub(r"^(вот\s+)?перевод\s*[:：]\s*", "", line, flags=re.I).strip()
    return ""

class Translator:
    def __init__(self, model_id, target="ru"):
        from mlx_lm import load
        from mlx_lm.sample_utils import make_sampler
        self.model, self.tok = load(local_model(model_id))
        self.sampler = make_sampler(temp=0.2, top_p=0.9)
        self.rules = TRANSLATE_RULES
        self.t = TARGETS[target]
        self.code, self.src_lang = target, ""
        self.lang = self.t["name"]
        self._cache, self._head, self._head_ids = None, 0, []

    def _prompt(self, text, tokens=False):
        return self.tok.apply_chat_template([{"role": "user", "content": text}],
                                            add_generation_prompt=True,
                                            enable_thinking=False,
                                            tokenize=tokens)

    @staticmethod
    def _clean(text):
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    def _gen(self, user, max_tokens=600):
        from mlx_lm import generate
        ids = self._prompt(user, tokens=True)
        if self._cache is not None and ids[:self._head] == self._head_ids:
            # Общее начало запроса уже просчитано: подаём только хвост.
            from mlx_lm.models.cache import trim_prompt_cache
            r = generate(self.model, self.tok, prompt=ids[self._head:],
                         max_tokens=max_tokens, sampler=self.sampler,
                         prompt_cache=self._cache, verbose=False)
            trim_prompt_cache(self._cache, self._cache[0].offset - self._head)
            return self._clean(r)
        r = generate(self.model, self.tok, prompt=ids,
                     max_tokens=max_tokens, sampler=self.sampler, verbose=False)
        return self._clean(r)

    def prime(self, samples):
        """Просчитать общее начало запросов один раз.

        Правила перевода и справка по ролику повторяются в каждой реплике, и
        на плотной модели их разбор стоит дороже самого перевода: 577 токенов
        запроса — 4.8 с из 5.8 с. Кэш снимает эту часть со всех реплик, кроме
        первой, и на текст ответа не влияет никак.
        """
        from mlx_lm import generate
        from mlx_lm.models.cache import make_prompt_cache, trim_prompt_cache
        ids = [self._prompt(x, tokens=True) for x in samples[:2]]
        if len(ids) < 2:
            return
        n = 0
        for a, b in zip(*ids):
            if a != b:
                break
            n += 1
        if n < 64:                      # общего начала почти нет, кэш не окупится
            return
        self._head_ids = ids[0][:n]
        self._head = n
        self._cache = make_prompt_cache(self.model)
        generate(self.model, self.tok, prompt=self._head_ids, max_tokens=1,
                 sampler=self.sampler, prompt_cache=self._cache, verbose=False)
        trim_prompt_cache(self._cache, self._cache[0].offset - n)

    def forget(self):
        self._cache, self._head, self._head_ids = None, 0, []

    def _gen_many(self, prompts, max_tokens=600, should_stop=None):
        out = []
        for q in prompts:
            if should_stop and should_stop():
                raise Cancelled()
            out.append(self._gen(q, max_tokens))
        return out

    def _ok(self, text, src=""):
        """Ответ на нужном языке и без чужих кусков.

        Проверок три, потому что одной алфавитной мало: она ловит кириллицу в
        английской фразе, но испанский от французского не отличает. Поэтому
        дополнительно смотрим на долю чужой письменности и на совпадение с
        оригиналом — фраза, которую просто переписали, переводом не является.
        """
        if not text or not self.t["script"].search(text):
            return False
        lo = self.t["leftover"]
        if lo and lo.search(text):
            return False
        if _alien(text, self.t["script"], self.t["alien"]) > 0.25:
            return False
        return not (src and self.src_lang != self.code and _same_text(text, src))

    def brief(self, utts):
        """Короткая справка по всему ролику. Без неё модель переводит реплики
        вслепую и не узнаёт ни кулинарных терминов, ни названий мест."""
        full = " ".join(u["text"] for u in utts)[:6000]
        q = ("Ниже расшифровка видео. Составь справку для переводчика "
             f"на {self.lang} язык:\n"
             "1) о чём видео и в какой оно обстановке;\n"
             "2) кто участники, если понятно;\n"
             f"3) имена собственные, названия мест и блюд — и как писать их "
             f"на {self.lang} (в формате «оригинал — {self.lang}»).\n"
             f"Справку пиши на {self.lang}, кроме пункта 3, где оригинал уместен. "
             "Уложись в 10 строк, без вступлений и без повторов.\n\n" + full)
        b = self._gen(q, max_tokens=700).strip()
        # Испорченная справка хуже её отсутствия: она подкладывается в каждый
        # перевод и тянет за собой свои же ошибки. Проверяем и при сомнении бракуем.
        lines = [l for l in b.splitlines() if l.strip()]
        looped = len(lines) != len(set(lines))
        own = len(self.t["script"].findall(b))
        if not b or looped or own < 100 or _alien(b, self.t["script"],
                                                  self.t["alien"]) > 0.4:
            return ""
        return b

    def _one_prompt(self, utts, i, genders, brief):
        u = utts[i]
        ctx = ""
        if i:
            ctx += f"(до этого прозвучало: {utts[i-1]['text']})\n"
        if i + 1 < len(utts):
            ctx += f"(дальше прозвучит: {utts[i+1]['text']})\n"
        g = (genders or {}).get(str(u.get("speaker")))
        gline = self.t["gender"].format(g=g) if g and self.t["gender"] else ""
        # Целимся в длину сразу: подобрать синоним короче дешевле, чем потом
        # ужимать готовую фразу или разгонять её темп при озвучке.
        nxt = utts[i + 1]["start"] if i + 1 < len(utts) else u["end"] + 1.0
        budget = int(max(0.5, nxt - u["start"]) * self.t["cps"])
        lline = (f"Реплика должна звучать примерно {budget} знаков: подбирай более "
                 f"короткие синонимы и убирай слова-паразиты, но смысл сохраняй "
                 f"полностью.\n")
        bline = (f"\nСправка по ролику (для понимания, переводить её НЕ надо):\n{brief}\n"
                 if brief else "")
        # Постоянное — правила и справка — идёт первым: тогда у всех реплик
        # общее начало запроса, и модель разбирает его один раз на весь ролик.
        names = proper_names(u["text"])
        nline = ("Эти названия и имена оставь ровно как есть, не переводя и не "
                 "меняя написание: " + ", ".join(names) + ".\n") if names else ""
        return (self.rules + bline + "\n" + nline + gline + lline
                + "\nКонтекст только для понимания, переводить его НЕ надо:\n"
                + ctx + f"\nПереведи на {self.lang} ТОЛЬКО эту фразу, одной строкой:\n"
                + u["text"])

    def translate_all(self, utts, genders=None, progress=None, brief=None,
                      src_lang="", should_stop=lambda: False):
        """Перевод всех реплик ролика."""
        self.src_lang = src_lang
        prompts = [self._one_prompt(utts, i, genders, brief) for i in range(len(utts))]
        self.prime(prompts)
        got = [""] * len(utts)
        for i, q in enumerate(prompts):
            if should_stop():
                raise Cancelled()
            got[i] = _pick(self._gen(q))
            if progress:
                progress(i + 1, len(prompts))

        # Повтор только для тех, где язык не тот: перегонять всю партию заново
        # дороже, чем добить десяток отказов.
        for attempt in range(2):
            bad = [i for i, r in enumerate(got) if not self._ok(r, utts[i]["text"])]
            if not bad:
                break
            fixes = self._gen_many([prompts[i] + "\n\n" + self.t["insist"] for i in bad],
                                   should_stop=should_stop)
            for i, raw in zip(bad, fixes):
                r = _pick(raw)
                if r and (self._ok(r, utts[i]["text"]) or not got[i]):
                    got[i] = r

        # Осталось чужое слово — просим заменить точечно, а не переводить
        # фразу заново: так остальной текст не пострадает.
        spot = ([i for i, r in enumerate(got)
                 if r and not self._ok(r, utts[i]["text"])
                 and self.t["leftover"].findall(r)] if self.t["leftover"] else [])
        if spot:
            asks = [self.t["left_msg"]
                    + ", ".join(sorted(set(self.t["leftover"].findall(got[i])))[:5])
                    + f". Замени их на {self.lang} по смыслу, остальное не трогай. "
                    "Ответь только исправленной фразой.\n\n" + got[i] for i in spot]
            for i, raw in zip(spot, self._gen_many(asks, max_tokens=300,
                                                   should_stop=should_stop)):
                fix = _pick(raw)
                if fix and self._ok(fix, utts[i]["text"]):
                    got[i] = fix

        # Пустой ответ — это не «переводить нечего», а сбой разбора: правила,
        # справка и контекст сбили модель, и она ответила рассуждением. Просим
        # голым запросом, на нём срывов почти не бывает.
        empty = [i for i, r in enumerate(got) if not r]
        if empty:
            asks = [f"Переведи на {self.lang} одной строкой, без пояснений "
                    f"и без кавычек:\n{utts[i]['text']}" for i in empty]
            for i, raw in zip(empty, self._gen_many(asks, max_tokens=300,
                                                    should_stop=should_stop)):
                got[i] = _pick(raw)

        for u, r in zip(utts, got):
            u["ru"] = r
        return utts

    def translate_one(self, text, gender=None):
        g = f"Говорит {gender}, используй соответствующий род глаголов.\n" if gender else ""
        q = (self.rules + "\n" + g +
             f"\nПереведи на {self.lang} ТОЛЬКО эту фразу, одной строкой:\n" + text)
        return _pick(self._gen(q))

    def shorten_all(self, items, should_stop=lambda: False):
        """Пакетное сокращение: [(индекс, текст, предел)] -> {индекс: короче}."""
        if not items:
            return {}
        asks = [TRANSLATE_RULES
                + f"\nСократи фразу до {lim} знаков. Убирай слова-паразиты, "
                  "повторы и вводные, но СМЫСЛ и все факты обязаны остаться теми же. "
                  "Ничего не добавляй от себя. Ответь только сокращённой фразой.\n\n"
                + txt for _, txt, lim in items]
        out = {}
        for (i, txt, _), raw in zip(items, self._gen_many(asks, max_tokens=250,
                                                          should_stop=should_stop)):
            r = _pick(raw)
            if r and len(r) < len(txt) and self._keeps_sense(txt, r):
                out[i] = r
        return out

    @staticmethod
    def _keeps_sense(text, short):
        """Сжатие любит подменить фразу соседней или дописать своё — проверяем,
        что от исходной осталась хотя бы половина значимых слов."""
        def key_words(t):
            return {w.lower().strip(".,!?:;«»\"'-")[:5] for w in t.split() if len(w) > 4}
        a, b = key_words(text), key_words(short)
        return not a or len(a & b) / len(a) >= 0.5

    def shorten(self, text, limit):
        q = (TRANSLATE_RULES + f"\nСократи фразу до {limit} знаков. Убирай слова-паразиты, "
             f"повторы и вводные, но СМЫСЛ и все факты обязаны остаться теми же. "
             f"Ничего не добавляй от себя. Ответь только сокращённой фразой.\n\n{text}")
        r = _pick(self._gen(q, max_tokens=250))
        if not r or len(r) >= len(text):
            return text
        # Сжатие любит подменить фразу соседней или дописать своё — проверяем,
        # что от исходной осталась хотя бы половина значимых слов.
        def key_words(t):
            return {w.lower().strip(".,!?:;«»\"'-")[:5]
                    for w in t.split() if len(w) > 4}
        a, b = key_words(text), key_words(r)
        if a and len(a & b) / len(a) < 0.5:
            return text
        return r


# ---------------------------------------------------------------- озвучка

def _plural_ru(n, one, few, many):
    n = abs(int(n)) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


PERCENT = {"en": "percent", "es": "por ciento", "fr": "pour cent",
           "de": "Prozent", "it": "per cento", "pt": "por cento",
           "ja": "パーセント", "ko": "퍼센트"}


def spell_out(text, target="ru"):
    """Цифры и знаки словами. Синтез читает «100%» и «20» на своём родном языке,
    поэтому в чужой реплике они звучат не тем языком — это слышно сразу."""
    from num2words import num2words
    lang = TARGETS[target]["num"]
    if not lang:
        return text

    def pct(m):
        n = int(m.group(1))
        word = (_plural_ru(n, "процент", "процента", "процентов") if target == "ru"
                else PERCENT.get(target, "percent"))
        return f"{num2words(n, lang=lang)} {word}"

    text = re.sub(r"(\d+)\s*%", pct, text)
    # Пробелы вокруг числа обязательны: «C10H15N» без них превращается в
    # «CдесятьHпятнадцатьN», и синтез проглатывает буквы формулы.
    text = re.sub(r"\d+",
                  lambda m: " " + num2words(int(m.group(0)), lang=lang) + " ", text)
    signs = ((("&", " и "), ("№", "номер "), ("+", " плюс "), ("=", " равно "))
             if target == "ru" else
             (("&", " and "), ("№", "number "), ("+", " plus "), ("=", " equals ")))
    for a, b in signs:
        text = text.replace(a, b)
    return re.sub(r"\s{2,}", " ", text).strip()


def describe_voice(gender, f0, index, target="ru", pace=None):
    """Словесный портрет голоса для режима «Подобрать». Из трёх слов синтез
    выдумывает что угодно, поэтому описываем всё, что удалось измерить: пол,
    высоту тона, возрастную окраску, темп речи — и отдельно оговариваем чистую
    запись без акцента, иначе он добавляет шум и придыхания.

    Портрет всегда английский, даже когда озвучиваем по-русски: замерено
    9 сентября 2026 на восьми образцах — с русским описанием синтез попадал в
    пол в пяти случаях из восьми, с английским во всех восьми.
    """
    t = TARGETS[target]
    woman = gender == "женщина"
    hz = f0 or (200 if woman else 120)

    if woman:
        band = "low" if hz < 190 else "high" if hz > 230 else "medium"
        age = "mature" if hz < 190 else "young" if hz > 235 else "adult"
    else:
        band = "very low" if hz < 100 else "high" if hz > 145 else "medium"
        age = "older" if hz < 100 else "young" if hz > 150 else "adult"
    speed = "measured" if (pace or 13) < 11 else "brisk" if (pace or 13) > 16 else "even"

    years = {"older": "mature, over forty", "mature": "mature, over forty",
             "adult": "adult, around thirty-five",
             "young": "young, around twenty-five"}[age]
    tempo = {"measured": "unhurried pace", "even": "even pace",
             "brisk": "brisk pace"}[speed]
    body = "chesty" if band in ("very low", "low") else "light" if band == "high" else "warm"
    who = "Female" if woman else "Male"
    return (f"{who} voice, {years}. {band.capitalize()} {body} timbre, "
            f"pitch around {round(hz)} Hz, {tempo}, "
            f"{t['traits'][index % len(t['traits'])]}. "
            f"Natural conversational delivery, no theatrics. "
            f"Clean studio recording: no music, echo or noise, even loudness. "
            f"{t['native']}")


def design_refs(tts, refs, utts, outdir, target="ru", log=print, tries=3):
    """Подбирает по голосу на говорящего и возвращает их как образцы для клона.

    Синтез по описанию каждый раз выдумывает голос заново: на одном описании
    три вызова подряд дали 113, 201 и 179 Гц — мужчину и двух женщин. Поэтому
    голос подбирается один раз, проверяется по полу и высоте, и дальше все
    реплики говорятся клоном с этого образца.
    """
    out = {}
    for i, spk in enumerate(sorted(refs)):
        v = refs[spk]
        said = [u for u in utts if str(u["speaker"]) == spk and u.get("ru")]
        if not said:
            out[spk] = v
            continue
        secs = sum(u["end"] - u["start"] for u in said)
        pace = (sum(len(u["text"]) for u in said) / secs) if secs > 1 else None
        look = describe_voice(v.get("gender"), v.get("f0"), i, target, pace)
        log(tf("  Г{spk}: {look}", spk=spk, look=look))
        # Фраза для образца — своя же речь, но короткая. Проверено: с образца
        # на 17.7 с клон каждый раз говорит новым голосом (235, 173, 186 Гц),
        # с шестисекундного держит один (158, 160, 169 Гц).
        text = ""
        for u in said:
            if len(text) > 70:
                break
            text = (text + " " + u["ru"]).strip()
        if len(text) > 110:
            text = text[:110].rsplit(" ", 1)[0]
        best = None
        for n in range(tries):
            sample = Path(outdir) / f"voice{spk}_{n}.wav"
            try:
                tts.design(spell_out(text, target), look, sample,
                           TARGETS[target]["tts"])
            except Exception as e:
                log(tf("  подобрать голос не вышло: {e}", e=e))
                break
            dur = duration(sample)
            gender, f0 = estimate_gender(sample)
            far = abs((f0 or 0) - (v.get("f0") or f0 or 0))
            fits = (gender == v.get("gender") if v.get("gender") else True) and 2.5 <= dur <= 12
            log(tf("    образец {n}: {gender} {f0} Гц, {dur} с", n=n + 1,
                   gender=t(gender or "?"), f0=f0 or "?", dur=f"{dur:.1f}"))
            if best is None or (fits, -far) > (best[0], -best[1]):
                best = (fits, far, sample)
            if fits and far < 25:
                break
        if best is None:
            out[spk] = v
            continue
        trim_silence(best[2])
        out[spk] = dict(v, file=str(best[2]), text=text)
    return out


class TTS:
    """Синтез речи двумя моделями Qwen3-TTS. Base говорит голосом с образца,
    VoiceDesign — по словесному портрету. Обе держатся в памяти видеоядра,
    поэтому ненужную отпускаем сразу, как только она отработала."""

    CLONE = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16"
    DESIGN = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-bf16"
    SR = 24000

    def __init__(self):
        self.loaded = {}

    def _model(self, repo):
        if repo not in self.loaded:
            from mlx_audio.tts.utils import load_model
            self.loaded[repo] = load_model(local_model(repo))
        return self.loaded[repo]

    def load_models(self, progress=None):
        if progress:
            progress(t("Загрузка моделей синтеза…"))
        self._model(self.CLONE)

    def _write(self, chunks, out_wav, text):
        import numpy as np, soundfile as sf
        parts = [np.asarray(c.audio).reshape(-1) for c in chunks]
        if not parts:
            raise RuntimeError(f"Синтез не дал звука для: {text[:60]}")
        sf.write(str(out_wav), np.concatenate(parts).astype("float32"), self.SR)

    def clone(self, text, ref_wav, ref_text, out_wav, language="Russian"):
        m = self._model(self.CLONE)
        self._write(list(m.generate(text=text, ref_audio=str(ref_wav),
                                    ref_text=ref_text)), out_wav, text)

    def design(self, text, description, out_wav, language="Russian"):
        m = self._model(self.DESIGN)
        self._write(list(m.generate_voice_design(text=text, instruct=description,
                                                 language=language)), out_wav, text)

    def free(self, repo=None):
        for key in ([repo] if repo else list(self.loaded)):
            self.loaded.pop(key, None)
        _free_gpu()


# ---------------------------------------------------------------- тайминг и сборка

def _atempo_chain(rate):
    """ffmpeg меняет темп множителями 0.5..2.0 за раз — при нужде цепляем несколько."""
    parts, r = [], rate
    while r > 2.0:
        parts.append("atempo=2.0"); r /= 2.0
    while r < 0.5:
        parts.append("atempo=0.5"); r /= 0.5
    parts.append(f"atempo={r:.4f}")
    return ",".join(parts)

def trim_silence(path, thresh=0.012, pad=0.03, sr_out=24000):
    """Срезает тишину по краям. синтез дописывает 200 мс в конец, плюс синтез
    обычно начинается с паузы — это чистый резерв, который иначе съедает окно."""
    import numpy as np, soundfile as sf
    a, sr = sf.read(str(path), dtype="float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    loud = np.abs(a) > thresh
    if not loud.any():
        return
    i, j = int(loud.argmax()), int(len(loud) - loud[::-1].argmax())
    i = max(0, i - int(pad * sr))
    j = min(len(a), j + int(pad * sr))
    sf.write(str(path), a[i:j], sr)


def fit_segment(src, dst, available, max_speedup=MAX_SPEEDUP):
    """Ужимает реплику в отведённое окно. Возвращает (итоговая длительность, во сколько ускорили)."""
    d = duration(src)
    if d <= available or available <= 0.05:
        shutil.copy(src, dst)
        return d, 1.0
    rate = min(d / available, max_speedup)
    run([FFMPEG, "-y", "-v", "error", "-i", str(src),
         "-filter:a", _atempo_chain(rate), "-ar", "24000", "-ac", "1", str(dst)])
    return duration(dst), rate

def assemble_track(pieces, total_seconds, out_wav, sr=24000):
    """Раскладывает реплики по их местам на общей дорожке."""
    import numpy as np, soundfile as sf
    loaded = []
    for p in pieces:
        a, _ = sf.read(p["file"], dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        loaded.append((int(p["start"] * sr), a))
    # Реплика могла сдвинуться к самому концу — берём длину с запасом под неё,
    # иначе последний кусок не помещается в буфер.
    need = max([i + len(a) for i, a in loaded], default=0)
    track = np.zeros(max(int(total_seconds * sr) + sr, need + sr), dtype="float32")
    for i, a in loaded:
        n = min(len(a), len(track) - i)
        if n > 0:
            track[i:i + n] += a[:n]
    track = track[:int(total_seconds * sr) + sr]
    peak = float(abs(track).max()) or 1.0
    if peak > 0.99:
        track *= 0.99 / peak
    sf.write(str(out_wav), track, sr)

# ---------------------------------------------------------------- пение

HOP = 5.0            # мс между кадрами вокодера


def _world():
    """Вокодер WORLD. Его __init__ лезет в pkg_resources только за номером
    версии, а в setuptools 84 того больше нет — подставляем заглушку."""
    import types
    if "pkg_resources" not in sys.modules:
        stub = types.ModuleType("pkg_resources")
        stub.get_distribution = lambda name: types.SimpleNamespace(version="0")
        sys.modules["pkg_resources"] = stub
    import pyworld
    return pyworld


def _energy(a, sr):
    """Громкость по тем же кадрам, что и тон."""
    import numpy as np
    n = max(1, int(sr * HOP / 1000))
    m = len(a) // n
    if m < 1:
        return np.zeros(0)
    return np.sqrt((a[:m * n].reshape(m, n) ** 2).mean(axis=1))


def melody(vocals):
    """Тон и громкость вокальной дорожки по кадрам. Считается один раз на
    ролик: нарезать готовые ряды по репликам дешевле, чем гонять анализ на
    каждую."""
    import numpy as np, soundfile as sf
    pw = _world()
    a, sr = sf.read(str(vocals), dtype="float64", always_2d=True)
    a = np.ascontiguousarray(a.mean(axis=1))
    f0, tp = pw.harvest(a, sr, f0_floor=65.0, f0_ceil=900.0, frame_period=HOP)
    f0 = pw.stonemask(a, f0, tp, sr)
    e = _energy(a, sr)
    n = min(len(f0), len(e))
    return f0[:n], e[:n]


def _smooth(x, win=9):
    import numpy as np
    if len(x) < win:
        return x
    w = np.hanning(win); w /= w.sum()
    return np.convolve(x, w, mode="same")


def retune(src, dst, track, start, end):
    """Кладёт синтезированную строку на мелодию оригинала.

    Спектральная огибающая остаётся своя — тембр и слова те же, — а тон,
    длительность и громкость берутся у оригинала. Кадры без тона (согласные)
    остаются глухими.
    """
    import numpy as np, soundfile as sf
    pw = _world()
    mel, vol = track
    i, j = int(start * 1000 / HOP), int(end * 1000 / HOP)
    tgt = np.asarray(mel[i:j], dtype="float64")
    tvol = np.asarray(vol[i:j], dtype="float64")
    voiced = tgt > 0
    if voiced.sum() < 8:                      # в оригинале здесь не поют
        return False
    # Паузы и согласные внутри строки заполняем соседями: иначе синтез
    # проваливается в шёпот посреди слова.
    n = np.arange(len(tgt))
    tgt = np.interp(n, n[voiced], tgt[voiced])

    a, sr = sf.read(str(src), dtype="float64", always_2d=True)
    a = np.ascontiguousarray(a.mean(axis=1))
    # Реплика ложится ровно в окно оригинала, ускорять её приходится молча.
    # Больше чем в полтора раза — уже скороговорка, тогда лучше обычная укладка
    # с переносом в соседнюю паузу.
    if len(a) / sr > 1.6 * (end - start):
        return False
    f0, tp = pw.harvest(a, sr, f0_floor=65.0, f0_ceil=600.0, frame_period=HOP)
    f0 = pw.stonemask(a, f0, tp, sr)
    if len(f0) < 8 or len(tgt) < 8:
        return False
    sp = pw.cheaptrick(a, f0, tp, sr)
    ap = pw.d4c(a, f0, tp, sr)
    take = np.round(np.linspace(0, len(f0) - 1, len(tgt))).astype(int)
    out = pw.synthesize(np.where(f0[take] > 0, tgt, 0.0),
                        np.ascontiguousarray(sp[take]),
                        np.ascontiguousarray(ap[take]), sr, HOP)

    # Динамика оригинала: атака и спад ноты на своих местах. Пределы узкие —
    # огибающая правит громкость, но не глушит слоги, попавшие мимо ноты.
    got = _energy(out, sr)
    k = min(len(got), len(tvol))
    gain = np.ones(len(got))
    gain[:k] = np.clip(_smooth(tvol[:k], 31) / (_smooth(got[:k], 31) + 1e-6), 0.7, 1.45)
    step = max(1, int(sr * HOP / 1000))
    curve = np.interp(np.arange(len(out)), np.arange(len(gain)) * step, gain)
    out = np.clip(out * curve, -0.99, 0.99)
    sf.write(str(dst), out.astype("float32"), sr)
    return True


def split_voice(video, out_wav, voice_wav=None, log=print,
                should_stop=lambda: False):
    """Фон без голоса и, отдельно, чистый голос. htdemucs делит запись на голос,
    ударные, бас и остальное. Фон нужен для подмешивания под дубляж, а чистый
    голос — лучший образец для клонирования: в нём нет музыки и шумов сцены."""
    import numpy as np
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    src = Path(out_wav).with_name("orig_stereo.wav")
    run([FFMPEG, "-y", "-v", "error", "-i", str(video), "-vn",
         "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(src)])
    # Читаем soundfile, а не torchaudio: тот с версии 2.11 просит отдельный
    # декодер, а нам он ни к чему — на входе всегда свой wav.
    data, sr = sf.read(str(src), dtype="float32", always_2d=True)
    wav = torch.from_numpy(np.ascontiguousarray(data.T))
    model = get_model("htdemucs")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device).eval()
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        parts = apply_model(model, wav[None].to(device), device=device,
                            shifts=0, overlap=0.1, progress=False)[0]
    parts = parts * ref.std() + ref.mean()
    keep = sum(parts[i] for i, name in enumerate(model.sources) if name != "vocals")
    sf.write(str(out_wav), keep.cpu().numpy().T, sr)
    if voice_wav is not None:
        idx = list(model.sources).index("vocals")
        voice = parts[idx].mean(0, keepdim=True)      # образцу хватает моно
        sf.write(str(voice_wav), voice.cpu().numpy().T, sr)
    src.unlink(missing_ok=True)
    return Path(out_wav), (Path(voice_wav) if voice_wav is not None else None)


def write_srt(utts, path, key):
    """Дорожка субтитров одним файлом: key задаёт, что писать — оригинал
    («text») или перевод («ru»)."""
    def stamp(sec):
        h, m = int(sec) // 3600, int(sec) // 60 % 60
        s, ms = int(sec) % 60, int(sec * 1000) % 1000
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    rows, n = [], 0
    for u in utts:
        line = (u.get(key) or "").strip()
        if not line:
            continue
        n += 1
        rows.append(f"{n}\n{stamp(u['start'])} --> {stamp(u['end'])}\n{line}\n")
    Path(path).write_text("\n".join(rows), encoding="utf-8")
    return Path(path) if n else None


def mux(video, dubbed_wav, out_video, original_volume=0.0, background=None,
        subs=()):
    """Кладёт новую дорожку в видео. original_volume>0 оставляет оригинал фоном."""
    cmd = [FFMPEG, "-y", "-v", "error", "-i", str(video), "-i", str(dubbed_wav)]
    n = 2
    if background:
        cmd += ["-i", str(background)]
        n += 1
    # Субтитры кладём дорожками внутрь файла: системный проигрыватель тогда
    # сам даёт их включить и выключить, отдельный файл никому не нужен.
    for path, _, _ in subs:
        cmd += ["-i", str(path)]
    if background:
        cmd += ["-filter_complex",
                "[2:a]volume=1.0[b];[1:a]volume=1.0[d];"
                "[b][d]amix=inputs=2:duration=first:normalize=0[a]",
                "-map", "0:v", "-map", "[a]"]
    elif original_volume > 0:
        cmd += ["-filter_complex",
                f"[0:a]volume={original_volume}[o];[1:a]volume=1.0[d];"
                "[o][d]amix=inputs=2:duration=first[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    for i in range(len(subs)):
        cmd += ["-map", str(n + i)]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    if subs:
        cmd += ["-c:s", "mov_text"]
        for i, (_, lang, title) in enumerate(subs):
            cmd += [f"-metadata:s:s:{i}", f"language={lang}",
                    f"-metadata:s:s:{i}", f"title={title}"]
    cmd += ["-shortest", str(out_video)]
    run(cmd)


# ---------------------------------------------------------------- всё вместе

def _voice_and_mux(video, out_video, utts, tmp, refs, bg, total_len, *,
                   target="ru", voice_mode="clone", original_volume=0.0,
                   background="strip", tone=None, reworded=0, should_stop=lambda: False,
                   log=print, stage=lambda n, c, t: None):
    """Синтез, сборка дорожки и упаковка в файл. Вынесено отдельно, потому что
    переозвучка по исправленному тексту повторяет ровно эти шаги."""
    def _check():
        if should_stop():
            raise Cancelled()

    stage("Озвучка", 0, len(utts)); log(t("Озвучка…"))
    tts = TTS()
    try:
        tts.load_models(progress=lambda s: log(f"  {s}"))
        piece_dir = tmp / "tts"; piece_dir.mkdir(exist_ok=True)
        if voice_mode == "design":
            # Подобранные голоса храним: переозвучка по правкам должна говорить
            # теми же голосами, что и первый прогон.
            saved = tmp / "voices" / "design.json"
            keep = json.load(open(saved, encoding="utf-8")) if saved.exists() else {}
            if keep and all(Path(v["file"]).exists() for v in keep.values()):
                refs = keep
            else:
                refs = design_refs(tts, refs, utts, tmp / "voices", target, log)
                json.dump(refs, open(saved, "w"), ensure_ascii=False)
            # Подбор отработал, дальше говорит клон: четыре гигабайта памяти
            # видеоядра ни к чему держать до конца ролика.
            tts.free(TTS.DESIGN)
        pieces, stretched, overflow, skipped, sung = [], 0, 0, 0, 0
        mel = None
        if tone:
            log(t("Разбор интонации…"))
            try:
                mel = melody(tone)
            except Exception as e:
                log(tf("  интонацию снять не удалось: {e}", e=e))
        forced = []
        placed_end = 0.0
        any_ref = next(iter(refs.values())) if refs else None
        for i, u in enumerate(utts):
            _check()
            if not u.get("ru"):
                continue
            ref = refs.get(str(u["speaker"])) or any_ref
            if ref is None:
                log(t("  образца голоса нет, реплика пропущена")); continue
            raw = piece_dir / f"{i:04d}_raw.wav"
            for attempt in (1, 2):
                try:
                    tts.clone(spell_out(u["ru"], target), ref["file"], ref["text"],
                              raw, TARGETS[target]["tts"])
                    break
                except Exception as e:
                    if attempt == 2:
                        log(tf("  реплика {n} пропущена: {e}", n=i + 1, e=e))
                        raw = None
                    else:
                        time.sleep(2)
            if raw is None:
                skipped += 1
                stage("Озвучка", i + 1, len(utts))
                continue

            trim_silence(raw)
            fitted = piece_dir / f"{i:04d}.wav"

            if mel is not None and retune(raw, fitted, mel, u["start"], u["end"]):
                # Строка уже уложена в свой такт и в мелодию: сдвигать и ужимать
                # нечего, иначе она разъедется с музыкой.
                start_at, got, rate = u["start"], duration(fitted), 1.0
                sung += 1
                placed_end = start_at + got
                u["placed_start"], u["placed_dur"] = start_at, got
                pieces.append({"file": str(fitted), "start": start_at})
                stage("Озвучка", i + 1, len(utts))
                continue

            # Окно реплики: от конца предыдущей до начала следующей. Если своё окно
            # мало, занимаем тишину ПЕРЕД репликой — начать раньше лучше, чем наехать
            # на следующего говорящего.
            nxt = utts[i + 1]["start"] if i + 1 < len(utts) else total_len
            prev_end = placed_end
            # Если предыдущая реплика затянулась, начинаем не в свой момент, а после
            # неё — небольшой сдвиг слышен куда меньше, чем два голоса разом.
            start_at = min(max(u["start"], prev_end + 0.05), u["start"] + MAX_DRIFT)
            earliest = max(prev_end + 0.05, u["start"] - MAX_BORROW)
            available = max(0.3, nxt - 0.05 - start_at)
            got, rate = fit_segment(raw, fitted, available)

            if got > available + 0.02 and earliest < start_at:
                # не уместились — сдвигаемся в паузу перед репликой и пробуем снова
                start_at = max(earliest, nxt - 0.05 - got)
                available = max(0.3, nxt - 0.05 - start_at)
                got, rate = fit_segment(raw, fitted, available, max_speedup=MAX_SPEEDUP_TIGHT)

            if got > available + 0.02:
                # Жёсткая гарантия: реплика обязана уложиться в своё окно,
                # иначе она перебьёт следующего. Ускоряем ровно во столько,
                # во сколько нужно, и записываем, где пришлось передавить.
                # Потолок 1.8: дальше речь превращается в писк, и лучше оставить
                # небольшой нахлёст, чем нечитаемую реплику.
                got, rate = fit_segment(raw, fitted, available, max_speedup=1.8)
                if rate > MAX_SPEEDUP_TIGHT:
                    forced.append((round(u["start"], 1), round(rate, 2)))

            if rate > 1.001:
                stretched += 1
            if got > available + 0.02:
                overflow += 1
            placed_end = start_at + got
            u["placed_start"] = start_at
            u["placed_dur"] = got
            pieces.append({"file": str(fitted), "start": start_at})
            stage("Озвучка", i + 1, len(utts))

        tts.free()

        stage("Сборка дорожки", 0, 1); log(t("Сборка дорожки…"))
        dubbed = tmp / "dubbed.wav"
        assemble_track(pieces, total_len, dubbed)
        tracks = []
        for key, lang, title in (("ru", TARGETS[target]["iso"], "Перевод"),
                                 ("text", "und", "Оригинал")):
            f = write_srt(utts, tmp / f"subs_{key}.srt", key)
            if f:
                tracks.append((f, lang, title))
        mux(video, dubbed, out_video,
            original_volume if background == "quiet" else 0.0, bg, tracks)
        log(tf("Готово: {out}", out=out_video))
        log(tf("  ускорено: {a}, переформулировано: {b}", a=stretched, b=reworded))
        if mel is not None:
            log(tf("  с интонацией оригинала: {a} из {b}", a=sung, b=len(pieces)))
        if forced:
            log(tf("  сильно ускорено ({n}): ", n=len(forced))
                + ", ".join(f"{sec}c x{r}" for sec, r in forced[:6]))
        json.dump(utts, open(tmp / "utterances.json", "w"), ensure_ascii=False, indent=1)
        return {"out": str(out_video), "utterances": len(utts), "voices": len(set(u.get("speaker") for u in utts)),
                "stretched": stretched, "overflow": overflow, "skipped": skipped,
                "sung": sung,
                "reworded": reworded,
                "workdir": str(tmp)}
    finally:
        tts.free()


def redub(video, out_video, utts, workdir, *, target="ru", voice_mode="clone",
          original_volume=0.0, background="strip", tone=False,
          should_stop=lambda: False,
          log=print, stage=lambda name, cur, total: None):
    """Переозвучка по исправленному тексту. Перевод и разделение голосов уже
    сделаны, образцы и фон лежат в рабочей папке — заново считается только
    синтез и сборка."""
    tmp = Path(workdir)
    refs = json.load(open(tmp / "voices" / "refs.json", encoding="utf-8"))
    bg = tmp / "background.wav"
    voice = tmp / "vocals.wav"
    return _voice_and_mux(video, out_video, utts, tmp, refs,
                          bg if bg.exists() else None, duration(video),
                          target=target, voice_mode=voice_mode,
                          original_volume=original_volume, background=background,
                          tone=voice if (tone and voice.exists()) else None,
                          should_stop=should_stop, log=log, stage=stage)


def dub(video, out_video, *, model_id, num_speakers=0, original_volume=0.0,
        voice_mode="clone", target="ru", background="strip", tone=False,
        fast=False, should_stop=lambda: False,
        log=print, stage=lambda name, cur, total: None, workdir=None):
    def check():
        if should_stop():
            raise Cancelled()

    video = Path(video)
    tmp = Path(workdir or tempfile.mkdtemp(prefix="dub_"))
    tmp.mkdir(parents=True, exist_ok=True)
    wav = tmp / "source.wav"
    total_len = duration(video)

    stage("Извлечение звука", 0, 1); log(t("Извлечение звука…"))
    extract_audio(video, wav)
    ref_src = tmp / "voice_hq.wav"
    extract_audio_hq(video, ref_src)

    check()
    # Разделение голосов считает процессор, распознавание — видеоядро,
    # поэтому пускаем их вместе: замерено 37 с и 15 с по отдельности.
    import threading
    box = {}

    def split_voices():
        try:
            box["diar"] = diarize(wav, num_speakers)
        except Exception as e:
            box["err"] = e

    side = threading.Thread(target=split_voices, daemon=True)
    side.start()

    stage("Распознавание речи", 0, 1); log(t("Распознавание речи…"))
    segs, lang = transcribe(wav)
    log(tf("  реплик: {n}, язык: {lang}", n=len(segs), lang=lang))

    check()
    stage("Разделение голосов", 0, 1); log(t("Разделение голосов…"))
    side.join()
    if "err" in box:
        raise box["err"]
    diar = box["diar"]
    segs = assign_speakers(segs, diar, wav)
    utts = group_utterances(segs)
    # Порог знаков, ниже которого считаем, что речи нет. У иероглифических
    # языков знак несёт целое слово, поэтому там он втрое ниже.
    least = 7 if lang in ("zh", "ja", "ko") else 20
    if not utts or sum(len(u["text"]) for u in utts) < least:
        raise NoSpeech("В ролике нет речи — переводить и озвучивать нечего.")
    voices = sorted({u["speaker"] for u in utts})
    log(tf("  голосов: {a}, цельных реплик: {b}", a=len(voices), b=len(utts)))

    # Фон отделяем до образцов голоса, а не в конце: тот же проход даёт чистый
    # голос без музыки, а по нему клонирование получается заметно ближе.
    bg, vocals = None, None
    if background == "strip" or tone:
        check()
        stage("Отделение фона", 0, 1); log(t("Отделение фона от голоса…"))
        try:
            keep, voice = split_voice(video, tmp / "background.wav",
                                      tmp / "vocals.wav", log=log)
            if background == "strip":
                bg = keep
            if voice and voice.exists():
                ref_src = vocals = voice
            log(t("  фон и голос разделены"))
        except Exception as e:
            log(tf("  отделить фон не удалось: {e}", e=e))

    refs = pick_voice_refs(utts, ref_src, tmp / "voices")
    if vocals is None:
        refs = clean_refs(refs, log)
    json.dump(refs, open(tmp / "voices" / "refs.json", "w"), ensure_ascii=False)
    missing = [v for v in voices if str(v) not in refs]
    if missing:
        log(tf("  для голосов {v} чистого образца нет — берётся общий", v=missing))

    check()
    stage("Перевод", 0, len(utts)); log(t("Перевод…"))
    tr = Translator(model_id, target)
    cps = TARGETS[target]["cps"]
    # Справка стоит отдельного прохода модели: в быстром режиме она дороже
    # той точности, что даёт.
    brief = "" if fast else tr.brief(utts)
    if brief:
        log(t("  справка по ролику: ") + brief.replace("\n", " ")[:140] + "…")
    genders = {spk: v.get("gender") for spk, v in refs.items() if v.get("gender")}
    if genders:
        log(t("  голоса: ") + ", ".join(tf("Г{k} — {v}", k=k, v=t(v))
                                        for k, v in sorted(genders.items())))
    tr.translate_all(utts, genders=genders, brief=brief, src_lang=lang,
                     should_stop=should_stop,
                     progress=lambda c, t: stage("Перевод", c, t))
    missed = [u for u in utts if not u.get("ru")]
    if missed:
        log(tf("  не перевелось реплик: {n} — ", n=len(missed))
            + ", ".join(tf("{sec} с", sec=f"{u['start']:.0f}") for u in missed[:5]))

    # Ужимаем по НАСТОЯЩЕМУ окну до следующей реплики, а не по её собственной длине:
    # это делается сейчас, пока модель перевода в памяти, потому что вместе с
    # моделями озвучки они в память видеоядра не помещаются.
    check()
    stage("Подгонка длины", 0, len(utts)); log(t("Подгонка длины реплик…"))
    long = []
    for i, u in enumerate(utts):
        if not u.get("ru"):
            continue
        nxt = utts[i + 1]["start"] if i + 1 < len(utts) else total_len
        window = max(0.4, nxt - u["start"] + MAX_BORROW * 0.5)
        limit = int(window * cps * MAX_SPEEDUP)   # с учётом допустимого ускорения
        if len(u["ru"]) > limit:
            long.append((i, u["ru"], limit))
    stage("Подгонка длины", 0, max(1, len(long)))
    shorter = tr.shorten_all(long, should_stop=should_stop)
    for i, short in shorter.items():
        utts[i]["ru_full"] = utts[i]["ru"]; utts[i]["ru"] = short
    reworded = len(shorter)
    stage("Подгонка длины", max(1, len(long)), max(1, len(long)))
    log(tf("  переформулировано короче: {a} из {b}", a=reworded, b=len(long)))

    # Модель перевода держит 16 ГБ памяти видеоядра, и синтез в остатках
    # захлёбывается: замерено 29.5 с на реплику против 3-6 с после уборки.
    del tr
    _free_gpu()

    check()
    return _voice_and_mux(video, out_video, utts, tmp, refs, bg, total_len,
                          target=target, voice_mode=voice_mode,
                          original_volume=original_volume, background=background,
                          tone=vocals if tone else None,
                          reworded=reworded, should_stop=should_stop,
                          log=log, stage=stage)
