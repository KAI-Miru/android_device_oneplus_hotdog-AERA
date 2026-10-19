# Flatten the original builder's exact runtime after it has packed its sources
# and compiled outputs. No credentials are passed into that container.
FROM scratch
ADD runtime.tar /
ENV AERA_SOURCE_DIR=/aera AERA_ARTIFACT_DIR=/artifacts BUILD_JOBS=4
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV DEBIAN_FRONTEND=noninteractive
LABEL org.opencontainers.image.source="https://github.com/KAI-Miru/android_device_oneplus_hotdog-AERA"
LABEL org.opencontainers.image.description="Private AERA source and compiled checkpoint"
COPY manifest.json /builder-archive/manifest.json
COPY part00 /builder-archive/part00
COPY part01 /builder-archive/part01
COPY part02 /builder-archive/part02
COPY part03 /builder-archive/part03
COPY part04 /builder-archive/part04
COPY part05 /builder-archive/part05
COPY part06 /builder-archive/part06
COPY part07 /builder-archive/part07
COPY part08 /builder-archive/part08
COPY part09 /builder-archive/part09
COPY part10 /builder-archive/part10
COPY part11 /builder-archive/part11
COPY part12 /builder-archive/part12
COPY part13 /builder-archive/part13
COPY part14 /builder-archive/part14
COPY part15 /builder-archive/part15
WORKDIR /device-tree
ENTRYPOINT ["bash", "/device-tree/ci/use-prepared.sh"]
