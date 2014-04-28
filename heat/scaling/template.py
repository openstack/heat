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

from heat.common import short_id

from heat.engine import template


def resource_templates(old_resources, resource_definition,
                       num_resources, num_replace):
    """
    Create the template for the nested stack of existing and new instances
    For rolling update, if launch configuration is different, the
    instance definition should come from the existing instance instead
    of using the new launch configuration.
    """
    old_resources = old_resources[-num_resources:]
    num_create = num_resources - len(old_resources)
    num_replace -= num_create

    for i in range(num_resources):
        if i < len(old_resources):
            old_name, old_template = old_resources[i]
            if old_template != resource_definition and num_replace > 0:
                num_replace -= 1
                yield old_name, resource_definition
            else:
                yield old_name, old_template
        else:
            yield short_id.generate_id(), resource_definition


def make_template(resource_definitions,
                  version=('heat_template_version', '2013-05-23')):
    """
    Return a Template object containing the given resource definitions.

    By default, the template will be in the HOT format. A different format
    can be specified by passing a (version_type, version_string) tuple matching
    any of the available template format plugins.
    """
    tmpl = template.Template(dict([version]))
    for name, defn in resource_definitions:
        tmpl.add_resource(defn, name)

    return tmpl
