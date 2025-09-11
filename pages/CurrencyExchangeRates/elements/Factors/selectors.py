FROM_FACTOR_BY_LABEL_XPATH = (
    "("
    "//label[.//bdi[normalize-space()='From Currency Unit']]/following::input[contains(@id,'-inner')][1] | "
    "//label[.//bdi[contains(normalize-space(.),'From') and contains(normalize-space(.),'Unit')]]"
    "/following::input[contains(@id,'-inner')][1] | "
    "//label[.//bdi[contains(normalize-space(.),'From') and contains(normalize-space(.),'Factor')]]"
    "/following::input[contains(@id,'-inner')][1]"
    ")"
)
TO_FACTOR_BY_LABEL_XPATH = (
    "("
    "//label[.//bdi[normalize-space()='To Currency Unit']]/following::input[contains(@id,'-inner')][1] | "
    "//label[.//bdi[contains(normalize-space(.),'To') and contains(normalize-space(.),'Unit')]]"
    "/following::input[contains(@id,'-inner')][1] | "
    "//label[.//bdi[contains(normalize-space(.),'To') and contains(normalize-space(.),'Factor')]]"
    "/following::input[contains(@id,'-inner')][1]"
    ")"
)
