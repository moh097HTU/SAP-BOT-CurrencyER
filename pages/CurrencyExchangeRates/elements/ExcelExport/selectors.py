# pages/CurrencyExchangeRates/elements/ExcelExport/selectors.py

# The <span> id suffix you showed — we click the owning button of that icon
EXPORT_SPLIT_BTN_IMG_ID_SUFFIX = "--listReport-btnExcelExport-internalSplitBtn-textButton-img"

# Generic fallback for the Export button
EXPORT_BTN_GENERIC_XP = (
    "//button[.//bdi[normalize-space()='Export to Spreadsheet'] or .//bdi[normalize-space()='Export']]"
)
