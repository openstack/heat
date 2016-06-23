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
from oslo_log import log as logging
import six

from heat.common.i18n import _LW
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources import signal_responder
from heat.engine.resources import stack_resource
from heat.engine.resources import stack_user
from heat.engine import support
LOG = logging.getLogger(__name__)


class GenericResource(resource.Resource):
    """Dummy resource for use in tests."""
    properties_schema = {}
    attributes_schema = collections.OrderedDict([
        ('foo', attributes.Schema('A generic attribute')),
        ('Foo', attributes.Schema('Another generic attribute'))])

    @classmethod
    def is_service_available(cls, context):
        return (True, None)

    def handle_create(self):
        LOG.warning(_LW('Creating generic resource (Type "%s")'),
                    self.type())

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        LOG.warning(_LW('Updating generic resource (Type "%s")'),
                    self.type())

    def handle_delete(self):
        LOG.warning(_LW('Deleting generic resource (Type "%s")'),
                    self.type())

    def _resolve_attribute(self, name):
        return self.name

    def handle_suspend(self):
        LOG.warning(_LW('Suspending generic resource (Type "%s")'),
                    self.type())

    def handle_resume(self):
        LOG.warning(_LW('Resuming generic resource (Type "%s")'),
                    self.type())


class ResWithShowAttr(GenericResource):
    def _show_resource(self):
        return {'foo': self.name,
                'Foo': self.name,
                'Another': self.name}


class ResWithStringPropAndAttr(GenericResource):

    properties_schema = {
        'a_string': properties.Schema(properties.Schema.STRING)}

    attributes_schema = {'string': attributes.Schema('A string')}

    def _resolve_attribute(self, name):
        try:
            return self.properties["a_%s" % name]
        except KeyError:
            return None


class ResWithComplexPropsAndAttrs(ResWithStringPropAndAttr):

    properties_schema = {
        'a_string': properties.Schema(properties.Schema.STRING),
        'a_list': properties.Schema(properties.Schema.LIST),
        'a_map': properties.Schema(properties.Schema.MAP),
        'an_int': properties.Schema(properties.Schema.INTEGER)}

    attributes_schema = {'list': attributes.Schema('A list'),
                         'map': attributes.Schema('A map'),
                         'string': attributes.Schema('A string')}
    update_allowed_properties = ('an_int',)

    def _resolve_attribute(self, name):
        try:
            return self.properties["a_%s" % name]
        except KeyError:
            return None


class ResourceWithProps(GenericResource):
    properties_schema = {
        'Foo': properties.Schema(properties.Schema.STRING),
        'FooInt': properties.Schema(properties.Schema.INTEGER)}


class ResourceWithPropsRefPropOnDelete(ResourceWithProps):
    def check_delete_complete(self, cookie):
        return self.properties['FooInt'] is not None


class ResourceWithPropsRefPropOnValidate(ResourceWithProps):
    def validate(self):
        super(ResourceWithPropsRefPropOnValidate, self).validate()
        self.properties['FooInt'] is not None


class ResourceWithPropsAndAttrs(ResourceWithProps):
    attributes_schema = {'Bar': attributes.Schema('Something.')}


class ResourceWithResourceID(GenericResource):
    properties_schema = {'ID': properties.Schema(properties.Schema.STRING)}

    def handle_create(self):
        super(ResourceWithResourceID, self).handle_create()
        self.resource_id_set(self.properties.get('ID'))

    def handle_delete(self):
        self.mox_resource_id(self.resource_id)

    def mox_resource_id(self, resource_id):
        pass


class ResourceWithComplexAttributes(GenericResource):
    attributes_schema = {
        'list': attributes.Schema('A list'),
        'flat_dict': attributes.Schema('A flat dictionary'),
        'nested_dict': attributes.Schema('A nested dictionary'),
        'none': attributes.Schema('A None')
    }

    list = ['foo', 'bar']
    flat_dict = {'key1': 'val1', 'key2': 'val2', 'key3': 'val3'}
    nested_dict = {'list': [1, 2, 3],
                   'string': 'abc',
                   'dict': {'a': 1, 'b': 2, 'c': 3}}

    def _resolve_attribute(self, name):
        if name == 'list':
            return self.list
        if name == 'flat_dict':
            return self.flat_dict
        if name == 'nested_dict':
            return self.nested_dict
        if name == 'none':
            return None


class ResourceWithRequiredProps(GenericResource):
    properties_schema = {'Foo': properties.Schema(properties.Schema.STRING,
                                                  required=True)}


class ResourceWithMultipleRequiredProps(GenericResource):
    properties_schema = {'Foo1': properties.Schema(properties.Schema.STRING,
                                                   required=True),
                         'Foo2': properties.Schema(properties.Schema.STRING,
                                                   required=True),
                         'Foo3': properties.Schema(properties.Schema.STRING,
                                                   required=True)}


