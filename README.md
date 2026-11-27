# VoiceTake Studio Backend

VoiceTake Studio is a local AI voiceover application for creators who want to turn scripts into editable narration, with a particular focus on Hindi storytelling. It supports Hindi, Hinglish and English according to the selected engine and voice.

## Why we built it

Independent creators may not have a quiet recording space, professional equipment or a voice artist budget. Recording and correcting narration can also take several attempts. Text-to-speech helps, but pronunciation mistakes, awkward pauses and a single line that needs another take can still create extra editing work.

VoiceTake brings script editing, pronunciation overrides, per-line delivery controls and audio exports into one workflow. A creator can preview or retake a passage while preserving the rest of the narration.

## Who it helps

- Hindi storytellers and YouTubers producing recurring episodes.
- Short-form creators preparing voiceovers for social videos.
- Educators and independent creators who need editable narration.

## How a creator uses it

1. Create a project and paste or write a script.
2. Select the script language and a supported narrator; compare Hindi voice samples if needed.
3. Separate narration and dialogue, adjust speed and pauses, and add pronunciation overrides.
4. Generate a take, listen to the result, and preview or retake individual lines.
5. Compare takes and export WAV or MP3 audio with timed SRT subtitles.

The local workflow does not require a paid API. It is designed for one creator on their own computer. Kokoro presets adjust pacing, pauses and levels; they do not provide true emotion prompting or guarantee human-level acting. Local Kokoro does not clone an uploaded voice.

## Planned improvements

Priorities include Hindi pronunciation and narration consistency, clearer correction workflows, longer-script handling, and continued usability improvements. More languages and voices will be evaluated before introduction. Public hosting and multi-user infrastructure are future work, not current capabilities.

## What this repository contains

This repository contains the Python FastAPI service: synthesis endpoints, voice and language validation, pronunciation dictionaries, segment previews and retakes, WAV/MP3/SRT exports, and SQLite take metadata.

Hindi synthesis uses installed Kokoro ONNX assets; eSpeak NG supports the local speech pipeline, and FFmpeg handles audio processing and conversion. Use the companion [VoiceTake Frontend](https://github.com/tejas8291/VoiceTake-Frontend) for the complete creator interface.

## Viewing and reuse

This is a source-visible portfolio project. Original VoiceTake code is not offered under a general reuse license; see [COPYRIGHT.md](COPYRIGHT.md) before reusing it. Third-party software and models retain their own licenses. Development used AI assistance from Codex; this project did not train the Kokoro model.

## Setup

Use Python 3.12 or later and Node.js 22 or later. The commands below target macOS or Linux.

```sh
git clone https://github.com/tejas8291/VoiceTake-Backend.git
cd VoiceTake-Backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
npm --prefix demo-engine ci
.venv/bin/python -m uvicorn voice_take.main:app --host 127.0.0.1 --port 8000
```

API documentation is available at http://127.0.0.1:8000/docs. Run the companion VoiceTake-Frontend repository on 127.0.0.1:5173 for the complete Studio.

The default provider is demo. With Kokoro assets installed, Hindi narration uses the local neural pipeline.

## Local Hindi voices

From the repository root, install the optional runtime.

```sh
.venv/bin/python -m pip install -e '.[kokoro]'
mkdir -p .voice-take/kokoro
```

Download the quantized ONNX model and the voice pack to these paths.

```text
.voice-take/kokoro/model_quantized.onnx
.voice-take/kokoro/voices-v1.0.bin
```

Model download sources are the [ONNX model](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/onnx/model_quantized.onnx) and [Kokoro voice pack](https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin).

Restart the API in its default `demo` mode. With the assets installed, Hindi synthesis uses Kokoro. The supported voice mappings are Omega (`hm_omega`), Psi (`hm_psi`) and the female voice (`hf_alpha`). Availability depends on the installed pack. Write Hindi in Devanagari and compare the samples in the voice picker.

## Generation progress

Take responses now include optional `progress` metadata with `stage`, `completed`,
`total`, `current_line` and `operation`. Stages are queued, generating, assembling,
complete and failed. Counts represent generated lines, not elapsed time. Retakes
have one unit of generation work; unchanged clips are reused. WAV/SRT assembly
is reported separately; MP3 encoding still happens when the MP3 is requested.
Existing take records without this field remain readable.

## Project structure

```text
src/voice_take/     API, voice selection, synthesis, audio processing and storage
tests/             API and audio regression tests
demo-engine/       Local eSpeak NG wrapper and dependencies
requirements.lock  Pinned Python dependencies
pyproject.toml     Python package and optional Kokoro runtime
.env.example       Configuration template with empty credential fields
```

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The tests cover voice and language selection, pronunciations, previews, pauses, retakes, WAV exports and subtitle timing. GitHub Actions installs the dependencies and runs the suite.

## Credentials and data

Keep provider credentials in a local .env file, using .env.example as a template. The optional existing ElevenLabs integration sends text or uploaded samples to its provider and may incur charges.

The .voice-take/ directory contains local SQLite storage, generated audio, voice samples, pronunciations and model assets. Git exclusions cover this directory, environment files, credentials, private keys, model weights and generated media.

This service targets a single creator on localhost. Public deployment requires HTTPS, authentication, per-user authorization and protected storage. Origin checks alone do not authenticate a user. See SECURITY.md.

## Branches

Use `main` for the latest tested stable code. Preserve feature/fix branches as checkpoints; start subsequent work from current `main`. Create feature/<description> or fix/<description> branches for subsequent changes.

The companion interface is available in the VoiceTake-Frontend repository.

## Ownership and credits

This is a source-visible portfolio project, not an open-source release. No general reuse license is granted for original VoiceTake code. See [COPYRIGHT.md](COPYRIGHT.md) and [third-party notices](THIRD_PARTY_NOTICES.md). GitHub public-repository viewing/forking rights still apply. Repository visibility is managed separately.

Built with AI assistance from Codex: requirements, integration, testing and iteration are part of this project; Kokoro is an existing third-party model.

## Windows PowerShell setup

Install Python 3.12 and Node.js 22 first. From this repository:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
npm --prefix demo-engine ci
.\.venv\Scripts\python.exe -m pip install -e ".[kokoro]"
New-Item -ItemType Directory -Force .voice-take/kokoro
```

Save the model and voice pack linked above at the documented paths, then run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn voice_take.main:app --host 127.0.0.1 --port 8000
```

These Windows instructions have not yet been validated on a fresh physical Windows laptop. They use the virtual-environment executable directly, so PowerShell activation-policy changes are unnecessary.

## Supported behavior and limitations

The frontend sends scripts/settings to FastAPI. Local synthesis produces segment audio; finishing assembles WAV and subtitle boundaries, FFmpeg converts requested MP3 exports, and SQLite records takes. Downloads and data remain on this computer. Cloning this repository does not restore personal data or downloaded models.

Kokoro is an existing third-party model. Presets control pacing, pauses and levels, not true emotion prompting. Hindi pronunciation and expressive acting are not guaranteed. Local Kokoro does not clone an uploaded voice; existing profile/optional provider restrictions still apply. No paid provider is required for the local workflow.

This is a local single-creator application, not a hosted multi-user service. A larger server alone does not provide authentication, isolated user storage, queues or distributed workers.

## Release readiness

Dependency credits are documented. The retained source of the legacy microphone artwork is recorded in the frontend's `docs/asset-provenance.md`; this is not a blanket redistribution clearance. Fresh Windows laptop setup with Kokoro assets and physical iPhone checks remain deferred.
