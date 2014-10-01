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

from oslo.utils import strutils

from heat.openstack.common.gettextutils import _


def extract_bool(subject):
    '''
    Convert any true/false string to its corresponding boolean value,
    regardless of case.
    '''
    if str(subject).lower() not in ('true', 'false'):
        raise ValueError(_('Unrecognized value "%(value)s", acceptable '
                           'values are: true, false.') % {'value': subject})
    return strutils.bool_from_string(subject, strict=True)
