# Hotdog build runners

Device configuration is on `main`. This branch keeps GitHub workflows, source
checkout tools and private checkpoint handling separate from device history.
Both checkouts are resolved to exact commits before assembly and recorded in
the build diagnostics.

The product is `twrp_hotdog-bp2a-eng`, the build target is `recoveryimage`, and
the output is `AERA-hotdog-ALPHA-recovery.img`. Builds verify the original F22
kernel, header, reference ramdisk and device trees bundled in the selected
device revision, with its matching F22 WLAN module. No external kernel URL,
caller checksum or kernel secret is needed. AERA generates its native ramdisk.

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

## Bundled input policy

Cold builds, preparation and prepared builds run the same bundled verifier.
Boot and WLAN module manifests are part of the prepared fingerprint. Old CI59
environments remain stored but are rejected for F22 builds; fresh preparation
is the default. There is no retained-image fallback. The archive selector remains
a standalone tested tool outside the production build path.

WLAN startup reads `modinfo -F vermagic` from the actual bundled module and
compares its release with the running kernel before starting radio helpers.
Normal `insmod` retains the kernel's vermagic and symbol-version checks; modules
are never force-loaded. Rebuilding with a different kernel/module pair also
requires updating the module manifest and passing the existing image/ABI audits.
