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

import json

from heat.common import exception
from heat.common import identifier
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import signal_responder

from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


class WaitConditionHandle(signal_responder.SignalResponder):
    '''
    the main point of this class is to :
    have no dependancies (so the instance can reference it)
    generate a unique url (to be returned in the refernce)
    then the cfn-signal will use this url to post to and
    WaitCondition will poll it to see if has been written to.
    '''
    properties_schema = {}

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
        expected_keys = ['Data', 'Reason', 'Status', 'UniqueId']
        if sorted(metadata.keys()) == expected_keys:
            return metadata['Status'] in WAIT_STATUSES

    def metadata_update(self, new_metadata=None):
        '''
        Validate and update the resource metadata
        '''
        if new_metadata is None:
            return

        if self._metadata_format_ok(new_metadata):
            rsrc_metadata = self.metadata
            if new_metadata['UniqueId'] in rsrc_metadata:
                logger.warning(_("Overwriting Metadata item for UniqueId %s!")
                               % new_metadata['UniqueId'])
            safe_metadata = {}
            for k in ('Data', 'Reason', 'Status'):
                safe_metadata[k] = new_metadata[k]
            # Note we can't update self.metadata directly, as it
            # is a Metadata descriptor object which only supports get/set
            rsrc_metadata.update({new_metadata['UniqueId']: safe_metadata})
            self.metadata = rsrc_metadata
        else:
            logger.error(_("Metadata failed validation for %s") % self.name)
            raise ValueError(_("Metadata format invalid"))

    def get_status(self):
        '''
        Return a list of the Status values for the handle signals
        '''
        return [self.metadata[s]['Status']
                for s in self.metadata]

    def get_status_reason(self, status):
        '''
        Return the reason associated with a particular status
        If there is more than one handle signal matching the specified status
        then return a semicolon delimited string containing all reasons
        '''
        return ';'.join([self.metadata[s]['Reason']
                        for s in self.metadata
                        if self.metadata[s]['Status'] == status])


WAIT_STATUSES = (
    STATUS_FAILURE,
    STATUS_SUCCESS,
) = (
    'FAILURE',
    'SUCCESS',
)


class WaitConditionFailure(Exception):
    def __init__(self, wait_condition, handle):
        reasons = handle.get_status_reason(STATUS_FAILURE)
        super(WaitConditionFailure, self).__init__(reasons)


class WaitConditionTimeout(Exception):
    def __init__(self, wait_condition, handle):
        reasons = handle.get_status_reason(STATUS_SUCCESS)
        message = (_('%(len)d of %(count)d received') % {
                   'len': len(reasons), 'count': wait_condition.count})
        if reasons:
            message += ' - %s' % reasons

        super(WaitConditionTimeout, self).__init__(message)


class WaitCondition(resource.Resource):
    PROPERTIES = (
        HANDLE, TIMEOUT, COUNT,
    ) = (
        'Handle', 'Timeout', 'Count',
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
            ]
        ),
    }

    def __init__(self, name, json_snippet, stack):
        super(WaitCondition, self).__init__(name, json_snippet, stack)

        self.count = int(self.t['Properties'].get('Count', '1'))

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
                logger.info(_('%(name)s Timed out (%(timeout)s)') % {
                            'name': str(self), 'timeout': str(timeout)})
                raise timeout

            handle_status = handle.get_status()

            if any(s != STATUS_SUCCESS for s in handle_status):
                failure = WaitConditionFailure(self, handle)
                logger.info(_('%(name)s Failed (%(failure)s)') % {
                            'name': str(self), 'failure': str(failure)})
                raise failure

            if len(handle_status) >= self.count:
                logger.info(_("%s Succeeded") % str(self))
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

    def handle_delete(self):
        if self.resource_id is None:
            return

        handle = self.stack[self.resource_id]
        handle.metadata = {}

    def FnGetAtt(self, key):
        res = {}
        handle_res_name = self._get_handle_resource_name()
        handle = self.stack[handle_res_name]
        if key == 'Data':
            meta = handle.metadata
            # Note, can't use a dict generator on python 2.6, hence:
            res = dict([(k, meta[k]['Data']) for k in meta])
        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        logger.debug('%s.GetAtt(%s) == %s' % (self.name, key, res))
        return unicode(json.dumps(res))


def resource_mapping():
    return {
        'AWS::CloudFormation::WaitCondition': WaitCondition,
        'AWS::CloudFormation::WaitConditionHandle': WaitConditionHandle,
    }
