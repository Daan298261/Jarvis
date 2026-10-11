# RFC-0207: ANZU APK Reverse-Engineering Sidecar (RE Phase 1)

**Status:** accepted  
**Queue item:** (none — Phase 1 spec; Architect may add a §58 line after land; do not edit `JARVIS_MASTER_PLAN.md` here)  
**Author:** Daan / Codex  
**Date:** 2026-10-09

**Aligns with:** [`ANZU_PRODUCT_NORTH_STAR.md`](../../ANZU_PRODUCT_NORTH_STAR.md) §1 (end goal: figure out how to accomplish the task), §8 (verify own work: confidence from evidence, not cheerful messages), §9 (local-first infrastructure), §15 (security and evidence platform), §20 (quality test: evidence over speculation, graceful degradation).  
**Extends:** [RFC-0201](0201-reverse-engineer-anything.md) (ANZU Reverse Engineer Anything), [RFC-0200](0200-rea-mcp-local-investigation.md) (REA MCP local investigation).  
**Related:** [RFC-0208](0208-ffs-dump-self-ingest.md) (FFS Dump Self-Ingest Phase 2), [RFC-0198](0198-blue-re-lta-protected-folder.md) (LTA extract dirs), [RFC-0197](0197-blue-red-purple-security-agents.md) (security agent policy).

This PR is **specs-only**. No application code. Do not edit spec docs. Do not commit.

---

## Problem

Under RFC-0201, ANZU's mobile reverse-engineering capability is bounded to a single standalone `.apk` artifact copied into the investigation workspace (`store.prepare`) and subjected to rudimentary DEX decompilation via `jadx --no-res -d ...` (`backend/app/reverse_engineering/android.py`). This baseline has five major operational shortcomings during real Android application and forensic investigations:

1. **Unsupported real-world packaging formats:** Modern Android applications (Google Play App Bundles, OEM diagnostic suites, enterprise packages) rarely ship as single monolithic APKs. They arrive as split APK sets (`base.apk` + `split_config.arm64_v8a.apk` + `split_config.xxhdpi.apk`), containerized `.xapk` / `.apks` archives, or directories on seized devices. Ingesting only a single file causes missing native libraries, absent resources, or incomplete DEX classes.
2. **Missing resource decoding and manifest synthesis:** Running `jadx --no-res` skips Android resource tables (`resources.arsc`) and binary XML decoding. Without `apktool` resource decoding, `AndroidManifest.xml` remains binary or unlinked, preventing extraction of declared components, intent filters, deep links, content provider authorities, and network security configs.
3. **No structured static analysis extraction:** Analysts and AI agents must manually grep raw decompiled output. There is no automated extraction of package identity, permission risk, exported component attack surfaces, native shared library (`.so`) inventories and JNI entry points, network endpoints / URLs, or cryptographic key material and insecure cipher usage.
4. **Weak chain of custody and evidence citation:** Results from decompilation are not written into structured, citable evidence records (`<investigation>/evidence/E0000X.json`). Agents cannot cite specific decompilation findings in reports or distinguish established facts from incomplete coverage (such as obfuscated DEX or packed native binaries).
5. **Coupled, brittle toolchain readiness:** `android.py` readiness checks require the heavy Android emulator, system images (~2 GB), and AVD initialization before marking the subsystem `ready`. If an analyst only needs static reverse engineering of an APK, requiring an emulator download is wasteful, slow, and blocks static analysis if virtualization is unavailable.

## Decision

Extend the existing RFC-0201 REA path with a dedicated, execution-free **APK Reverse-Engineering Sidecar** (Phase 1). No rewrite of existing investigation stores, no stubs, and no changes to single-artifact caps in `store.prepare`.

The sidecar orchestrates pinned `apktool` and `jadx` instances inside the existing `ANZU-REA` WSL2 environment (or host JVM), processes standalone APKs, split APKs, and `.xapk` containers, and extracts structured metadata into citable evidence records.

---

### 1. Architectural Position & REA Path Extension

The APK Reverse-Engineering Sidecar operates as an execution-free static analysis pipeline within `backend/app/reverse_engineering/`:

```
+---------------------------------------------------------------------------------------------------+
|                                   Investigation Coordinator                                       |
|                                (backend/app/reverse_engineering/)                                 |
+---------------------------------------------------------------------------------------------------+
       |                                       |                                      |
       v                                       v                                      v
 [RFC-0201 Store]                     [RFC-0208 FFS Index]                     [ADB Device Bridge]
 store.prepare()                      index/files.ndjson                       android.py (adb)
       |                                       |                                      |
       +-----------------------+---------------+--------------------------------------+
                               |
                               v Target APK / XAPK / Split Set
+---------------------------------------------------------------------------------------------------+
|                             APK Reverse-Engineering Sidecar Pipeline                              |
|                              (backend/app/reverse_engineering/apk.py)                             |
+---------------------------------------------------------------------------------------------------+
       |                                                                              |
       +-------------------------------+------------------------------+               |
       |                               |                              |               |
       v                               v                              v               v
 [Container Unpack]           [apktool Decode]                [jadx Decompile]   [ELF Native Walk]
 Safe ZIP / Split Merge       res/, AXML, XML Strings         DEX -> Java        lib/<ABI>/*.so
       |                               |                              |               |
       +-------------------------------+------------------------------+---------------+
                                       |
                                       v
+---------------------------------------------------------------------------------------------------+
|                                   Metadata & Extraction Engine                                    |
|  - Manifest & Components (Exported Attack Surface, Permissions)                                   |
|  - Native .so Inventory (ABIs, JNI Exports, Packing/Entropy Detection)                            |
|  - String Pools & Endpoints (URLs, IPs, WebSockets, Schemes, Cloud APIs)                          |
|  - Cryptographic Hints (Hardcoded Secrets, Weak Ciphers, Network Security Config)                 |
+---------------------------------------------------------------------------------------------------+
                                       |
                                       v
+---------------------------------------------------------------------------------------------------+
|                                 Investigation Evidence Store                                      |
|  <investigation>/evidence/E0000X.json (citable) | <investigation>/apk/metadata/*.json            |
|  <investigation>/custody.json (chain of custody) | findings & declared unknowns in report.json    |
+---------------------------------------------------------------------------------------------------+
```

