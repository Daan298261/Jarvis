"""Refresh the packaged EasyList ad-server domain rules from a pinned upstream commit."""
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / "extensions" / "chrome" / "filters"


def compile_domains(text):
    groups = {"any": set(), "thirdParty": set()}
    skipped = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        match = re.fullmatch(r"\|\|([a-zA-Z0-9.-]+)\^(\$third-party)?", line)
        if not match:
            skipped += 1
            continue
        domain = match[1].lower()
        if "." not in domain or domain.startswith(".") or ".." in domain:
            skipped += 1
            continue
        groups["thirdParty" if match[2] else "any"].add(domain)
    groups["thirdParty"] -= groups["any"]
    return {key: sorted(domains) for key, domains in groups.items()}, skipped


def main():
    commit = json.load(urllib.request.urlopen("https://api.github.com/repos/easylist/easylist/commits/master", timeout=20))["sha"]
    url = f"https://raw.githubusercontent.com/easylist/easylist/{commit}/easylist/easylist_adservers.txt"
    source = urllib.request.urlopen(url, timeout=20).read()
    groups, skipped = compile_domains(source.decode("utf-8"))
    ROOT.mkdir(parents=True, exist_ok=True)
    payload = {"source": url, "sha256": hashlib.sha256(source).hexdigest(), "attribution": "The EasyList authors (https://easylist.to/)", "license": "CC-BY-SA-3.0", "license_url": "https://creativecommons.org/licenses/by-sa/3.0/", "changes": "Extracted domain-only ad-server rules; preserved third-party scope. Unsupported ABP expressions omitted.", "skipped_expressions": skipped, "domains": groups}
    (ROOT / "easylist-domains.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"Compiled {sum(map(len, groups.values()))} EasyList domains; skipped {skipped} unsupported expressions")


if __name__ == "__main__":
    main()
