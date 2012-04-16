#part-handler


def list_types():
    return(["text/x-cfninitdata"])


def handle_part(data, ctype, filename, payload):
    if ctype == "__begin__":
        return
    if ctype == "__end__":
        return

    if ctype == 'text/x-cfninitdata':
        f = open('/var/lib/cloud/data/%s' % filename, 'w')
        f.write(payload)
        f.close()
