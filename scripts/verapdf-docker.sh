#!/usr/bin/env bash
# veraPDF CLI (PDF/A validator) in Docker, pinned by version and image digest (plan §5: the verapdf/cli image).
# Runs veraPDF in the current directory, mounted read-only at the image's working directory /data, so file
# arguments must be paths relative to it. Point EUINVOICE_VERAPDF at this script to let `make conformance` run
# tests/conformance/test_facturx_verapdf.py without a local Java install; CI does that in the conformance job.
#
# Usage: scripts/verapdf-docker.sh [veraPDF options] FILE...
# Bump: pick the tag at hub.docker.com/r/verapdf/cli, then pin the digest that `docker pull` prints.

set -euo pipefail

IMAGE="verapdf/cli:v1.30.2@sha256:d5ee329657cf9bc4b2400392dd54c7d0a0ce9980ff6fa2da5590eebeec007cdb"

exec docker run --rm --platform linux/amd64 --network none -v "$PWD:/data:ro" "$IMAGE" "$@"
