"""Install or repair the dedicated local REA engine."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.reverse_engineering.provision import install, readiness

if __name__ == "__main__":
    print(json.dumps(readiness() if "--status" in sys.argv else install(), indent=2))
