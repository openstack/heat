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

from designateclient import client
from designateclient import exceptions
from designateclient.v1 import domains
from designateclient.v1 import records

from heat.common import exception as heat_exception
from heat.engine.clients import client_plugin
from heat.engine import constraints

CLIENT_NAME = 'designate'


class DesignateClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = [exceptions]

    service_types = [DNS] = ['dns']

    supported_versions = [V1, V2] = ['1', '2']

    default_version = V1

    def _create(self, version=default_version):
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        return client.Client(version=version,
                             session=self.context.keystone_session,
                             endpoint_type=endpoint_type,
                             service_type=self.DNS,
                             region_name=self._get_region_name())

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def get_domain_id(self, domain_id_or_name):
        try:
            domain_obj = self.client().domains.get(domain_id_or_name)
            return domain_obj.id
        except exceptions.NotFound:
            for domain in self.client().domains.list():
                if domain.name == domain_id_or_name:
                    return domain.id

        raise heat_exception.EntityNotFound(entity='Designate Domain',
                                            name=domain_id_or_name)

    def get_zone_id(self, zone_id_or_name):
        client = self.client(version=self.V2)
        try:
            zone_obj = client.zones.get(zone_id_or_name)
            return zone_obj['id']
        except exceptions.NotFound:
            zones = client.zones.list(criterion=dict(name=zone_id_or_name))
            if len(zones) == 1:
                return zones[0]['id']

        raise heat_exception.EntityNotFound(entity='Designate Zone',
                                            name=zone_id_or_name)

    def domain_create(self, **kwargs):
        domain = domains.Domain(**kwargs)
        return self.client().domains.create(domain)

    def domain_update(self, **kwargs):
        # Designate mandates to pass the Domain object with updated properties
        domain = self.client().domains.get(kwargs['id'])
        for key in kwargs.keys():
            setattr(domain, key, kwargs[key])

        return self.client().domains.update(domain)

    def record_create(self, **kwargs):
        domain_id = self.get_domain_id(kwargs.pop('domain'))
        record = records.Record(**kwargs)
        return self.client().records.create(domain_id, record)

    def record_update(self, **kwargs):
        # Designate mandates to pass the Record object with updated properties
        domain_id = self.get_domain_id(kwargs.pop('domain'))
        record = self.client().records.get(domain_id, kwargs['id'])

        for key in kwargs.keys():
            setattr(record, key, kwargs[key])

        return self.client().records.update(record.domain_id, record)

    def record_delete(self, **kwargs):
        try:
            domain_id = self.get_domain_id(kwargs.pop('domain'))
        except heat_exception.EntityNotFound:
            return
        return self.client().records.delete(domain_id,
                                            kwargs.pop('id'))

    def record_show(self, **kwargs):
        domain_id = self.get_domain_id(kwargs.pop('domain'))
        return self.client().records.get(domain_id,
                                         kwargs.pop('id'))


class DesignateDomainConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_domain_id'


class DesignateZoneConstraint(constraints.BaseCustomConstraint):
    resource_client_name = CLIENT_NAME
    resource_getter_name = 'get_zone_id'
