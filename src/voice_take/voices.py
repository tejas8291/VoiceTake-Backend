"""Built-in synthetic demo voices and metadata for account voices."""

from typing import Literal
from unicodedata import name
from urllib.parse import urlparse

DEFAULT_DEMO_VOICE = "adult-neutral"
Language = Literal["en", "hi", "hinglish"]
LanguageChoice = Literal["auto", "en", "hi", "hinglish"]


def detect_language(text: str) -> Language:
    scripts = {name(character, "").split(" ", 1)[0] for character in text if character.isalpha()}
    if "DEVANAGARI" not in scripts:
        return "en"
    return "hinglish" if "LATIN" in scripts else "hi"


PREVIEW_LINES = {
    "en": "Hello! Here is how my voice sounds in VoiceTake.",
    "hi": "नमस्ते! वॉइसटेक में मेरी आवाज़ कुछ ऐसी सुनाई देती है।",
    "hinglish": "नमस्ते! आज हम VoiceTake में एक short video बनाएँगे।",
}

# The labels describe the sound of synthetic presets.
DEMO_VOICES = {
    "young-bright": ("Bright storyteller", "Childlike", "High pitch", "en-us+f4"),
    "adult-neutral": ("Clear narrator", "Adult", "Neutral", "en-us"),
    "adult-feminine": ("Warm narrator", "Adult", "Feminine", "en-us+f2"),
    "adult-masculine": ("Deep narrator", "Adult", "Masculine", "en-us+m3"),
    "senior-soft": ("Gentle elder", "Older adult", "Feminine", "en-us+f1"),
    "senior-low": ("Gravelly elder", "Older adult", "Masculine", "en-us+m1"),
}


def demo_voices():
    return [
        {"id": key, "name": name, "age": age, "sound": sound,
         "preview_url": f"/api/voices/{key}/preview"}
        for key, (name, age, sound, _) in DEMO_VOICES.items()
    ]


def hosted_voice(voice):
    labels = voice.get("labels") or {}
    preview = voice.get("preview_url") or ""
    address = urlparse(preview)
    age = labels.get("age") or ""
    sound = labels.get("gender") or ""
    return {
        "id": voice["voice_id"],
        "name": voice.get("name") or "Unnamed voice",
        "age": {"young": "Young", "middle-aged": "Adult", "middle_aged": "Adult",
                "old": "Older adult"}.get(age, age.replace("_", " ").capitalize()),
        "sound": {"female": "Feminine", "male": "Masculine",
                  "neutral": "Neutral"}.get(sound, ""),
        "description": voice.get("description") or "",
        "preview_url": preview if address.scheme == "https" and address.hostname else None,
    }
