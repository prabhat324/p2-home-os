import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from runtime import atomic,read
from content_analyzer import caption_chunks
from editorial import validate
from qa_gate import new_events,freeze_event_present_in_source,repeat_event_present_in_source,intentional_static_spans,filter_intentional_freezes,filter_intentional_repeats
from auto_repair import classify_failures
from creative_planner import build as build_plan,normalize_text
from creative_qa import read as creative_read
from podcast_captions import chunks as podcast_chunks,bgr_to_ass
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
 def test_qa_failure_is_recoverable(self):
  self.assertNotIn('QA_FAILED',w.TERMINAL);self.assertIn('QA_REVIEW_REQUIRED',w.TERMINAL)
 def test_visual_baseline_only_flags_new_events(self):
  source=[{'start':10.0,'duration':2.0}]
  output=[{'start':10.2,'duration':2.1},{'start':40.0,'duration':3.0}]
  self.assertEqual(new_events(output,source,['start','duration'],1.0),[output[1]])
 def test_source_freeze_can_be_longer_than_output_freeze(self):
  source=[{'start':46.58,'duration':5.44}];event={'start':49.55,'duration':2.50}
  match=freeze_event_present_in_source(event,source,1.5,0.75);self.assertEqual(match,source[0])
 def test_source_freeze_boundary_tolerance_allows_edit_truncation(self):
  source=[{'start':192.225,'duration':5.239}];event={'start':195.195,'duration':2.469}
  self.assertIsNotNone(freeze_event_present_in_source(event,source,1.5,0.75))
 def test_unrelated_freeze_is_not_inherited(self):
  source=[{'start':10.0,'duration':4.0}];event={'start':20.0,'duration':3.0}
  self.assertIsNone(freeze_event_present_in_source(event,source,1.5,0.75))
 def test_small_overlap_is_not_enough_to_inherit_freeze(self):
  source=[{'start':10.0,'duration':3.0}];event={'start':12.5,'duration':3.0}
  self.assertIsNone(freeze_event_present_in_source(event,source,1.5,0.75))
 def test_repeat_pair_can_be_verified_directly_against_source(self):
  hashes=[0xffffffffffffffff]*60;a=[0x0,0x1,0x3,0x7,0xf];b=[0x0,0x1,0x3,0x7,0x1f]
  hashes[10:15]=a;hashes[30:35]=b;event={'first_second':10,'repeat_second':30,'seconds':5}
  self.assertTrue(repeat_event_present_in_source(event,hashes,5,1.5));self.assertFalse(repeat_event_present_in_source({'first_second':10,'repeat_second':45,'seconds':5},hashes,5,1.5))
 def test_intentional_static_spans_require_approved_still_treatments(self):
  timeline={'events':[{'start':10,'end':20,'kind':'graph','approved':True},{'start':30,'end':40,'kind':'zoom','approved':True},{'start':50,'end':60,'kind':'fact_card','approved':False}]}
  self.assertEqual(intentional_static_spans(timeline),[{'start':10.0,'end':20.0,'kind':'graph'}])
 def test_static_timeline_freeze_is_exempt_but_outside_freeze_still_fails(self):
  spans=[{'start':10.0,'end':20.0,'kind':'graph'}];events=[{'start':10.2,'duration':9.7},{'start':40.0,'duration':3.0}]
  remaining,intentional=filter_intentional_freezes(events,spans,1.0);self.assertEqual(remaining,[events[1]]);self.assertEqual(len(intentional),1);self.assertEqual(intentional[0]['timeline_kind'],'graph')
 def test_repeat_exemption_requires_both_windows_inside_same_static_event(self):
  spans=[{'start':100.0,'end':130.0,'kind':'graph'}];events=[{'first_second':101,'repeat_second':120,'seconds':5},{'first_second':101,'repeat_second':140,'seconds':5}]
  remaining,intentional=filter_intentional_repeats(events,spans,5,1.0);self.assertEqual(remaining,[events[1]]);self.assertEqual(len(intentional),1)
 def test_failure_classifier_preserves_non_audio_review_flags(self):
  audio,other=classify_failures(['True peak -0.6 dBTP exceeds -1.0 dBTP','Detected 1 new freeze event(s) introduced after source']);self.assertEqual(len(audio),1);self.assertEqual(len(other),1)
 def test_qa_logic_version_exists_for_safe_rechecks(self):self.assertGreaterEqual(w.QA_LOGIC_VERSION,5)
 def test_podcast_plan_has_no_cutaways(self):
  plan=build_plan({'mode':'podcast'},{},{},120);self.assertEqual(plan['events'],[]);self.assertFalse(plan['creative_policy']['cutaways']);self.assertTrue(plan['creative_policy']['speaker_captions'])
 def test_explainer_plan_is_not_empty(self):
  plan=build_plan({'mode':'explainer'},{'fact_check_flags':[]},{},120);self.assertGreaterEqual(len(plan['events']),3);self.assertTrue(all(e['kind']=='zoom' for e in plan['events']))
 def test_unsourced_claim_does_not_become_fact_card(self):
  report={'fact_check_flags':[{'second':20,'text':'The project cost $40 million'}]};plan=build_plan({'mode':'explainer'},report,{},100);self.assertFalse(any(e['kind']=='fact_card' for e in plan['events']))
 def test_sourced_claim_can_become_fact_card(self):
  report={'fact_check_flags':[{'second':20,'text':'The project cost $40 million'}]};plan=build_plan({'mode':'explainer','verified_sources':{'20':'Town budget'}},report,{},100);self.assertTrue(any(e['kind']=='fact_card' for e in plan['events']))
 def test_curated_graph_is_preserved_and_sourced(self):
  m={'mode':'explainer','graphic_events':[{'start':10,'end':16,'kind':'graph','title':'Funding','unit':'$M','source':'Town source','data':[{'label':'A','value':2},{'label':'B','value':3}]}]}
  plan=build_plan(m,{'fact_check_flags':[]},{},120);g=[e for e in plan['events'] if e['kind']=='graph'];self.assertEqual(len(g),1);self.assertEqual(g[0]['source'],'Town source');self.assertEqual(len(g[0]['data']),2)
 def test_protected_wasaga_spelling_is_normalized(self):
  self.assertEqual(normalize_text('Visaga Beach and Vassaga'), 'Wasaga Beach and Wasaga')
 def test_podcast_caption_chunks_keep_word_times(self):
  t={'segments':[{'start':0,'end':2,'text':'hello world','words':[{'word':'hello','start':0.1,'end':0.5},{'word':'world','start':0.6,'end':1.0}]}]};cues=podcast_chunks(t,12);self.assertEqual(cues[0]['start'],0.1);self.assertEqual(cues[0]['end'],1.0)
 def test_ass_color_is_bgr(self):self.assertEqual(bgr_to_ass('#7DFF95'),'&H0095FF7D')

if __name__=='__main__':unittest.main()
