"""Double-click entry point for the packaged Windows app.

Starts the web page and opens it in the default browser. No commands needed.
"""

import sys
import threading
import webbrowser

from main import main

URL = "http://127.0.0.1:8000"

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("--web")
    if "--web" in sys.argv:
        threading.Timer(2.0, lambda: webbrowser.open(URL)).start()
    main()
