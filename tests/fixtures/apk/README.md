Fixtures for tests/test_rfc0207_apk_sidecar.py.

- minimal_valid.apk: aapt2 35.0.0 `link` of minimal_valid.AndroidManifest.xml against android-35.
- libtestnative_arm64.so: NDK 27.0.12077973 `aarch64-linux-android26-clang -shared -fPIC -O2 -fstack-protector-all -Wl,-z,relro,-z,now -Wl,-soname,libtestnative.so -llog testnative.c` (full RELRO, stack canary, non-executable stack).
- libtestnative_armv7.so: NDK 27.0.12077973 `armv7a-linux-androideabi26-clang -shared -fPIC -O2 -fno-stack-protector -Wl,-z,relro -Wl,-z,lazy -Wl,-soname,libtestnative.so -llog testnative.c` (32-bit, partial RELRO, no canary).
