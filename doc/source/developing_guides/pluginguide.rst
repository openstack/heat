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

=======================================
Heat Resource Plug-in Development Guide
=======================================
Heat allows service providers to extend the capabilities of the orchestration
service by writing their own resource plug-ins. These plug-ins are written in
Python and included in a directory configured by the service provider. This
guide describes a resource plug-in structure and life cycle in order to assist
developers in writing their own resource plug-ins.

Resource Plug-in Life Cycle
---------------------------
A resource plug-in is relatively simple in that it needs to extend a base
``Resource`` class and implement some relevant life cycle handler methods.
The basic life cycle methods of a resource are:

create
  The plug-in should create a new physical resource.

update
  The plug-in should update an existing resource with new
  configuration or tell the engine that the resource must be destroyed
  and re-created.  This method is optional; the default behavior is to
  create a replacement resource and then delete the old resource.

suspend
  The plug-in should suspend operation of the physical resource; this is
  an optional operation.

resume
  The plug-in should resume operation of the physical resource; this is an
  optional operation.

delete
  The plug-in should delete the physical resource.

The base class ``Resource`` implements each of these life cycle methods and
defines one or more handler methods that plug-ins can implement in order
to manifest and manage the actual physical resource abstracted by the plug-in.
These handler methods will be described in detail in the following sections.

Heat Resource Base Class
++++++++++++++++++++++++
Plug-ins must extend the class ``heat.engine.resource.Resource``.

This class is responsible for managing the overall life cycle of the plug-in.
It defines methods corresponding to the life cycle as well as the basic hooks
for plug-ins to handle the work of communicating with specific down-stream
services. For example, when the engine determines it is time to create a
resource, it calls the ``create`` method of the applicable plug-in. This method
is implemented in the ``Resource`` base class and handles most of the
bookkeeping and interaction with the engine. This method then calls a
``handle_create`` method defined in the plug-in class (if implemented) which is
responsible for using specific service calls or other methods needed to
instantiate the desired physical resource (server, network, volume, etc).

Resource Status and Action
**************************

The base class handles reporting state of the resource back to the engine.
A resource's state is the combination of the life cycle action and the status
of that action. For example, if a resource is created successfully, the state
of that resource will be ``CREATE_COMPLETE``. Alternatively, if the plug-in
encounters an error when attempting to create the physical resource, the
state would be ``CREATE_FAILED``. The base class handles the
reporting and persisting of resource state, so a plug-in's handler
methods only need to return data or raise exceptions as appropriate.

Resource Support Status
***********************

New resource should be marked from which OpenStack release it will be available
with *support_status* option. For more details, see
:ref:`supportstatus`.

Resource description
********************

An important part of future resources is a concisely written description. It
should be in class docstring and contain information about the resource and
how it could be useful to the end-user. The docstring description is used in
documentation generation and should be always defined, if resource is designed
for public use. Docstring should follows `PEP 257
<https://www.python.org/dev/peps/pep-0257/>`_.

.. code-block:: python

    class CustomResource(resource.Resource):
        """This custom resource has description.

        Now end-users could understand the meaning of the resource existing
        and will use it correctly without any additional questions.
        """

Properties and Attributes
+++++++++++++++++++++++++
A resource's *properties* define the settings the template author can
manipulate when including that resource in a template. Some examples would be:

* Which flavor and image to use for a Nova server
* The port to listen to on Neutron LBaaS nodes
* The size of a Cinder volume

.. note::

   Properties should normally be accessed through self.properties.
   This resolves intrinsic functions, provides default values when required
   and performs property translation for backward compatible schema changes.
   The self.properties.data dict provides access to the raw data supplied by
   the user in the template without any of those transformations.

*Attributes* describe runtime state data of the physical resource that the
plug-in can expose to other resources in a Stack. Generally, these aren't
available until the physical resource has been created and is in a usable
state. Some examples would be:

* The host id of a Nova server
* The status of a Neutron network
* The creation time of a Cinder volume

Defining Resource Properties
****************************
Each property that a resource supports must be defined in a schema that informs
the engine and validation logic what the properties are, what type each is,
and validation constraints. The schema is a dictionary whose keys define
property names and whose values describe the constraints on that property. This
dictionary must be assigned to the ``properties_schema`` attribute of the
plug-in.

