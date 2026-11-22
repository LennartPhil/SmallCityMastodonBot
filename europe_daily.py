"""Daily Europe controller. Preview by default; --publish requires explicit enablement."""
import argparse
import base64
import copy
import json
import os
import subprocess
import time
import urllib.request
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from europe_rotation import ordered_candidates

COUNTRIES = dict(AL='Albania', AT='Austria', BA='Bosnia and Herzegovina', BG='Bulgaria', BY='Belarus', CZ='Czechia', ES='Spain', FI='Finland', FR='France', GB='United Kingdom', GR='Greece', HR='Croatia', IT='Italy', LT='Lithuania', MD='Moldova', ME='Montenegro', MK='North Macedonia', PL='Poland', PT='Portugal', RO='Romania', RS='Serbia', SE='Sweden', SI='Slovenia', TR='Türkiye', XK='Kosovo')

def request(url, token=None, data=None, method=None, headers=None):
    h={'User-Agent':'SmallTownEurope/1.0 (https://en.osm.town/@SmallTownEurope)', **(headers or {})}
    if token:h['Authorization']='Bearer '+token
    if isinstance(data,dict):
        data=json.dumps(data).encode();h['Content-Type']='application/json'
    with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h,method=method),timeout=90) as r:
        return json.load(r)

class RemoteJournal:
    def __init__(self):
        self.repo=os.environ['GITHUB_REPOSITORY'];self.token=os.environ['GH_TOKEN']
        self.branch=os.environ.get('EUROPE_STATE_BRANCH','main')
        self.url=f'https://api.github.com/repos/{self.repo}/contents/europe-posting-history.json'
        payload=request(self.url+'?ref='+urllib.parse.quote(self.branch),self.token)
        self.sha=payload['sha'];self.state=json.loads(base64.b64decode(payload['content']))
        if self.state.get('version')!=1 or not isinstance(self.state.get('posts'),list):raise ValueError('Invalid journal')
    def save(self,state):
        result=request(self.url,self.token,dict(message='Update Europe posting journal',branch=self.branch,sha=self.sha,content=base64.b64encode(json.dumps(state,ensure_ascii=False,indent=2).encode()).decode()),method='PUT')
        self.sha=result['content']['sha'];self.state=state

def check_ready(state,today):
    if state.get('pending'):raise ValueError('Unresolved publication: inspect Mastodon and reconcile the journal before another run')
    return not any(p['posted_at'][:10]==today for p in state['posts'])

def reserve(journal,node,text):
    state=copy.deepcopy(journal.state)
    if not check_ready(state,datetime.now(timezone.utc).date().isoformat()):raise ValueError('Already posted today')
    if node['id'] in {p['node_id'] for p in state['posts']}:raise ValueError('Already posted town')
    if state['posts'] and state['posts'][-1]['country_code']==node['country_code']:raise ValueError('Repeated country')
    state['pending']={'node_id':node['id'],'country_code':node['country_code'],'key':str(uuid.uuid4()),'text':text,'started_at':datetime.now(timezone.utc).isoformat()}
    journal.save(state) # MUST succeed before any Mastodon mutation
    return state['pending']['key']

def finish(journal,status_id):
    if not status_id:raise ValueError('Missing Mastodon status ID')
    state=copy.deepcopy(journal.state);p=state['pending']
    state['posts'].append(dict(node_id=p['node_id'],country_code=p['country_code'],status_id=str(status_id),posted_at=datetime.now(timezone.utc).isoformat()))
    state['pending']=None;journal.save(state)

