# pages/Index/elements/ProcurementOverviewTile/selectors.py

# Grid container (ensures tiles were rendered)
GRID_READY_XPATH = ("//div[starts-with(@id,'__section') and "
                    "contains(@id,'-defaultArea-listUl') and @role='list']")

# Primary: match by the hash target in the href (most stable between tenants)
BY_HREF_XPATH = ("//a[contains(@class,'sapMGT') and "
                 "contains(@href, '#Procurement-displayOverviewPage')]")

# Secondary: visible title text (from your HTML)
BY_TITLE_TEXT_XPATH = ("//a[contains(@class,'sapMGT')]"
                       "[.//span[normalize-space()='Procurement Overview']]")

# Tertiary: aria-label starts with title
BY_ARIA_LABEL_XPATH = ("//a[contains(@class,'sapMGT') and "
                       "starts-with(normalize-space(@aria-label),'Procurement Overview')]")
