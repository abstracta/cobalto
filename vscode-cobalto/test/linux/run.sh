#!/bin/sh
# Linux (Docker) verification of the DAP proxy of the Cobalto extension.
#
# Builds the image from test/linux/Dockerfile, copies the example project
# examples/ and the CLI package src/ to a work directory (so that the Linux
# build/ does not overwrite the host's), mounts the compiled extension (out/
# and package.json) and runs inside the container, in this order:
#   1. cobalto test --coverage      (every suite)
#   2. cobalto debug --suite TSTINV (compiles with -g)
#   3. node out/test/verify-dap.js /work/examples TSTINV   (DAP client over stdio)
# The CLI runs from the copied package (python3 -m cobalto), not installed.
#
# Usage: test/linux/run.sh [work directory]
#   The extension must be compiled first (npm run compile) on the host.
#   Variables: COBALTO_IMAGE (name of the image, cobalto-linux-verify by
#   default) and COBALTO_SUITE (TSTINV by default).
#
# License: Apache-2.0 (the project's).

set -eu

here=$(cd "$(dirname "$0")" && pwd)
ext=$(cd "$here/../.." && pwd)
repo=$(cd "$ext/.." && pwd)
image=${COBALTO_IMAGE:-cobalto-linux-verify}
suite=${COBALTO_SUITE:-TSTINV}
work=${1:-$(mktemp -d)}

if [ ! -f "$ext/out/test/verify-dap.js" ]; then
    echo "$ext/out/test/verify-dap.js is missing: compile the extension first (npm run compile)" >&2
    exit 2
fi

echo "image: $image"
docker build -t "$image" -f "$here/Dockerfile" "$here"

echo "work directory: $work"
mkdir -p "$work"
rm -rf "$work/examples" "$work/src"
cp -R "$repo/examples" "$work/examples"
rm -rf "$work/examples/build"
cp -R "$repo/src" "$work/src"

mkdir -p "$work/vscode-cobalto"
rm -rf "$work/vscode-cobalto/out"
cp -R "$ext/out" "$work/vscode-cobalto/out"
cp "$ext/package.json" "$work/vscode-cobalto/package.json"

# SYS_PTRACE and unconfined seccomp: lldb needs ptrace on the debugged
# process.
docker run --rm \
    --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
    -v "$work:/work" \
    -e COBALTO_SUITE="$suite" \
    "$image" /bin/bash -c '
set -e
echo "== versions"
cobc --version | head -1
lldb-18 --version | head -1
node --version
python3 --version
export PYTHONPATH=/work/src
echo "== 1. cobalto test --coverage"
cd /work/examples && python3 -m cobalto test --coverage || true
echo "== 2. cobalto debug --suite $COBALTO_SUITE"
cd /work/examples && python3 -m cobalto debug --suite "$COBALTO_SUITE"
echo "== 3. verify-dap"
node /work/vscode-cobalto/out/test/verify-dap.js /work/examples "$COBALTO_SUITE"
'
