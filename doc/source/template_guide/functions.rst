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

===================================
CloudFormation Compatible Functions
===================================

There are a number of functions that you can use to help you write
CloudFormation compatible templates.  While most CloudFormation functions are
supported in HOT version '2013-05-23', *Fn::Select* is the only CloudFormation
function supported in HOT templates since version '2014-10-16' which is
introduced in Juno.

All of these functions (except *Ref*) start with *Fn::*.

---
Ref
---
Returns the value of the named parameter or resource.

Parameters
~~~~~~~~~~
name : String
    The name of the resource or parameter.

Usage
~~~~~

.. code-block:: yaml

  {Ref: my_server}

Returns the nova instance ID. For example, ``d8093de0-850f-4513-b202-7979de6c0d55``.

----------
Fn::Base64
----------
This is a placeholder for a function to convert an input string to Base64.
This function in Heat actually performs no conversion.  It is included for
the benefit of CFN templates that convert UserData to Base64.  Heat only
accepts UserData in plain text.

Parameters
~~~~~~~~~~
value : String
    The string to convert.

Usage
~~~~~

.. code-block:: yaml

  {"Fn::Base64": "convert this string please."}

Returns the original input string.

-------------
Fn::FindInMap
-------------
Returns the value corresponding to keys into a two-level map declared in the
Mappings section.

Parameters
~~~~~~~~~~
map_name : String
    The logical name of a mapping declared in the Mappings section that
    contains the keys and values.

top_level_key : String
    The top-level key name. It's value is a list of key-value pairs.

second_level_key : String
    The second-level key name, which is set to one of the keys from the list
    assigned to top_level_key.

Usage
~~~~~

.. code-block:: yaml

  Mapping:
    MyContacts:
      jone: {phone: 337, email: a@b.com}
      jim: {phone: 908, email: g@b.com}

  {"Fn::FindInMap": ["MyContacts", "jim", "phone" ] }

Returns ``908``.

----------
Fn::GetAtt
----------
Returns an attribute of a resource within the template.

Parameters
~~~~~~~~~~
resource : String
    The name of the resource.

attribute : String
    The name of the attribute.

Usage
~~~~~

.. code-block:: yaml

  {Fn::GetAtt: [my_server, PublicIp]}

Returns an IP address such as ``10.0.0.2``.

----------
Fn::GetAZs
----------
Returns the Availability Zones within the given region.

*Note: AZ's and regions are not fully implemented in Heat.*

Parameters
~~~~~~~~~~
region : String
    The name of the region.

Usage
~~~~~

.. code-block:: yaml

  {Fn::GetAZs: ""}

Returns the list provided by ``nova availability-zone-list``.

--------
Fn::Join
--------
Like python join, it joins a list of strings with the given delimiter.

Parameters
~~~~~~~~~~
delimiter : String
    The string to join the list with.

list : list
    The list to join.

Usage
~~~~~

.. code-block:: yaml

  {Fn::Join: [",", ["beer", "wine", "more beer"]]}

Returns ``beer, wine, more beer``.

----------
Fn::Select
----------
Select an item from a list.

*Heat extension: Select an item from a map*

Parameters
~~~~~~~~~~
selector : string or integer
    The number of item in the list or the name of the item in the map.

collection : map or list
    The collection to select the item from.

Usage
~~~~~

For a list lookup:

.. code-block:: yaml

  { "Fn::Select" : [ "2", [ "apples", "grapes", "mangoes" ] ] }

Returns ``mangoes``.

For a map lookup:

.. code-block:: yaml

  { "Fn::Select" : [ "red", {"red": "a", "flu": "b"} ] }

Returns ``a``.

---------
Fn::Split
---------
This is the reverse of Join. Convert a string into a list based on the
delimiter.

Parameters
~~~~~~~~~~
delimiter : string
    Matching string to split on.

string : String
    The string to split.

Usage
~~~~~

.. code-block:: yaml

  { "Fn::Split" : [ ",", "str1,str2,str3,str4"]}

Returns ``{["str1", "str2", "str3", "str4"]}``.

-----------
Fn::Replace
-----------
Find and replace one string with another.

Parameters
~~~~~~~~~~
substitutions : map
    A map of substitutions.
string: String
    The string to do the substitutions in.

Usage
~~~~~

.. code-block:: yaml

  {"Fn::Replace": [
   {'$var1': 'foo', '%var2%': 'bar'},
    '$var1 is %var2%'
  ]}

Returns ``"foo is bar"``.

------------------
Fn::ResourceFacade
------------------
When writing a Template Resource:
 - user writes a template that will fill in for a resource (the resource is the facade).
 - when they are writing their template they need to access the metadata from
   the facade.


Parameters
~~~~~~~~~~
attribute_name : String
    One of ``Metadata``, ``DeletionPolicy`` or ``UpdatePolicy``.

