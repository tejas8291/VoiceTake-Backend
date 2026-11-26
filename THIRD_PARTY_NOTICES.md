# Third-party notices

This notice identifies major runtime components. Each third-party component retains its own license; VoiceTake's original-code copyright notice does not override those rights. Dependencies are installed separately, and model weights, voice packs and FFmpeg executables are not included in this source repository. Retain upstream notices and meet applicable source/distribution requirements when redistributing their binaries. This is not a complete transitive-dependency or binary distribution audit.

| Component | License / source |
| --- | --- |
| Kokoro-82M weights and voices | [Apache-2.0 model card](https://huggingface.co/hexgrad/Kokoro-82M) |
| ONNX conversion | [ONNX Community model card and files](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX) |
| kokoro-onnx wrapper | [MIT](https://github.com/thewh1teagle/kokoro-onnx/blob/main/LICENSE) |
| ONNX Runtime | [MIT](https://github.com/microsoft/onnxruntime/blob/main/LICENSE) |
| eSpeak NG / espeak-ng npm WASM package | GPL-3.0-or-later; [engine source](https://github.com/espeak-ng/espeak-ng), [WASM package source](https://github.com/ianmarmour/espeak-ng.js) |
| imageio-ffmpeg Python wrapper | [BSD-2-Clause](https://github.com/imageio/imageio-ffmpeg/blob/main/LICENSE) |
| FFmpeg executable | License depends on build; [upstream licensing](https://ffmpeg.org/legal.html). The locally installed macOS binary reports GPL-2.0-or-later via `ffmpeg -L`; do not confuse this with the wrapper's BSD license. |
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| HTTPX | BSD-3-Clause |
| python-dotenv | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| SQLite | [Public domain](https://sqlite.org/copyright.html) |

Kokoro model downloads and voice packs must keep their upstream licensing/attribution. The application does not claim to have trained these models or to own their voices. See installed package metadata and license files for exact versions and full notices.

Optional provider integrations are governed by their provider terms; no provider entitlement is included with this repository. The separate Chatterbox experiment is not part of the stable branch or production pipeline.