- **Non-destructive extension:** The sidecar extends `backend/app/reverse_engineering/runtime.py` and `android.py`. It registers static tool operations in the investigation catalog (`apk_decompile`, `apk_extract_manifest`, `apk_inventory_native`, `apk_extract_endpoints`, `apk_crypto_hints`).
- **Fail-closed path security:** All extraction, decoding, and decompilation targets remain strictly bounded under `<data_dir>/investigations/<id>/apk/`. No symlinks, reparse points, or path escapes outside the investigation directory are admitted.
- **Execution-free Phase 1:** Phase 1 performs static analysis and extraction only. No target application code is executed during this pipeline; dynamic runtime capture remains gated under RFC-0201 `android_capture`.

---

### 2. Ingestion & Input Pipeline

The sidecar accepts three input packaging formats from three distinct origins:

#### 2.1 Input Formats

| Format | Structure | Sidecar Handling |
| --- | --- | --- |
| **Standalone APK** (`.apk`) | Single ZIP container with `AndroidManifest.xml`, `classes.dex`, `resources.arsc`, `lib/`, `res/`. | Fingerprinted, validated, and directly passed to the decompile pipeline. |
| **XAPK Container** (`.xapk`) | ZIP container holding `manifest.json`, `base.apk`, split configuration APKs (`config.*.apk`), and optional OBB files (`Android/obb/`). | Unpacked under `<investigation>/apk/staged/`. The sidecar inspects `manifest.json`, resolves `base.apk`, and inventories all split packages. OBB files are indexed as secondary assets without extraction. |
| **Split APK Set** (App Bundle directory or list) | Multi-APK directory containing `base.apk` alongside architecture splits (`split_config.arm64_v8a.apk`), language splits, and display splits. | `base.apk` provides primary manifest and components. Architecture splits provide ABI `.so` binaries. Additional splits containing `classes.dex` are ingested into the JADX DEX search path. |

#### 2.2 Input Origins

1. **Owner-Named Local Path:** Direct filesystem target resolved via `resolve_allowed_path` within approved roots (`store.prepare`).
2. **Connected Android Device via ADB:**
   - Command: `adb shell pm path <package_name>` enumerates all APK parts installed on the device (e.g. `package:/data/app/~~.../base.apk` and `package:/data/app/~~.../split_config.arm64_v8a.apk`).
   - Command: `adb pull <remote_path> <investigation>/apk/staged/` fetches base and split APKs.
   - Requires device connection and authorization, but does **not** launch or execute the app.
3. **Forensic FFS Ingest Reference (RFC-0208):**
   - References an APK from an existing FFS investigation (`kind == "ffs"`).
   - The sidecar reads the file entry from `<ffs_investigation>/index/files.ndjson`.
   - The specific APK bytes are streamed read-only into `<investigation>/apk/target/` without copying or modifying the source 60 GB dump.
   - The SHA-256 of the extracted target is verified against the entry in the FFS NDJSON index, preserving forensic provenance.

#### 2.3 Unpack Safety Bounds

- Maximum total uncompressed archive size: 8 GiB (`store.MAX_BYTES`).
- Maximum total file count: 50,000 files (`store.MAX_FILES`).
- Path sanitization: every ZIP entry is checked with `PurePosixPath`. Entries with absolute paths, directory traversals (`..`), or NTFS alternate data streams (`:`) trigger immediate termination with `ValueError("Unsafe archive entry")`.

---

### 3. Sidecar Process Lifecycle & Toolchain Readiness

The sidecar reuses and refines the toolchain verification pattern from `backend/app/reverse_engineering/android.py`.

#### 3.1 Pinned Toolchain

| Tool | Version | Location / Runtime | Purpose |
| --- | --- | --- | --- |
| **JDK** | 21.0.12.1+1 | `/opt/anzu/jdk` (WSL) or host `<runtime>/android/jdk` | Runtime for JADX, apktool, and APK analyzers |
| **JADX** | 1.5.6 | `/opt/anzu/jadx/bin/jadx` | High-level DEX to Java decompilation |
| **apktool** | 2.10.0 | `/opt/anzu/apktool/apktool.jar` | AXML decoding, resource table reconstitution, smali fallback |
| **aapt / aapt2** | 35.0.0 | `<runtime>/android/sdk/build-tools/35.0.0/aapt2` | Fast manifest dump and resource inspection fallback |