.. code-block:: python

    from heat.common.i18n import _
    from heat.engine import constraints
    from heat.engine import properties

        nested_schema = {
            "foo": properties.Schema(
                properties.Schema.STRING,
                _('description of foo field'),
                constraints=[
                    constraints.AllowedPattern('(Ba[rc]?)+'),
                    constraints.Length(max=10,
                                       description="don't go crazy")
                ]
            )
        }
        properties_schema = {
            "property_name": properties.Schema(
                properties.Schema.MAP,
                _('Internationalized description of property'),
                required=True,
                default={"Foo": "Bar"},
                schema=nested_schema
            )
        }

As shown above, some properties may themselves be complex and
reference nested schema definitions. Following are the parameters to the
``Schema`` constructor; all but the first have defaults.

*data_type*:

        Defines the type of the property's value. The valid types are
        the members of the list ``properties.Schema.TYPES``, currently
        ``INTEGER``, ``STRING``, ``NUMBER``, ``BOOLEAN``, ``MAP``, ``LIST``
        and ``ANY``; please use those symbolic names rather than the
        literals to which they are equated. For ``LIST`` and ``MAP``
        type properties, the ``schema`` referenced constrains the
        format of complex items in the list or map.

*description*:
  A description of the property and its function; also used in documentation
  generation.  Default is ``None`` --- but you should always provide a
  description.

*default*:
  The default value to assign to this property if none was supplied in the
  template.  Default is ``None``.

*schema*:
  This property's value is complex and its members must conform to
  this referenced schema in order to be valid. The referenced schema
  dictionary has the same format as the ``properties_schema``. Default
  is ``None``.

*required*:
        ``True`` if the property must have a value for the template to be valid;
        ``False`` otherwise. The default is ``False``

*constraints*:
  A list of constraints that apply to the property's value.  See
  `Property Constraints`_.

*update_allowed*:
  ``True`` if an existing resource can be updated, ``False`` means
  update is accomplished by delete and re-create.  Default is ``False``.

*immutable*:
  ``True`` means updates are not supported, resource update will fail on
  every change of this property. ``False`` otherwise. Default is ``False``.

*support_status*:
  Defines current status of the property. Read :ref:`supportstatus` for
  details.

Accessing property values of the plug-in at runtime is then a simple call to:

.. code-block:: python

        self.properties['PropertyName']

Based on the property type, properties without a set value will return the
default "empty" value for that type:

======= ============
Type    Empty Value
======= ============
String      ''
Number      0
Integer     0
List        []
Map         {}
Boolean     False
======= ============

Property Constraints
********************

Following are the available kinds of constraints.  The description is
optional and, if given, states the constraint in plain language for
the end user.

*AllowedPattern(regex, description)*:
  Constrains the value to match the given regular expression;
  applicable to STRING.

*AllowedValues(allowed, description)*:
  Lists the allowed values.  ``allowed`` must be a
  ``collections.Sequence`` or ``basestring``.  Applicable to all types
  of value except MAP.

*Length(min, max, description)*:
  Constrains the length of the value.  Applicable to STRING, LIST,
  MAP.  Both ``min`` and ``max`` default to ``None``.

*Range(min, max, description)*:
  Constrains a numerical value.  Applicable to INTEGER and NUMBER.
  Both ``min`` and ``max`` default to ``None``.

*Modulo(step, offset, description)*:
  Starting with the specified ``offset``, every multiple of ``step`` is a valid
  value. Applicable to INTEGER and NUMBER.

  Available from template version 2017-02-24.

*CustomConstraint(name, description, environment)*:
  This constructor brings in a named constraint class from an
  environment.  If the given environment is ``None`` (its default)
  then the environment used is the global one.

Defining Resource Attributes
****************************
Attributes communicate runtime state of the physical resource. Note that some
plug-ins do not define any attributes and doing so is optional. If the plug-in
needs to expose attributes, it will define an ``attributes_schema`` similar to
the properties schema described above. Each item in the schema dictionary
consists of an attribute name and an attribute Schema object.

.. code-block:: python

        attributes_schema = {
            "foo": attributes.Schema(
                _("The foo attribute"),
                type=attribute.Schema.STRING
            ),
            "bar": attributes.Schema(
                _("The bar attribute"),
                type=attribute.Schema.STRING
            ),
            "baz": attributes.Schema(
                _("The baz attribute"),
                type=attribute.Schema.STRING
            )
        }

Following are the parameters to the Schema.

*description*
  A description of the attribute; also used in documentation
  generation.  Default is ``None`` --- but you should always provide a
  description.

*type*
  Defines the type of attribute value. The valid types are
  the members of the list ``attributes.Schema.TYPES``, currently
  ``STRING``, ``NUMBER``, ``BOOLEAN``, ``MAP``, and ``LIST``; please use
  those symbolic names rather than the literals to which they are equated.

