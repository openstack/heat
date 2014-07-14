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

from neutronclient.common.exceptions import NeutronClientException

from heat.common import exception
from heat.engine import resource
from heat.engine import scheduler
from heat.openstack.common import log as logging
from heat.openstack.common import uuidutils

LOG = logging.getLogger(__name__)


class NeutronResource(resource.Resource):

    def validate(self):
        '''
        Validate any of the provided params
        '''
        res = super(NeutronResource, self).validate()
        if res:
            return res
        return self.validate_properties(self.properties)

    @staticmethod
    def validate_properties(properties):
        '''
        Validates to ensure nothing in value_specs overwrites
        any key that exists in the schema.

        Also ensures that shared and tenant_id is not specified
        in value_specs.
        '''
        if 'value_specs' in properties.keys():
            vs = properties.get('value_specs')
            banned_keys = set(['shared', 'tenant_id']).union(
                properties.keys())
            for k in banned_keys.intersection(vs.keys()):
                return '%s not allowed in value_specs' % k

    @staticmethod
    def _validate_depr_property_required(properties, prop_key, depr_prop_key):
            prop_value = properties.get(prop_key)
            depr_prop_value = properties.get(depr_prop_key)

            if prop_value and depr_prop_value:
                raise exception.ResourcePropertyConflict(prop_key,
                                                         depr_prop_key)
            if not prop_value and not depr_prop_value:
                msg = _('Either %(prop_key)s or %(depr_prop_key)s'
                        ' should be specified.'
                        ) % {'prop_key': prop_key,
                             'depr_prop_key': depr_prop_key}
                raise exception.StackValidationFailed(message=msg)

    @staticmethod
    def prepare_properties(properties, name):
        '''
        Prepares the property values so that they can be passed directly to
        the Neutron create call.

        Removes None values and value_specs, merges value_specs with the main
        values.
        '''
        props = dict((k, v) for k, v in properties.items()
                     if v is not None and k != 'value_specs')

        if 'name' in properties.keys():
            props.setdefault('name', name)

        if 'value_specs' in properties.keys():
            props.update(properties.get('value_specs'))

        return props

    def prepare_update_properties(self, definition):
        '''
        Prepares the property values so that they can be passed directly to
        the Neutron update call.

        Removes any properties which are not update_allowed, then processes
        as for prepare_properties.
        '''
        p = definition.properties(self.properties_schema, self.context)
        update_props = dict((k, v) for k, v in p.items()
                            if p.props.get(k).schema.update_allowed)

        props = self.prepare_properties(
            update_props,
            self.physical_resource_name())
        return props

    @staticmethod
    def is_built(attributes):
        if attributes['status'] == 'BUILD':
            return False
        if attributes['status'] in ('ACTIVE', 'DOWN'):
            return True
        else:
            raise exception.Error(_('neutron reported unexpected '
                                    'resource[%(name)s] status[%(status)s]') %
                                  {'name': attributes['name'],
                                   'status': attributes['status']})

    def _resolve_attribute(self, name):
        try:
            attributes = self._show_resource()
        except NeutronClientException as ex:
            LOG.warn(_("failed to fetch resource attributes: %s") % ex)
            return None
        if name == 'show':
            return attributes

        return attributes[name]

    def _confirm_delete(self):
        while True:
            try:
                yield
                self._show_resource()
            except NeutronClientException as ex:
                self._handle_not_found_exception(ex)
                return

    def _handle_not_found_exception(self, ex):
        if ex.status_code != 404:
            raise ex

    def FnGetRefId(self):
        return unicode(self.resource_id)

    @staticmethod
    def get_secgroup_uuids(security_groups, client):
        '''
        Returns a list of security group UUIDs.
        Args:
            security_groups: List of security group names or UUIDs
            client: reference to neutronclient
        '''
        seclist = []
        all_groups = None
        for sg in security_groups:
            if uuidutils.is_uuid_like(sg):
                seclist.append(sg)
            else:
                if not all_groups:
                    response = client.list_security_groups()
                    all_groups = response['security_groups']
                groups = [g['id'] for g in all_groups if g['name'] == sg]
                if len(groups) == 0:
                    raise exception.PhysicalResourceNotFound(resource_id=sg)
                if len(groups) > 1:
                    raise exception.PhysicalResourceNameAmbiguity(name=sg)
                seclist.append(groups[0])
        return seclist

    def _delete_task(self):
        delete_task = scheduler.TaskRunner(self._confirm_delete)
        delete_task.start()
        return delete_task

    def check_delete_complete(self, delete_task):
        # if the resource was already deleted, delete_task will be None
        return delete_task is None or delete_task.step()
