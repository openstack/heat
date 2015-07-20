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

import collections


Message = collections.namedtuple('Message', ['name', 'data'])


class MessageQueue(object):

    def __init__(self, name):
        self.name = name
        self._queue = collections.deque()

    def send(self, name, data=None):
        self._queue.append(Message(name, data))

    def send_priority(self, name, data=None):
        self._queue.appendleft(Message(name, data))

    def get(self):
        try:
            return self._queue.popleft()
        except IndexError:
            return None

    def clear(self):
        self._queue.clear()
