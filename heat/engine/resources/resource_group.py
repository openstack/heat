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

import collections
import copy

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import stack_resource
from heat.engine import template

template_template = {
    "heat_template_version": "2013-05-23",
    "resources": {}
}


class ResourceGroup(stack_resource.StackResource):
    """
    A resource that creates one or more identically configured nested
    resources.

    In addition to the `refs` attribute, this resource implements synthetic
    attributes that mirror those of the resources in the group.  When
    getting an attribute from this resource, however, a list of attribute
    values for each resource in the group is returned. To get attribute values
    for a single resource in the group, synthetic attributes of the form
    `resource.{resource index}.{attribute name}` can be used. The resource ID
    of a particular resource in the group can be obtained via the synthetic
    attribute `resource.{resource index}`.

    While each resource in the group will be identically configured, this
    resource does allow for some index-based customization of the properties
    of the resources in the group. For example::

      resources:
        my_indexed_group:
          type: OS::Heat::ResourceGroup
          properties:
            count: 3
            resource_def:
              type: OS::Nova::Server
              properties:
                # create a unique name for each server
                # using its index in the group
                name: my_server_%index%
                image: CentOS 6.5
                flavor: 4GB Performance

    would result in a group of three servers having the same image and flavor,
    but names of `my_server_0`, `my_server_1`, and `my_server_2`. The variable
    used for substitution can be customized by using the `index_var` property.
    """

    PROPERTIES = (
        COUNT, INDEX_VAR, RESOURCE_DEF,
    ) = (
        'count', 'index_var', 'resource_def',
    )

    _RESOURCE_DEF_KEYS = (
        RESOURCE_DEF_TYPE, RESOURCE_DEF_PROPERTIES,
    ) = (
        'type', 'properties',
    )

    ATTRIBUTES = (
        REFS, ATTR_ATTRIBUTES,
    ) = (
        'refs', 'attributes',
    )

    properties_schema = {
        COUNT: properties.Schema(
            properties.Schema.INTEGER,
            _('The number of instances to create.'),
            default=1,
            constraints=[
                constraints.Range(min=0),
            ],
            update_allowed=True
        ),
        INDEX_VAR: properties.Schema(
            properties.Schema.STRING,
            _('A variable that this resource will use to replace with the '
              'current index of a given resource in the group. Can be used, '
              'for example, to customize the name property of grouped '
              'servers in order to differentiate them when listed with '
              'nova client.'),
            default="%index%",
            constraints=[
                constraints.Length(min=3)
            ]
        ),
        RESOURCE_DEF: properties.Schema(
            properties.Schema.MAP,
            _('Resource definition for the resources in the group. The value '
              'of this property is the definition of a resource just as if '
              'it had been declared in the template itself.'),
            schema={
                RESOURCE_DEF_TYPE: properties.Schema(
                    properties.Schema.STRING,
                    _('The type of the resources in the group'),
                    required=True
                ),
                RESOURCE_DEF_PROPERTIES: properties.Schema(
                    properties.Schema.MAP,
                    _('Property values for the resources in the group')
                ),
            },
            required=True
        ),
    }

    attributes_schema = {
        REFS: attributes.Schema(
            _("A list of resource IDs for the resources in the group")
        ),
        ATTR_ATTRIBUTES: attributes.Schema(
            _("A map of resource names to the specified attribute of each "
              "individual resource.")
        ),
    }

    def validate(self):
        # validate our basic properties
        super(ResourceGroup, self).validate()
        # make sure the nested resource is valid
        test_tmpl = self._assemble_nested(["0"], include_all=True)
        val_templ = template.Template(test_tmpl)
        res_def = val_templ.resource_definitions(self.stack)["0"]
        res_class = self.stack.env.get_class(res_def.resource_type)
        res_inst = res_class("%s:resource_def" % self.name, res_def,
                             self.stack)
        res_inst.validate()

    def _resource_names(self, properties=None):
        p = properties or self.properties
        return [str(n) for n in range(p.get(self.COUNT, 0))]

    def handle_create(self):
        names = self._resource_names()
        return self.create_with_template(self._assemble_nested(names),
                                         {}, self.stack.timeout_mins)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        self.properties = json_snippet.properties(self.properties_schema,
                                                  self.context)
        new_names = self._resource_names()
        return self.update_with_template(self._assemble_nested(new_names),
                                         {},
                                         self.stack.timeout_mins)

    def handle_delete(self):
        return self.delete_nested()

    def FnGetAtt(self, key, *path):
        nested_stack = self.nested()

        def get_resource(resource_name):
            try:
                return nested_stack[resource_name]
            except KeyError:
                raise exception.InvalidTemplateAttribute(resource=self.name,
                                                         key=key)

        def get_rsrc_attr(resource_name, *attr_path):
            resource = get_resource(resource_name)
            return resource.FnGetAtt(*attr_path)

        def get_rsrc_id(resource_name):
            resource = get_resource(resource_name)
            return resource.FnGetRefId()

        if key.startswith("resource."):
            path = key.split(".", 2)[1:] + list(path)
            if len(path) > 1:
                return get_rsrc_attr(*path)
            else:
                return get_rsrc_id(*path)

        names = self._resource_names()
        if key == self.REFS:
            return [get_rsrc_id(n) for n in names]
        if key == self.ATTR_ATTRIBUTES:
            if not path:
                raise exception.InvalidTemplateAttribute(
                    resource=self.name, key=key)
            return dict((n, get_rsrc_attr(n, *path)) for n in names)

        path = [key] + list(path)
        return [get_rsrc_attr(n, *path) for n in names]

    def _build_resource_definition(self, include_all=False):
        res_def = self.properties[self.RESOURCE_DEF]
        if res_def[self.RESOURCE_DEF_PROPERTIES] is None:
            res_def[self.RESOURCE_DEF_PROPERTIES] = {}
        if not include_all:
            resource_def_props = res_def[self.RESOURCE_DEF_PROPERTIES]
            clean = dict((k, v) for k, v in resource_def_props.items() if v)
            res_def[self.RESOURCE_DEF_PROPERTIES] = clean
        return res_def

    def _handle_repl_val(self, res_name, val):
        repl_var = self.properties[self.INDEX_VAR]
        recurse = lambda x: self._handle_repl_val(res_name, x)
        if isinstance(val, basestring):
            return val.replace(repl_var, res_name)
        elif isinstance(val, collections.Mapping):
            return dict(zip(val, map(recurse, val.values())))
        elif isinstance(val, collections.Sequence):
            return map(recurse, val)
        return val

    def _do_prop_replace(self, res_name, res_def_template):
        res_def = copy.deepcopy(res_def_template)
        props = res_def[self.RESOURCE_DEF_PROPERTIES]
        if props:
            props = self._handle_repl_val(res_name, props)
            res_def[self.RESOURCE_DEF_PROPERTIES] = props
        return res_def

    def _assemble_nested(self, names, include_all=False):
        res_def = self._build_resource_definition(include_all)

        resources = dict((k, self._do_prop_replace(k, res_def))
                         for k in names)
        child_template = copy.deepcopy(template_template)
        child_template['resources'] = resources
        return child_template

    def child_template(self):
        names = self._resource_names()
        return self._assemble_nested(names)

    def child_params(self):
        return {}

    def handle_adopt(self, resource_data):
        names = self._resource_names()
        if names:
            return self.create_with_template(self._assemble_nested(names),
                                             {},
                                             adopt_data=resource_data)

    def check_adopt_complete(self, adopter):
        if adopter is None:
            return True
        done = adopter.step()
        if done:
            if self._nested.state != (self._nested.ADOPT,
                                      self._nested.COMPLETE):
                raise exception.Error(self._nested.status_reason)

        return done


def resource_mapping():
    return {
        'OS::Heat::ResourceGroup': ResourceGroup,
    }
