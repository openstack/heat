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

"""
Routines for configuring Heat
"""

import logging
import logging.config
import logging.handlers
import os
import socket
# TODO ^ eventlet.socket ?
import sys

from heat import version
from heat.common import wsgi
from heat.openstack.common import cfg

DEFAULT_PORT = 8000

paste_deploy_group = cfg.OptGroup('paste_deploy')
paste_deploy_opts = [
    cfg.StrOpt('flavor'),
    cfg.StrOpt('config_file'),
    ]

FLAGS = None

rpc_opts = [
    cfg.StrOpt('rpc_backend',
        default='heat.rpc.impl_qpid',
        help="The messaging module to use, defaults to kombu."),
    cfg.IntOpt('rpc_thread_pool_size',
               default=1024,
               help='Size of RPC thread pool'),
    cfg.IntOpt('rpc_conn_pool_size',
               default=30,
               help='Size of RPC connection pool'),
    cfg.IntOpt('rpc_response_timeout',
               default=60,
               help='Seconds to wait for a response from call or multicall'),
    cfg.StrOpt('qpid_hostname',
               default='localhost',
               help='Qpid broker hostname'),
    cfg.StrOpt('qpid_port',
               default='5672',
               help='Qpid broker port'),
    cfg.StrOpt('qpid_username',
               default='',
               help='Username for qpid connection'),
    cfg.StrOpt('qpid_password',
               default='',
               help='Password for qpid connection'),
    cfg.StrOpt('qpid_sasl_mechanisms',
               default='',
               help='Space separated list of SASL mechanisms to use for auth'),
    cfg.BoolOpt('qpid_reconnect',
                default=True,
                help='Automatically reconnect'),
    cfg.IntOpt('qpid_reconnect_timeout',
               default=0,
               help='Reconnection timeout in seconds'),
    cfg.IntOpt('qpid_reconnect_limit',
               default=0,
               help='Max reconnections before giving up'),
    cfg.IntOpt('qpid_reconnect_interval_min',
               default=0,
               help='Minimum seconds between reconnection attempts'),
    cfg.IntOpt('qpid_reconnect_interval_max',
               default=0,
               help='Maximum seconds between reconnection attempts'),
    cfg.IntOpt('qpid_reconnect_interval',
               default=0,
               help='Equivalent to setting max and min to the same value'),
    cfg.IntOpt('qpid_heartbeat',
               default=5,
               help='Seconds between connection keepalive heartbeats'),
    cfg.StrOpt('qpid_protocol',
               default='tcp',
               help="Transport to use, either 'tcp' or 'ssl'"),
    cfg.BoolOpt('qpid_tcp_nodelay',
                default=True,
                help='Disable Nagle algorithm'),
    cfg.StrOpt('rabbit_host',
               default='localhost',
               help='the RabbitMQ host'),
    cfg.IntOpt('rabbit_port',
               default=5672,
               help='the RabbitMQ port'),
    cfg.BoolOpt('rabbit_use_ssl',
                default=False,
                help='connect over SSL for RabbitMQ'),
    cfg.StrOpt('rabbit_userid',
               default='guest',
               help='the RabbitMQ userid'),
    cfg.StrOpt('rabbit_password',
               default='guest',
               help='the RabbitMQ password'),
    cfg.StrOpt('rabbit_virtual_host',
               default='/',
               help='the RabbitMQ virtual host'),
    cfg.IntOpt('rabbit_retry_interval',
               default=1,
               help='how frequently to retry connecting with RabbitMQ'),
    cfg.IntOpt('rabbit_retry_backoff',
               default=2,
               help='how long to backoff for between retries when connecting '
                    'to RabbitMQ'),
    cfg.IntOpt('rabbit_max_retries',
               default=0,
               help='maximum retries with trying to connect to RabbitMQ '
                    '(the default of 0 implies an infinite retry count)'),
    cfg.StrOpt('control_exchange',
               default='heat-engine',
               help='the main RabbitMQ exchange to connect to'),
    cfg.BoolOpt('rabbit_durable_queues',
                default=False,
                help='use durable queues in RabbitMQ'),
    cfg.BoolOpt('fake_rabbit',
                default=False,
                help='If passed, use a fake RabbitMQ provider'),
    ]


class HeatConfigOpts(cfg.CommonConfigOpts):
    def __init__(self):
        super(HeatConfigOpts, self).__init__()
        opts = [cfg.IntOpt('bind_port', default=8000),
                cfg.StrOpt('bind_host', default='127.0.0.1')]
        opts.extend(rpc_opts)
        self.register_cli_opts(opts)


class HeatMetadataConfigOpts(cfg.CommonConfigOpts):
    def __init__(self):
        super(HeatMetadataConfigOpts, self).__init__()
        opts = [cfg.IntOpt('bind_port', default=8000),
                cfg.StrOpt('bind_host', default='127.0.0.1')]
        opts.extend(rpc_opts)
        self.register_cli_opts(opts)


