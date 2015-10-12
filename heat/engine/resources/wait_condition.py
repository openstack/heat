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

from oslo_log import log as logging
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LE
from heat.common.i18n import _LW
from heat.engine.resources import signal_responder

LOG = logging.getLogger(__name__)


class BaseWaitConditionHandle(signal_responder.SignalResponder):
    """Base WaitConditionHandle resource.

    The main point of this class is to :
    - have no dependencies (so the instance can reference it)
    - create credentials to allow for signalling from the instance.
    - handle signals from the instance, validate and store result
    """
    properties_schema = {}

    WAIT_STATUSES = (
        STATUS_FAILURE,
        STATUS_SUCCESS,
    ) = (
        'FAILURE',
        'SUCCESS',
    )

    def handle_create(self):
        super(BaseWaitConditionHandle, self).handle_create()
        self.resource_id_set(self._get_user_id())

    def _status_ok(self, status):
        return status in self.WAIT_STATUSES

    def _metadata_format_ok(self, metadata):
        if sorted(tuple(six.iterkeys(metadata))) == sorted(self.METADATA_KEYS):
            return self._status_ok(metadata[self.STATUS])

    def handle_signal(self, metadata=None):
        signal_reason = None
        if self._metadata_format_ok(metadata):
            rsrc_metadata = self.metadata_get(refresh=True)
            if metadata[self.UNIQUE_ID] in rsrc_metadata:
                LOG.warn(_LW("Overwriting Metadata item for id %s!"),
                         metadata[self.UNIQUE_ID])
            safe_metadata = {}
            for k in self.METADATA_KEYS:
                if k == self.UNIQUE_ID:
                    continue
                safe_metadata[k] = metadata[k]
            rsrc_metadata.update({metadata[self.UNIQUE_ID]: safe_metadata})
            self.metadata_set(rsrc_metadata)
            signal_reason = ('status:%s reason:%s' %
                             (safe_metadata[self.STATUS],
                              safe_metadata[self.REASON]))
        else:
            LOG.error(_LE("Metadata failed validation for %s"), self.name)
            raise ValueError(_("Metadata format invalid"))
        return signal_reason

    def get_status(self):
        """Return a list of the Status values for the handle signals."""
        return [v[self.STATUS]
                for v in six.itervalues(self.metadata_get(refresh=True))]

    def get_status_reason(self, status):
        """Return a list of reasons associated with a particular status."""
        return [v[self.REASON]
                for v in six.itervalues(self.metadata_get(refresh=True))
                if v[self.STATUS] == status]


class WaitConditionFailure(exception.Error):
    def __init__(self, wait_condition, handle):
        reasons = handle.get_status_reason(handle.STATUS_FAILURE)
        super(WaitConditionFailure, self).__init__(';'.join(reasons))


class WaitConditionTimeout(exception.Error):
    def __init__(self, wait_condition, handle):
        reasons = handle.get_status_reason(handle.STATUS_SUCCESS)
        vals = {'len': len(reasons),
                'count': wait_condition.properties[wait_condition.COUNT]}
        if reasons:
            vals['reasons'] = ';'.join(reasons)
            message = (_('%(len)d of %(count)d received - %(reasons)s') % vals)
        else:
            message = (_('%(len)d of %(count)d received') % vals)
        super(WaitConditionTimeout, self).__init__(message)
