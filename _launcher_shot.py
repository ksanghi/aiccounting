import os
from playwright.sync_api import sync_playwright

B = "http://127.0.0.1:8800"
OUT = os.path.dirname(os.path.abspath(__file__))
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1300, "height": 860})
    pg.goto(B + "/", wait_until="load", timeout=15000)
    pg.wait_for_timeout(400)
    pg.screenshot(path=os.path.join(OUT, "_launcher.png"))
    # search must filter live
    pg.fill("#q", "bank"); pg.wait_for_timeout(350)
    vis = pg.eval_on_selector_all(".ltile", "els=>els.filter(e=>e.style.display!=='none').map(e=>e.dataset.label)")
    print("typed 'bank' -> visible tiles:", vis)
    pg.screenshot(path=os.path.join(OUT, "_launcher_search.png"))
    b.close()
print("done")
