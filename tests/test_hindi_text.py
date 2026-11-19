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
