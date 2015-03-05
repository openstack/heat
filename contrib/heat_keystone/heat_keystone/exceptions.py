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

from heat.common import exception
from heat.common.i18n import _


class KeystoneRoleNotFound(exception.HeatException):
    msg_fmt = _("Keystone role %(role_id)s does not found")


class KeystoneProjectNotFound(exception.HeatException):
    msg_fmt = _("Keystone project %(project_id)s does not found")


class KeystoneDomainNotFound(exception.HeatException):
    msg_fmt = _("Keystone domain %(domain_id)s does not found")


class KeystoneGroupNotFound(exception.HeatException):
    msg_fmt = _("Keystone group %(group_id)s does not found")
