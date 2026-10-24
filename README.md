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

## Kernel containers and WLAN compatibility

Kernel intake identifies ARM64 Image, gzip Image or boot-v2 payloads by content,
not archive or member names. A ZIP may contain one candidate payload or one
inner ZIP containing it. Multiple candidates, extra ZIP nesting, unsafe paths,
symlinks and oversized inputs are rejected. The exact caller-supplied kernel
SHA256 remains mandatory; ramdisks and device trees in containers are ignored.

WLAN startup reads `modinfo -F vermagic` from the actual bundled module and
compares its release with the running kernel before starting radio helpers.
Normal `insmod` retains the kernel's vermagic and symbol-version checks; modules
are never force-loaded. Rebuilding with a different kernel/module pair also
requires updating the module manifest and passing the existing image/ABI audits.
