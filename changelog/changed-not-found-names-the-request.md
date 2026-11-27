- The two `NotFoundError` refusals that Quick Stats answers with HTTP 400 name the request
  by its method and path, `GET /api/api_GET/` for filters without a record and
  `GET /api/get_param_values/` for an unknown parameter, and never its host or its query.
  (https://github.com/xippios/sdk-usda-nass/issues/83)
