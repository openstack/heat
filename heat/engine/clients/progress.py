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


class UpdateProgressBase(object):
    """Keeps track on particular server update task.

    ``handler`` is a method of client plugin performing
    required update operation.
    Its first positional argument must be ``resource_id``
    and this method must be resilent to intermittent failures,
    returning ``True`` if API was successfully called, ``False`` otherwise.

    If result of API call is asynchronous, client plugin must have
    corresponding ``check_<handler>`` method.
    Its first positional argument must be ``resource_id``
    and it must return ``True`` or ``False`` indicating completeness
    of the update operation.

    For synchronous API calls,
    set ``complete`` attribute of this object to ``True``.

    ``[handler|checker]_extra`` arguments, if passed to constructor,
    should be dictionaries of

      {'args': tuple(), 'kwargs': dict()}

    structure and contain parameters with which corresponding ``handler`` and
    ``check_<handler>`` methods of client plugin must be called.
    ``args`` is automatically prepended with ``resource_id``.
    Missing ``args`` or ``kwargs`` are interpreted
    as empty tuple/dict respectively.
    Defaults are interpreted as both ``args`` and ``kwargs`` being empty.
    """
    def __init__(self, resource_id, handler, complete=False, called=False,
                 handler_extra=None, checker_extra=None):
        self.complete = complete
        self.called = called
        self.handler = handler
        self.checker = 'check_%s' % handler

        # set call arguments basing on incomplete values and defaults
        hargs = handler_extra or {}
        self.handler_args = (resource_id,) + (hargs.get('args') or ())
        self.handler_kwargs = hargs.get('kwargs') or {}

        cargs = checker_extra or {}
        self.checker_args = (resource_id,) + (cargs.get('args') or ())
        self.checker_kwargs = cargs.get('kwargs') or {}


class ServerUpdateProgress(UpdateProgressBase):
    def __init__(self, server_id, handler, complete=False, called=False,
                 handler_extra=None, checker_extra=None):
        super(ServerUpdateProgress, self).__init__(
            server_id, handler, complete=complete, called=called,
            handler_extra=handler_extra, checker_extra=checker_extra)
        self.server_id = server_id


class ContainerUpdateProgress(UpdateProgressBase):
    def __init__(self, container_id, handler, complete=False, called=False,
                 handler_extra=None, checker_extra=None):
        super(ContainerUpdateProgress, self).__init__(
            container_id, handler, complete=complete, called=called,
            handler_extra=handler_extra, checker_extra=checker_extra)
        self.container_id = container_id


class ServerDeleteProgress(object):

    def __init__(self, server_id, image_id=None, image_complete=True):
        self.server_id = server_id
        self.image_id = image_id
        self.image_complete = image_complete


class VolumeDetachProgress(object):
    def __init__(self, srv_id, vol_id, attach_id, task_complete=False):
        self.called = task_complete
        self.cinder_complete = task_complete
        self.nova_complete = task_complete
        self.srv_id = srv_id
        self.vol_id = vol_id
        self.attach_id = attach_id


class VolumeAttachProgress(object):
    def __init__(self, srv_id, vol_id, device, task_complete=False):
        self.called = task_complete
        self.complete = task_complete
        self.srv_id = srv_id
        self.vol_id = vol_id
        self.device = device


class VolumeDeleteProgress(object):
    def __init__(self, task_complete=False):
        self.backup = {'called': task_complete,
                       'complete': task_complete}
        self.delete = {'called': task_complete,
                       'complete': task_complete}
        self.backup_id = None


class VolumeResizeProgress(object):
    def __init__(self, task_complete=False, size=None):
        self.called = task_complete
        self.complete = task_complete
        self.size = size


class VolumeUpdateAccessModeProgress(object):
    def __init__(self, task_complete=False, read_only=None):
        self.called = task_complete
        self.read_only = read_only


class VolumeBackupRestoreProgress(object):
    def __init__(self, vol_id, backup_id):
        self.called = False
        self.complete = False
        self.vol_id = vol_id
        self.backup_id = backup_id


class PoolDeleteProgress(object):
    def __init__(self, task_complete=False):
        self.pool = {'delete_called': task_complete,
                     'deleted': task_complete}
        self.vip = {'delete_called': task_complete,
                    'deleted': task_complete}
