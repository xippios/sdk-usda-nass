# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: breaking changes bump the minor).

## [Unreleased]

### Added

- `get_counts` task and `api.get_counts` wrapper for `GET /api/get_counts`: the number of
  records a set of Quick Stats filters would return. Fixtures recorded 2026-10-22.
- Scaffold from [sdk-template](https://github.com/xippios/sdk-template): configured
  client for USDA NASS Quick Stats, empty task layer, MCP server and FastAPI router
  wired to it, test harness, CI and publishing.