class HeatEngineConfigOpts(cfg.CommonConfigOpts):

    service_opts = [
    cfg.IntOpt('report_interval',
               default=10,
               help='seconds between nodes reporting state to datastore'),
    cfg.IntOpt('periodic_interval',
               default=60,
               help='seconds between running periodic tasks'),
    cfg.StrOpt('ec2_listen',
               default="0.0.0.0",
               help='IP address for EC2 API to listen'),
    cfg.IntOpt('ec2_listen_port',
               default=8773,
               help='port for ec2 api to listen'),
    cfg.StrOpt('osapi_compute_listen',
               default="0.0.0.0",
               help='IP address for OpenStack API to listen'),
    cfg.IntOpt('osapi_compute_listen_port',
               default=8774,
               help='list port for osapi compute'),
    cfg.StrOpt('metadata_manager',
               default='nova.api.manager.MetadataManager',
               help='OpenStack metadata service manager'),
    cfg.StrOpt('metadata_listen',
               default="0.0.0.0",
               help='IP address for metadata api to listen'),
    cfg.IntOpt('metadata_listen_port',
               default=8775,
               help='port for metadata api to listen'),
    cfg.StrOpt('osapi_volume_listen',
               default="0.0.0.0",
               help='IP address for OpenStack Volume API to listen'),
    cfg.IntOpt('osapi_volume_listen_port',
               default=8776,
               help='port for os volume api to listen'),
    cfg.StrOpt('heat_metadata_server_url',
               default="",
               help='URL of the Heat metadata server'),
    ]
    db_opts = [
    cfg.StrOpt('sql_connection',
               default='mysql://heat:heat@localhost/heat',
               help='The SQLAlchemy connection string used to connect to the '
                    'database'),
    cfg.IntOpt('sql_idle_timeout',
               default=3600,
               help='timeout before idle sql connections are reaped'),
    ]
    engine_opts = [
    cfg.StrOpt('host',
               default=socket.gethostname(),
               help='Name of this node.  This can be an opaque identifier.  '
                    'It is not necessarily a hostname, FQDN, or IP address.'),
    cfg.StrOpt('instance_driver',
               default='heat.engine.nova',
               help='Driver to use for controlling instances'),
    ]

    def __init__(self):
        super(HeatEngineConfigOpts, self).__init__()
        self.register_cli_opts(self.engine_opts)
        self.register_cli_opts(self.db_opts)
        self.register_cli_opts(self.service_opts)
        self.register_cli_opts(rpc_opts)


def setup_logging(conf):
    """
    Sets up the logging options for a log with supplied name

    :param conf: a cfg.ConfOpts object
    """

    if conf.log_config:
        # Use a logging configuration file for all settings...
        if os.path.exists(conf.log_config):
            logging.config.fileConfig(conf.log_config)
            return
        else:
            raise RuntimeError("Unable to locate specified logging "
                               "config file: %s" % conf.log_config)

    root_logger = logging.root
    if conf.debug:
        root_logger.setLevel(logging.DEBUG)
    elif conf.verbose:
        root_logger.setLevel(logging.INFO)
    else:
        root_logger.setLevel(logging.WARNING)

    # quiet down the qpid logging
    root_logger.getChild('qpid.messaging').setLevel(logging.INFO)

    formatter = logging.Formatter(conf.log_format, conf.log_date_format)

    if conf.use_syslog:
        try:
            facility = getattr(logging.handlers.SysLogHandler,
                               conf.syslog_log_facility)
        except AttributeError:
            raise ValueError(_("Invalid syslog facility"))

        handler = logging.handlers.SysLogHandler(address='/dev/log',
                                                 facility=facility)
    elif conf.log_file:
        logfile = conf.log_file
        if conf.log_dir:
            logfile = os.path.join(conf.log_dir, logfile)
        handler = logging.handlers.WatchedFileHandler(logfile)
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)


def _register_paste_deploy_opts(conf):
    """
    Idempotent registration of paste_deploy option group

    :param conf: a cfg.ConfigOpts object
    """
    conf.register_group(paste_deploy_group)
    conf.register_opts(paste_deploy_opts, group=paste_deploy_group)


def _get_deployment_flavor(conf):
    """
    Retrieve the paste_deploy.flavor config item, formatted appropriately
    for appending to the application name.

    :param conf: a cfg.ConfigOpts object
    """
    _register_paste_deploy_opts(conf)
    flavor = conf.paste_deploy.flavor
    return '' if not flavor else ('-' + flavor)


def _get_deployment_config_file(conf):
    """
    Retrieve the deployment_config_file config item, formatted as an
    absolute pathname.

   :param conf: a cfg.ConfigOpts object
    """
    _register_paste_deploy_opts(conf)
    config_file = conf.paste_deploy.config_file
    if not config_file:
        if conf.config_file:
            # Assume paste config is in a paste.ini file corresponding
            # to the last config file
            path = os.path.splitext(conf.config_file[-1])[0] + "-paste.ini"
        else:
            return None
    else:
        path = config_file
    return os.path.abspath(path)


def load_paste_app(conf, app_name=None):
    """
    Builds and returns a WSGI app from a paste config file.

    We assume the last config file specified in the supplied ConfigOpts
    object is the paste config file.

    :param conf: a cfg.ConfigOpts object
    :param app_name: name of the application to load

    :raises RuntimeError when config file cannot be located or application
            cannot be loaded from config file
    """
    if app_name is None:
        app_name = conf.prog

    # append the deployment flavor to the application name,
    # in order to identify the appropriate paste pipeline
    app_name += _get_deployment_flavor(conf)

    conf_file = _get_deployment_config_file(conf)
    if conf_file is None:
        raise RuntimeError("Unable to locate config file")

    try:
        # Setup logging early
        setup_logging(conf)

        app = wsgi.paste_deploy_app(conf_file, app_name, conf)

        # Log the options used when starting if we're in debug mode...
        if conf.debug:
            conf.log_opt_values(logging.getLogger(app_name), logging.DEBUG)

        return app
    except (LookupError, ImportError), e:
        raise RuntimeError("Unable to load %(app_name)s from "
                           "configuration file %(conf_file)s."
                           "\nGot: %(e)r" % locals())
