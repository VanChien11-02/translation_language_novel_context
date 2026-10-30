import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from translate import retrieve_examples,split_paragraphs,prompt_for,read_json

class TestCore(unittest.TestCase):
    def test_split_does_not_lose_content(self):
        text='First paragraph.\n\nSecond paragraph.\n\nThird paragraph.'
        pieces=split_paragraphs(text,30)
        self.assertEqual(' '.join(pieces).replace('\n',' '),text.replace('\n\n',' '))
    def test_retrieval_prefers_speaker_and_scene(self):
        records=[
          {'en':'I see you.', 'vi':'Anh nhìn thấy em.', 'speaker':'Sensei','listener':'Yuuka','scene':'normal'},
          {'en':'I will find you.', 'vi':'Ta sẽ tìm ngươi.', 'speaker':'Yuuka','listener':'Sensei','scene':'hostile'}]
        result=retrieve_examples('You will regret this.',records,'Yuuka','Sensei','hostile',1)
        self.assertEqual(result[0]['scene'],'hostile')
    def test_prompt_has_clear_boundaries(self):
        profile=read_json(Path(__file__).resolve().parents[1]/'data/book_profile.json')
        p=prompt_for('Hello', profile, [],'Sensei','Yuuka','normal')
        self.assertIn('ngôi 1 = thầy, ngôi 2 = em',p)
        self.assertIn('[TEXT_TO_TRANSLATE]',p)

if __name__=='__main__': unittest.main()
