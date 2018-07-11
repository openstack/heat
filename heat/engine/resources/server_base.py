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

import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from heat.common import exception
from heat.common import password_gen
from heat.engine.clients import progress
from heat.engine.resources import stack_user

cfg.CONF.import_opt('max_server_name_length', 'heat.common.config')

LOG = logging.getLogger(__name__)


class BaseServer(stack_user.StackUser):
    """Base Server resource."""

    physical_resource_name_limit = cfg.CONF.max_server_name_length

    entity = 'servers'

    def __init__(self, name, json_snippet, stack):
        super(BaseServer, self).__init__(name, json_snippet, stack)
        self.default_collectors = []

    def _server_name(self):
        name = self.properties[self.NAME]
        if name:
            return name

        return self.physical_resource_name()

    def _container_and_object_name(self, props):
        deployment_swift_data = props.get(
            self.DEPLOYMENT_SWIFT_DATA,
            self.properties[self.DEPLOYMENT_SWIFT_DATA])
        container_name = deployment_swift_data[self.CONTAINER]
        if container_name is None:
            container_name = self.physical_resource_name()

        object_name = deployment_swift_data[self.OBJECT]
        if object_name is None:
            object_name = self.data().get('metadata_object_name')
        if object_name is None:
            object_name = str(uuid.uuid4())

        return container_name, object_name

    def _populate_deployments_metadata(self, meta, props):
        meta['deployments'] = meta.get('deployments', [])
        meta['os-collect-config'] = meta.get('os-collect-config', {})
        occ = meta['os-collect-config']
        collectors = list(self.default_collectors)
        occ['collectors'] = collectors
        region_name = (self.context.region_name or
                       cfg.CONF.region_name_for_services)

        # set existing values to None to override any boot-time config
        occ_keys = ('heat', 'zaqar', 'cfn', 'request')
        for occ_key in occ_keys:
            if occ_key not in occ:
                continue
            existing = occ[occ_key]
            for k in existing:
                existing[k] = None

        queue_id = self.data().get('metadata_queue_id')
        if self.transport_poll_server_heat(props):
            occ.update({'heat': {
                'user_id': self._get_user_id(),
                'password': self.password,
                'auth_url': self.context.auth_url,
                'project_id': self.stack.stack_user_project_id,
                'stack_id': self.stack.identifier().stack_path(),
                'resource_name': self.name,
                'region_name': region_name}})
            collectors.append('heat')

        elif self.transport_zaqar_message(props):
            queue_id = queue_id or self.physical_resource_name()
            occ.update({'zaqar': {
                'user_id': self._get_user_id(),
                'password': self.password,
                'auth_url': self.context.auth_url,
                'project_id': self.stack.stack_user_project_id,
                'queue_id': queue_id,
                'region_name': region_name}})
            collectors.append('zaqar')

        elif self.transport_poll_server_cfn(props):
            heat_client_plugin = self.stack.clients.client_plugin('heat')
            config_url = heat_client_plugin.get_cfn_metadata_server_url()
            occ.update({'cfn': {
                'metadata_url': config_url,
                'access_key_id': self.access_key,
                'secret_access_key': self.secret_key,
                'stack_name': self.stack.name,
                'path': '%s.Metadata' % self.name}})
            collectors.append('cfn')

        elif self.transport_poll_temp_url(props):
            container_name, object_name = self._container_and_object_name(
                props)

            self.client('swift').put_container(container_name)

            url = self.client_plugin('swift').get_temp_url(
                container_name, object_name, method='GET')
            put_url = self.client_plugin('swift').get_temp_url(
                container_name, object_name)
            self.data_set('metadata_put_url', put_url)
            self.data_set('metadata_object_name', object_name)

            collectors.append('request')
            occ.update({'request': {'metadata_url': url}})

        collectors.append('local')
        self.metadata_set(meta)

        # push replacement polling config to any existing push-based sources
        if queue_id:
            zaqar_plugin = self.client_plugin('zaqar')
            zaqar = zaqar_plugin.create_for_tenant(
                self.stack.stack_user_project_id, self._user_token())
            queue = zaqar.queue(queue_id)
            queue.post({'body': meta, 'ttl': zaqar_plugin.DEFAULT_TTL})
            self.data_set('metadata_queue_id', queue_id)

        object_name = self.data().get('metadata_object_name')
        if object_name:
            container_name, object_name = self._container_and_object_name(
                props)
            self.client('swift').put_object(
                container_name, object_name, jsonutils.dumps(meta))

    def _create_transport_credentials(self, props):
        if self.transport_poll_server_cfn(props):
            self._create_user()
            self._create_keypair()

        elif (self.transport_poll_server_heat(props) or
              self.transport_zaqar_message(props)):
            if self.password is None:
                self.password = password_gen.generate_openstack_password()
            self._create_user()

        self._register_access_key()

    @property
    def access_key(self):
        return self.data().get('access_key')

    @property
    def secret_key(self):
        return self.data().get('secret_key')

    @property
    def password(self):
        return self.data().get('password')

    @password.setter
    def password(self, password):
        if password is None:
            self.data_delete('password')
        else:
            self.data_set('password', password, True)

    def transport_poll_server_cfn(self, props):
        return props[
            self.SOFTWARE_CONFIG_TRANSPORT] == self.POLL_SERVER_CFN

    def transport_poll_server_heat(self, props):
        return props[
            self.SOFTWARE_CONFIG_TRANSPORT] == self.POLL_SERVER_HEAT

    def transport_poll_temp_url(self, props):
        return props[
            self.SOFTWARE_CONFIG_TRANSPORT] == self.POLL_TEMP_URL

    def transport_zaqar_message(self, props):
        return props[
            self.SOFTWARE_CONFIG_TRANSPORT] == self.ZAQAR_MESSAGE

    def check_create_complete(self, server_id):
        return True

    def _resolve_attribute(self, name):
        if self.resource_id is None:
            return
        if name == self.NAME_ATTR:
            return self._server_name()
        if name == self.OS_COLLECT_CONFIG:
            return self.metadata_get().get('os-collect-config', {})

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if tmpl_diff.metadata_changed():
            # If SOFTWARE_CONFIG user_data_format is enabled we require
            # the "deployments" and "os-collect-config" keys for Deployment
            # polling.  We can attempt to merge the occ data, but any
            # metadata update containing deployments will be discarded.
            new_md = json_snippet.metadata()
            if self.user_data_software_config():
                metadata = self.metadata_get(True) or {}
                new_occ_md = new_md.get('os-collect-config', {})
                occ_md = metadata.get('os-collect-config', {})
                occ_md.update(new_occ_md)
                new_md['os-collect-config'] = occ_md
                deployment_md = metadata.get('deployments', [])
                new_md['deployments'] = deployment_md
            self.metadata_set(new_md)

        updaters = []

        if self.SOFTWARE_CONFIG_TRANSPORT in prop_diff:
            self._update_software_config_transport(prop_diff)

        # NOTE(pas-ha) optimization is possible (starting first task
        # right away), but we'd rather not, as this method already might
        # have called several APIs
        return updaters

    def _update_software_config_transport(self, prop_diff):
        if not self.user_data_software_config():
            return
        try:
            metadata = self.metadata_get(True) or {}
            self._create_transport_credentials(prop_diff)
            self._populate_deployments_metadata(metadata, prop_diff)
            # push new metadata to all sources by creating a dummy
            # deployment
            sc = self.rpc_client().create_software_config(
                self.context, 'ignored', 'ignored', '')
            sd = self.rpc_client().create_software_deployment(
                self.context, self.resource_id, sc['id'])
            self.rpc_client().delete_software_deployment(
                self.context, sd['id'])
            self.rpc_client().delete_software_config(
                self.context, sc['id'])
        except Exception:
            # Updating the software config transport is on a best-effort
            # basis as any raised exception here would result in the resource
            # going into an ERROR state, which will be replaced on the next
            # stack update. This is not desirable for a server. The old
            # transport will continue to work, and the new transport may work
            # despite exceptions in the above block.
            LOG.exception(
                'Error while updating software config transport'
            )

    def metadata_update(self, new_metadata=None):
        """Refresh the metadata if new_metadata is None."""
        if new_metadata is None:
            # Re-resolve the template metadata and merge it with the
            # current resource metadata.  This is necessary because the
            # attributes referenced in the template metadata may change
            # and the resource itself adds keys to the metadata which
            # are not specified in the template (e.g the deployments data)
            meta = self.metadata_get(refresh=True) or {}
            tmpl_meta = self.t.metadata()
            meta.update(tmpl_meta)
            self.metadata_set(meta)

    @staticmethod
    def _check_maximum(count, maximum, msg):
        """Check a count against a maximum.

        Unless maximum is -1 which indicates that there is no limit.
        """
        if maximum != -1 and count > maximum:
            raise exception.StackValidationFailed(message=msg)

    def _delete_temp_url(self):
        object_name = self.data().get('metadata_object_name')
        if not object_name:
            return
        with self.client_plugin('swift').ignore_not_found:
            container = self.properties[self.DEPLOYMENT_SWIFT_DATA].get(
                'container')
            container = container or self.physical_resource_name()
            swift = self.client('swift')
            swift.delete_object(container, object_name)
            headers = swift.head_container(container)
            if int(headers['x-container-object-count']) == 0:
                swift.delete_container(container)

    def _delete_queue(self):
        queue_id = self.data().get('metadata_queue_id')
        if not queue_id:
            return
        client_plugin = self.client_plugin('zaqar')
        zaqar = client_plugin.create_for_tenant(
            self.stack.stack_user_project_id, self._user_token())
        with client_plugin.ignore_not_found:
            zaqar.queue(queue_id).delete()
        self.data_delete('metadata_queue_id')

    def handle_snapshot_delete(self, state):

        if state[1] != self.FAILED and self.resource_id:
            image_id = self.client().servers.create_image(
                self.resource_id, self.physical_resource_name())
            return progress.ServerDeleteProgress(
                self.resource_id, image_id, False)
        return self._delete()

    def handle_delete(self):

        return self._delete()

    def check_delete_complete(self, prg):
        if not prg:
            return True

    def _show_resource(self):
        rsrc_dict = super(BaseServer, self)._show_resource()
        rsrc_dict.setdefault(
            self.OS_COLLECT_CONFIG,
            self.metadata_get().get('os-collect-config', {}))
        return rsrc_dict
