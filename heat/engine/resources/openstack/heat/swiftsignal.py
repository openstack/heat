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
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import six
from six.moves.urllib import parse

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine.clients.os import swift
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import support

LOG = logging.getLogger(__name__)


class SwiftSignalFailure(exception.Error):
    def __init__(self, wait_cond):
        reasons = wait_cond.get_status_reason(wait_cond.STATUS_FAILURE)
        super(SwiftSignalFailure, self).__init__(';'.join(reasons))


class SwiftSignalTimeout(exception.Error):
    def __init__(self, wait_cond):
        reasons = wait_cond.get_status_reason(wait_cond.STATUS_SUCCESS)
        vals = {'len': len(reasons),
                'count': wait_cond.properties[wait_cond.COUNT]}
        if reasons:
            vals['reasons'] = ';'.join(reasons)
            message = (_('%(len)d of %(count)d received - %(reasons)s') % vals)
        else:
            message = (_('%(len)d of %(count)d received') % vals)
        super(SwiftSignalTimeout, self).__init__(message)


class SwiftSignalHandle(resource.Resource):
    """Resource for managing signals from Swift resources.

    This resource is same as WaitConditionHandle, but designed for using by
    Swift resources.
    """

    support_status = support.SupportStatus(version='2014.2')
    default_client_name = "swift"

    properties_schema = {}

    ATTRIBUTES = (
        TOKEN,
        ENDPOINT,
        CURL_CLI,
    ) = (
        'token',
        'endpoint',
        'curl_cli',
    )

    attributes_schema = {
        TOKEN: attributes.Schema(
            _('Tokens are not needed for Swift TempURLs. This attribute is '
              'being kept for compatibility with the '
              'OS::Heat::WaitConditionHandle resource.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
        ENDPOINT: attributes.Schema(
            _('Endpoint/url which can be used for signalling handle.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
        CURL_CLI: attributes.Schema(
            _('Convenience attribute, provides curl CLI command '
              'prefix, which can be used for signalling handle completion or '
              'failure. You can signal success by adding '
              '--data-binary \'{"status": "SUCCESS"}\' '
              ', or signal failure by adding '
              '--data-binary \'{"status": "FAILURE"}\'.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        cplugin = self.client_plugin()
        url = cplugin.get_signal_url(self.stack.id,
                                     self.physical_resource_name())
        self.data_set(self.ENDPOINT, url)
        self.resource_id_set(self.physical_resource_name())

    def _resolve_attribute(self, key):
        if self.resource_id:
            if key == self.TOKEN:
                return ''  # HeatWaitConditionHandle compatibility
            elif key == self.ENDPOINT:
                return self.data().get(self.ENDPOINT)
            elif key == self.CURL_CLI:
                return ("curl -i -X PUT '%s'" %
                        self.data().get(self.ENDPOINT))

    def handle_delete(self):
        cplugin = self.client_plugin()
        client = cplugin.client()

        # Delete all versioned objects
        while True:
            try:
                client.delete_object(self.stack.id,
                                     self.physical_resource_name())
            except Exception as exc:
                cplugin.ignore_not_found(exc)
                break

        # Delete the container if it is empty
        try:
            client.delete_container(self.stack.id)
        except Exception as exc:
            if cplugin.is_not_found(exc) or cplugin.is_conflict(exc):
                pass
            else:
                raise

        self.data_delete(self.ENDPOINT)

    def get_reference_id(self):
        return self.data().get(self.ENDPOINT)


class SwiftSignal(resource.Resource):
    """Resource for handling signals received by SwiftSignalHandle.

    This resource handles signals received by SwiftSignalHandle and
    is same as WaitCondition resource.
    """

    support_status = support.SupportStatus(version='2014.2')
    default_client_name = "swift"

    PROPERTIES = (HANDLE, TIMEOUT, COUNT,) = ('handle', 'timeout', 'count',)

    properties_schema = {
        HANDLE: properties.Schema(
            properties.Schema.STRING,
            required=True,
            description=_('URL of TempURL where resource will signal '
                          'completion and optionally upload data.')
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.NUMBER,
            description=_('The maximum number of seconds to wait for the '
                          'resource to signal completion. Once the timeout '
                          'is reached, creation of the signal resource will '
                          'fail.'),
            required=True,
            constraints=[
                constraints.Range(1, 43200),
            ]
        ),
        COUNT: properties.Schema(
            properties.Schema.INTEGER,
            description=_('The number of success signals that must be '
                          'received before the stack creation process '
                          'continues.'),
            default=1,
            constraints=[
                constraints.Range(1, 1000),
            ]
        )
    }

    ATTRIBUTES = (DATA) = 'data'

    attributes_schema = {
        DATA: attributes.Schema(
            _('JSON data that was uploaded via the SwiftSignalHandle.'),
            type=attributes.Schema.STRING
        )
    }

    WAIT_STATUSES = (
        STATUS_FAILURE,
        STATUS_SUCCESS,
    ) = (
        'FAILURE',
        'SUCCESS',
    )

    METADATA_KEYS = (
        DATA, REASON, STATUS, UNIQUE_ID
    ) = (
        'data', 'reason', 'status', 'id'
    )

    def __init__(self, name, json_snippet, stack):
        super(SwiftSignal, self).__init__(name, json_snippet, stack)
        self._obj_name = None
        self._url = None

    @property
    def url(self):
        if not self._url:
            self._url = parse.urlparse(self.properties[self.HANDLE])
        return self._url

    @property
    def obj_name(self):
        if not self._obj_name:
            self._obj_name = self.url.path.split('/')[4]
        return self._obj_name

    def _validate_handle_url(self):
        parts = self.url.path.split('/')
        msg = _('"%(url)s" is not a valid SwiftSignalHandle.  The %(part)s '
                'is invalid')
        cplugin = self.client_plugin()
        if not cplugin.is_valid_temp_url_path(self.url.path):
            raise ValueError(msg % {'url': self.url.path,
                                    'part': 'Swift TempURL path'})
        if not parts[3] == self.stack.id:
            raise ValueError(msg % {'url': self.url.path,
                                    'part': 'container name'})

    def handle_create(self):
        self._validate_handle_url()
        started_at = timeutils.utcnow()
        return started_at, float(self.properties[self.TIMEOUT])

    def get_signals(self):
        try:
            container = self.client().get_container(self.stack.id)
        except Exception as exc:
            self.client_plugin().ignore_not_found(exc)
            LOG.debug("Swift container %s was not found", self.stack.id)
            return []

        index = container[1]
        if not index:
            LOG.debug("Swift objects in container %s were not found",
                      self.stack.id)
            return []

        # Remove objects in that are for other handle resources, since
        # multiple SwiftSignalHandle resources in the same stack share
        # a container
        filtered = [obj for obj in index if self.obj_name in obj['name']]

        # Fetch objects from Swift and filter results
        obj_bodies = []
        for obj in filtered:
            try:
                signal = self.client().get_object(self.stack.id, obj['name'])
            except Exception as exc:
                self.client_plugin().ignore_not_found(exc)
                continue

            body = signal[1]
            if body == swift.IN_PROGRESS:  # Ignore the initial object
                continue
            if body == "":
                obj_bodies.append({})
                continue
            try:
                obj_bodies.append(jsonutils.loads(body))
            except ValueError:
                raise exception.Error(_("Failed to parse JSON data: %s") %
                                      body)

        # Set default values on each signal
        signals = []
        signal_num = 1
        for signal in obj_bodies:

            # Remove previous signals with the same ID
            sig_id = self.UNIQUE_ID
            ids = [s.get(sig_id) for s in signals if sig_id in s]
            if ids and sig_id in signal and ids.count(signal[sig_id]) > 0:
                [signals.remove(s) for s in signals
                 if s.get(sig_id) == signal[sig_id]]

            # Make sure all fields are set, since all are optional
            signal.setdefault(self.DATA, None)
            unique_id = signal.setdefault(sig_id, signal_num)
            reason = 'Signal %s received' % unique_id
            signal.setdefault(self.REASON, reason)
            signal.setdefault(self.STATUS, self.STATUS_SUCCESS)

            signals.append(signal)
            signal_num += 1

        return signals

    def get_status(self):
        return [s[self.STATUS] for s in self.get_signals()]

    def get_status_reason(self, status):
        return [s[self.REASON]
                for s in self.get_signals()
                if s[self.STATUS] == status]

    def get_data(self):
        signals = self.get_signals()
        if not signals:
            return None
        data = {}
        for signal in signals:
            data[signal[self.UNIQUE_ID]] = signal[self.DATA]
        return data

    def check_create_complete(self, create_data):
        if timeutils.is_older_than(*create_data):
            raise SwiftSignalTimeout(self)

        statuses = self.get_status()
        if not statuses:
            return False

        for status in statuses:
            if status == self.STATUS_FAILURE:
                failure = SwiftSignalFailure(self)
                LOG.info('%(name)s Failed (%(failure)s)',
                         {'name': str(self), 'failure': str(failure)})
                raise failure
            elif status != self.STATUS_SUCCESS:
                raise exception.Error(_("Unknown status: %s") % status)

        if len(statuses) >= self.properties[self.COUNT]:
            LOG.info("%s Succeeded", str(self))
            return True
        return False

    def _resolve_attribute(self, key):
        if key == self.DATA:
            return six.text_type(jsonutils.dumps(self.get_data()))


def resource_mapping():
    return {'OS::Heat::SwiftSignal': SwiftSignal,
            'OS::Heat::SwiftSignalHandle': SwiftSignalHandle}
