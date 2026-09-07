from playwright.sync_api import sync_playwright
try:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        b.close()
    print("LAUNCH OK")
except Exception as e:
    print("LAUNCH BLAD:", str(e).split("Call log")[0].strip()[:120])
