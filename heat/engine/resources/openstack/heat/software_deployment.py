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
from six import itertools
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import output
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.openstack.heat import resource_group
from heat.engine.resources import signal_responder
from heat.engine import rsrc_defn
from heat.engine import software_config_io as swc_io
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
    inputs which have names prefixed with ``deploy_``. The extra inputs relate
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
        DEPLOY_SIGNAL_VERB, DEPLOY_SIGNAL_TRANSPORT,
        DEPLOY_QUEUE_ID, DEPLOY_REGION_NAME
    ) = (
        'deploy_server_id', 'deploy_action',
        'deploy_signal_id', 'deploy_stack_id',
        'deploy_resource_name', 'deploy_auth_url',
        'deploy_username', 'deploy_password',
        'deploy_project_id', 'deploy_user_id',
        'deploy_signal_verb', 'deploy_signal_transport',
        'deploy_queue_id', 'deploy_region_name'
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

    def _build_properties(self, config_id, action):
        props = {
            'config_id': config_id,
            'action': action,
            'input_values': self.properties.get(self.INPUT_VALUES)
        }

        if self._signal_transport_none():
            props['status'] = SoftwareDeployment.COMPLETE
            props['status_reason'] = _('Not waiting for outputs signal')
        else:
            props['status'] = SoftwareDeployment.IN_PROGRESS
            props['status_reason'] = _('Deploy data available')
        return props

    def _delete_derived_config(self, derived_config_id):
        with self.rpc_client().ignore_error_by_name('NotFound'):
            self.rpc_client().delete_software_config(
                self.context, derived_config_id)

    def _create_derived_config(self, action, source_config):

        derived_params = self._build_derived_config_params(
            action, source_config)
        derived_config = self.rpc_client().create_software_config(
            self.context, **derived_params)
        return derived_config[rpc_api.SOFTWARE_CONFIG_ID]

    def _get_derived_config_id(self):
        sd = self.rpc_client().show_software_deployment(self.context,
                                                        self.resource_id)
        return sd[rpc_api.SOFTWARE_DEPLOYMENT_CONFIG_ID]

    def _load_config(self, config_id=None):
        if config_id is None:
            config_id = self.properties.get(self.CONFIG)
        if config_id:
            config = self.rpc_client().show_software_config(self.context,
                                                            config_id)
        else:
            config = {}

        config[rpc_api.SOFTWARE_CONFIG_INPUTS] = [
            swc_io.InputConfig(**i)
            for i in config.get(rpc_api.SOFTWARE_CONFIG_INPUTS, [])
        ]
        config[rpc_api.SOFTWARE_CONFIG_OUTPUTS] = [
            swc_io.OutputConfig(**o)
            for o in config.get(rpc_api.SOFTWARE_CONFIG_OUTPUTS, [])
        ]

        return config

    def _handle_action(self, action, config=None, prev_derived_config=None):
        if config is None:
            config = self._load_config()

        if config.get(rpc_api.SOFTWARE_CONFIG_GROUP) == 'component':
            valid_actions = set()
            for conf in config[rpc_api.SOFTWARE_CONFIG_CONFIG]['configs']:
                valid_actions.update(conf['actions'])
            if action not in valid_actions:
                return
        elif action not in self.properties[self.DEPLOY_ACTIONS]:
            return

        props = self._build_properties(
            self._create_derived_config(action, config),
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
            if prev_derived_config is None:
                prev_derived_config = self._get_derived_config_id()
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

    def _check_complete(self):
        sd = self.rpc_client().show_software_deployment(
            self.context, self.resource_id)
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
        derived_inputs = self._build_derived_inputs(action, source)
        derived_options = self._build_derived_options(action, source)
        derived_config = self._build_derived_config(
            action, source, derived_inputs, derived_options)
        derived_name = (self.properties.get(self.NAME) or
                        source.get(rpc_api.SOFTWARE_CONFIG_NAME))
        return {
            rpc_api.SOFTWARE_CONFIG_GROUP:
                source.get(rpc_api.SOFTWARE_CONFIG_GROUP) or 'Heat::Ungrouped',
            rpc_api.SOFTWARE_CONFIG_CONFIG:
                derived_config or self.empty_config(),
            rpc_api.SOFTWARE_CONFIG_OPTIONS: derived_options,
            rpc_api.SOFTWARE_CONFIG_INPUTS:
                [i.as_dict() for i in derived_inputs],
            rpc_api.SOFTWARE_CONFIG_OUTPUTS:
                [o.as_dict() for o in source[rpc_api.SOFTWARE_CONFIG_OUTPUTS]],
            rpc_api.SOFTWARE_CONFIG_NAME:
                derived_name or self.physical_resource_name()
        }

    def _build_derived_config(self, action, source,
                              derived_inputs, derived_options):
        return source.get(rpc_api.SOFTWARE_CONFIG_CONFIG)

    def _build_derived_options(self, action, source):
        return source.get(rpc_api.SOFTWARE_CONFIG_OPTIONS)

    def _build_derived_inputs(self, action, source):
        inputs = source[rpc_api.SOFTWARE_CONFIG_INPUTS]
        input_values = dict(self.properties[self.INPUT_VALUES] or {})

        def derive_inputs():
            for input_config in inputs:
                value = input_values.pop(input_config.name(),
                                         input_config.default())
                yield swc_io.InputConfig(value=value, **input_config.as_dict())

            # for any input values that do not have a declared input, add
            # a derived declared input so that they can be used as config
            # inputs
            for inpk, inpv in input_values.items():
                yield swc_io.InputConfig(name=inpk, value=inpv)

            yield swc_io.InputConfig(
                name=self.DEPLOY_SERVER_ID, value=self.properties[self.SERVER],
                description=_('ID of the server being deployed to'))
            yield swc_io.InputConfig(
                name=self.DEPLOY_ACTION, value=action,
                description=_('Name of the current action being deployed'))
            yield swc_io.InputConfig(
                name=self.DEPLOY_STACK_ID,
                value=self.stack.identifier().stack_path(),
                description=_('ID of the stack this deployment belongs to'))
            yield swc_io.InputConfig(
                name=self.DEPLOY_RESOURCE_NAME, value=self.name,
                description=_('Name of this deployment resource in the stack'))
            yield swc_io.InputConfig(
                name=self.DEPLOY_SIGNAL_TRANSPORT,
                value=self.properties[self.SIGNAL_TRANSPORT],
                description=_('How the server should signal to heat with '
                              'the deployment output values.'))

            if self._signal_transport_cfn():
                yield swc_io.InputConfig(
                    name=self.DEPLOY_SIGNAL_ID,
                    value=self._get_ec2_signed_url(),
                    description=_('ID of signal to use for signaling output '
                                  'values'))
                yield swc_io.InputConfig(
                    name=self.DEPLOY_SIGNAL_VERB, value='POST',
                    description=_('HTTP verb to use for signaling output '
                                  'values'))

            elif self._signal_transport_temp_url():
                yield swc_io.InputConfig(
                    name=self.DEPLOY_SIGNAL_ID,
                    value=self._get_swift_signal_url(),
                    description=_('ID of signal to use for signaling output '
                                  'values'))
                yield swc_io.InputConfig(
                    name=self.DEPLOY_SIGNAL_VERB, value='PUT',
                    description=_('HTTP verb to use for signaling output '
                                  'values'))

            elif (self._signal_transport_heat() or
                  self._signal_transport_zaqar()):
                creds = self._get_heat_signal_credentials()
                yield swc_io.InputConfig(
                    name=self.DEPLOY_AUTH_URL, value=creds['auth_url'],
                    description=_('URL for API authentication'))
                yield swc_io.InputConfig(
                    name=self.DEPLOY_USERNAME, value=creds['username'],
                    description=_('Username for API authentication'))
                yield swc_io.InputConfig(
                    name=self.DEPLOY_USER_ID, value=creds['user_id'],
                    description=_('User ID for API authentication'))
                yield swc_io.InputConfig(
                    name=self.DEPLOY_PASSWORD, value=creds['password'],
                    description=_('Password for API authentication'))
                yield swc_io.InputConfig(
                    name=self.DEPLOY_PROJECT_ID, value=creds['project_id'],
                    description=_('ID of project for API authentication'))
                yield swc_io.InputConfig(
                    name=self.DEPLOY_REGION_NAME, value=creds['region_name'],
                    description=_('Region name for API authentication'))
            if self._signal_transport_zaqar():
                yield swc_io.InputConfig(
                    name=self.DEPLOY_QUEUE_ID,
                    value=self._get_zaqar_signal_queue_id(),
                    description=_('ID of queue to use for signaling output '
                                  'values'))

        return list(derive_inputs())

    def handle_create(self):
        return self._handle_action(self.CREATE)

    def check_create_complete(self, sd):
        if not sd:
            return True
        return self._check_complete()

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if self.resource_id is None:
            prev_derived_config = None
            old_inputs = {}
        else:
            prev_derived_config = self._get_derived_config_id()
            old_config = self._load_config(prev_derived_config)
            old_inputs = {i.name(): i
                          for i in old_config[rpc_api.SOFTWARE_CONFIG_INPUTS]}

        self.properties = json_snippet.properties(self.properties_schema,
                                                  self.context)

        config = self._load_config()

        for inp in self._build_derived_inputs(self.UPDATE, config):
            name = inp.name()
            if inp.replace_on_change() and name in old_inputs:
                if inp.input_data() != old_inputs[name].input_data():
                    LOG.debug('Replacing SW Deployment due to change in '
                              'input "%s"', name)
                    raise resource.UpdateReplace

        return self._handle_action(self.UPDATE, config=config,
                                   prev_derived_config=prev_derived_config)

    def check_update_complete(self, sd):
        if not sd:
            return True
        return self._check_complete()

    def handle_delete(self):
        with self.rpc_client().ignore_error_by_name('NotFound'):
            return self._handle_action(self.DELETE)

    def check_delete_complete(self, sd=None):
        if not sd or not self._server_exists(sd) or self._check_complete():
            self._delete_resource()
            return True

    def _delete_resource(self):
        derived_config_id = None
        if self.resource_id is not None:
            with self.rpc_client().ignore_error_by_name('NotFound'):
                derived_config_id = self._get_derived_config_id()
                self.rpc_client().delete_software_deployment(
                    self.context, self.resource_id)

        if derived_config_id:
            self._delete_derived_config(derived_config_id)

        self._delete_signals()
        self._delete_user()

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
            timeutils.utcnow().isoformat())

    def _handle_cancel(self):
        if self.resource_id is None:
            return

        sd = self.rpc_client().show_software_deployment(
            self.context, self.resource_id)

        if sd is None:
            return

        status = sd[rpc_api.SOFTWARE_DEPLOYMENT_STATUS]
        if status == SoftwareDeployment.IN_PROGRESS:
            self.rpc_client().update_software_deployment(
                self.context, self.resource_id,
                status=SoftwareDeployment.FAILED,
                status_reason=_('Deployment cancelled.'))

    def handle_create_cancel(self, cookie):
        self._handle_cancel()

    def handle_update_cancel(self, cookie):
        self._handle_cancel()

    def handle_delete_cancel(self, cookie):
        self._handle_cancel()

    def handle_suspend_cancel(self, cookie):
        self._handle_cancel()

    def handle_resume_cancel(self, cookie):
        self._handle_cancel()

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
                user_data_format = res.properties.get('user_data_format')
                if user_data_format and \
                   not (user_data_format == 'SOFTWARE_CONFIG'):
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

    _ROLLING_UPDATES_SCHEMA_KEYS = (
        MAX_BATCH_SIZE,
        PAUSE_TIME,
    ) = (
        resource_group.ResourceGroup.MAX_BATCH_SIZE,
        resource_group.ResourceGroup.PAUSE_TIME,
    )

    _sd_ps = SoftwareDeployment.properties_schema
    _rg_ps = resource_group.ResourceGroup.properties_schema

    properties_schema = {
        SERVERS: properties.Schema(
            properties.Schema.MAP,
            _('A map of names and server IDs to apply configuration to. The '
              'name is arbitrary and is used as the Heat resource name '
              'for the corresponding deployment.'),
            update_allowed=True,
            required=True
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

    rolling_update_schema = {
        MAX_BATCH_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('The maximum number of deployments to replace at once.'),
            constraints=[constraints.Range(min=1)],
            default=1),
        PAUSE_TIME: properties.Schema(
            properties.Schema.NUMBER,
            _('The number of seconds to wait between batches of '
              'updates.'),
            constraints=[constraints.Range(min=0)],
            default=0),
    }

    update_policy_schema = {
        resource_group.ResourceGroup.ROLLING_UPDATE: properties.Schema(
            properties.Schema.MAP,
            schema=rolling_update_schema,
            support_status=support.SupportStatus(version='7.0.0')
        ),
        resource_group.ResourceGroup.BATCH_CREATE: properties.Schema(
            properties.Schema.MAP,
            schema=resource_group.ResourceGroup.batch_create_schema,
            support_status=support.SupportStatus(version='7.0.0')
        )
    }

    def get_size(self):
        return len(self.properties[self.SERVERS])

    def _resource_names(self, size=None,
                        update_rsrc_data=True):
        candidates = self.properties[self.SERVERS]
        if size is None:
            return iter(candidates)
        return itertools.islice(candidates, size)

    def res_def_changed(self, prop_diff):
        return True

    def _update_name_blacklist(self, properties):
        pass

    def _name_blacklist(self):
        return set()

    def get_resource_def(self, include_all=False):
        return dict(self.properties)

    def build_resource_definition(self, res_name, res_defn):
        props = copy.deepcopy(res_defn)
        servers = props.pop(self.SERVERS)
        props[SoftwareDeployment.SERVER] = servers.get(res_name)
        return rsrc_defn.ResourceDefinition(res_name,
                                            'OS::Heat::SoftwareDeployment',
                                            props, None)

    def _member_attribute_name(self, key):
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
        return n_attr

    def get_attribute(self, key, *path):
        rg = super(SoftwareDeploymentGroup, self)
        n_attr = self._member_attribute_name(key)

        rg_attr = rg.get_attribute(rg.ATTR_ATTRIBUTES, n_attr)
        return attributes.select_from_attribute(rg_attr, path)

    def _nested_output_defns(self, resource_names, get_attr_fn, get_res_fn):
        for attr in self.referenced_attrs():
            key = attr if isinstance(attr, six.string_types) else attr[0]
            n_attr = self._member_attribute_name(key)
            output_name = self._attribute_output_name(self.ATTR_ATTRIBUTES,
                                                      n_attr)
            value = {r: get_attr_fn([r, n_attr])
                     for r in resource_names}
            yield output.OutputDefinition(output_name, value)

    def _try_rolling_update(self):
        if self.update_policy[self.ROLLING_UPDATE]:
            policy = self.update_policy[self.ROLLING_UPDATE]
            return self._replace(0,
                                 policy[self.MAX_BATCH_SIZE],
                                 policy[self.PAUSE_TIME])


class SoftwareDeployments(SoftwareDeploymentGroup):

    hidden_msg = _('Please use OS::Heat::SoftwareDeploymentGroup instead.')
    support_status = support.SupportStatus(
        status=support.HIDDEN,
        message=hidden_msg,
        version='7.0.0',
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            version='2014.2'),
        substitute_class=SoftwareDeploymentGroup)


def resource_mapping():
    return {
        'OS::Heat::SoftwareDeployment': SoftwareDeployment,
        'OS::Heat::SoftwareDeploymentGroup': SoftwareDeploymentGroup,
        'OS::Heat::SoftwareDeployments': SoftwareDeployments,
    }
