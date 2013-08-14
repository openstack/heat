# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


(TYPE, PROPERTIES, SCRIPTS, RELATIONSHIPS) = (
    'type', 'properties', 'scripts', 'relationships')

(SOFTWARE_CONFIG_TYPE, HOSTED_ON, DEPENDS_ON) = (
    'OS::Heat::SoftwareConfig', 'hosted_on', 'depends_on')


class Component(dict):
    """
    Model for hot component.
    """

    def __init__(self, schema={}):
        super(Component, self).__init__(schema)

    @property
    def properties(self):
        return self.get(PROPERTIES, {})

    @property
    def type(self):
        return self.get(TYPE, SOFTWARE_CONFIG_TYPE)

    @property
    def scripts(self):
        return self.get(SCRIPTS, {})

    @property
    def relations(self):
        return self.get(RELATIONSHIPS, [])

    def hosted_on(self):
        for rel in self.relations:
            if HOSTED_ON in rel:
                return rel[HOSTED_ON]
        return None

    def depends(self):
        deps = []
        rels = self.relations
        for rel in rels:
            if DEPENDS_ON in rel:
                deps.append(rel[DEPENDS_ON])
        return deps


class Components(dict):
    """
    Model for hot components.
    """

    def __init__(self, schema):
        items = schema.iteritems()
        schema = dict(map(lambda x: (x[0], Component(x[1])), items))
        super(Components, self).__init__(schema)

    def depends(self):
        deps = []
        for (k, v) in self.iteritems():
            for dep in v.depends():
                if dep not in deps:
                    deps.append(dep)
        return deps

    def filter(self, hosted):
        return map(lambda x: x[0],
                   filter(lambda x: x[1].hosted_on() == hosted,
                          self.iteritems()))

    def validate(self):
        deps = self.depends()
        for dep in deps:
            if dep not in self.iterkeys():
                raise ValueError('component %s is not defined.' % dep)
            comp = self[dep]
            if dep in comp.depends():
                raise ValueError('component %s depends on itself.' % dep)
        for (name, comp) in self.iteritems():
            cdeps = comp.depends()
            for dep in cdeps:
                if cdeps.count(dep) > 1:
                    msg = 'duplicated %s in %s depends on.' % (dep, name)
                    raise ValueError(msg)
        return True
