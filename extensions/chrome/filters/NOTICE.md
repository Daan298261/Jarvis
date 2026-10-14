# EasyList ad-server domain rules

`easylist-domains.json` is derived from the EasyList authors' ad-server list, licensed under Creative Commons Attribution-ShareAlike 3.0. Attribution: **The EasyList authors (https://easylist.to/)**. The JSON records the exact source commit, checksum, license, and transformation. This derived data remains under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/legalcode).

ANZU extracts plain domain rules and preserves the `third-party` restriction. Expressions requiring other ABP options, regexes, cosmetic filtering, or scriptlets are omitted rather than approximated. This provides a maintained domain list, not full EasyList syntax support. Refresh with `python scripts/update-chrome-ad-list.py`, review the diff, and rebuild the extension package.
