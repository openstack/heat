.. -*- rst -*-

==============
Resource Types
==============

List resource types
===================

.. rest_method::  GET /v1/{tenant_id}/resource_types

Lists all supported template resource types.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - name: type_name_query
   - support_status: support_status_query
   - version: type_version_query
   - with_description: with_description

Response Parameters
-------------------

Note that the format of the response from this API varies when different query
parameters are specified. The default response has the following format:

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - resource_types: resource_types_simple

When ``with_description`` is specified, the response has the following format:

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - resource_types: resource_types_advanced
   - resource_type: resource_type
   - description: resource_type_description

Response Example
----------------

The following is an example of the simple response:

.. literalinclude:: samples/resource-types-list-response.json
   :language: javascript

The following is an example of the response when ``with_description`` is
specified:

.. literalinclude:: samples/resource-types-list-advanced-response.json
   :language: javascript


Show resource type template
===========================

.. rest_method::  GET /v1/{tenant_id}/resource_types/{type_name}/template

Shows the template representation for a resource type.

The returned template contains a single resource type. Each resource property
is mapped to a template parameter and each resource attribute is mapped to a
template output.

You can use these templates as a starting place for creating customized,
template-based resources or as examples of using the particular resource in
another template.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - type_name: type_name
   - template_type: template_type_query

Response Parameters
-------------------

The format of the response varies when ``template_type`` is set to different
values. When it is set to ``cfn`` or omitted, the response has the following
format:

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - Description: Description
   - Outputs: Outputs
   - HeatTemplateFormatVersion: HeatTemplateFormatVersion
   - Parameters: Parameters
   - Resources: Resources

When the ``template_type`` is explicitly set to ``hot``, the response has the
following format:

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - heat_template_version: heat_template_version
   - description: template_description
   - outputs: template_outputs
   - parameters: template_parameters
   - resources: template_resources


Response Example
----------------

The following is a sample of the response when ``template_type`` is set to
``cfn`` or omitted:

.. literalinclude:: samples/resource-type-template-response.json
   :language: javascript

The following is a sample of the response when ``template_type`` is explicitly
set to ``hot``:

.. literalinclude:: samples/resource-type-template-hot-response.json
   :language: javascript


Show resource type schema
=========================

.. rest_method::  GET /v1/{tenant_id}/resource_types/{type_name}

Shows the interface schema for a resource type.

A schema describes the properties that can be set on the resource, their types,
constraints, descriptions, and default values.  Additionally, the response
shows the resource attributes and their descriptions.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - type_name: type_name

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - attributes: attributes
   - properties: properties
   - resource_type: resource_type
   - support_status: support_status

Response Example
----------------

.. literalinclude:: samples/resource-schema-response.json
   :language: javascript
