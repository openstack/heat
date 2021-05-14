..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

.. _supportstatus:

===============================
Heat Support Status usage Guide
===============================
Heat allows to use for each resource, property, attribute special option named
*support_status*, which describes current state of object: current status,
since what time this status is actual, any additional information about
object's state. This guide describes a detailed state life cycle of resources,
properties and attributes.

Support Status option and its parameters
----------------------------------------
Support status of object may be specified by using class ``SupportStatus``,
which has follow options:

*status*:
  Current status of object. Allowed values:
    - SUPPORTED. Default value of status parameter. All objects with this
      status are available and can be used.
    - DEPRECATED. Object with this status is available, but using it in
      code or templates is undesirable. As usual, can be reference in message
      to new object, which can be used instead of deprecated resource.
    - HIDDEN. The last step in the deprecation process. Old stacks
      containing resources in this status will continue
      functioning. Certain functionality is disabled for resources in
      this status (resource-type-list, resource-type-show, and
      resource-type-template). Resources in HIDDEN status are not
      included in the documentation. A known limitation is that new
      stacks can be created with HIDDEN resources. See below for more
      details about the removal and deprecation process.
    - UNSUPPORTED. Resources with UNSUPPORTED status are not supported by Heat
      team, i.e. user can use it, but it may be broken.

*substitute_class*:
  Assign substitute class for object. If replacing the object with new object
  which inherited (or extended) from the substitute class will transfer the
  object to new class type gracefully (without calling update replace).

*version*:
  Release name, since which current status is active. Parameter is optional,
  but should be defined or changed any time SupportStatus is specified or
  status changed. It used for better understanding from which release object
  in current status.
  .. note::

     Since Liberty release mark looks like 5.0.0 instead of 2015.2.

*message*:
  Any additional information about object's state, e.g.
  ``'Use property new_property instead.'``.

*previous_status*:
  Option, which allows to display object's previous status, if any. This is
  helpful for displaying full life cycle of object. Type of *previous_status*
  is SupportStatus.

Life cycle of resource, property, attribute
-------------------------------------------
This section describes life cycle of such objects as resource, property
and attribute. All these objects have same life cycle::

  UNSUPPORTED -> SUPPORTED -> DEPRECATED -> HIDDEN
                                        \
                                         -> UNSUPPORTED

where UNSUPPORTED is optional.

Creating process of object
++++++++++++++++++++++++++
During creating object there is a reason to add support status. So new
object should contains *support_status* parameter equals to ``SupportStatus``
class with defined version of object and, maybe, *substitute_class* or some
message. This parameter allows user to understand, from which OpenStack
release this object is available and can be used.

Deprecating process of object
+++++++++++++++++++++++++++++
When some object becomes obsolete, user should know about that, so there is
need to add information about deprecation in *support_status* of object.
Status of ``SupportStatus`` must equals to DEPRECATED. If there is no *version*
parameter, need to add one with current release otherwise move current status
to *previous_status* and add to *version* current release as value. If some new
object replaces old object, it will be good decision to add some information
about new object to *support_status* message of old object, e.g. 'Use property
new_property instead.'. If old object is directly replaceable by new object,
we should add *substitute_class* to *support_status* in old object.

Removing process of object
++++++++++++++++++++++++++
After at least one full release cycle deprecated object should be hidden and
*support_status* status should equals to HIDDEN. HIDDEN status means hiding
object from documentation and from result of :code:`resource-type-list` CLI
command, if object is resource. Also, :code:`resource-type-show` command with
such resource will raise `NotSupported` exception.

The purpose of hiding, rather than removing, obsolete resources or properties
is to ensure that users can continue to operate existing stacks - replacing or
removing the offending resources, or deleting the entire stack. Steps should be
taken to ensure that these operations can succeed, e.g. by replacing a hidden
resource type's implementation with one that is equivalent to
``OS::Heat::None`` when the underlying API no longer exists, supplying a
*substitute_class* for a resource type, or adding a property translation rule.

Using Support Status during code writing
----------------------------------------
When adding new objects or adding objects instead of some old (e.g. property
subnet instead of subnet_id in OS::Neutron::RouterInterface), there is some
information about time of adding objects (since which release it will be
available or unavailable). This section described ``SupportStatus`` during
creating/deprecating/removing resources and properties and attributes. Note,
that ``SupportStatus`` locates in support.py, so you need to import *support*.
For specifying status, use *support* constant names, e.g. support.SUPPORTED.
All constant names described in section above.

Using Support Status during creation
++++++++++++++++++++++++++++++++++++
Option *support_status* may be used for whole resource:

.. code-block:: python

   class ResourceWithType(resource.Resource):

       support_status=support.SupportStatus(
           version='5.0.0',
           message=_('Optional message')
       )

