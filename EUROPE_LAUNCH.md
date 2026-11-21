# SmallTownEurope launch preparation

The Europe building limit is 25 objects within 800 metres, with a fresh count before each post. A low count does not establish missing mapping. The current townsList_Europe_test.json is a population-only Austria test dataset, not a reviewed launch list.

Before enabling daily posts:

- Collect a geographically scoped dataset across multiple European countries. Retain the agreed Russia/Ukraine exclusions and exclude overseas territories. Document treatment of transcontinental boundaries; do not claim full Europe coverage until implemented.
- Screen candidates at population 1–999 and at most 25 building objects within 800m. Manually review qualifying locations for real mapping opportunities; exclude Obertriesting (27255545) and Gruberau (21512705).
- Commit a nonempty reviewed townsList_Europe.json and change the Europe townFile to that filename. Preserve OSM attribution and collection provenance.
- Run Europe dry run with OVERPASS_PRIMARY_URL set as a repository secret. The dummy token 12345 prevents town publishing. The workflow now enforces the real threshold. Failed or exhausted searches fail the job; the ten-minute workflow timeout remains the hard deadline for network requests.
- Resolve dependency vulnerability warnings and verify the supported .NET runtime with the maintainer before deployment.
- Review generated text, attribution and map, and confirm the bot icon/profile are ready.
- Arrange private token transfer with Matt and add a dedicated Europe secret in the hosting repository. Never commit tokens or private endpoint values.
- Enable one English-language town post per day only in the chosen hosting repository. Leave replies and monthly posts disabled for Europe until separately tested. Confirm posting history/deduplication behavior before sustained operation.

The bounded Europe search tries at most 20 distinct candidates per run, checking a seven-minute budget between candidates. A request already in progress can exceed that budget; the workflow timeout is the final limit. No eligible candidate is a failed run, not permission to relax the threshold.