#### 3.2 Decoupled Readiness (`readiness_static()`)

`android.py` readiness is decoupled into two explicit check functions:

1. `readiness_static()`: Verifies only tools required for static APK reverse engineering:
   - JDK 21 executable exists.
   - JADX executable exists.
   - `apktool.jar` exists and matches pinned SHA-256 (`engine-lock.json`).
   - If any are missing, returns `{"status": "needs_repair", "stage": "Static APK toolchain missing", "error": "Missing: ...; run setup to install"}`.
2. `readiness_dynamic()`: Retains the existing `android.py` checks for `adb.exe`, `emulator.exe`, and `anzu_rea.ini`.

The static APK sidecar requires only `readiness_static() == "ready"`. Static reverse engineering does not fail if emulator virtualization is disabled or unconfigured.

#### 3.3 Concurrency, Memory & Process Lifecycle

- **Concurrency ceiling:** At most 2 concurrent decompilation tasks across the system to prevent CPU/memory starvation (`asyncio.Semaphore(2)`).
- **Memory cap:** Subprocess JVMs are launched with `-Xmx4g -XX:+UseG1GC` to prevent unbounded heap consumption.
- **Timeouts:**
  - `apktool` resource decoding: 300 seconds.
  - `jadx` DEX decompilation: 600 seconds.
- **Process isolation & cancellation:** Subprocesses are tracked in the investigation session registry. If an investigation is cancelled or timed out:
  1. The sidecar issues `SIGTERM` (or `terminate()`) to the process group.
  2. If the process does not terminate within 10 seconds, `SIGKILL` is issued.
  3. Partial output directories are marked with `.incomplete` markers.
  4. The investigation row status transitions to `interrupted`.

---

### 4. Decompilation Pipeline: apktool & jadx Orchestration

The decompile pipeline runs as a two-phase coordinated process:

```
[Target APK / Splits]
         |
         +---------------------------------------+
         |                                       |
         v                                       v
   Phase A: apktool                        Phase B: jadx
  Resource & Manifest                      Bytecode & Classes
         |                                       |
  - AndroidManifest.xml (readable UTF-8)  - Multi-DEX processing
  - res/values/strings.xml                - Java source tree (*.java)
  - res/xml/network_security_config.xml   - Method call hierarchies
  - Raw assets/ and res/                  - Smali fallback on error
         |                                       |
         +-------------------+-------------------+
                             |
                             v
                Synthesized Investigation View
```

#### Phase A: apktool (Resource & Manifest Reconstitution)
- **Command:**  
  `java -Xmx4g -jar /opt/anzu/apktool/apktool.jar d -f --no-src -o <target>/apk/apktool <apk_path>`
- `--no-src` skips smali generation during Phase A to reduce disk footprint and execution time, since `jadx` generates full Java source in Phase B.
- If `jadx` encounters catastrophic failure on specific DEX classes, `apktool` can be invoked targetedly without `--no-src` to recover smali disassembly for those specific classes.
- Produces:
  - Valid, human-readable UTF-8 `AndroidManifest.xml` (converted from binary AXML).
  - Fully decoded `res/values/strings.xml`, `arrays.xml`, `integers.xml`.
  - Security configurations: `res/xml/network_security_config.xml`.

#### Phase B: jadx (DEX Bytecode Decompilation)
- **Command:**  
  `/opt/anzu/jadx/bin/jadx --no-res -d <target>/apk/jadx --threads-count 4 --show-bad-code --escape-unicode <apk_path>`
- `--no-res` prevents duplicate or conflicting resource processing, letting `apktool` remain the single source of truth for resources.
- `--show-bad-code` forces JADX to emit partial/pseudo-code even when control-flow deobfuscation fails, rather than discarding the method.
- Multi-DEX handling: automatically consumes `classes.dex`, `classes2.dex`, `classes3.dex`, etc.
- Diagnostic collection: stdout and stderr are parsed for warnings, decompiler crashes, and skipped classes. Classes that failed decompilation are cataloged into `unknowns` to maintain honest coverage tracking.

---

### 5. Manifest, Permission, and Component Extraction

From the decoded `AndroidManifest.xml`, the sidecar produces `<investigation>/apk/metadata/manifest.json` and `<investigation>/apk/metadata/components.json`.

#### 5.1 Package & SDK Metadata
- Package identifier: `package` (e.g. `com.example.app`).
- Versioning: `android:versionCode`, `android:versionName`.
- SDK constraints: `minSdkVersion`, `targetSdkVersion`, `maxSdkVersion`.
- Installation & flags: `installLocation`, `sharedUserId`.

#### 5.2 Application Security Flags
- `android:debuggable`: Flagged as critical if `true` in release packages.
- `android:allowBackup`: Flagged if `true` (allows adb backup extraction).
- `android:usesCleartextTraffic`: Flagged if `true` (permits unencrypted HTTP).
- `android:networkSecurityConfig`: Reference to custom XML trust policy.
- `android:requestLegacyExternalStorage`: Scoped storage bypass flag.