Usage
~~~~~

.. code-block:: yaml

  {'Fn::ResourceFacade': 'Metadata'}
  {'Fn::ResourceFacade': 'DeletionPolicy'}
  {'Fn::ResourceFacade': 'UpdatePolicy'}


Example
~~~~~~~
Here is a top level template ``top.yaml``

.. code-block:: yaml

  resources:
    my_server:
      type: OS::Nova::Server
      metadata:
        key: value
        some: more stuff


Here is a resource template ``my_actual_server.yaml``

.. code-block:: yaml

  resources:
    _actual_server_:
      type: OS::Nova::Server
      metadata: {'Fn::ResourceFacade': Metadata}

The environment file ``env.yaml``

.. code-block:: yaml

  resource_registry:
    resources:
      my_server:
        "OS::Nova::Server": my_actual_server.yaml

To use it

::

  $ openstack stack create -t top.yaml -e env.yaml mystack


What happened is the metadata in ``top.yaml`` (key: value, some: more
stuff) gets passed into the resource template via the `Fn::ResourceFacade`_
function.

-------------------
Fn::MemberListToMap
-------------------
Convert an AWS style member list into a map.

Parameters
~~~~~~~~~~
key name: string
    The name of the key (normally "Name" or "Key").

value name: string
    The name of the value (normally "Value").

list: A list of strings
    The string to convert.

Usage
~~~~~

.. code-block:: yaml

  {'Fn::MemberListToMap': ['Name', 'Value', ['.member.0.Name=key',
                                             '.member.0.Value=door',
                                             '.member.1.Name=colour',
                                             '.member.1.Value=green']]}


Returns ``{'key': 'door', 'colour': 'green'}``.

----------
Fn::Equals
----------
Compares whether two values are equal. And returns true if the
two values are equal or false if they aren't.

Parameters
~~~~~~~~~~
value1:
    A value of any type that you want to compare.

value2:
    A value of any type that you want to compare.

Usage
~~~~~

.. code-block:: yaml

  {'Fn::Equals': [{'Ref': 'env_type'}, 'prod']}


Returns true if the param 'env_type' equals to 'prod',
otherwise returns false.

------
Fn::If
------
Returns one value if the specified condition evaluates to true and
another value if the specified condition evaluates to false.

Parameters
~~~~~~~~~~
condition_name:
    A reference to a condition in the ``Conditions`` section.

value_if_true:
    A value to be returned if the specified condition evaluates
    to true.

value_if_false:
    A value to be returned if the specified condition evaluates
    to false.

Usage
~~~~~

.. code-block:: yaml

  {'Fn::If': ['create_prod', 'value_true', 'value_false']}


Returns 'value_true' if the condition 'create_prod' evaluates to true,
otherwise returns 'value_false'.

-------
Fn::Not
-------
Acts as a NOT operator.

The syntax of the ``Fn::Not`` function is

.. code-block:: yaml

  {'Fn::Not': [condition]}

Returns true for a condition that evaluates to false or returns false
for a condition that evaluates to true.

Parameters
~~~~~~~~~~
condition:
    A condition such as ``Fn::Equals`` that evaluates to true or false
    can be defined in this function, also we can set a boolean value
    as a condition.

Usage
~~~~~

.. code-block:: yaml

  {'Fn::Not': [{'Fn::Equals': [{'Ref': env_type'}, 'prod']}]}


Returns false if the param 'env_type' equals to 'prod',
otherwise returns true.

-------
Fn::And
-------
Acts as an AND operator to evaluate all the specified conditions.
Returns true if all the specified conditions evaluate to true, or returns
false if any one of the conditions evaluates to false.

Parameters
~~~~~~~~~~
condition:
    A condition such as Fn::Equals that evaluates to true or false.

Usage
~~~~~

.. code-block:: yaml

  {'Fn::And': [{'Fn::Equals': [{'Ref': env_type}, 'prod']},
               {'Fn::Not': [{'Fn::Equals': [{'Ref': zone}, 'beijing']}]}]

Returns true if the param 'env_type' equals to 'prod' and the param 'zone' is
not equal to 'beijing', otherwise returns false.

------
Fn::Or
------
Acts as an OR operator to evaluate all the specified conditions.
Returns true if any one of the specified conditions evaluate to true,
or returns false if all of the conditions evaluates to false.

Parameters
~~~~~~~~~~
condition:
    A condition such as Fn::Equals that evaluates to true or false.

Usage
~~~~~

.. code-block:: yaml

  {'Fn::Or': [{'Fn::Equals': [{'Ref': zone}, 'shanghai']},
              {'Fn::Equals': [{'Ref': zone}, 'beijing']}]}

Returns true if the param 'zone' equals to 'shanghai' or 'beijing',
otherwise returns false.
