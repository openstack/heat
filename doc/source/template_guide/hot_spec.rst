.. highlight: yaml
   :linenothreshold: 5

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

.. _hot_spec:

===============================================
Heat Orchestration Template (HOT) specification
===============================================

HOT is a new template format meant to replace the Heat
CloudFormation-compatible format (CFN) as the native format supported by the
Heat over time. This specification explains in detail all elements of the HOT
template format.
An example driven guide to writing HOT templates can be found
at :ref:`hot_guide`.

Status
~~~~~~

HOT is considered reliable, supported, and standardized as of our
Icehouse (April 2014) release. The Heat core team may make improvements
to the standard, which very likely would be backward compatible. The template
format is also versioned. Since Juno release, Heat supports multiple
different versions of the HOT specification.

Template structure
~~~~~~~~~~~~~~~~~~

HOT templates are defined in YAML and follow the structure outlined below.

.. code-block:: yaml

  heat_template_version: 2016-10-14

  description:
    # a description of the template

  parameter_groups:
    # a declaration of input parameter groups and order

  parameters:
    # declaration of input parameters

  resources:
    # declaration of template resources

  outputs:
    # declaration of output parameters

  conditions:
    # declaration of conditions

heat_template_version
    This key with value ``2013-05-23`` (or a later date) indicates that the
    YAML document is a HOT template of the specified version.

description
    This optional key allows for giving a description of the template, or the
    workload that can be deployed using the template.

parameter_groups
    This section allows for specifying how the input parameters should be
    grouped and the order to provide the parameters in. This section is
    optional and can be omitted when necessary.

parameters
    This section allows for specifying input parameters that have to be
    provided when instantiating the template. The section is optional and can
    be omitted when no input is required.

resources
    This section contains the declaration of the single resources of the
    template. This section with at least one resource should be defined in any
    HOT template, or the template would not really do anything when being
    instantiated.

outputs
    This section allows for specifying output parameters available to users
    once the template has been instantiated. This section is optional and can
    be omitted when no output values are required.

conditions
    This optional section includes statements which can be used to restrict
    when a resource is created or when a property is defined. They can be
    associated with resources and resource properties in the
    ``resources`` section, also can be associated with outputs in the
    ``outputs`` sections of a template.

    Note: Support for this section is added in the Newton version.


.. _hot_spec_template_version:

Heat template version
~~~~~~~~~~~~~~~~~~~~~

The value of ``heat_template_version`` tells Heat not only the format of the
template but also features that will be validated and supported. Beginning with
the Newton release, the version can be either the date of the Heat release or
the code name of the Heat release. Heat currently supports the following values
for the ``heat_template_version`` key:

2013-05-23
----------
The key with value ``2013-05-23`` indicates that the YAML document is a HOT
template and it may contain features implemented until the Icehouse
release. This version supports the following functions (some are back
ported to this version)::

  get_attr
  get_file
  get_param
  get_resource
  list_join
  resource_facade
  str_replace
  Fn::Base64
  Fn::GetAZs
  Fn::Join
  Fn::MemberListToMap
  Fn::Replace
  Fn::ResourceFacade
  Fn::Select
  Fn::Split
  Ref

2014-10-16
----------
The key with value ``2014-10-16`` indicates that the YAML document is a HOT
template and it may contain features added and/or removed up until the Juno
release. This version removes most CFN functions that were supported in
the Icehouse release, i.e. the ``2013-05-23`` version. So the supported
functions now are::

  get_attr
  get_file
  get_param
  get_resource
  list_join
  resource_facade
  str_replace
  Fn::Select

2015-04-30
----------
The key with value ``2015-04-30`` indicates that the YAML document is a HOT
template and it may contain features added and/or removed up until the Kilo
release. This version adds the ``repeat`` function. So the complete list of
supported functions is::

  get_attr
  get_file
  get_param
  get_resource
  list_join
  repeat
  digest
  resource_facade
  str_replace
  Fn::Select

2015-10-15
----------
The key with value ``2015-10-15`` indicates that the YAML document is a HOT
template and it may contain features added and/or removed up until the
Liberty release. This version removes the *Fn::Select* function, path based
``get_attr``/``get_param`` references should be used instead. Moreover
``get_attr`` since this version returns dict of all attributes for the
given resource excluding *show* attribute, if there's no <attribute name>
specified, e.g. :code:`{ get_attr: [<resource name>]}`. This version
also adds the str_split function and support for passing multiple lists to
the existing list_join function. The complete list of supported functions
is::

  get_attr
  get_file
  get_param
  get_resource
  list_join
  repeat
  digest
  resource_facade
  str_replace
  str_split

2016-04-08
----------
The key with value ``2016-04-08`` indicates that the YAML document is a HOT
template and it may contain features added and/or removed up until the
Mitaka release. This version also adds the ``map_merge`` function which
can be used to merge the contents of maps. The complete list of supported
functions is::

  digest
  get_attr
  get_file
  get_param
  get_resource
  list_join
  map_merge
  repeat
  resource_facade
  str_replace
  str_split

2016-10-14 | newton
-------------------
The key with value ``2016-10-14`` or ``newton`` indicates that the YAML
document is a HOT template and it may contain features added and/or removed
up until the Newton release. This version adds the ``yaql`` function which
can be used for evaluation of complex expressions, the ``map_replace``
function that can do key/value replacements on a mapping, and the ``if``
function which can be used to return corresponding value based on condition
evaluation. The complete list of supported functions is::

  digest
  get_attr
  get_file
  get_param
  get_resource
  list_join
  map_merge
  map_replace
  repeat
  resource_facade
  str_replace
  str_split
  yaql
  if

This version adds ``equals`` condition function which can be used
to compare whether two values are equal, the ``not`` condition function
which acts as a NOT operator, the ``and`` condition function which acts
as an AND operator to evaluate all the specified conditions, the ``or``
condition function which acts as an OR operator to evaluate all the
specified conditions. The complete list of supported condition
functions is::

  equals
  get_param
  not
  and
  or