#### 5.3 Permissions Analysis
- **Declared Permissions (`<permission>`):** Custom permissions exposed by this app, including `name` and `protectionLevel` (`normal`, `dangerous`, `signature`, `signatureOrSystem`).
- **Requested Permissions (`<uses-permission>`):** All permissions requested from the Android OS.
- **Dangerous & High-Risk Flags:** Categorizes sensitive permissions:
  - Storage: `READ_EXTERNAL_STORAGE`, `WRITE_EXTERNAL_STORAGE`, `MANAGE_EXTERNAL_STORAGE`.
  - Location: `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`.
  - Media & Hardware: `CAMERA`, `RECORD_AUDIO`, `BODY_SENSORS`.
  - Identity & Telephony: `READ_CONTACTS`, `READ_PHONE_STATE`, `CALL_PHONE`, `READ_SMS`, `SEND_SMS`.
  - System: `SYSTEM_ALERT_WINDOW`, `REQUEST_INSTALL_PACKAGES`, `WRITE_SETTINGS`.

#### 5.4 Component Inventory & Exported Attack Surface
Every component is classified into one of four Android types:

| Component Type | Attributes Extracted | Security Evaluation |
| --- | --- | --- |
| **Activities** | Name, `android:exported`, required permission, intent-filters. | Identifies entry screens accessible by third-party apps without authentication. |
| **Services** | Name, `android:exported`, required permission, intent-filters. | Identifies background workers, IPC interfaces, and unprotected Binder endpoints. |
| **Broadcast Receivers** | Name, `android:exported`, required permission, intent-filters. | Identifies broadcast listeners vulnerable to unauthorized intent injection. |
| **Content Providers** | Name, `android:exported`, `android:authorities`, `readPermission`, `writePermission`, `grantUriPermissions`. | High-priority attack surface: identifies unprotected database providers vulnerable to data leakage or SQL injection. |

**Exported Status Calculation:**
- Explicit: `android:exported="true"` or `android:exported="false"`.
- Implicit (pre-Android 12 behavior): if `android:exported` is omitted, components containing at least one `<intent-filter>` default to `exported="true"`.
- Attack Surface Score: computes total components, total exported components, and total exported components lacking permission enforcement (`exported_unprotected_count`).

---

### 6. Native `.so` Inventory & Architecture Analysis

Android applications frequently encapsulate proprietary algorithms, anti-tamper logic, or crypto routines in native C/C++ libraries. The sidecar performs binary inspection without running the code.

#### 6.1 Architecture Inventory
Scans `<apk>/lib/<ABI>/` for standard architectures:
- `arm64-v8a` (64-bit ARM)
- `armeabi-v7a` (32-bit ARM)
- `x86_64` (64-bit Intel/AMD)
- `x86` (32-bit Intel/AMD)

For each library discovered, records:
- Relative path (e.g. `lib/arm64-v8a/libengine.so`).
- ABI target.
- File size (bytes).
- SHA-256 digest.

#### 6.2 ELF Header & Symbol Inspection
Using an in-process ELF parser (with fallback to `readelf` in WSL):
- **ELF Type & Class:** 32-bit vs 64-bit ELF, endianness, machine architecture.
- **SONAME:** Internal library identifier (`DT_SONAME`).
- **Dynamic Dependencies:** Needed shared objects (`DT_NEEDED`, e.g. `libc.so`, `libcrypto.so`, `liblog.so`).
- **Exported Dynamic Symbols (`.dynsym`):**
  - Flags JNI method implementations following standard naming: `Java_<package>_<class>_<method>`.
  - Identifies lifecycle entry points: `JNI_OnLoad`, `JNI_OnUnload`.
- **Relocations & Security Hardening:**
  - Checks for GNU RELRO (`Full RELRO` vs `Partial RELRO`).
  - Checks for Stack Canaries (`__stack_chk_fail` presence).
  - Checks for Executable Stack (`GNU_STACK` flag with `RWE`).

#### 6.3 Packing & High-Entropy Detection
- Computes Shannon entropy over 4 KiB sliding blocks:
  - Entropy $> 7.2$ across code segments indicates packed, encrypted, or compressed native code.
- Known packer / protector signature scan:
  - Bangcle (`libsecexe.so`, `libsecmain.so`)
  - Tencent Legu (`libtxloader.so`, `libshell.so`)
  - Qihoo 360 (`libprotectClass.so`, `libjiagu.so`)
  - SecNeo (`libDexHelper.so`)
  - DexGuard / DashO native components.
- If a packer is detected, an explicit unknown is logged: `"Native code is protected by <PackerName>; static symbols are obscured."`

---

### 7. String & Network Endpoint Extraction

Strings and endpoints are extracted across multiple layers, indexed, and sanitized into `<investigation>/apk/metadata/endpoints.json` and `<investigation>/apk/metadata/strings.json`.

#### 7.1 Sources Scanned
1. **DEX String Pools:** Extracted directly from `classes*.dex` string ID tables.
2. **Resource Strings:** Extracted from decoded `res/values/strings.xml` and localized variants (`values-*/strings.xml`).
3. **Decompiled Java Literals:** String constants found in `.java` source files.

#### 7.2 Endpoint Taxonomy & Regex Patterns

