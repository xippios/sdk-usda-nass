- A packaged parameter's value is checked by core's check of a list: an integer given for
  one of the nine packaged lists, whose values are text, is refused with
  `InvalidRequestError` naming the text to pass, where it was an `UnknownCode`. A value
  that the list lacks is refused as before. (https://github.com/xippios/sdk-core/issues/313)
