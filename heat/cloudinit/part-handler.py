#part-handler

import datetime
import errno
import os


def list_types():
    return(["text/x-cfninitdata"])


def handle_part(data, ctype, filename, payload):
    if ctype == "__begin__":
        try:
            os.makedirs('/var/lib/heat-cfntools', 0o700)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
        return

    if ctype == "__end__":
        return

    with open('/var/log/part-handler.log', 'a') as log:
        timestamp = datetime.datetime.now()
        log.write('%s filename:%s, ctype:%s\n' % (timestamp, filename, ctype))

    if ctype == 'text/x-cfninitdata':
        with open('/var/lib/heat-cfntools/%s' % filename, 'w') as f:
            f.write(payload)

        # TODO(sdake) hopefully temporary until users move to heat-cfntools-1.3
        with open('/var/lib/cloud/data/%s' % filename, 'w') as f:
            f.write(payload)
