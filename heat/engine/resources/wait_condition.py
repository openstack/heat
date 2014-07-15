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

import json

from heat.common import exception
from heat.common import identifier
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import signal_responder
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class WaitConditionHandle(signal_responder.SignalResponder):
    '''
    the main point of this class is to :
    have no dependencies (so the instance can reference it)
    generate a unique url (to be returned in the reference)
    then the cfn-signal will use this url to post to and
    WaitCondition will poll it to see if has been written to.
    '''
    properties_schema = {}

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
        'Data', 'Reason', 'Status', 'UniqueId'
    )

    def handle_create(self):
        super(WaitConditionHandle, self).handle_create()
        self.resource_id_set(self._get_user_id())

    def FnGetRefId(self):
        '''
        Override the default resource FnGetRefId so we return the signed URL
        '''
        if self.resource_id:
            wc = signal_responder.WAITCONDITION
            return unicode(self._get_signed_url(signal_type=wc))
        else:
            return unicode(self.name)

    def _metadata_format_ok(self, metadata):
        """
        Check the format of the provided metadata is as expected.
        metadata must use the following format:
        {
            "Status" : "Status (must be SUCCESS or FAILURE)"
            "UniqueId" : "Some ID, should be unique for Count>1",
            "Data" : "Arbitrary Data",
            "Reason" : "Reason String"
        }
        """
        if tuple(sorted(metadata.keys())) == self.METADATA_KEYS:
            return metadata[self.STATUS] in self.WAIT_STATUSES

    def metadata_update(self, new_metadata=None):
        """DEPRECATED. Should use handle_signal instead."""
        self.handle_signal(details=new_metadata)

    def handle_signal(self, details=None):
        '''
        Validate and update the resource metadata
        '''
        if details is None:
            return

        if self._metadata_format_ok(details):
            rsrc_metadata = self.metadata_get(refresh=True)
            if details[self.UNIQUE_ID] in rsrc_metadata:
                LOG.warning(_("Overwriting Metadata item for UniqueId %s!")
                            % details[self.UNIQUE_ID])
            safe_metadata = {}
            for k in self.METADATA_KEYS:
                if k == self.UNIQUE_ID:
                    continue
                safe_metadata[k] = details[k]
            rsrc_metadata.update({details[self.UNIQUE_ID]: safe_metadata})
            self.metadata_set(rsrc_metadata)
        else:
            LOG.error(_("Metadata failed validation for %s") % self.name)
            raise ValueError(_("Metadata format invalid"))

    def get_status(self):
        '''
        Return a list of the Status values for the handle signals
        '''
        return [v[self.STATUS]
                for v in self.metadata_get(refresh=True).values()]

    def get_status_reason(self, status):
        '''
        Return a list of reasons associated with a particular status
        '''
        return [v[self.REASON]
                for v in self.metadata_get(refresh=True).values()
                if v[self.STATUS] == status]


class UpdateWaitConditionHandle(WaitConditionHandle):
    '''
    This works identically to a regular WaitConditionHandle, except that
    on update it clears all signals received and changes the handle. Using
    this handle means that you must setup the signal senders to send their
    signals again any time the update handle changes. This allows us to roll
    out new configurations and be confident that they are rolled out once
    UPDATE COMPLETE is reached.
    '''
    def update(self, after, before=None, prev_resource=None):
        raise resource.UpdateReplace(self.name)


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