def building_count(node):
    query=f'[out:json][timeout:60];nwr(around:800,{node["lat"]},{node["lon"]})["building"];out count;'
    endpoint=os.environ['OVERPASS_PRIMARY_URL']
    if not endpoint.startswith('https://'):raise ValueError('HTTPS endpoint required')
    data=request(endpoint,data=urllib.parse.urlencode({'data':query}).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})
    if data.get('remark'):raise ValueError('Overpass returned an error')
    snapshot=datetime.fromisoformat(data['osm3s']['timestamp_osm_base'].replace('Z','+00:00'))
    age=(datetime.now(timezone.utc)-snapshot).total_seconds()
    if not -300<=age<=48*3600:raise ValueError('Stale Overpass snapshot')
    elements=data['elements']
    if len(elements)!=1 or elements[0]['type']!='count':raise ValueError('Incomplete count response')
    tags=elements[0]['tags'];counts=[int(tags[k]) for k in ('nodes','ways','relations')];total=int(tags['total'])
    if min(counts)<0 or sum(counts)!=total:raise ValueError('Invalid count')
    return total

def text_for(node,count):
    return (f'{node["tags"]["name"]}, {COUNTRIES[node["country_code"]]}\n'
            'A small place to explore on OpenStreetMap—are there any missing details?\n\n'
            f'Population recorded in OSM: {node["tags"]["population"]}\n'
            f'Mapped building objects within 800 m: {count}\n\n'
            f'https://www.openstreetmap.org/#map=16/{node["lat"]}/{node["lon"]}\n#OpenStreetMap #SmallTownEurope')

def publish(text,image,key):
    token=os.environ['MASTODON_API_KEY_EU'];root='https://en.osm.town'
    account=request(root+'/api/v1/accounts/verify_credentials',token)
    if account['username'].lower()!='smalltowneurope':raise ValueError('Wrong Mastodon account')
    boundary=uuid.uuid4().hex
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="description"\r\n\r\nOpenStreetMap view of the featured settlement at posting time.\r\n'
          f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="town.png"\r\nContent-Type: image/png\r\n\r\n').encode()+image.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
    media=request(root+'/api/v2/media',token,body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    for _ in range(30):
        if media.get('url'):break
        time.sleep(2);media=request(root+'/api/v1/media/'+str(media['id']),token)
    else:raise ValueError('Media processing timed out; reconcile pending journal')
    status=request(root+'/api/v1/statuses',token,dict(status=text,media_ids=[str(media['id'])],language='en',visibility='public'),headers={'Idempotency-Key':key})
    return status['id']

def main():
    p=argparse.ArgumentParser();p.add_argument('--publish',action='store_true');args=p.parse_args()
    if args.publish and os.environ.get('EUROPE_ENABLE_POSTING')!='true':raise ValueError('Publishing is not enabled')
    journal=RemoteJournal()
    if not check_ready(journal.state,datetime.now(timezone.utc).date().isoformat()):
        print('Already posted today; skipping.');return
    data=json.loads(Path('townsList_Europe_countries.json').read_text())
    nodes=ordered_candidates(data['elements'],journal.state['posts'])
    # Round-robin the recency-ordered groups so a failed country cannot consume
    # the entire bounded search before another country receives an attempt.
    groups={}
    for n in nodes:groups.setdefault(n['country_code'],[]).append(n)
    attempts=[]
    while groups and len(attempts)<50:
        for code in list(groups):
            attempts.append(groups[code].pop(0))
            if not groups[code]:del groups[code]
            if len(attempts)==50:break
    start=time.monotonic()
    for n in attempts:
        if time.monotonic()-start>600:break
        pop=int(n['tags']['population'])
        if not 1<=pop<=999:continue
        count=building_count(n)
        if count>25 or 2*count>=pop:
            print(f'Rejected {n["id"]}: {count} buildings');time.sleep(10);continue
        text=text_for(n,count);Path('europe-post.txt').write_text(text)
        image=Path('europe-preview.png')
        subprocess.run(['dotnet','run','--project','SmallCityMastodonBot.csproj','--configuration','Release','--no-build','--no-launch-profile','--','/europemap',str(n['lat']),str(n['lon']),str(image)],check=True)
        print(text)
        if args.publish:
            key=reserve(journal,n,text)
            status_id=publish(text,image,key)
            finish(journal,status_id)
            print('Published status '+str(status_id))
        else:print('Preview only: no publication or history update.')
        return
    raise ValueError('No eligible town in bounded country search; no post generated')

if __name__=='__main__':main()
