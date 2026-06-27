import os
from playwright.sync_api import sync_playwright

B = "http://127.0.0.1:8800"
OUT = os.path.dirname(os.path.abspath(__file__))

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1380, "height": 900})
    pg.goto(B + "/", wait_until="load"); pg.wait_for_timeout(300)
    pg.screenshot(path=os.path.join(OUT, "_menu.png"), full_page=True)
    print("menu title:", pg.title())

    # Click the Trial Balance TILE — proves navigation works end to end
    pg.click("a[href='/trial-balance']")
    pg.wait_for_load_state("load"); pg.wait_for_timeout(300)
    print("after clicking Trial Balance tile -> URL:", pg.url, "| title:", pg.title())
    pg.screenshot(path=os.path.join(OUT, "_nav_tb.png"), full_page=False)

    # Back to menu, click Bank Reconciliation tile
    pg.goto(B + "/"); pg.wait_for_load_state("load")
    pg.click("a[href='/bankreco']")
    pg.wait_for_load_state("load"); pg.wait_for_timeout(300)
    print("after clicking Bank Reco tile -> URL:", pg.url, "| title:", pg.title())
    pg.screenshot(path=os.path.join(OUT, "_nav_bank.png"), full_page=False)

    b.close()
print("done")
