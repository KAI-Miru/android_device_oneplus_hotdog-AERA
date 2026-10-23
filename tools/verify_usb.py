"""Check MTP+ADB FunctionFS handoff and exclusive minadbd sideload ownership."""
import shlex


def verify_usb_configuration(script):
    rules = {}
    trigger = None
    for line in script.decode('utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('on '):
            trigger = line[3:]
            # Init executes every matching action, including repeated triggers.
            rules.setdefault(trigger, [])
        elif trigger:
            rules[trigger].append(shlex.split(line))
    ready = ('property:sys.usb.config=mtp,adb && property:sys.usb.ffs.ready=1 && '
             'property:sys.usb.ffs.mtp.ready=1 && property:sys.usb.configfs=1')
    for condition, values in rules.items():
        for args in values:
            starts_adbd = (args[:2] in (['start', 'adbd'], ['restart', 'adbd'],
                                        ['exec_start', 'adbd']) or
                           args in (['setprop', 'ctl.start', 'adbd'],
                                    ['setprop', 'ctl.restart', 'adbd']))
            profiles = {'property:sys.usb.config=adb',
                        'property:sys.usb.config=mtp,adb'}
            if starts_adbd and not profiles.intersection(condition.split(' && ')):
                raise ValueError('Normal adbd requires an explicit adb or mtp,adb '
                                 'profile; sideload belongs to minadbd')
        if any(args[:2] == ['write', '/config/usb_gadget/g1/UDC'] and
               args[2] != 'none' for args in values) and 'sys.usb.config=mtp' in condition:
            required = {'property:sys.usb.ffs.mtp.ready=1'}
            if 'property:sys.usb.config=mtp,adb' in condition:
                required.add('property:sys.usb.ffs.ready=1')
            if not required <= set(condition.split(' && ')):
                raise ValueError('MTP USB profiles must wait for every FunctionFS descriptor')
            if ['write', '/config/usb_gadget/g1/UDC', 'none'] in values:
                raise ValueError('The ready handler must not invalidate FunctionFS by detaching USB')
    commands = rules.get(ready, [])
    base = '/config/usb_gadget/g1'
    writes = {args[1]: args[2] for args in commands if args[0] == 'write'}
    try:
        identity = (int(writes[base + '/idVendor'], 16), int(writes[base + '/idProduct'], 16))
    except (KeyError, ValueError) as error:
        raise ValueError('MTP+ADB must explicitly select its USB identity') from error
    if identity != (0x18d1, 0x4ee2):
        raise ValueError('MTP+ADB must pair the Google VID with the native Google product ID')
    start = rules.get('property:sys.usb.config=mtp,adb && property:sys.usb.configfs=1', [])
    if ['start', 'adbd'] not in start:
        raise ValueError('MTP+ADB must start adbd before waiting for FunctionFS readiness')
    links = {args[2]: args[1] for args in commands if args[0] == 'symlink'}
    if links.get(base + '/configs/b.1/f1') != base + '/functions/ffs.mtp' or \
       links.get(base + '/configs/b.1/f2') != base + '/functions/ffs.adb':
        raise ValueError('MTP+ADB must preserve both FunctionFS interfaces')
    detach = ['write', base + '/UDC', 'none']
    bind = ['write', base + '/UDC', '${sys.usb.controller}']
    if bind not in commands or commands[-1] != ['setprop', 'sys.usb.state', '${sys.usb.config}']:
        raise ValueError('MTP+ADB must bind before publishing its USB state')
    if detach in commands or any(commands.index(args) > commands.index(bind)
                                 for args in commands if args[0] == 'symlink'):
        raise ValueError('MTP+ADB must link ready functions before binding without a second detach')
    if any(args[:3] == ['mount', 'functionfs', 'adb'] for values in rules.values() for args in values):
        raise ValueError('The device extension must leave the ADB FunctionFS mount to native init')
    return {'mtp_adb_vid': '18d1', 'mtp_adb_pid': '4ee2', 'adb_function_preserved': True}