2017-02-24 | ocata
-------------------
The key with value ``2017-02-24`` or ``ocata`` indicates that the YAML
document is a HOT template and it may contain features added and/or removed
up until the Ocata release. This version adds the ``str_replace_strict``
function which raises errors for missing params and the ``filter`` function
which filters out values from lists. The complete list of supported
functions is::

  digest
  filter
  get_attr
  get_file
  get_param
  get_resource
  list_join
  map_merge
  map_replace
  repeat
  resource_facade
  str_replace
  str_replace_strict
  str_split
  yaql
  if

The complete list of supported condition functions is::

  equals
  get_param
  not
  and
  or

2017-09-01 | pike
-----------------
The key with value ``2017-09-01`` or ``pike`` indicates that the YAML
document is a HOT template and it may contain features added and/or removed
up until the Pike release. This version adds the ``make_url`` function for
assembling URLs, the ``list_concat`` function for combining multiple
lists, the ``list_concat_unique`` function for combining multiple
lists without repeating items, the ``string_replace_vstrict`` function
which raises errors for missing and empty params, and the ``contains``
function which checks whether specific value is in a sequence. The
complete list of supported functions is::

  digest
  filter
  get_attr
  get_file
  get_param
  get_resource
  list_join
  make_url
  list_concat
  list_concat_unique
  contains
  map_merge
  map_replace
  repeat
  resource_facade
  str_replace
  str_replace_strict
  str_replace_vstrict
  str_split
  yaql
  if

We support 'yaql' and 'contains' as condition functions in this version.
The complete list of supported condition functions is::

  equals
  get_param
  not
  and
  or
  yaql
  contains

2018-03-02 | queens
-------------------
The key with value ``2018-03-02`` or ``queens`` indicates that the YAML
document is a HOT template and it may contain features added and/or removed
up until the Queens release. The complete list of supported functions is::

  digest
  filter
  get_attr
  get_file
  get_param
  get_resource
  list_join
  make_url
  list_concat
  list_concat_unique
  contains
  map_merge
  map_replace
  repeat
  resource_facade
  str_replace
  str_replace_strict
  str_replace_vstrict
  str_split
  yaql
  if

The complete list of supported condition functions is::

  equals
  get_param
  not
  and
  or
  yaql
  contains

2018-08-31 | rocky
-------------------
The key with value ``2018-08-31`` or ``rocky`` indicates that the YAML
document is a HOT template and it may contain features added and/or removed
up until the Queens release. The complete list of supported functions is::

  digest
  filter
  get_attr
  get_file
  get_param
  get_resource
  list_join
  make_url
  list_concat
  list_concat_unique
  contains
  map_merge
  map_replace
  repeat
  resource_facade
  str_replace
  str_replace_strict
  str_replace_vstrict
  str_split
  yaql
  if

The complete list of supported condition functions is::

  equals
  get_param
  not
  and
  or
  yaql
  contains

.. _hot_spec_parameter_groups:

Parameter groups section
~~~~~~~~~~~~~~~~~~~~~~~~

The ``parameter_groups`` section allows for specifying how the input parameters
should be grouped and the order to provide the parameters in. These groups are
typically used to describe expected behavior for downstream user interfaces.

These groups are specified in a list with each group containing a list of
associated parameters. The lists are used to denote the expected order of the
parameters. Each parameter should be associated to a specific group only once
using the parameter name to bind it to a defined parameter in the
``parameters`` section.

.. code-block:: yaml

  parameter_groups:
  - label: <human-readable label of parameter group>
    description: <description of the parameter group>
    parameters:
    - <param name>
    - <param name>

label
    A human-readable label that defines the associated group of parameters.

description
    This attribute allows for giving a human-readable description of the
    parameter group.

parameters
    A list of parameters associated with this parameter group.

param name
    The name of the parameter that is defined in the associated ``parameters``
    section.


.. _hot_spec_parameters:

Parameters section
~~~~~~~~~~~~~~~~~~

The ``parameters`` section allows for specifying input parameters that have to
be provided when instantiating the template. Such parameters are typically used
to customize each deployment (e.g. by setting custom user names or passwords)
or for binding to environment-specifics like certain images.

Each parameter is specified in a separated nested block with the name of the
parameters defined in the first line and additional attributes such as type or
default value defined as nested elements.

.. code-block:: yaml

  parameters:
    <param name>:
      type: <string | number | json | comma_delimited_list | boolean>
      label: <human-readable name of the parameter>
      description: <description of the parameter>
      default: <default value for parameter>
      hidden: <true | false>
      constraints:
        <parameter constraints>
      immutable: <true | false>
      tags: <list of parameter categories>

param name
    The name of the parameter.

type
    The type of the parameter. Supported types
    are ``string``, ``number``, ``comma_delimited_list``, ``json`` and
    ``boolean``.
    This attribute is required.

label
    A human readable name for the parameter.
    This attribute is optional.

description
    A human readable description for the parameter.
    This attribute is optional.

default
    A default value for the parameter. This value is used if the user doesn't
    specify his own value during deployment.
    This attribute is optional.

hidden
    Defines whether the parameters should be hidden when a user requests
    information about a stack created from the template. This attribute can be
    used to hide passwords specified as parameters.

    This attribute is optional and defaults to ``false``.

constraints
    A list of constraints to apply. The constraints are validated by the
    Orchestration engine when a user deploys a stack. The stack creation fails
    if the parameter value doesn't comply to the constraints.
    This attribute is optional.

immutable
    Defines whether the parameter is updatable. Stack update fails, if this is
    set to ``true`` and the parameter value is changed.
    This attribute is optional and defaults to ``false``.

tags
    A list of strings to specify the category of a parameter. This value is
    used to categorize a parameter so that users can group the parameters.
    This attribute is optional.

The table below describes all currently supported types with examples:

+----------------------+-------------------------------+------------------+
| Type                 | Description                   | Examples         |
+======================+===============================+==================+
| string               | A literal string.             | "String param"   |
+----------------------+-------------------------------+------------------+
| number               | An integer or float.          | "2"; "0.2"       |
+----------------------+-------------------------------+------------------+
| comma_delimited_list | An array of literal strings   | ["one", "two"];  |
|                      | that are separated by commas. | "one, two";      |
|                      | The total number of strings   | Note: "one, two" |
|                      | should be one more than the   | returns          |
|                      | total number of commas.       | ["one", " two"]  |
+----------------------+-------------------------------+------------------+
| json                 | A JSON-formatted map or list. | {"key": "value"} |
+----------------------+-------------------------------+------------------+
| boolean              | Boolean type value, which can | "on"; "n"        |
|                      | be equal "t", "true", "on",   |                  |
|                      | "y", "yes", or "1" for true   |                  |
|                      | value and "f", "false",       |                  |
|                      | "off", "n", "no", or "0" for  |                  |
|                      | false value.                  |                  |
+----------------------+-------------------------------+------------------+

The following example shows a minimalistic definition of two parameters

.. code-block:: yaml

  parameters:
    user_name:
      type: string
      label: User Name
      description: User name to be configured for the application
    port_number:
      type: number
      label: Port Number
      description: Port number to be configured for the web server

.. note::
    The description and the label are optional, but defining these attributes
    is good practice to provide useful information about the role of the
    parameter to the user.

.. _hot_spec_parameters_constraints:

Parameter Constraints
---------------------

The ``constraints`` block of a parameter definition defines
additional validation constraints that apply to the value of the
parameter. The parameter values provided by a user are validated against the
constraints at instantiation time. The constraints are defined as a list with
the following syntax

.. code-block:: yaml

  constraints:
    - <constraint type>: <constraint definition>
      description: <constraint description>

constraint type
    Type of constraint to apply. The set of currently supported constraints is
    given below.

constraint definition
    The actual constraint, depending on the constraint type. The
    concrete syntax for each constraint type is given below.

description
    A description of the constraint. The text
    is presented to the user when the value he defines violates the constraint.
    If omitted, a default validation message is presented to the user.
    This attribute is optional.

The following example shows the definition of a string parameter with two
constraints. Note that while the descriptions for each constraint are optional,
it is good practice to provide concrete descriptions to present useful messages
to the user at deployment time.

.. code-block:: yaml

  parameters:
    user_name:
      type: string
      label: User Name
      description: User name to be configured for the application
      constraints:
        - length: { min: 6, max: 8 }
          description: User name must be between 6 and 8 characters
        - allowed_pattern: "[A-Z]+[a-zA-Z0-9]*"
          description: User name must start with an uppercase character

.. note::
   While the descriptions for each constraint are optional, it is good practice
   to provide concrete descriptions so useful messages can be presented to the
   user at deployment time.

The following sections list the supported types of parameter constraints, along
with the concrete syntax for each type.

length
++++++
The ``length`` constraint applies to parameters of type
``string``, ``comma_delimited_list`` and ``json``.

It defines a lower and upper limit for the length of the string value or
list/map collection.

The syntax of the ``length`` constraint is

.. code-block:: yaml

   length: { min: <lower limit>, max: <upper limit> }

It is possible to define a length constraint with only a lower limit or an
upper limit. However, at least one of ``min`` or ``max`` must be specified.

range
+++++
The ``range`` constraint applies to parameters of type ``number``.
It defines a lower and upper limit for the numeric value of the
parameter.

The syntax of the ``range`` constraint is

.. code-block:: yaml

   range: { min: <lower limit>, max: <upper limit> }

It is possible to define a range constraint with only a lower limit or an
upper limit. However, at least one of ``min`` or ``max`` must be specified.

The minimum and maximum boundaries are included in the range. For example, the
following range constraint would allow for all numeric values between 0 and
10

.. code-block:: yaml

   range: { min: 0, max: 10 }

modulo
++++++
The ``modulo`` constraint applies to parameters of type ``number``. The value
is valid if it is a multiple of ``step``, starting with ``offset``.

The syntax of the ``modulo`` constraint is

.. code-block:: yaml

   modulo: { step: <step>, offset: <offset> }

Both ``step`` and ``offset`` must be specified.

For example, the following modulo constraint would only allow for odd numbers

.. code-block:: yaml

   modulo: { step: 2, offset: 1 }

allowed_values
++++++++++++++
The ``allowed_values`` constraint applies to parameters of type
``string`` or ``number``. It specifies a set of possible values for a
parameter. At deployment time, the user-provided value for the
respective parameter must match one of the elements of the list.

The syntax of the ``allowed_values`` constraint is

.. code-block:: yaml

   allowed_values: [ <value>, <value>, ... ]

Alternatively, the following YAML list notation can be used

.. code-block:: yaml

   allowed_values:
     - <value>
     - <value>
     - ...

For example

.. code-block:: yaml

   parameters:
     instance_type:
       type: string
       label: Instance Type
       description: Instance type for compute instances
       constraints:
         - allowed_values:
           - m1.small
           - m1.medium
           - m1.large

allowed_pattern
+++++++++++++++
The ``allowed_pattern`` constraint applies to parameters of type
``string``. It specifies a regular expression against which a
user-provided parameter value must evaluate at deployment.

The syntax of the ``allowed_pattern`` constraint is

.. code-block:: yaml

   allowed_pattern: <regular expression>

For example

.. code-block:: yaml

   parameters:
     user_name:
       type: string
       label: User Name
       description: User name to be configured for the application
       constraints:
         - allowed_pattern: "[A-Z]+[a-zA-Z0-9]*"
           description: User name must start with an uppercase character


custom_constraint
+++++++++++++++++
The ``custom_constraint`` constraint adds an extra step of validation,
generally to check that the specified resource exists in the backend. Custom
constraints get implemented by plug-ins and can provide any kind of advanced
constraint validation logic.

The syntax of the ``custom_constraint`` constraint is

.. code-block:: yaml

   custom_constraint: <name>

The ``name`` attribute specifies the concrete type of custom constraint. It
corresponds to the name under which the respective validation plugin has been
registered in the Orchestration engine.

For example

.. code-block:: yaml

   parameters:
     key_name
       type: string
       description: SSH key pair
       constraints:
         - custom_constraint: nova.keypair

The following section lists the custom constraints and the plug-ins
that support them.

.. table_from_text:: ../../setup.cfg
   :header: Name,Plug-in
   :regex: (.*)=(.*)
   :start-after: heat.constraints =
   :end-before: heat.stack_lifecycle_plugins =
   :sort:

.. _hot_spec_pseudo_parameters:

Pseudo parameters
-----------------
In addition to parameters defined by a template author, Heat also
creates three parameters for every stack that allow referential access
to the stack's name, stack's identifier and project's
identifier. These parameters are named ``OS::stack_name`` for the
stack name, ``OS::stack_id`` for the stack identifier and
``OS::project_id`` for the project identifier. These values are
accessible via the `get_param`_ intrinsic function, just like
user-defined parameters.

.. note::

  ``OS::project_id`` is available since 2015.1 (Kilo).

.. _hot_spec_resources:


Resources section
~~~~~~~~~~~~~~~~~
The ``resources`` section defines actual resources that make up a stack
deployed from the HOT template (for instance compute instances, networks,
storage volumes).

Each resource is defined as a separate block in the ``resources`` section with
the following syntax

.. code-block:: yaml

   resources:
     <resource ID>:
       type: <resource type>
       properties:
         <property name>: <property value>
       metadata:
         <resource specific metadata>
       depends_on: <resource ID or list of ID>
       update_policy: <update policy>
       deletion_policy: <deletion policy>
       external_id: <external resource ID>
       condition: <condition name or expression or boolean>

resource ID
    A resource ID which must be unique within the ``resources`` section of the
    template.

type
    The resource type, such as ``OS::Nova::Server`` or ``OS::Neutron::Port``.
    This attribute is required.

properties
    A list of resource-specific properties. The property value can be provided
    in place, or via a function (see :ref:`hot_spec_intrinsic_functions`).
    This section is optional.

metadata
    Resource-specific metadata.
    This section is optional.

depends_on
    Dependencies of the resource on one or more resources of the template.
    See :ref:`hot_spec_resources_dependencies` for details.
    This attribute is optional.

update_policy
    Update policy for the resource, in the form of a nested dictionary. Whether
    update policies are supported and what the exact semantics are depends on
    the type of the current resource.
    This attribute is optional.

deletion_policy
    Deletion policy for the resource. The allowed deletion policies are
    ``Delete``, ``Retain``, and ``Snapshot``. Beginning with
    ``heat_template_version`` ``2016-10-14``, the lowercase equivalents
    ``delete``, ``retain``, and ``snapshot`` are also allowed.
    This attribute is optional; the default policy is to delete the physical
    resource when deleting a resource from the stack.

external_id
   Allows for specifying the resource_id for an existing external
   (to the stack) resource. External resources can not depend on other
   resources, but we allow other resources depend on external resource.
   This attribute is optional.
   Note: when this is specified, properties will not be used for building the
   resource and the resource is not managed by Heat. This is not possible to
   update that attribute. Also resource won't be deleted by heat when stack
   is deleted.

condition
    Condition for the resource. Which decides whether to create the
    resource or not.
    This attribute is optional.

    Note: Support ``condition`` for resource is added in the Newton version.

Depending on the type of resource, the resource block might include more
resource specific data.

All resource types that can be used in CFN templates can also be used in HOT
templates, adapted to the YAML structure as outlined above.

The following example demonstrates the definition of a simple compute resource
with some fixed property values

.. code-block:: yaml

   resources:
     my_instance:
       type: OS::Nova::Server
       properties:
         flavor: m1.small
         image: F18-x86_64-cfntools


.. _hot_spec_resources_dependencies:

Resource dependencies
---------------------
The ``depends_on`` attribute of a resource defines a dependency between this
resource and one or more other resources.

If a resource depends on just one other resource, the ID of the other resource
is specified as string of the ``depends_on`` attribute, as shown in the
following example

.. code-block:: yaml

   resources:
     server1:
       type: OS::Nova::Server
       depends_on: server2

     server2:
       type: OS::Nova::Server

If a resource depends on more than one other resources, the value of the
``depends_on`` attribute is specified as a list of resource IDs, as shown in
the following example

.. code-block:: yaml

   resources:
     server1:
       type: OS::Nova::Server
       depends_on: [ server2, server3 ]

     server2:
       type: OS::Nova::Server

     server3:
       type: OS::Nova::Server


.. _hot_spec_outputs:

Outputs section
~~~~~~~~~~~~~~~
The ``outputs`` section defines output parameters that should be available to
the user after a stack has been created. This would be, for example, parameters
such as IP addresses of deployed instances, or URLs of web applications
deployed as part of a stack.

Each output parameter is defined as a separate block within the outputs section
according to the following syntax

.. code-block:: yaml

   outputs:
     <parameter name>:
       description: <description>
       value: <parameter value>
       condition: <condition name or expression or boolean>

parameter name
    The output parameter name, which must be unique within the ``outputs``
    section of a template.

description
    A short description of the output parameter.
    This attribute is optional.

parameter value
    The value of the output parameter. This value is usually resolved by means
    of a function. See :ref:`hot_spec_intrinsic_functions` for details about
    the functions.
    This attribute is required.

condition
    To conditionally define an output value. None value will be shown if the
    condition is False.
    This attribute is optional.

    Note: Support ``condition`` for output is added in the Newton version.

The example below shows how the IP address of a compute resource can
be defined as an output parameter

.. code-block:: yaml

   outputs:
     instance_ip:
       description: IP address of the deployed compute instance
       value: { get_attr: [my_instance, first_address] }


Conditions section
~~~~~~~~~~~~~~~~~~
The ``conditions`` section defines one or more conditions which are evaluated
based on input parameter values provided when a user creates or updates a
stack. The condition can be associated with resources, resource properties and
outputs. For example, based on the result of a condition, user can
conditionally create resources, user can conditionally set different values
of properties, and user can conditionally give outputs of a stack.

The ``conditions`` section is defined with the following syntax

.. code-block:: yaml

   conditions:
     <condition name1>: {expression1}
     <condition name2>: {expression2}
     ...

condition name
    The condition name, which must be unique within the ``conditions``
    section of a template.

expression
    The expression which is expected to return True or False. Usually,
    the condition functions can be used as expression to define conditions::

      equals
      get_param
      not
      and
      or
      yaql

    Note: In condition functions, you can reference a value from an input
    parameter, but you cannot reference resource or its attribute. We support
    referencing other conditions (by condition name) in condition functions.
    We support 'yaql' as condition function in the Pike version.

