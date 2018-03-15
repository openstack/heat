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

import six

from heat.engine.resources import signal_responder
from heat.engine.resources import wait_condition as wc_base
from heat.engine import support


class WaitConditionHandle(wc_base.BaseWaitConditionHandle):
    """AWS WaitConditionHandle resource.

    the main point of this class is to :
    have no dependencies (so the instance can reference it)
    generate a unique url (to be returned in the reference)
    then the cfn-signal will use this url to post to and
    WaitCondition will poll it to see if has been written to.
    """

    support_status = support.SupportStatus(version='2014.1')

    METADATA_KEYS = (
        DATA, REASON, STATUS, UNIQUE_ID
    ) = (
        'Data', 'Reason', 'Status', 'UniqueId'
    )

    def get_reference_id(self):
        if self.resource_id:
            wc = signal_responder.WAITCONDITION
            return six.text_type(self._get_ec2_signed_url(signal_type=wc))
        else:
            return six.text_type(self.name)

    def metadata_update(self, new_metadata=None):
        """DEPRECATED. Should use handle_signal instead."""
        self.handle_signal(details=new_metadata)

    def handle_signal(self, details=None):
        """Validate and update the resource metadata.

        metadata must use the following format::

            {
                "Status" : "Status (must be SUCCESS or FAILURE)",
                "UniqueId" : "Some ID, should be unique for Count>1",
                "Data" : "Arbitrary Data",
                "Reason" : "Reason String"
            }
        """
        if details is None:
            return
        return super(WaitConditionHandle, self).handle_signal(details)


def resource_mapping():
    return {
        'AWS::CloudFormation::WaitConditionHandle': WaitConditionHandle,
    }
