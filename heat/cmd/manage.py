#
# All Rights Reserved.
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
  CLI interface for heat management.
"""

import sys

from oslo_config import cfg
from oslo_log import log

from heat.common import context
from heat.common.i18n import _
from heat.common import service_utils
from heat.db import api as db_api
from heat.db import utils
from heat.objects import service as service_objects
from heat import version


CONF = cfg.CONF


def do_db_version():
    """Print database's current migration level."""
    print(db_api.db_version(db_api.get_engine()))


def do_db_sync():
    """
    Place a database under migration control and upgrade,
    creating first if necessary.
    """
    db_api.db_sync(db_api.get_engine(), CONF.command.version)


class ServiceManageCommand(object):
    def service_list(self):
        ctxt = context.get_admin_context()
        services = [service_utils.format_service(service)
                    for service in service_objects.Service.get_all(ctxt)]

        print_format = "%-16s %-16s %-36s %-10s %-10s %-10s %-10s"
        print(print_format % (_('Hostname'),
                              _('Binary'),
                              _('Engine_Id'),
                              _('Host'),
                              _('Topic'),
                              _('Status'),
                              _('Updated At')))

        for svc in services:
            print(print_format % (svc['hostname'],
                                  svc['binary'],
                                  svc['engine_id'],
                                  svc['host'],
                                  svc['topic'],
                                  svc['status'],
                                  svc['updated_at']))

    @staticmethod
    def add_service_parsers(subparsers):
        service_parser = subparsers.add_parser('service')
        service_parser.set_defaults(command_object=ServiceManageCommand)
        service_subparsers = service_parser.add_subparsers(dest='action')
        list_parser = service_subparsers.add_parser('list')
        list_parser.set_defaults(func=ServiceManageCommand().service_list)


def purge_deleted():
    """
    Remove database records that have been previously soft deleted
    """
    utils.purge_deleted(CONF.command.age, CONF.command.granularity)


def add_command_parsers(subparsers):
    parser = subparsers.add_parser('db_version')
    parser.set_defaults(func=do_db_version)

    parser = subparsers.add_parser('db_sync')
    parser.set_defaults(func=do_db_sync)
    parser.add_argument('version', nargs='?')
    parser.add_argument('current_version', nargs='?')

    parser = subparsers.add_parser('purge_deleted')
    parser.set_defaults(func=purge_deleted)
    parser.add_argument('age', nargs='?', default='90',
                        help=_('How long to preserve deleted data.'))
    parser.add_argument(
        '-g', '--granularity', default='days',
        choices=['days', 'hours', 'minutes', 'seconds'],
        help=_('Granularity to use for age argument, defaults to days.'))

    ServiceManageCommand.add_service_parsers(subparsers)

command_opt = cfg.SubCommandOpt('command',
                                title='Commands',
                                help='Show available commands.',
                                handler=add_command_parsers)


def main():
    log.register_options(CONF)
    log.setup(CONF, "heat-manage")
    CONF.register_cli_opt(command_opt)
    try:
        default_config_files = cfg.find_config_files('heat', 'heat-engine')
        CONF(sys.argv[1:], project='heat', prog='heat-manage',
             version=version.version_info.version_string(),
             default_config_files=default_config_files)
    except RuntimeError as e:
        sys.exit("ERROR: %s" % e)

    try:
        CONF.command.func()
    except Exception as e:
        sys.exit("ERROR: %s" % e)
