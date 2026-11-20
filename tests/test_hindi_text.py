import unittest

from voice_take.neural import prepare_hindi_text
from voice_take.speech import apply_aliases


class HindiTextTest(unittest.TestCase):
    def test_room_approach_keeps_separate_words(self):
        self.assertEqual(prepare_hindi_text("दोनों धीरे-धीरे कमरे की तरफ बढ़े।", "storytelling"),
                         "दोनों धीरे धीरे कमरे की तरफ़ बढ़े.")

    def test_speech_spellings_preserve_the_script(self):
        original = "आरव के हाथ काँपने लगे। अचानक बेडरूम से आवाज़ आई।"
        self.assertEqual(prepare_hindi_text(original, "storytelling"),
                         "आरव के हाथ कांपने लगे. अचानक बेड रूम से आवाज़ आई.")
        self.assertIn("काँपने", original)

    def test_word_boundaries_include_indic_marks(self):
        self.assertEqual(prepare_hindi_text("फोन फोनो हमशक्ल हमशक्लों", "warm"),
                         "फ़ोन फोनो हमशक्ल् हमशक्लों")

    def test_project_pronunciation_runs_before_defaults(self):
        customized = apply_aliases("बेडरूम", {"बेडरूम": "सोने का कमरा"})
        self.assertEqual(prepare_hindi_text(customized, "warm"), "सोने का कमरा")

    def test_warning_punctuation_and_nukta_are_preserved(self):
        self.assertEqual(prepare_hindi_text("आरव... दरवाज़े मत खोलना!", "warning"),
                         "आरव, दरवाज़े मत खोलना!")


class PronunciationPreviewTest(unittest.TestCase):
    def test_unsaved_override_is_used_without_changing_saved_dictionary(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from voice_take import main
        from voice_take.speech import DemoSpeech
        from voice_take.store import Store

        with (tempfile.TemporaryDirectory() as folder,
              patch.object(main, 'store', Store(Path(folder))),
              patch.object(main, 'mode', 'demo'),
              patch.object(main, 'provider', DemoSpeech()),
              patch.object(main, 'neural_voice_supported', return_value=True),
              patch('voice_take.speech.synthesize_hindi', return_value=b'\x08\x00' * 24000) as synthesize,
              TestClient(main.app, base_url='http://127.0.0.1:8000',
                         headers={'Origin': 'http://127.0.0.1:5173'}) as client):
            client.put('/api/pronunciations', json={'written': 'बेडरूम', 'spoken': 'पुराना कमरा'})
            body = {'language': 'hi', 'voice_id': 'hindi-natural-male', 'index': 0,
                    'scenes': [{'text': 'बेडरूम से आवाज़ आई।', 'style': 'storytelling'}],
                    'pronunciation': {'written': 'बेडरूम', 'spoken': 'बेड रूम'}}
            response = client.post('/api/pronunciations/preview', json=body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['content-type'], 'audio/wav')
            self.assertEqual(synthesize.call_args.args[0], 'बेड रूम से आवाज़ आई।')
            self.assertEqual(client.get('/api/pronunciations').json(), {'बेडरूम': 'पुराना कमरा'})
            with main.store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM takes').fetchone()[0], 0)
            invalid = {**body, 'pronunciation': {'written': '', 'spoken': 'कमरा'}}
            self.assertEqual(client.post('/api/pronunciations/preview', json=invalid).status_code, 422)