An example of conditions section definition

.. code-block:: yaml

   conditions:
     cd1: True
     cd2:
       get_param: param1
     cd3:
       equals:
       - get_param: param2
       - yes
     cd4:
       not:
         equals:
         - get_param: param3
         - yes
     cd5:
       and:
       - equals:
         - get_param: env_type
         - prod
       - not:
           equals:
           - get_param: zone
           - beijing
     cd6:
       or:
       - equals:
         - get_param: zone
         - shanghai
       - equals:
         - get_param: zone
         - beijing
     cd7:
       not: cd4
     cd8:
       and:
       - cd1
       - cd2
     cd9:
       yaql:
         expression: $.data.services.contains('heat')
         data:
           services:
             get_param: ServiceNames
     cd10:
       contains:
       - 'neutron'
       - get_param: ServiceNames

The example below shows how to associate condition with resources

.. code-block:: yaml

   parameters:
     env_type:
       default: test
       type: string
   conditions:
     create_prod_res: {equals : [{get_param: env_type}, "prod"]}
   resources:
     volume:
       type: OS::Cinder::Volume
       condition: create_prod_res
       properties:
         size: 1

The 'create_prod_res' condition evaluates to true if the 'env_type'
parameter is equal to 'prod'. In the above sample template, the 'volume'
resource is associated with the 'create_prod_res' condition. Therefore,
the 'volume' resource is created only if the 'env_type' is equal to 'prod'.

The example below shows how to conditionally define an output

.. code-block:: yaml

   outputs:
     vol_size:
       value: {get_attr: [my_volume, size]}
       condition: create_prod_res

In the above sample template, the 'vol_size' output is associated with
the 'create_prod_res' condition. Therefore, the 'vol_size' output is
given corresponding value only if the 'env_type' is equal to 'prod',
otherwise the value of the output is None.


.. _hot_spec_intrinsic_functions:

Intrinsic functions
~~~~~~~~~~~~~~~~~~~
HOT provides a set of intrinsic functions that can be used inside templates
to perform specific tasks, such as getting the value of a resource attribute at
runtime. The following section describes the role and syntax of the intrinsic
functions.

Note: these functions can only be used within the "properties" section
of each resource or in the outputs section.


get_attr
--------
The ``get_attr`` function references an attribute of a
resource. The attribute value is resolved at runtime using the resource
instance created from the respective resource definition.

Path based attribute referencing using keys or indexes requires
``heat_template_version`` ``2014-10-16`` or higher.

The syntax of the ``get_attr`` function is

.. code-block:: yaml

  get_attr:
    - <resource name>
    - <attribute name>
    - <key/index 1> (optional)
    - <key/index 2> (optional)
    - ...

resource name
    The resource name for which the attribute needs to be resolved.

    The resource name must exist in the ``resources`` section of the template.

attribute name
    The attribute name to be resolved. If the attribute returns a complex data
    structure such as a list or a map, then subsequent keys or indexes can be
    specified. These additional parameters are used to navigate the data
    structure to return the desired value.

The following example demonstrates how to use the :code:`get_attr` function:

.. code-block:: yaml

    resources:
      my_instance:
        type: OS::Nova::Server
        # ...

    outputs:
      instance_ip:
        description: IP address of the deployed compute instance
        value: { get_attr: [my_instance, first_address] }
      instance_private_ip:
        description: Private IP address of the deployed compute instance
        value: { get_attr: [my_instance, networks, private, 0] }

In this example, if the ``networks`` attribute contained the following data::

   {"public": ["2001:0db8:0000:0000:0000:ff00:0042:8329", "1.2.3.4"],
    "private": ["10.0.0.1"]}

then the value of ``get_attr`` function would resolve to ``10.0.0.1``
(first item of the ``private`` entry in the ``networks`` map).

From ``heat_template_version``: '2015-10-15' <attribute_name> is optional and
if <attribute_name> is not specified, ``get_attr`` returns dict of all
attributes for the given resource excluding *show* attribute. In this case
syntax would be next:

.. code-block:: yaml

  get_attr:
    - <resource_name>

get_file
--------
The ``get_file`` function returns the content of a file into the template.
It is generally used as a file inclusion mechanism for files
containing scripts or configuration files.

The syntax of ``get_file`` function is

.. code-block:: yaml

   get_file: <content key>

The ``content key`` is used to look up the ``files`` dictionary that is
provided in the REST API call. The Orchestration client command
(``heat``) is ``get_file`` aware and populates the ``files``
dictionary with the actual content of fetched paths and URLs. The
Orchestration client command supports relative paths and transforms these
to the absolute URLs required by the Orchestration API.

.. note::
    The ``get_file`` argument must be a static path or URL and not rely on
    intrinsic functions like ``get_param``. the Orchestration client does not
    process intrinsic functions (they are only processed by the Orchestration
    engine).

The example below demonstrates the ``get_file`` function usage with both
relative and absolute URLs

.. code-block:: yaml

  resources:
    my_instance:
      type: OS::Nova::Server
      properties:
        # general properties ...
        user_data:
          get_file: my_instance_user_data.sh
    my_other_instance:
      type: OS::Nova::Server
      properties:
        # general properties ...
        user_data:
          get_file: http://example.com/my_other_instance_user_data.sh

The ``files`` dictionary generated by the Orchestration client during
instantiation of the stack would contain the following keys:

* :file:`file:///path/to/my_instance_user_data.sh`
* :file:`http://example.com/my_other_instance_user_data.sh`


get_param
---------
The ``get_param`` function references an input parameter of a template. It
resolves to the value provided for this input parameter at runtime.

The syntax of the ``get_param`` function is

.. code-block:: yaml

    get_param:
     - <parameter name>
     - <key/index 1> (optional)
     - <key/index 2> (optional)
     - ...

parameter name
    The parameter name to be resolved. If the parameters returns a complex data
    structure such as a list or a map, then subsequent keys or indexes can be
    specified. These additional parameters are used to navigate the data
    structure to return the desired value.

The following example demonstrates the use of the ``get_param`` function

