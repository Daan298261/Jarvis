#!/usr/bin/env bash
set -euo pipefail
umask 077
mkdir -p /opt/anzu/{node,jdk,ghidra,jadx,rea,bin}
tar -xJf "$1" -C /opt/anzu/node --strip-components=1
tar -xzf "$2" -C /opt/anzu/jdk --strip-components=1
unzip -oq "$3" -d /opt/anzu/ghidra
unzip -oq "$4" -d /opt/anzu/jadx
export PATH=/opt/anzu/node/bin:/opt/anzu/jdk/bin:$PATH
export JAVA_HOME=/opt/anzu/jdk
cd /opt/anzu/rea
printf '%s\n' '{"name":"anzu-rea-engine","private":true,"dependencies":{"rea-agents":"3.2.1"}}' > package.json
cp "$5" package-lock.json
npm ci --ignore-scripts --no-audit --no-fund
node -e 'const l=require("./package-lock.json");if(l.packages["node_modules/rea-agents"].integrity!=="sha512-R+EwNkWiZjJi4cAxnQzwnCC5w+b4GlZoSJ5VNjliyLB4OoDsJyUngJleLuxgtoyyxHF9DFZ5x+JMQags+INPKw==")process.exit(1)'
cat > /opt/anzu/bin/rea <<'EOF'
#!/usr/bin/env bash
export PATH=/opt/anzu/node/bin:/opt/anzu/jdk/bin:$PATH
export JAVA_HOME=/opt/anzu/jdk
export GHIDRA_INSTALL_DIR=/opt/anzu/ghidra/ghidra_12.1.4_PUBLIC
export REA_ANALYSIS_PROVIDER=ghidra
exec /opt/anzu/node/bin/node /opt/anzu/rea/node_modules/rea-agents/scripts/rea.mjs "$@"
EOF
chmod 700 /opt/anzu/bin/rea
/opt/anzu/bin/rea --version
