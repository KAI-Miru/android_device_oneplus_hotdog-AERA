"""Keep auto-probed System mounts compatible with both ext4 and EROFS."""


def verify_system_mount_options(text):
    rows = [line.split() for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]
    system = [row for row in rows if row[1] in ('/', '/system', '/system_root')]
    if len(system) != 1 or system[0][3].split(',') != ['ro']:
        raise ValueError('Auto-probed System requires one filesystem-neutral read-only row')
    return {'system_mount_options': 'ro', 'filesystem_probe_keeps_ext4_options': False}