.. code-block:: yaml

    parameters:
      instance_type:
        type: string
        label: Instance Type
        description: Instance type to be used.
      server_data:
        type: json

    resources:
      my_instance:
        type: OS::Nova::Server
        properties:
          flavor: { get_param: instance_type}
          metadata: { get_param: [ server_data, metadata ] }
          key_name: { get_param: [ server_data, keys, 0 ] }

In this example, if the ``instance_type`` and ``server_data`` parameters
contained the following data::

    {"instance_type": "m1.tiny",
    {"server_data": {"metadata": {"foo": "bar"},
                     "keys": ["a_key","other_key"]}}}

then the value of the property ``flavor`` would resolve to ``m1.tiny``,
``metadata`` would resolve to ``{"foo": "bar"}`` and ``key_name`` would resolve
to ``a_key``.


get_resource
------------
The ``get_resource`` function references another resource within the
same template. At runtime, it is resolved to reference the ID of the referenced
resource, which is resource type specific. For example, a reference to a
floating IP resource returns the respective IP address at runtime. The syntax
of the ``get_resource`` function is

.. code-block:: yaml

    get_resource: <resource ID>

The resource ID of the referenced resource is given as single parameter to the
``get_resource`` function.

For example

.. code-block:: yaml

   resources:
     instance_port:
       type: OS::Neutron::Port
       properties: ...

     instance:
       type: OS::Nova::Server
       properties:
         ...
         networks:
           port: { get_resource: instance_port }


list_join
---------
The ``list_join`` function joins a list of strings with the given delimiter.

The syntax of the ``list_join`` function is

.. code-block:: yaml

    list_join:
    - <delimiter>
    - <list to join>

For example

.. code-block:: yaml

   list_join: [', ', ['one', 'two', 'and three']]

This resolve to the string ``one, two, and three``.

From HOT version ``2015-10-15`` you may optionally pass additional lists, which
will be appended to the previous lists to join.

For example::

   list_join: [', ', ['one', 'two'], ['three', 'four']]

This resolve to the string ``one, two, three, four``.

From HOT version ``2015-10-15`` you may optionally also pass non-string list
items (e.g json/map/list parameters or attributes) and they will be serialized
as json before joining.


digest
------
The ``digest`` function allows for performing digest operations on a given
value. This function has been introduced in the Kilo release and is usable with
HOT versions later than ``2015-04-30``.

The syntax of the ``digest`` function is

.. code-block:: yaml

  digest:
    - <algorithm>
    - <value>

algorithm
    The digest algorithm. Valid algorithms are the ones
    provided natively by hashlib (md5, sha1, sha224, sha256, sha384,
    and sha512) or any one provided by OpenSSL.
value
    The value to digest. This function will resolve to the corresponding hash
    of the value.


For example

.. code-block:: yaml

  # from a user supplied parameter
  pwd_hash: { digest: ['sha512', { get_param: raw_password }] }

The value of the digest function would resolve to the corresponding hash of
the value of ``raw_password``.


repeat
------
The ``repeat`` function allows for dynamically transforming lists by iterating
over the contents of one or more source lists and replacing the list elements
into a template. The result of this function is a new list, where the elements
are set to the template, rendered for each list item.

The syntax of the ``repeat`` function is

.. code-block:: yaml

  repeat:
    template:
      <template>
    for_each:
      <var>: <list>

template
    The ``template`` argument defines the content generated for each iteration,
    with placeholders for the elements that need to be replaced at runtime.
    This argument can be of any supported type.
for_each
    The ``for_each`` argument is a dictionary that defines how to generate the
    repetitions of the template and perform substitutions. In this dictionary
    the keys are the placeholder names that will be replaced in the template,
    and the values are the lists to iterate on. On each iteration, the function
    will render the template by performing substitution with elements of the
    given lists. If a single key/value pair is given in this argument, the
    template will be rendered once for each element in the list. When more
    than one key/value pairs are given, the iterations will be performed on all
    the permutations of values between the given lists. The values in this
    dictionary can be given as functions such as ``get_attr`` or ``get_param``.

The following example shows how a security group resource can be defined to
include a list of ports given as a parameter

.. code-block:: yaml

    parameters:
      ports:
        type: comma_delimited_list
        label: ports
        default: "80,443,8080"

    resources:
      security_group:
        type: OS::Neutron::SecurityGroup
        properties:
          name: web_server_security_group
          rules:
            repeat:
              for_each:
                <%port%>: { get_param: ports }
              template:
                protocol: tcp
                port_range_min: <%port%>
                port_range_max: <%port%>

The following example demonstrates how the use of multiple lists enables the
security group to also include parameterized protocols

.. code-block:: yaml

    parameters:
      ports:
        type: comma_delimited_list
        label: ports
        default: "80,443,8080"
      protocols:
        type: comma_delimited_list
        label: protocols
        default: "tcp,udp"

    resources:
      security_group:
        type: OS::Neutron::SecurityGroup
        properties:
          name: web_server_security_group
          rules:
            repeat:
              for_each:
                <%port%>: { get_param: ports }
                <%protocol%>: { get_param: protocols }
              template:
                protocol: <%protocol%>
                port_range_min: <%port%>

Note how multiple entries in the ``for_each`` argument are equivalent to
nested for-loops in most programming languages.

From HOT version ``2016-10-14`` you may also pass a map as value for the
``for_each`` key, in which case the list of map keys will be used as value.

From HOT version ``2017-09-01`` (or pike) you may specify a argument
``permutations`` to decide whether to iterate nested the over all the
permutations of the elements in the given lists. If 'permutations' is not
specified, we set the default value to true to compatible with before behavior.
The args have to be lists instead of dicts if 'permutations' is False because
keys in a dict are unordered, and the list args all have to be of the
same length.

.. code-block:: yaml

    parameters:
      subnets:
        type: comma_delimited_list
        label: subnets
        default: "sub1, sub2"
      networks:
        type: comma_delimited_list
        label: networks
        default: "net1, net2"

    resources:
      my_server:
        type: OS::Nova:Server
        properties:
          networks:
            repeat:
              for_each:
                <%sub%>: { get_param: subnets }
                <%net%>: { get_param: networks }
              template:
                subnet: <%sub%>
                network: <%net%>
              permutations: false

