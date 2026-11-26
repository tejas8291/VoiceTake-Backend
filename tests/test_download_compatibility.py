"""Check the media HTTP contract used by Safari and desktop download clients."""
import io
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from voice_take import main
from voice_take.speech import DemoSpeech
from voice_take.store import Store


class DownloadCompatibilityTest(unittest.TestCase):
    def test_exports_support_playback_ranges_and_attachment_downloads(self):
        # Deterministic speech avoids network/model downloads; MP3 encoding is real FFmpeg.
        pcm = b"".join(struct.pack("<h", 3000 if i % 80 < 40 else -3000) for i in range(24000))
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "provider", DemoSpeech()),
            patch.object(main, "mode", "demo"),
            patch.object(main, "neural_available", return_value=True),
            patch.object(main, "neural_voice_supported", return_value=True),
            patch("voice_take.speech.synthesize_hindi", return_value=pcm),
            TestClient(main.app, base_url="http://127.0.0.1:8000",
                       headers={"Origin": "http://127.0.0.1:5173"}) as client,
        ):
            created = client.post("/api/takes", json={
                "language": "hi", "scenes": [{"text": "आरव ने दरवाज़ा खोला।"}],
            })
            self.assertEqual(created.status_code, 202, created.text)
            route = f"/api/takes/{created.json()['id']}/files/"
            for filename, content_type in [("narration.wav", "audio/wav"),
                                           ("narration.mp3", "audio/mpeg"),
                                           ("captions.srt", "text/plain")]:
                with self.subTest(filename=filename):
                    playback = client.get(route + filename)
                    self.assertEqual(playback.status_code, 200)
                    self.assertTrue(playback.content)
                    self.assertTrue(playback.headers["content-type"].startswith(content_type))
                    self.assertEqual(int(playback.headers["content-length"]), len(playback.content))
                    self.assertNotIn("attachment", playback.headers.get("content-disposition", ""))
                    download = client.get(route + filename + "?download=true")
                    self.assertEqual(download.content, playback.content)
                    self.assertIn("attachment;", download.headers["content-disposition"])
                    self.assertIn("-hi.", download.headers["content-disposition"])
                    if filename.endswith(("wav", "mp3")):
                        partial = client.get(route + filename, headers={"Range": "bytes=0-99"})
                        self.assertEqual(partial.status_code, 206)
                        self.assertEqual(partial.content, playback.content[:100])
                        self.assertEqual(partial.headers["content-range"], f"bytes 0-99/{len(playback.content)}")
                        tail = client.get(route + filename, headers={"Range": "bytes=-100"})
                        self.assertEqual(tail.status_code, 206)
                        self.assertEqual(tail.content, playback.content[-100:])
                    if filename.endswith("wav"):
                        with wave.open(io.BytesIO(playback.content)) as audio:
                            self.assertEqual(audio.getframerate(), 24000)
                            self.assertGreater(audio.getnframes(), 0)
                    elif filename.endswith("srt"):
                        self.assertIn("आरव ने दरवाज़ा खोला।", playback.text)
