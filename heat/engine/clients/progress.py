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

"""Helper classes that are simple key-value storages
meant to be passed between handle_* and check_*_complete,
being mutated during subsequent check_*_complete calls.

Some of them impose restrictions on client plugin API, thus they are
put in this client-plugin-agnostic module.

"""


class ServerCreateProgress(object):
    def __init__(self, server_id, complete=False):
        self.complete = complete
        self.server_id = server_id


class ServerUpdateProgress(ServerCreateProgress):
    """Keeps track on particular server update task

    ``handler`` is a method of client plugin performing
    required update operation.
    It must accept ``server_id`` as first positional argument and
    be resilent to intermittent failures, returning ``True`` if
    API was successfully called, ``False`` otherwise.

    If result of API call is asyncronous, client plugin must have
    corresponding ``check_<handler>`` method
    accepting ``server_id`` as first positional argument and
    returning ``True`` or ``False``.

    For syncronous API calls,
    set ``complete`` attribute of this object to ``True``.

    ``*_extra`` arguments, if passed to constructor, should be dictionaries of

      {'args': tuple(), 'kwargs': dict()}

    structure and contain parameters with which corresponding ``handler`` and
    ``check_<handler>`` methods of client plugin must be called.
    (``args`` is automatically prepended with ``server_id``).
    Missing ``args`` or ``kwargs`` are interpreted
    as empty tuple/dict respectively.
    Defaults are interpreted as both ``args`` and ``kwargs`` being empty.


    """
    def __init__(self, server_id, handler, complete=False, called=False,
                 handler_extra=None, checker_extra=None):
        super(ServerUpdateProgress, self).__init__(server_id, complete)
        self.called = called
        self.handler = handler
        self.checker = 'check_%s' % handler

        # set call arguments basing on incomplete values and defaults
        hargs = handler_extra or {}
        self.handler_args = (server_id,) + (hargs.get('args') or ())
        self.handler_kwargs = hargs.get('kwargs') or {}

        cargs = checker_extra or {}
        self.checker_args = (server_id,) + (cargs.get('args') or ())
        self.checker_kwargs = cargs.get('kwargs') or {}


class ServerDeleteProgress(object):

    def __init__(self, server_id, image_id=None, image_complete=True):
        self.server_id = server_id
        self.image_id = image_id
        self.image_complete = image_complete
