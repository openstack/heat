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

import datetime

from oslo_utils import timeutils
import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource

try:
    from pyrax.exceptions import NotFound  # noqa
    PYRAX_INSTALLED = True
except ImportError:
    # Setup fake exception for testing without pyrax
    class NotFound(Exception):
        pass
    PYRAX_INSTALLED = False


def lb_immutable(exc):
    return 'immutable' in six.text_type(exc)


class LoadbalancerDeleted(exception.HeatException):
    msg_fmt = _("The Load Balancer (ID %(lb_id)s) has been deleted.")


class NodeNotFound(exception.HeatException):
    msg_fmt = _("Node (ID %(node_id)s) not found on Load Balancer "
                "(ID %(lb_id)s).")


class LBNode(resource.Resource):
    """Represents a single node of a Rackspace Cloud Load Balancer"""

    default_client_name = 'cloud_lb'

    _CONDITIONS = (
        ENABLED, DISABLED, DRAINING,
    ) = (
        'ENABLED', 'DISABLED', 'DRAINING',
    )

    _NODE_KEYS = (
        ADDRESS, PORT, CONDITION, TYPE, WEIGHT
    ) = (
        'address', 'port', 'condition', 'type', 'weight'
    )

    _OTHER_KEYS = (
        LOAD_BALANCER, DRAINING_TIMEOUT
    ) = (
        'load_balancer', 'draining_timeout'
    )

    PROPERTIES = _NODE_KEYS + _OTHER_KEYS

    properties_schema = {
        LOAD_BALANCER: properties.Schema(
            properties.Schema.STRING,
            _("The ID of the load balancer to associate the node with."),
            required=True
        ),
        DRAINING_TIMEOUT: properties.Schema(
            properties.Schema.INTEGER,
            _("The time to wait, in seconds, for the node to drain before it "
              "is deleted."),
            default=0,
            constraints=[
                constraints.Range(min=0)
            ],
            update_allowed=True
        ),
        ADDRESS: properties.Schema(
            properties.Schema.STRING,
            _("IP address for the node."),
            required=True
        ),
        PORT: properties.Schema(
            properties.Schema.INTEGER,
            required=True
        ),
        CONDITION: properties.Schema(
            properties.Schema.STRING,
            default=ENABLED,
            constraints=[
                constraints.AllowedValues(_CONDITIONS),
            ],
            update_allowed=True
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            constraints=[
                constraints.AllowedValues(['PRIMARY',
                                           'SECONDARY']),
            ],
            update_allowed=True
        ),
        WEIGHT: properties.Schema(
            properties.Schema.NUMBER,
            constraints=[
                constraints.Range(1, 100),
            ],
            update_allowed=True
        ),
    }

    def lb(self):
        lb_id = self.properties.get(self.LOAD_BALANCER)
        lb = self.client().get(lb_id)

        if lb.status in ('DELETED', 'PENDING_DELETE'):
            raise LoadbalancerDeleted(lb_id=lb.id)

        return lb

    def node(self, lb):
        for node in getattr(lb, 'nodes', []):
            if node.id == self.resource_id:
                return node
        raise NodeNotFound(node_id=self.resource_id, lb_id=lb.id)

    def handle_create(self):
        pass

    def check_create_complete(self, *args):
        node_args = {k: self.properties.get(k) for k in self._NODE_KEYS}
        node = self.client().Node(**node_args)

        try:
            resp, body = self.lb().add_nodes([node])
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        new_node = body['nodes'][0]
        node_id = new_node['id']

        self.resource_id_set(node_id)
        return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        return prop_diff

    def check_update_complete(self, prop_diff):
        node = self.node(self.lb())
        is_complete = True

        for key in self._NODE_KEYS:
            if key in prop_diff and getattr(node, key, None) != prop_diff[key]:
                setattr(node, key, prop_diff[key])
                is_complete = False

        if is_complete:
            return True

        try:
            node.update()
        except Exception as exc:
            if lb_immutable(exc):
                return False
            raise

        return False

    def handle_delete(self):
        return timeutils.utcnow()

    def check_delete_complete(self, deleted_at):
        if self.resource_id is None:
            return True

        try:
            node = self.node(self.lb())
        except (NotFound, LoadbalancerDeleted, NodeNotFound):
            return True

        if isinstance(deleted_at, six.string_types):
            deleted_at = timeutils.parse_isotime(deleted_at)

        deleted_at = timeutils.normalize_time(deleted_at)
        waited = timeutils.utcnow() - deleted_at
        timeout_secs = self.properties[self.DRAINING_TIMEOUT]
        timeout_secs = datetime.timedelta(seconds=timeout_secs)

        if waited > timeout_secs:
            try:
                node.delete()
            except NotFound:
                return True
            except Exception as exc:
                if lb_immutable(exc):
                    return False
                raise
        elif node.condition != self.DRAINING:
            node.condition = self.DRAINING
            try:
                node.update()
            except Exception as exc:
                if lb_immutable(exc):
                    return False
                raise

        return False


def resource_mapping():
    return {'Rackspace::Cloud::LBNode': LBNode}


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
