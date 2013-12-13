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

import copy

from heat.engine import parser
from heat.engine import properties
from heat.engine import constraints
from heat.engine import stack_resource
from heat.common import exception

from heat.openstack.common.gettextutils import _

template_template = {
    "heat_template_version": "2013-05-23",
    "resources": {}
}


class ResourceGroup(stack_resource.StackResource):
    """
    A resource that creates one or more identically configured nested
    resources. The attributes of this resource mirror those of the
    nested resource definition.

    The attributes of this resource mirror the attributes of the resources
    in the group except a list of attribute values for each resource in
    the group is returned. Additionally, attributes for individual resources
    in the group can be accessed using synthetic attributes of the form
    "resource.[index].[attribute name]"
    """

    PROPERTIES = (
        COUNT, RESOURCE_DEF,
    ) = (
        'count', 'resource_def',
    )

    _RESOURCE_DEF_KEYS = (
        RESOURCE_DEF_TYPE, RESOURCE_DEF_PROPERTIES,
    ) = (
        'type', 'properties',
    )

    properties_schema = {
        COUNT: properties.Schema(
            properties.Schema.INTEGER,
            _('The number of instances to create.'),
            default=1,
            required=True,
            constraints=[
                constraints.Range(min=1),
            ],
            update_allowed=True
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

    attributes_schema = {}

    update_allowed_keys = ("Properties",)

    def validate(self):
        # validate our basic properties
        super(ResourceGroup, self).validate()
        # make sure the nested resource is valid
        test_tmpl = self._assemble_nested(1, include_all=True)
        val_templ = parser.Template(test_tmpl)
        res_def = val_templ["Resources"]["0"]
        res_class = self.stack.env.get_class(res_def['Type'])
        res_inst = res_class("%s:resource_def" % self.name, res_def,
                             self.stack)
        res_inst.validate()

    def handle_create(self):
        count = self.properties[self.COUNT]
        return self.create_with_template(self._assemble_nested(count),
                                         {},
                                         self.stack.timeout_mins)

    def handle_update(self, new_snippet, tmpl_diff, prop_diff):
        count = prop_diff.get("count")
        if count:
            return self.update_with_template(self._assemble_nested(count),
                                             {},
                                             self.stack.timeout_mins)

    def handle_delete(self):
        return self.delete_nested()

    def FnGetAtt(self, key):
        if key.startswith("resource."):
            parts = key.split(".", 2)
            attr_name = parts[-1]
            try:
                res = self.nested()[parts[1]]
            except KeyError:
                raise exception.InvalidTemplateAttribute(resource=self.name,
                                                         key=key)
            else:
                return res.FnGetAtt(attr_name)
        else:
            return [self.nested()[str(v)].FnGetAtt(key) for v
                    in range(self.properties[self.COUNT])]

    def _assemble_nested(self, count, include_all=False):
        child_template = copy.deepcopy(template_template)
        resource_def = self.properties[self.RESOURCE_DEF]
        if not include_all:
            resource_def_props = resource_def[self.RESOURCE_DEF_PROPERTIES]
            clean = dict((k, v) for k, v in resource_def_props.items() if v)
            resource_def[self.RESOURCE_DEF_PROPERTIES] = clean
        resources = dict((str(k), resource_def)
                         for k in range(count))
        child_template['resources'] = resources
        return child_template


def resource_mapping():
    return {
        'OS::Heat::ResourceGroup': ResourceGroup,
    }