*support_status*
  Defines current status of the attribute. Read :ref:`supportstatus` for
  details.

If attributes are defined, their values must also be resolved by the plug-in.
The simplest way to do this is to override the ``_resolve_attribute`` method
from the ``Resource`` class:

.. code-block:: python

        def _resolve_attribute(self, name):
            # _example_get_physical_resource is just an example and is not
            # defined in the Resource class
            phys_resource = self._example_get_physical_resource()
            if phys_resource:
                if not hasattr(phys_resource, name):
                        # this is usually not needed, but this is a simple
                        # example
                        raise exception.InvalidTemplateAttribute(name)
                return getattr(phys_resource, name)
            return None

If the plug-in needs to be more sophisticated in its attribute resolution, the
plug-in may instead choose to override ``FnGetAtt``. However, if this method is
chosen, validation and accessibility of the attribute would be the plug-in's
responsibility.

Also, each resource has ``show`` attribute by default. The attribute uses
default implementation from ``heat.engine.resource.Resource`` class, but if
resource has different way of resolving ``show`` attribute, the
``_show_resource`` method from the ``Resource`` class will need to be
overridden:

.. code-block:: python

       def _show_resource(self):
           """Default implementation; should be overridden by resources.

           :returns: the map of resource information or None
           """
           if self.entity:
               try:
                   obj = getattr(self.client(), self.entity)
                   resource = obj.get(self.resource_id)
                   return resource.to_dict()
                except AttributeError as ex:
                    LOG.warning(_LW("Resolving 'show' attribute has "
                                    "failed : %s"), ex)
                    return None

Property and Attribute Example
******************************
Assume the following simple property and attribute definition:

.. code-block:: python

        properties_schema = {
            'foo': properties.Schema(
                properties.Schema.STRING,
                _('foo prop description'),
                default='foo',
                required=True
            ),
            'bar': properties.Schema(
                properties.Schema.INTEGER,
                _('bar prop description'),
                required=True,
                constraints=[
                    constraints.Range(5, 10)
                ]
            )
        }

        attributes_schema = {
            'Attr_1': attributes.Schema(
                _('The first attribute'),
                support_status=support.Status('5.0.0'),
                type=attributes.Schema.STRING
            ),
            'Attr_2': attributes.Schema(
                _('The second attribute'),
                type=attributes.Schema.MAP
            )
        }

Also assume the plug-in defining the above has been registered under the
template reference name 'Resource::Foo' (see `Registering Resource Plug-ins`_).
A template author could then use this plug-in in a stack by simply making
following declarations in a template:

.. code-block:: yaml

        # ... other sections omitted for brevity ...

        resources:
          resource-1:
            type: Resource::Foo
            properties:
              foo: Value of the foo property
              bar: 7

        outputs:
          foo-attrib-1:
            value: { get_attr: [resource-1, Attr_1] }
            description: The first attribute of the foo resource
          foo-attrib-2:
            value: { get_attr: [resource-1, Attr_2] }
            description: The second attribute of the foo resource

Life Cycle Handler Methods
++++++++++++++++++++++++++
To do the work of managing the physical resource the plug-in supports, the
following life cycle handler methods should be implemented. Note that the
plug-in need not implement *all* of these methods; optional handlers will
be documented as such.

Generally, the handler methods follow a basic pattern. The basic
handler method for any life cycle step follows the format
``handle_<life cycle step>``. So for the create step, the handler
method would be ``handle_create``. Once a handler is called, an
optional ``check_<life cycle step>_complete`` may also be implemented
so that the plug-in may return immediately from the basic handler and
then take advantage of cooperative multi-threading built in to the
base class and periodically poll a down-stream service for completion;
the check method is polled until it returns ``True``. Again, for the
create step, this method would be ``check_create_complete``.

Create
******
.. py:function:: handle_create(self)

  Create a new physical resource. This function should make the required
  calls to create the physical resource and return as soon as there is enough
  information to identify the resource. The function should return this
  identifying information and implement ``check_create_complete`` which will
  take this information in as a parameter and then periodically be polled.
  This allows for cooperative multi-threading between multiple resources that
  have had their dependencies satisfied.

  *Note* once the native identifier of the physical resource is known, this
  function should call ``self.resource_id_set`` passing the native identifier
  of the physical resource. This will persist the identifier and make it
  available to the plug-in by accessing ``self.resource_id``.

  :returns: A representation of the created physical resource
  :raise: any ``Exception`` if the create failed

