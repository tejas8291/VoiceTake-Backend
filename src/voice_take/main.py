"""Loopback API for the VoiceTake desktop development workflow."""
import io
import logging
import os
import re
import shutil
import subprocess
import time
import wave
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, Optional
from uuid import UUID, uuid4
from unicodedata import normalize

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, StringConstraints, model_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse, Response

from .media import TEMPO, encode_mp3, finish_dialogue, prepare_pcm
from .neural import (
    DELIVERY, HINDI_COMPARISON_TEXT, HINDI_NEURAL_VOICE, HINDI_NEURAL_VOICES,
    NEURAL_LANGUAGES, auto_hindi_style, neural_available, neural_voice_supported,
)
from .speech import DemoSpeech, ElevenSpeech, apply_aliases, auto_style, export_take, sample_rate_for
from .store import Store
from .voices import DEFAULT_DEMO_VOICE, DEMO_VOICES, PREVIEW_LINES, Language, LanguageChoice, demo_voices, detect_language

load_dotenv(Path.cwd() / ".env")
mode = os.getenv("VOICE_TAKE_PROVIDER", "demo")
api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
if mode not in {"demo", "elevenlabs"} or (mode == "elevenlabs" and not api_key):
    raise RuntimeError("Set a valid VOICE_TAKE_PROVIDER and configure its server credentials.")

provider = ElevenSpeech(api_key) if mode == "elevenlabs" else DemoSpeech()
default_voice = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
store = Store(Path.cwd() / ".voice-take")
generation_lock = Lock()
preview_lock = Lock()
pronunciation_lock = Lock()
LEGACY_PROJECT = UUID(int=0).hex
logger = logging.getLogger(__name__)
origins = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8000)}

Line = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500, pattern=r"^[^\r\n]+$")]
Alias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[^\r\n\[\]]+$")]
Style = Literal["auto", "conversational", "curious", "suspenseful", "energetic", "warm", "storytelling", "horror", "sad", "happy", "angry", "warning", "reveal"]


class Scene(BaseModel):
    text: Line
    style: Style = "auto"
    kind: Literal["narration", "dialogue"] = "narration"
    speed: Literal["slow", "normal", "fast"] = "normal"
    speaker: Literal["narrator", "hindi-natural-female", "hindi-natural-male", "hindi-natural-male-psi"] = "narrator"
    gain_db: float = Field(default=0, ge=-12, le=6, allow_inf_nan=False)
    pause_before_ms: int = Field(default=0, ge=0, le=5000)
    pause_after_ms: int = Field(default=0, ge=0, le=5000)


