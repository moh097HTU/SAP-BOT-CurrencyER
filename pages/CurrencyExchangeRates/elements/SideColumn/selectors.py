CLOSE_COLUMN_BTN_XPATH = (
    "("
    "  //button[substring(@id,string-length(@id)-string-length('--closeColumn')+1)='--closeColumn']"
    "  | //button[substring(@id,string-length(@id)-string-length('--closeColumnBtn')+1)='--closeColumnBtn']"
    "  | //span[substring(@id,string-length(@id)-string-length('--closeColumn-inner')+1)='--closeColumn-inner']/ancestor::button[1]"
    "  | //span[substring(@id,string-length(@id)-string-length('--closeColumn-img')+1)='--closeColumn-img']/ancestor::button[1]"
    "  | //button[@title='Close' or @aria-label='Close' or @aria-label='Close Column']"
    ")[1]"
)
