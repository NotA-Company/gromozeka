#!/bin/sh
# Single source of truth for the Gromozeka CI pipeline's in-container script.
#
# Invoked from two contexts, BOTH of which already provide a fresh
# docker.io/library/alpine:3.24 container with the repo present as the working
# directory (so `make`, `./venv/...`, and `scripts/ci.sh` all resolve from cwd):
#   1. .sourcecraft/ci.yaml  — sourcecraft runs the cube (image + checkout) and
#      calls this script as its sole script step.
#   2. Makefile `make ci`    — `docker run` from the host stages the repo into a
#      container-local /app (read-only bind mount + copy) and then runs this script.
#
# `set -eu` preserves the per-step abort-on-failure semantics that sourcecraft's
# previous multi-entry `script:` list provided: the first failing command exits
# non-zero and fails the whole run. Do not remove it.
set -eux

apk add --no-cache gcc git libmagic make musl-dev nodejs py3-pip python3 sqlite tzdata py3-onnxruntime
make venv-alpine
make install
./venv/bin/pip install --ignore-installed packaging
make check
make test
