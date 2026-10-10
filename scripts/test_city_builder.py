#!/usr/bin/env python3
"""No-network City Builder distribution smoke tests."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "live_world" / "static" / "city-builder.html"
INDEX = ROOT / "live_world" / "static" / "index.html"

class IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "id" in data:
            assert data["id"] not in self.ids, f"Duplicate DOM ID: {data['id']}"
            self.ids.add(data["id"])

def main():
    text = PAGE.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    parsed = IDs()
    parsed.feed(text)
    required = {"city", "worldId", "lookup", "loadStreets", "display", "country",
                "state", "lat", "lon", "timezone", "climate", "notes",
                "streets", "districts", "places", "export", "preview", "jsonPreview"}
    assert required <= parsed.ids, f"Missing controls: {required - parsed.ids}"
    assert index.count('href="/city-builder.html"') == 1
    assert "agentopia.city.manifest.v1" in text
    assert "staging_only" in text and "does_not_modify_active_world:true" in text
    assert "nominatim.openstreetmap.org/search" in text
    assert "overpass.kumi.systems/api/interpreter" in text
    assert text.count("<script>") == 1 and text.count("</script>") == 1
    js = text.split("<script>", 1)[1].split("</script>", 1)[0]
    if shutil.which("node"):
        with tempfile.TemporaryDirectory() as name:
            script = Path(name) / "city-builder.js"
            script.write_text(js, encoding="utf-8")
            subprocess.run(["node", "--check", str(script)], check=True)
        print("PASS: JavaScript syntax")
    else:
        print("SKIP: JavaScript parse test requires Node.js")
    print("PASS: City Builder page, navigation, schema, source endpoints, controls")
    return 0

if __name__ == "__main__":
    sys.exit(main())