| Category | Regex / Extraction Rule | Noise Filtering / Exclusion |
| --- | --- | --- |
| **HTTP / HTTPS URLs** | `https?://[a-zA-Z0-9][-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_+.~#?&//=]*)` | Excludes standard XML schema namespaces (`schemas.android.com`, `www.w3.org`, `apache.org/xml`). |
| **IP Addresses** | Standard IPv4 and IPv6 patterns. | Excludes loopbacks (`127.0.0.1`), unassigned (`0.0.0.0`), broadcast (`255.255.255.255`), and local link-local addresses. |
| **WebSockets** | `wss?://[a-zA-Z0-9._-]+(:[0-9]+)?(/.*)?` | None. |
| **Custom URI Schemes** | `[a-zA-Z][a-zA-Z0-9+.-]+://[^"\s<>]+` (extracted from Manifest intent-filters and code). | Excludes `android-resource://`, `file://`, `content://android.`. |
| **Cloud / Backend Services** | Specific domain patterns for AWS (`*.amazonaws.com`), Firebase (`*.firebaseio.com`, `*.firebaseapp.com`), Supabase, Azure, Google Cloud APIs. | Grouped into high-confidence service buckets. |

#### 7.3 Output Structure
Each extracted endpoint record includes:
- `url` or `endpoint`: The raw string value.
- `category`: `url`, `ipv4`, `websocket`, `custom_scheme`, `cloud_service`.
- `occurrences`: Total count found.
- `references`: List of sample source locations (`res/values/strings.xml`, `sources/com/example/NetworkClient.java:42`).

---

### 8. Cryptographic & Key-Material Hints

Static heuristic detection flags potential cryptographic vulnerabilities and embedded credentials across Java sources, smali, and decoded resources, saved into `<investigation>/apk/metadata/crypto_hints.json`.

#### 8.1 Hardcoded Secrets & Credentials
- **Google API Keys:** `AIza[0-9A-Za-z\-_]{35}`
- **AWS Access Key IDs:** `AKIA[0-9A-Z]{16}`
- **Generic High-Entropy Keys:** Variable assignment patterns matching `(api_key|apiKey|secret_key|client_secret|auth_token)\s*=\s*["']([A-Za-z0-9_\-]{24,})["']`
- **Private Key PEM Blocks:** Matches `-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----`
- **Firebase Project IDs / DB URLs:** `https://[a-z0-9\-]+\.firebaseio\.com`

#### 8.2 Insecure Cryptographic Usage
- **ECB Mode Ciphers:** Flagged when `Cipher.getInstance("AES/ECB/...")` or `Cipher.getInstance("DES")` is instantiated.
- **Hardcoded Static IVs:** Detects `IvParameterSpec` initialized with hardcoded byte arrays or constant strings.
- **Static Encryption Keys:** Detects `SecretKeySpec` initialized from string literals or inline byte arrays instead of AndroidKeyStore or KeyDerivationFunction (`PBKDF2`, `HKDF`).
- **Broken Hash Functions:** Flags `MessageDigest.getInstance("MD5")` or `MessageDigest.getInstance("SHA-1")` when used in signature or password contexts.

#### 8.3 Network Security Config & Trust Anchors
If `res/xml/network_security_config.xml` is present, the sidecar evaluates:
- **User Certificate Trust:** Checks for `<certificates src="user" />` under `<trust-anchors>`, which allows Man-in-the-Middle (MitM) traffic interception via user-installed CA certificates.
- **Cleartext Permits:** Checks for `<domain-config cleartextTrafficPermitted="true">` specifying domains where plaintext HTTP is permitted.
- **Certificate Pinning:** Checks for `<pin-set>` configurations and records whether custom SPKI pins are enforced or if expiration overrides are present.

#### 8.4 AndroidKeyStore vs Software Crypto
- Inventories usage of `KeyStore.getInstance("AndroidKeyStore")`.
- Highlights whether cryptographic operations rely on hardware-backed security (StrongBox / TEE) or purely software-implemented cryptography.

---

### 9. Investigation Evidence Store & Chain of Custody

All outputs from the APK reverse-engineering pipeline integrate into the existing ANZU investigation evidence store (`backend/app/reverse_engineering/store.py`).

#### 9.1 Filesystem Hierarchy
Under `<data_dir>/investigations/<id>/`:

```
<investigation_id>/
├── investigation.json                # Standard row metadata
├── custody.json                      # Immutable chain of custody record
├── target/                           # Prepared input artifact (APK / XAPK)
│   └── original_target.apk
├── apk/
│   ├── staged/                       # Unpacked split APKs / components
│   ├── apktool/                      # Decoded resources and readable manifest
│   │   ├── AndroidManifest.xml
│   │   └── res/
│   ├── jadx/                         # Recovered Java source tree
│   │   └── sources/
│   └── metadata/                     # Machine-readable extraction results
│       ├── manifest.json
│       ├── components.json
│       ├── native_libs.json
│       ├── endpoints.json
│       ├── crypto_hints.json
│       └── strings.json
├── evidence/
│   ├── E00001.json                   # Ingest & Unpack Evidence
│   ├── E00002.json                   # Manifest & Components Evidence
│   ├── E00003.json                   # Decompile Pipeline Evidence
│   ├── E00004.json                   # Native Libraries Evidence
│   ├── E00005.json                   # Endpoints & Network Evidence
│   └── E00006.json                   # Cryptographic Hints Evidence
├── report.json                       # Final investigation report
└── report.md                         # Markdown summary for owner/analyst
```