class ResourceWithRequiredPropsAndEmptyAttrs(GenericResource):
    properties_schema = {'Foo': properties.Schema(properties.Schema.STRING,
                                                  required=True)}
    attributes_schema = {}


class SignalResource(signal_responder.SignalResponder):
    SIGNAL_TRANSPORTS = (
        CFN_SIGNAL, TEMP_URL_SIGNAL, HEAT_SIGNAL, NO_SIGNAL,
        ZAQAR_SIGNAL
    ) = (
        'CFN_SIGNAL', 'TEMP_URL_SIGNAL', 'HEAT_SIGNAL', 'NO_SIGNAL',
        'ZAQAR_SIGNAL'
    )

    properties_schema = {
        'signal_transport': properties.Schema(properties.Schema.STRING,
                                              default='CFN_SIGNAL')}
    attributes_schema = {'AlarmUrl': attributes.Schema('Get a signed webhook'),
                         'signal': attributes.Schema('Get a signal')}

    def handle_create(self):
        self.password = 'password'
        super(SignalResource, self).handle_create()
        self.resource_id_set(self._get_user_id())

    def handle_signal(self, details=None):
        LOG.warning(_LW('Signaled resource (Type "%(type)s") %(details)s'),
                    {'type': self.type(), 'details': details})

    def _resolve_attribute(self, name):
        if self.resource_id is not None:
            if name == 'AlarmUrl':
                return self._get_signal().get('alarm_url')
            elif name == 'signal':
                return self._get_signal()


class StackUserResource(stack_user.StackUser):
    properties_schema = {}
    attributes_schema = {}

    def handle_create(self):
        super(StackUserResource, self).handle_create()
        self.resource_id_set(self._get_user_id())


class ResourceWithCustomConstraint(GenericResource):
    properties_schema = {
        'Foo': properties.Schema(
            properties.Schema.STRING,
            constraints=[constraints.CustomConstraint('neutron.network')])}


class ResourceWithAttributeType(GenericResource):
    attributes_schema = {
        'attr1': attributes.Schema('A generic attribute',
                                   type=attributes.Schema.STRING),
        'attr2': attributes.Schema('Another generic attribute',
                                   type=attributes.Schema.MAP)
    }

    def _resolve_attribute(self, name):
        if name == 'attr1':
            return "valid_sting"
        elif name == 'attr2':
            return "invalid_type"


class ResourceWithDefaultClientName(resource.Resource):
    default_client_name = 'sample'


class ResourceWithDefaultClientNameExt(resource.Resource):
    default_client_name = 'sample'
    required_service_extension = 'foo'


class ResourceWithFnGetAttType(GenericResource):
    def get_attribute(self, name):
        pass


class ResourceWithFnGetRefIdType(ResourceWithProps):
    def get_reference_id(self):
        return 'ID-%s' % self.name


class ResourceWithListProp(ResourceWithFnGetRefIdType):
    properties_schema = {"listprop": properties.Schema(properties.Schema.LIST)}


class StackResourceType(stack_resource.StackResource, GenericResource):
    def physical_resource_name(self):
        return "cb2f2b28-a663-4683-802c-4b40c916e1ff"

    def set_template(self, nested_template, params):
        self.nested_template = nested_template
        self.nested_params = params

    def handle_create(self):
        return self.create_with_template(self.nested_template,
                                         self.nested_params)

    def handle_adopt(self, resource_data):
        return self.create_with_template(self.nested_template,
                                         self.nested_params,
                                         adopt_data=resource_data)

    def handle_delete(self):
        self.delete_nested()

    def has_nested(self):
        if self.nested() is not None:
            return True

        return False


class ResourceWithRestoreType(ResWithComplexPropsAndAttrs):

    def handle_restore(self, defn, data):
        props = dict(
            (key, value) for (key, value) in
            six.iteritems(defn.properties(self.properties_schema))
            if value is not None)
        value = data['resource_data']['a_string']
        props['a_string'] = value
        return defn.freeze(properties=props)


class DynamicSchemaResource(resource.Resource):
    """Resource with an attribute not registered in the attribute schema."""
    properties_schema = {}

    attributes_schema = {
        'stat_attr': attributes.Schema('A generic static attribute',
                                       type=attributes.Schema.STRING),
    }

    def _init_attributes(self):
        # software deployment scheme is not static
        # so return dynamic attributes for it
        return attributes.DynamicSchemeAttributes(
            self.name, self.attributes_schema, self._resolve_attribute)

    def _resolve_attribute(self, name):
        if name == 'stat_attr':
            return "static_attribute"
        elif name == 'dynamic_attr':
            return "dynamic_attribute"
        else:
            raise KeyError()


class ResourceTypeUnSupportedLiberty(GenericResource):
    support_status = support.SupportStatus(
        version='5.0.0',
        status=support.UNSUPPORTED)


class ResourceTypeSupportedKilo(GenericResource):
    support_status = support.SupportStatus(
        version='2015.1')
