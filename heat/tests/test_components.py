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

from heat.engine.components import Component
from heat.engine.components import Components
from heat.tests.common import HeatTestCase


class ComponentTest(HeatTestCase):

    def test_init(self):
        comp = Component()
        self.assertEqual(comp.type, 'OS::Heat::SoftwareConfig')
        self.assertEqual(comp.properties, {})
        self.assertEqual(comp.scripts, {})
        self.assertEqual(comp.relations, [])
        self.assertEqual(comp.hosted_on(), None)
        self.assertEqual(comp.depends(), [])

    def test_hosted_on(self):
        schema = {
            'relationships': [
                {'hosted_on': 'wordpress'}
            ]
        }
        comp = Component(schema)
        self.assertEqual(comp.hosted_on(), 'wordpress')

    def test_depends(self):
        schema = {
            'relationships': [
                {'depends_on': 'config_mysql'}
            ]
        }
        comp = Component(schema)
        self.assertEqual(comp.depends(), ['config_mysql'])

        comp['relationships'].append({'depends_on': 'config_wordpress'})
        self.assertEqual(comp.depends(),
                         ['config_mysql', 'config_wordpress'])


class ComponentsTest(HeatTestCase):

    def test_init(self):
        schema = {}
        comps = Components(schema)
        self.assertEqual(0, len(comps))

        schema['config_mysql'] = {}
        comps = Components(schema)
        self.assertEquals(1, len(comps))
        comp = comps['config_mysql']
        self.assertIsInstance(comp, Component)

    def test_depends(self):
        schema = {
            'install_mysql': {
            },
            'config_mysql': {
                'relationships': [
                    {'depends_on': 'install_mysql'}
                ]
            },
            'start_mysql': {
                'relationships': [
                    {'depends_on': 'config_mysql'}
                ]
            }
        }
        comps = Components(schema)
        self.assertEqual(3, len(comps))
        deps = comps.depends()
        self.assertEqual(2, len(deps))
        self.assertIn('install_mysql', deps)
        self.assertIn('config_mysql', deps)

    def test_multi_depends(self):
        schema = {
            'install_mysql': {
            },
            'config_mysql': {
                'relationships': [
                    {'depends_on': 'install_mysql'}
                ]
            },
            'start_mysql': {
                'relationships': [
                    {'depends_on': 'config_mysql'}
                ]
            },
            'install_wordpress': {},
            'config_wordpress': {
                'relationships': [
                    {'depends_on': 'install_wordpress'}
                ]
            },
            'start_wordpress': {
                'relationships': [
                    {'depends_on': 'config_wordpress'},
                    {'depends_on': 'start_mysql'}
                ]
            }
        }
        comps = Components(schema)
        deps = comps.depends()
        self.assertEqual(5, len(deps))
        self.assertNotIn('start_wordpress', deps)
        self.assertIn('install_wordpress', deps)
        self.assertIn('config_wordpress', deps)
        self.assertIn('start_mysql', deps)
        self.assertIn('config_mysql', deps)
        self.assertIn('install_mysql', deps)

    def test_filter(self):
        schema = {
            'install_mysql': {
                'relationships': [
                    {'hosted_on': 'mysql'}
                ]
            },
            'config_mysql': {
                'relationships': [
                    {'hosted_on': 'mysql'},
                    {'depends_on': 'install_mysql'}
                ]
            },
            'start_mysql': {
                'relationships': [
                    {'hosted_on': 'mysql'},
                    {'depends_on': 'config_mysql'}
                ]
            },
            'install_wordpress': {
                'relationships': [
                    {'hosted_on': 'wordpress'}
                ]
            },
            'config_wordpress': {
                'relationships': [
                    {'hosted_on': 'wordpress'},
                    {'depends_on': 'install_wordpress'}
                ]
            },
            'start_wordpress': {
                'relationships': [
                    {'hosted_on': 'wordpress'},
                    {'depends_on': 'config_wordpress'},
                    {'depends_on': 'start_mysql'}
                ]
            }
        }

        comps = Components(schema)
        names = comps.filter('mysql')
        self.assertEqual(3, len(names))
        self.assertIn('config_mysql', names)
        self.assertIn('install_mysql', names)
        self.assertIn('start_mysql', names)

        names = comps.filter('wordpress')
        self.assertEqual(3, len(names))
        self.assertIn('config_wordpress', names)
        self.assertIn('install_wordpress', names)
        self.assertIn('start_wordpress', names)

    def test_validate(self):
        schema = {'install_mysql': {}}
        comps = Components(schema)
        self.assertTrue(comps.validate())

        schema = {
            'config_mysql': {
                'relationships': [
                    {'depends_on': 'config_mysql'}
                ]
            }
        }
        comps = Components(schema)
        err = self.assertRaises(ValueError, comps.validate)
        self.assertIn('component config_mysql depends on itself.', str(err))

        schema = {
            'config_mysql': {
                'relationships': [
                    {'depends_on': 'install_mysql'}
                ]
            }
        }
        comps = Components(schema)
        err = self.assertRaises(ValueError, comps.validate)
        self.assertIn('component install_mysql is not defined.', str(err))

        schema = {
            'install_mysql': {
            },
            'config_mysql': {
                'relationships': [
                    {'depends_on': 'install_mysql'},
                    {'depends_on': 'install_mysql'}
                ]
            }
        }
        comps = Components(schema)
        err = self.assertRaises(ValueError, comps.validate)
        self.assertIn('duplicated install_mysql in config_mysql depends on.',
                      str(err))
