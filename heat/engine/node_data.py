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

import six


class NodeData(object):
    """Data about a node in the graph, to be passed along to other nodes."""

    __slots__ = ('primary_key', 'name', 'uuid',
                 '_reference_id', '_attributes',
                 'action', 'status')

    def __init__(self, primary_key, resource_name, uuid,
                 reference_id, attributes, action, status):
        """Initialise with data about the resource processed by the node.

        :param primary_key: the ID of the resource in the database
        :param name: the logical resource name
        :param uuid: the UUID of the resource
        :param reference_id: the value to be returned by get_resource
        :param attributes: dict of attributes values to be returned by get_attr
        :param action: the last resource action
        :param status: the status of the last action
        """
        self.primary_key = primary_key
        self.name = resource_name
        self.uuid = uuid
        self._reference_id = reference_id
        self._attributes = attributes
        self.action = action
        self.status = status

    def reference_id(self):
        """Return the reference ID of the resource.

        i.e. the result that the {get_resource: } intrinsic function should
        return for this resource.
        """
        return self._reference_id

    def attributes(self):
        """Return a dict of all available top-level attribute values."""
        attrs = {k: v
                 for k, v in self._attributes.items()
                 if isinstance(k, six.string_types)}
        for v in six.itervalues(attrs):
            if isinstance(v, Exception):
                raise v
        return attrs

    def attribute(self, attr_name):
        """Return the specified attribute value."""
        val = self._attributes[attr_name]
        if isinstance(val, Exception):
            raise val
        return val

    def attribute_names(self):
        """Iterate over valid top-level attribute names."""
        for key in self._attributes:
            if isinstance(key, six.string_types):
                yield key
            else:
                yield key[0]

    def as_dict(self):
        """Return a dict representation of the data.

        This is the format that is serialised and stored in the database's
        SyncPoints.
        """
        for v in six.itervalues(self._attributes):
            if isinstance(v, Exception):
                raise v

        return {
            'id': self.primary_key,
            'name': self.name,
            'reference_id': self.reference_id(),
            'attrs': dict(self._attributes),
            'status': self.status,
            'action': self.action,
            'uuid': self.uuid,
        }

    @classmethod
    def from_dict(cls, node_data):
        """Create a new NodeData object from deserialised data.

        This reads the format that is stored in the database, and is the
        inverse of as_dict().
        """
        if isinstance(node_data, cls):
            return node_data

        return cls(node_data.get('id'),
                   node_data.get('name'),
                   node_data.get('uuid'),
                   node_data.get('reference_id'),
                   node_data.get('attrs', {}),
                   node_data.get('action'),
                   node_data.get('status'))


def load_resources_data(data):
    """Return the data for all of the resources that meet at a SyncPoint.

    The input is the input_data dict from a SyncPoint received over RPC. The
    keys (which are ignored) are resource primary keys.

    The output is a dict of NodeData objects with the resource names as the
    keys.
    """
    nodes = (NodeData.from_dict(nd) for nd in data.values() if nd is not None)
    return {node.name: node for node in nodes}
