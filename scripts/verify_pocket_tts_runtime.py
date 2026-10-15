"""Load every hash-pinned Pocket TTS graph with the APK's ONNX Runtime version.

Run in an isolated environment with onnxruntime matching ORT_VERSION in CMake.
Weights are cached outside source and never included in the APK.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def verify(cache: Path) -> None:
    import onnxruntime as ort

    cmake = (ROOT / "android/app/src/main/cpp/voice_native/CMakeLists.txt").read_text()
    version = re.search(r'set\(ORT_VERSION "([^"]+)"\)', cmake).group(1)
    if ort.__version__ != version:
        raise RuntimeError(f"Install onnxruntime=={version}; found {ort.__version__}")
    catalog = (ROOT / "android/app/src/main/java/com/jarvis/companion/CompanionVoicePackCatalog.kt").read_text(encoding="utf-8")
    base = re.search(r'private const val POCKET_BASE =\s*"([^"]+)"', catalog).group(1)
    graphs = re.findall(r'CompanionVoiceArtifact\("([^"]+[.]onnx)", "\$POCKET_BASE/[^"]+",\s*"([a-f0-9]{64})", ([0-9_]+)L\)', catalog)
    if len(graphs) != 5:
        raise RuntimeError("Expected all five Pocket TTS graphs")
    cache.mkdir(parents=True, exist_ok=True)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    for name, digest, size in graphs:
        path = cache / name
        def valid() -> bool:
            return path.is_file() and path.stat().st_size == int(size.replace("_", "")) and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        if not valid():
            with urlopen(f"{base}/{name}", timeout=120) as response:
                path.write_bytes(response.read())
        if not valid():
            raise RuntimeError(f"Pocket TTS artifact verification failed: {name}")
        session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        print(f"ONNX Runtime {version}: {name}: loaded ({len(session.get_inputs())} inputs, {len(session.get_outputs())} outputs)", flush=True)
        del session


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "android/app/build/pocket-validation")
    verify(parser.parse_args().cache_dir)
