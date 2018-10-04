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

import functools
import six

from oslo_log import log as logging

from heat.common import exception
from heat.common import grouputils
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import output
from heat.engine import properties
from heat.engine.resources import stack_resource
from heat.engine import rsrc_defn
from heat.engine import support
from heat.objects import service as service_objects
from heat.scaling import template as scl_template

LOG = logging.getLogger(__name__)


class ResourceChain(stack_resource.StackResource):
    """Creates one or more resources with the same configuration.

    The types of resources to be created are passed into the chain
    through the ``resources`` property. One resource will be created for each
    type listed. Each is passed the configuration specified
    under ``resource_properties``.

    The ``concurrent`` property controls if the resources will be created
    concurrently. If omitted or set to false, each resource will be treated
    as having a dependency on the resource before it in the list.
    """

    support_status = support.SupportStatus(version='6.0.0')

    PROPERTIES = (
        RESOURCES, CONCURRENT, RESOURCE_PROPERTIES,
    ) = (
        'resources', 'concurrent', 'resource_properties',
    )

    ATTRIBUTES = (
        REFS, ATTR_ATTRIBUTES,
    ) = (
        'refs', 'attributes',
    )

    properties_schema = {
        RESOURCES: properties.Schema(
            properties.Schema.LIST,
            description=_('The list of resource types to create. This list '
                          'may contain type names or aliases defined in '
                          'the resource registry. Specific template names '
                          'are not supported.'),
            required=True,
            update_allowed=True
        ),
        CONCURRENT: properties.Schema(
            properties.Schema.BOOLEAN,
            description=_('If true, the resources in the chain will be '
                          'created concurrently. If false or omitted, '
                          'each resource will be treated as having a '
                          'dependency on the previous resource in the list.'),
            default=False,
        ),
        RESOURCE_PROPERTIES: properties.Schema(
            properties.Schema.MAP,
            description=_('Properties to pass to each resource being created '
                          'in the chain.'),
        )
    }

    attributes_schema = {
        REFS: attributes.Schema(
            description=_('A list of resource IDs for the resources in '
                          'the chain.'),
            type=attributes.Schema.LIST
        ),
        ATTR_ATTRIBUTES: attributes.Schema(
            description=_('A map of resource names to the specified attribute '
                          'of each individual resource.'),
            type=attributes.Schema.MAP
        ),
    }

    def validate_nested_stack(self):
        # Check each specified resource type to ensure it's valid
        for resource_type in self.properties[self.RESOURCES]:
            try:
                self.stack.env.get_class_to_instantiate(resource_type)
            except exception.EntityNotFound:
                # Valid if it's a template resource
                pass

        super(ResourceChain, self).validate_nested_stack()

    def handle_create(self):
        return self.create_with_template(self.child_template())

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self.properties = json_snippet.properties(self.properties_schema,
                                                  self.context)
        return self.update_with_template(self.child_template())

    def child_template(self):
        resource_types = self.properties[self.RESOURCES]
        resource_names = self._resource_names(resource_types)
        name_def_tuples = []
        # Impose a concurrency limit if concurrent is set. This minimizes the
        # memory usage when the chain contains lots of resources, but it keeps
        # performance to a reasonable level.
        concurrency_limit = service_objects.Service.active_service_count(
            self.context) or 1
        for index, rt in enumerate(resource_types):
            name = resource_names[index]

            depends_on = None
            if index > 0 and not self.properties[self.CONCURRENT]:
                depends_on = [resource_names[index - 1]]
            elif index >= concurrency_limit:
                depends_on = [resource_names[index - concurrency_limit]]

            t = (name, self._build_resource_definition(name, rt,
                                                       depends_on=depends_on))
            name_def_tuples.append(t)

        nested_template = scl_template.make_template(name_def_tuples)

        att_func = 'get_attr'
        get_attr = functools.partial(nested_template.functions[att_func],
                                     None, att_func)
        res_func = 'get_resource'
        get_res = functools.partial(nested_template.functions[res_func],
                                    None, res_func)
        res_names = [k for k, d in name_def_tuples]
        for odefn in self._nested_output_defns(res_names, get_attr, get_res):
            nested_template.add_output(odefn)

        return nested_template

    def child_params(self):
        return {}

    def _attribute_output_name(self, *attr_path):
        return ', '.join(six.text_type(a) for a in attr_path)

    def get_attribute(self, key, *path):
        if key == self.ATTR_ATTRIBUTES and not path:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        try:
            output = self.get_output(self._attribute_output_name(key, *path))
        except (exception.NotFound,
                exception.TemplateOutputError) as op_err:
            resource_types = self.properties[self.RESOURCES]
            names = self._resource_names(resource_types)
            if key.startswith('resource.'):
                target = key.split('.', 2)[1]
                if target not in names:
                    raise exception.NotFound(_("Member '%(mem)s' not "
                                               "found in group resource "
                                               "'%(grp)s'.") %
                                             {'mem': target,
                                              'grp': self.name})
            LOG.debug('Falling back to grouputils due to %s', op_err)
        else:
            if key == self.REFS:
                return attributes.select_from_attribute(output, path)
            return output

        if key.startswith('resource.'):
            return grouputils.get_nested_attrs(self, key, False, *path)

        if key == self.REFS:
            vals = [grouputils.get_rsrc_id(self, key, False, n) for n in names]
            return attributes.select_from_attribute(vals, path)
        if key == self.ATTR_ATTRIBUTES:
            return dict((n, grouputils.get_rsrc_attr(
                self, key, False, n, *path)) for n in names)

        path = [key] + list(path)
        return [grouputils.get_rsrc_attr(self, key, False, n, *path)
                for n in names]

    def _nested_output_defns(self, resource_names, get_attr_fn, get_res_fn):
        for attr in self.referenced_attrs():
            if isinstance(attr, six.string_types):
                key, path = attr, []
            else:
                key, path = attr[0], list(attr[1:])
            output_name = self._attribute_output_name(key, *path)
            value = None

            if key.startswith("resource."):
                keycomponents = key.split('.', 2)
                res_name = keycomponents[1]
                attr_path = keycomponents[2:] + path
                if res_name in resource_names:
                    if attr_path:
                        value = get_attr_fn([res_name] + attr_path)
                    else:
                        value = get_res_fn(res_name)
            elif key == self.REFS:
                value = [get_res_fn(r) for r in resource_names]
            elif key == self.ATTR_ATTRIBUTES and path:
                value = {r: get_attr_fn([r] + path) for r in resource_names}
            elif key not in self.ATTRIBUTES:
                value = [get_attr_fn([r, key] + path) for r in resource_names]

            if value is not None:
                yield output.OutputDefinition(output_name, value)

    @staticmethod
    def _resource_names(resource_types):
        """Returns a list of unique resource names to create."""
        return [six.text_type(i) for i, t in enumerate(resource_types)]

    def _build_resource_definition(self, resource_name, resource_type,
                                   depends_on=None):
        """Creates a definition object for one of the types in the chain.

        The definition will be built from the given name and type and will
        use the properties specified in the chain's resource_properties
        property. All types in the chain are given the same set of properties.

        :type resource_name: str
        :type resource_type: str
        :param depends_on: if specified, the new resource will depend on the
               resource name specified
        :type depends_on: str
        :return: resource definition suitable for adding to a template
        :rtype: heat.engine.rsrc_defn.ResourceDefinition
        """

        properties = self.properties[self.RESOURCE_PROPERTIES]
        return rsrc_defn.ResourceDefinition(resource_name, resource_type,
                                            properties, depends=depends_on)


def resource_mapping():
    """Hook to install the type under a specific name."""
    return {
        'OS::Heat::ResourceChain': ResourceChain,
    }
