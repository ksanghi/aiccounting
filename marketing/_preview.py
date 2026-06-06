import webbrowser, os, sys, time
base = os.path.abspath(os.path.dirname(__file__)).replace(os.sep, "/")
pages = ["index.html", "pricing.html", "checkout.html"]
for f in pages:
    url = "file:///" + base + "/" + f
    print("Opening:", url)
    webbrowser.open(url, new=2)
    time.sleep(0.4)
