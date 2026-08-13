#!/usr/bin/env bash
# Install the exact OpenTTD nttd is written against, on Linux.
#
# Why not the distro package. nttd targets OpenTTD 15.3, and several load-bearing behaviours
# were established by measurement against it: the admin protocol's packet limit, the pause
# level at which a command is still served, the absence of any speed multiplier. No
# distribution ships it. Checked at the time of writing:
#
#   Ubuntu noble (ubuntu-latest)  13.4      Debian trixie  14.1
#   Ubuntu plucky                 14.1      Debian sid     15.1
#
# That is not a cosmetic difference. OpenTTD refuses a savegame written by a newer version, so
# a runner with 13.4 cannot replay a 15.3 save at all, and the leaderboard's nightly verifier
# was installing 13.4 by way of apt.
#
# OpenGFX is a separate download because the release tarball ships the baseset metadata but not
# the graphics. Without it OpenTTD has no base graphics set and will not start, even under -D
# where nothing is ever drawn.
#
# Both downloads are pinned by checksum, so an upstream replacement fails here rather than
# quietly changing the environment a score was produced in. This file is the only place those
# pins live; the Dockerfile calls it rather than repeating them.
#
#   ./scripts/install_openttd.sh                  # into /opt/openttd, linked into /usr/local/bin
#   ./scripts/install_openttd.sh /tmp/ottd        # into a prefix of your choosing
#   NTTD_OPENTTD_LINK_DIR=~/.local/bin ./scripts/install_openttd.sh ~/ottd

set -euo pipefail

OPENTTD_VERSION="${OPENTTD_VERSION:-15.3}"
OPENTTD_SHA256="${OPENTTD_SHA256:-f49eb25d61b00f8f4d332fee02b530ad75552d1efb8f2bb01e7ca5e6540fe059}"
OPENGFX_VERSION="${OPENGFX_VERSION:-8.0}"
OPENGFX_SHA256="${OPENGFX_SHA256:-43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be}"

PREFIX="${1:-/opt/openttd}"
LINK_DIR="${NTTD_OPENTTD_LINK_DIR:-/usr/local/bin}"

# OpenTTD publishes no linux-generic arm64 build, so this is amd64 only. An arm64 machine
# needs either emulation or a source build, and saying so beats a confusing tar failure.
OPENTTD_ARCHIVE="openttd-${OPENTTD_VERSION}-linux-generic-amd64.tar.xz"
OPENTTD_URL="https://cdn.openttd.org/openttd-releases/${OPENTTD_VERSION}/${OPENTTD_ARCHIVE}"
OPENGFX_ARCHIVE="opengfx-${OPENGFX_VERSION}-all.zip"
OPENGFX_URL="https://cdn.openttd.org/opengfx-releases/${OPENGFX_VERSION}/${OPENGFX_ARCHIVE}"

# sha256sum on Linux, shasum on macOS. Named here so the failure is about a missing tool
# rather than an empty digest that then compares equal to nothing.
if command -v sha256sum > /dev/null 2>&1; then
    sha256_of() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum > /dev/null 2>&1; then
    sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }
else
    echo "Error: neither sha256sum nor shasum is available, so downloads cannot be verified." >&2
    exit 1
fi

verify() {
    local file="$1" expected="$2" actual
    actual="$(sha256_of "$file")"
    if [ "$actual" != "$expected" ]; then
        echo "Error: checksum mismatch for $file" >&2
        echo "  expected $expected" >&2
        echo "  actual   $actual" >&2
        exit 1
    fi
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Downloading OpenTTD ${OPENTTD_VERSION}"
curl -fsSL -o "$work/$OPENTTD_ARCHIVE" "$OPENTTD_URL"
verify "$work/$OPENTTD_ARCHIVE" "$OPENTTD_SHA256"

echo "Downloading OpenGFX ${OPENGFX_VERSION}"
curl -fsSL -o "$work/$OPENGFX_ARCHIVE" "$OPENGFX_URL"
verify "$work/$OPENGFX_ARCHIVE" "$OPENGFX_SHA256"

echo "Installing into ${PREFIX}"
mkdir -p "$PREFIX"
tar -xJf "$work/$OPENTTD_ARCHIVE" -C "$work"
# --strip-components would flatten the versioned top directory, but naming it explicitly
# means a changed archive layout fails loudly instead of scattering files into the prefix.
cp -R "$work/openttd-${OPENTTD_VERSION}-linux-generic-amd64/." "$PREFIX/"

unzip -q -o "$work/$OPENGFX_ARCHIVE" -d "$work"
tar -xf "$work/opengfx-${OPENGFX_VERSION}.tar" -C "$PREFIX/baseset"

if [ ! -x "$PREFIX/openttd" ]; then
    echo "Error: no openttd executable at $PREFIX/openttd after unpacking." >&2
    exit 1
fi

if [ -n "$LINK_DIR" ]; then
    mkdir -p "$LINK_DIR"
    ln -sf "$PREFIX/openttd" "$LINK_DIR/openttd"
    echo "Linked $LINK_DIR/openttd"
fi

# nttd finds this on PATH with no environment variable set, which is the lookup a Linux user
# gets. Printing the version proves the binary runs, not merely that it landed on disk: the
# generic build is dynamically linked and a missing library shows up only when it executes.
echo "Installed:"
"$PREFIX/openttd" --version 2>&1 | head -2 || {
    echo "Error: the executable is present but did not run. A shared library is likely missing." >&2
    exit 1
}
