#!/usr/bin/env bash
# veraPDF CLI (PDF/A validator) in Docker, pinned by version and image digest (plan §5: the verapdf/cli image).
# Runs veraPDF on the current directory, mounted read-only at /data, so file
# arguments must be relative paths inside it. Point EUINVOICE_VERAPDF at this script to let `make conformance` run
# tests/conformance/test_facturx_verapdf.py without a local Java install (CI wiring: #25).
#
# Usage: scripts/verapdf-docker.sh [veraPDF options] FILE...
# Bump: pick the tag at hub.docker.com/r/verapdf/cli, then pin the digest that `docker pull` prints.

set -euo pipefail

IMAGE="verapdf/cli:v1.30.2@sha256:d5ee329657cf9bc4b2400392dd54c7d0a0ce9980ff6fa2da5590eebeec007cdb"

# The image's launcher does not run veraPDF in /data (on GitHub runners relative paths resolved against
# /tmp/hsperfdata_verapdf), so every argument naming a file here becomes an absolute /data path.
args=()
for arg in "$@"; do
    if [[ "$arg" != /* && -f "$arg" ]]; then
        args+=("/data/$arg")
    else
        args+=("$arg")
    fi
done

# Run as the calling user: the image's own user (uid 100) cannot read a 0700 directory such as pytest's tmp_path on a
# Linux host (on the GitHub runner veraPDF reported every file as missing). Docker Desktop hides this on macOS.
exec docker run --rm --platform linux/amd64 --network none --user "$(id -u):$(id -g)" -v "$PWD:/data:ro" "$IMAGE" "${args[@]}"
