"""SmallTownEurope 3x3 OSM tile renderer; no .NET dependency."""
import io
import math
import re
import time
import urllib.request
from pathlib import Path
from PIL import Image

def tile_grid(lat,lon,zoom=16):
    if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat)>85 or abs(lon)>180:
        raise ValueError('Invalid map coordinates')
    if not isinstance(zoom,int) or not 1<=zoom<=19:raise ValueError('Invalid zoom')
    size=2**zoom
    x=math.floor((lon+180)/360*size)
    y=math.floor((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*size)
    return [(col,row,zoom,(x+col-1)%size,y+row-1) for col in range(3) for row in range(3)]

def fetch_tile(z,x,y,cache):
    path=Path(cache)/f'{z}-{x}-{y}.png';expiry=path.with_suffix('.expires')
    if path.exists() and expiry.exists() and float(expiry.read_text())>time.time():
        return path.read_bytes()
    req=urllib.request.Request(f'https://tile.openstreetmap.org/{z}/{x}/{y}.png',headers={'User-Agent':'SmallTownEurope/1.0 (https://en.osm.town/@SmallTownEurope)','Referer':'https://www.openstreetmap.org/'})
    with urllib.request.urlopen(req,timeout=30) as response:
        data=response.read(2_000_001)
        if len(data)>2_000_000:raise ValueError('Oversized tile response')
        cc=response.headers.get('Cache-Control','')
    with Image.open(io.BytesIO(data)) as tile:
        if tile.format!='PNG' or tile.size!=(256,256):raise ValueError('Unexpected tile image')
        tile.load()
    if 'no-store' not in cc.lower():
        age=re.search(r'max-age=(\d+)',cc)
        seconds=int(age[1]) if age else 7*24*3600
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data);expiry.write_text(str(time.time()+seconds))
    return data

def render_map(lat,lon,output,overlay='OSM_copyright.png',cache='tile-cache',fetch=fetch_tile):
    with Image.open(overlay) as source:
        credit=source.convert('RGBA')
    if credit.width>768 or credit.height>768:raise ValueError('Attribution overlay exceeds map')
    canvas=Image.new('RGBA',(768,768))
    for col,row,z,x,y in tile_grid(lat,lon):
        with Image.open(io.BytesIO(fetch(z,x,y,cache))) as tile:
            if tile.size!=(256,256) or tile.format!='PNG':raise ValueError('Invalid tile')
            canvas.paste(tile.convert('RGBA'),(col*256,row*256))
    canvas.alpha_composite(credit,(768-credit.width,768-credit.height))
    output=Path(output);temporary=output.with_name(output.name+'.tmp')
    canvas.convert('RGB').save(temporary,format='PNG');temporary.replace(output)
