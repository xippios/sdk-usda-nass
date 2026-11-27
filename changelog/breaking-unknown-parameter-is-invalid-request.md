- `list_param_values` and `api.get_param_values` raise `InvalidRequestError`, 422 over HTTP,
  for a parameter that no column of the packaged table holds, where they raised
  `NotFoundError`. Quick Stats refuses such a call with HTTP 400 `no value`, and the error
  names the parameter and the request. A column of the table that Quick Stats answered so
  would keep `NotFoundError`, naming the column.
  (https://github.com/xippios/sdk-usda-nass/issues/99)
