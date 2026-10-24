#!/usr/bin/env python3
"""Build a SmallCityMastodonBot candidate list using Python 3.10+ (no packages).

Quick start, from the bot repository:
  python3 generate_europe_towns.py --countries AT --output townsList_Europe_test.json
  python3 generate_europe_towns.py --countries AT DE CH --output townsList_Europe.json

Use --countries all for the 51 country entries in the user's reference list:
https://simple.wikipedia.org/w/index.php?title=List_of_European_countries&oldid=11036573
IMPORTANT: country areas include their entire OSM extent, including Asian and
overseas parts. 'all' is NOT a geographic Europe polygon. Agree scope first.
XK is the commonly used Kosovo code; a missing area fails loudly.

This selects named place=town/village/hamlet NODES with population 1..999.
Ways/relations, missing/non-integer populations, cities, isolated dwellings,
and locality tags are excluded. Population dates are retained, not verified.
This is a candidate list, NOT a list of confirmed undermapped settlements.
Building counts are checked later by the bot. More candidate nodes in a
country mean more chances of selection by the existing bot.

Requests are sequential, cached and spaced by 10 seconds. Re-run to resume.
Use --refresh to replace cached responses. On any failure no final output is
written; an existing output stays intact. Cache snapshots can have different
dates; their metadata is retained in the adjacent .report.json file.
No Mastodon credentials are needed and this script never posts to Mastodon.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

COUNTRIES = '''AL AD AM AT AZ BY BE BA BG HR CY CZ DK EE FI FR GE DE GR HU
IS IE IT KZ XK LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES
SE CH TR UA GB VA'''.split()


def query_for(code):
    return f'''[out:json][timeout:180];
area["ISO3166-1"="{code}"]["boundary"="administrative"]["admin_level"="2"]->.country;
.country out count;
node(area.country)["place"~"^(town|village|hamlet)$"]["name"]
  ["population"~"^[0-9]+$"](if:number(t["population"]) > 0 && number(t["population"]) < 1000);
out body;'''


def validate_response(data):
    if not isinstance(data, dict) or data.get('remark'):
        raise ValueError(f"Overpass error or partial response: {str(data)[:300]}")
    elements = data.get('elements')
    if not isinstance(elements, list) or not elements or elements[0].get('type') != 'count':
        raise ValueError('Missing country-area count; refusing potentially incomplete data')
    if elements[0].get('tags', {}).get('areas') != '1':
        raise ValueError(f"Expected exactly one country area: {elements[0]}")
    if not data.get('osm3s', {}).get('timestamp_osm_base'):
        raise ValueError('Missing OSM source timestamp')
    return data


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def select_nodes(data):
    accepted, reasons = [], Counter()
    for item in data['elements'][1:]:
        tags = item.get('tags', {})
        pop = str(tags.get('population', ''))
        if item.get('type') != 'node' or tags.get('place') not in ('town', 'village', 'hamlet'):
            reasons['not_place_node'] += 1
        elif not isinstance(tags.get('name'), str) or not tags['name'].strip():
            reasons['missing_name'] += 1
        elif not re.fullmatch(r'[0-9]+', pop) or not 1 <= int(pop) <= 999:
            reasons['invalid_population'] += 1
        elif (not isinstance(item.get('id'), int) or isinstance(item.get('id'), bool)
              or item['id'] <= 0):
            reasons['invalid_id'] += 1
        elif not all(isinstance(item.get(k), (int, float)) and
                     not isinstance(item[k], bool) and math.isfinite(item[k]) and
                     -limit <= item[k] <= limit for k, limit in [('lat', 90), ('lon', 180)]):
            reasons['invalid_coordinates'] += 1
        else:
            accepted.append({**item, 'tags': {**tags, 'population': str(int(pop))}})
    return accepted, dict(reasons)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--countries', nargs='+', required=True, help='Codes such as AT DE CH, or all (entire countries)')
    parser.add_argument('--output', type=Path, default=Path('townsList_Europe.json'))
    parser.add_argument('--cache', type=Path, default=Path('towns-cache'))
    parser.add_argument('--endpoint', default='https://overpass-api.de/api/interpreter')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    codes = COUNTRIES if args.countries == ['all'] else list(dict.fromkeys(c.upper() for c in args.countries))
    if any(c not in COUNTRIES for c in codes):
        parser.error('Unknown country code; use --help for scope. United Kingdom uses GB.')
    if not args.endpoint.startswith('https://'):
        parser.error('Use an HTTPS endpoint')
    nodes, sources, duplicates = {}, {}, 0
    last_request = None
    for code in codes:
        query = query_for(code)
        key = hashlib.sha256((args.endpoint + query).encode()).hexdigest()[:16]
        cache_path = args.cache / f'{code}-{key}.json'
        if cache_path.exists() and not args.refresh:
            data = validate_response(json.loads(cache_path.read_text(encoding='utf-8')))
            print(f'{code}: using cache', flush=True)
        else:
            for attempt in range(3):
                if last_request is not None:
                    time.sleep(max(0, 10 - (time.monotonic() - last_request)))
                print(f'{code}: fetching (attempt {attempt + 1}/3)', flush=True)
                request = urllib.request.Request(args.endpoint,
                    data=urllib.parse.urlencode({'data': query}).encode(),
                    headers={'User-Agent': 'SmallTownEuropeDataset/1.0', 'Accept': 'application/json'})
                try:
                    with urllib.request.urlopen(request, timeout=240) as response:
                        data = validate_response(json.load(response))
                    last_request = time.monotonic()
                    break
                except urllib.error.HTTPError as exc:
                    last_request = time.monotonic()
                    if exc.code not in (429, 502, 503, 504) or attempt == 2:
                        raise
                    wait = exc.headers.get('Retry-After', '')
                    time.sleep(max(30 * (attempt + 1), int(wait) if wait.isdigit() else 0))
                except (urllib.error.URLError, TimeoutError, ValueError):
                    last_request = time.monotonic()
                    if attempt == 2:
                        raise
                    time.sleep(30 * (attempt + 1))
            atomic_json(cache_path, data)
        accepted, skipped = select_nodes(data)
        sources[code] = {'candidates': len(accepted), 'rejected': skipped,
                         'osm3s': data['osm3s'], 'query': query}
        for node in accepted:
            identity = (node['type'], node['id'])
            if identity in nodes:
                duplicates += 1
            else:
                nodes[identity] = node
        print(f'{code}: {len(accepted)} candidates; rejected {skipped}', flush=True)
    if not nodes:
        raise ValueError('No candidates found; refusing to write an empty bot dataset')
    dates = [s['osm3s']['timestamp_osm_base'] for s in sources.values()]
    metadata = {'timestamp_osm_base': min(dates),
                'copyright': 'Data © OpenStreetMap contributors, ODbL 1.0. https://www.openstreetmap.org/copyright'}
    area_dates = [s['osm3s'].get('timestamp_areas_base') for s in sources.values()]
    if all(area_dates):
        metadata['timestamp_areas_base'] = min(area_dates)
    output = {'version': 0.6, 'generator': 'SmallTownEuropeDataset/1.0',
              'osm3s': metadata, 'elements': sorted(nodes.values(), key=lambda x: x['id'])}
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'countries': codes,
              'scope': 'Entire selected OSM country areas, not a geographic Europe polygon',
              'candidate_count': len(nodes), 'duplicate_node_ids_removed': duplicates,
              'timestamp_note': 'Dataset timestamps are oldest source dates; see each country below.',
              'sources': sources}
    atomic_json(args.output.with_suffix('.report.json'), report)
    atomic_json(args.output, output)
    print(f'Saved {len(nodes)} candidates to {args.output}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        sys.exit(f'FAILED: {exc}\nNo final dataset was written. Re-run to resume cached countries.')
