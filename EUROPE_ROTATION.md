# Europe country rotation — integration in progress

These modules are tested foundations, not yet called by Program.cs. Do not enable live posting based on this PR.

## Country attribution

Extract towns-cache.tar.gz from the successful population-collection artifact. This is the collection cache, not screening-cache. Run:

```bash
python3 europe_rotation.py townsList_Europe_screened_10000.json --collection-cache towns-cache --output townsList_Europe_countries.json
```

The output preserves screened nodes and adds country_code outside OSM tags. France tiles map to FR, Turkish districts map to TR. Missing/conflicting attribution aborts instead of guessing. The three manually excluded towns are removed. This uses no network requests.

## Selection

ordered_candidates takes candidates and successful posting history. It excludes already posted nodes and the country of the last successful post, sorts countries by least recent use and randomizes tied countries and towns. It returns no candidates when only the last country is available. The caller must apply the live building filters and bounded retries; filter failures must not be recorded as successful posts.

## Journal

PostingHistory uses SQLite transactions. Reserve before publishing, confirm with the returned Mastodon status ID afterward. A pending reservation survives restarts and blocks another post until reconciled. Never release a reservation merely because a publish request timed out: the server may have accepted it. A positively confirmed failure can be released without affecting rotation. Back up the database.

## Remaining integration before launch

- Recover country attribution for the actual 2,207 screened candidates from the collection cache.
- Integrate selection into the C# live checks and text/image generation; dry runs must not advance real history.
- Implement durable remote journal storage for the maintainer's GitHub Actions hosting. A runner-local SQLite file or expiring Actions cache alone is NOT sufficient. Persist the reservation remotely before calling Mastodon and reconcile any uncertain result before another run.
- Connect confirmed Mastodon status IDs to the journal, serialize workflows, and verify restoration across fresh runners.
- Include country and cautious mapping-opportunity wording in posts.
- Test multiple simulated days and an end-to-end dry run, resolve dependency warnings, then separately enable the live schedule.

Local validation: python3 -m unittest -v test_europe_rotation test_europe_history. Seven tests cover rotation, recency, exhaustion, missing/conflicting countries, persistence across reopening, uncertain results and two competing database connections.
