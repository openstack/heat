.. -*- rst -*-

=========
Templates
=========




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


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - template_versions: template_versions
   - type: type
   - version: version



Response Example
----------------

.. literalinclude:: samples/resource-types-list-response.json
   :language: javascript






List template versions
======================

.. rest_method::  GET /v1/{tenant_id}/template_versions

Lists all available template versions.


Normal response codes: 200
Error response codes:404,500,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id




Response Example
----------------

.. literalinclude:: samples/template-versions-response.json
   :language: javascript








Validate template
=================

.. rest_method::  POST /v1/{tenant_id}/validate

Validates a template.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - environment: environment
   - template_url: template_url
   - template: template
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: samples/template-validate-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - ParameterGroups: ParameterGroups
   - Description: Description
   - Parameters: Parameters



Response Example
----------------

.. literalinclude:: samples/template-validate-response.json
   :language: javascript




Show resource template
======================

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







Get stack template
==================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/template

Gets a template for a stack.


Normal response codes: 200
Error response codes:404,500,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - outputs: outputs
   - heat_template_version: heat_template_version
   - description: description
   - parameters: parameters
   - resources: resources



Response Example
----------------

.. literalinclude:: samples/template-show-response.json
   :language: javascript








Show resource schema
====================

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
   - resource_type: resource_type



Response Example
----------------

.. literalinclude:: samples/resource-schema-response.json
   :language: javascript





