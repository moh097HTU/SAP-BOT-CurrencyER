# XPaths & ID suffixes used by DraftFinder

# Table rows in the List Report
ROWS_XPATH = ("//main//table//tbody"
              "/tr[contains(@id,'ListReportTable:::ColumnListItem')]")

# A row is Draft if col 8 contains the Draft marker link
DRAFT_MARKER_REL_XP = (
    "./td[8]//a[contains(@id,'DraftObjectMarker')"
    " and .//span[contains(normalize-space(),'Draft')]]"
)

# Row checkbox (multi-select) — works from the row root
ROW_CHECKBOX_REL_XP = (
    ".//div[contains(@id,'-selectMulti') and contains(@class,'sapMCb')]"
)

# List-level “Delete” button (toolbar)
LIST_DELETE_BTN_SUFFIX = "--deleteEntry"

# Delete confirmation dialog + its Delete button
CONFIRM_DIALOG_ROLE = "alertdialog"
CONFIRM_DELETE_BTN_XP = (
    "//button[.//bdi[normalize-space()='Delete']]"
    " | //bdi[normalize-space()='Delete']/ancestor::button[1]"
)
