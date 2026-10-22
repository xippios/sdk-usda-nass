Refresh the packaged reference data for USDA NASS Quick Stats: $ARGUMENTS

Reference data (commodity codes, country codes, attribute lists, report calendars)
ships inside the package under `src/xippios/usda/nass/reference/` and is loaded
with `xippios.core.reference`. It comes from the upstream, never from memory.

1. Work on a branch `chore/reference-<thing>`.
2. Identify the upstream list endpoint or published file for each list named in the
   arguments, using `docs/upstream/`. Fetch it through the configured client
   (`xippios.usda.nass._client.client`) or by downloading the published file.
3. Write it as CSV (header row, upstream column names in snake_case) or JSON (a list of
   objects) under `reference/`, sorted deterministically so diffs stay readable.
4. Update the provenance table in `reference/README.md`: file, origin (endpoint or
   URL), fetch date.
5. If a `list_<thing>` task does not exist yet for this list, add one with
   `/add-endpoint` so agents can look the codes up; it should return the packaged data,
   not call upstream.
6. Run the checks and open the PR with the diff summarised: how many rows changed, any
   codes that disappeared (those may break existing fixtures or callers). Do not merge.
