# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import heatclient.exc as heat_exp

from heat.common import exception
from heat.db import api as db_api
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.software_config import software_config as sc
from heat.engine import signal_responder
from heat.openstack.common import log as logging

logger = logging.getLogger(__name__)


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

    DEPLOY_ATTRIBUTES = (
        STDOUT, STDERR, STATUS_CODE
    ) = (
        'deploy_stdout', 'deploy_stderr', 'deploy_status_code'
    )

    DERIVED_CONFIG_INPUTS = (
        DEPLOY_SERVER_ID, DEPLOY_ACTION,
        DEPLOY_SIGNAL_ID, DEPLOY_STACK_ID,
        DEPLOY_RESOURCE_NAME, DEPLOY_AUTH_URL,
        DEPLOY_USERNAME, DEPLOY_PASSWORD,
        DEPLOY_PROJECT_ID, DEPLOY_USER_ID
    ) = (
        'deploy_server_id', 'deploy_action',
        'deploy_signal_id', 'deploy_stack_id',
        'deploy_resource_name', 'deploy_auth_url',
        'deploy_username', 'deploy_password',
        'deploy_project_id', 'deploy_user_id'
    )

    SIGNAL_TRANSPORTS = (
        CFN_SIGNAL, HEAT_SIGNAL, NO_SIGNAL
    ) = (
        'CFN_SIGNAL', 'HEAT_SIGNAL', 'NO_SIGNAL'
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
              'keypair signed URL. HEAT_SIGNAL will allow calls to '
              'the Heat API resource-signal using the provided keystone '
              'credentials. NO_SIGNAL will result in the resource going to '
              'the COMPLETE state without waiting for any signal.'),
            default=CFN_SIGNAL,
            constraints=[
                constraints.AllowedValues(SIGNAL_TRANSPORTS),
            ]
        ),
    }

    attributes_schema = {
        STDOUT: _("Captured stdout from the configuration execution."),
        STDERR: _("Captured stderr from the configuration execution."),
        STATUS_CODE: _("Returned status code from the configuration "
                       "execution"),
    }

    update_allowed_keys = ('Properties',)

    def _signal_transport_cfn(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.CFN_SIGNAL

    def _signal_transport_heat(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.HEAT_SIGNAL

    def _signal_transport_none(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.NO_SIGNAL

    def _build_properties(self, properties, config_id, action):
        props = {
            'config_id': config_id,
            'server_id': properties[SoftwareDeployment.SERVER],
            'action': action,
            'stack_user_project_id': self.stack.stack_user_project_id
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
            self.heat().software_configs.delete(derived_config_id)
        except heat_exp.HTTPNotFound:
            pass

    def _get_derived_config(self, action):

        source_config_id = self.properties.get(self.CONFIG)
        source_config = self.heat().software_configs.get(source_config_id)
        derived_params = self._build_derived_config_params(
            action, source_config.to_dict())
        derived_config = self.heat().software_configs.create(**derived_params)
        return derived_config.id

    def _handle_action(self, action):
        if action not in self.properties[self.DEPLOY_ACTIONS]:
            return

        props = self._build_properties(
            self.properties,
            self._get_derived_config(action),
            action)

        if action == self.CREATE:
            sd = self.heat().software_deployments.create(**props)
            self.resource_id_set(sd.id)
        else:
            sd = self.heat().software_deployments.get(self.resource_id)
            previous_derived_config = sd.config_id
            sd.update(**props)
            if previous_derived_config:
                self._delete_derived_config(previous_derived_config)
        if not self._signal_transport_none():
            return sd

    @staticmethod
    def _check_complete(sd):
        if not sd:
            return True
        # NOTE(dprince): when lazy loading the sd attributes
        # we need to support multiple versions of heatclient
        if hasattr(sd, 'get'):
            sd.get()
        else:
            sd._get()
        if sd.status == SoftwareDeployment.COMPLETE:
            return True
        elif sd.status == SoftwareDeployment.FAILED:
            message = _("Deployment to server "
                        "failed: %s") % sd.status_reason
            logger.error(message)
            exc = exception.Error(message)
            raise exc

    def _build_derived_config_params(self, action, source):
        scl = sc.SoftwareConfig
        derived_inputs = self._build_derived_inputs(action, source)
        derived_options = self._build_derived_options(action, source)
        derived_config = self._build_derived_config(
            action, source, derived_inputs, derived_options)
        derived_name = self.properties.get(self.NAME) or source[scl.NAME]
        return {
            scl.GROUP: source[scl.GROUP],
            scl.CONFIG: derived_config,
            scl.OPTIONS: derived_options,
            scl.INPUTS: derived_inputs,
            scl.OUTPUTS: source.get(scl.OUTPUTS),
            scl.NAME: derived_name
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
        }])
        if self._signal_transport_cfn():
            inputs.append({
                scl.NAME: self.DEPLOY_SIGNAL_ID,
                scl.DESCRIPTION: _('ID of signal to use for signalling '
                                   'output values'),
                scl.TYPE: 'String',
                'value': self._get_signed_url()
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
        try:
            return db_api.resource_data_get(self, 'password')
        except exception.NotFound:
            pass

    @password.setter
    def password(self, password):
        try:
            if password is None:
                db_api.resource_data_delete(self, 'password')
            else:
                db_api.resource_data_set(self, 'password', password, True)
        except exception.NotFound:
            pass

    def check_create_complete(self, sd):
        return self._check_complete(sd)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            self.properties = properties.Properties(
                self.properties_schema,
                json_snippet.get('Properties', {}),
                self.stack.resolve_runtime_data,
                self.name,
                self.context)

        return self._handle_action(self.UPDATE)

    def check_update_complete(self, sd):
        return self._check_complete(sd)

    def handle_delete(self):
        if self.DELETE in self.properties[self.DEPLOY_ACTIONS]:
            return self._handle_action(self.DELETE)
        else:
            self._delete_resource()

    def check_delete_complete(self, sd=None):
        if not sd:
            return True
        if self._check_complete(sd):
            self._delete_resource()
            return True

    def _delete_resource(self):
        if self._signal_transport_cfn():
            self._delete_signed_url()
            self._delete_user()
        elif self._signal_transport_heat():
            self._delete_user()

        derived_config_id = None
        if self.resource_id is not None:
            try:
                sd = self.heat().software_deployments.get(self.resource_id)
                derived_config_id = sd.config_id
                sd.delete()
            except heat_exp.HTTPNotFound:
                pass

        if derived_config_id:
            self._delete_derived_config(derived_config_id)

    def handle_suspend(self):
        return self._handle_action(self.SUSPEND)

    def check_suspend_complete(self, sd):
        return self._check_complete(sd)

    def handle_resume(self):
        return self._handle_action(self.RESUME)

    def check_resume_complete(self, sd):
        return self._check_complete(sd)

    def handle_signal(self, details):
        sd = self.heat().software_deployments.get(self.resource_id)
        sc = self.heat().software_configs.get(self.properties[self.CONFIG])
        if not sd.status == self.IN_PROGRESS:
            # output values are only expected when in an IN_PROGRESS state
            return

        details = details or {}

        ov = sd.output_values or {}
        status = None
        status_reasons = {}
        if details.get(self.STATUS_CODE):
            status = self.FAILED
            status_reasons[self.STATUS_CODE] = _(
                'Deployment exited with non-zero status code: %s'
            ) % details.get(self.STATUS_CODE)

        for output in sc.outputs or []:
            out_key = output['name']
            if out_key in details:
                ov[out_key] = details[out_key]
                if output.get('error_output', False):
                    status = self.FAILED
                    status_reasons[out_key] = details[out_key]

        for out_key in self.DEPLOY_ATTRIBUTES:
            ov[out_key] = details.get(out_key)

        if status == self.FAILED:
            # build a status reason out of all of the values of outputs
            # flagged as error_output
            status_reason = ', '.join([' : '.join((k, str(status_reasons[k])))
                                       for k in status_reasons])
        else:
            status = self.COMPLETE
            status_reason = _('Outputs received')
        sd.update(output_values=ov, status=status, status_reason=status_reason)

    def FnGetAtt(self, key):
        '''
        Resource attributes map to deployment outputs values
        '''
        sd = self.heat().software_deployments.get(self.resource_id)
        if key in sd.output_values:
            return sd.output_values.get(key)

        # Since there is no value for this key yet, check the output schemas
        # to find out if the key is valid
        sc = self.heat().software_configs.get(self.properties[self.CONFIG])
        output_keys = [output['name'] for output in sc.outputs]
        if key not in output_keys and key not in self.DEPLOY_ATTRIBUTES:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)


def resource_mapping():
    return {
        'OS::Heat::SoftwareDeployment': SoftwareDeployment,
    }
