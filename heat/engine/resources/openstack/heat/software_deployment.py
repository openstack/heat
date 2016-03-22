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

import copy
import six
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.heat import resource_group
from heat.engine.resources.openstack.heat import software_config as sc
from heat.engine.resources import signal_responder
from heat.engine import rsrc_defn
from heat.engine import support
from heat.rpc import api as rpc_api

cfg.CONF.import_opt('default_deployment_signal_transport',
                    'heat.common.config')

LOG = logging.getLogger(__name__)


class SoftwareDeployment(signal_responder.SignalResponder):
    """This resource associates a server with some configuration.

    The configuration is to be deployed to that server.

    A deployment allows input values to be specified which map to the inputs
    schema defined in the config resource. These input values are interpreted
    by the configuration tool in a tool-specific manner.

    Whenever this resource goes to an IN_PROGRESS state, it creates an
    ephemeral config that includes the inputs values plus a number of extra
    inputs which have names prefixed with deploy_. The extra inputs relate
    to the current state of the stack, along with the information and
    credentials required to signal back the deployment results.

    Unless signal_transport=NO_SIGNAL, this resource will remain in an
    IN_PROGRESS state until the server signals it with the output values
    for that deployment. Those output values are then available as resource
    attributes, along with the default attributes deploy_stdout,
    deploy_stderr and deploy_status_code.

    Specifying actions other than the default CREATE and UPDATE will result
    in the deployment being triggered in those actions. For example this would
    allow cleanup configuration to be performed during actions SUSPEND and
    DELETE. A config could be designed to only work with some specific
    actions, or a config can read the value of the deploy_action input to
    allow conditional logic to perform different configuration for different
    actions.
    """

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        CONFIG, SERVER, INPUT_VALUES,
        DEPLOY_ACTIONS, NAME, SIGNAL_TRANSPORT,
        TIMEOUT,
    ) = (
        'config', 'server', 'input_values',
        'actions', 'name', 'signal_transport',
        'timeout',
    )

    ALLOWED_DEPLOY_ACTIONS = (
        resource.Resource.CREATE,
        resource.Resource.UPDATE,
        resource.Resource.DELETE,
        resource.Resource.SUSPEND,
        resource.Resource.RESUME,
    )

    ATTRIBUTES = (
        STDOUT, STDERR, STATUS_CODE
    ) = (
        'deploy_stdout', 'deploy_stderr', 'deploy_status_code'
    )

    DERIVED_CONFIG_INPUTS = (
        DEPLOY_SERVER_ID, DEPLOY_ACTION,
        DEPLOY_SIGNAL_ID, DEPLOY_STACK_ID,
        DEPLOY_RESOURCE_NAME, DEPLOY_AUTH_URL,
        DEPLOY_USERNAME, DEPLOY_PASSWORD,
        DEPLOY_PROJECT_ID, DEPLOY_USER_ID,
        DEPLOY_SIGNAL_VERB, DEPLOY_SIGNAL_TRANSPORT,
        DEPLOY_QUEUE_ID
    ) = (
        'deploy_server_id', 'deploy_action',
        'deploy_signal_id', 'deploy_stack_id',
        'deploy_resource_name', 'deploy_auth_url',
        'deploy_username', 'deploy_password',
        'deploy_project_id', 'deploy_user_id',
        'deploy_signal_verb', 'deploy_signal_transport',
        'deploy_queue_id'
    )

    SIGNAL_TRANSPORTS = (
        CFN_SIGNAL, TEMP_URL_SIGNAL, HEAT_SIGNAL, NO_SIGNAL,
        ZAQAR_SIGNAL
    ) = (
        'CFN_SIGNAL', 'TEMP_URL_SIGNAL', 'HEAT_SIGNAL', 'NO_SIGNAL',
        'ZAQAR_SIGNAL'
    )

    properties_schema = {
        CONFIG: properties.Schema(
            properties.Schema.STRING,
            _('ID of software configuration resource to execute when '
              'applying to the server.'),
            update_allowed=True
        ),
        SERVER: properties.Schema(
            properties.Schema.STRING,
            _('ID of resource to apply configuration to. '
              'Normally this should be a Nova server ID.'),
            required=True,
        ),
        INPUT_VALUES: properties.Schema(
            properties.Schema.MAP,
            _('Input values to apply to the software configuration on this '
              'server.'),
            update_allowed=True
        ),
        DEPLOY_ACTIONS: properties.Schema(
            properties.Schema.LIST,
            _('Which lifecycle actions of the deployment resource will result '
              'in this deployment being triggered.'),
            update_allowed=True,
            default=[resource.Resource.CREATE, resource.Resource.UPDATE],
            constraints=[constraints.AllowedValues(ALLOWED_DEPLOY_ACTIONS)]
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the derived config associated with this deployment. '
              'This is used to apply a sort order to the list of '
              'configurations currently deployed to a server.'),
            update_allowed=True
        ),
        SIGNAL_TRANSPORT: properties.Schema(
            properties.Schema.STRING,
            _('How the server should signal to heat with the deployment '
              'output values. CFN_SIGNAL will allow an HTTP POST to a CFN '
              'keypair signed URL. TEMP_URL_SIGNAL will create a '
              'Swift TempURL to be signaled via HTTP PUT. HEAT_SIGNAL '
              'will allow calls to the Heat API resource-signal using the '
              'provided keystone credentials. ZAQAR_SIGNAL will create a '
              'dedicated zaqar queue to be signaled using the provided '
              'keystone credentials. NO_SIGNAL will result in the resource '
              'going to the COMPLETE state without waiting for any signal.'),
            default=cfg.CONF.default_deployment_signal_transport,
            constraints=[
                constraints.AllowedValues(SIGNAL_TRANSPORTS),
            ]
        ),
        TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            description=_('The maximum number of seconds to wait for the '
                          'deployment to signal it has been completed. Once '
                          'the timeout is reached, the deployment will be '
                          'marked as failed.'),
            constraints=[
                constraints.Range(1, 43200),
            ],
            support_status=support.SupportStatus(version='7.0.0'),
        ),
    }

    attributes_schema = {
        STDOUT: attributes.Schema(
            _("Captured stdout from the configuration execution."),
            type=attributes.Schema.STRING
        ),
        STDERR: attributes.Schema(
            _("Captured stderr from the configuration execution."),
            type=attributes.Schema.STRING
        ),
        STATUS_CODE: attributes.Schema(
            _("Returned status code from the configuration execution."),
            type=attributes.Schema.STRING
        ),
    }

    default_client_name = 'heat'

    no_signal_actions = ()

    # No need to make metadata_update() calls since deployments have a
    # dedicated API for changing state on signals
    signal_needs_metadata_updates = False

    def _signal_transport_cfn(self):
        return self.properties[
            self.SIGNAL_TRANSPORT] == self.CFN_SIGNAL

    def _signal_transport_heat(self):
        return self.properties[
            self.SIGNAL_TRANSPORT] == self.HEAT_SIGNAL

    def _signal_transport_none(self):
        return self.properties[
            self.SIGNAL_TRANSPORT] == self.NO_SIGNAL

    def _signal_transport_temp_url(self):
        return self.properties[
            self.SIGNAL_TRANSPORT] == self.TEMP_URL_SIGNAL

    def _signal_transport_zaqar(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.ZAQAR_SIGNAL

    def _build_properties(self, config_id, action):
        props = {
            'config_id': config_id,
            'action': action,
        }

        if self._signal_transport_none():
            props['status'] = SoftwareDeployment.COMPLETE
            props['status_reason'] = _('Not waiting for outputs signal')
        else:
            props['status'] = SoftwareDeployment.IN_PROGRESS
            props['status_reason'] = _('Deploy data available')
        return props

    def _delete_derived_config(self, derived_config_id):
        try:
            self.rpc_client().delete_software_config(
                self.context, derived_config_id)
        except Exception as ex:
            self.rpc_client().ignore_error_named(ex, 'NotFound')

    def _get_derived_config(self, action, source_config):

        derived_params = self._build_derived_config_params(
            action, source_config)
        derived_config = self.rpc_client().create_software_config(
            self.context, **derived_params)
        return derived_config[rpc_api.SOFTWARE_CONFIG_ID]

    def _handle_action(self, action):
        if self.properties.get(self.CONFIG):
            config = self.rpc_client().show_software_config(
                self.context, self.properties.get(self.CONFIG))
        else:
            config = {}

        if config.get(rpc_api.SOFTWARE_CONFIG_GROUP) == 'component':
            valid_actions = set()
            for conf in config['config']['configs']:
                valid_actions.update(conf['actions'])
            if action not in valid_actions:
                return
        elif action not in self.properties[self.DEPLOY_ACTIONS]:
            return

        props = self._build_properties(
            self._get_derived_config(action, config),
            action)

        if self.resource_id is None:
            resource_id = str(uuid.uuid4())
            self.resource_id_set(resource_id)
            sd = self.rpc_client().create_software_deployment(
                self.context,
                deployment_id=resource_id,
                server_id=self.properties[SoftwareDeployment.SERVER],
                stack_user_project_id=self.stack.stack_user_project_id,
                **props)
        else:
            sd = self.rpc_client().show_software_deployment(
                self.context, self.resource_id)
            prev_derived_config = sd[rpc_api.SOFTWARE_DEPLOYMENT_CONFIG_ID]
            sd = self.rpc_client().update_software_deployment(
                self.context,
                deployment_id=self.resource_id,
                **props)
            if prev_derived_config:
                self._delete_derived_config(prev_derived_config)
        if not self._signal_transport_none():
            # NOTE(pshchelo): sd is a simple dict, easy to serialize,
            # does not need fixing re LP bug #1393268
            return sd

    def _check_complete(self, started_at):
        sd = self.rpc_client().show_software_deployment(
            self.context, self.resource_id)

        if started_at:
            timeout = self.properties[self.TIMEOUT]
            if timeout and timeutils.is_older_than(started_at, timeout):
                msg = _('Deployment %(action)s started at %(started)s timed '
                        'out after %(timeout)ss seconds')
                msg_data = {'started': started_at,
                            'action': sd[rpc_api.SOFTWARE_DEPLOYMENT_ACTION],
                            'timeout': timeout}
                raise exception.Error(msg % msg_data)

        status = sd[rpc_api.SOFTWARE_DEPLOYMENT_STATUS]
        if status == SoftwareDeployment.COMPLETE:
            return True
        elif status == SoftwareDeployment.FAILED:
            status_reason = sd[rpc_api.SOFTWARE_DEPLOYMENT_STATUS_REASON]
            message = _("Deployment to server failed: %s") % status_reason
            LOG.info(message)
            raise exception.Error(message)

    def _server_exists(self, sd):
        """Returns whether or not the deployment's server exists."""
        nova_client = self.client_plugin('nova')

        try:
            nova_client.get_server(sd['server_id'])
            return True
        except exception.EntityNotFound:
            return False

    def empty_config(self):
        return ''

    def _build_derived_config_params(self, action, source):
        scl = sc.SoftwareConfig
        derived_inputs = self._build_derived_inputs(action, source)
        derived_options = self._build_derived_options(action, source)
        derived_config = self._build_derived_config(
            action, source, derived_inputs, derived_options)
        derived_name = self.properties.get(self.NAME) or source.get(scl.NAME)
        return {
            scl.GROUP: source.get(scl.GROUP) or 'Heat::Ungrouped',
            scl.CONFIG: derived_config or self.empty_config(),
            scl.OPTIONS: derived_options,
            scl.INPUTS: derived_inputs,
            scl.OUTPUTS: source.get(scl.OUTPUTS),
            scl.NAME: derived_name or self.physical_resource_name()
        }

    def _build_derived_config(self, action, source,
                              derived_inputs, derived_options):
        return source.get(sc.SoftwareConfig.CONFIG)

    def _build_derived_options(self, action, source):
        return source.get(sc.SoftwareConfig.OPTIONS)

    def _build_derived_inputs(self, action, source):
        scl = sc.SoftwareConfig
        inputs = copy.deepcopy(source.get(scl.INPUTS)) or []
        input_values = dict(self.properties.get(self.INPUT_VALUES) or {})

        for inp in inputs:
            input_key = inp[scl.NAME]
            inp['value'] = input_values.pop(input_key, inp[scl.DEFAULT])

        # for any input values that do not have a declared input, add
        # a derived declared input so that they can be used as config
        # inputs
        for inpk, inpv in input_values.items():
            inputs.append({
                scl.NAME: inpk,
                scl.TYPE: 'String',
                'value': inpv
            })

        inputs.extend([{
            scl.NAME: self.DEPLOY_SERVER_ID,
            scl.DESCRIPTION: _('ID of the server being deployed to'),
            scl.TYPE: 'String',
            'value': self.properties[self.SERVER]
        }, {
            scl.NAME: self.DEPLOY_ACTION,
            scl.DESCRIPTION: _('Name of the current action being deployed'),
            scl.TYPE: 'String',
            'value': action
        }, {
            scl.NAME: self.DEPLOY_STACK_ID,
            scl.DESCRIPTION: _('ID of the stack this deployment belongs to'),
            scl.TYPE: 'String',
            'value': self.stack.identifier().stack_path()
        }, {
            scl.NAME: self.DEPLOY_RESOURCE_NAME,
            scl.DESCRIPTION: _('Name of this deployment resource in the '
                               'stack'),
            scl.TYPE: 'String',
            'value': self.name
        }, {
            scl.NAME: self.DEPLOY_SIGNAL_TRANSPORT,
            scl.DESCRIPTION: _('How the server should signal to heat with '
                               'the deployment output values.'),
            scl.TYPE: 'String',
            'value': self.properties[self.SIGNAL_TRANSPORT]
        }])
        if self._signal_transport_cfn():
            inputs.append({
                scl.NAME: self.DEPLOY_SIGNAL_ID,
                scl.DESCRIPTION: _('ID of signal to use for signaling '
                                   'output values'),
                scl.TYPE: 'String',
                'value': self._get_ec2_signed_url()
            })
            inputs.append({
                scl.NAME: self.DEPLOY_SIGNAL_VERB,
                scl.DESCRIPTION: _('HTTP verb to use for signaling '
                                   'output values'),
                scl.TYPE: 'String',
                'value': 'POST'
            })
        elif self._signal_transport_temp_url():
            inputs.append({
                scl.NAME: self.DEPLOY_SIGNAL_ID,
                scl.DESCRIPTION: _('ID of signal to use for signaling '
                                   'output values'),
                scl.TYPE: 'String',
                'value': self._get_swift_signal_url()
            })
            inputs.append({
                scl.NAME: self.DEPLOY_SIGNAL_VERB,
                scl.DESCRIPTION: _('HTTP verb to use for signaling '
                                   'output values'),
                scl.TYPE: 'String',
                'value': 'PUT'
            })
        elif self._signal_transport_heat() or self._signal_transport_zaqar():
            creds = self._get_heat_signal_credentials()
            inputs.extend([{
                scl.NAME: self.DEPLOY_AUTH_URL,
                scl.DESCRIPTION: _('URL for API authentication'),
                scl.TYPE: 'String',
                'value': creds['auth_url']
            }, {
                scl.NAME: self.DEPLOY_USERNAME,
                scl.DESCRIPTION: _('Username for API authentication'),
                scl.TYPE: 'String',
                'value': creds['username']
            }, {
                scl.NAME: self.DEPLOY_USER_ID,
                scl.DESCRIPTION: _('User ID for API authentication'),
                scl.TYPE: 'String',
                'value': creds['user_id']
            }, {
                scl.NAME: self.DEPLOY_PASSWORD,
                scl.DESCRIPTION: _('Password for API authentication'),
                scl.TYPE: 'String',
                'value': creds['password']
            }, {
                scl.NAME: self.DEPLOY_PROJECT_ID,
                scl.DESCRIPTION: _('ID of project for API authentication'),
                scl.TYPE: 'String',
                'value': creds['project_id']
            }])
        if self._signal_transport_zaqar():
            inputs.append({
                scl.NAME: self.DEPLOY_QUEUE_ID,
                scl.DESCRIPTION: _('ID of queue to use for signaling '
                                   'output values'),
                scl.TYPE: 'String',
                'value': self._get_zaqar_signal_queue_id()
            })

        return inputs

    def handle_create(self):
        started_at = timeutils.utcnow()
        return self._handle_action(self.CREATE), started_at

    def check_create_complete(self, create_data):
        sd, started_at = create_data
        if not sd:
            return True
        return self._check_complete(started_at)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        started_at = timeutils.utcnow()
        if prop_diff:
            self.properties = json_snippet.properties(self.properties_schema,
                                                      self.context)

        return self._handle_action(self.UPDATE), started_at

    def check_update_complete(self, update_data):
        sd, started_at = update_data
        if not sd:
            return True
        return self._check_complete(started_at)

    def handle_delete(self):
        started_at = timeutils.utcnow()
        try:
            return self._handle_action(self.DELETE), started_at
        except Exception as ex:
            self.rpc_client().ignore_error_named(ex, 'NotFound')

    def check_delete_complete(self, delete_data=None):
        sd, started_at = delete_data
        if (not sd or
                not self._server_exists(sd) or
                self._check_complete(started_at)):
            self._delete_resource()
            return True

    def _delete_resource(self):
        self._delete_signals()
        self._delete_user()

        derived_config_id = None
        if self.resource_id is not None:
            try:
                sd = self.rpc_client().show_software_deployment(
                    self.context, self.resource_id)
                derived_config_id = sd[rpc_api.SOFTWARE_DEPLOYMENT_CONFIG_ID]
                self.rpc_client().delete_software_deployment(
                    self.context, self.resource_id)
            except Exception as ex:
                self.rpc_client().ignore_error_named(ex, 'NotFound')

        if derived_config_id:
            self._delete_derived_config(derived_config_id)

    def handle_suspend(self):
        started_at = timeutils.utcnow()
        return self._handle_action(self.SUSPEND), started_at

    def check_suspend_complete(self, suspend_data):
        sd, started_at = suspend_data
        if not sd:
            return True
        return self._check_complete(started_at)

    def handle_resume(self):
        started_at = timeutils.utcnow()
        return self._handle_action(self.RESUME), started_at

    def check_resume_complete(self, resume_data):
        sd, started_at = resume_data
        if not sd:
            return True
        return self._check_complete(started_at)

    def handle_signal(self, details):
        return self.rpc_client().signal_software_deployment(
            self.context, self.resource_id, details,
            timeutils.utcnow().isoformat())

    def get_attribute(self, key, *path):
        """Resource attributes map to deployment outputs values."""
        sd = self.rpc_client().show_software_deployment(
            self.context, self.resource_id)
        ov = sd[rpc_api.SOFTWARE_DEPLOYMENT_OUTPUT_VALUES] or {}
        if key in ov:
            attribute = ov.get(key)
            return attributes.select_from_attribute(attribute, path)

        # Since there is no value for this key yet, check the output schemas
        # to find out if the key is valid
        sc = self.rpc_client().show_software_config(
            self.context, self.properties[self.CONFIG])
        outputs = sc[rpc_api.SOFTWARE_CONFIG_OUTPUTS] or []
        output_keys = [output['name'] for output in outputs]
        if key not in output_keys and key not in self.ATTRIBUTES:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)
        return None

    def validate(self):
        """Validate any of the provided params.

        :raises StackValidationFailed: if any property failed validation.
        """
        super(SoftwareDeployment, self).validate()
        server = self.properties[self.SERVER]
        if server:
            res = self.stack.resource_by_refid(server)
            if res:
                if not (res.properties.get('user_data_format') ==
                        'SOFTWARE_CONFIG'):
                    raise exception.StackValidationFailed(message=_(
                        "Resource %s's property user_data_format should be "
                        "set to SOFTWARE_CONFIG since there are software "
                        "deployments on it.") % server)


