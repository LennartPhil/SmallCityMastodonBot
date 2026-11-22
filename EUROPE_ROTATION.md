# Europe on the shared C# bot

EuropeDaily.cs owns Europe's bounded selection and durable history. It calls Program.GenerateImageFromOSMTiles and Program.PostTown, the same renderer and Mastonet publication function used by the other bots. Python remains for offline collection, screening and country attribution, not daily rendering or posting. The experimental Python daily controller and Pillow renderer have been removed.

## Preview and checks

Use the Europe dry run workflow on europe-country-rotation. It builds the shared .NET 9 project, runs /europetest offline checks, then runs /europe without --publish. Inspect europe-preview.png and europe-post.txt in the artifact. A green workflow alone is not proof of a usable map.

Local command after building:
`dotnet run --project SmallCityMastodonBot.csproj --configuration Release --no-build --no-launch-profile -- /europe`

The preview needs GH_TOKEN, GITHUB_REPOSITORY, EUROPE_STATE_BRANCH and OVERPASS_PRIMARY_URL. It reads the remote journal but never writes history or calls Mastodon.

## Selection

The 2,207 screened candidates across 25 countries are retained unchanged. Population must be 1–999, live building count at most 25, and twice the building count strictly less than population. Counts are OSM building objects within 800 m, not houses or proof of missing mapping. Overpass errors, incomplete counts and snapshots older than 48 hours stop the run.

Previously posted nodes and the previous successful country are excluded. Countries never posted or least recently posted are preferred, with randomized ties. A round-robin search checks at most 50 candidates and a ten-minute selection budget between requests. No suitable candidate means no post.

## Durable history

europe-posting-history.json is read from GitHub every run. A pending record is saved with a compare-SHA update BEFORE Mastodon uploads or publication. Only a returned status ID is saved as a successful post. An unresolved pending record blocks future runs; publication is not automatically retried. One successful post per UTC day is allowed. The workflow serializes production runs.

If a request or final journal write fails, inspect Mastodon first. If a post exists, append its node_id, country_code, actual status_id and posted_at to posts, then clear pending. Only clear pending without adding a post when positively confirmed that no post exists. Never clear pending automatically on a timeout.

## Map blocker and dependencies

The renderer still uses Matt's OSM tile source and ImageSharp 3.1.12 dependencies. Returning to C# does not guarantee tile access. The exact Access blocked tile observed in run 45039931108 is rejected by decoded-pixel fingerprint; changed error artwork is not guaranteed to be detected. Inspect the first real image before launch. Do not change identities or endpoints to evade a block; resolve permitted tile access with Matt.

Existing ImageSharp vulnerability warnings remain unresolved. No licensing-related version upgrade is included. Agree dependency remediation with the shared project maintainer.

## Launch gates

1. Pass the C# build and /europetest checks.
2. Complete a real preview and visually verify the map and attribution.
3. Confirm ONE hosting repository with Matt; never activate both forks.
4. Put this code, dataset and journal on its main branch. Configure OVERPASS_PRIMARY_URL and MASTODON_API_KEY_EU secrets.
5. Ensure Actions can update the journal (contents: write and compatible branch rules).
6. Only after those checks set EUROPE_ENABLE_POSTING=true. The daily schedule is 19:05 UTC. Manual publication also requires main, --publish and the enable variable.
7. Check the first real post and matching history record. Unset the variable to disable scheduling.

Replies and monthly summaries are not enabled for Europe. Their text parsers have not been adapted to Europe's wording. The Europe overview map remains a post-launch task.
