FROM ubuntu:22.04@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401 AS dependencies
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install --yes --no-install-recommends \
    bc binutils bison build-essential ca-certificates ccache curl flex \
    g++-multilib gcc-multilib git gnupg gperf libelf-dev liblz4-tool \
    libncurses-dev libssl-dev libxml2 libxml2-utils lzop python3 python3-pip python-is-python3 \
    rsync unzip util-linux procps xsltproc zip zlib1g-dev && \
    rm -rf /var/lib/apt/lists/* && \
    curl --fail --location --retry 3 https://storage.googleapis.com/git-repo-downloads/repo \
        -o /usr/local/bin/repo && chmod 0755 /usr/local/bin/repo
COPY tools/requirements.txt /tmp/aera-requirements.txt
RUN python -c 'import sys; assert sys.version_info.major == 3' && \
    python3 -m pip install --no-cache-dir -r /tmp/aera-requirements.txt && \
    rm /tmp/aera-requirements.txt

FROM dependencies AS compiled
COPY . /device-tree/
ARG DEVICE_REVISION
ARG ENVIRONMENT_FINGERPRINT
ENV AERA_SOURCE_DIR=/aera AERA_ARTIFACT_DIR=/artifacts BUILD_JOBS=4
# Keep only a compressed snapshot in the layer that performed the build.
# Copying two expanded source trees exhausts hosted-runner export space.
RUN AERA_DEVICE_REVISION="$DEVICE_REVISION" bash /device-tree/ci/warm-builder.sh && \
    bash /device-tree/ci/package-builder.sh

FROM dependencies AS prepared
ARG ENVIRONMENT_FINGERPRINT
ENV AERA_SOURCE_DIR=/aera AERA_ARTIFACT_DIR=/artifacts BUILD_JOBS=4
LABEL org.opencontainers.image.source="https://github.com/KAI-Miru/android_device_oneplus_hotdog-AERA"
LABEL org.opencontainers.image.description="Private hotdog AERA sources, toolchains, host tools and generated build graph"
LABEL org.aera.environment.fingerprint="${ENVIRONMENT_FINGERPRINT}"
COPY --from=compiled /device-tree/ /device-tree/
COPY --from=compiled /builder-archive/manifest.json /builder-archive/manifest.json
COPY --from=compiled /builder-archive/part00 /builder-archive/part00
COPY --from=compiled /builder-archive/part01 /builder-archive/part01
COPY --from=compiled /builder-archive/part02 /builder-archive/part02
COPY --from=compiled /builder-archive/part03 /builder-archive/part03
COPY --from=compiled /builder-archive/part04 /builder-archive/part04
COPY --from=compiled /builder-archive/part05 /builder-archive/part05
COPY --from=compiled /builder-archive/part06 /builder-archive/part06
COPY --from=compiled /builder-archive/part07 /builder-archive/part07
COPY --from=compiled /builder-archive/part08 /builder-archive/part08
COPY --from=compiled /builder-archive/part09 /builder-archive/part09
COPY --from=compiled /builder-archive/part10 /builder-archive/part10
COPY --from=compiled /builder-archive/part11 /builder-archive/part11
COPY --from=compiled /builder-archive/part12 /builder-archive/part12
COPY --from=compiled /builder-archive/part13 /builder-archive/part13
COPY --from=compiled /builder-archive/part14 /builder-archive/part14
COPY --from=compiled /builder-archive/part15 /builder-archive/part15
WORKDIR /device-tree
ENTRYPOINT ["bash", "/device-tree/ci/use-prepared.sh"]

FROM scratch AS artifacts
COPY --from=compiled /artifacts/ /
