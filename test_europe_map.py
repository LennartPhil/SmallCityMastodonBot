import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from europe_map import tile_grid,render_map

class MapTests(unittest.TestCase):
 def test_geometry(self):
  grid=tile_grid(0,0);self.assertEqual(grid[4],(1,1,16,32768,32768))
  self.assertEqual(len(set((t[3],t[4]) for t in grid)),9)
  with self.assertRaises(ValueError):tile_grid(float('nan'),0)
 def test_stitch_and_attribution(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);credit=p/'credit.png';Image.new('RGBA',(100,20),(255,255,255,255)).save(credit)
   calls=[]
   def fetch(z,x,y,cache):
    calls.append((x,y));b=io.BytesIO();Image.new('RGB',(256,256),(x%256,y%256,100)).save(b,format='PNG');return b.getvalue()
   render_map(0,0,p/'map.png',credit,fetch=fetch)
   with Image.open(p/'map.png') as im:
    self.assertEqual(im.size,(768,768));self.assertEqual(im.getpixel((767,767)),(255,255,255))
    self.assertEqual(im.getpixel((256,256)),(0,0,100));self.assertEqual(im.getpixel((0,0)),(255,255,100))
   self.assertEqual(len(calls),9)
 def test_missing_attribution_fails_before_download(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(FileNotFoundError):render_map(0,0,Path(d)/'x.png',Path(d)/'missing.png',fetch=lambda *a:self.fail('download attempted'))
 def test_tile_failure_writes_no_output(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);Image.new('RGB',(100,20)).save(p/'credit.png')
   with self.assertRaises(Exception):render_map(0,0,p/'x.png',p/'credit.png',fetch=lambda *a:b'error')
   self.assertFalse((p/'x.png').exists())
if __name__=='__main__':unittest.main()
