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
import functools
import inspect
import six

from oslo_log import log as logging
from oslo_messaging import rpc

LOG = logging.getLogger(__name__)


def asynchronous(function):
    """Decorator for MessageProcessor methods to make them asynchronous.

    To use, simply call the method as usual. Instead of being executed
    immediately, it will be placed on the queue for the MessageProcessor and
    run on a future iteration of the event loop.
    """

    if six.PY2:
        arg_names = inspect.getargspec(function).args
    else:
        sig = inspect.signature(function)
        arg_names = [name for name, param in sig.parameters.items()
                     if param.kind == param.POSITIONAL_OR_KEYWORD]
    MessageData = collections.namedtuple(function.__name__, arg_names[1:])

    @functools.wraps(function)
    def call_or_send(processor, *args, **kwargs):
        if len(args) == 1 and not kwargs and isinstance(args[0], MessageData):
            try:
                return function(processor, **args[0]._asdict())
            except rpc.dispatcher.ExpectedException as exc:
                LOG.error('[%s] Exception in "%s": %s',
                          processor.name, function.__name__, exc.exc_info[1],
                          exc_info=exc.exc_info)
                raise
            except Exception as exc:
                LOG.exception('[%s] Exception in "%s": %s',
                              processor.name, function.__name__, exc)
                raise
        else:
            data = inspect.getcallargs(function, processor, *args, **kwargs)
            data.pop(arg_names[0])  # lose self
            return processor.queue.send(function.__name__,
                                        MessageData(**data))

    call_or_send.MessageData = MessageData
    return call_or_send


class MessageProcessor(object):

    queue = None

    def __init__(self, name):
        self.name = name

    def __call__(self):
        message = self.queue.get()
        if message is None:
            LOG.debug('[%s] No messages', self.name)
            return False

        try:
            method = getattr(self, message.name)
        except AttributeError:
            LOG.error('[%s] Bad message name "%s"' % (self.name,
                                                      message.name))
            raise
        else:
            LOG.info('[%s] %r' % (self.name, message.data))

        method(message.data)
        return True

    @asynchronous
    def noop(self, count=1):
        """Insert <count> No-op operations in the message queue."""
        assert isinstance(count, int)
        if count > 1:
            self.queue.send_priority('noop',
                                     self.noop.MessageData(count - 1))

    @asynchronous
    def _execute(self, func):
        """Insert a function call in the message queue.

        The function takes no arguments, so use functools.partial to curry the
        arguments before passing it here.
        """
        func()

    def call(self, func, *args, **kwargs):
        """Insert a function call in the message queue."""
        self._execute(functools.partial(func, *args, **kwargs))

    def clear(self):
        """Delete all the messages from the queue."""
        self.queue.clear()

__all__ = ['MessageProcessor', 'asynchronous']
