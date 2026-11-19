"""Speech providers and sample-accurate audio exports."""
import base64
import re
import shutil
import struct
import subprocess
import tempfile
import wave
from itertools import groupby
from pathlib import Path
from unicodedata import category, normalize

import httpx

from .neural import HINDI_NEURAL_VOICES, NEURAL_SAMPLE_RATE, synthesize_hindi
from .voices import DEFAULT_DEMO_VOICE, DEMO_VOICES, hosted_voice

EXPRESSION = {
    "conversational": "",
    "storytelling": "[warmly] ",
    "warning": "[quietly, with suspense] ",
    "reveal": "[quietly, with suspense] ",
    "horror": "[quietly, with suspense] ",
    "sad": "[sadly] ",
    "happy": "[cheerfully] ",
    "angry": "[angrily] ",
    "curious": "[curious] ",
    "suspenseful": "[quietly, with suspense] ",
    "energetic": "[enthusiastically] ",
    "warm": "[warmly] ",
}


def apply_aliases(text, aliases):
    if not aliases:
        return text
    text = normalize("NFC", text)
    lookup = {normalize("NFC", word).casefold(): normalize("NFC", alias)
              for word, alias in aliases.items()}
    alternatives = sorted(lookup, key=len, reverse=True)

    def part_of_word(character):
        return character.isalnum() or category(character).startswith("M") or character in "_\u200c\u200d"

    def substitute(match):
        start, end = match.span()
        if (start and part_of_word(text[start - 1])) or (end < len(text) and part_of_word(text[end])):
            return match[0]
        return lookup.get(match[0].casefold(), match[0])

    pattern = "|".join(map(re.escape, alternatives))
    return re.sub(pattern, substitute, text, flags=re.I)


def auto_style(text, index, count):
    if text.endswith("!"):
        return "energetic"
    if "…" in text or "..." in text:
        return "suspenseful"
    if text.endswith("?") or index == 0:
        return "curious"
    if index == count - 1:
        return "warm"
    return "conversational"


def shorten_demo_silence(pcm: bytes, sample_rate: int, *, has_next_line: bool) -> bytes:
    """Shorten digital silence without changing any nonzero PCM samples."""
    frames = len(pcm) // 2
    limits = {"leading": 40, "between": 220, "trailing": 160 if has_next_line else 100}
    chunks = []
    start = 0
    for silent, samples in groupby(struct.iter_unpack("<h", pcm), lambda frame: frame[0] == 0):
        end = start + sum(1 for _ in samples)
        if silent:
            position = "leading" if start == 0 else "trailing" if end == frames else "between"
            end_of_clip = min(end, start + sample_rate * limits[position] // 1000)
        else:
            end_of_clip = end
        chunks.append(pcm[2 * start:2 * end_of_clip])
        start = end
    return b"".join(chunks)


def sample_rate_for(engine, voice_id):
    if isinstance(engine, DemoSpeech) and voice_id in HINDI_NEURAL_VOICES:
        return NEURAL_SAMPLE_RATE
    return engine.sample_rate


class DemoSpeech:
    name = "demo"
    sample_rate = 22050

    def generate(self, text, style, voice, previous, following, language="en", *, tempo=1.0):
        if voice in HINDI_NEURAL_VOICES:
            return synthesize_hindi(text, style, has_next_line=bool(following),
                                    speaker=HINDI_NEURAL_VOICES[voice][2],
                                    **({"tempo": tempo} if tempo != 1.0 else {}))
        engine = Path.cwd() / "demo-engine" / "synthesize.mjs"
        if not shutil.which("node") or not (engine.parent / "node_modules" / "espeak-ng").exists():
            raise ValueError("Install the demo engine with npm ci in backend/demo-engine.")
        speed = {"curious": 147, "suspenseful": 129, "energetic": 163, "warm": 136, "storytelling": 138, "warning": 144, "reveal": 135, "horror": 126, "sad": 130, "happy": 154, "angry": 158}
        words_per_minute = speed.get(style, 141)
        if language in {"hi", "hinglish"}:
            words_per_minute -= 3
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "speech.txt"
            output = Path(folder) / "speech.wav"
            source.write_text(text, encoding="utf-8")
            subprocess.run(["node", str(engine), str(source), str(output),
                            str(words_per_minute),
                            DEMO_VOICES[voice or DEFAULT_DEMO_VOICE][3], language], check=True, timeout=30, capture_output=True)
            with wave.open(str(output), "rb") as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, self.sample_rate):
                    raise ValueError("Demo speech returned an unexpected audio format.")
                pcm = audio.readframes(audio.getnframes())
                return shorten_demo_silence(pcm, self.sample_rate, has_next_line=bool(following))


class ElevenSpeech:
    name = "elevenlabs"
    sample_rate = 24000

    def __init__(self, api_key):
        self.api_key = api_key

    def request(self, method, path, *, version="v1", **kwargs):
        try:
            response = httpx.request(
                method, f"https://api.elevenlabs.io/{version}/{path}",
                headers={"xi-api-key": self.api_key}, timeout=90, **kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            raise ValueError(
                f"ElevenLabs returned HTTP {status}. Check voice access, verification, and quota."
            ) from None
        except httpx.RequestError:
            raise ValueError("Could not reach ElevenLabs. Check your connection before retrying.") from None
        return response

    def generate(self, text, style, voice, previous, following, language="en"):
        if not voice:
            raise ValueError("Set ELEVENLABS_VOICE_ID or create your own voice first.")
        response = self.request(
            "POST", "text-to-dialogue/with-timestamps",
            params={"output_format": "pcm_24000"},
            json={
                "model_id": "eleven_v4",
                **({"language_code": language} if language != "hinglish" else {}),
                "inputs": [{"text": EXPRESSION[style] + text, "voice_id": voice}],
                "previous_text": previous[-100:] or None,
                "future_text": following[:100] or None,
            },
        )
        return base64.b64decode(response.json()["audio_base64"], validate=True)

    def list_voices(self, search, cursor):
        params = {"page_size": 20, "include_total_count": "false"}
        if search:
            params["search"] = search
        if cursor:
            params["next_page_token"] = cursor
        result = self.request("GET", "voices", version="v2", params=params).json()
        voices = [hosted_voice(voice) for voice in result["voices"]]
        return {"voices": voices, "next_cursor": result.get("next_page_token")
                if result.get("has_more") else None}

    def clone(self, name, audio, extension, media_type):
        response = self.request(
            "POST", "voices/add", data={"name": name},
            files=[("files", ("reference" + extension, audio, media_type))],
        ).json()
        return {
            "voice_id": response["voice_id"],
            "requires_verification": bool(response.get("requires_verification")),
        }

    def delete_clone(self, voice_id):
        self.request("DELETE", "voices/" + voice_id)


def timestamp(frames, sample_rate):
    milliseconds = frames * 1000 // sample_rate
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def export_take(folder, scenes, clips, sample_rate):
    position = 0
    captions = []
    with wave.open(str(folder / "narration.wav"), "wb") as output:
        output.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
        for index, (scene, clip) in enumerate(zip(scenes, clips), start=1):
            spoken_frames = scene["spoken_frames"]
            start = position + scene.get("leading_frames", 0)
            captions.append(
                f"{index}\n{timestamp(start, sample_rate)} --> {timestamp(start + spoken_frames, sample_rate)}\n"
                f"{scene['text']}"
            )
            output.writeframes(clip)
            position += len(clip) // 2
    (folder / "captions.srt").write_text("\n\n".join(captions) + "\n", encoding="utf-8")
    return position / sample_rate
