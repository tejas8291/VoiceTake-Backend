"""Offline experiment only. Does not register a provider or touch app storage."""
import json
import os
from pathlib import Path
import random
import time

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime" / "chatterbox-test"
os.environ.setdefault("HF_HOME", str(RUNTIME / "huggingface"))
os.environ.setdefault("XDG_CACHE_HOME", str(RUNTIME / "cache"))
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import numpy as np
import soundfile as sf
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

SAMPLES = {
    "room": "अचानक बेडरूम से किसी के खर्राटे लेने की आवाज़ आई। दोनों धीरे-धीरे कमरे की तरफ बढ़े।",
    "reveal": "अगर तुम असली आरव हो, तो मैं कौन हूँ?",
}


def main():
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    output = RUNTIME / "outputs"
    output.mkdir(parents=True, exist_ok=True)
    reference = RUNTIME / "reference" / "hi_f1.flac"
    if not reference.is_file():
        raise SystemExit("Missing publisher Hindi reference hi_f1.flac. See README.")
    started = time.monotonic()
    model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
    load_seconds = time.monotonic() - started
    results = []
    for name, text in SAMPLES.items():
        started = time.monotonic()
        wav = model.generate(text.replace("।", "."), language_id="hi",
                             audio_prompt_path=str(reference), exaggeration=0.5,
                             cfg_weight=0.3, temperature=0.8)
        samples = wav.squeeze(0).cpu().numpy()
        if not samples.size or not np.isfinite(samples).all():
            raise ValueError("Invalid generated audio")
        peak = float(np.abs(samples).max())
        sf.write(output / f"chatterbox-v3-{name}.wav", samples, model.sr, subtype="FLOAT")
        results.append(dict(sample=name, text=text, model="ResembleAI/chatterbox",
                            checkpoint="t3_mtl23ls_v3.safetensors", device=device,
                            reference="publisher Hindi female hi_f1.flac",
                            seconds=len(samples) / model.sr, peak=peak,
                            samples_at_or_above_full_scale=int((np.abs(samples) >= 1).sum()),
                            generation_seconds=time.monotonic() - started))
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    (output / "measurements.json").write_text(json.dumps(
        dict(load_seconds=load_seconds, results=results), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
