"""Country attribution and pure selection helpers; no network or publishing."""
import argparse
import json
import random
import re
from pathlib import Path

EXCLUDED = {21512705, 27255545, 240052706}


def attribute(dataset, cache):
    countries = {}
    for path in sorted(Path(cache).glob('*.json')):
        match = re.match(r'^([A-Z]{2})(?:-|_tile_)', path.name)
        if not match:
            continue
        country = match[1]
        if country in {'RU', 'UA'}:
            raise ValueError('Excluded country present in collection cache')
        response = json.loads(path.read_text(encoding='utf-8'))
        if response.get('remark'):
            raise ValueError(f'Failed response in cache: {path.name}')
        for node in response.get('elements', []):
            if node.get('type') == 'node':
                countries.setdefault(node['id'], set()).add(country)
    output = {**dataset, 'elements': []}
    for node in dataset['elements']:
        if node['id'] in EXCLUDED:
            continue
        matches = countries.get(node['id'], set())
        if len(matches) != 1:
            raise ValueError(f"Node {node['id']} has missing/ambiguous country: {sorted(matches)}")
        output['elements'].append({**node, 'country_code': next(iter(matches))})
    if not output['elements']:
        raise ValueError('No candidates remain')
    return output


def ordered_candidates(nodes, history, rng=None):
    """Least recently posted country first, shuffled ties/towns, no last-country reuse.

    history is an ordered list of SUCCESSFUL posts, oldest first. Failed attempts
    must never be appended. Caller must persist history before another run.
    """
    rng = rng or random.Random()
    used = {p['node_id'] for p in history}
    last_country = history[-1]['country_code'] if history else None
    last_seen = {p['country_code']: i for i, p in enumerate(history)}
    groups = {}
    seen = set()
    for node in nodes:
        code = node.get('country_code', '')
        if not re.fullmatch('[A-Z]{2}', code):
            raise ValueError(f"Missing country for node {node['id']}")
        if node['id'] in seen:
            raise ValueError('Duplicate candidate ID')
        seen.add(node['id'])
        if node['id'] not in used | EXCLUDED and code != last_country:
            groups.setdefault(code, []).append(node)
    countries = list(groups)
    rng.shuffle(countries)
    countries.sort(key=lambda c: last_seen.get(c, -1))
    result = []
    for code in countries:
        rng.shuffle(groups[code])
        result.extend(groups[code])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--collection-cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() == args.dataset.resolve():
        parser.error('Choose a new output path; input is never overwritten')
    result = attribute(json.loads(args.dataset.read_text(encoding='utf-8')), args.collection_cache)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f"Attributed {len(result['elements'])} candidates across {len({n['country_code'] for n in result['elements']})} countries")


if __name__ == '__main__':
    main()
