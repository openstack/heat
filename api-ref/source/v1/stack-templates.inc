.. -*- rst -*-

=========
Templates
=========

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


List template functions
=======================

.. rest_method::  GET /v1/{tenant_id}/template_versions/{template_version}/functions

Lists all available functions for a template version.


Normal response codes: 200
Error response codes:401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - template_version: template_version

Response Example
----------------

.. literalinclude:: samples/template-functions-list-response.json
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
   - ignore_errors: ignore_errors

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