class SoftwareDeploymentGroup(resource_group.ResourceGroup):
    """This resource associates a group of servers with some configuration.

    The configuration is to be deployed to all servers in the group.

    The properties work in a similar way to OS::Heat::SoftwareDeployment,
    and in addition to the attributes documented, you may pass any
    attribute supported by OS::Heat::SoftwareDeployment, including those
    exposing arbitrary outputs, and return a map of deployment names to
    the specified attribute.
    """

    support_status = support.SupportStatus(version='5.0.0')

    PROPERTIES = (
        SERVERS,
        CONFIG,
        INPUT_VALUES,
        DEPLOY_ACTIONS,
        NAME,
        SIGNAL_TRANSPORT,
    ) = (
        'servers',
        SoftwareDeployment.CONFIG,
        SoftwareDeployment.INPUT_VALUES,
        SoftwareDeployment.DEPLOY_ACTIONS,
        SoftwareDeployment.NAME,
        SoftwareDeployment.SIGNAL_TRANSPORT,
    )

    ATTRIBUTES = (
        STDOUTS, STDERRS, STATUS_CODES
    ) = (
        'deploy_stdouts', 'deploy_stderrs', 'deploy_status_codes'
    )

    _sd_ps = SoftwareDeployment.properties_schema
    _rg_ps = resource_group.ResourceGroup.properties_schema

    properties_schema = {
        SERVERS: properties.Schema(
            properties.Schema.MAP,
            _('A map of Nova names and IDs to apply configuration to.'),
            update_allowed=True
        ),
        CONFIG: _sd_ps[CONFIG],
        INPUT_VALUES: _sd_ps[INPUT_VALUES],
        DEPLOY_ACTIONS: _sd_ps[DEPLOY_ACTIONS],
        NAME: _sd_ps[NAME],
        SIGNAL_TRANSPORT: _sd_ps[SIGNAL_TRANSPORT]
    }

    attributes_schema = {
        STDOUTS: attributes.Schema(
            _("A map of Nova names and captured stdouts from the "
              "configuration execution to each server."),
            type=attributes.Schema.MAP
        ),
        STDERRS: attributes.Schema(
            _("A map of Nova names and captured stderrs from the "
              "configuration execution to each server."),
            type=attributes.Schema.MAP
        ),
        STATUS_CODES: attributes.Schema(
            _("A map of Nova names and returned status code from the "
              "configuration execution."),
            type=attributes.Schema.MAP
        ),
    }

    update_policy_schema = {}

    def get_size(self):
        return len(self.properties.get(self.SERVERS, {}))

    def _resource_names(self):
        return six.iterkeys(self.properties.get(self.SERVERS, {}))

    def get_resource_def(self, include_all=False):
        return dict(self.properties)

    def build_resource_definition(self, res_name, res_defn):
        props = copy.deepcopy(res_defn)
        servers = props.pop(self.SERVERS)
        props[SoftwareDeployment.SERVER] = servers.get(res_name)
        return rsrc_defn.ResourceDefinition(res_name,
                                            'OS::Heat::SoftwareDeployment',
                                            props, None)

    def get_attribute(self, key, *path):
        rg = super(SoftwareDeploymentGroup, self)
        if key == self.STDOUTS:
            n_attr = SoftwareDeployment.STDOUT
        elif key == self.STDERRS:
            n_attr = SoftwareDeployment.STDERR
        elif key == self.STATUS_CODES:
            n_attr = SoftwareDeployment.STATUS_CODE
        else:
            # Allow any attribute valid for a single SoftwareDeployment
            # including arbitrary outputs, so we can't validate here
            n_attr = key

        rg_attr = rg.get_attribute(rg.ATTR_ATTRIBUTES, n_attr)
        return attributes.select_from_attribute(rg_attr, path)


class SoftwareDeployments(SoftwareDeploymentGroup):

    deprecation_msg = _('Use of this resource is discouraged. Please use '
                        'OS::Heat::SoftwareDeploymentGroup instead.')
    support_status = support.SupportStatus(status=support.DEPRECATED,
                                           message=deprecation_msg,
                                           version='2014.2')


def resource_mapping():
    return {
        'OS::Heat::SoftwareDeployment': SoftwareDeployment,
        'OS::Heat::SoftwareDeploymentGroup': SoftwareDeploymentGroup,
        'OS::Heat::SoftwareDeployments': SoftwareDeployments,
    }
