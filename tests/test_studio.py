"""Verify the key creator workflow through the API and real demo engine."""
import base64
import io
import tempfile
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from voice_take import main
from voice_take.speech import DemoSpeech, ElevenSpeech
from voice_take.store import Store


class StudioTest(unittest.TestCase):
    def test_fixed_retake_preserves_later_audio_and_captions(self):
        origin = {"Origin": "http://127.0.0.1:5173"}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "provider", DemoSpeech()),
            patch.object(main, "mode", "demo"),
            TestClient(main.app, base_url="http://127.0.0.1:8000", headers=origin) as client,
        ):
            response = client.put("/api/pronunciations", json={"written": "Acme", "spoken": "Ack me"})
            self.assertEqual(response.json(), {"acme": "Ack me"})
            denied = client.put("/api/pronunciations", headers={"Origin": "https://example.com"},
                                json={"written": "Acme", "spoken": "Other"})
            self.assertEqual(denied.status_code, 403)
            initial = client.post("/api/takes", json={"scenes": [
                {"text": "This is a longer first line for Acme."},
                {"text": "Here is the second line."},
            ]})
            self.assertEqual(initial.status_code, 202, initial.text)
            original = client.get("/api/takes/" + initial.json()["id"]).json()
            self.assertEqual(original["status"], "ready", original)

            retake = client.post(f"/api/takes/{original['id']}/retakes", json={
                "index": 0, "scene": {"text": "Hello Acme."}, "keep_timing": True,
            })
            self.assertEqual(retake.status_code, 202, retake.text)
            revised = client.get("/api/takes/" + retake.json()["id"]).json()
            self.assertEqual(revised["status"], "ready", revised)
            self.assertEqual(original["duration"], revised["duration"])

            def download(take, filename):
                response = client.get(f"/api/takes/{take['id']}/files/{filename}")
                self.assertEqual(response.status_code, 200)
                return response

            old_srt = download(original, "captions.srt").text
            new_srt = download(revised, "captions.srt").text
            # Windows exports valid CRLF SRT; compare logical blocks on every platform.
            self.assertEqual(old_srt.replace("\r\n", "\n").split("\n\n")[1],
                             new_srt.replace("\r\n", "\n").split("\n\n")[1])
            self.assertIn("Hello Acme.", new_srt)
            self.assertNotIn("Ack me", new_srt)
            start = original["scenes"][0]["spoken_frames"]

            def unchanged_audio(take):
                wav = download(take, "narration.wav").content
                with wave.open(io.BytesIO(wav), "rb") as reader:
                    self.assertEqual(reader.getframerate(), 22050)
                    reader.setpos(start)
                    return reader.readframes(reader.getnframes() - start)

            self.assertTrue(unchanged_audio(original))
            self.assertEqual(unchanged_audio(original), unchanged_audio(revised))

    def test_voice_preview_and_selection_affect_audio(self):
        origin = {"Origin": "http://127.0.0.1:5173"}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "provider", DemoSpeech()),
            patch.object(main, "mode", "demo"),
            TestClient(main.app, base_url="http://127.0.0.1:8000", headers=origin) as client,
        ):
            catalog = [voice for voice in client.get("/api/voices").json()["voices"] if not voice.get("languages")]
            self.assertEqual(len(catalog), 6)
            def preview_audio(voice):
                response = client.get(voice["preview_url"])
                self.assertEqual(response.status_code, 200, response.text if not response.is_success else "")
                with wave.open(io.BytesIO(response.content), "rb") as preview:
                    return preview.readframes(preview.getnframes())

            with ThreadPoolExecutor(max_workers=len(catalog)) as previews_pool:
                previews = list(previews_pool.map(preview_audio, catalog))
            self.assertTrue(all(previews))
            self.assertEqual(len(set(previews)), len(catalog))

            def generate(voice_id):
                response = client.post("/api/takes", json={
                    "voice_id": voice_id,
                    "scenes": [{"text": "This recording uses the selected voice."}],
                })
                self.assertEqual(response.status_code, 202, response.text)
                return client.get(
                    f"/api/takes/{response.json()['id']}/files/narration.wav"
                ).content

            self.assertNotEqual(generate("adult-neutral"), generate("young-bright"))
            invalid = client.post("/api/takes", json={
                "voice_id": "missing", "scenes": [{"text": "Hello."}],
            })
            self.assertEqual(invalid.status_code, 422)

    def test_language_controls_preview_and_is_kept_on_retake(self):
        origin = {"Origin": "http://127.0.0.1:5173"}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "provider", DemoSpeech()),
            patch.object(main, "mode", "demo"),
            TestClient(main.app, base_url="http://127.0.0.1:8000", headers=origin) as client,
        ):
            previews = []
            for language in ("en", "hi", "hinglish"):
                sample = client.get("/api/voices/adult-feminine/preview", params={"language": language})
                self.assertEqual(sample.status_code, 200)
                with wave.open(io.BytesIO(sample.content), "rb") as audio:
                    self.assertGreater(audio.getnframes(), 0)
                previews.append(sample.content)
            self.assertEqual(len(set(previews)), 3)

            for requested, script, expected in [
                ("auto", "आज हम एक नई कहानी सुनेंगे।", "hi"),
                ("auto", "Today we will hear a new story.", "en"),
                ("hi", "आज एक short video बनाएँगे।", "hi"),
            ]:
                with self.subTest(requested=requested, script=script):
                    response = client.post("/api/takes", json={
                        "language": requested, "scenes": [{"text": script}],
                    })
                    self.assertEqual(response.status_code, 202, response.text)
                    take = client.get(f"/api/takes/{response.json()['id']}").json()
                    self.assertEqual(take["status"], "ready", take)
                    self.assertEqual(take["language"], expected)

            created = client.post("/api/takes", json={
                "language": "auto", "voice_id": "young-bright",
                "scenes": [{"text": "नमस्ते! यह मेरा पहला demo video है।"}],
            })
            self.assertEqual(created.status_code, 202, created.text)
            created_id = created.json()["id"]
            retake = client.post(f"/api/takes/{created_id}/retakes", json={
                "index": 0, "scene": {"text": "नमस्ते! आज एक नई कहानी है।"}, "keep_timing": False,
            })
            self.assertEqual(retake.status_code, 202, retake.text)
            result_id = retake.json()["id"]
            result = client.get(f"/api/takes/{result_id}").json()
            self.assertEqual(result["status"], "ready", result)
            self.assertEqual(result["language"], "hinglish")
            captions = client.get(f"/api/takes/{result_id}/files/captions.srt")
            self.assertIn("नमस्ते! आज एक नई कहानी है।", captions.text)

    def test_clone_uses_the_selected_private_voice_with_restraint(self):
        origin = {"Origin": "http://127.0.0.1:5173"}
        engine = ElevenSpeech("test-only")
        audio = base64.b64encode(b"\x01\x00" * 24000).decode()
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "provider", engine),
            patch.object(main, "mode", "elevenlabs"),
            patch.object(engine, "request", side_effect=[
                httpx.Response(200, json={"voice_id": "private-demo", "requires_verification": False}),
                httpx.Response(200, json={"audio_base64": audio}),
            ]) as provider_request,
            TestClient(main.app, base_url="http://127.0.0.1:8000", headers=origin) as client,
        ):
            fields = {"name": "My narration", "consent": "false"}
            recording = {"audio": ("my-voice.webm", b"test audio", "audio/webm")}
            declined = client.post("/api/voice", data=fields, files=recording)
            self.assertEqual(declined.status_code, 422)
            provider_request.assert_not_called()

            fields["consent"] = "true"
            profile = client.post("/api/voice", data=fields, files=recording)
            self.assertEqual(profile.status_code, 201, profile.text)
            self.assertEqual(profile.json()["voice"]["name"], "My narration")
            self.assertTrue(provider_request.call_args.kwargs["files"][0][1][0].endswith(".webm"))

            take = client.post("/api/takes", json={
                "voice_id": "_private", "language": "hi",
                "scenes": [{"text": "नमस्ते!", "style": "auto"}],
            })
            self.assertEqual(take.status_code, 202, take.text)
            request = provider_request.call_args.kwargs["json"]
            self.assertEqual(request["inputs"], [{"voice_id": "private-demo", "text": "नमस्ते!"}])
            self.assertEqual(request["language_code"], "hi")
            self.assertEqual(client.get(f"/api/takes/{take.json()['id']}").json()["status"], "ready")

    def test_pronunciations_are_isolated_and_reused_for_project_retakes(self):
        origin = {"Origin": "http://127.0.0.1:5173"}
        project_a = "550e8400-e29b-41d4-a716-446655440000"
        project_b = "550e8400-e29b-41d4-a716-446655440001"
        scene = {"text": "Say Acme.", "style": "conversational"}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "provider", DemoSpeech()),
            patch.object(main, "mode", "demo"),
            TestClient(main.app, base_url="http://127.0.0.1:8000", headers=origin) as client,
        ):
            def submit(project_id):
                response = client.post("/api/takes", json={"project_id": project_id, "scenes": [scene]})
                self.assertEqual(response.status_code, 202, response.text)
                return response.json()["id"]

            def wav(take_id):
                response = client.get(f"/api/takes/{take_id}/files/narration.wav")
                self.assertEqual(response.status_code, 200)
                return response.content

            for project_id, alias in [(project_a, "Alpha"), (project_b, "Bravo")]:
                response = client.put("/api/pronunciations", params={"project_id": project_id},
                                      json={"written": "Acme", "spoken": alias})
                self.assertEqual(response.json(), {"acme": alias})
            self.assertEqual(client.get("/api/pronunciations").json(), {})

            first = submit(project_a)
            other = submit(project_b)
            self.assertNotEqual(wav(first), wav(other))
            retake = client.post(f"/api/takes/{first}/retakes", json={
                "index": 0, "scene": scene, "keep_timing": False,
            })
            self.assertEqual(retake.status_code, 202, retake.text)
            self.assertEqual(wav(first), wav(retake.json()["id"]))

    def test_neural_hindi_voice_uses_native_sample_rate_and_language(self):
        origin = {"Origin": "http://127.0.0.1:5173"}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "mode", "demo"),
            patch.object(main, "provider", DemoSpeech()),
            patch.object(main, "neural_available", return_value=True),
            patch.object(main, "neural_voice_supported", return_value=True),
            patch("voice_take.speech.synthesize_hindi", return_value=b"\x08\x00" * 24000) as synthesize,
            TestClient(main.app, base_url="http://127.0.0.1:8000", headers=origin) as client,
        ):
            voice_id = "hindi-natural-male"
            catalog = client.get("/api/voices").json()["voices"]
            self.assertEqual(catalog[0]["id"], voice_id)
            rejected = client.post("/api/takes", json={
                "voice_id": voice_id, "language": "auto", "scenes": [{"text": "Hello."}],
            })
            self.assertEqual(rejected.status_code, 422)
            accepted = client.post("/api/takes", json={
                "language": "auto", "scenes": [{"text": "आज हम सुनेंगे।"}],
            })
            self.assertEqual(accepted.status_code, 202, accepted.text)
            take_id = accepted.json()["id"]
            take = client.get(f"/api/takes/{take_id}").json()
            self.assertEqual(take["language"], "hi")
            self.assertEqual(take["voice_name"], "Hindi · Natural Male")
            wav = client.get(f"/api/takes/{take_id}/files/narration.wav")
            self.assertEqual(wav.status_code, 200)
            with wave.open(io.BytesIO(wav.content), "rb") as audio:
                self.assertEqual(audio.getframerate(), 24000)
            synthesize.assert_called_once_with("आज हम सुनेंगे।", "conversational", has_next_line=False, speaker="hm_omega")
            for selected_id, expected_name in [("hindi-natural-female", "Hindi · Natural Female"),
                                               ("young-bright", "Bright storyteller")]:
                generated = client.post("/api/takes", json={
                    "voice_id": selected_id, "language": "hi", "scenes": [{"text": "आज हम सुनेंगे।"}],
                })
                self.assertEqual(generated.status_code, 202, generated.text)
                result = client.get(f"/api/takes/{generated.json()['id']}").json()
                self.assertEqual(result["status"], "ready")
                self.assertEqual(result["voice_name"], expected_name)
            synthesize.assert_called_with("आज हम सुनेंगे।", "conversational", has_next_line=False, speaker="hf_alpha")

    def test_added_pause_shifts_next_line_without_extending_caption(self):
        origin = {"Origin": "http://127.0.0.1:5173"}
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "mode", "demo"),
            patch.object(main, "provider", DemoSpeech()),
            patch.object(main, "neural_available", return_value=True),
            patch.object(main, "neural_voice_supported", return_value=True),
            patch("voice_take.speech.synthesize_hindi", return_value=b"\x08\x00" * 24000),
            TestClient(main.app, base_url="http://127.0.0.1:8000", headers=origin) as client,
        ):
            created = client.post("/api/takes", json={"language": "auto", "scenes": [
                {"text": "दरवाज़े से आवाज़ आई।", "style": "suspenseful", "pause_after_ms": 750},
                {"text": "दरवाज़ा मत खोलना।", "style": "conversational"},
            ]})
            self.assertEqual(created.status_code, 202, created.text)
            route = f"/api/takes/{created.json()['id']}"
            self.assertEqual(client.get(route).json()["duration"], 2.75)
            captions = client.get(route + "/files/captions.srt").text
            self.assertIn("00:00:00,000 --> 00:00:01,000", captions)
            self.assertIn("00:00:01,750 --> 00:00:02,750", captions)
            wav = client.get(route + "/files/narration.wav").content
            with wave.open(io.BytesIO(wav)) as reader:
                reader.setpos(24000)
                self.assertEqual(reader.readframes(18000), bytes(36000))
                self.assertEqual(reader.readframes(1), b"\x08\x00")

    def test_explicit_gap_shared_hindi_pronunciation_and_psi_retake(self):
        from unittest.mock import call
        import struct

        origin = {"Origin": "http://127.0.0.1:5173"}
        project = "550e8400-e29b-41d4-a716-446655440000"
        voice = "hindi-natural-male-psi"
        pcm = struct.pack("<h", 10000) * 24000
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "mode", "demo"),
            patch.object(main, "provider", DemoSpeech()),
            patch.object(main, "neural_available", return_value=True),
            patch.object(main, "neural_voice_supported", return_value=True),
            patch("voice_take.speech.synthesize_hindi", return_value=pcm) as synthesize,
            TestClient(main.app, base_url="http://127.0.0.1:8000", headers=origin) as client,
        ):
            for url, replacement in [
                ("/api/pronunciations?shared=true", "आरव्"),
                (f"/api/pronunciations?project_id={project}", "आरव जी"),
            ]:
                self.assertEqual(client.put(url, json={"written": "आरव", "spoken": replacement}).status_code, 200)
            scenes = [
                {"text": "आरव ने कहा।", "style": "storytelling"},
                {"text": "आरव, रुको।", "speaker": voice, "kind": "dialogue", "style": "warning"},
            ]
            created = client.post("/api/takes", json={
                "language": "hi", "project_id": project, "segment_gap_ms": 350, "scenes": scenes,
            })
            self.assertEqual(created.status_code, 202, created.text)
            original = created.json()["id"]
            self.assertEqual(synthesize.call_args_list, [
                call("आरव जी ने कहा।", "storytelling", has_next_line=False, speaker="hm_omega"),
                call("आरव जी, रुको।", "warning", has_next_line=False, speaker="hm_psi"),
            ])
            captions = client.get(f"/api/takes/{original}/files/captions.srt").text
            self.assertIn("00:00:01,350 --> 00:00:02,350", captions)
            self.assertIn("आरव, रुको।", captions)
            with wave.open(io.BytesIO(client.get(f"/api/takes/{original}/files/narration.wav").content), "rb") as wav:
                voice_frames = wav.readframes(24000)
                self.assertLess(max(abs(frame[0]) for frame in struct.iter_unpack("<h", voice_frames)), 10000)
                self.assertEqual(wav.readframes(8400), bytes(16800))
            synthesize.reset_mock()
            retake = client.post(f"/api/takes/{original}/retakes", json={
                "index": 1, "scene": {**scenes[1], "style": "reveal", "gain_db": -3},
            })
            self.assertEqual(retake.status_code, 202, retake.text)
            synthesize.assert_called_once_with("आरव जी, रुको।", "reveal", has_next_line=False, speaker="hm_psi")
            mp3 = client.get(f"/api/takes/{retake.json()['id']}/files/narration.mp3?download=true")
            self.assertEqual(mp3.status_code, 200)
            self.assertEqual(mp3.headers["content-type"], "audio/mpeg")
            self.assertIn("attachment;", mp3.headers["content-disposition"])

    def test_segment_preview_export_and_leading_pause_agree(self):
        import struct

        origin = {"Origin": "http://127.0.0.1:5173"}
        pcm = struct.pack("<h", 9000) * 24000
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(main, "store", Store(Path(folder))),
            patch.object(main, "mode", "demo"),
            patch.object(main, "provider", DemoSpeech()),
            patch.object(main, "neural_voice_supported", return_value=True),
            patch("voice_take.speech.synthesize_hindi", return_value=pcm) as synthesize,
            TestClient(main.app, base_url="http://127.0.0.1:8000", headers=origin) as client,
        ):
            scene = {"text": "आरव... दरवाज़ा मत खोलना!", "style": "warning", "speed": "fast",
                     "pause_before_ms": 400, "pause_after_ms": 312}
            body = {"language": "hi", "segment_gap_ms": 0, "scenes": [scene]}
            preview = client.post("/api/segments/preview", json={**body, "index": 0})
            self.assertEqual(preview.status_code, 200, preview.text if not preview.is_success else "")
            self.assertEqual(synthesize.call_args.kwargs["tempo"], 1.12)
            created = client.post("/api/takes", json=body)
            self.assertEqual(created.status_code, 202, created.text)
            route = f"/api/takes/{created.json()['id']}"
            segment = client.get(route + "/segments/0/wav?download=true")
            self.assertEqual(segment.status_code, 200)
            self.assertIn("attachment;", segment.headers["content-disposition"])
            self.assertEqual(segment.content, preview.content)
            with wave.open(io.BytesIO(segment.content), "rb") as audio:
                self.assertEqual(audio.readframes(9600), bytes(19200))
                spoken = audio.readframes(24000)
                self.assertEqual((spoken[:2], spoken[-2:]), (b"\0\0", b"\0\0"))
                self.assertEqual(audio.readframes(7488), bytes(14976))
            captions = client.get(route + "/files/captions.srt").text
            self.assertIn("00:00:00,400 --> 00:00:01,400", captions)
            self.assertIn(scene["text"], captions)
