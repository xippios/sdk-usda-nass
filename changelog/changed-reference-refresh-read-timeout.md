- The reference refresh, `scripts/refresh_reference.py`, which a maintainer runs before a
  release, waits up to 300 seconds for each list's answer, where it gave up after the
  client's 60, and still sends each request once. Two runs had stopped at
  `agg_level_desc`, which Quick Stats did not answer within 60 seconds.
  (https://github.com/xippios/sdk-usda-nass/issues/78)
