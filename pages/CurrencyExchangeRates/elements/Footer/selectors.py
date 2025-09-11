# Prefer the specific Activate/Create button on the Object Page footer
ACTIVATE_CREATE_BTN_XPATH = (
    "//*[self::button or self::a]"
    "[substring(@id,string-length(@id)-string-length('--activate')+1)='--activate']"
)

# Backup: Create/Save button by text (kept for safety)
FORM_CREATE_OR_SAVE_BTN_XPATH = (
    "("
    "//bdi[normalize-space()='Create']/ancestor::button[1] | "
    "//bdi[normalize-space()='Save']/ancestor::button[1]"
    ")[1]"
)

# CSS variants (used by JS helpers)
ACTIVATE_CREATE_BTN_CSS = "button[id$='--activate'],a[id$='--activate']"

# DOM success signals (from your snippet)
HEADER_TITLE_ID_SUFFIX = "--objectPage-headerTitle"   # aria-label like "* Header area"
EDIT_BTN_ID_SUFFIX     = "--edit"
DELETE_BTN_ID_SUFFIX   = "--delete"
DISCARD_BTN_ID_SUFFIX  = "--discard"
COPY_BTN_ID_CONTAINS   = "::Copy"
