import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import split_into_chunks, stable_hash

class UnitTests(unittest.TestCase):
    def test_chunks_are_bounded(self):
        raw = 'A sentence. ' * 150
        result = split_into_chunks(raw, max_chars=400)
        self.assertTrue(result)
        self.assertTrue(all(len(x) <= 400 for x in result))

    def test_simple_paragraph(self):
        self.assertEqual(split_into_chunks('First\n\nSecond', max_chars=400),
                         ['First\n\nSecond'])

    def test_hash_stable(self):
        self.assertEqual(stable_hash({'a': 1, 'b': 2}), stable_hash({'b': 2, 'a': 1}))

if __name__ == '__main__':
    unittest.main()