class Generation(BaseModel):
    project_id: Optional[UUID] = None
    language: LanguageChoice = "en"
    voice_id: Optional[Annotated[str, StringConstraints(max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")]] = None
    segment_gap_ms: Optional[int] = Field(default=None, ge=0, le=5000)
    scenes: list[Scene] = Field(min_length=1, max_length=24)

    @model_validator(mode="after")
    def check_length(self):
        if sum(len(scene.text) for scene in self.scenes) > 1600:
            raise ValueError("The script exceeds 1600 characters.")
        return self


class SegmentPreview(Generation):
    index: int = Field(ge=0, lt=24)


class Retake(BaseModel):
    index: int = Field(ge=0, lt=24)
    scene: Scene
    keep_timing: bool = True


class Pronunciation(BaseModel):
    written: Alias
    spoken: Alias


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    yield


app = FastAPI(title="VoiceTake API", lifespan=lifespan, version="0.1.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])


@app.middleware("http")
async def protect_local_api(request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") not in origins:
            return JSONResponse({"detail": "Use the VoiceTake editor on this computer."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


def get_take(take_id):
    take = store.get(take_id.hex)
    if not take:
        raise HTTPException(404, "Take not found.")
    return take


def wav_bytes(pcm, sample_rate):
    audio = io.BytesIO()
    with wave.open(audio, "wb") as output:
        output.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
        output.writeframes(pcm)
    return audio.getvalue()


def render_segment(take, position, voice_id, aliases):
    scenes = take["scenes"]
    scene = scenes[position]
    text = apply_aliases(scene["text"], aliases).replace("[", "［").replace("]", "］")
    speaker = scene.get("speaker", "narrator")
    line_voice = voice_id if speaker == "narrator" else speaker
    neural = mode == "demo" and line_voice in HINDI_NEURAL_VOICES
    style = scene["style"]
    if style == "auto":
        if neural:
            style = auto_hindi_style(text)
        elif mode == "elevenlabs":
            style = "conversational"
        else:
            style = auto_style(text, position, len(scenes))
    before = scenes[position - 1]["text"] if position else ""
    next_scene = scenes[position + 1] if position + 1 < len(scenes) else None
    after = next_scene["text"] if next_scene else ""
    gap = take.get("segment_gap_ms")
    leading = scene.get("pause_before_ms", 0)
    trailing = scene.get("pause_after_ms", 0)
    trim_edges = (gap is not None or leading > 0 or trailing > 0
                  or bool(next_scene and next_scene.get("pause_before_ms", 0)))
    if gap is not None and next_scene:
        trailing += gap
    speed = scene.get("speed", "normal")
    clip = provider.generate(text, style, line_voice, before,
                             after if not trim_edges or mode != "demo" else "", take["language"],
                             **({"tempo": TEMPO[speed]} if neural and speed != "normal" else {}))
    if not clip or len(clip) % 2:
        raise ValueError("The voice engine returned invalid audio.")
    rate = take["sample_rate"]
    clip = prepare_pcm(clip, sample_rate_for(provider, line_voice), rate, "normal" if neural else speed)
    gain = scene.get("gain_db", 0) + {"warning": -2.0, "reveal": -1.0}.get(style, 0)
    clip = finish_dialogue(clip, rate, gain, trim_edges=trim_edges, fade_edges=trim_edges or neural)
    scene["leading_frames"] = rate * leading // 1000
    scene["spoken_frames"] = len(clip) // 2
    scene["trailing_frames"] = rate * trailing // 1000
    return bytes(2 * scene["leading_frames"]) + clip + bytes(2 * scene["trailing_frames"])


def render(take, previous_take, index, keep_timing, voice_id, aliases):
    folder = store.root / take["id"]
    try:
        take["status"] = "running"
        store.save(take)
        folder.mkdir(mode=0o700)
        scenes = take["scenes"]
        clips = []
        sample_rate = take["sample_rate"]
        for position, scene in enumerate(scenes):
            clip_name = f"{position}.pcm"
            if previous_take and position != index:
                clip = (store.root / previous_take["id"] / clip_name).read_bytes()
            else:
                clip = render_segment(take, position, voice_id, aliases)
                if previous_take and keep_timing:
                    original = store.root / previous_take["id"] / clip_name
                    remaining = original.stat().st_size - len(clip)
                    if remaining < 0:
                        raise ValueError(
                            f"This line is {-remaining / (2 * sample_rate):.2f}s too long. "
                            "Shorten it or turn off fixed timing."
                        )
                    clip += bytes(remaining)
            (folder / clip_name).write_bytes(clip)
            clips.append(clip)
        take["duration"] = export_take(folder, scenes, clips, sample_rate)
        take["status"] = "ready"
        store.save(take)
    except Exception as error:
        shutil.rmtree(folder, ignore_errors=True)
        logger.warning("Take %s failed (%s)", take["id"], type(error).__name__)
        take.update(status="failed", error=str(error) if isinstance(error, ValueError)
                    else "Audio generation failed. Check the local engine and try again.")
        store.save(take)
    finally:
        generation_lock.release()


def resolve_take(scenes, earlier, selected_voice, language, project_id, segment_gap_ms):
    profile = store.settings("voice", None)
    if mode == "demo":
        voice_id = selected_voice or (
            HINDI_NEURAL_VOICE if language == "hi" and neural_voice_supported(HINDI_NEURAL_VOICE) else DEFAULT_DEMO_VOICE
        )
        if voice_id not in DEMO_VOICES and voice_id not in HINDI_NEURAL_VOICES:
            raise HTTPException(422, "Choose a voice from the demo catalog.")
    elif selected_voice == "_private":
        if not profile:
            raise HTTPException(422, "Create a private voice before choosing it.")
        voice_id = profile["voice_id"]
    elif selected_voice == "_default":
        voice_id = default_voice
    else:
        voice_id = selected_voice or (profile["voice_id"] if profile else default_voice)
    if earlier:
        if earlier["provider"] != mode:
            raise HTTPException(409, "Regenerate the full script with the current engine first.")
        voice_id = earlier["voice_id"]
        language = earlier.get("language", "en")
        project_id = earlier.get("project_id")
        segment_gap_ms = earlier.get("segment_gap_ms")
    if mode == "demo" and voice_id in HINDI_NEURAL_VOICES:
        if not neural_voice_supported(voice_id):
            raise HTTPException(503, "This Kokoro voice is not in the installed pack.")
        if language not in NEURAL_LANGUAGES:
            raise HTTPException(422, "This voice requires Hindi or Hinglish.")
    if mode == "elevenlabs" and not voice_id:
        raise HTTPException(422, "Set a server-side voice ID or upload your voice first.")
    has_characters = any(scene.get("speaker", "narrator") != "narrator" for scene in scenes)
    if has_characters and (mode != "demo" or language not in NEURAL_LANGUAGES or not neural_available()):
        raise HTTPException(422, "Local character voices need the Kokoro model and Hindi or Hinglish.")
    if has_characters and any(
        scene.get("speaker", "narrator") != "narrator" and not neural_voice_supported(scene["speaker"])
        for scene in scenes
    ):
        raise HTTPException(422, "A character voice is not in the installed Kokoro pack.")
    narrator_rate = sample_rate_for(provider, voice_id)
    return voice_id, language, project_id, segment_gap_ms, narrator_rate, has_characters


def take_aliases(project_id):
    return {**store.settings("pronunciations:shared", {}),
            **store.settings(pronunciation_key(project_id), {})}


def queue(scenes, background, earlier=None, index=None, keep_timing=False, selected_voice=None, language="en", project_id=None, segment_gap_ms=None):
    if not generation_lock.acquire(blocking=False):
        raise HTTPException(409, "Another generation is running. Try again after it finishes.")
    try:
        voice_id, language, project_id, segment_gap_ms, narrator_rate, has_characters = resolve_take(
            scenes, earlier, selected_voice, language, project_id, segment_gap_ms
        )
        if earlier:
            sample_rate = earlier.get("sample_rate", narrator_rate)
        else:
            sample_rate = max(narrator_rate, 24000) if has_characters else narrator_rate
        take = {"id": uuid4().hex, "status": "queued", "scenes": scenes, "sample_rate": sample_rate,
                "provider": mode, "voice_id": voice_id, "language": language,
                "project_id": project_id, "segment_gap_ms": segment_gap_ms}
        aliases = take_aliases(project_id)
        store.save(take)
        background.add_task(render, take, earlier, index, keep_timing, voice_id, aliases)
        return public_take(take)
    except Exception:
        generation_lock.release()
        raise


def public_take(take):
    result = {key: value for key, value in take.items() if key != "voice_id"}
    if take["provider"] == "demo":
        voice_id = take.get("voice_id") or DEFAULT_DEMO_VOICE
        if voice_id in HINDI_NEURAL_VOICES:
            result["voice_name"] = HINDI_NEURAL_VOICES[voice_id][0]
        elif voice_id in DEMO_VOICES:
            result["voice_name"] = DEMO_VOICES[voice_id][0]
    return result


@app.get("/api/status")
def status():
    profile = store.settings("voice", None)
    return {"provider": mode, "has_default_voice": bool(default_voice),
            "has_local_characters": mode == "demo" and neural_available(),
            "local_character_voices": [key for key in HINDI_NEURAL_VOICES if neural_voice_supported(key)]
            if mode == "demo" else [],
            "voice": {"name": profile["name"], "requires_verification":
                      profile["requires_verification"]} if profile else None}


@app.get("/api/voices")
def list_voices(search: str = Query(default="", max_length=100),
                cursor: Optional[str] = Query(default=None, max_length=500)):
    if isinstance(provider, ElevenSpeech):
        try:
            return provider.list_voices(search.strip(), cursor)
        except ValueError as error:
            raise HTTPException(502, str(error)) from None
    voices = demo_voices()
    if neural_available():
        voices[:0] = [
            {"id": key, "name": title, "age": "Adult", "sound": sound,
             "languages": NEURAL_LANGUAGES, "preview_url": f"/api/voices/{key}/preview"}
            for key, (title, sound, _) in HINDI_NEURAL_VOICES.items() if neural_voice_supported(key)
        ]
    return {"voices": voices, "next_cursor": None}


@lru_cache(maxsize=(len(DEMO_VOICES) + len(HINDI_NEURAL_VOICES)) * len(PREVIEW_LINES))
def demo_preview(engine, voice_id, language):
    neural = voice_id in HINDI_NEURAL_VOICES
    text = HINDI_COMPARISON_TEXT if neural and language == "hi" else PREVIEW_LINES[language]
    rate = sample_rate_for(engine, voice_id)
    started = time.perf_counter()
    pcm = engine.generate(text, "conversational", voice_id, "", "", language)
    if neural:
        pcm = finish_dialogue(pcm, rate, 0, trim_edges=True, fade_edges=True)
    wav = wav_bytes(pcm, rate)
    headers = {
        "X-VoiceTake-Generation-Ms": str(round((time.perf_counter() - started) * 1000)),
        "X-VoiceTake-Duration-Ms": str(round(len(pcm) * 500 / rate)),
    }
    if neural:
        speed, sentence_pause, clause_pause = DELIVERY["conversational"]
        headers.update({
            "X-VoiceTake-Model": "Kokoro-82M-v1.0-ONNX-quantized",
            "X-VoiceTake-Speaker": HINDI_NEURAL_VOICES[voice_id][2],
            "X-VoiceTake-Speed": str(speed),
            "X-VoiceTake-Sentence-Pause-Ms": str(round(sentence_pause * 1000)),
            "X-VoiceTake-Clause-Pause-Ms": str(round(clause_pause * 1000)),
        })
    return wav, headers


@app.get("/api/voices/{voice_id}/preview")
def preview_voice(voice_id: str, language: Language = "en"):
    if not isinstance(provider, DemoSpeech) or (
        voice_id not in DEMO_VOICES and (voice_id not in HINDI_NEURAL_VOICES or not neural_voice_supported(voice_id))
    ):
        raise HTTPException(404, "Voice preview unavailable.")
    if voice_id in HINDI_NEURAL_VOICES and language not in NEURAL_LANGUAGES:
        raise HTTPException(422, "Choose Hindi or Hinglish to preview this voice.")
    try:
        with preview_lock:
            preview, headers = demo_preview(provider, voice_id, language)
        return Response(preview, media_type="audio/wav", headers=headers)
    except (ValueError, OSError):
        raise HTTPException(503, "Offline voice preview unavailable.") from None


def pronunciation_key(project_id, shared=False):
    if shared:
        return "pronunciations:shared"
    if not project_id or project_id == LEGACY_PROJECT:
        return "pronunciations"
    return "pronunciations:" + project_id


@app.get("/api/pronunciations")
def pronunciations(project_id: Optional[UUID] = None, shared: bool = False):
    return store.settings(pronunciation_key(project_id.hex if project_id else None, shared), {})


@app.put("/api/pronunciations")
def put_pronunciation(body: Pronunciation, project_id: Optional[UUID] = None, shared: bool = False):
    storage_key = pronunciation_key(project_id.hex if project_id else None, shared)
    with pronunciation_lock:
        aliases = store.settings(storage_key, {})
        word = normalize("NFC", body.written).casefold()
        if word not in aliases and len(aliases) >= 100:
            raise HTTPException(422, "Keep up to 100 saved pronunciations per project.")
        aliases[word] = body.spoken
        store.update(storage_key, aliases)
        return aliases


@app.delete("/api/pronunciations")
def remove_pronunciation(written: Alias, project_id: Optional[UUID] = None, shared: bool = False):
    storage_key = pronunciation_key(project_id.hex if project_id else None, shared)
    with pronunciation_lock:
        aliases = store.settings(storage_key, {})
        aliases.pop(normalize("NFC", written).casefold(), None)
        store.update(storage_key, aliases)
        return aliases


@app.post("/api/takes", status_code=202)
def generate(body: Generation, background: BackgroundTasks):
    language = body.language
    if language == "auto":
        language = detect_language(" ".join(scene.text for scene in body.scenes))
    return queue([scene.model_dump() for scene in body.scenes], background,
                 selected_voice=body.voice_id, language=language,
                 project_id=body.project_id.hex if body.project_id else None, segment_gap_ms=body.segment_gap_ms)


@app.post("/api/segments/preview")
def preview_segment(body: SegmentPreview):
    if mode != "demo":
        raise HTTPException(409, "Draft segment preview is available in local mode. You can play saved segments in Takes.")
    if body.index >= len(body.scenes):
        raise HTTPException(422, "Select an existing segment.")
    if not generation_lock.acquire(blocking=False):
        raise HTTPException(409, "Wait for the current take before previewing a segment.")
    try:
        scenes = [scene.model_dump() for scene in body.scenes]
        language = body.language if body.language != "auto" else detect_language(" ".join(scene.text for scene in body.scenes))
        project_id = body.project_id.hex if body.project_id else None
        voice_id, language, _, gap, rate, has_characters = resolve_take(
            scenes, None, body.voice_id, language, project_id, body.segment_gap_ms,
        )
        sample_rate = max(rate, 24000) if has_characters else rate
        take = {"scenes": scenes, "sample_rate": sample_rate, "language": language, "segment_gap_ms": gap}
        pcm = render_segment(take, body.index, voice_id, take_aliases(project_id))
        return Response(wav_bytes(pcm, sample_rate), media_type="audio/wav")
    except (ValueError, OSError, subprocess.SubprocessError):
        raise HTTPException(503, "Could not render this segment preview.") from None
    finally:
        generation_lock.release()


@app.get("/api/takes/{take_id}/segments/{index}/wav")
def take_segment(take_id: UUID, index: int, download: bool = False):
    take = get_take(take_id)
    if take["status"] != "ready" or not 0 <= index < len(take["scenes"]):
        raise HTTPException(404, "This segment is not available.")
    folder = store.root / take["id"]
    path = folder / f"{index}.pcm"
    try:
        pcm = path.read_bytes()
        # Older takes did not store the sample rate.
        rate = take.get("sample_rate")
        if rate is None:
            with wave.open(str(folder / "narration.wav"), "rb") as original:
                rate = original.getframerate()
    except (OSError, wave.Error):
        raise HTTPException(404, "This segment audio could not be found.") from None
    scene = take["scenes"][index]
    # Leave fixed-timing filler in the combined take, outside the individual export.
    frames = sum(scene.get(key, 0) for key in ("leading_frames", "spoken_frames", "trailing_frames"))
    if "trailing_frames" in scene:
        pcm = pcm[:2 * frames]
    headers = {"Content-Disposition": f'attachment; filename="voicetake-{take["id"][:8]}-segment-{index + 1}.wav"'} if download else None
    return Response(wav_bytes(pcm, rate), media_type="audio/wav", headers=headers)


@app.get("/api/takes/{take_id}")
def take_status(take_id: UUID):
    return public_take(get_take(take_id))


@app.post("/api/takes/{take_id}/retakes", status_code=202)
def retake(take_id: UUID, body: Retake, background: BackgroundTasks):
    earlier = get_take(take_id)
    if earlier["status"] != "ready" or body.index >= len(earlier["scenes"]):
        raise HTTPException(422, "Select a line from a finished take.")
    scenes = [dict(scene) for scene in earlier["scenes"]]
    scenes[body.index] = body.scene.model_dump()
    if sum(len(scene["text"]) for scene in scenes) > 1600:
        raise HTTPException(422, "The script exceeds 1600 characters.")
    return queue(scenes, background, earlier, body.index, body.keep_timing)


@app.get("/api/takes/{take_id}/files/{filename}")
def take_file(take_id: UUID, filename: Literal["narration.wav", "narration.mp3", "captions.srt"], download: bool = False):
    take = get_take(take_id)
    if take["status"] != "ready":
        raise HTTPException(404, "This take is not ready.")
    download_name = None
    if download:
        extension = Path(filename).suffix
        download_name = f"voicetake-{take['id'][:8]}-{take.get('language', 'en')}{extension}"
    folder = store.root / take["id"]
    media_types = {"narration.wav": "audio/wav", "narration.mp3": "audio/mpeg", "captions.srt": "text/plain"}
    path = folder / filename
    if filename == "narration.mp3":
        try:
            path = encode_mp3(folder / "narration.wav")
        except (OSError, RuntimeError, subprocess.SubprocessError):
            raise HTTPException(503, "MP3 export is unavailable. Download the WAV instead.") from None
    return FileResponse(path, media_type=media_types[filename], filename=download_name)


@app.post("/api/voice", status_code=201)
def create_voice(
    audio: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=60),
    consent: bool = Form(...),
):
    if not isinstance(provider, ElevenSpeech):
        raise HTTPException(409, "Voice cloning requires the hosted engine.")
    if not consent or not name.strip():
        raise HTTPException(422, "Enter a name and confirm this is your own voice.")
    maximum = 10 * 1024 * 1024
    extension = Path(audio.filename or "").suffix.lower()
    media = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".webm": "audio/webm", ".ogg": "audio/ogg"}
    if extension not in media or not audio.size or audio.size > maximum:
        raise HTTPException(422, "Upload a WAV, MP3, M4A, WebM, or OGG recording of up to 10 MB.")
    if not generation_lock.acquire(blocking=False):
        raise HTTPException(409, "Wait for the current voice operation to finish.")
    try:
        if store.settings("voice", None):
            raise HTTPException(409, "Delete the current clone before creating a new one.")
        profile = provider.clone(name.strip(), audio.file.read(maximum), extension, media[extension])
        store.update("voice", {**profile, "name": name.strip()})
    except ValueError as error:
        raise HTTPException(502, str(error)) from None
    finally:
        generation_lock.release()
    return status()


@app.delete("/api/voice")
def delete_voice():
    if not isinstance(provider, ElevenSpeech) or not generation_lock.acquire(blocking=False):
        raise HTTPException(409, "The hosted engine is unavailable or busy.")
    try:
        profile = store.settings("voice", None)
        if profile:
            voice_id = profile["voice_id"]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", voice_id):
                raise HTTPException(422, "The saved voice identifier is invalid.")
            provider.delete_clone(voice_id)
            store.update("voice", None)
    except ValueError as error:
        raise HTTPException(502, str(error)) from None
    finally:
        generation_lock.release()
    return status()
