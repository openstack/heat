

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

"""
Routines for configuring Heat
"""
import copy
import logging as sys_logging
import os

from eventlet.green import socket
from oslo.config import cfg

from heat.common import wsgi

from heat.openstack.common import log as logging
from heat.openstack.common import rpc

logger = logging.getLogger(__name__)

paste_deploy_group = cfg.OptGroup('paste_deploy')
paste_deploy_opts = [
    cfg.StrOpt('flavor',
               help=_("The flavor to use.")),
    cfg.StrOpt('api_paste_config', default="api-paste.ini",
               help=_("The API paste config file to use."))]


service_opts = [
    cfg.IntOpt('periodic_interval',
               default=60,
               help='Seconds between running periodic tasks.'),
    cfg.StrOpt('heat_metadata_server_url',
               default="",
               help='URL of the Heat metadata server.'),
    cfg.StrOpt('heat_waitcondition_server_url',
               default="",
               help='URL of the Heat waitcondition server.'),
    cfg.StrOpt('heat_watch_server_url',
               default="",
               help='URL of the Heat CloudWatch server.'),
    cfg.StrOpt('instance_connection_is_secure',
               default="0",
               help='Instance connection to CFN/CW API via https.'),
    cfg.StrOpt('instance_connection_https_validate_certificates',
               default="1",
               help='Instance connection to CFN/CW API validate certs if SSL '
                    'is used.'),
    cfg.StrOpt('region_name_for_services',
               default=None,
               help='Default region name used to get services endpoints.'),
    cfg.StrOpt('heat_stack_user_role',
               default="heat_stack_user",
               help='Keystone role for heat template-defined users.'),
    cfg.StrOpt('stack_user_domain',
               help='Keystone domain ID which contains heat template-defined '
                    'users.'),
    cfg.StrOpt('stack_domain_admin',
               help='Keystone username, a user with roles sufficient to '
                    'manage users and projects in the stack_user_domain.'),
    cfg.StrOpt('stack_domain_admin_password',
               help='Keystone password for stack_domain_admin user.'),
    cfg.IntOpt('max_template_size',
               default=524288,
               help='Maximum raw byte size of any template.'),
    cfg.IntOpt('max_nested_stack_depth',
               default=3,
               help='Maximum depth allowed when using nested stacks.')]

engine_opts = [
    cfg.StrOpt('instance_user',
               default='ec2-user',
               help="The default user for new instances. This option "
                    "is deprecated and will be removed in the Juno release. "
                    "If it's empty, Heat will use the default user set up "
                    "with your cloud image (for OS::Nova::Server) or "
                    "'ec2-user' (for AWS::EC2::Instance)."),
    cfg.StrOpt('instance_driver',
               default='heat.engine.nova',
               help='Driver to use for controlling instances.'),
    cfg.ListOpt('plugin_dirs',
                default=['/usr/lib64/heat', '/usr/lib/heat'],
                help='List of directories to search for plug-ins.'),
    cfg.StrOpt('environment_dir',
               default='/etc/heat/environment.d',
               help='The directory to search for environment files.'),
    cfg.StrOpt('deferred_auth_method',
               choices=['password', 'trusts'],
               default='password',
               help=_('Select deferred auth method, '
                      'stored password or trusts.')),
    cfg.ListOpt('trusts_delegated_roles',
                default=['heat_stack_owner'],
                help=_('Subset of trustor roles to be delegated to heat.')),
    cfg.IntOpt('max_resources_per_stack',
               default=1000,
               help='Maximum resources allowed per top-level stack.'),
    cfg.IntOpt('max_stacks_per_tenant',
               default=100,
               help=_('Maximum number of stacks any one tenant may have'
                      ' active at one time.')),
    cfg.IntOpt('event_purge_batch_size',
               default=10,
               help=_('Controls how many events will be pruned whenever a '
                      ' stack\'s events exceed max_events_per_stack. Set this'
                      ' lower to keep more events at the expense of more'
                      ' frequent purges.')),
    cfg.IntOpt('max_events_per_stack',
               default=1000,
               help=_('Maximum events that will be available per stack. Older'
                      ' events will be deleted when this is reached. Set to 0'
                      ' for unlimited events per stack.')),
    cfg.IntOpt('stack_action_timeout',
               default=3600,
               help=_('Timeout in seconds for stack action (ie. create or'
                      ' update).')),
    cfg.IntOpt('engine_life_check_timeout',
               default=2,
               help=_('RPC timeout for the engine liveness check that is used'
                      ' for stack locking.')),
    cfg.StrOpt('onready',
               help=_('onready allows you to send a notification when the'
                      ' heat processes are ready to serve.  This is either a'
                      ' module with the notify() method or a shell command. '
                      ' To enable notifications with systemd, one may use'
                      ' the \'systemd-notify --ready\' shell command or'
                      ' the \'heat.common.systemd\' notification module.'))]

rpc_opts = [
    cfg.StrOpt('host',
               default=socket.gethostname(),
               help='Name of the engine node. '
                    'This can be an opaque identifier. '
                    'It is not necessarily a hostname, FQDN, or IP address.')]

