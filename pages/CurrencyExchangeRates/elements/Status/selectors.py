# elements/Status/selectors.py

# Action buttons that flip after activation
HEADER_EDIT_BTN_XPATH = (
    "//bdi[normalize-space()='Edit']/ancestor::button[1] | "
    "//button[substring(@id,string-length(@id)-string-length('--edit')+1)='--edit']"
)
HEADER_DELETE_BTN_XPATH = (
    "//bdi[normalize-space()='Delete']/ancestor::button[1] | "
    "//button[substring(@id,string-length(@id)-string-length('--delete')+1)='--delete']"
)
HEADER_COPY_BTN_XPATH = (
    "//bdi[normalize-space()='Copy']/ancestor::button[1] | "
    "//button[substring(@id,string-length(@id)-string-length('--copy')+1)='--copy']"
)
FOOTER_DISCARD_DRAFT_BTN_XPATH = (
    "//bdi[normalize-space()='Discard Draft']/ancestor::button[1] | "
    "//button[substring(@id,string-length(@id)-string-length('--discard')+1)='--discard']"
)

# Sections that typically appear post-activation
CHANGE_LOG_SECTION_ANCHOR_XPATH = (
    "//a[contains(@id,'ExchangeRateLog') and contains(@id,'Section-anchor')] | "
    "//a[contains(normalize-space(.), 'Change Log') and contains(@id,'Section-anchor')]"
)
TREND_SECTION_ANCHOR_XPATH = (
    "//a[contains(@id,'CurrencyExchangeRateTrend') and contains(@id,'Section-anchor')] | "
    "//a[contains(normalize-space(.), 'Trend') and contains(@id,'Section-anchor')]"
)

# Object header root for reading aria-label
OBJECT_HEADER_CONTENT_XPATH = (
    "//*[substring(@id,string-length(@id)-string-length('--objectPage-OPHeaderContent')+1)="
    "'--objectPage-OPHeaderContent']"
)
