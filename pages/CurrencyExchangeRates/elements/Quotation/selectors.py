QUOTATION_INNER_INPUT_XPATH = (
    "//input[substring(@id,string-length(@id)-string-length('ExchangeRateQuotation::Field-comboBoxEdit-inner')+1)="
    "'ExchangeRateQuotation::Field-comboBoxEdit-inner']"
)
QUOTATION_ARROW_BTN_XPATH = (
    "//span[substring(@id,string-length(@id)-string-length('ExchangeRateQuotation::Field-comboBoxEdit-arrow')+1)="
    "'ExchangeRateQuotation::Field-comboBoxEdit-arrow']/ancestor::button[1] | "
    "//span[substring(@id,string-length(@id)-string-length('ExchangeRateQuotation::Field-comboBoxEdit-arrow')+1)="
    "'ExchangeRateQuotation::Field-comboBoxEdit-arrow']"
)
QUOTATION_OPTION_BY_TEXT_XPATH = (
    "//div[contains(@id,'ExchangeRateQuotation::Field-comboBoxEdit-popup')]"
    "//bdi[normalize-space()='{TEXT}']/ancestor::li[1] | "
    "//div[contains(@id,'ExchangeRateQuotation::Field-comboBoxEdit-popup')]"
    "//span[normalize-space()='{TEXT}']/ancestor::li[1]"
)
