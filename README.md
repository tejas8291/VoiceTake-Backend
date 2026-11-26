# VoiceTake Backend

Python FastAPI service for VoiceTake Studio. It generates narration, previews and retakes, stores take metadata in SQLite, applies pronunciation dictionaries and exports WAV, MP3 and SRT.

The local Hindi pipeline uses Kokoro ONNX with supported installed voices. The demo engine uses eSpeak NG. FFmpeg handles export processing. Kokoro storytelling presets adjust pacing, pauses and levels.

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

## Project structure

Take responses now include optional `progress` metadata with `stage`, `completed`,
`total`, `current_line` and `operation`. Stages are queued, generating, assembling,
complete and failed. Counts represent generated lines, not elapsed time. Retakes
have one unit of generation work; unchanged clips are reused. WAV/SRT assembly
is reported separately; MP3 encoding still happens when the MP3 is requested.
Existing take records without this field remain readable.

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

Use main for the baseline and develop for ongoing work. Create feature/<description> or fix/<description> branches for subsequent changes.

The companion interface is available in the VoiceTake-Frontend repository.
