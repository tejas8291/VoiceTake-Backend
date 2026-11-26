import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from voice_take import main
from voice_take.speech import DemoSpeech
from voice_take.store import Store


class GenerationProgressTest(unittest.TestCase):
    def test_completed_lines_and_retake_work_are_reported_truthfully(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder))
            saved = []
            save = store.save

            def record(take):
                saved.append(copy.deepcopy(take))
                save(take)

            with (patch.object(main, 'store', store), patch.object(main, 'mode', 'demo'),
                  patch.object(main, 'provider', DemoSpeech()), patch.object(store, 'save', side_effect=record),
                  patch.object(main, 'neural_voice_supported', return_value=True),
                  patch('voice_take.speech.synthesize_hindi', return_value=b'\x08\x00' * 24000) as synthesize,
                  TestClient(main.app, base_url='http://127.0.0.1:8000',
                             headers={'Origin': 'http://127.0.0.1:5173'}) as client):
                scenes = [{'text': 'आरव ने दरवाज़ा खोला।'}, {'text': 'सामने उसका हमशक्ल था।'}]
                initial = client.post('/api/takes', json={'language': 'hi', 'voice_id': 'hindi-natural-male', 'scenes': scenes})
                self.assertEqual(initial.status_code, 202)
                self.assertEqual(initial.json()['progress']['stage'], 'queued')
                result = client.get('/api/takes/' + initial.json()['id']).json()
                self.assertEqual(result['progress'], {'stage': 'complete', 'completed': 2, 'total': 2,
                                                       'current_line': None, 'operation': 'narration'})
                self.assertTrue(any(s['progress']['stage'] == 'generating' and s['progress']['current_line'] == 2
                                    and s['progress']['completed'] == 1 for s in saved))
                self.assertTrue(any(s['progress']['stage'] == 'assembling' for s in saved))
                synthesize.reset_mock()
                retake = client.post('/api/takes/' + result['id'] + '/retakes',
                                     json={'index': 1, 'scene': scenes[1], 'keep_timing': False})
                self.assertEqual(retake.status_code, 202)
                updated = client.get('/api/takes/' + retake.json()['id']).json()
                self.assertEqual(updated['progress']['total'], 1)
                self.assertEqual(updated['progress']['completed'], 1)
                self.assertEqual(updated['progress']['operation'], 'retake')
                synthesize.assert_called_once()

    def test_failure_preserves_completed_count(self):
        with tempfile.TemporaryDirectory() as folder:
            with (patch.object(main, 'store', Store(Path(folder))), patch.object(main, 'mode', 'demo'),
                  patch.object(main, 'provider', DemoSpeech()),
                  patch.object(main, 'neural_voice_supported', return_value=True),
                  patch('voice_take.speech.synthesize_hindi', side_effect=[b'\x08\x00' * 24000, ValueError('Test failure')]),
                  TestClient(main.app, base_url='http://127.0.0.1:8000',
                             headers={'Origin': 'http://127.0.0.1:5173'}) as client):
                response = client.post('/api/takes', json={'language': 'hi', 'voice_id': 'hindi-natural-male',
                    'scenes': [{'text': 'पहली लाइन।'}, {'text': 'दूसरी लाइन।'}]})
                result = client.get('/api/takes/' + response.json()['id']).json()
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['progress']['stage'], 'failed')
                self.assertEqual(result['progress']['completed'], 1)
                self.assertIsNone(result['progress']['current_line'])
