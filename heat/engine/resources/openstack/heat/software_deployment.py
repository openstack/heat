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
from heat.engine import support
from heat.rpc import api as rpc_api

cfg.CONF.import_opt('default_deployment_signal_transport',
                    'heat.common.config')

LOG = logging.getLogger(__name__)


class SoftwareDeployment(signal_responder.SignalResponder):
    '''
    This resource associates a server with some configuration which
    is to be deployed to that server.

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
    '''

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        CONFIG, SERVER, INPUT_VALUES,
        DEPLOY_ACTIONS, NAME, SIGNAL_TRANSPORT
    ) = (
        'config', 'server', 'input_values',
        'actions', 'name', 'signal_transport'
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
        DEPLOY_SIGNAL_VERB, DEPLOY_SIGNAL_TRANSPORT
    ) = (
        'deploy_server_id', 'deploy_action',
        'deploy_signal_id', 'deploy_stack_id',
        'deploy_resource_name', 'deploy_auth_url',
        'deploy_username', 'deploy_password',
        'deploy_project_id', 'deploy_user_id',
        'deploy_signal_verb', 'deploy_signal_transport'
    )

    SIGNAL_TRANSPORTS = (
        CFN_SIGNAL, TEMP_URL_SIGNAL, HEAT_SIGNAL, NO_SIGNAL
    ) = (
        'CFN_SIGNAL', 'TEMP_URL_SIGNAL', 'HEAT_SIGNAL', 'NO_SIGNAL'
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
            _('ID of Nova server to apply configuration to.'),
            constraints=[
                constraints.CustomConstraint('nova.server')
            ]
        ),
        INPUT_VALUES: properties.Schema(
            properties.Schema.MAP,
            _('Input values to apply to the software configuration on this '
              'server.'),
            update_allowed=True
        ),
        DEPLOY_ACTIONS: properties.Schema(
            properties.Schema.LIST,
            _('Which stack actions will result in this deployment being '
              'triggered.'),
            update_allowed=True,
            default=[resource.Resource.CREATE, resource.Resource.UPDATE],
            constraints=[constraints.AllowedValues(ALLOWED_DEPLOY_ACTIONS)]
        ),
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the derived config associated with this deployment. '
              'This is used to apply a sort order to the list of '
              'configurations currently deployed to a server.'),
        ),
        SIGNAL_TRANSPORT: properties.Schema(
            properties.Schema.STRING,
            _('How the server should signal to heat with the deployment '
              'output values. CFN_SIGNAL will allow an HTTP POST to a CFN '
              'keypair signed URL. TEMP_URL_SIGNAL will create a '
              'Swift TempURL to be signaled via HTTP PUT. HEAT_SIGNAL '
              'will allow calls to the Heat API resource-signal using the '
              'provided keystone credentials. NO_SIGNAL will result in the '
              'resource going to the COMPLETE state without waiting for '
              'any signal.'),
            default=cfg.CONF.default_deployment_signal_transport,
            constraints=[
                constraints.AllowedValues(SIGNAL_TRANSPORTS),
            ]
        ),
    }

    attributes_schema = {
        STDOUT: attributes.Schema(
            _("Captured stdout from the configuration execution.")
        ),
        STDERR: attributes.Schema(
            _("Captured stderr from the configuration execution.")
        ),
        STATUS_CODE: attributes.Schema(
            _("Returned status code from the configuration execution")
        ),
    }

    default_client_name = 'heat'

    no_signal_actions = ()

    def _signal_transport_cfn(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.CFN_SIGNAL

    def _signal_transport_heat(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.HEAT_SIGNAL

    def _signal_transport_none(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.NO_SIGNAL

    def _signal_transport_temp_url(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.TEMP_URL_SIGNAL

    def _build_properties(self, properties, config_id, action):
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

        if (action not in self.properties[self.DEPLOY_ACTIONS]
                and not config.get(
                    rpc_api.SOFTWARE_CONFIG_GROUP) == 'component'):
            return

        props = self._build_properties(
            self.properties,
            self._get_derived_config(action, config),
            action)

        if self.resource_id is None:
            sd = self.rpc_client().create_software_deployment(
                self.context,
                server_id=self.properties[SoftwareDeployment.SERVER],
                stack_user_project_id=self.stack.stack_user_project_id,
                **props)
            self.resource_id_set(sd[rpc_api.SOFTWARE_DEPLOYMENT_ID])
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
            return sd

    def _check_complete(self):
        sd = self.rpc_client().show_software_deployment(
            self.context, self.resource_id)
        status = sd[rpc_api.SOFTWARE_DEPLOYMENT_STATUS]
        if status == SoftwareDeployment.COMPLETE:
            return True
        elif status == SoftwareDeployment.FAILED:
            status_reason = sd[rpc_api.SOFTWARE_DEPLOYMENT_STATUS_REASON]
            message = _("Deployment to server "
                        "failed: %s") % status_reason
            LOG.error(message)
            exc = exception.Error(message)
            raise exc

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

    def _get_temp_url(self):
        put_url = self.data().get('signal_temp_url')
        if put_url:
            return put_url

        container = self.physical_resource_name()
        object_name = str(uuid.uuid4())

        self.client('swift').put_container(container)

        put_url = self.client_plugin('swift').get_temp_url(
            container, object_name)
        self.data_set('signal_temp_url', put_url)
        self.data_set('signal_object_name', object_name)

        self.client('swift').put_object(
            container, object_name, '')
        return put_url

    def _delete_temp_url(self):
        object_name = self.data().get('signal_object_name')
        if not object_name:
            return
        try:
            container = self.physical_resource_name()
            swift = self.client('swift')
            swift.delete_object(container, object_name)
            headers = swift.head_container(container)
            if int(headers['x-container-object-count']) == 0:
                swift.delete_container(container)
        except Exception as ex:
            self.client_plugin('swift').ignore_not_found(ex)
        self.data_delete('signal_object_name')
        self.data_delete('signal_temp_url')

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
            'value': self.properties.get(self.SERVER)
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
            'value': self.properties.get(self.SIGNAL_TRANSPORT)
        }])
        if self._signal_transport_cfn():
            inputs.append({
                scl.NAME: self.DEPLOY_SIGNAL_ID,
                scl.DESCRIPTION: _('ID of signal to use for signaling '
                                   'output values'),
                scl.TYPE: 'String',
                'value': self._get_signed_url()
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
                'value': self._get_temp_url()
            })
            inputs.append({
                scl.NAME: self.DEPLOY_SIGNAL_VERB,
                scl.DESCRIPTION: _('HTTP verb to use for signaling '
                                   'output values'),
                scl.TYPE: 'String',
                'value': 'PUT'
            })
        elif self._signal_transport_heat():
            inputs.extend([{
                scl.NAME: self.DEPLOY_AUTH_URL,
                scl.DESCRIPTION: _('URL for API authentication'),
                scl.TYPE: 'String',
                'value': self.keystone().v3_endpoint
            }, {
                scl.NAME: self.DEPLOY_USERNAME,
                scl.DESCRIPTION: _('Username for API authentication'),
                scl.TYPE: 'String',
                'value': self.physical_resource_name(),
            }, {
                scl.NAME: self.DEPLOY_USER_ID,
                scl.DESCRIPTION: _('User ID for API authentication'),
                scl.TYPE: 'String',
                'value': self._get_user_id(),
            }, {
                scl.NAME: self.DEPLOY_PASSWORD,
                scl.DESCRIPTION: _('Password for API authentication'),
                scl.TYPE: 'String',
                'value': self.password
            }, {
                scl.NAME: self.DEPLOY_PROJECT_ID,
                scl.DESCRIPTION: _('ID of project for API authentication'),
                scl.TYPE: 'String',
                'value': self.stack.stack_user_project_id
            }])

        return inputs

    def handle_create(self):
        if self._signal_transport_cfn():
            self._create_user()
            self._create_keypair()
        if self._signal_transport_heat():
            self.password = uuid.uuid4().hex
            self._create_user()
        return self._handle_action(self.CREATE)

    @property
    def password(self):
        return self.data().get('password')

    @password.setter
    def password(self, password):
        if password is None:
            self.data_delete('password')
        else:
            self.data_set('password', password, True)

    def check_create_complete(self, sd):
        if not sd:
            return True
        return self._check_complete()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.properties = json_snippet.properties(self.properties_schema,
                                                      self.context)

        return self._handle_action(self.UPDATE)

    def check_update_complete(self, sd):
        if not sd:
            return True
        return self._check_complete()

    def handle_delete(self):
        try:
            return self._handle_action(self.DELETE)
        except Exception as ex:
            self.rpc_client().ignore_error_named(ex, 'NotFound')

    def check_delete_complete(self, sd=None):
        if not sd or self._check_complete():
            self._delete_resource()
            return True

    def _delete_resource(self):
        if self._signal_transport_cfn():
            self._delete_signed_url()
            self._delete_user()
        elif self._signal_transport_heat():
            self._delete_user()
        elif self._signal_transport_temp_url():
            self._delete_temp_url()

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
        return self._handle_action(self.SUSPEND)

    def check_suspend_complete(self, sd):
        if not sd:
            return True
        return self._check_complete()

    def handle_resume(self):
        return self._handle_action(self.RESUME)

    def check_resume_complete(self, sd):
        if not sd:
            return True
        return self._check_complete()

    def handle_signal(self, details):
        return self.rpc_client().signal_software_deployment(
            self.context, self.resource_id, details,
            timeutils.strtime())

    def FnGetAtt(self, key, *path):
        '''
        Resource attributes map to deployment outputs values
        '''
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
        '''
        Validate any of the provided params

        :raises StackValidationFailed: if any property failed validation.
        '''
        super(SoftwareDeployment, self).validate()
        server = self.properties.get(self.SERVER)
        if server:
            res = self.stack.resource_by_refid(server)
            if res:
                if not res.user_data_software_config():
                    raise exception.StackValidationFailed(message=_(
                        "Resource %s's property user_data_format should be "
                        "set to SOFTWARE_CONFIG since there are software "
                        "deployments on it.") % server)


class SoftwareDeployments(resource_group.ResourceGroup):

    support_status = support.SupportStatus(version='2014.2')

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
              "configuration execution to each server.")
        ),
        STDERRS: attributes.Schema(
            _("A map of Nova names and captured stderrs from the "
              "configuration execution to each server.")
        ),
        STATUS_CODES: attributes.Schema(
            _("A map of Nova names and returned status code from the "
              "configuration execution")
        ),
    }

    def _resource_names(self):
        return self.properties.get(self.SERVERS, {}).keys()

    def _do_prop_replace(self, res_name, res_def_template):
        res_def = copy.deepcopy(res_def_template)
        props = res_def[self.RESOURCE_DEF_PROPERTIES]
        servers = self.properties.get(self.SERVERS, {})
        props[SoftwareDeployment.SERVER] = servers.get(res_name)
        return res_def

    def _build_resource_definition(self, include_all=False):
        p = self.properties
        return {
            self.RESOURCE_DEF_TYPE: 'OS::Heat::SoftwareDeployment',
            self.RESOURCE_DEF_PROPERTIES: {
                self.CONFIG: p[self.CONFIG],
                self.INPUT_VALUES: p[self.INPUT_VALUES],
                self.DEPLOY_ACTIONS: p[self.DEPLOY_ACTIONS],
                self.SIGNAL_TRANSPORT: p[self.SIGNAL_TRANSPORT],
                self.NAME: p[self.NAME],
            }
        }

    def FnGetAtt(self, key, *path):
        rg = super(SoftwareDeployments, self)
        if key == self.STDOUTS:
            return rg.FnGetAtt(
                rg.ATTR_ATTRIBUTES, SoftwareDeployment.STDOUT)
        if key == self.STDERRS:
            return rg.FnGetAtt(
                rg.ATTR_ATTRIBUTES, SoftwareDeployment.STDERR)
        if key == self.STATUS_CODES:
            return rg.FnGetAtt(
                rg.ATTR_ATTRIBUTES, SoftwareDeployment.STATUS_CODE)


def resource_mapping():
    return {
        'OS::Heat::SoftwareDeployment': SoftwareDeployment,
        'OS::Heat::SoftwareDeployments': SoftwareDeployments,
    }