class WaitCondition(resource.Resource):
    PROPERTIES = (
        HANDLE, TIMEOUT, COUNT,
    ) = (
        'Handle', 'Timeout', 'Count',
    )

    ATTRIBUTES = (
        DATA,
    ) = (
        'Data',
    )

    properties_schema = {
        HANDLE: properties.Schema(
            properties.Schema.STRING,
            _('A reference to the wait condition handle used to signal this '
              'wait condition.'),
            required=True
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.NUMBER,
            _('The number of seconds to wait for the correct number of '
              'signals to arrive.'),
            required=True,
            constraints=[
                constraints.Range(1, 43200),
            ]
        ),
        COUNT: properties.Schema(
            properties.Schema.NUMBER,
            _('The number of success signals that must be received before '
              'the stack creation process continues.'),
            constraints=[
                constraints.Range(min=1),
            ],
            default=1,
            update_allowed=True
        ),
    }

    attributes_schema = {
        DATA: attributes.Schema(
            _('JSON serialized dict containing data associated with wait '
              'condition signals sent to the handle.'),
            cache_mode=attributes.Schema.CACHE_NONE
        ),
    }

    def __init__(self, name, json_snippet, stack):
        super(WaitCondition, self).__init__(name, json_snippet, stack)

    def _validate_handle_url(self):
        handle_url = self.properties[self.HANDLE]
        handle_id = identifier.ResourceIdentifier.from_arn_url(handle_url)
        if handle_id.tenant != self.stack.context.tenant_id:
            raise ValueError(_("WaitCondition invalid Handle tenant %s") %
                             handle_id.tenant)
        if handle_id.stack_name != self.stack.name:
            raise ValueError(_("WaitCondition invalid Handle stack %s") %
                             handle_id.stack_name)
        if handle_id.stack_id != self.stack.id:
            raise ValueError(_("WaitCondition invalid Handle stack %s") %
                             handle_id.stack_id)
        if handle_id.resource_name not in self.stack:
            raise ValueError(_("WaitCondition invalid Handle %s") %
                             handle_id.resource_name)
        if not isinstance(self.stack[handle_id.resource_name],
                          WaitConditionHandle):
            raise ValueError(_("WaitCondition invalid Handle %s") %
                             handle_id.resource_name)

    def _get_handle_resource_name(self):
        handle_url = self.properties[self.HANDLE]
        handle_id = identifier.ResourceIdentifier.from_arn_url(handle_url)
        return handle_id.resource_name

    def _wait(self, handle):
        while True:
            try:
                yield
            except scheduler.Timeout:
                timeout = WaitConditionTimeout(self, handle)
                LOG.info(_('%(name)s Timed out (%(timeout)s)')
                         % {'name': str(self), 'timeout': str(timeout)})
                raise timeout

            handle_status = handle.get_status()

            if any(s != handle.STATUS_SUCCESS for s in handle_status):
                failure = WaitConditionFailure(self, handle)
                LOG.info(_('%(name)s Failed (%(failure)s)')
                         % {'name': str(self), 'failure': str(failure)})
                raise failure

            if len(handle_status) >= self.properties[self.COUNT]:
                LOG.info(_("%s Succeeded") % str(self))
                return

    def handle_create(self):
        self._validate_handle_url()
        handle_res_name = self._get_handle_resource_name()
        handle = self.stack[handle_res_name]
        self.resource_id_set(handle_res_name)

        runner = scheduler.TaskRunner(self._wait, handle)
        runner.start(timeout=float(self.properties[self.TIMEOUT]))
        return runner

    def check_create_complete(self, runner):
        return runner.step()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.properties = json_snippet.properties(self.properties_schema,
                                                      self.context)

        handle_res_name = self._get_handle_resource_name()
        handle = self.stack[handle_res_name]

        runner = scheduler.TaskRunner(self._wait, handle)
        runner.start(timeout=float(self.properties[self.TIMEOUT]))
        return runner

    def check_update_complete(self, runner):
        return runner.step()

    def handle_delete(self):
        if self.resource_id is None:
            return

        handle = self.stack[self.resource_id]
        handle.metadata_set({})

    def _resolve_attribute(self, key):
        res = {}
        handle_res_name = self._get_handle_resource_name()
        handle = self.stack[handle_res_name]
        if key == self.DATA:
            meta = handle.metadata_get(refresh=True)
            # Note, can't use a dict generator on python 2.6, hence:
            res = dict([(k, meta[k][handle.DATA]) for k in meta])
            LOG.debug('%(name)s.GetAtt(%(key)s) == %(res)s'
                      % {'name': self.name,
                         'key': key,
                         'res': res})

            return unicode(json.dumps(res))


def resource_mapping():
    return {
        'AWS::CloudFormation::WaitCondition': WaitCondition,
        'AWS::CloudFormation::WaitConditionHandle': WaitConditionHandle,
        'OS::Heat::UpdateWaitConditionHandle': UpdateWaitConditionHandle,
    }
