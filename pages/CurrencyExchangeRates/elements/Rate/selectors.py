EXCH_RATE_INPUT_XPATH = (
    "//input[substring(@id,string-length(@id)-string-length('AbsoluteExchangeRate::Field-input-inner')+1)="
    "'AbsoluteExchangeRate::Field-input-inner']"
)

EXCH_RATE_INPUT_FALLBACK_XPATH = (
    "("
    "//label[.//bdi[normalize-space()='Exchange Rate']]"
    "/following::input[contains(@id,'-inner')][1] | "
    "//span[normalize-space()='Exchange Rate']/ancestor::label[1]"
    "/following::input[contains(@id,'-inner')][1] | "
    "//*[self::label or self::span][contains(normalize-space(.), 'Exchange Rate')]"
    "/following::input[contains(@id,'-inner')][1]"
    ")"
)
