#!/usr/bin/env python3
"""Pre-screen an existing SmallTown candidate JSON using small Overpass batches.

Python 3.10+, standard library only. No Mastodon token or posting code.
Set OVERPASS_PRIMARY_URL in the environment; it is never written to reports.

Example (a deliberately small pilot):
  python3 screen_towns.py townsList_Corsica_test.json --limit 100 --seed 2026 --output townsList_Corsica_screened.json

Rechecks current place/population tags and counts nwr[building] within 800m,
matching the bot's building query. Up to 25 buildings is eligible by default;
use --max-buildings to change it and match the C# bot configuration. Building
tag values are not reinterpreted: even building=no is counted, as in the bot.
Candidates also require twice the building count to be strictly below population.
This is a conservative heuristic, not a measure of residential completeness.
Batch size defaults to 5; requests are sequential, spaced by 10 seconds.
Valid responses are cached for 24h; rerun the same command to resume.
Source snapshots older than 48h are rejected. Errors never become zero counts.

This script does not establish geographic scope. Supply a scoped candidate
list. Nodes moved more than 50m since that list are withheld for scope review.
The full unfiltered input is preserved. A companion report records every
result, building count and source date. No empty bot dataset is written.
The bot MUST recheck building counts before posting, with the SAME threshold.
Sampling uses a deterministic seeded hash of node IDs, not oldest-ID order.
Use --exclude-ids for settlements manually reviewed as already well mapped.
"""

import argparse
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


def utcnow():
    return datetime.now(timezone.utc)


def date(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Missing timezone in response/cache timestamp')
    return parsed


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def query_for(ids):
    return f'''[out:json][timeout:60];
node(id:{','.join(map(str, ids))})->.towns;
foreach.towns->.town(
  .town out body;
  nwr(around.town:800)["building"];
  out count;
);
.towns out count;'''


def valid_node(node):
    if not isinstance(node, dict) or node.get('type') != 'node':
        return False
    if type(node.get('id')) is not int or node['id'] <= 0:
        return False
    for key, bound in [('lat', 90), ('lon', 180)]:
        n = node.get(key)
        if type(n) not in (int, float) or not math.isfinite(n) or not -bound <= n <= bound:
            return False
    return isinstance(node.get('tags'), dict)


def population_ok(tags):
    pop = tags.get('population', '')
    return (tags.get('place') in ('town', 'village', 'hamlet')
            and isinstance(tags.get('name'), str) and bool(tags['name'].strip())
            and isinstance(pop, str) and re.fullmatch(r'[0-9]{1,12}', pop) is not None
            and 1 <= int(pop) <= 999)


def parse_count(item):
    if not isinstance(item, dict) or item.get('type') != 'count':
        raise ValueError('Missing building count/completion marker')
    tags = item.get('tags', {})
    values = {}
    for key in ('nodes', 'ways', 'relations', 'total'):
        value = tags.get(key)
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value):
            raise ValueError('Invalid count field: ' + key)
        values[key] = int(value)
    if values['total'] != values['nodes'] + values['ways'] + values['relations']:
        raise ValueError('Count components do not match total')
    return values


def validate(data, ids):
    if not isinstance(data, dict):
        raise ValueError('Response is not an object')
    if data.get('remark'):
        raise ValueError('Overpass remark: ' + str(data['remark']))
    timestamp = data.get('osm3s', {}).get('timestamp_osm_base')
    if not isinstance(timestamp, str):
        raise ValueError('Missing source snapshot timestamp')
    age = (utcnow() - date(timestamp)).total_seconds()
    if age > 48 * 3600 or age < -300:
        raise ValueError('Source snapshot is stale or unexpectedly in the future')
    elements = data.get('elements')
    if not isinstance(elements, list) or not elements or len(elements) % 2 != 1:
        raise ValueError('Incomplete response: expected node/count pairs and completion marker')
    completion = parse_count(elements[-1])
    found = {}
    for index in range(0, len(elements) - 1, 2):
        node = elements[index]
        if not valid_node(node) or node['id'] not in ids or node['id'] in found:
            raise ValueError('Invalid, unexpected or duplicate settlement in response')
        found[node['id']] = (node, parse_count(elements[index + 1]))
    if completion != {'nodes': len(found), 'ways': 0, 'relations': 0, 'total': len(found)}:
        raise ValueError('Incomplete response: completion count mismatch')
    return found, timestamp