#### 9.2 Chain of Custody (`custody.json`)
The custody record preserves verifiable forensic provenance:

```json
{
  "investigation_id": "0123456789abcdef0123456789abcdef",
  "task_id": "task-789",
  "source_uri": "device://emulator-5584/com.example.app",
  "source_kind": "device_pull",
  "source_sha256": "3a5b6c...9e",
  "source_bytes": 48291048,
  "toolchain": {
    "platform": "WSL2 ANZU-REA",
    "jdk": "21.0.12.1+1",
    "jadx": "1.5.6",
    "apktool": "2.10.0"
  },
  "ingested_at": "2026-10-09T14:30:00Z",
  "decompiled_at": "2026-10-09T14:32:15Z",
  "completed_at": "2026-10-09T14:33:02Z",
  "analyst": "ANZU-Superassistant",
  "verified_digest": "3a5b6c...9e"
}
```

#### 9.3 Discrete Evidence Records (`E00001` - `E00006`)
Each evidence entry follows the standard schema required by `store.py::record`:

- `E00001` (`apk_unpack`): Package packaging metadata, file manifest, container format (XAPK, split set, monolithic).
- `E00002` (`apk_manifest`): Decoded package name, version, SDK bounds, permissions, and exported component attack surface.
- `E00003` (`apk_decompile`): JADX execution summary, class counts, decompiler diagnostics, and recovered Java directory path.
- `E00004` (`apk_native_libs`): Inventories of `.so` files, ABIs, JNI symbols, and packer detection results.
- `E00005` (`apk_endpoints`): Classified URLs, IP addresses, WebSockets, and custom schemes with line-level references.
- `E00006` (`apk_crypto_hints`): Flagged hardcoded credentials, weak ciphers, and network security config trust policies.

#### 9.4 Report Synthesis & Declared Unknowns
When `store.write_report` produces `report.json` and `report.md`, findings cite these evidence IDs directly:

```json
{
  "findings": [
    {
      "kind": "observation",
      "claim": "The application exports 4 Content Providers and 2 Broadcast Receivers with no permission requirements, allowing unauthorized external invocation.",
      "evidence_ids": ["E00002"],
      "limitations": "Static manifest parsing only; dynamic authorization checks in code were not evaluated."
    },
    {
      "kind": "observation",
      "claim": "Hardcoded AWS Access Key ID detected in com/example/Config.java and cleartext HTTP traffic is explicitly permitted.",
      "evidence_ids": ["E00005", "E00006"],
      "limitations": "Key validity was not verified against remote AWS endpoints."
    }
  ],
  "unknowns": [
    "DEX code exhibits heavy identifier renaming (ProGuard/R8); 62% of class names are obfuscated.",
    "Native library libcore.so has high entropy (7.64) suggesting packing or encryption; dynamic memory dump required for symbol resolution."
  ]
}
```

---

### 10. API Endpoints & Tool Catalog Exposure

The APK sidecar surfaces via authenticated REST API endpoints in `backend/app/api/investigations.py` and via tool operations in `backend/app/reverse_engineering/runtime.py`.

#### 10.1 REST API Routes

```
POST /api/investigations/apk/prepare
```
- Prepares an APK investigation from a local path, device pull, or FFS ingest reference.
- **Request Body:**
  ```json
  {
    "source_type": "file" | "device" | "ffs",
    "target": "/path/to/app.apk",
    "device_serial": "emulator-5584",
    "package_name": "com.example.app",
    "ffs_investigation_id": "0123...def",
    "question": "Identify network endpoints and exported attack surface",
    "task_id": "task-102"
  }
  ```
- **Response:** Public investigation row (`id`, `status: "prepared"`, `target`, `sha256`).

```
POST /api/investigations/{id}/apk/decompile
```
- Triggers the complete APK sidecar pipeline (unpack, apktool, jadx, metadata extraction, evidence generation).
- **Request Body:**
  ```json
  {
    "skip_jadx": false,
    "decompile_smali_fallback": true,
    "background": true
  }
  ```
- **Response:** Current investigation row and status (`"analyzing"` or `"investigating"`).

```
GET /api/investigations/{id}/apk/summary
```
- Returns high-level synthesized overview: package ID, version, SDK limits, component count, exported attack surface count, native ABI count, URL count, crypto alert count.

```
GET /api/investigations/{id}/apk/manifest
GET /api/investigations/{id}/apk/components
GET /api/investigations/{id}/apk/native
GET /api/investigations/{id}/apk/endpoints
GET /api/investigations/{id}/apk/crypto
```
- Returns the specific structured JSON documents generated under `<investigation>/apk/metadata/`.

#### 10.2 Agent Tool Catalog Operations (`runtime.py`)

Registered under `STATIC_OPERATIONS` so agents can call them during investigations without extra runtime approvals:

| Tool Operation | Description | Arguments Schema |
| --- | --- | --- |
| `apk_decompile` | Runs full apktool and jadx pipeline on the prepared APK target. | `{ "skip_jadx": boolean }` |
| `apk_extract_manifest` | Returns parsed manifest, permissions, and exported attack surface. | `{}` |
| `apk_inventory_native` | Returns native `.so` libraries, ABIs, ELF headers, and JNI symbols. | `{ "abi": string }` (optional filter) |
| `apk_extract_endpoints` | Returns extracted URLs, IPs, schemes, and backend endpoints. | `{ "category": string, "limit": integer }` |
| `apk_crypto_hints` | Returns hardcoded secrets, weak cipher alerts, and network security config. | `{}` |

---

### 11. Failure Modes & Graceful Degradation

| Failure Condition | Detection | Graceful Degradation & System Behavior |
| --- | --- | --- |
| **Missing Static Tools** | `readiness_static()` detects missing JDK, JADX, or apktool. | Returns `needs_repair` with exact missing tool name and remediation command. Never crashes or executes broken subcommands. |
| **Corrupted or Truncated APK** | ZIP signature missing (`PK\x03\x04`), bad CRC, or truncated header. | Fails fast with `ValueError("Target is not a valid APK/ZIP container")`. Workspace is cleaned up, error logged in custody record. |
| **Zip Slip / Path Traversal** | Archive entry contains `..`, absolute path, or colon `:`. | Reject extraction immediately with `ValueError("Unsafe archive entry: <path>")`. Prevents arbitrary file write vulnerabilities. |
| **Zip Bomb / Resource Explosion** | Uncompressed bytes exceed 8 GiB or file count exceeds 50,000. | Extraction loop aborts immediately when cap is reached; logs `ValueError("Archive exceeds expanded size/file limit")`. |
| **JADX Memory Exhaustion / OOM** | Subprocess exits with exit code 137 or `OutOfMemoryError`. | Catch failure; fall back to class-by-class decompilation or smali extraction. Manifest, resources, and native inventory remain valid; JADX failure is recorded as an explicit `unknown` in the final report. |
| **JADX Decompile Timeout (> 600s)** | Subprocess exceeds execution deadline. | Sidecar kills the process group cleanly; indexes already decompiled classes; records timeout in evidence diagnostics; report status marked `partial`. |
| **apktool AXML Decoding Failure** | Heavily obfuscated binary XML triggers apktool parsing exception. | Fall back to JADX internal binary XML decoder (`jadx` has a standalone AXML parser). Preserve available resources; record manifest limitations in `unknowns`. |
| **Anti-Decompiler DEX Tricks** | Bogus bytecode instructions cause specific method decompiler errors. | JADX flag `--show-bad-code` forces partial pseudo-code output; affected methods are tagged with `/* JADX WARNING */`; sidecar catalogs them as incomplete coverage. |
| **Heavily Packed Native Binaries** | High entropy ($>7.2$) or known packer signature detected in `.so`. | Record native binary metadata and hashes into evidence; record explicit unknown: `"Native binary is packed; static symbol extraction incomplete; dynamic unpacking required."` |

---

## Test Plan with Synthetic Fixtures

Testing the APK sidecar must not require multi-gigabyte commercial APKs or real device hardware during CI runs. The test suite uses synthetic, deterministically constructed fixtures.

### 1. Synthetic Test Fixtures

Stored under `tests/fixtures/apk/`:

1. `minimal_valid.apk`:
   - Valid ZIP container containing:
     - Minimal binary `AndroidManifest.xml` (package `org.anzu.test`, `versionCode=1`, `minSdkVersion=26`, `targetSdkVersion=35`, 1 exported Activity, 1 unexported Service).
     - Minimal valid `classes.dex` with 1 class (`org.anzu.test.MainActivity`) calling `Log.d` and declaring dummy strings.
     - `res/values/strings.xml` containing app name and 2 test string keys.
     - `lib/arm64-v8a/libtestnative.so`: Tiny valid 64-bit ELF shared object exporting `Java_org_anzu_test_MainActivity_stringFromJNI`.
2. `bundle_split.xapk`:
   - Valid ZIP container containing:
     - `manifest.json` referencing `base.apk` and `config.arm64_v8a.apk`.
     - `base.apk`: Base package with components and DEX.
     - `config.arm64_v8a.apk`: Configuration split containing `lib/arm64-v8a/libsplit.so`.
3. `crypto_vulnerable.apk`:
   - Valid APK containing:
     - Decompiled Java code referencing `Cipher.getInstance("AES/ECB/PKCS5Padding")`.
     - Static hardcoded key: `SecretKeySpec("0123456789ABCDEF".getBytes(), "AES")`.
     - Hardcoded Google API key: `AIzaSyD-x9SampleKeyForTestingPurpose123`.
     - `res/xml/network_security_config.xml` containing `<certificates src="user" />` and `cleartextTrafficPermitted="true"`.
4. `malformed_zip_slip.apk`:
   - Test archive containing an entry named `../../etc/passwd` to verify zip slip rejection.
5. `high_entropy_packed.apk`:
   - Test APK containing a native binary with high-entropy randomized byte sequences ($> 7.5$) and `libsecexe.so` name to verify packer detection.

### 2. Unit & Integration Tests (`tests/test_rfc0207_apk_sidecar.py`)

