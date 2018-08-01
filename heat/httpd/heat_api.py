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

"""WSGI script for heat-api.

Script for running heat-api under Apache2.
"""


from oslo_config import cfg
import oslo_i18n as i18n
from oslo_log import log as logging

from heat.common import config
from heat.common import messaging
from heat.common import profiler
from heat import version as hversion


def init_application():
    i18n.enable_lazy()

    LOG = logging.getLogger('heat.api')

    logging.register_options(cfg.CONF)
    version = hversion.version_info.version_string()
    cfg.CONF(project='heat', prog='heat-api', version=version)
    logging.setup(cfg.CONF, 'heat-api')
    config.set_config_defaults()
    messaging.setup()

    port = cfg.CONF.heat_api.bind_port
    host = cfg.CONF.heat_api.bind_host
    profiler.setup('heat-api', host)
    LOG.info('Starting Heat REST API on %(host)s:%(port)s',
             {'host': host, 'port': port})
    return config.load_paste_app()
