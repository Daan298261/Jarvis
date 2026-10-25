"""Bounded known-plaintext AT2 recovery over admitted, read-only FFS streams.

Names and metadata nominate pairs; only whole-body agreement supplies evidence.
Unknown table entries remain null. No guessed byte is used to decode evidence.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import os
from pathlib import PurePosixPath
import stat
import uuid
import zipfile
import zlib

MAX_PAIR_BYTES = 8 * 1024 * 1024
MAX_REFERENCE_BYTES = 64 * 1024 * 1024
MODELS = ("substitution", "cipher-xor-offset", "plain-xor-offset", "cipher-minus-offset")


def _symbol(byte: int, offset: int, model: str) -> int:
    if model == "cipher-xor-offset":
        return byte ^ (offset & 255)
    if model == "cipher-minus-offset":
        return (byte - offset) & 255
    return byte


def derive_mapping(cipher: bytes, plain: bytes, model: str = "substitution") -> list | None:
    """Return the observed function, or None when one input has two outputs."""
    if model not in MODELS:
        raise ValueError(model)
    if not cipher or len(cipher) != len(plain):
        return None
    table = [None] * 256
    for i, (c, p) in enumerate(zip(cipher, plain)):
        c = _symbol(c, i, model)
        if model == "plain-xor-offset":
            p ^= i & 255
        if table[c] not in (None, p):
            return None
        table[c] = p
    return table


def mapping_status(table: list) -> dict:
    values = [v for v in table if v is not None]
    return {"observed_inputs": len(values), "distinct_outputs": len(set(values)),
            "bijection": len(values) == len(set(values)) == 256}


def bit_permutation_xor(table: list) -> dict | None:
    """Recognise, rather than assume, a full bit permutation followed by XOR."""
    if not mapping_status(table)["bijection"]:
        return None
    mask = table[0]
    basis = [table[1 << bit] ^ mask for bit in range(8)]
    if set(basis) != {1 << bit for bit in range(8)}:
        return None
    for c, p in enumerate(table):
        value = mask
        for bit, output in enumerate(basis):
            if c & (1 << bit):
                value ^= output
        if value != p:
            return None
    return {"xor": mask, "input_to_output_bits": [b.bit_length() - 1 for b in basis]}


def candidate_pair(keyed: dict, reference: dict) -> bool:
    """Equal body lengths plus AT2 schema/count, or equal basename for XOR TSV."""
    k, r = keyed["container"], reference["container"]
    if k.get("body_transform") != "keyed" or k.get("anomalies"):
        return False
    if r.get("body_transform") == "plain" and not r.get("anomalies"):
        return (keyed["bytes"] - 64 == reference["bytes"] - 16 > 0
                and all(k.get(f) == r.get(f) for f in ("table_type", "record_count", "format_rev")))
    return (reference.get("xor_key") is not None
            and keyed["bytes"] - 64 == reference["bytes"] > 0
            and PurePosixPath(keyed["path"]).name.lower() == PurePosixPath(reference["path"]).name.lower())


class TableRecovery:
    """One analysis session. Entry factories must use the FFS safe-member iterator.

    The caller owns admission, cancellation and derivative output. Bodies are bounded;
    only matched pairs are retained, never the dump or all keyed bodies.
    """
    def __init__(self, profiles: list[dict]):
        self.profiles = {p["path"]: p for p in profiles}

    def run(self, entries, output_dir, check=lambda: None) -> dict:
        references = {}
        retained = 0
        gaps = Counter()
        keyed = [p for p in self.profiles.values() if p.get("container", {}).get("body_transform") == "keyed"]
        keyed_by_size = defaultdict(list)
        for p in keyed:
            keyed_by_size[p["bytes"] - 64].append(p)
        eligible = set()
        corpus = Counter()
        for p in self.profiles.values():
            if p.get("container", {}).get("body_transform") == "plain":
                corpus["plain_at2_files"] += 1
            elif p.get("xor_key") is not None:
                corpus["xor_candidate_files"] += 1
            else:
                continue
            offset = 16 if p.get("container", {}).get("body_transform") == "plain" else 0
            if any(candidate_pair(k, p) for k in keyed_by_size.get(p["bytes"] - offset, [])):
                eligible.add(p["path"])
        for path, size, _, opener in entries():
            check()
            p = self.profiles.get(path)
            if not p or path not in eligible:
                continue
            h = p.get("container", {})
            if h.get("body_transform") != "plain" and p.get("xor_key") is None:
                continue
            if size > MAX_PAIR_BYTES or retained + size > MAX_REFERENCE_BYTES:
                gaps["reference_budget"] += 1
                continue
            raw = self._read(opener, p)
            if raw is None:
                gaps["reference_changed_or_unreadable"] += 1
                continue
            body = raw[16:] if h.get("body_transform") == "plain" else raw.translate(bytes(b ^ p["xor_key"] for b in range(256)))
            if h.get("body_transform") != "plain" and (b"\t" not in body or b"\n" not in body):
                gaps["xor_not_tsv"] += 1
                continue
            references[path] = body
            retained += len(body)
        by_size = defaultdict(list)
        for path, body in references.items():
            by_size[len(body)].append(self.profiles[path])
        pairs = []
        maps = {}
        conflicts = set()
        attempts = 0
        rejected = []
        seen = set()
        for path, size, _, opener in entries():
            check()
            if path in seen:
                continue
            seen.add(path)
            p = self.profiles.get(path)
            if not p or p.get("container", {}).get("body_transform") != "keyed":
                continue
            candidates = [r for r in by_size.get(size - 64, []) if candidate_pair(p, r)]
            if not candidates:
                continue
            if size > MAX_PAIR_BYTES:
                gaps["pair_budget"] += 1
                continue
            raw = self._read(opener, p)
            if raw is None:
                gaps["keyed_changed_or_unreadable"] += 1
                continue
            for r in candidates:
                attempts += 1
                accepted = False
                for model in MODELS:
                    table = derive_mapping(raw[64:], references[r["path"]], model)
                    if table is None or min(mapping_status(table)[f] for f in ("observed_inputs", "distinct_outputs")) < 16 or len(raw) - 64 < 64:
                        continue
                    key = p["container"]["key_id"]
                    pair = {"key_id": key, "keyed_path": path, "reference_path": r["path"],
                            "keyed_sha256": p.get("sha256"), "reference_sha256": r.get("sha256"),
                            "body_bytes": size - 64, "model": model, **mapping_status(table)}
                    pairs.append(pair)
                    accepted = True
                    previous = maps.get(key)
                    if previous:
                        old_model, old = previous
                        if old_model != model or any(a is not None and b is not None and a != b for a, b in zip(old, table)):
                            conflicts.add(key)
                        else:
                            table = [a if a is not None else b for a, b in zip(old, table)]
                    maps[key] = (model, table)
                    break
                if not accepted:
                    rejected.append({"key_id": p["container"]["key_id"], "keyed_path": path,
                                     "reference_path": r["path"], "keyed_sha256": p.get("sha256"),
                                     "reference_sha256": r.get("sha256"), "models_rejected": list(MODELS)})
        groups = []
        for key, count in sorted(Counter(p["container"].get("key_id") for p in keyed).items(), key=lambda x: str(x[0])):
            model, table = maps.get(key, (None, [None] * 256))
            status = mapping_status(table)
            groups.append({"key_id": key, "files": count, "model": model, "cipher_to_plain": table,
                           **status, "conflicting_pairs": key in conflicts,
                           "solved": status["bijection"] and key not in conflicts,
                           "decoded_files": 0, "independently_matched_files": len({p["keyed_path"] for p in pairs if p["key_id"] == key})})
            groups[-1]["files_without_plaintext_verification"] = count - groups[-1]["independently_matched_files"]
            groups[-1]["bit_permutation_xor"] = bit_permutation_xor(table) if model == "substitution" else None
        solved = {g["key_id"]: g for g in groups if g["solved"]}
        decoded = []
        if solved:
            output_dir.mkdir(parents=True, exist_ok=True)
            st = output_dir.lstat()
            if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
                raise PermissionError("Linked/reparse derivative directory is not admitted")
            seen.clear()
            for path, _, _, opener in entries():
                check()
                if path in seen:
                    continue
                seen.add(path)
                p = self.profiles.get(path)
                g = solved.get((p or {}).get("container", {}).get("key_id"))
                if not g or p["container"].get("anomalies"):
                    continue
                # Hash-named derivatives cannot escape the investigation directory.
                name = hashlib.sha256(path.encode()).hexdigest() + ".body"
                target = output_dir / name
                result = self._decode(opener, p, g, target, check)
                if result is None:
                    gaps["decode_source_changed"] += 1
                    continue
                g["decoded_files"] += 1
                decoded.append({"path": path, "source_sha256": p["sha256"], "key_id": g["key_id"],
                                **result, "derivative": name})
        return {"version": 1, "corpus": dict(corpus), "candidate_pairs_tested": attempts, "reference_files": len(references),
                "pairs": pairs, "rejected_pairs": rejected, "key_ids": groups, "decoded": decoded, "gaps": dict(gaps),
                "limitations": ["Metadata nominates pairs; whole-body consistency is required, not semantic identity.",
                                "Decoding unpaired files applies a hypothesis, not independent plaintext verification.",
                                "Models tested: substitution, cipher XOR offset, plain XOR offset, cipher minus offset. Bit permutations plus XOR are included in substitution.",
                                "Partial maps are never completed by guessing; reference/pair memory budgets are explicit."]}

    @staticmethod
    def _decode(opener, profile, group, target, check):
        # Do not append the UUID to the 64-character digest: investigation roots
        # can already approach Win32's path-length limit.
        tmp = target.with_name(uuid.uuid4().hex + ".tmp")
        sha, original = hashlib.sha256(), hashlib.sha256()
        offset = 0
        try:
            with opener() as src, tmp.open("xb") as dst:
                header = src.read(64)
                original.update(header)
                while chunk := src.read(1024 * 1024):
                    check()
                    original.update(chunk)
                    if group["model"] == "substitution":
                        data = chunk.translate(bytes(group["cipher_to_plain"]))
                    else:
                        data = bytes(group["cipher_to_plain"][_symbol(b, offset+i, group["model"])] ^ (((offset+i) & 255) if group["model"] == "plain-xor-offset" else 0) for i, b in enumerate(chunk))
                    offset += len(chunk)
                    sha.update(data)
                    dst.write(data)
            if original.hexdigest() != profile.get("sha256"):
                return None
            check()
            os.replace(tmp, target)
            return {"body_bytes": offset, "sha256": sha.hexdigest()}
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _read(opener, profile):
        try:
            with opener() as stream:
                raw = stream.read(MAX_PAIR_BYTES + 1)
            if len(raw) != profile["bytes"] or hashlib.sha256(raw).hexdigest() != profile.get("sha256"):
                return None
            return raw
        except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, zlib.error):
            return None