auth_password_group = cfg.OptGroup('auth_password')
auth_password_opts = [
    cfg.BoolOpt('multi_cloud',
                default=False,
                help=_('Allow orchestration of multiple clouds.')),
    cfg.ListOpt('allowed_auth_uris',
                default=[],
                help=_('Allowed keystone endpoints for auth_uri when '
                       'multi_cloud is enabled. At least one endpoint needs '
                       'to be specified.'))]
clients_opts = [
    cfg.StrOpt('endpoint_type',
               default='publicURL',
               help=_(
                   'Type of endpoint in Identity service catalog to use '
                   'for communication with the OpenStack service.')),
    cfg.StrOpt('ca_file',
               help=_('Optional CA cert file to use in SSL connections.')),
    cfg.StrOpt('cert_file',
               help=_('Optional PEM-formatted certificate chain file.')),
    cfg.StrOpt('key_file',
               help=_('Optional PEM-formatted file that contains the '
                      'private key.')),
    cfg.BoolOpt('insecure',
                default=False,
                help=_("If set, then the server's certificate will not "
                       "be verified."))]


def register_clients_opts():
    cfg.CONF.register_opts(clients_opts, group='clients')
    for client in ('nova', 'swift', 'neutron', 'cinder',
                   'ceilometer', 'keystone', 'heat', 'trove'):
        client_specific_group = 'clients_' + client
        # register opts copy and put it to globals in order to
        # generate_sample.sh to work
        opts_copy = copy.deepcopy(clients_opts)
        if client == 'heat':
            opts_copy.append(
                cfg.StrOpt('url',
                           help=_('Optional heat url in format like'
                                  ' http://0.0.0.0:8004/v1/%(tenant_id)s.')))
        globals()[client_specific_group + '_opts'] = opts_copy
        cfg.CONF.register_opts(opts_copy, group=client_specific_group)


revision_group = cfg.OptGroup('revision')
revision_opts = [
    cfg.StrOpt('heat_revision',
               default='unknown',
               help=_('Heat build revision. '
                      'If you would prefer to manage your build revision '
                      'separately, you can move this section to a different '
                      'file and add it as another config option.'))]

cfg.CONF.register_opts(engine_opts)
cfg.CONF.register_opts(service_opts)
cfg.CONF.register_opts(rpc_opts)
rpc.set_defaults(control_exchange='heat')
cfg.CONF.register_group(paste_deploy_group)
cfg.CONF.register_opts(paste_deploy_opts, group=paste_deploy_group)
cfg.CONF.register_group(auth_password_group)
cfg.CONF.register_opts(auth_password_opts, group=auth_password_group)
cfg.CONF.register_group(revision_group)
cfg.CONF.register_opts(revision_opts, group=revision_group)
register_clients_opts()

# A bit of history:
# This was added initially by jianingy, then it got added
# to oslo by Luis. Then it was receintly removed from the
# default list again.
# I am not sure we can (or should) rely on oslo to keep
# our exceptions class in the defaults list.
allowed_rpc_exception_modules = cfg.CONF.allowed_rpc_exception_modules
allowed_rpc_exception_modules.append('heat.common.exception')
cfg.CONF.set_default(name='allowed_rpc_exception_modules',
                     default=allowed_rpc_exception_modules)

if cfg.CONF.instance_user:
    logger.warn(_('The "instance_user" option in heat.conf is deprecated and '
                  'will be removed in the Juno release.'))


def _get_deployment_flavor():
    """
    Retrieve the paste_deploy.flavor config item, formatted appropriately
    for appending to the application name.
    """
    flavor = cfg.CONF.paste_deploy.flavor
    return '' if not flavor else ('-' + flavor)


def _get_deployment_config_file():
    """
    Retrieve the deployment_config_file config item, formatted as an
    absolute pathname.
    """
    config_path = cfg.CONF.find_file(
        cfg.CONF.paste_deploy['api_paste_config'])
    if config_path is None:
        return None

    return os.path.abspath(config_path)


def load_paste_app(app_name=None):
    """
    Builds and returns a WSGI app from a paste config file.

    We assume the last config file specified in the supplied ConfigOpts
    object is the paste config file.

    :param app_name: name of the application to load

    :raises RuntimeError when config file cannot be located or application
            cannot be loaded from config file
    """
    if app_name is None:
        app_name = cfg.CONF.prog

    # append the deployment flavor to the application name,
    # in order to identify the appropriate paste pipeline
    app_name += _get_deployment_flavor()

    conf_file = _get_deployment_config_file()
    if conf_file is None:
        raise RuntimeError(_("Unable to locate config file"))

    try:
        app = wsgi.paste_deploy_app(conf_file, app_name, cfg.CONF)

        # Log the options used when starting if we're in debug mode...
        if cfg.CONF.debug:
            cfg.CONF.log_opt_values(logging.getLogger(app_name),
                                    sys_logging.DEBUG)

        return app
    except (LookupError, ImportError) as e:
        raise RuntimeError(_("Unable to load %(app_name)s from "
                             "configuration file %(conf_file)s."
                             "\nGot: %(e)r") % {'app_name': app_name,
                                                'conf_file': conf_file,
                                                'e': e})
