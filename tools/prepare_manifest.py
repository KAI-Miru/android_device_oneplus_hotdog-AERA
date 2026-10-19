#!/usr/bin/env python3
"""Write pinned project overrides for the existing AERA source manifest."""
from pathlib import Path
import argparse, json, xml.etree.ElementTree as ET

def write_manifest(destination):
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root/'sources.lock.json').read_text())
    manifest = ET.Element('manifest')
    # A prebuilt SM8150 kernel and Linux recovery build do not consume GKI,
    # macOS Bazel, or VNDK snapshots for other vendor releases.
    for path in ('kernel/prebuilts/6.1/arm64', 'kernel/prebuilts/6.6/arm64',
                 'kernel/prebuilts/6.12/arm64',
                 'kernel/prebuilts/common-modules/trusty/6.6/arm64',
                 'kernel/prebuilts/common-modules/trusty/6.12/arm64',
                 'prebuilts/bazel/darwin-x86_64',
                 'prebuilts/vndk/v31', 'prebuilts/vndk/v32',
                 'prebuilts/vndk/v33', 'prebuilts/vndk/v34'):
        ET.SubElement(manifest, 'remove-project', path=path)
    # Retain upstream Java and module SDK dependencies. Guava's host build uses
    # JDK 8 bootclasspath jars even though the active compiler is JDK 21.
    # repo reads its own remote configuration; Git's global insteadOf setting
    # is not consistently used during its preliminary revision probes.
    ET.SubElement(manifest, 'remote', name='hotdog-aera-https',
                  fetch='https://github.com/AERA-Recovery')
    ET.SubElement(manifest, 'remote', name='miru-https',
                  fetch='https://github.com/KAI-Miru')
    for p in lock['projects']:
        attributes = dict(name=p['name'], path=p['path'], revision=p['commit'])
        if p['remote'] == 'AERA':
            attributes['remote'] = 'hotdog-aera-https'
        elif p['remote'] == 'Miru':
            attributes['remote'] = 'miru-https'
        ET.SubElement(manifest, 'extend-project', **attributes)
    ET.indent(manifest)
    target = Path(destination); target.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(manifest).write(target, encoding='utf-8', xml_declaration=True)

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('destination')
    write_manifest(p.parse_args().destination)
