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

from oslo_log import log as logging
import six

from heat.common import exception
from heat.common.i18n import _
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
        if not isinstance(metadata, collections.Mapping):
            return False
        if set(metadata) != set(self.METADATA_KEYS):
            return False
        return self._status_ok(metadata[self.STATUS])

    def normalise_signal_data(self, signal_data, latest_metadata):
        return signal_data

    def handle_signal(self, details=None):
        write_attempts = []

        def merge_signal_metadata(signal_data, latest_rsrc_metadata):
            signal_data = self.normalise_signal_data(signal_data,
                                                     latest_rsrc_metadata)

            if not self._metadata_format_ok(signal_data):
                LOG.info("Metadata failed validation for %s", self.name)
                raise ValueError(_("Metadata format invalid"))

            new_entry = signal_data.copy()
            unique_id = six.text_type(new_entry.pop(self.UNIQUE_ID))

            new_rsrc_metadata = latest_rsrc_metadata.copy()
            if unique_id in new_rsrc_metadata:
                LOG.info("Overwriting Metadata item for id %s!",
                         unique_id)
            new_rsrc_metadata.update({unique_id: new_entry})

            write_attempts.append(signal_data)
            return new_rsrc_metadata

        self.metadata_set(details, merge_metadata=merge_signal_metadata)

        data_written = write_attempts[-1]
        signal_reason = ('status:%s reason:%s' %
                         (data_written[self.STATUS],
                          data_written[self.REASON]))
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
