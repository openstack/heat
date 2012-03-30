#!/usr/bin/env python
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



class HeatConfigOpts(cfg.CommonConfigOpts):

    def __init__(self, default_config_files=None, **kwargs):
        super(HeatConfigOpts, self).__init__(
            project='heat',
            version='%%prog %s' % version.version_string(),
            default_config_files=default_config_files,
            **kwargs)

class HeatEngineConfigOpts(cfg.CommonConfigOpts):
    engine_opts = [
        cfg.StrOpt('host',
                   default=socket.gethostname(),
                   help='Name of this node.  This can be an opaque identifier.  '
                        'It is not necessarily a hostname, FQDN, or IP address.'),
        cfg.StrOpt('instance_driver',
                   default='heat.engine.nova',
                   help='Driver to use for controlling instances'),

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

    ]

    def __init__(self, default_config_files=None, **kwargs):
        super(HeatEngineConfigOpts, self).__init__(
            project='heat',
            version='%%prog %s' % version.version_string(),
            **kwargs)
        config_files = cfg.find_config_files(project='heat',
                                             prog='heat-engine')
        self.register_cli_opts(self.engine_opts)

FLAGS = HeatEngineConfigOpts()


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
        # Assume paste config is in a paste.ini file corresponding
        # to the last config file
        path = conf.config_file[-1].replace(".conf", "-paste.ini")
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
