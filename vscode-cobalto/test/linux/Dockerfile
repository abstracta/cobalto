# Linux verification image for the DAP proxy of the Cobalto extension.
#
# It holds what the headless verification needs (README, "Verification"
# section): GnuCOBOL 3.x, lldb with lldb-dap, Python 3 and Node.js 18+.
# It includes nothing from the repository: the example project (examples/),
# the CLI package (src/) and the compiled extension (vscode-cobalto/out,
# package.json) are mounted when the container runs; see run.sh in this
# same folder.
#
# Direct use:
#   docker build -t cobalto-linux-verify -f test/linux/Dockerfile test/linux
#
# License: Apache-2.0 (the project's).

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# gnucobol3: GnuCOBOL 3.1.2 (Ubuntu's gnucobol4 package is an early version
# of 4.0 and not the stable branch). lldb-18 provides /usr/bin/lldb-dap-18.
# Ubuntu 24.04's nodejs is 18.19, enough for the extension (Node 18+).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ca-certificates \
        gcc \
        libc6-dev \
        gnucobol3 \
        lldb-18 \
        python3 \
        nodejs \
 && rm -rf /var/lib/apt/lists/*

# lldb-dap reachable under its generic name (find-lldb.ts also tries
# lldb-dap-18 on the PATH, but this way it works for any DAP client).
RUN ln -s /usr/bin/lldb-dap-18 /usr/local/bin/lldb-dap \
 && cobc --version | head -1 \
 && lldb-18 --version | head -1 \
 && node --version \
 && python3 --version

# Explicit path in case the generic name is not on the client's PATH.
ENV COBALTO_LLDB_DAP=/usr/bin/lldb-dap-18

# The example project and the extension are mounted here.
WORKDIR /work
CMD ["/bin/bash"]
