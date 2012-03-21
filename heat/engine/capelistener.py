# vim: tabstop=4 shiftwidth=4 softtabstop=4

#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import errno
import eventlet
from eventlet.green import socket
import fcntl
import libxml2
import logging
import os
import stat
from heat.engine import simpledb


logger = logging.getLogger('heat.engine.capelistener')

class CapeEventListener(object):

    def __init__(self):
        self.backlog = 50
        self.file = 'pacemaker-cloud-cped'

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        flags = fcntl.fcntl(sock, fcntl.F_GETFD)
        fcntl.fcntl(sock, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            st = os.stat(self.file)
        except OSError, err:
            if err.errno != errno.ENOENT:
                raise
        else:
            if stat.S_ISSOCK(st.st_mode):
                os.remove(self.file)
            else:
                raise ValueError("File %s exists and is not a socket",
                                 self.file)
        sock.bind(self.file)
        sock.listen(self.backlog)
        os.chmod(self.file, 0600)

        eventlet.spawn_n(self.cape_event_listner, sock)

    def cape_event_listner(self, sock):
        eventlet.serve(sock, self.cape_event_handle)

    def store(self, xml_event):

        try:
            doc = libxml2.parseDoc(xml_event)
        except:
            return

        event = {'EventId': ''}
        root = doc.getRootElement()
        child = root.children
        while child is not None:
            if child.type != "element":
                child = child.next
            elif child.name == 'event':
                child = child.children
            elif child.name == 'application':
                event['StackId'] = child.prop('name')
                event['StackName'] = child.prop('name')
                child = child.children
            elif child.name == 'node':
                event['ResourceType'] = 'AWS::EC2::Instance'
                event['LogicalResourceId'] = child.prop('name')
                child = child.children
            elif child.name == 'resource':
                event['ResourceType'] = 'ORG::HA::Service'
                event['LogicalResourceId'] = child.prop('name')
                child = child.children
            elif child.name == 'state':
                event['ResourceStatus'] = child.content
                child = child.next
            elif child.name == 'reason':
                event['ResourceStatusReason'] = child.content
                child = child.next
            else:
                child = child.next

        simpledb.event_append(event)
        doc.freeDoc()

    def cape_event_handle(self, sock, client_addr):
        while True:
            x = sock.recv(4096)
            self.store(x.strip('\n'))
            if not x: break

