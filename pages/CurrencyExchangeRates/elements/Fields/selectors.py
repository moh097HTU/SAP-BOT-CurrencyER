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
