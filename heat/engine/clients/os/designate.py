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

from designateclient import exceptions
from designateclient import v1 as client
from designateclient.v1 import domains

from heat.common import exception as heat_exception
from heat.engine.clients import client_plugin
from heat.engine import constraints


class DesignateClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = [exceptions]

    service_types = ['dns']

    def _create(self):
        args = self._get_client_args(service_name='designate',
                                     service_type=self.service_types[0])

        return client.Client(auth_url=args['auth_url'],
                             project_id=args['project_id'],
                             token=args['token'](),
                             endpoint=args['os_endpoint'],
                             cacert=args['cacert'],
                             insecure=args['insecure'])

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

    def domain_create(self, **kwargs):
        domain = domains.Domain(**kwargs)
        return self.client().domains.create(domain)

    def domain_update(self, **kwargs):
        # Designate mandates to pass the Domain object with updated properties
        domain = self.client().domains.get(kwargs['id'])
        for key in kwargs.keys():
            setattr(domain, key, kwargs[key])

        return self.client().domains.update(domain)


class DesignateDomainConstraint(constraints.BaseCustomConstraint):

    expected_exceptions = (heat_exception.EntityNotFound,)

    def validate_with_client(self, client, domain):
        client.client_plugin('designate').get_domain_id(domain)