- **`test_toolchain_readiness_static`**:
  - Tests `readiness_static()` when JDK, JADX, and apktool are present (`"ready"`).
  - Tests missing `apktool.jar` returning `"needs_repair"` with specific missing tool.
  - Verifies that lack of emulator/AVD does **not** fail static readiness.
- **`test_ingest_standalone_apk`**:
  - Prepares `minimal_valid.apk`.
  - Verifies hash calculation, workspace creation, and evidence generation.
- **`test_ingest_xapk_and_split_resolution`**:
  - Unpacks `bundle_split.xapk`.
  - Verifies that `base.apk` and split config are correctly associated and native libraries across splits are inventoried.
- **`test_zip_slip_and_bounds_enforcement`**:
  - Attempts to unpack `malformed_zip_slip.apk`.
  - Verifies immediate `ValueError` and confirms no files were written outside the workspace.
- **`test_manifest_component_attack_surface`**:
  - Runs manifest extraction on `minimal_valid.apk`.
  - Asserts correct package name, SDK limits, exported Activity, unexported Service, and attack surface count.
- **`test_native_so_inventory_and_jni_symbols`**:
  - Tests ELF parser against `libtestnative.so`.
  - Verifies extraction of ABI (`arm64-v8a`), ELF class, and JNI function `Java_org_anzu_test_MainActivity_stringFromJNI`.
- **`test_string_and_endpoint_extraction`**:
  - Verifies regex extraction of HTTP/HTTPS URLs, WebSockets, and custom schemes while filtering standard Android schema namespaces.
- **`test_crypto_hints_and_network_security`**:
  - Runs extraction on `crypto_vulnerable.apk`.
  - Asserts detection of AES/ECB mode, hardcoded secret key, Google API key pattern, and user CA trust anchors.
- **`test_custody_and_evidence_generation`**:
  - Verifies generation of `custody.json` and discrete evidence records `E00001` through `E00006`.
  - Asserts that report synthesis generates findings citing these evidence IDs.
- **`test_decompile_timeout_and_graceful_degradation`**:
  - Mocks subprocess timeout during JADX execution.
  - Verifies clean process termination, status transition to `partial`, and explicit declaration of timeout in `unknowns`.

---

## Acceptance Criteria

- [ ] Static toolchain readiness (`readiness_static()`) validates JDK 21, JADX 1.5.6, and apktool 2.10.0 independently of emulator/AVD status.
- [ ] Ingestion accepts standalone APKs, XAPK containers, and split APK sets, enforcing 8 GiB size and 50,000 file caps.
- [ ] Zip slip, path traversal, and symlink escape attempts are rejected fail-closed with `ValueError`.
- [ ] Decompile pipeline orchestrates `apktool` for resources/manifest and `jadx` for DEX bytecode.
- [ ] Manifest parser extracts package metadata, SDK boundaries, application flags, declared/requested permissions, and exported component attack surfaces.
- [ ] Native `.so` inventory correctly identifies ABIs, ELF headers, dynamic dependencies, exported JNI functions, and flags high entropy / known packer signatures.
- [ ] Endpoint engine extracts URLs, IPs, WebSockets, and cloud endpoints while filtering XML namespace noise.
- [ ] Crypto scanner detects hardcoded keys, weak ciphers (AES/ECB, DES), static IVs, and evaluates network security configs (cleartext, user trust anchors).
- [ ] Results write discrete citable evidence records (`E00001`-`E00006`) and immutable chain of custody (`custody.json`) to the investigation evidence store.
- [ ] Subprocess timeouts and memory limits are enforced with clean process tree termination and explicit recording of unknowns.
- [ ] All new synthetic fixture unit tests pass in `python3 -m pytest tests/test_rfc0207_*.py`.
- [ ] Full pytest suite passes without regressions.

---

## Likely Files

| Area | Paths |
| --- | --- |
| **Backend Core** | `backend/app/reverse_engineering/apk.py` (new sidecar module), `backend/app/reverse_engineering/android.py` (readiness split), `backend/app/reverse_engineering/runtime.py` (tool catalog registration), `backend/app/reverse_engineering/engine-lock.json` (apktool pin) |
| **Backend API** | `backend/app/api/investigations.py` (APK prepare/decompile/metadata endpoints) |
| **Setup & Scripting** | `backend/app/reverse_engineering/setup-engine.sh` (apktool jar placement) |
| **Tests & Fixtures** | `tests/test_rfc0207_apk_sidecar.py`, `tests/fixtures/apk/*` |
| **Docs** | `docs/rfcs/0207-apk-reverse-sidecar.md` |

---

## Out of Scope

- Dynamic instrumentation or live Frida hooking (deferred to RE Phase 2 / dynamic runtime RFC).
- Live Android emulator UI scenario execution (remains under RFC-0201 `android_capture`).
- Automatic binary patching, repackaging, or re-signing.
- Cloud-hosted reverse engineering or artifact uploads (strictly local-first).
- iOS IPA sidecar analysis (separate spec).

---

## Notes

- Upstream apktool: [iBotPeaches/Apktool](https://github.com/iBotPeaches/Apktool) (Apache 2.0).
- Upstream jadx: [skylot/jadx](https://github.com/skylot/jadx) (Apache 2.0).
- Cloud Linux agents can execute all static analysis unit tests using synthetic fixtures; live physical device ADB pulls remain desktop sign-off.
