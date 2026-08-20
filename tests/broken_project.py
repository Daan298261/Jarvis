"""Create a deliberately broken project for TEST 4. Do not document the bug here in comments the agent will read as the answer."""

from pathlib import Path


def create_broken_project(root: Path) -> Path:
    project = root / "broken_primes"
    project.mkdir(parents=True, exist_ok=True)
    (project / "README.txt").write_text(
        "This program should write the first 100 primes to output.txt when you run python main.py.\n",
        encoding="utf-8",
    )
    (project / "main.py").write_text(
        "from utils import first_primes\n\n"
        "if __name__ == '__main__':\n"
        "    values = first_primes(100)\n"
        "    Path = __import__('pathlib').Path\n"
        "    Path('output.txt').write_text('\\n'.join(str(v) for v in values), encoding='utf-8')\n"
        "    print(f'wrote {len(values)} primes')\n",
        encoding="utf-8",
    )
    (project / "utils.py").write_text(
        "def first_primes(n):\n"
        "    found = []\n"
        "    candidate = 2\n"
        "    while len(found) < n:\n"
        "        if is_prime(candidate):\n"
        "            found.append(candidate)\n"
        "        candidate += 1\n"
        "    return found\n",
        encoding="utf-8",
    )
    return project
