#!/usr/bin/python

import eventlet
from eventlet.green import socket
import libssh2
import os
import random


def monitor(hostname, username, id):

    print('%s %s %d' % (hostname, username, id))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((hostname, 22))

    session = libssh2.Session()
    started = False
    while not started:
        try:
            session.startup(sock)
            started = True
        except:
            eventlet.sleep(1)
    session.userauth_publickey_fromfile(
        username,
        os.path.expanduser('~/.ssh/id_rsa.pub'),
        os.path.expanduser('~/.ssh/id_rsa'),
        '')

    while True:
        sl = random.randint(1, 20)
        eventlet.sleep(sl)
        channel = session.channel()
        channel.execute('uname -a')

        stdout = []
        #stderr = []

        while not channel.eof:
            data = channel.read(1024)
            if data:
                stdout.append(data)

            #data = channel.read(1024, libssh2.STDERR)
            #if data:
            #    stderr.append(data)

        print('%d %d %s' % (id, sl, ''.join(stdout)))
        #print ''.join(stderr)


pool = eventlet.GreenPool()
i = 1
while True:
    pool.spawn_n(monitor, '192.168.122.238', 'root', i)
    i = i + 1
    if i > 800:
        break

pool.waitall()
