# Europe daily controller

europe_daily.py now owns the Europe selection, count validation and publication flow. It uses europe_map.py with Pillow 13.0.0 for the same 3x3, zoom-16 tile layout and existing OSM_copyright.png overlay. Europe workflows require only Python 3.12. Other bots retain their existing entry points. The earlier SQLite helper is retained for tests/local experimentation; production uses the GitHub JSON journal instead.

## Preview

Run the Europe daily controller workflow with publish unchecked. It reads history, selects a country and town, checks a fresh Overpass building count, renders an attributed map and uploads the text/image. It never updates posting history in preview mode.

Country-attributed dataset: townsList_Europe_countries.json (2,207 screened candidates, 25 countries). Country attribution was recovered from the original collection caches. Automated candidates have not all received manual review. Population values can be historical.

## Durable history

europe-posting-history.json is read directly from GitHub at every run. Updates use the current blob SHA as an optimistic concurrency guard. A pending record is committed BEFORE Mastodon uploads/publication. The success record is committed with the returned Mastodon status ID. An unresolved pending entry blocks another run. Concurrent reservations cannot both succeed.

If a request or final journal write fails, inspect the account first. If the status exists, append a success record using pending.node_id, pending.country_code, actual status_id and posted_at, then set pending to null. If positively confirmed that no status exists, clear pending. Never clear pending automatically on a timeout. Preserve all earlier history. Restrict workflow execution and journal editing to trusted maintainers.

A successful UTC date can have at most one post. The last successfully posted country is excluded, even after skipped days. Candidates already in history never repeat. At most 50 candidates are checked, spread across countries in recency order; a ten-minute selection budget is checked between requests. Overpass errors stop the run instead of becoming zero counts.

## Launch gates

1. Pass Python controller and renderer CI.
2. Run a preview on this branch and inspect the map/text. Verify the Pillow-generated map and attribution visually.
3. Confirm which SINGLE repository Matt will host; its main branch must contain this code, dataset and journal. Do not activate the same bot in two forks.
4. Add OVERPASS_PRIMARY_URL and MASTODON_API_KEY_EU secrets. The Mastodon account must be SmallTownEurope on en.osm.town.
5. Ensure Actions can update the journal on main (contents: write; branch rules must permit this). A failed reservation prevents posting.
6. Only after preview verification, set repository variable EUROPE_ENABLE_POSTING=true. This enables the daily 19:05 UTC schedule. A manual run with publish checked also requires that variable and main.
7. Inspect the first status and journal record. Disable the variable to stop scheduled posting.

The schedule is present but disabled while EUROPE_ENABLE_POSTING is unset. Replies/monthly posts are not invoked. Preview artifacts are diagnostic, not the persistent state store.

## Validation

Local tests cover country rotation and local journal persistence (7 earlier tests), plus remote SHA guarding, pending/success transitions, failed reservations and wording (4 new tests). CI runs Python tests including the Pillow renderer. The shared C# project and its dependency versions remain as on main; its existing ImageSharp security warnings are NOT resolved by this Europe-only change. A real end-to-end preview and live Mastodon test remain required; mocked/local tests do not establish these.