.. py:function:: check_create_complete(self, token)

  If defined, will be called with the return value of ``handle_create``

  :param token: the return value of ``handle_create``; used to poll the
                physical resource's status.
  :returns: ``True`` if the physical resource is active and ready for use;
            ``False`` otherwise.
  :raise: any ``Exception`` if the create failed.

Update (Optional)
*****************
Note that there is a default implementation of ``handle_update`` in
``heat.engine.resource.Resource`` that simply raises an exception indicating
that updates require the engine to delete and re-create the resource
(this is the default behavior) so implementing this is optional.

.. py:function:: handle_update(self, json_snippet, tmpl_diff, prop_diff)

  Update the physical resources using updated information.

  :param json_snippet: the resource definition from the updated template
  :type json_snippet: collections.Mapping
  :param tmpl_diff: values in the updated definition that have changed
                    with respect to the original template definition.
  :type tmpl_diff: collections.Mapping
  :param prop_diff: property values that are different between the original
                    definition and the updated definition; keys are
                    property names and values are the new values. Deleted or
                    properties that were originally present but now absent
                    have values of ``None``
  :type prop_diff: collections.Mapping

  *Note* Before calling ``handle_update`` we check whether need to replace
  the resource, especially for resource in ``*_FAILED`` state, there is a
  default implementation of ``needs_replace_failed`` in
  ``heat.engine.resource.Resource`` that simply returns ``True`` indicating
  that updates require replacement. And we override the implementation for
  ``OS::Nova::Server``, ``OS::Cinder::Volume`` and all of neutron resources.
  The base principle is that to check whether the resource exists underlying
  and whether the real status is available. So override the method
  ``needs_replace_failed`` for your resource plug-ins if needed.

.. py:function:: check_update_complete(self, token)

  If defined, will be called with the return value of ``handle_update``

  :param token: the return value of ``handle_update``; used to poll the
                physical resource's status.
  :returns: ``True`` if the update has finished;
            ``False`` otherwise.
  :raise: any ``Exception`` if the update failed.

Suspend (Optional)
******************
*These handler functions are optional and only need to be implemented if the
physical resource supports suspending*

.. py:function:: handle_suspend(self)

  If the physical resource supports it, this function should call the native
  API and suspend the resource's operation. This function should return
  information sufficient for ``check_suspend_complete`` to poll the native
  API to verify the operation's status.

  :return: a token containing enough information for ``check_suspend_complete``
           to verify operation status.
  :raise: any ``Exception`` if the suspend operation fails.

.. py:function:: check_suspend_complete(self, token)

  Verify the suspend operation completed successfully.

  :param token: the return value of ``handle_suspend``
  :return: ``True`` if the suspend operation completed and the physical
           resource is now suspended; ``False`` otherwise.
  :raise: any ``Exception`` if the suspend operation failed.

Resume (Optional)
*****************
*These handler functions are optional and only need to be implemented if the
physical resource supports resuming from a suspended state*

.. py:function:: handle_resume(self)

  If the physical resource supports it, this function should call the native
  API and resume a suspended resource's operation. This function should return
  information sufficient for ``check_resume_complete`` to poll the native
  API to verify the operation's status.

  :return: a token containing enough information for ``check_resume_complete``
           to verify operation status.
  :raise: any ``Exception`` if the resume operation fails.

.. py:function:: check_resume_complete(self, token)

  Verify the resume operation completed successfully.

  :param token: the return value of ``handle_resume``
  :return: ``True`` if the resume operation completed and the physical resource
           is now active; ``False`` otherwise.
  :raise: any Exception if the resume operation failed.


Delete
******
.. py:function:: handle_delete(self)

  Delete the physical resource.

  :return: a token containing sufficient data to verify the operations status
  :raise: any ``Exception`` if the delete operation failed

  .. note::
     As of the Liberty release, implementing handle_delete is optional. The
     parent resource class can handle the most common pattern for deleting
     resources:

     .. code-block:: python

        def handle_delete(self):
            if self.resource_id is not None:
                try:
                    self.client().<entity>.delete(self.resource_id)
                except Exception as ex:
                    self.client_plugin().ignore_not_found(ex)
                    return None
                return self.resource_id

     For this to work for a particular resource, the `entity` and
     `default_client_name` attributes must be overridden in the resource
     implementation. For example, `entity` of Aodh Alarm should equals
     to "alarm" and `default_client_name` to "aodh".

.. py:function:: handle_delete_snapshot(self, snapshot)

  Delete resource snapshot.

  :param snapshot: dictionary describing current snapshot.
  :return: a token containing sufficient data to verify the operations status
  :raise: any ``Exception`` if the delete operation failed

