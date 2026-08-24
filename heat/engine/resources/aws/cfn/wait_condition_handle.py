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

from heat.common.i18n import _
from heat.engine.resources import wait_condition as wc_base
from heat.engine import support


class WaitConditionHandle(wc_base.BaseCfnWaitConditionHandle):
    """AWS WaitConditionHandle resource.

    the main point of this class is to :
    have no dependencies (so the instance can reference it)
    generate a unique url (to be returned in the reference)
    then the cfn-signal will use this url to post to and
    WaitCondition will poll it to see if has been written to.
    """

    support_status = support.SupportStatus(
        version='27.0.0',
        status=support.DEPRECATED,
        message=_('AWS-compatible resources are deprecated; use '
                  'OS::Heat::WaitConditionHandle with signal_transport set '
                  'to CFN_SIGNAL instead'),
        previous_status=support.SupportStatus(version='2014.1'))


def resource_mapping():
    return {
        'AWS::CloudFormation::WaitConditionHandle': WaitConditionHandle,
    }
