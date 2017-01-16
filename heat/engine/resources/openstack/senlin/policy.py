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
#

import copy

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.senlin import res_base
from heat.engine import translation


class Policy(res_base.BaseSenlinResource):
    """A resource that creates a Senlin Policy.

    A policy is a set of rules that can be checked and/or enforced when
    an action is performed on a Cluster.
    """

    entity = 'policy'

    PROPERTIES = (
        NAME, TYPE, POLICY_PROPS, BINDINGS,
    ) = (
        'name', 'type', 'properties', 'bindings'
    )

    _BINDINGS = (
        BD_CLUSTER, BD_ENABLED,
    ) = (
        'cluster', 'enabled'
    )

    _ACTION_STATUS = (
        ACTION_SUCCEEDED, ACTION_FAILED,
    ) = (
        'SUCCEEDED', 'FAILED',
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the senlin policy. By default, physical resource name '
              'is used.'),
            update_allowed=True,
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('The type of senlin policy.'),
            required=True,
            constraints=[
                constraints.CustomConstraint('senlin.policy_type')
            ]
        ),
        POLICY_PROPS: properties.Schema(
            properties.Schema.MAP,
            _('Properties of this policy.'),
        ),
        BINDINGS: properties.Schema(
            properties.Schema.LIST,
            _('A list of clusters to which this policy is attached.'),
            update_allowed=True,
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    BD_CLUSTER: properties.Schema(
                        properties.Schema.STRING,
                        _("The name or ID of target cluster."),
                        required=True,
                        constraints=[
                            constraints.CustomConstraint('senlin.cluster')
                        ]
                    ),
                    BD_ENABLED: properties.Schema(
                        properties.Schema.BOOLEAN,
                        _("Whether enable this policy on that cluster."),
                        default=True,
                    ),
                }
            )
        )
    }

    def translation_rules(self, props):
        rules = [
            translation.TranslationRule(
                props,
                translation.TranslationRule.RESOLVE,
                translation_path=[self.BINDINGS, self.BD_CLUSTER],
                client_plugin=self.client_plugin(),
                finder='get_cluster_id'),
        ]
        return rules

    def remove_bindings(self, bindings):
        for bd in bindings:
            try:
                bd['action'] = self.client().cluster_detach_policy(
                    bd[self.BD_CLUSTER], self.resource_id)['action']
                bd['finished'] = False
            except Exception as ex:
                # policy didn't attach to cluster, skip.
                if (self.client_plugin().is_bad_request(ex) or
                        self.client_plugin().is_not_found(ex)):
                    bd['finished'] = True
                else:
                    raise

    def add_bindings(self, bindings):
        for bd in bindings:
            bd['action'] = self.client().cluster_attach_policy(
                bd[self.BD_CLUSTER], self.resource_id,
                enabled=bd[self.BD_ENABLED])['action']
            bd['finished'] = False

    def check_action_done(self, bindings):
        ret = True
        if not bindings:
            return ret
        for bd in bindings:
            if bd.get('finished', False):
                continue
            action = self.client().get_action(bd['action'])
            if action.status == self.ACTION_SUCCEEDED:
                bd['finished'] = True
            elif action.status == self.ACTION_FAILED:
                err_msg = _('Failed to execute %(action)s for '
                            '%(cluster)s: %(reason)s') % {
                    'action': action.action,
                    'cluster': bd[self.BD_CLUSTER],
                    'reason': action.status_reason}
                raise exception.ResourceInError(
                    status_reason=err_msg,
                    resource_status=self.FAILED)
            else:
                ret = False
        return ret

    def handle_create(self):
        params = {
            'name': (self.properties[self.NAME] or
                     self.physical_resource_name()),
            'spec': self.client_plugin().generate_spec(
                self.properties[self.TYPE],
                self.properties[self.POLICY_PROPS]
            )
        }

        policy = self.client().create_policy(**params)
        self.resource_id_set(policy.id)
        bindings = copy.deepcopy(self.properties[self.BINDINGS])
        if bindings:
            self.add_bindings(bindings)
        return bindings

    def check_create_complete(self, bindings):
        return self.check_action_done(bindings)

    def handle_delete(self):
        return copy.deepcopy(self.properties[self.BINDINGS])

    def check_delete_complete(self, bindings):
        if not self.resource_id:
            return True
        self.remove_bindings(bindings)
        if self.check_action_done(bindings):
            with self.client_plugin().ignore_not_found:
                self.client().delete_policy(self.resource_id)
                return True
        return False

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if self.NAME in prop_diff:
            param = {'name': prop_diff[self.NAME]}
            policy_obj = self.client().get_policy(self.resource_id)
            self.client().update_policy(policy_obj, **param)
        actions = dict()
        if self.BINDINGS in prop_diff:
            old = self.properties[self.BINDINGS] or []
            new = prop_diff[self.BINDINGS] or []
            actions['remove'] = [bd for bd in old if bd not in new]
            actions['add'] = [bd for bd in new if bd not in old]
            self.remove_bindings(actions['remove'])
        return actions

    def check_update_complete(self, actions):
        ret = True
        remove_done = self.check_action_done(actions.get('remove', []))
        # wait until detach finished, then start attach
        if remove_done and 'add' in actions:
            if not actions.get('add_started', False):
                self.add_bindings(actions['add'])
                actions['add_started'] = True
            ret = self.check_action_done(actions['add'])
        return ret


def resource_mapping():
    return {
        'OS::Senlin::Policy': Policy
    }
