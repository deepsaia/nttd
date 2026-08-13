# nttd with a working OpenTTD inside it, so a contestant can run a benchmark without
# installing a game and without their score depending on which OpenTTD their distribution
# happens to ship. That last part is the real reason this exists: no distribution packages
# 15.3, and OpenTTD refuses a savegame written by a newer version, so a mismatched build does
# not merely behave differently, it cannot read the artefacts a submission is made of.
#
#   docker build -t nttd .
#   docker run --rm -p 8000:8000 -v nttd-data:/data nttd
#
# On Apple Silicon add --platform linux/amd64: OpenTTD publishes no linux-generic arm64 build,
# so the game runs under emulation.

FROM python:3.13-slim-trixie AS openttd

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates curl unzip xz-utils \
    && rm -rf /var/lib/apt/lists/*

# The versions and their checksums live in the script, not here, so CI and the leaderboard's
# verifier install the same game this image does from one set of pins.
COPY scripts/install_openttd.sh /tmp/install_openttd.sh
RUN NTTD_OPENTTD_LINK_DIR= bash /tmp/install_openttd.sh /opt/openttd


FROM python:3.13-slim-trixie

# The shared libraries the generic build links against. It is not static, and without these
# the executable is present and unrunnable, which is a worse failure than being absent.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
       libfontconfig1 libfreetype6 liblzma5 liblzo2-2 libpng16-16 zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=openttd /opt/openttd /opt/openttd

# On PATH, with no NTTD_OPENTTD_BINARY set, so the container exercises the same lookup a Linux
# user gets rather than a special case that only works here.
RUN ln -s /opt/openttd/openttd /usr/local/bin/openttd

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies before source, so editing nttd does not re-resolve the environment.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    NTTD_SESSIONS_DIR=/data/sessions

# Recorded runs outlive the container: a session is the artefact a submission is built from.
VOLUME ["/data"]
EXPOSE 8000

# Bound to all interfaces because the point of the container is to be reached from outside it.
CMD ["nttd", "server", "--host", "0.0.0.0", "--port", "8000"]