.. py:function:: handle_snapshot_delete(self, state)

  Called instead of ``handle_delete`` when the deletion policy is SNAPSHOT.
  Create backup of resource and then delete resource.

  :param state: the (action, status) tuple of the resource to make sure that
                backup may be created for the current resource
  :return: a token containing sufficient data to verify the operations status
  :raise: any ``Exception`` if the delete operation failed

.. py:function:: check_delete_complete(self, token)

  Verify the delete operation completed successfully.

  :param token: the return value of ``handle_delete`` or
                ``handle_snapshot_delete`` (for deletion policy - Snapshot)
                used to verify the status of the operation
  :return: ``True`` if the delete operation completed and the physical resource
           is deleted; ``False`` otherwise.
  :raise: any ``Exception`` if the delete operation failed.

.. py:function:: check_delete_snapshot_complete(self, token)

  Verify the delete snapshot operation completed successfully.

  :param token: the return value of ``handle_delete_snapshot`` used
                to verify the status of the operation
  :return: ``True`` if the delete operation completed and the snapshot
           is deleted; ``False`` otherwise.
  :raise: any ``Exception`` if the delete operation failed.

Resource Dependencies
+++++++++++++++++++++

Ideally, your resource should not have any 'hidden' dependencies, i.e. Heat
should be able to infer any inbound or outbound dependencies of your resource
instances from resource properties and the other resources/resource attributes
they reference. This is handled by
``heat.engine.resource.Resource.add_dependencies()``.

If this is not possible, please do not simply override `add_dependencies()` in
your resource plugin! This has previously caused `problems
<https://bugs.launchpad.net/heat/+bug/1554625>`_ for multiple operations,
usually due to uncaught exceptions, If you feel you need to override
`add_dependencies()`, please reach out to Heat developers on the `#heat` IRC
channel on FreeNode or on the `openstack-dev
<mailto:openstack-dev@lists.openstack.org>`_ mailing list to discuss the
possibility of a better solution.

Registering Resource Plug-ins
+++++++++++++++++++++++++++++
To make your plug-in available for use in stack templates, the plug-in must
register a reference name with the engine. This is done by defining a
``resource_mapping`` function in your plug-in module that returns a map of
template resource type names and their corresponding implementation classes::

        def resource_mapping():
            return { 'My::Custom::Plugin': MyResourceClass }

This would allow a template author to define a resource as:

.. code-block:: yaml

        resources:
          my_resource:
            type: My::Custom::Plugin
            properties:
            # ... your plug-in's properties ...

Note that you can define multiple plug-ins per module by simply returning
a map containing a unique template type name for each. You may also use this to
register a single resource plug-in under multiple template type names (which
you would only want to do when constrained by backwards compatibility).

Configuring the Engine
----------------------
In order to use your plug-in, Heat must be configured to read your resources
from a particular directory. The ``plugin_dirs`` configuration option lists the
directories on the local file system where the engine will search for plug-ins.
Simply place the file containing your resource in one of these directories and
the engine will make them available next time the service starts.

See :doc:`../configuration/index` for more information on configuring the
orchestration service.

Testing
-------

Tests can live inside the plug-in under the ``tests``
namespace/directory. The Heat plug-in loader will implicitly not load
anything under that directory. This is useful when your plug-in tests
have dependencies you don't want installed in production.

Putting It All Together
-----------------------
You can find the plugin classes in ``heat/engine/resources``.  An
exceptionally simple one to start with is ``random_string.py``; it is
unusual in that it does not manipulate anything in the cloud!

Resource Contributions
----------------------

The Heat team is interested in adding new resources that give Heat access to
additional OpenStack or StackForge projects. The following checklist defines
the requirements for a candidate resource to be considered for inclusion:

- Must wrap an OpenStack or StackForge project, or a third party project that
  is relevant to OpenStack users.
- Must have its dependencies listed in OpenStack's ``global-requirements.txt``
  file, or else it should be able to conditionally disable itself when there
  are missing dependencies, without crashing or otherwise affecting the normal
  operation of the heat-engine service.
- The resource's support status flag must be set to ``UNSUPPORTED``, to
  indicate that the Heat team is not responsible for supporting this resource.
- The code must be of comparable quality to official resources. The Heat team
  can help with this during the review phase.

If you have a resource that is a good fit, you are welcome to contact the Heat
team. If for any reason your resource does not meet the above requirements,
but you still think it can be useful to other users, you are encouraged to
host it on your own repository and share it as a regular Python installable
package. You can find example resource plug-ins that have all the required
packaging files in the ``contrib`` directory of the official Heat git
repository.