After resolved, we will get the networks of server like:
[{subnet: sub1, network: net1}, {subnet: sub2, network: net2}]


resource_facade
---------------
The ``resource_facade`` function retrieves data in a parent
provider template.

A provider template provides a custom definition of a resource, called its
facade. For more information about custom templates, see :ref:`composition`.
The syntax of the ``resource_facade`` function is

.. code-block:: yaml

   resource_facade: <data type>

``data type`` can be one of ``metadata``, ``deletion_policy`` or
``update_policy``.


str_replace
-----------
The ``str_replace`` function dynamically constructs strings by
providing a template string with placeholders and a list of mappings to assign
values to those placeholders at runtime. The placeholders are replaced with
mapping values wherever a mapping key exactly matches a placeholder.

The syntax of the ``str_replace`` function is

.. code-block:: yaml

   str_replace:
     template: <template string>
     params: <parameter mappings>

template
    Defines the template string that contains placeholders which will be
    substituted at runtime.

params
    Provides parameter mappings in the form of dictionary. Each key refers to a
    placeholder used in the ``template`` attribute. From HOT version
    ``2015-10-15`` you may optionally pass non-string parameter values
    (e.g json/map/list parameters or attributes) and they will be serialized
    as json before replacing, prior heat/HOT versions require string values.


The following example shows a simple use of the ``str_replace`` function in the
outputs section of a template to build a URL for logging into a deployed
application

.. code-block:: yaml

    resources:
      my_instance:
        type: OS::Nova::Server
        # general metadata and properties ...

    outputs:
      Login_URL:
        description: The URL to log into the deployed application
        value:
          str_replace:
            template: http://host/MyApplication
            params:
              host: { get_attr: [ my_instance, first_address ] }

The following examples show the use of the ``str_replace``
function to build an instance initialization script

.. code-block:: yaml

    parameters:
      DBRootPassword:
        type: string
        label: Database Password
        description: Root password for MySQL
        hidden: true

    resources:
      my_instance:
        type: OS::Nova::Server
        properties:
          # general properties ...
          user_data:
            str_replace:
              template: |
                #!/bin/bash
                echo "Hello world"
                echo "Setting MySQL root password"
                mysqladmin -u root password $db_rootpassword
                # do more things ...
              params:
                $db_rootpassword: { get_param: DBRootPassword }

In the example above, one can imagine that MySQL is being configured on a
compute instance and the root password is going to be set based on a user
provided parameter. The script for doing this is provided as userdata to the
compute instance, leveraging the ``str_replace`` function.


str_replace_strict
------------------
``str_replace_strict`` behaves identically to the ``str_replace``
function, only an error is raised if any of the params are not present
in the template. This may help catch typo's or other issues sooner
rather than later when processing a template.


str_replace_vstrict
-------------------
``str_replace_vstrict`` behaves identically to the
``str_replace_strict`` function, only an error is raised if any of the
params are empty. This may help catch issues (i.e., prevent
resources from being created with bogus values) sooner rather than later if
it is known that all the params should be non-empty.


str_split
---------
The ``str_split`` function allows for splitting a string into a list by
providing an arbitrary delimiter, the opposite of ``list_join``.

The syntax of the ``str_split`` function is as follows:

.. code-block:: yaml

  str_split:
    - ','
    - string,to,split

Or:

.. code-block:: yaml

  str_split: [',', 'string,to,split']

The result of which is:

.. code-block:: yaml

  ['string', 'to', 'split']

Optionally, an index may be provided to select a specific entry from the
resulting list, similar to ``get_attr``/``get_param``:

.. code-block:: yaml

  str_split: [',', 'string,to,split', 0]

The result of which is:

.. code-block:: yaml

  'string'

Note: The index starts at zero, and any value outside the maximum (e.g the
length of the list minus one) will cause an error.

map_merge
---------
The ``map_merge`` function merges maps together. Values in the latter maps
override any values in earlier ones. Can be very useful when composing maps
that contain configuration data into a single consolidated map.

The syntax of the ``map_merge`` function is

.. code-block:: yaml

    map_merge:
    - <map 1>
    - <map 2>
    - ...

For example

.. code-block:: yaml

    map_merge: [{'k1': 'v1', 'k2': 'v2'}, {'k1': 'v2'}]

This resolves to a map containing ``{'k1': 'v2', 'k2': 'v2'}``.

Maps containing no items resolve to {}.

map_replace
-----------
The ``map_replace`` function does key/value replacements on an existing mapping.
An input mapping is processed by iterating over all keys/values and performing
a replacement if an exact match is found in either of the optional keys/values
mappings.

The syntax of the ``map_replace`` function is

.. code-block:: yaml

    map_replace:
    - <input map>
    - keys: <map of key replacements>
      values: <map of value replacements>

For example

.. code-block:: yaml

    map_replace:
    - k1: v1
      k2: v2
    - keys:
        k1: K1
      values:
        v2: V2

This resolves to a map containing ``{'K1': 'v1', 'k2': 'V2'}``.

The keys/values mappings are optional, either or both may be specified.

Note that an error is raised if a replacement defined in "keys" results
in a collision with an existing keys in the input or output map.

Also note that while unhashable values (e.g lists) in the input map are valid,
they will be ignored by the values replacement, because no key can be defined
in the values mapping to define their replacement.

yaql
----
The ``yaql`` evaluates yaql expression on a given data.

The syntax of the ``yaql`` function is

.. code-block:: yaml

    yaql:
      expression: <expression>
      data: <data>

For example

.. code-block:: yaml

    parameters:
      list_param:
        type: comma_delimited_list
        default: [1, 2, 3]

    outputs:
      max_elem:
        value:
          yaql:
            expression: $.data.list_param.select(int($)).max()
            data:
              list_param: {get_param: list_param}

max_elem output will be evaluated to 3

equals
------
The ``equals`` function compares whether two values are equal.

The syntax of the ``equals`` function is

.. code-block:: yaml

    equals: [value_1, value_2]

The value can be any type that you want to compare. This function
returns true if the two values are equal or false if they aren't.

