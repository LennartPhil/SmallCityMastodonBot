# SmallTownEurope launch preparation

The Europe building limit is 25 objects within 800 metres, with a fresh count before each post. Europe also rejects candidates when twice the building count is greater than or equal to population (including equality). For population 38, 18 buildings passes this additional rule; 19 or more fails. Buildings are not necessarily homes, population tags can be outdated, and the 800m count can extend beyond settlement boundaries: this is a conservative screening heuristic, not a measured occupancy rate. A low count does not establish missing mapping. The current townsList_Europe_test.json is a population-only Austria test dataset, not a reviewed launch list.

Before enabling daily posts:

- Collect a geographically scoped dataset across multiple European countries. Retain the agreed Russia/Ukraine exclusions and exclude overseas territories. Document treatment of transcontinental boundaries; do not claim full Europe coverage until implemented.
- Screen candidates at population 1–999 and at most 25 building objects within 800m, strictly fewer than half the population. Manually review qualifying locations for real mapping opportunities; exclude Obertriesting (27255545) , Gruberau (21512705), and Leiten (240052706).
- Commit a nonempty reviewed townsList_Europe.json and change the Europe townFile to that filename. Preserve OSM attribution and collection provenance.
- Run Europe dry run with OVERPASS_PRIMARY_URL set as a repository secret. The dummy token 12345 prevents town publishing. The workflow now enforces the real threshold. Failed or exhausted searches fail the job; the ten-minute workflow timeout remains the hard deadline for network requests.
- Resolve dependency vulnerability warnings and verify the supported .NET runtime with the maintainer before deployment.
- Review generated text, attribution and map, and confirm the bot icon/profile are ready.
- Arrange private token transfer with Matt and add a dedicated Europe secret in the hosting repository. Never commit tokens or private endpoint values.
- Enable one English-language town post per day only in the chosen hosting repository. Leave replies and monthly posts disabled for Europe until separately tested. Confirm posting history/deduplication behavior before sustained operation.

The bounded Europe search tries at most 20 distinct candidates per run, checking a seven-minute budget between candidates. A request already in progress can exceed that budget; the workflow timeout is the final limit. No eligible candidate is a failed run, not permission to relax the threshold.

## Progress recorded 21 November 2026

- Population collection completed: 205,240 candidates within the implemented scope.
- Initial screening: 1,000 candidates checked; 222 passed both building filters.
- The user manually reviewed the following ten candidates against imagery and reported all as useful mapping opportunities. These are review observations as of this date, not a guarantee of current building counts. Live eligibility checks remain required before posting.

| OSM node ID | Settlement | Manual review |
| --- | --- | --- |
| 448211660 | Costești | Useful |
| 296190326 | Stefanovouno / Στεφανόβουνο | Useful |
| 5036933263 | Smoluća / Смолућа | Useful |
| 8641573833 | O Castelo | Useful |
| 1665929580 | Casais da Amendoeira | Useful |
| 745545716 | Finikia / Φοινικιά | Useful |
| 365039003 | Llers | Useful |
| 650442892 | Villa Pulcini | Useful |
| 1825594349 | Bubaces | Useful |
| 3122893887 | Briteiros (São Salvador) | Useful |

The sample was selected for review, not a representative random validation sample. Its ten positive reviews must not be generalized to all 222 candidates. Costești's population tag references the 1992 census.

## Post-launch backlog

- [ ] Build a SmallTownEurope status overview map **after the main bot's daily job works and hosting/account setup is complete**.
  - Show Europe with candidate towns highlighted, or shade countries by the number of towns identified as needing mapping; consider offering both views.
  - Distinguish automatically screened candidates from manually reviewed mapping opportunities.
  - Include data freshness, geographic coverage, screening rules, and OpenStreetMap attribution.
  - Country totals must describe the collected/screened dataset, not imply a complete count of all undermapped towns. Unscreened areas must not appear equivalent to areas with zero candidates.
  - Decide refresh cadence and treatment of posted or subsequently mapped towns when implementing this feature.
  - Deferred deliberately; this feature does not block the main bot launch.
