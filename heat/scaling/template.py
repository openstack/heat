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

from heat.engine import template


def _identity(resource_name, definition):
    return definition


def member_definitions(old_resources, new_definition,
                       num_resources, num_new,
                       get_new_id, customise=_identity):
    """Iterate over resource definitions for a scaling group

    Generates the definitions for the next change to the scaling group. Each
    item is a (name, definition) tuple.

    The input is a list of (name, definition) tuples for existing resources in
    the group, sorted in the order that they should be replaced or removed
    (i.e. the resource that should be the first to be replaced (on update) or
    removed (on scale down) appears at the beginning of the list.) New
    resources are added or old resources removed as necessary to ensure a total
    of num_resources.

    The number of resources to have their definition changed to the new one is
    controlled by num_new. This value includes any new resources to be added,
    with any shortfall made up by modifying the definitions of existing
    resources.
    """
    old_resources = old_resources[-num_resources:]
    num_create = num_resources - len(old_resources)
    num_replace = num_new - num_create

    for i in range(num_resources):
        if i < len(old_resources):
            old_name, old_definition = old_resources[i]
            custom_definition = customise(old_name, new_definition)
            if old_definition != custom_definition and num_replace > 0:
                num_replace -= 1
                yield old_name, custom_definition
            else:
                yield old_name, old_definition
        else:
            new_name = get_new_id()
            yield new_name, customise(new_name, new_definition)


def make_template(resource_definitions,
                  version=('heat_template_version', '2015-04-30'),
                  child_env=None):
    """Return a Template object containing the given resource definitions.

    By default, the template will be in the HOT format. A different format
    can be specified by passing a (version_type, version_string) tuple matching
    any of the available template format plugins.
    """
    tmpl = template.Template(dict([version]), env=child_env)
    for name, defn in resource_definitions:
        tmpl.add_resource(defn, name)

    return tmpl
