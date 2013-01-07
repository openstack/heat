#part-handler

import datetime


def list_types():
    return(["text/x-cfninitdata"])


def handle_part(data, ctype, filename, payload):
    if ctype == "__begin__":
        return
    if ctype == "__end__":
        return

    with open('/var/log/part-handler.log', 'a') as log:
        timestamp = datetime.datetime.now()
        log.write('%s filename:%s, ctype:%s\n' % (timestamp, filename, ctype))

    if ctype == 'text/x-cfninitdata':
        with open('/var/lib/cloud/data/%s' % filename, 'w') as f:
            f.write(payload)
