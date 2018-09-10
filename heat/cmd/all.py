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

"""Heat All Server.

An OpenStack Heat server that can run all services.
"""
import eventlet
eventlet.monkey_patch(os=False)

import six

import sys

from heat.cmd import api
from heat.cmd import api_cfn
from heat.cmd import engine
from heat.common import config
from heat.common import messaging
from heat import version
from oslo_config import cfg
import oslo_i18n as i18n
from oslo_log import log as logging
from oslo_service import systemd

i18n.enable_lazy()

LOG = logging.getLogger('heat.all')

API_LAUNCH_OPTS = {'setup_logging': False}

LAUNCH_SERVICES = {
    'engine': [engine.launch_engine, {'setup_logging': False}],
    'api': [api.launch_api, API_LAUNCH_OPTS],
    'api_cfn': [api_cfn.launch_cfn_api, API_LAUNCH_OPTS],
}

services_opt = cfg.ListOpt(
    'enabled_services',
    default=['engine', 'api', 'api_cfn'],
    help='Specifies the heat services that are enabled when running heat-all. '
         'Valid options are all or any combination of '
         'api, engine or api_cfn.'
)

cfg.CONF.register_opt(services_opt, group='heat_all')


def _start_service_threads(services):
    threads = []
    for option in services:
        launch_func = LAUNCH_SERVICES[option][0]
        kwargs = LAUNCH_SERVICES[option][1]
        threads.append(eventlet.spawn(launch_func, **kwargs))
    return threads


def launch_all(setup_logging=True):
        if setup_logging:
            logging.register_options(cfg.CONF)
        cfg.CONF(project='heat', prog='heat-all',
                 version=version.version_info.version_string())
        if setup_logging:
            logging.setup(cfg.CONF, 'heat-all')
        config.set_config_defaults()
        messaging.setup()
        return _start_service_threads(set(cfg.CONF.heat_all.enabled_services))


def main():
    try:
        threads = launch_all()
        services = [thread.wait() for thread in threads]
        systemd.notify_once()
        [service.wait() for service in services]
    except RuntimeError as e:
        msg = six.text_type(e)
        sys.exit("ERROR: %s" % msg)
