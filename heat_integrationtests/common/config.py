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

import os

from oslo_config import cfg
from oslo_log import log as logging

import heat_integrationtests

_CONF = None

heat_group = cfg.OptGroup(name="heat_plugin",
                          title="Heat Service Options")

HeatGroup = [
    cfg.StrOpt("catalog_type",
               default="orchestration",
               help="Catalog type of the orchestration service."),
    cfg.StrOpt('username',
               help="Username to use for non admin API requests."),
    cfg.StrOpt('password',
               help="Non admin API key to use when authenticating.",
               secret=True),
    cfg.StrOpt('admin_username',
               help="Username to use for admin API requests."),
    cfg.StrOpt('admin_password',
               help="Admin API key to use when authentication.",
               secret=True),
    cfg.StrOpt('project_name',
               help="Project name to use for API requests.",
               deprecated_opts=[cfg.DeprecatedOpt('tenant_name',
                                                  group='heat_plugin')]),
    cfg.StrOpt('admin_project_name',
               default='admin',
               help="Admin project name to use for admin API requests.",
               deprecated_opts=[cfg.DeprecatedOpt('admin_tenant_name',
                                                  group='heat_plugin')]),
    cfg.StrOpt('auth_url',
               help="Full URI of the OpenStack Identity API (Keystone)."),
    cfg.StrOpt('auth_version',
               help="OpenStack Identity API version."),
    cfg.StrOpt('user_domain_name',
               help="User domain name, if keystone v3 auth_url "
                    "is used"),
    cfg.StrOpt('project_domain_name',
               help="Project domain name, if keystone v3 auth_url "
                    "is used"),
    cfg.StrOpt('user_domain_id',
               help="User domain id, if keystone v3 auth_url "
                    "is used"),
    cfg.StrOpt('project_domain_id',
               help="Project domain id, if keystone v3 auth_url "
                    "is used"),
    cfg.StrOpt('region',
               help="The region name to use"),
    cfg.StrOpt('instance_type',
               help="Instance type for tests. Needs to be big enough for a "
                    "full OS plus the test workload"),
    cfg.StrOpt('minimal_instance_type',
               help="Instance type enough for simplest cases."),
    cfg.StrOpt('image_ref',
               help="Name of image to use for tests which boot servers."),
    cfg.StrOpt('keypair_name',
               help="Name of existing keypair to launch servers with."),
    cfg.StrOpt('minimal_image_ref',
               help="Name of minimal (e.g cirros) image to use when "
                    "launching test instances."),
    cfg.BoolOpt('disable_ssl_certificate_validation',
                default=False,
                help="Set to True if using self-signed SSL certificates."),
    cfg.StrOpt('ca_file',
               help="CA certificate to pass for servers that have "
                    "https endpoint."),
    cfg.IntOpt('build_interval',
               default=4,
               help="Time in seconds between build status checks."),
    cfg.IntOpt('build_timeout',
               default=1200,
               help="Timeout in seconds to wait for a stack to build."),
    cfg.StrOpt('network_for_ssh',
               default='heat-net',
               help="Network used for SSH connections."),
    cfg.StrOpt('fixed_network_name',
               default='heat-net',
               help="Visible fixed network name "),
    cfg.StrOpt('floating_network_name',
               default='public',
               help="Visible floating network name "),
    cfg.StrOpt('fixed_subnet_name',
               default='heat-subnet',
               help="Visible fixed sub-network name "),
    cfg.BoolOpt('skip_functional_tests',
                default=False,
                help="Skip all functional tests"),
    cfg.ListOpt('skip_functional_test_list',
                help="List of functional test class or class.method "
                     "names to skip ex. AutoscalingGroupTest, "
                     "InstanceGroupBasicTest.test_size_updates_work"),
    cfg.ListOpt('skip_test_stack_action_list',
                help="List of stack actions in tests to skip "
                     "ex. ABANDON, ADOPT, SUSPEND, RESUME"),
    cfg.BoolOpt('convergence_engine_enabled',
                default=True,
                help="Test features that are only present for stacks with "
                     "convergence enabled."),
    cfg.IntOpt('connectivity_timeout',
               default=120,
               help="Timeout in seconds to wait for connectivity to "
                    "server."),
]


def init_conf(read_conf=True):
    global _CONF
    if _CONF is not None:
        return _CONF

    default_config_files = None
    if read_conf:
        confpath = os.path.join(
            os.path.dirname(os.path.realpath(heat_integrationtests.__file__)),
            'heat_integrationtests.conf')
        if os.path.isfile(confpath):
            default_config_files = [confpath]

    _CONF = cfg.ConfigOpts()
    logging.register_options(_CONF)
    _CONF(args=[], project='heat_integrationtests',
          default_config_files=default_config_files)

    for group, opts in list_opts():
        _CONF.register_opts(opts, group=group)
    return _CONF


def list_opts():
    yield heat_group.name, HeatGroup
