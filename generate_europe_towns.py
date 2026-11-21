#!/usr/bin/env python3
"""Build a SmallCityMastodonBot candidate list using Python 3.10+ (no packages).

Quick start, from the bot repository:
  python3 generate_europe_towns.py --countries AT --output townsList_Europe_test.json
  python3 generate_europe_towns.py --countries AT DE CH --output townsList_Europe.json

Use --countries all for the agreed European scope. Russia, Ukraine, Cyprus,
Asian Türkiye, the Caucasus, overseas territories, the Canaries, Madeira and
Azores are excluded. Faroes and British Crown Dependencies are included.
Norway includes coastal islands, not Svalbard/Jan Mayen. Country membership
uses OSM boundaries plus explicit territory clipping boxes. European Türkiye
uses Edirne, Kirklareli and Tekirdag provinces, 25 European Istanbul districts,
and Eceabat/Gelibolu districts. No approximate longitude cutoff is used there.
Each queried area must resolve to exactly one boundary or the run stops.
Boundary tagging can change: a failed lookup needs review, not silent skipping.

Suggested validation run:
  python3 generate_europe_towns.py --countries FR ES PT TR FO --output townsList_scope_test.json
Then:
  python3 generate_europe_towns.py --countries all --output townsList_Europe.json

Implementation references:
https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL
https://wiki.openstreetmap.org/wiki/Tr:Key:boundary
https://istanbul.gov.tr/ (district names)

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
Failed queries and response bodies are saved under overpass-diagnostics/.
The exact Overpass remark is printed, including on intermediate retries.
Use --print-query with one country to inspect its query without making requests.
No Mastodon credentials are needed and this script never posts to Mastodon.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = '2.1'


class OverpassResponseError(ValueError):
    """An explicit Overpass error; only known transient errors are retried."""

    def __init__(self, remark):
        self.remark = str(remark)
        lower = self.remark.lower()
        self.retryable = any(word in lower for word in (
            'timed out', 'timeout', 'out of memory', 'server is probably too busy',
            'rate limit', 'dispatcher_client::request_read_and_idx',
        ))
        super().__init__('Overpass remark: ' + self.remark)


def save_diagnostic(directory, code, attempt, query, body):
    """Save errors separately from successful cache entries. Never save headers."""
    directory.mkdir(parents=True, exist_ok=True)
    label = re.sub(r'[^A-Za-z0-9_-]', '_', code)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    prefix = directory / f'{label}-{stamp}-attempt-{attempt + 1}'
    prefix.with_suffix('.overpassql').write_text(query + '\n', encoding='utf-8')
    response_path = prefix.with_suffix('.response.txt')
    response_path.write_text(body, encoding='utf-8')
    print(f'{code}: saved diagnostic response: {response_path}', flush=True)

# Country membership is the primary filter. Bounding boxes only clip distant
# territories of those countries; they are not used to approximate the Bosphorus.
COUNTRIES = "AL AD AT BY BE BA BG HR CZ DK EE FI FR DE GR HU IS IE IT XK LV LI LT LU MT MD MC ME NL MK NO PL PT RO SM RS SK SI ES SE CH GB VA FO GG JE IM TR".split()
BOUNDS = {
    'FR': (41.3, -5.6, 51.2, 9.7),  # mainland and Corsica
    'ES': (36.0, -9.6, 43.9, 4.4),  # mainland and Balearics
    'PT': (36.9, -9.6, 42.2, -6.1), # mainland only
    'NL': (50.7, 3.1, 53.7, 7.3),
    'DK': (54.4, 7.9, 57.9, 15.3),  # Faroes queried separately
    'NO': (57.8, 4.0, 71.3, 31.3),  # mainland and coastal islands
}
ISTANBUL_WEST = "Arnavutköy|Avcılar|Bağcılar|Bahçelievler|Bakırköy|Başakşehir|Bayrampaşa|Beşiktaş|Beylikdüzü|Beyoğlu|Büyükçekmece|Çatalca|Esenler|Esenyurt|Eyüpsultan|Fatih|Gaziosmanpaşa|Güngören|Kağıthane|Küçükçekmece|Sarıyer|Silivri|Sultangazi|Şişli|Zeytinburnu".split('|')
# Query each administrative unit separately so each missing boundary is an error.
TURKEY_UNITS = ['TR-22', 'TR-39', 'TR-59'] + ['TR-34:' + n for n in ISTANBUL_WEST] + ['TR-17:Eceabat', 'TR-17:Gelibolu']
SCOPE = 'European country areas with explicit territory clips; European Türkiye by province/district boundaries; Russia, Ukraine and Cyprus excluded. Arctic territories not included.'


# Partition the existing France clip into 40 boxes no wider/taller than 2 degrees.
# Border nodes may occur twice; the existing node-ID deduplication removes them.
FRANCE_TILES = {
    f'FR_tile_{row}_{col}': (round(41.3 + row * 2, 1), round(-5.6 + col * 2, 1),
                            min(round(43.3 + row * 2, 1), 51.2),
                            min(round(-3.6 + col * 2, 1), 9.7))
    for row in range(5) for col in range(8)
}


def inside_scope(code, lat, lon):
    if code in FRANCE_TILES:
        code = 'FR'
    bounds = BOUNDS.get(code, (34, -25, 72, 45))
    south, west, north, east = bounds
    return south <= lat <= north and west <= lon <= east


def query_for(code):
    tile_bounds = FRANCE_TILES.get(code)
    if tile_bounds:
        code = 'FR'
    if code.startswith('TR-'):
        province, _, district = code.partition(':')
        selector = f'rel["boundary"="administrative"]["admin_level"="4"]["ISO3166-2"="{province}"];map_to_area->.province;'
        if district:
            selector += f'\nrel(area.province)["boundary"="administrative"]["admin_level"="6"]["name"="{district}"];map_to_area->.country;'
        else:
            selector += '\n.province->.country;'
    else:
        selector = f'area["ISO3166-1"="{code}"]["boundary"="administrative"]->.country;'
    bounds = BOUNDS.get(code, (34, -25, 72, 45))
    bounds = tile_bounds or bounds
    bbox = ','.join(str(v) for v in bounds)
    return f'''[out:json][timeout:180];
{selector}
.country out count;
node(area.country)({bbox})["place"~"^(town|village|hamlet)$"]["name"]
  ["population"~"^[0-9]+$"](if:number(t["population"]) > 0 && number(t["population"]) < 1000);
out body;'''


def validate_response(data):
    if not isinstance(data, dict):
        raise ValueError('Overpass response must be a JSON object')
    if data.get('remark'):
        raise OverpassResponseError(data['remark'])
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


def select_nodes(data, code):
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
        elif not inside_scope(code, item['lat'], item['lon']):
            reasons['outside_geographic_scope'] += 1
        else:
            accepted.append({**item, 'tags': {**tags, 'population': str(int(pop))}})
    return accepted, dict(reasons)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--countries', nargs='+', required=True, help='Codes such as AT FR TR, or all for the agreed Europe scope')
    parser.add_argument('--output', type=Path, default=Path('townsList_Europe.json'))
    parser.add_argument('--cache', type=Path, default=Path('towns-cache'))
    parser.add_argument('--endpoint', default=os.environ.get('OVERPASS_PRIMARY_URL', 'https://overpass-api.de/api/interpreter'))
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--diagnostics', type=Path, default=Path('overpass-diagnostics'))
    parser.add_argument('--print-query', action='store_true', help='Print queries and exit without network requests')
    args = parser.parse_args()
    codes = COUNTRIES if args.countries == ['all'] else list(dict.fromkeys(c.upper() for c in args.countries))
    if any(c not in COUNTRIES for c in codes):
        parser.error('Unknown country code; use --help for scope. United Kingdom uses GB.')
    if not args.endpoint.startswith('https://'):
        parser.error('Use an HTTPS endpoint')
    requested_countries = codes[:]
    codes = [unit for code in codes for unit in (TURKEY_UNITS if code == 'TR' else list(FRANCE_TILES) if code == 'FR' else [code])]
    if args.print_query:
        for code in codes:
            print(f'// {code}\n{query_for(code)}\n')
        return
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
                    headers={'User-Agent': f'SmallTownEuropeDataset/{VERSION}', 'Accept': 'application/json'})
                try:
                    with urllib.request.urlopen(request, timeout=240) as response:
                        raw = response.read().decode('utf-8', errors='replace')
                    try:
                        data = validate_response(json.loads(raw))
                    except ValueError:
                        save_diagnostic(args.diagnostics, code, attempt, query, raw)
                        raise
                    last_request = time.monotonic()
                    break
                except urllib.error.HTTPError as exc:
                    last_request = time.monotonic()
                    with exc:
                        body = exc.read().decode('utf-8', errors='replace')
                    save_diagnostic(args.diagnostics, code, attempt, query, body)
                    print(f'{code}: HTTP {exc.code} {exc.reason}', flush=True)
                    if exc.code not in (429, 502, 503, 504) or attempt == 2:
                        raise
                    wait = exc.headers.get('Retry-After', '')
                    delay = max(30 * (2 ** attempt), int(wait) if wait.isdigit() else 0)
                    print(f'{code}: retrying in {delay}s', flush=True)
                    time.sleep(delay)
                except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                    last_request = time.monotonic()
                    print(f'{code}: {exc}', flush=True)
                    retryable = (isinstance(exc, (urllib.error.URLError, TimeoutError))
                                 or isinstance(exc, json.JSONDecodeError)
                                 or isinstance(exc, OverpassResponseError) and exc.retryable)
                    if not retryable or attempt == 2:
                        raise
                    delay = 30 * (2 ** attempt)
                    print(f'{code}: retrying in {delay}s', flush=True)
                    time.sleep(delay)
            atomic_json(cache_path, data)
        accepted, skipped = select_nodes(data, code)
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
    output = {'version': 0.6, 'generator': f'SmallTownEuropeDataset/{VERSION}',
              'osm3s': metadata, 'elements': sorted(nodes.values(), key=lambda x: x['id'])}
    report = {'generated_at': datetime.now(timezone.utc).isoformat(), 'countries': requested_countries,
              'scope': SCOPE, 'territory_bounds': BOUNDS, 'turkey_units': TURKEY_UNITS,
              'france_tiles': FRANCE_TILES,
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
