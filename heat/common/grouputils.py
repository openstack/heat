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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import status
from heat.engine import template
from heat.rpc import api as rpc_api


class GroupInspector(object):
    """A class for returning data about a scaling group.

    All data is fetched over RPC, and the group's stack is never loaded into
    memory locally. Data is cached so it will be fetched only once. To
    refresh the data, create a new GroupInspector.
    """

    def __init__(self, context, rpc_client, group_identity):
        """Initialise with a context, rpc_client, and stack identifier."""
        self._context = context
        self._rpc_client = rpc_client
        self._identity = group_identity
        self._member_data = None
        self._template_data = None

    @classmethod
    def from_parent_resource(cls, parent_resource):
        """Create a GroupInspector from a parent resource.

        This is a convenience method to instantiate a GroupInspector from a
        Heat StackResource object.
        """
        return cls(parent_resource.context, parent_resource.rpc_client(),
                   parent_resource.nested_identifier())

    def _get_member_data(self):
        if self._identity is None:
            return []

        if self._member_data is None:
            rsrcs = self._rpc_client.list_stack_resources(self._context,
                                                          dict(self._identity))

            def sort_key(r):
                return (r[rpc_api.RES_STATUS] != status.ResourceStatus.FAILED,
                        r[rpc_api.RES_CREATION_TIME],
                        r[rpc_api.RES_NAME])

            self._member_data = sorted(rsrcs, key=sort_key)

        return self._member_data

    def _members(self, include_failed):
        return (r for r in self._get_member_data()
                if (include_failed or
                    r[rpc_api.RES_STATUS] != status.ResourceStatus.FAILED))

    def size(self, include_failed):
        """Return the size of the group.

        If include_failed is False, only members not in a FAILED state will
        be counted.
        """
        return sum(1 for m in self._members(include_failed))

    def member_names(self, include_failed):
        """Return an iterator over the names of the group members

        If include_failed is False, only members not in a FAILED state will
        be included.
        """
        return (m[rpc_api.RES_NAME] for m in self._members(include_failed))

    def _get_template_data(self):
        if self._identity is None:
            return None

        if self._template_data is None:
            self._template_data = self._rpc_client.get_template(self._context,
                                                                self._identity)
        return self._template_data

    def template(self):
        """Return a Template object representing the group's current template.

        Note that this does *not* include any environment data.
        """
        data = self._get_template_data()
        if data is None:
            return None
        return template.Template(data)


def get_size(group, include_failed=False):
    """Get number of member resources managed by the specified group.

    The size excludes failed members by default; set include_failed=True
    to get the total size.
    """
    return GroupInspector.from_parent_resource(group).size(include_failed)


def get_members(group, include_failed=False):
    """Get a list of member resources managed by the specified group.

    Sort the list of instances first by created_time then by name.
    If include_failed is set, failed members will be put first in the
    list sorted by created_time then by name.
    """
    resources = []
    if group.nested():
        resources = [r for r in six.itervalues(group.nested())
                     if include_failed or r.status != r.FAILED]

    return sorted(resources,
                  key=lambda r: (r.status != r.FAILED, r.created_time, r.name))


def get_member_refids(group):
    """Get a list of member resources managed by the specified group.

    The list of resources is sorted first by created_time then by name.
    """
    return [r.FnGetRefId() for r in get_members(group)]


def get_member_names(group):
    """Get a list of resource names of the resources in the specified group.

    Failed resources will be ignored.
    """
    inspector = GroupInspector.from_parent_resource(group)
    return list(inspector.member_names(include_failed=False))


def get_resource(stack, resource_name, use_indices, key=None):
    nested_stack = stack.nested()
    if not nested_stack:
        return None
    try:
        if use_indices:
            return get_members(stack)[int(resource_name)]
        else:
            return nested_stack[resource_name]
    except (IndexError, KeyError):
        raise exception.NotFound(_("Member '%(mem)s' not found "
                                   "in group resource '%(grp)s'.")
                                 % {'mem': resource_name,
                                    'grp': stack.name})


def get_rsrc_attr(stack, key, use_indices, resource_name, *attr_path):
    resource = get_resource(stack, resource_name, use_indices)
    if resource:
        return resource.FnGetAtt(*attr_path)


def get_rsrc_id(stack, key, use_indices, resource_name):
    resource = get_resource(stack, resource_name, use_indices)
    if resource:
        return resource.FnGetRefId()


def get_nested_attrs(stack, key, use_indices, *path):
    path = key.split(".", 2)[1:] + list(path)
    if len(path) > 1:
        return get_rsrc_attr(stack, key, use_indices, *path)
    else:
        return get_rsrc_id(stack, key, use_indices, *path)


def get_member_definitions(group, include_failed=False):
    """Get member definitions in (name, ResourceDefinition) pair for group.

    The List is sorted first by created_time then by name.
    If include_failed is set, failed members will be put first in the
    List sorted by created_time then by name.
    """
    inspector = GroupInspector.from_parent_resource(group)
    template = inspector.template()
    if template is None:
        return []
    definitions = template.resource_definitions(None)
    return [(name, definitions[name])
            for name in inspector.member_names(include_failed=include_failed)
            if name in definitions]


def get_child_template_files(context, stack,
                             is_rolling_update,
                             old_template_id):
    """Return a merged map of old and new template files.

    For rolling update files for old and new defintions are required as the
    nested stack is updated in batches of scaled units.
    """
    if not stack.convergence:
        old_template_id = stack.t.id

    if is_rolling_update and old_template_id:
        prev_files = template.Template.load(context, old_template_id).files
        prev_files.update(dict(stack.t.files))
        return prev_files
    return stack.t.files
