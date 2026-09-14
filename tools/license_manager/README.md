# Jarvis License Manager (RFC-0087)
#
# Vendor-only. Run from the repo:
#   PYTHONPATH=backend python -m app.licensing.manager_app
#
# Signing private key and SQLite live in %LOCALAPPDATA%\Jarvis\license-issuer\
# (or $JARVIS_LICENSE_ISSUER_DIR). Never copy issuer.key into the customer
# installer. build-installer.ps1 places JarvisLicenseManager.exe beside
# JarvisSetup.exe in installer/windows/dist/ after iscc; Jarvis.iss does not
# include it.
