.. -*- rst -*-

==============
Resource Types
==============

List resource types
===================

.. rest_method::  GET /v1/{tenant_id}/resource_types

Lists all supported template resource types.


Normal response codes: 200
Error response codes:401,400,

Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - name: name
   - version: version
   - support_status: support_status
   - with_description: with_description

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - template_versions: template_versions
   - type: type
   - version: version
   - description: resource_description

Response Example
----------------

.. literalinclude:: samples/resource-types-list-response.json
   :language: javascript


Show resource type template
===========================

.. rest_method::  GET /v1/{tenant_id}/resource_types/{type_name}/template

Shows the template representation for a resource type.

The returned template contains a single resource type. Each
resource property is mapped to a template parameter and each
resource attribute is mapped to a template output.

You can use these templates as a starting place for creating
customized, template-based resources or as examples of using the
particular resource in another template.

Use the ``template_type`` query parameter to specify the resource
template type. Default type is ``cfn``. The ``hot`` template type
is supported. For example:

::

   /v1/{tenant_id}/resource_types/{type_name}/template?template_type=cfn


Normal response codes: 200
Error response codes:404,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - type_name: type_name

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - Outputs: Outputs
   - HeatTemplateFormatVersion: HeatTemplateFormatVersion
   - Resources: Resources
   - Parameters: Parameters

Response Example
----------------

.. literalinclude:: samples/resource-type-template-response.json
   :language: javascript


Show resource type schema
=========================

.. rest_method::  GET /v1/{tenant_id}/resource_types/{type_name}

Shows the interface schema for a resource type.

A schema describes the properties that can be set on the resource,
their types, constraints, descriptions, and default values.
Additionally, the response shows the resource attributes and their
descriptions.

Normal response codes: 200
Error response codes:401,400,

Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - type_name: type_name
   - with_description: with_description

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - description: description
   - required: required
   - update_allowed: update_allowed
   - support_status: support_status
   - attributes: attributes
   - type: type
   - properties: properties
   - description: resource_description
   - resource_type: resource_type

Response Example
----------------

.. literalinclude:: samples/resource-schema-response.json
   :language: javascript