For example

.. code-block:: yaml

    equals: [{get_param: env_type}, 'prod']

If param 'env_type' equals to 'prod', this function returns true,
otherwise returns false.

if
--
The ``if`` function returns the corresponding value based on the
evaluation of a condition.

The syntax of the ``if`` function is

.. code-block:: yaml

    if: [condition_name, value_if_true, value_if_false]

For example

.. code-block:: yaml

    conditions:
      create_prod_res: {equals : [{get_param: env_type}, "prod"]}

    resources:
      test_server:
        type: OS::Nova::Server
        properties:
          name: {if: ["create_prod_res", "s_prod", "s_test"]}

The 'name' property is set to 's_prod' if the condition
"create_prod_res" evaluates to true (if parameter 'env_type' is 'prod'),
and is set to 's_test' if the condition "create_prod_res" evaluates
to false (if parameter 'env_type' isn't 'prod').

Note: You define all conditions in the ``conditions`` section of a
template except for ``if`` conditions. You can use the ``if`` condition
in the property values in the ``resources`` section and ``outputs`` sections
of a template.

not
---
The ``not`` function acts as a NOT operator.

The syntax of the ``not`` function is

.. code-block:: yaml

    not: condition

Note: A condition can be an expression such as ``equals``, ``or`` and ``and``
that evaluates to true or false, can be a boolean, and can be other condition
name defined in ``conditions`` section of template.

Returns true for a condition that evaluates to false or
returns false for a condition that evaluates to true.

For example

.. code-block:: yaml

    not:
      equals:
      - get_param: env_type
      - prod

If param 'env_type' equals to 'prod', this function returns false,
otherwise returns true.

Another example with boolean value definition

.. code-block:: yaml

    not: True

This function returns false.

Another example reference other condition name

.. code-block:: yaml

    not: my_other_condition

This function returns false if my_other_condition evaluates to true,
otherwise returns true.

and
---
The ``and`` function acts as an AND operator to evaluate all the
specified conditions.

The syntax of the ``and`` function is

.. code-block:: yaml

    and: [{condition_1}, {condition_2}, ... {condition_n}]

Note: A condition can be an expression such as ``equals``, ``or`` and ``not``
that evaluates to true or false, can be a boolean, and can be other condition
names defined in ``conditions`` section of template.

Returns true if all the specified conditions evaluate to true, or returns
false if any one of the conditions evaluates to false.

For example

.. code-block:: yaml

    and:
    - equals:
      - get_param: env_type
      - prod
    - not:
        equals:
        - get_param: zone
        - beijing

If param 'env_type' equals to 'prod', and param 'zone' is not equal to
'beijing', this function returns true, otherwise returns false.

Another example reference with other conditions

.. code-block:: yaml

    and:
    - other_condition_1
    - other_condition_2

This function returns true if other_condition_1 and other_condition_2
evaluate to true both, otherwise returns false.

or
--
The ``or`` function acts as an OR operator to evaluate all the
specified conditions.

The syntax of the ``or`` function is

.. code-block:: yaml

    or: [{condition_1}, {condition_2}, ... {condition_n}]

Note: A condition can be an expression such as ``equals``, ``and`` and ``not``
that evaluates to true or false, can be a boolean, and can be other condition
names defined in ``conditions`` section of template.

Returns true if any one of the specified conditions evaluate to true,
or returns false if all of the conditions evaluates to false.

For example

.. code-block:: yaml

    or:
    - equals:
      - get_param: env_type
      - prod
    - not:
        equals:
        - get_param: zone
        - beijing

If param 'env_type' equals to 'prod', or the param 'zone' is not equal to
'beijing', this function returns true, otherwise returns false.

Another example reference other conditions

.. code-block:: yaml

    or:
    - other_condition_1
    - other_condition_2

This function returns true if any one of other_condition_1 or
other_condition_2 evaluate to true, otherwise returns false.

filter
------
The ``filter`` function removes values from lists.

The syntax of the ``filter`` function is

.. code-block:: yaml

    filter:
      - <values>
      - <list>

For example

.. code-block:: yaml

    parameters:
      list_param:
        type: comma_delimited_list
        default: [1, 2, 3]

    outputs:
      output_list:
        value:
          filter:
            - [3]
            - {get_param: list_param}

output_list will be evaluated to [1, 2].

make_url
--------

The ``make_url`` function builds URLs.

The syntax of the ``make_url`` function is

.. code-block:: yaml

    make_url:
      scheme: <protocol>
      username: <username>
      password: <password>
      host: <hostname or IP>
      port: <port>
      path: <path>
      query:
        <key1>: <value1>
        <key2>: <value2>
      fragment: <fragment>


All parameters are optional.

For example

.. code-block:: yaml

    outputs:
      server_url:
        value:
          make_url:
            scheme: http
            host: {get_attr: [server, networks, <network_name>, 0]}
            port: 8080
            path: /hello
            query:
              recipient: world
            fragment: greeting

``server_url`` will be evaluated to a URL in the form::

    http://[<server IP>]:8080/hello?recipient=world#greeting

list_concat
-----------

The ``list_concat`` function concatenates lists together.

The syntax of the ``list_concat`` function is

.. code-block:: yaml

    list_concat:
      - <list #1>
      - <list #2>
      - ...


For example

.. code-block:: yaml

    list_concat: [['v1', 'v2'], ['v3', 'v4']]

Will resolve to the list ``['v1', 'v2', 'v3', 'v4']``.

Null values will be ignored.

list_concat_unique
------------------

The ``list_concat_unique`` function behaves identically to the function
``list_concat``, only removes the repeating items of lists.

For example

.. code-block:: yaml

    list_concat_unique: [['v1', 'v2'], ['v2', 'v3']]

Will resolve to the list ``['v1', 'v2', 'v3']``.

contains
--------

The ``contains`` function checks whether the specific value is
in a sequence.

The syntax of the ``contains`` function is

.. code-block:: yaml

    contains: [<value>, <sequence>]

This function returns true if value is in sequence or false if it isn't.

For example

.. code-block:: yaml

    contains: ['v1', ['v1', 'v2', 'v3']]

Will resolve to boolean true.
