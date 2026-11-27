- The two errors that the package maps from Quick Stats' HTTP 400 name the request by its
  method and path, `GET /api/api_GET/` for filters without a record and
  `GET /api/get_param_values/` for a parameter answered with `no value`, and never its host
  or its query. (https://github.com/xippios/sdk-usda-nass/issues/83)
