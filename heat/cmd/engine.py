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

"""Heat Engine Server.

This does the work of actually implementing the API calls made by the user.
Normal communications is done via the heat API which then calls into this
engine.
"""

# flake8: noqa: E402

import eventlet
eventlet.monkey_patch()
# Monkey patch the original current_thread to use the up-to-date _active
# global variable. See https://bugs.launchpad.net/bugs/1863021 and
# https://github.com/eventlet/eventlet/issues/592
import __original_module_threading as orig_threading
import threading  # noqa
orig_threading.current_thread.__globals__['_active'] = threading._active

import sys

from oslo_concurrency import processutils
from oslo_config import cfg
import oslo_i18n as i18n
from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr
from oslo_service import service

from heat.common import config
from heat.common import messaging
from heat.common import profiler
from heat.engine import template
from heat.rpc import api as rpc_api
from heat import version


i18n.enable_lazy()

CONF = cfg.CONF


def launch_engine(setup_logging=True):
    if setup_logging:
        logging.register_options(CONF)
    CONF(project='heat', prog='heat-engine',
         version=version.version_info.version_string())
    if setup_logging:
        logging.setup(CONF, CONF.prog)
        logging.set_defaults()
    LOG = logging.getLogger(CONF.prog)
    messaging.setup()

    config.startup_sanity_check()

    mgr = None
    try:
        mgr = template._get_template_extension_manager()
    except template.TemplatePluginNotRegistered as ex:
        LOG.critical("%s", ex)
    if not mgr or not mgr.names():
        sys.exit("ERROR: No template format plugins registered")

    from heat.engine import service as engine  # noqa

    profiler.setup(CONF.prog, CONF.host)
    gmr.TextGuruMeditation.setup_autorun(version)
    srv = engine.EngineService(CONF.host, rpc_api.ENGINE_TOPIC)
    workers = CONF.num_engine_workers
    if not workers:
        workers = max(4, processutils.get_worker_count())

    launcher = service.launch(CONF, srv, workers=workers,
                              restart_method='mutate')
    return launcher


def main():
    launcher = launch_engine()
    launcher.wait()
