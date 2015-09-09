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


def get_size(group, include_failed=False):
    """Get number of member resources managed by the specified group.

    The size exclude failed members default, set include_failed=True
    to get total size.
    """
    if group.nested():
        resources = [r for r in six.itervalues(group.nested())
                     if include_failed or r.status != r.FAILED]
        return len(resources)
    else:
        return 0


def get_members(group):
    """Get a list of member resources managed by the specified group.

    Sort the list of instances first by created_time then by name.
    """
    resources = []
    if group.nested():
        resources = [r for r in six.itervalues(group.nested())
                     if r.status != r.FAILED]

    return sorted(resources, key=lambda r: (r.created_time, r.name))


def get_member_refids(group, exclude=None):
    """Get a list of member resources managed by the specified group.

    The list of resources is sorted first by created_time then by name.
    """
    members = get_members(group)
    if len(members) == 0:
        return []

    if exclude is None:
        exclude = []
    return [r.FnGetRefId() for r in members
            if r.FnGetRefId() not in exclude]


def get_member_names(group):
    """Get a list of resource names of the resources in the specified group.

    Failed resources will be ignored.
    """
    return [r.name for r in get_members(group)]


def get_resource(stack, resource_name, use_indices, key):
    nested_stack = stack.nested()
    if not nested_stack:
        return None
    try:
        if use_indices:
            return get_members(stack)[int(resource_name)]
        else:
            return nested_stack[resource_name]
    except (IndexError, KeyError):
        raise exception.InvalidTemplateAttribute(resource=stack.name,
                                                 key=key)


def get_rsrc_attr(stack, key, use_indices, resource_name, *attr_path):
    resource = get_resource(stack, resource_name, use_indices, key)
    if resource:
        return resource.FnGetAtt(*attr_path)


def get_rsrc_id(stack, key, use_indices, resource_name):
    resource = get_resource(stack, resource_name, use_indices, key)
    if resource:
        return resource.FnGetRefId()


def get_nested_attrs(stack, key, use_indices, *path):
    path = key.split(".", 2)[1:] + list(path)
    if len(path) > 1:
        return get_rsrc_attr(stack, key, use_indices, *path)
    else:
        return get_rsrc_id(stack, key, use_indices, *path)


def get_member_definitions(group):
    """Get member definitions in (name, ResourceDefinition) pair for group.

        The List is sorted first by created_time then by name.
    """
    return [(resource.name, resource.t)
            for resource in get_members(group)]