def moved_metres(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    dlat = lat2 - lat1
    dlon = math.radians(b['lon'] - a['lon'])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=20, help='Maximum candidates for this run (default 20); use --all for all')
    parser.add_argument('--all', action='store_true', help='Process all input candidates; potentially many requests')
    parser.add_argument('--max-buildings', type=int, default=25, help='Inclusive building limit (default 25); match the bot config')
    parser.add_argument('--seed', type=int, default=2026, help='Reproducible sampling seed (default 2026)')
    parser.add_argument('--exclude-ids', nargs='*', type=int, default=[], help='OSM node IDs manually excluded from sampling')
    parser.add_argument('--batch-size', type=int, default=5, choices=range(1, 11))
    parser.add_argument('--cache', type=Path, default=Path('screening-cache'))
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    endpoint = os.environ.get('OVERPASS_PRIMARY_URL', '').strip()
    uri = urllib.parse.urlsplit(endpoint)
    if uri.scheme != 'https' or not uri.hostname:
        parser.error('Set OVERPASS_PRIMARY_URL to the HTTPS interpreter endpoint')
    if args.output.suffix != '.json' or args.output.resolve() == args.input.resolve():
        parser.error('Use a separate output .json file; the population-only input must be preserved')
    report_path = args.output.with_suffix('.report.json')
    if report_path.resolve() == args.input.resolve() or report_path == args.output:
        parser.error('Input, output and report paths must differ')
    if args.output.exists():
        parser.error('Output already exists. Choose a new output filename; cached requests can still be reused.')
    if args.limit < 1:
        parser.error('--limit must be positive')
    if args.max_buildings < 0 or any(i <= 0 for i in args.exclude_ids):
        parser.error('--max-buildings must be nonnegative; excluded node IDs must be positive')
    raw_input = args.input.read_bytes()
    source = json.loads(raw_input)
    elements = source.get('elements') if isinstance(source, dict) else None
    if not isinstance(elements, list) or not elements:
        parser.error('Input needs a nonempty elements list')
    unique = {}
    for node in elements:
        if not valid_node(node) or not population_ok(node['tags']):
            parser.error('Input must contain valid named settlement nodes with populations 1–999')
        if node['id'] in unique and unique[node['id']] != node:
            parser.error('Conflicting duplicate input node')
        unique[node['id']] = node
    ordered = sorted(unique.values(), key=lambda n: n['id'])
    excluded = set(args.exclude_ids)
    pool = [n for n in ordered if n['id'] not in excluded]
    pool.sort(key=lambda n: hashlib.sha256(f"{args.seed}:{n['id']}".encode()).digest())
    candidates = pool if args.all else pool[:args.limit]
    if not candidates:
        parser.error('No candidates remain after manual exclusions')
    print(f'Screening {len(candidates)} of {len(ordered)} unique input candidates; maximum {args.max_buildings} buildings / 800m; seed {args.seed}.', flush=True)
    eligible, records, timestamps = [], [], []
    last_request = None
    for start in range(0, len(candidates), args.batch_size):
        batch = candidates[start:start + args.batch_size]
        ids = [n['id'] for n in batch]
        query = query_for(ids)
        key = hashlib.sha256((endpoint + '\n' + query).encode()).hexdigest()
        cache_path = args.cache / (key + '.json')
        data = None
        if cache_path.exists() and not args.refresh:
            try:
                cached = json.loads(cache_path.read_text())
                cache_age = (utcnow() - date(cached['fetched_at'])).total_seconds()
                if 0 <= cache_age <= 24 * 3600:
                    validate(cached['response'], ids)
                    data = cached['response']
                    print(f'Batch {start // args.batch_size + 1}: cached', flush=True)
            except (ValueError, KeyError, TypeError):
                pass
        if data is None:
            for attempt in range(3):
                if last_request is not None:
                    time.sleep(max(0, 10 - (time.monotonic() - last_request)))
                print(f'Batch {start // args.batch_size + 1}: requesting {len(ids)} towns, attempt {attempt + 1}/3', flush=True)
                request = urllib.request.Request(endpoint,
                    data=urllib.parse.urlencode({'data': query}).encode(),
                    headers={'User-Agent': 'SmallTownEuropeScreening/1.1', 'Accept': 'application/json'})
                try:
                    with urllib.request.urlopen(request, timeout=90) as response:
                        data = json.load(response)
                    validate(data, ids)
                    last_request = time.monotonic()
                    write_json(cache_path, {'fetched_at': utcnow().isoformat(), 'response': data})
                    break
                except (OSError, ValueError) as exc:
                    last_request = time.monotonic()
                    data = None
                    message = str(exc).replace(endpoint, '<private endpoint>').replace(uri.hostname, '<private host>')
                    print(f'Batch failed: {message}', flush=True)
                    retry = not isinstance(exc, urllib.error.HTTPError) or exc.code in (429, 502, 503, 504)
                    if not retry or attempt == 2:
                        raise ValueError('Screening stopped: no final dataset written; successful batches are cached') from None
                    delay = 30 * (2 ** attempt)
                    if isinstance(exc, urllib.error.HTTPError):
                        retry_after = exc.headers.get('Retry-After', '')
                        if retry_after.isdigit():
                            delay = max(delay, int(retry_after))
                    print(f'Retrying in {delay}s', flush=True)
                    time.sleep(delay)
        found, timestamp = validate(data, ids)
        timestamps.append(timestamp)
        for original in batch:
            record = {'id': original['id'], 'name': original['tags']['name'], 'snapshot': timestamp}
            if original['id'] not in found:
                record['status'] = 'missing_from_current_data'
            else:
                current, counts = found[original['id']]
                record['building_counts'] = counts
                if not population_ok(current['tags']):
                    record['status'] = 'no_longer_population_qualified'
                elif moved_metres(original, current) > 50:
                    record['status'] = 'moved_requires_scope_review'
                elif 2 * counts['total'] >= int(current['tags']['population']):
                    record['status'] = 'buildings_at_least_half_population'
                elif counts['total'] > args.max_buildings:
                    record['status'] = 'too_many_buildings'
                else:
                    record['status'] = 'eligible'
                    eligible.append({**current, 'tags': {**current['tags'], 'population': str(int(current['tags']['population']))}})
            records.append(record)
            count = record.get('building_counts', {}).get('total', 'unknown')
            print(f"{record['name']}: {count} buildings — {record['status']}", flush=True)
    report = {'generated_at': utcnow().isoformat(), 'input_file': args.input.name,
              'input_sha256': hashlib.sha256(raw_input).hexdigest(),
              'input_candidates': len(ordered), 'screened_candidates': len(candidates),
              'all_input_screened': len(candidates) == len(ordered),
              'all_nonexcluded_input_screened': len(candidates) == len(pool),
              'sampling_method': 'SHA256 of seed:node_id; first limit entries in hash order',
              'seed': args.seed, 'manually_excluded_ids': sorted(excluded),
              'eligible_candidates': len(eligible), 'radius_metres': 800, 'maximum_buildings': args.max_buildings,
              'population_rule': '2 * building_count < population',
              'threshold_comparison_note': 'All thresholds also apply the population rule',
              'threshold_comparison': {
                  str(limit): sum(r['status'] in ('eligible', 'too_many_buildings')
                                  and r.get('building_counts', {}).get('total', limit + 1) <= limit
                                  for r in records)
                  for limit in sorted({10, 25, 50, 100, args.max_buildings})},
              'count_semantics': 'OSM nodes + ways + relations carrying building tag; not necessarily distinct real-world buildings',
              'geography': 'Inherited from input; full Europe boundary not established here',
              'live_recheck_required': True, 'results': records}
    write_json(report_path, report)
    if not eligible:
        print(f'No eligible towns in this sample. Report saved to {report_path}; no empty bot dataset written.', flush=True)
        return
    output = {'version': 0.6, 'generator': 'SmallTownEuropeScreening/1.1',
              'osm3s': {'timestamp_osm_base': min(timestamps),
                        'copyright': 'Data © OpenStreetMap contributors, ODbL 1.0. https://www.openstreetmap.org/copyright'},
              'elements': sorted(eligible, key=lambda n: n['id'])}
    write_json(args.output, output)
    print(f'Saved {len(eligible)} screened candidates to {args.output}. Report: {report_path}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        sys.exit(f'FAILED: {exc}')
