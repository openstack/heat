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
::

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

::

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

::

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

::

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
::

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

::

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
::

  { "Fn::Select" : [ "2", [ "apples", "grapes", "mangoes" ] ] }

Returns ``mangoes``.

For a map lookup:
::

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
::

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
::

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

::

  {'Fn::ResourceFacade': 'Metadata'}
  {'Fn::ResourceFacade': 'DeletionPolicy'}
  {'Fn::ResourceFacade': 'UpdatePolicy'}


Example
~~~~~~~
Here is a top level template ``top.yaml``

::

  resources:
    my_server:
      type: OS::Nova::Server
      metadata:
        key: value
        some: more stuff


Here is a resource template ``my_actual_server.yaml``
::

  resources:
    _actual_server_:
      type: OS::Nova::Server
      metadata: {'Fn::ResourceFacade': Metadata}

The environment file ``env.yaml``
::

  resource_registry:
    resources:
      my_server:
        "OS::Nova::Server": my_actual_server.yaml

To use it

::

  $ heat stack-create -f top.yaml -e env.yaml


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
::

  {'Fn::MemberListToMap': ['Name', 'Value', ['.member.0.Name=key',
                                             '.member.0.Value=door',
                                             '.member.1.Name=colour',
                                             '.member.1.Value=green']]}


Returns ``{'key': 'door', 'colour': 'green'}``.
