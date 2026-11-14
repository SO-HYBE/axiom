"""Capture the documentation screenshots from a running AXIOM instance.

Requires Google Chrome or Microsoft Edge and `websocket-client`. The script
launches a headless browser with the DevTools protocol, drives the Mission
Scenario workflow with DOM clicks, and writes PNG files.

Usage:
    python scripts/capture_screenshots.py http://127.0.0.1:8767
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websocket import create_connection

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "screenshots"
CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)
WIDTH, HEIGHT = 1440, 1000


class DevTools:
    def __init__(self, ws_url):
        self.ws = create_connection(ws_url, timeout=30)
        self.next_id = 0

    def call(self, method, **params):
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params}
        self.ws.send(json.dumps(message))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise RuntimeError(reply["error"])
                return reply.get("result", {})

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", expression=expression,
                           awaitPromise=True, returnByValue=True)
        return result.get("result", {}).get("value")

    def wait_for(self, expression, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.evaluate(expression):
                    return
            except Exception:
                pass
            time.sleep(0.25)
        raise TimeoutError(expression)

    def shot(self, name):
        data = self.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)
        path = OUT / name
        path.write_bytes(base64.b64decode(data["data"]))
        print("wrote", path)

    def scroll_to_text(self, text):
        self.evaluate(
            "(() => { const nodes=[...document.querySelectorAll('h1,h2,h3')];"
            "const node=nodes.find(n=>n.textContent.trim().startsWith(%s));"
            "if(node) node.scrollIntoView({block:'start'}); return !!node; })()"
            % json.dumps(text))
        time.sleep(0.6)

    def overflow(self):
        """Return (scrollWidth, innerWidth) for the document root."""
        return self.evaluate(
            "(() => [document.documentElement.scrollWidth, window.innerWidth])()")


def browser_command():
    for candidate in CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise SystemExit("No Chrome or Edge executable found")


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8767"
    OUT.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="axiom-shot-")
    process = subprocess.Popen([
        browser_command(), "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", "--remote-debugging-port=9333",
        "--user-data-dir=" + profile, "--window-size=%d,%d" % (WIDTH, HEIGHT),
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(80):
            try:
                with urllib.request.urlopen("http://127.0.0.1:9333/json", timeout=2) as response:
                    targets = json.load(response)
                page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise SystemExit("Browser did not expose a debugging target")

        client = DevTools(page["webSocketDebuggerUrl"])
        client.call("Page.enable")
        client.call("Runtime.enable")
        client.call("Emulation.setDeviceMetricsOverride", width=WIDTH, height=HEIGHT,
                    deviceScaleFactor=1, mobile=False)
        client.call("Page.navigate", url=url)
        client.wait_for("document.readyState === 'complete' && !!document.getElementById('nav-scenario')")
        time.sleep(1.0)

        client.evaluate("document.getElementById('nav-scenario').click()")
        client.wait_for("document.querySelectorAll('#scenario-presets button').length > 0")
        client.evaluate(
            "(() => { const b=[...document.querySelectorAll('#scenario-presets button')]"
            ".find(x=>x.textContent.includes('Crew cabin')); if(b) b.click(); return !!b; })()")
        time.sleep(0.5)
        client.evaluate("document.getElementById('sc-assess').click()")
        client.wait_for("document.getElementById('sc-report').textContent.length > 500")
        time.sleep(1.5)

        client.evaluate("window.scrollTo(0,0)")
        time.sleep(0.4)
        client.shot("mission-scenario.png")

        client.scroll_to_text("Parameter comparison matrix")
        client.shot("evidence-matrix.png")

        client.scroll_to_text("Next experiment proposals")
        client.shot("planner.png")

        client.evaluate("document.getElementById('nav-research').click()")
        client.wait_for("!!document.getElementById('question') && !!document.getElementById('submit')")
        client.evaluate("document.getElementById('provider').value='extractive'; document.getElementById('provider').dispatchEvent(new Event('change',{bubbles:true}))")
        client.evaluate("document.getElementById('answer-example').click()")
        client.evaluate("document.getElementById('submit').click()")
        client.wait_for("document.querySelector('#research-view').textContent.includes('custom-made for a previous project')")
        time.sleep(0.5)
        client.shot("research.png")

        client.evaluate("document.getElementById('nav-evaluation').click()")
        client.wait_for("!!document.getElementById('axiom-title')")
        client.wait_for("document.getElementById('axiom-record-select').options.length > 1", timeout=15)
        client.scroll_to_text("Assurance Inspector and Trace Lab")
        client.shot("assurance-inspector.png")

        client.evaluate("document.getElementById('nav-scenario').click()")
        time.sleep(0.6)

        client.call("Emulation.setDeviceMetricsOverride", width=390, height=844,
                    deviceScaleFactor=2, mobile=True)
        client.evaluate("window.scrollTo(0,0)")
        time.sleep(0.8)
        print("mobile overflow", client.overflow())
        client.shot("mission-scenario-mobile.png")

        client.call("Emulation.setDeviceMetricsOverride", width=900, height=1100,
                    deviceScaleFactor=1, mobile=False)
        time.sleep(0.8)
        print("tablet overflow", client.overflow())
        client.shot("mission-scenario-tablet.png")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
