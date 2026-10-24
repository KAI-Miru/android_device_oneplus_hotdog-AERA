"""Require the stock AW8697 duration range used by recovery haptic sliders."""
import hashlib
import json
import stat
from pathlib import Path


def verify_haptic_source(source):
    required = {f'vendor/firmware/{duration}ms_RTP_{hz}Hz.bin'
                for duration in range(20, 501, 20) for hz in (166, 170, 174)}
    required |= {f'vendor/firmware/aw8697_haptic{suffix}.bin'
                 for suffix in ('', '_166', '_168', '_170', '_172', '_174')}
    required.add('vendor/firmware/aw8697_rtp.bin')
    if not required <= source['files'].keys():
        raise ValueError('Incomplete AW8697 slider duration or calibration firmware')


def haptic_inputs(dump, source):
    """Import each device's exact stock set; never substitute a port's effects."""
    dump = Path(dump)
    if dump.name != source['source_dump']:
        raise ValueError('Haptic firmware must come from ' + source['source_dump'])
    verify_haptic_source(source)
    result = {}
    for name, identity in source['files'].items():
        data = (dump / name).read_bytes()
        if len(data) != identity['bytes'] or hashlib.sha256(data).hexdigest() != identity['sha256']:
            raise ValueError('Haptic firmware identity differs: ' + name)
        result[name] = data
    return result


def verify_haptic_runtime(entries):
    source = json.loads(Path(__file__).with_name('haptic-source.json').read_text())
    verify_haptic_source(source)
    for name, identity in source['files'].items():
        if name not in entries or not stat.S_ISREG(entries[name][0]):
            raise ValueError(f'Missing regular haptic firmware: {name}')
        data = entries[name][1]
        if len(data) != identity['bytes'] or hashlib.sha256(data).hexdigest() != identity['sha256']:
            raise ValueError(f'Haptic firmware differs from stock: {name}')
    return {'source_dump': source['source_dump'], 'files': source['files'],
            'duration_range_ms': [20, 500], 'duration_step_ms': 20,
            'rtp_frequencies_hz': [166, 170, 174]}
