# pages/CurrencyExchangeRates/selectors.py

# App root hash (used to deep-link back to the list)
APP_HASH = "#Currency-maintainExchangeRates"

# LIST PAGE: Create button in the list report toolbar (robust locator by BDI text)
CREATE_BUTTON_XPATH = "//bdi[normalize-space()='Create']/ancestor::button[1]"

# Object Page fields – match by stable tail fragments in IDs.
EXCH_TYPE_INPUT_XPATH = (
    "//input[substring(@id,string-length(@id)-string-length('ExchangeRateTypeForEdit::Field-input-inner')+1)="
    "'ExchangeRateTypeForEdit::Field-input-inner']"
)

FROM_CCY_INPUT_XPATH = (
    "//input[substring(@id,string-length(@id)-string-length('SourceCurrencyForEdit::Field-input-inner')+1)="
    "'SourceCurrencyForEdit::Field-input-inner']"
)

TO_CCY_INPUT_XPATH = (
    "//input[substring(@id,string-length(@id)-string-length('TargetCurrencyForEdit::Field-input-inner')+1)="
    "'TargetCurrencyForEdit::Field-input-inner']"
)

VALID_FROM_INPUT_XPATH = (
    "//input[substring(@id,string-length(@id)-string-length('ExchangeRateEffectiveDateFoEd::Field-datePicker-inner')+1)="
    "'ExchangeRateEffectiveDateFoEd::Field-datePicker-inner']"
)

# Quotation combobox (inner input)
QUOTATION_INNER_INPUT_XPATH = (
    "//input[substring(@id,string-length(@id)-string-length('ExchangeRateQuotation::Field-comboBoxEdit-inner')+1)="
    "'ExchangeRateQuotation::Field-comboBoxEdit-inner']"
)

# Quotation dropdown arrow (to open popup)
QUOTATION_ARROW_BTN_XPATH = (
    "//span[substring(@id,string-length(@id)-string-length('ExchangeRateQuotation::Field-comboBoxEdit-arrow')+1)="
    "'ExchangeRateQuotation::Field-comboBoxEdit-arrow']/ancestor::button[1] | "
    "//span[substring(@id,string-length(@id)-string-length('ExchangeRateQuotation::Field-comboBoxEdit-arrow')+1)="
    "'ExchangeRateQuotation::Field-comboBoxEdit-arrow']"
)

# Quotation option in the popup by visible text (Direct/Indirect)
# Use `{TEXT}` placeholder with .format(TEXT=...)
QUOTATION_OPTION_BY_TEXT_XPATH = (
    "//div[contains(@id,'ExchangeRateQuotation::Field-comboBoxEdit-popup')]"
    "//bdi[normalize-space()='{TEXT}']/ancestor::li[1] | "
    "//div[contains(@id,'ExchangeRateQuotation::Field-comboBoxEdit-popup')]"
    "//span[normalize-space()='{TEXT}']/ancestor::li[1]"
)

# Exchange Rate input (primary by ID tail)
EXCH_RATE_INPUT_XPATH = (
    "//input[substring(@id,string-length(@id)-string-length('AbsoluteExchangeRate::Field-input-inner')+1)="
    "'AbsoluteExchangeRate::Field-input-inner']"
)

# --- NEW: robust fallbacks (by label proximity / aria) ---

# Exchange Rate input fallback: find a label-like text then the nearest input
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

# Factors sometimes default to 0 → computed rate = 0 → validation yells.
# Try common label variants and grab the next input.
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

# OBJECT PAGE footer "Create" (…--activate) button
ACTIVATE_CREATE_BTN_XPATH = (
    "//button[substring(@id,string-length(@id)-string-length('--activate')+1)='--activate' "
    " and .//bdi[normalize-space()='Create']]"
)

# Fallback form action buttons
FORM_CREATE_OR_SAVE_BTN_XPATH = (
    "("
    "//bdi[normalize-space()='Create']/ancestor::button[1] | "
    "//bdi[normalize-space()='Save']/ancestor::button[1]"
    ")[1]"
)

# Message toast (transient) and validation/error detection
MESSAGE_TOAST_CSS = ".sapMMessageToast"
ANY_INVALID_INPUT_XPATH = "//*[(@aria-invalid='true') and (self::input or self::textarea)]"
ANY_ERROR_WRAPPER_XPATH = "//*[contains(@class,'sapMInputBaseContentWrapperError')]"

# Generic dialog detection (we will NOT close it automatically)
DIALOG_ROOT_CSS = "div[role='dialog']"
DIALOG_OK_BTN_XPATH = (
    "("
    "//div[@role='dialog']//bdi[normalize-space()='OK']/ancestor::button[1] | "
    "//div[@role='dialog']//bdi[normalize-space()='Create']/ancestor::button[1] | "
    "//div[@role='dialog']//bdi[normalize-space()='Save']/ancestor::button[1]"
    ")[1]"
)

# --- Object Page header presence (side panel) ---
OBJECT_HEADER_CONTENT_XPATH = (
    "//*[substring(@id,string-length(@id)-string-length('--objectPage-OPHeaderContent')+1)="
    "'--objectPage-OPHeaderContent']"
)

# A stable value node in the header (Exchange Rate value text)
OBJECT_HEADER_RATE_VALUE_XPATH = (
    "//*[substring(@id,string-length(@id)-string-length('--exchangeRate-text')+1)="
    "'--exchangeRate-text']"
)

# The 'Close Column' button in the side panel (FlexibleColumnLayout)
CLOSE_COLUMN_BTN_XPATH = (
    "("
    "  //button[substring(@id,string-length(@id)-string-length('--closeColumn')+1)='--closeColumn']"
    "  | //button[substring(@id,string-length(@id)-string-length('--closeColumnBtn')+1)='--closeColumnBtn']"
    "  | //span[substring(@id,string-length(@id)-string-length('--closeColumn-inner')+1)='--closeColumn-inner']/ancestor::button[1]"
    "  | //span[substring(@id,string-length(@id)-string-length('--closeColumn-img')+1)='--closeColumn-img']/ancestor::button[1]"
    "  | //button[@title='Close' or @aria-label='Close' or @aria-label='Close Column']"
    ")[1]"
)