To define *support_status* for property or attribute, follow next steps:

.. code-block:: python

   PROPERTY: properties.Schema(
       ...
       support_status=support.SupportStatus(
           version='5.0.0',
           message=_('Optional message')
       )
   )

Same support_status definition for attribute schema.

Note, that in this situation status parameter of ``SupportStatus`` uses default
value, equals to SUPPORTED.

Using Support Status during deprecation and hiding
++++++++++++++++++++++++++++++++++++++++++++++++++
When time of deprecation or hiding resource/property/attribute comes, follow
next steps:

1. If there is some support_status in object, add `previous_status` parameter
   with current ``SupportStatus`` value and change all other parameters for
   current `status`, `version` and, maybe, `substitute_class` or `message`.

2. If there is no support_status option, add new one with parameters status
   equals to current status, `version` equals to current release note and,
   optionally, some message.

Using Support Status during resource deprecating looks like:

.. code-block:: python

   class ResourceWithType(resource.Resource):

       support_status=support.SupportStatus(
           status=support.DEPRECATED,
           version='5.0.0',
           substitute_class=SubstituteResourceWithType,
           message=_('Optional message'),
           previous_status=support.SupportStatus(version='2014.2')
       )

Using Support Status during attribute (or property) deprecating looks like:

.. code-block:: python

   ATTRIBUTE: attributes.Schema(
       ...
       support_status=support.SupportStatus(
           status=support.DEPRECATED,
           version='5.0.0',
           message=_('Optional message like: Use attribute new_attr'),
           previous_status=support.SupportStatus(
               version='2014.2',
               message=_('Feature available since 2014.2'))
       )
   )

Same *support_status* defining for property schema.

Note, that during hiding object status should be equal support.HIDDEN
instead of support.DEPRECATED. Besides that, SupportStatus with DEPRECATED
status should be moved to *previous_status*, e.g.:

.. code-block:: python

    support.SupportStatus(
        status=support.HIDDEN,
        version='6.0.0',
        message=_('Some message'),
        previous_status=support.SupportStatus(
            status=support.DEPRECATED,
            version='2015.1',
            substitute_class=SubstituteResourceWithType,
            previous_status=support.SupportStatus(version='2014.2')
        )
    )

During hiding properties, if some hidden property has alternative, use
translation mechanism for translating properties from old to new one. See
below, how to use this mechanism.

Translating mechanism for hidden properties
-------------------------------------------

Sometimes properties become deprecated and replaced by another. There is
translation mechanism for that. Mechanism used for such cases:

1. If there are two properties in properties_schema, which have STRING,
   INTEGER, NUMBER or BOOLEAN type.
2. If there are two properties: one in LIST or MAP property sub-schema and
   another on the top schema.
3. If there are two properties in LIST property.
4. If there are non-LIST property and LIST property, which is designed to
   replace non-LIST property.
5. If there is STRING property, which contains name or ID of some entity, e.g.
   `subnet`, and should be resolved to entity's ID.

Mechanism has rules and executes them. To define rule, ``TranslationRule``
class called and specifies *translation_path* - list with path in
properties_schema for property which will be affected; *value* - value, which
will be added to property, specified by previous parameter; *value_name* - name
of old property, used for case 4; *value_path* - list with path in
properties_schema for property which will be used for getting value.
``TranslationRule`` supports next rules:

- *ADD*. This rule allows to add some value to LIST-type properties. Only
  LIST-type values can be added to such properties. Using for other
  cases is prohibited and will be returned with error.
- *REPLACE*. This rule allows to replace some property value to another. Used
  for all types of properties. Note, that if property has list type, then
  value will be replaced for all elements of list, where it needed. If
  element in such property must be replaced by value of another element of
  this property, *value_name* must be defined.
- *DELETE*. This rule allows to delete some property. If property has list
  type, then deleting affects value in all list elements.
- *RESOLVE* - This rule allows to resolve some property using client and the
  *finder* function. Finders may require an additional *entity* key.

Each resource, which has some hidden properties, which can be replaced by new,
must overload `translation_rules` method, which should return a list of
``TranslationRules``, for example:

.. code-block:: python

   def translation_rules(self, properties):
        rules = [
          translation.TranslationRule(
            properties,
            translation.TranslationRule.REPLACE,
            translation_path=[self.NETWORKS, self.NETWORK_ID],
            value_name=self.NETWORK_UUID),
          translation.TranslationRule(
            properties,
            translation.TranslationRule.RESOLVE,
            translation_path=[self.FLAVOR],
            client_plugin=self.client_plugin('nova'),
            finder='find_flavor_by_name_or_id')]
        return rules
