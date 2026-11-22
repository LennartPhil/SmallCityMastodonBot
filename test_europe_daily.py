import copy
import unittest
from unittest.mock import patch
from datetime import datetime,timezone
from europe_daily import reserve,finish,check_ready,RemoteJournal,text_for

class Journal:
 def __init__(self):self.state={'version':1,'posts':[],'pending':None};self.saved=[]
 def save(self,state):self.saved.append(copy.deepcopy(state));self.state=state

class DailyTests(unittest.TestCase):
 def test_pending_then_confirm(self):
  j=Journal();n={'id':1,'country_code':'FR'}
  reserve(j,n,'preview')
  with self.assertRaises(ValueError):check_ready(j.state,'2026-01-01')
  self.assertEqual(j.state['posts'],[])
  finish(j,'123');self.assertEqual(j.state['posts'][0]['status_id'],'123')
  self.assertFalse(check_ready(j.state,datetime.now(timezone.utc).date().isoformat()))
 def test_write_failure_blocks_reservation(self):
  j=Journal()
  with patch.object(j,'save',side_effect=RuntimeError('conflict')):
   with self.assertRaises(RuntimeError):reserve(j,{'id':1,'country_code':'FR'},'test')
  self.assertEqual(j.state['posts'],[])
 def test_remote_sha_is_required(self):
  j=RemoteJournal.__new__(RemoteJournal);j.url='https://example.test';j.token='test';j.sha='old';j.branch='main'
  with patch('europe_daily.request',return_value={'content':{'sha':'new'}}) as call:
   j.save({'version':1,'posts':[],'pending':None})
   self.assertEqual(call.call_args.args[2]['sha'],'old');self.assertEqual(j.sha,'new')
 def test_wording(self):
  text=text_for({'id':1,'country_code':'FR','lat':48,'lon':2,'tags':{'name':'Test','population':'50'}},10)
  self.assertIn('France',text);self.assertIn('recorded in OSM',text);self.assertIn('within 800 m: 10',text)

if __name__=='__main__':unittest.main()
