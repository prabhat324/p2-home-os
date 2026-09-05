import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from runtime import atomic,read
from content_analyzer import caption_chunks,repeated_speech
from editorial import validate
import media_worker as w
class Contracts(unittest.TestCase):
 def test_real_word_times(self):
  words=[{'word':str(i),'start':i*0.4,'end':i*0.4+0.2} for i in range(20)]
  c=caption_chunks({'words':words});self.assertEqual(c[1]['start'],5.6000000000000005);self.assertEqual(c[0]['end'],5.4)
 def test_unapproved_edit_rejected(self):
  with self.assertRaises(ValueError):validate({'events':[{'start':0,'end':4,'kind':'zoom'}]},20)
 def test_graph_requires_source(self):
  with self.assertRaises(ValueError):validate({'events':[{'start':0,'end':4,'kind':'graph','approved':True}]},20)
 def test_overlapping_edits_rejected(self):
  e={'start':0,'end':5,'kind':'zoom','approved':True,'crop_reviewed':True}
  with self.assertRaises(ValueError):validate({'events':[e,e]},20)
 def test_blocked_job_does_not_probe_or_transcribe(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);job=root/'inbox/test';job.mkdir(parents=True);(job/'source.mp4').write_bytes(b'x');m={'ready':True};atomic(job/'project.json',m)
   atomic(root/'logs/test.status.json',{'state':'BLOCKED_FOR_REVIEW','recipe_key':w.recipe_key(job/'source.mp4',m)})
   with patch.object(w,'ROOT',root),patch.object(w,'probe',side_effect=AssertionError('must not process')):w.review_job(job)
 def test_recipe_changes_with_manifest(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'x';p.write_text('x');self.assertNotEqual(w.recipe_key(p,{}),w.recipe_key(p,{'language':'fr'}))
 def test_atomic_state(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'state.json';atomic(p,{'a':1});atomic(p,{'a':2});self.assertEqual(read(p),{'a':2});self.assertEqual(len(list(Path(d).iterdir())),1)
if __name__=='__main__':unittest.main()
