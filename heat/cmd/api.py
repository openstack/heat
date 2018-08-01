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

"""Heat API Server.

An OpenStack ReST API to Heat.
"""

import eventlet
eventlet.monkey_patch(os=False)

import sys

from oslo_config import cfg
import oslo_i18n as i18n
from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr
from oslo_service import systemd
import six

from heat.common import config
from heat.common import messaging
from heat.common import profiler
from heat.common import wsgi
from heat import version

i18n.enable_lazy()

LOG = logging.getLogger('heat.api')


def launch_api(setup_logging=True):
    if setup_logging:
        logging.register_options(cfg.CONF)
    cfg.CONF(project='heat', prog='heat-api',
             version=version.version_info.version_string())
    if setup_logging:
        logging.setup(cfg.CONF, 'heat-api')
    config.set_config_defaults()
    messaging.setup()

    app = config.load_paste_app()

    port = cfg.CONF.heat_api.bind_port
    host = cfg.CONF.heat_api.bind_host
    LOG.info('Starting Heat REST API on %(host)s:%(port)s',
             {'host': host, 'port': port})
    profiler.setup('heat-api', host)
    gmr.TextGuruMeditation.setup_autorun(version)
    server = wsgi.Server('heat-api', cfg.CONF.heat_api)
    server.start(app, default_port=port)
    return server


def main():
    try:
        server = launch_api()
        systemd.notify_once()
        server.wait()
    except RuntimeError as e:
        msg = six.text_type(e)
        sys.exit("ERROR: %s" % msg)
