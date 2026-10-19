# Hotdog build runners

Device configuration is on `main`. This branch keeps GitHub workflows, source
checkout tools and private checkpoint handling separate from device history.
Both checkouts are resolved to exact commits before assembly and recorded in
the build diagnostics.

The product is `twrp_hotdog-bp2a-eng`, the build target is `recoveryimage`, and
the output is `AERA-hotdog-ALPHA-recovery.img`. A kernel Image is supplied by
HTTPS URL and SHA256 or as a local external input. The intended input is the
universal Miru CI59 Image and matching WLAN module used by guacamole.

The first Hotdog build uses fresh preparation. This repository does not select
an existing guacamole checkpoint or grant compatibility to its legacy caches.
Future Hotdog checkpoints must use a private GHCR package and an immutable
digest; the workflows verify package visibility and source/toolchain inputs.
Credentials are excluded from exported checkpoint runtimes.

Recovery is built directly from the exact `miru` commit in `sources.lock.json`.
Only the recorded host memory and build-configuration patches are applied;
recovery source is not patched during builds. A compatible compiled checkpoint
retains ARM64 objects and Ninja state so later changes can rebuild affected
outputs. Diagnostics must establish actual reuse before it is reported.

Pushes to `ci-runner` validate both runner and device inputs. Image builds and
checkpoint publication require a manual workflow dispatch. A passing build
still needs Hotdog hardware testing.
