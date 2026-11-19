# Chatterbox Hindi comparison experiment

Kokoro remains the Studio default. This standalone script does not alter API
providers, projects, voice IDs, SQLite or application dependencies.

Use the separate ignored environment `.runtime/chatterbox-venv` with
Chatterbox official source pinned to commit
`ab55923c27757c90cfcc407baa57dc25a7d25217` (the PyPI 0.1.7 release lacks
the V3 loader). Model weights and generated audio stay in ignored
`.runtime/chatterbox-test`. Never add tokens or reference recordings to Git.

Run from the backend root:

```sh
.runtime/chatterbox-venv/bin/python experiments/chatterbox-hindi/compare.py
```

The initial test uses **Chatterbox Multilingual V3**, language `hi`, with the
publisher's Hindi female reference from its official Hindi demo:
https://storage.googleapis.com/chatterbox-demo-samples/mtl_prompts/hi_f1.flac

This is not the dedicated `Chatterbox-Multilingual-hi` checkpoint. Its dedicated
loader requires separate verification. Do not label the initial outputs as that
model, or compare the female reference with a male Kokoro voice as a controlled
voice-quality test. Generate identical raw text with Kokoro female for comparison.

Record actual generation time, duration, clipping, pronunciation, omissions and
repetitions. A successful run alone does not establish subjective naturalness.
Listen to both before proposing any default-provider change.

Sources:
- https://github.com/resemble-ai/chatterbox
- https://huggingface.co/ResembleAI/Chatterbox-Multilingual-hi
- https://huggingface.co/spaces/ResembleAI/Chatterbox-Multilingual-TTS-hi
