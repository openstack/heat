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
from heat.engine.resources.openstack.magnum import cluster_template
from heat.engine import support
from heat.engine import translation


class BayModel(cluster_template.ClusterTemplate):
    """A resource for the BayModel in Magnum.

    This resource has been deprecated by ClusterTemplate.
    BayModel is an object that stores template information about the bay which
    is used to create new bays consistently.
    """
    SSH_AUTHORIZED_KEY = 'ssh_authorized_key'

    deprecate_msg = _('Please use OS::Magnum::ClusterTemplate instead.')
    support_status = support.SupportStatus(
        status=support.HIDDEN,
        message=deprecate_msg,
        version='11.0.0',
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            message=deprecate_msg,
            version='9.0.0',
            previous_status=support.SupportStatus(
                status=support.SUPPORTED,
                version='5.0.0'),
            substitute_class=cluster_template.ClusterTemplate
        )
    )

    def translation_rules(self, props):
        if props.get(self.SSH_AUTHORIZED_KEY):
            return [
                translation.TranslationRule(
                    props,
                    translation.TranslationRule.DELETE,
                    [self.SSH_AUTHORIZED_KEY]
                )
            ]


def resource_mapping():
    return {
        'OS::Magnum::BayModel': BayModel
    }
