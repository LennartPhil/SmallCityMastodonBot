import json
import random
import tempfile
import unittest
from pathlib import Path
from europe_rotation import attribute, ordered_candidates


class RotationTests(unittest.TestCase):
    def test_rotation_and_exhaustion(self):
        nodes = [{'id': i, 'country_code': c} for i,c in enumerate(['FR','FR','RO','RO','GR','GR'],1)]
        history=[]
        for _ in range(6):
            selected=ordered_candidates(nodes,history,random.Random(7))[0]
            self.assertNotIn(selected['id'],[p['node_id'] for p in history])
            if history:self.assertNotEqual(selected['country_code'],history[-1]['country_code'])
            history.append({'node_id':selected['id'],'country_code':selected['country_code']})
        self.assertEqual(ordered_candidates(nodes,history),[])

    def test_recency(self):
        nodes=[{'id':1,'country_code':'FR'},{'id':2,'country_code':'RO'},{'id':3,'country_code':'GR'}]
        history=[{'node_id':50,'country_code':'RO'},{'node_id':51,'country_code':'FR'}]
        self.assertEqual([n['country_code'] for n in ordered_candidates(nodes,history)],['GR','RO'])

    def test_one_country_skips(self):
        self.assertEqual(ordered_candidates([{'id':2,'country_code':'FR'}],[{'node_id':1,'country_code':'FR'}]),[])

    def test_country_mapping_and_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            for name,ids in [('FR_tile_0_0-hash.json',[1]),('FR_tile_0_1-hash.json',[1]),('TR-34:Fatih-hash.json',[2])]:
                (p/name).write_text(json.dumps({'elements':[{'type':'node','id':i} for i in ids]}))
            d={'elements':[{'id':1},{'id':2}]}
            self.assertEqual([n['country_code'] for n in attribute(d,p)['elements']],['FR','TR'])
            (p/'RO-hash.json').write_text(json.dumps({'elements':[{'type':'node','id':1}]}))
            with self.assertRaises(ValueError):attribute(d,p)

    def test_missing_country(self):
        with self.assertRaises(ValueError):ordered_candidates([{'id':1}],[])


if __name__=='__main__':unittest.main()
