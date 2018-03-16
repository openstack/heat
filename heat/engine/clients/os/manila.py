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

from heat.common import exception as heat_exception
from heat.engine.clients import client_plugin
from heat.engine import constraints
from manilaclient import client as manila_client
from manilaclient import exceptions

MANILACLIENT_VERSION = "2"
CLIENT_NAME = 'manila'


class ManilaClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [SHARE] = ['share']

    def _create(self):
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        args = {
            'endpoint_type': endpoint_type,
            'service_type': self.SHARE,
            'session': self.context.keystone_session,
            'region_name': self._get_region_name()
        }
        client = manila_client.Client(MANILACLIENT_VERSION, **args)
        return client

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)

    @staticmethod
    def _find_resource_by_id_or_name(id_or_name, resource_list,
                                     resource_type_name):
        """The method is trying to find id or name in item_list

        The method searches item with id_or_name in list and returns it.
        If there is more than one value or no values then it raises an
        exception

        :param id_or_name: resource id or name
        :param resource_list: list of resources
        :param resource_type_name: name of resource type that will be used
                                   for exceptions
        :raises EntityNotFound: if cannot find resource by name
        :raises NoUniqueMatch: if find more than one resource by ambiguous name
        :return: resource or generate an exception otherwise
        """
        search_result_by_id = [res for res in resource_list
                               if res.id == id_or_name]
        if search_result_by_id:
            return search_result_by_id[0]
        else:
            # try to find resource by name
            search_result_by_name = [res for res in resource_list
                                     if res.name == id_or_name]
            match_count = len(search_result_by_name)
            if match_count > 1:
                message = ("Ambiguous {0} name '{1}'. Found more than one "
                           "{0} for this name in Manila."
                           ).format(resource_type_name, id_or_name)
                raise exceptions.NoUniqueMatch(message)
            elif match_count == 1:
                return search_result_by_name[0]
            else:
                raise heat_exception.EntityNotFound(entity=resource_type_name,
                                                    name=id_or_name)

    def get_share_type(self, share_type_identity):
        return self._find_resource_by_id_or_name(
            share_type_identity,
            self.client().share_types.list(),
            "share type"
        )

    def get_share_network(self, share_network_identity):
        return self._find_resource_by_id_or_name(
            share_network_identity,
            self.client().share_networks.list(),
            "share network"
        )

    def get_share_snapshot(self, snapshot_identity):
        return self._find_resource_by_id_or_name(
            snapshot_identity,
            self.client().share_snapshots.list(),
            "share snapshot"
        )

    def get_security_service(self, service_identity):
        return self._find_resource_by_id_or_name(
            service_identity,
            self.client().security_services.list(),
            'security service'
        )


class ManilaShareBaseConstraint(constraints.BaseCustomConstraint):

    # check that exceptions module has been loaded. Without this check
    # doc tests on gates will fail
    expected_exceptions = (heat_exception.EntityNotFound,
                           exceptions.NoUniqueMatch)
    resource_client_name = CLIENT_NAME


class ManilaShareNetworkConstraint(ManilaShareBaseConstraint):

    resource_getter_name = 'get_share_network'


class ManilaShareTypeConstraint(ManilaShareBaseConstraint):

    resource_getter_name = 'get_share_type'


class ManilaShareSnapshotConstraint(ManilaShareBaseConstraint):

    resource_getter_name = 'get_share_snapshot'
