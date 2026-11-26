"""Optional local Kokoro Hindi synthesis."""
import re
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from unicodedata import normalize

HINDI_NEURAL_VOICE = "hindi-natural-male"
HINDI_NEURAL_VOICES = {
    HINDI_NEURAL_VOICE: ("Hindi · Natural Male", "Masculine", "hm_omega"),
    "hindi-natural-male-psi": ("Hindi · Natural Male (Psi)", "Masculine", "hm_psi"),
    "hindi-natural-female": ("Hindi · Natural Female", "Feminine", "hf_alpha"),
}
HINDI_COMPARISON_TEXT = "रात के ठीक दो बजे आरव का फ़ोन बजा। उसने धीरे से दरवाज़ा खोला। सामने उसका हमशक्ल खड़ा था।"
NEURAL_LANGUAGES = ("hi", "hinglish")
NEURAL_SAMPLE_RATE = 24000
RUPEE_AMOUNT = re.compile(r"₹\s*(\d+(?:[,.]\d+)*)")
ESPEAK_LANGUAGE_MARKER = re.compile(r"\((?:en|en-us|en-gb|hi)\)")

# Modest adjustments keep the same speaker and avoid exaggerated pauses.
DELIVERY = {
    "conversational": (0.98, 0.16, 0.10),
    "curious": (1.01, 0.14, 0.09),
    "warm": (0.97, 0.17, 0.10),
    "suspenseful": (0.95, 0.19, 0.10),
    "storytelling": (0.98, 0.17, 0.10),
    "energetic": (1.06, 0.14, 0.09),
    "warning": (1.02, 0.13, 0.07),
    "reveal": (0.92, 0.20, 0.11),
    "horror": (0.91, 0.24, 0.12),
    "sad": (0.92, 0.18, 0.11),
    "happy": (1.04, 0.15, 0.09),
    "angry": (1.05, 0.12, 0.08),
}


def auto_hindi_style(text: str) -> str:
    ending = text.rstrip().rstrip(" \"'”’»)]}").rstrip()
    if ending.endswith("?"):
        return "curious"
    if ending.endswith(("…", "...")):
        return "suspenseful"
    if ending.endswith("!"):
        return "warm"
    return "conversational"


model_directory = Path.cwd() / ".voice-take" / "kokoro"


def neural_available() -> bool:
    return find_spec("kokoro_onnx") is not None and all(
        (model_directory / filename).is_file()
        for filename in ("model_quantized.onnx", "voices-v1.0.bin")
    )


@lru_cache(maxsize=4)
def _voice_keys(pack: Path, modified_ns: int) -> frozenset[str]:
    try:
        with ZipFile(pack) as archive:
            return frozenset(Path(item).stem for item in archive.namelist() if item.endswith(".npy"))
    except (BadZipFile, OSError):
        return frozenset()


def neural_voice_supported(voice_id: str) -> bool:
    if not neural_available():
        return False
    pack = model_directory / "voices-v1.0.bin"
    try:
        return HINDI_NEURAL_VOICES[voice_id][2] in _voice_keys(pack, pack.stat().st_mtime_ns)
    except OSError:
        return False


@lru_cache(maxsize=1)
def _model():
    from kokoro_onnx import Kokoro

    return Kokoro(str(model_directory / "model_quantized.onnx"),
                  str(model_directory / "voices-v1.0.bin"))


def prepare_hindi_text(text: str, style: str) -> str:
    """Speech-only spellings for verified eSpeak errors; never alter captions.

    Match whole Indic words, including combining marks, rather than Python's
    Unicode \\w boundaries (which exclude vowel signs and nasalization marks).
    """
    spoken = RUPEE_AMOUNT.sub(lambda amount: amount[1] + " रुपये", normalize("NFC", text))
    aliases = {"काँपने": "कांपने", "बेडरूम": "बेड रूम", "हमशक्ल": "हमशक्ल्",
               "फोन": "फ़ोन", "तरफ": "तरफ़", "धीरे-धीरे": "धीरे धीरे"}
    for written, pronunciation in aliases.items():
        spoken = re.sub(r"(?<![\w\u0900-\u097f\u200c\u200d])" + re.escape(written)
                        + r"(?![\w\u0900-\u097f\u200c\u200d])", pronunciation, spoken)
    spoken = spoken.replace("।", ".")
    spoken = re.sub(r"\.{3,}|…+", "…" if style != "warning" else ",", spoken)
    return re.sub(r"\s+([,.!?…])", r"\1", spoken)


def synthesize_hindi(text: str, style: str, *, has_next_line: bool, speaker: str, tempo: float = 1.0) -> bytes:
    import numpy as np

    speed, sentence_pause, clause_pause = DELIVERY[style]
    model = _model()
    spoken = prepare_hindi_text(text, style)
    phonemes = model.tokenizer.phonemize(spoken, "hi")
    phonemes = ESPEAK_LANGUAGE_MARKER.sub("", phonemes)
    if not phonemes:
        raise ValueError("This line has no pronounceable Hindi or English words.")
    samples, rate = model.create(
        phonemes, voice=speaker, lang="hi", is_phonemes=True,
        speed=speed * tempo, sentence_pause=sentence_pause, clause_pause=clause_pause,
    )
    if rate != NEURAL_SAMPLE_RATE or not len(samples) or not np.isfinite(samples).all():
        raise ValueError("Kokoro returned invalid narration.")
    peak = float(np.max(np.abs(samples)))
    if peak <= 0:
        raise ValueError("Kokoro returned a silent clip. Check the words in this line.")
    pcm = (samples * min(1.0, 0.85 / peak) * 32767).astype("<i2").tobytes()
    if has_next_line:
        ending = text.rstrip().rstrip(" \"'”’»)]}").rstrip()
        pause_seconds = sentence_pause if ending.endswith(("।", ".", "!", "?", "…")) else clause_pause
        pcm += bytes(2 * round(NEURAL_SAMPLE_RATE * pause_seconds))
    return pcm
