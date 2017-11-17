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

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import requests
import six
from six.moves.urllib import parse as urlparse

from heat.common import crypt
from heat.common import exception
from heat.common.i18n import _
from heat.db.sqlalchemy import api as db_api
from heat.engine import api
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import software_config_io as swc_io
from heat.objects import resource as resource_objects
from heat.objects import software_config as software_config_object
from heat.objects import software_deployment as software_deployment_object
from heat.rpc import api as rpc_api

LOG = logging.getLogger(__name__)


class SoftwareConfigService(object):

    def show_software_config(self, cnxt, config_id):
        sc = software_config_object.SoftwareConfig.get_by_id(cnxt, config_id)
        return api.format_software_config(sc)

    def list_software_configs(self, cnxt, limit=None, marker=None):
        scs = software_config_object.SoftwareConfig.get_all(
            cnxt,
            limit=limit,
            marker=marker)
        result = [api.format_software_config(sc, detail=False,
                                             include_project=cnxt.is_admin)
                  for sc in scs]
        return result

    def create_software_config(self, cnxt, group, name, config,
                               inputs, outputs, options):

        swc_io.check_io_schema_list(inputs)
        in_conf = [swc_io.InputConfig(**i).as_dict() for i in inputs]
        swc_io.check_io_schema_list(outputs)
        out_conf = [swc_io.OutputConfig(**o).as_dict() for o in outputs]

        sc = software_config_object.SoftwareConfig.create(cnxt, {
            'group': group,
            'name': name,
            'config': {
                rpc_api.SOFTWARE_CONFIG_INPUTS: in_conf,
                rpc_api.SOFTWARE_CONFIG_OUTPUTS: out_conf,
                rpc_api.SOFTWARE_CONFIG_OPTIONS: options,
                rpc_api.SOFTWARE_CONFIG_CONFIG: config
            },
            'tenant': cnxt.tenant_id})
        return api.format_software_config(sc)

    def delete_software_config(self, cnxt, config_id):
        software_config_object.SoftwareConfig.delete(cnxt, config_id)

    def list_software_deployments(self, cnxt, server_id):
        all_sd = software_deployment_object.SoftwareDeployment.get_all(
            cnxt, server_id)
        result = [api.format_software_deployment(sd) for sd in all_sd]
        return result

    def metadata_software_deployments(self, cnxt, server_id):
        if not server_id:
            raise ValueError(_('server_id must be specified'))
        all_sd = software_deployment_object.SoftwareDeployment.get_all(
            cnxt, server_id)

        # filter out the sds with None config
        flt_sd = six.moves.filterfalse(lambda sd: sd.config is None,
                                       all_sd)
        # sort the configs by config name, to give the list of metadata a
        # deterministic and controllable order.
        flt_sd_s = sorted(flt_sd, key=lambda sd: sd.config.name)
        result = [api.format_software_config(sd.config) for sd in flt_sd_s]
        return result

    @resource_objects.retry_on_conflict
    def _push_metadata_software_deployments(
            self, cnxt, server_id, stack_user_project_id):
        rs = db_api.resource_get_by_physical_resource_id(cnxt, server_id)
        if not rs:
            return
        cnxt.session.refresh(rs)
        if rs.action == resource.Resource.DELETE:
            return
        deployments = self.metadata_software_deployments(cnxt, server_id)
        md = rs.rsrc_metadata or {}
        md['deployments'] = deployments

        metadata_put_url = None
        metadata_queue_id = None
        for rd in rs.data:
            if rd.key == 'metadata_put_url':
                metadata_put_url = rd.value
            if rd.key == 'metadata_queue_id':
                metadata_queue_id = rd.value

        action = _('deployments of server %s') % server_id
        atomic_key = rs.atomic_key
        rows_updated = db_api.resource_update(
            cnxt, rs.id, {'rsrc_metadata': md}, atomic_key)
        if not rows_updated:
            LOG.debug('Retrying server %s deployment metadata update',
                      server_id)
            raise exception.ConcurrentTransaction(action=action)

        LOG.debug('Updated server %s deployment metadata', server_id)

        if metadata_put_url:
            json_md = jsonutils.dumps(md)
            resp = requests.put(metadata_put_url, json_md)
            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                LOG.error('Failed to deliver deployment data to '
                          'server %s: %s', server_id, exc)
        if metadata_queue_id:
            project = stack_user_project_id
            queue = self._get_zaqar_queue(cnxt, rs, project, metadata_queue_id)
            zaqar_plugin = cnxt.clients.client_plugin('zaqar')
            queue.post({'body': md, 'ttl': zaqar_plugin.DEFAULT_TTL})

        # Bump the atomic key again to serialise updates to the data sent to
        # the server via Swift.
        if metadata_put_url is not None:
            rows_updated = db_api.resource_update(cnxt, rs.id, {},
                                                  atomic_key + 1)
            if not rows_updated:
                LOG.debug('Concurrent update to server %s deployments data '
                          'detected - retrying.', server_id)
                raise exception.ConcurrentTransaction(action=action)

    def _refresh_swift_software_deployment(self, cnxt, sd, deploy_signal_id):
        container, object_name = urlparse.urlparse(
            deploy_signal_id).path.split('/')[-2:]
        swift_plugin = cnxt.clients.client_plugin('swift')
        swift = swift_plugin.client()

        try:
            headers = swift.head_object(container, object_name)
        except Exception as ex:
            # ignore not-found, in case swift is not consistent yet
            if swift_plugin.is_not_found(ex):
                LOG.info('Signal object not found: %(c)s %(o)s', {
                    'c': container, 'o': object_name})
                return sd
            raise

        lm = headers.get('last-modified')

        last_modified = swift_plugin.parse_last_modified(lm)
        prev_last_modified = sd.updated_at

        if prev_last_modified:
            # assume stored as utc, convert to offset-naive datetime
            prev_last_modified = prev_last_modified.replace(tzinfo=None)

        if prev_last_modified and (last_modified <= prev_last_modified):
            return sd

        try:
            (headers, obj) = swift.get_object(container, object_name)
        except Exception as ex:
            # ignore not-found, in case swift is not consistent yet
            if swift_plugin.is_not_found(ex):
                LOG.info(
                    'Signal object not found: %(c)s %(o)s', {
                        'c': container, 'o': object_name})
                return sd
            raise
        if obj:
            self.signal_software_deployment(
                cnxt, sd.id, jsonutils.loads(obj),
                last_modified.isoformat())

        return software_deployment_object.SoftwareDeployment.get_by_id(
            cnxt, sd.id)

    def _get_zaqar_queue(self, cnxt, rs, project, queue_name):
        user = password = signed_url_data = None
        for rd in rs.data:
            if rd.key == 'password':
                password = crypt.decrypt(rd.decrypt_method, rd.value)
            if rd.key == 'user_id':
                user = rd.value
            if rd.key == 'zaqar_queue_signed_url_data':
                signed_url_data = jsonutils.loads(rd.value)
        zaqar_plugin = cnxt.clients.client_plugin('zaqar')
        if signed_url_data is None:
            keystone = cnxt.clients.client('keystone')
            token = keystone.stack_domain_user_token(
                user_id=user, project_id=project, password=password)
            zaqar = zaqar_plugin.create_for_tenant(project, token)
        else:
            signed_url_data.pop('project')
            zaqar = zaqar_plugin.create_from_signed_url(project,
                                                        **signed_url_data)

        return zaqar.queue(queue_name)

    def _refresh_zaqar_software_deployment(self, cnxt, sd, deploy_queue_id):
        rs = db_api.resource_get_by_physical_resource_id(cnxt, sd.id)
        project = sd.stack_user_project_id
        queue = self._get_zaqar_queue(cnxt, rs, project, deploy_queue_id)

        messages = list(queue.pop())
        if messages:
            self.signal_software_deployment(
                cnxt, sd.id, messages[0].body, None)

        return software_deployment_object.SoftwareDeployment.get_by_id(
            cnxt, sd.id)

    def check_software_deployment(self, cnxt, deployment_id, timeout):
        def _check():
            while True:
                sd = self._show_software_deployment(cnxt, deployment_id)
                if sd.status != rpc_api.SOFTWARE_DEPLOYMENT_IN_PROGRESS:
                    return
                yield
        scheduler.TaskRunner(_check)(timeout=timeout)
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            cnxt, deployment_id)
        return api.format_software_deployment(sd)

    def _show_software_deployment(self, cnxt, deployment_id):
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            cnxt, deployment_id)
        if sd.status == rpc_api.SOFTWARE_DEPLOYMENT_IN_PROGRESS:
            c = sd.config.config
            input_values = dict(swc_io.InputConfig(**i).input_data()
                                for i in c[rpc_api.SOFTWARE_CONFIG_INPUTS])
            transport = input_values.get('deploy_signal_transport')
            if transport == 'TEMP_URL_SIGNAL':
                sd = self._refresh_swift_software_deployment(
                    cnxt, sd, input_values.get('deploy_signal_id'))
            elif transport == 'ZAQAR_SIGNAL':
                sd = self._refresh_zaqar_software_deployment(
                    cnxt, sd, input_values.get('deploy_queue_id'))
        return sd

    def show_software_deployment(self, cnxt, deployment_id):
        sd = self._show_software_deployment(cnxt, deployment_id)
        return api.format_software_deployment(sd)

    def create_software_deployment(self, cnxt, server_id, config_id,
                                   input_values, action, status,
                                   status_reason, stack_user_project_id,
                                   deployment_id=None):

        if deployment_id is None:
            deployment_id = str(uuid.uuid4())
        sd = software_deployment_object.SoftwareDeployment.create(cnxt, {
            'id': deployment_id,
            'config_id': config_id,
            'server_id': server_id,
            'input_values': input_values,
            'tenant': cnxt.tenant_id,
            'stack_user_project_id': stack_user_project_id,
            'action': action,
            'status': status,
            'status_reason': six.text_type(status_reason)})
        self._push_metadata_software_deployments(
            cnxt, server_id, stack_user_project_id)
        return api.format_software_deployment(sd)

    def signal_software_deployment(self, cnxt, deployment_id, details,
                                   updated_at):

        if not deployment_id:
            raise ValueError(_('deployment_id must be specified'))

        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            cnxt, deployment_id)
        status = sd.status

        if not status == rpc_api.SOFTWARE_DEPLOYMENT_IN_PROGRESS:
            # output values are only expected when in an IN_PROGRESS state
            return

        details = details or {}

        output_status_code = rpc_api.SOFTWARE_DEPLOYMENT_OUTPUT_STATUS_CODE
        ov = sd.output_values or {}
        status = None
        status_reasons = {}
        status_code = details.get(output_status_code)
        if status_code and str(status_code) != '0':
            status = rpc_api.SOFTWARE_DEPLOYMENT_FAILED
            status_reasons[output_status_code] = _(
                'Deployment exited with non-zero status code: %s'
            ) % details.get(output_status_code)
            event_reason = 'deployment %s failed (%s)' % (deployment_id,
                                                          status_code)
        else:
            event_reason = 'deployment %s succeeded' % deployment_id

        for output in sd.config.config['outputs'] or []:
            out_key = output['name']
            if out_key in details:
                ov[out_key] = details[out_key]
                if output.get('error_output', False):
                    status = rpc_api.SOFTWARE_DEPLOYMENT_FAILED
                    status_reasons[out_key] = details[out_key]
                    event_reason = 'deployment %s failed' % deployment_id

        for out_key in rpc_api.SOFTWARE_DEPLOYMENT_OUTPUTS:
            ov[out_key] = details.get(out_key)

        if status == rpc_api.SOFTWARE_DEPLOYMENT_FAILED:
            # build a status reason out of all of the values of outputs
            # flagged as error_output
            status_reasons = [' : '.join((k, six.text_type(status_reasons[k])))
                              for k in status_reasons]
            status_reason = ', '.join(status_reasons)
        else:
            status = rpc_api.SOFTWARE_DEPLOYMENT_COMPLETE
            status_reason = _('Outputs received')

        self.update_software_deployment(
            cnxt, deployment_id=deployment_id,
            output_values=ov, status=status, status_reason=status_reason,
            config_id=None, input_values=None, action=None,
            updated_at=updated_at)
        # Return a string describing the outcome of handling the signal data
        return event_reason

    def update_software_deployment(self, cnxt, deployment_id, config_id,
                                   input_values, output_values, action,
                                   status, status_reason, updated_at):
        update_data = {}
        if config_id:
            update_data['config_id'] = config_id
        if input_values:
            update_data['input_values'] = input_values
        if output_values:
            update_data['output_values'] = output_values
        if action:
            update_data['action'] = action
        if status:
            update_data['status'] = status
        if status_reason:
            update_data['status_reason'] = six.text_type(status_reason)
        if updated_at:
            update_data['updated_at'] = timeutils.normalize_time(
                timeutils.parse_isotime(updated_at))
        else:
            update_data['updated_at'] = timeutils.utcnow()

        sd = software_deployment_object.SoftwareDeployment.update_by_id(
            cnxt, deployment_id, update_data)

        # only push metadata if this update resulted in the config_id
        # changing, since metadata is just a list of configs
        if config_id:
            self._push_metadata_software_deployments(
                cnxt, sd.server_id, sd.stack_user_project_id)

        return api.format_software_deployment(sd)

    def delete_software_deployment(self, cnxt, deployment_id):
        sd = software_deployment_object.SoftwareDeployment.get_by_id(
            cnxt, deployment_id)
        software_deployment_object.SoftwareDeployment.delete(
            cnxt, deployment_id)
        self._push_metadata_software_deployments(
            cnxt, sd.server_id, sd.stack_user_project_id)
