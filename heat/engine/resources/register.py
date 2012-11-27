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
Register of resource types and their mapping to Resource classes.
"""

from heat.engine.resources import autoscaling
from heat.engine.resources import cloud_watch
from heat.engine.resources import dbinstance
from heat.engine.resources import eip
from heat.engine.resources import instance
from heat.engine.resources import loadbalancer
from heat.engine.resources import s3
from heat.engine.resources import security_group
from heat.engine.resources import stack
from heat.engine.resources import user
from heat.engine.resources import volume
from heat.engine.resources import wait_condition
from heat.engine.resources.quantum import floatingip
from heat.engine.resources.quantum import net
from heat.engine.resources.quantum import port
from heat.engine.resources.quantum import router
from heat.engine.resources.quantum import subnet

from heat.openstack.common import log as logging

logger = logging.getLogger('heat.engine.resources.register')


_modules = [
    autoscaling, cloud_watch, dbinstance, eip, instance, loadbalancer, s3,
    security_group, stack, user, volume, wait_condition, floatingip, net, port,
    router, subnet,
]

_resource_classes = {}


def get_class(resource_type):
    return _resource_classes.get(resource_type)


def _register_class(resource_type, resource_class):
    logger.info(_('Registering resource type %s') % resource_type)
    if resource_type in _resource_classes:
        logger.warning(_('Replacing existing resource type %s') %
                resource_type)

    _resource_classes[resource_type] = resource_class


for m in _modules:
    for res_type, res_class in m.resource_mapping().items():
        _register_class(res_type, res_class)
