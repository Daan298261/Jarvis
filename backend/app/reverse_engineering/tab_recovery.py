"""Bounded known-plaintext AT2 recovery over admitted, read-only FFS streams.

Names and metadata nominate pairs; only whole-body agreement supplies evidence.
Unknown table entries remain null. No guessed byte is used to decode evidence.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import errno
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import uuid
import zipfile
import zlib

MAX_PAIR_BYTES = 8 * 1024 * 1024
MAX_REFERENCE_BYTES = 64 * 1024 * 1024
MIN_BODY_BYTES = 64  # §8: a candidate needs at least 64 body bytes ...
MIN_SYMBOLS = 16  # ... 16 observed inputs and 16 distinct outputs
CHUNK_SIZE = 1024 * 1024
MODELS = ("substitution", "cipher-xor-offset", "plain-xor-offset", "cipher-minus-offset")
# Errors a source member can raise while it is opened or streamed (mirrors ffs_ingest.MEMBER_ERRORS).
READ_ERRORS = (OSError, EOFError, RuntimeError, zipfile.BadZipFile, tarfile.TarError, zlib.error)
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
# Names this module writes into the derivative directory; nothing else there is touched.
_DERIVATIVE_NAME = re.compile(r"[0-9a-f]{64}\.body|[0-9a-f]{32}\.tmp")


class MemberReadError(Exception):
    """A source member could not be opened or streamed; ``original`` is the underlying error."""

    def __init__(self, original: BaseException):
        super().__init__(f"{type(original).__name__}: {original}")
        self.original = original


def _open(opener):
    try:
        return opener()
    except READ_ERRORS as exc:
        raise MemberReadError(exc) from exc


def _chunk(stream, size: int) -> bytes:
    try:
        return stream.read(size)
    except READ_ERRORS as exc:
        raise MemberReadError(exc) from exc


def key_id(profile: dict | None) -> int | None:
    """Key id of a keyed AT2 member, or None for plain/non-AT2 members and for keyed
    members indexed before the container parser (16-byte header only, key id unknown)."""
    container = (profile or {}).get("container") or {}
    return container.get("key_id") if container.get("body_transform") == "keyed" else None


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
    if key_id(keyed) is None or k.get("anomalies"):
        return False
    if r.get("body_transform") == "plain" and not r.get("anomalies"):
        return (keyed["bytes"] - 64 == reference["bytes"] - 16 > 0
                and all(k.get(f) == r.get(f) for f in ("table_type", "record_count", "format_rev")))
    return (reference.get("xor_key") is not None
            and keyed["bytes"] - 64 == reference["bytes"] > 0
            and PurePosixPath(keyed["path"]).name.lower() == PurePosixPath(reference["path"]).name.lower())


class TableRecovery:
    """One analysis session. Entry factories must use the FFS safe-member iterator.

    The caller owns admission and cancellation; this class owns the derivative
    directory it is given. Bodies are bounded; only matched pairs are retained,
    never the dump or all keyed bodies.

    Every re-read is checked against the index (size and SHA-256). A member whose
    bytes no longer match is reported as *changed*, one that cannot be read while the
    source is still present as *unreadable*, both under ``integrity`` with their paths.
    When the source itself is gone (``source_available()`` is false) the read error is
    re-raised so the caller can interrupt the run and resume it later.
    """

    def __init__(self, profiles: list[dict]):
        self.profiles = {p["path"]: p for p in profiles}

    def run(self, entries, output_dir: Path, check=lambda: None, source_available=lambda: True) -> dict:
        self._check, self._source_available = check, source_available
        self._gaps: Counter = Counter()
        self._integrity: dict[str, list] = {"changed": [], "unreadable": []}
        gaps = self._gaps
        references: dict[str, bytes] = {}
        reference_body_sha: dict[str, str] = {}
        retained = 0
        keyed = [p for p in self.profiles.values() if key_id(p) is not None]
        legacy_keyed = sum(1 for p in self.profiles.values()
                           if (p.get("container") or {}).get("body_transform") == "keyed" and key_id(p) is None)
        if legacy_keyed:
            # Indexed before the container parser: no key id, so they are neither paired nor decoded.
            gaps["keyed_without_key_id"] = legacy_keyed
        keyed_by_size = defaultdict(list)
        for p in keyed:
            keyed_by_size[p["bytes"] - 64].append(p)
        eligible = set()
        corpus = Counter()
        for p in self.profiles.values():
            container = p.get("container") or {}
            if container.get("body_transform") == "plain":
                corpus["plain_at2_files"] += 1
            elif p.get("xor_key") is not None:
                corpus["xor_candidate_files"] += 1
            else:
                continue
            offset = 16 if container.get("body_transform") == "plain" else 0
            if any(candidate_pair(k, p) for k in keyed_by_size.get(p["bytes"] - offset, [])):
                eligible.add(p["path"])
        if legacy_keyed:
            corpus["keyed_without_key_id"] = legacy_keyed

        # Pass 1: read and verify every nominated reference.
        for path, size, _, opener in entries():
            check()
            if path not in eligible:
                continue
            eligible.discard(path)  # an archive may repeat a member name; the index keeps the first
            p = self.profiles[path]
            plain = p["container"].get("body_transform") == "plain"
            if size > MAX_PAIR_BYTES or retained + size > MAX_REFERENCE_BYTES:
                gaps["reference_budget"] += 1
                continue
            raw = self._fetch(opener, p, "reference")
            if raw is None:
                continue
            body = raw[16:] if plain else raw.translate(bytes(b ^ p["xor_key"] for b in range(256)))
            if not plain and (b"\t" not in body or b"\n" not in body):
                gaps["xor_not_tsv"] += 1
                continue
            references[path] = body
            reference_body_sha[path] = hashlib.sha256(body).hexdigest()
            retained += len(body)
        self._require_source()

        # Pass 2: test every nominated keyed/reference pair under each model.
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
            if key_id(p) is None:
                continue
            candidates = [r for r in by_size.get(size - 64, []) if candidate_pair(p, r)]
            if not candidates:
                continue
            if size > MAX_PAIR_BYTES:
                gaps["pair_budget"] += 1
                continue
            raw = self._fetch(opener, p, "keyed")
            if raw is None:
                continue
            key = key_id(p)
            body = raw[64:]
            for r in candidates:
                attempts += 1
                identity = {"key_id": key, "keyed_path": path, "reference_path": r["path"],
                            "keyed_sha256": p.get("sha256"), "reference_sha256": r.get("sha256"),
                            "reference_body_sha256": reference_body_sha[r["path"]], "body_bytes": len(body)}
                outcomes = {}
                accepted = None
                for model in MODELS:
                    outcome, table = self._evaluate(body, references[r["path"]], model)
                    outcomes[model] = outcome
                    if outcome["result"] == "accepted":
                        accepted = model, table
                        break
                if accepted is None:
                    below = any(o["result"] != "inconsistent" for o in outcomes.values())
                    if below:
                        gaps["pairs_below_minimum"] += 1
                    rejected.append({**identity, "outcome": "skipped_below_minimum" if below else "rejected",
                                     "models_rejected": [m for m, o in outcomes.items() if o["result"] == "inconsistent"],
                                     "model_outcomes": outcomes})
                    continue
                model, table = accepted
                pairs.append({**identity, "model": model, **mapping_status(table), "model_outcomes": outcomes})
                previous = maps.get(key)
                if previous:
                    old_model, old = previous
                    if old_model != model or any(a is not None and b is not None and a != b for a, b in zip(old, table)):
                        conflicts.add(key)
                    else:
                        table = [a if a is not None else b for a, b in zip(old, table)]
                maps[key] = (model, table)
        self._require_source()

        groups = []
        for key, count in sorted(Counter(key_id(p) for p in keyed).items()):
            model, table = maps.get(key, (None, [None] * 256))
            status = mapping_status(table)
            matched = len({pair["keyed_path"] for pair in pairs if pair["key_id"] == key})
            groups.append({"key_id": key, "files": count, "model": model, "cipher_to_plain": table,
                           **status, "conflicting_pairs": key in conflicts,
                           "solved": status["bijection"] and key not in conflicts,
                           "independently_matched_files": matched,
                           "files_without_plaintext_verification": count - matched,
                           "bit_permutation_xor": bit_permutation_xor(table) if model == "substitution" else None,
                           "decoded_files": 0, "decoded_plaintext_verified": 0, "decoded_hypothesis_only": 0,
                           "decode_gaps": {}})
        solved = {g["key_id"]: g for g in groups if g["solved"]}

        # Pass 3: decode members of solved keys; every member ends decoded or in a decode gap.
        stale = self._prepare_output(output_dir, create=bool(solved))
        decoded = []
        if solved:
            pending = {p["path"] for p in keyed if key_id(p) in solved}
            written: list[Path] = []
            try:
                for path, _, _, opener in entries():
                    check()
                    if path not in pending:
                        continue
                    pending.discard(path)
                    p = self.profiles[path]
                    g = solved[key_id(p)]
                    if p["container"].get("anomalies"):
                        self._decode_gap(g, "decode_skipped_anomalous")
                        continue
                    # Hash-named derivatives cannot escape the investigation directory.
                    name = hashlib.sha256(path.encode()).hexdigest() + ".body"
                    target = output_dir / name
                    try:
                        result = self._decode(opener, p, g, target, check)
                    except MemberReadError as err:
                        self._unreadable(path, "decode", err)
                        self._decode_gap(g, "decode_source_unreadable")
                        continue
                    if result is None:
                        self._integrity["changed"].append({"path": path, "stage": "decode"})
                        self._decode_gap(g, "decode_source_changed")
                        continue
                    written.append(target)
                    verified_against = [
                        {"reference_path": pair["reference_path"], "reference_sha256": pair["reference_sha256"],
                         "reference_body_sha256": pair["reference_body_sha256"]}
                        for pair in pairs
                        if pair["keyed_path"] == path and pair["reference_body_sha256"] == result["sha256"]]
                    verified = bool(verified_against)
                    g["decoded_files"] += 1
                    g["decoded_plaintext_verified" if verified else "decoded_hypothesis_only"] += 1
                    decoded.append({"path": path, "source_sha256": p["sha256"], "key_id": g["key_id"],
                                    **result, "derivative": name, "plaintext_verified": verified,
                                    "verified_against": verified_against})
                self._require_source()
                for path in sorted(pending):
                    # Indexed members of a solved key the dump no longer yields.
                    self._integrity["changed"].append({"path": path, "stage": "decode", "missing": True})
                    self._decode_gap(solved[key_id(self.profiles[path])], "decode_source_missing")
            except BaseException:
                # §8: cancellation (or any failure) removes this run's partial derivatives.
                for target in written:
                    target.unlink(missing_ok=True)
                raise
        return {"version": 2, "corpus": dict(corpus), "candidate_pairs_tested": attempts,
                "reference_files": len(references), "pairs": pairs, "rejected_pairs": rejected,
                "key_ids": groups, "decoded": decoded,
                "decoded_plaintext_verified": sum(1 for d in decoded if d["plaintext_verified"]),
                "decoded_hypothesis_only": sum(1 for d in decoded if not d["plaintext_verified"]),
                "gaps": dict(gaps), "integrity": self._integrity, "stale_derivatives_removed": stale,
                "limitations": ["Metadata nominates pairs; whole-body consistency is required, not semantic identity.",
                                "Decoding unpaired files applies a hypothesis, not independent plaintext verification; "
                                "each decoded file states whether its output equals a paired reference body "
                                "(plaintext_verified).",
                                "Models tested: substitution, cipher XOR offset, plain XOR offset, cipher minus offset. "
                                "Bit permutations plus XOR are included in substitution.",
                                f"A pair needs at least {MIN_BODY_BYTES} body bytes and {MIN_SYMBOLS} observed inputs "
                                "and distinct outputs; consistent pairs below that are reported as "
                                "skipped_below_minimum, not as rejected.",
                                "Keyed tables indexed before the container parser have no key id; they are counted "
                                "under keyed_without_key_id and are neither paired nor decoded.",
                                "Partial maps are never completed by guessing; reference/pair memory budgets are explicit."]}

    @staticmethod
    def _evaluate(body: bytes, reference: bytes, model: str) -> tuple[dict, list | None]:
        table = derive_mapping(body, reference, model)
        if table is None:
            return {"result": "inconsistent"}, None
        status = mapping_status(table)
        counts = {"observed_inputs": status["observed_inputs"], "distinct_outputs": status["distinct_outputs"]}
        if len(body) < MIN_BODY_BYTES:
            return {"result": "below_minimum_body_bytes", **counts}, table
        if min(counts.values()) < MIN_SYMBOLS:
            return {"result": "below_minimum_symbols", **counts}, table
        return {"result": "accepted", **counts}, table

    def _decode_gap(self, group: dict, reason: str) -> None:
        group["decode_gaps"][reason] = group["decode_gaps"].get(reason, 0) + 1
        self._gaps[reason] += 1

    def _require_source(self) -> None:
        # A vanished folder makes os.walk yield nothing rather than fail: never let that
        # pass as an empty, complete analysis.
        if not self._source_available():
            raise FileNotFoundError(errno.ENOENT, "FFS source is no longer available during table recovery")

    def _unreadable(self, path: str, stage: str, err: MemberReadError) -> None:
        if not self._source_available():
            raise err.original  # the dump went away (drive unplugged): interrupt, resumable
        self._integrity["unreadable"].append({"path": path, "stage": stage, "error": str(err)[:500]})

    def _fetch(self, opener, profile: dict, stage: str) -> bytes | None:
        """Verified member bytes, or None after recording the member as changed or unreadable."""
        try:
            raw = self._read(opener, profile, self._check)
        except MemberReadError as err:
            self._unreadable(profile["path"], stage, err)
            self._gaps[f"{stage}_unreadable"] += 1
            return None
        if raw is None:
            self._integrity["changed"].append({"path": profile["path"], "stage": stage})
            self._gaps[f"{stage}_changed"] += 1
        return raw

    @staticmethod
    def _prepare_output(output_dir: Path, create: bool) -> int:
        """Refuse a linked/reparse derivative directory and remove derivatives left by an
        interrupted earlier run (no report covers them). Returns how many were removed."""
        if create:
            output_dir.mkdir(parents=True, exist_ok=True)
        elif not os.path.lexists(output_dir):
            return 0
        st = output_dir.lstat()
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            raise PermissionError("Linked/reparse derivative directory is not admitted")
        if not stat.S_ISDIR(st.st_mode):
            raise NotADirectoryError(errno.ENOTDIR, "Derivative path is not a directory", str(output_dir))
        removed = 0
        for entry in os.scandir(output_dir):
            if _DERIVATIVE_NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False):
                os.unlink(entry.path)
                removed += 1
        return removed

    @staticmethod
    def _decode(opener, profile, group, target, check):
        """Stream-decode one member; None when its bytes no longer match the index.
        Source read errors raise MemberReadError; output errors propagate unchanged."""
        # Do not append the UUID to the 64-character digest: investigation roots
        # can already approach Win32's path-length limit.
        tmp = target.with_name(uuid.uuid4().hex + ".tmp")
        sha, original = hashlib.sha256(), hashlib.sha256()
        model, table = group["model"], group["cipher_to_plain"]
        offset = 0
        try:
            src = _open(opener)
            try:
                with tmp.open("xb") as dst:
                    original.update(_chunk(src, 64))
                    while chunk := _chunk(src, CHUNK_SIZE):
                        check()
                        original.update(chunk)
                        if model == "substitution":
                            data = chunk.translate(bytes(table))
                        else:
                            data = bytes(table[_symbol(b, offset + i, model)]
                                         ^ (((offset + i) & 255) if model == "plain-xor-offset" else 0)
                                         for i, b in enumerate(chunk))
                        offset += len(chunk)
                        sha.update(data)
                        dst.write(data)
            finally:
                src.close()
            if original.hexdigest() != profile.get("sha256"):
                return None
            check()
            os.replace(tmp, target)
            return {"body_bytes": offset, "sha256": sha.hexdigest()}
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _read(opener, profile, check=lambda: None) -> bytes | None:
        """Whole member, or None when its size or SHA-256 no longer matches the index.
        Read errors raise MemberReadError (never swallowed); ``check`` runs per chunk."""
        expected = profile["bytes"]
        digest = hashlib.sha256()
        buf = bytearray()
        src = _open(opener)
        try:
            while chunk := _chunk(src, min(CHUNK_SIZE, expected + 1 - len(buf))):
                check()
                buf += chunk
                digest.update(chunk)
                if len(buf) > expected:
                    return None
        finally:
            src.close()
        if len(buf) != expected or digest.hexdigest() != profile.get("sha256"):
            return None
        return bytes(buf)
