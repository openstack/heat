.. -*- rst -*-

=========
Templates
=========

List template versions
======================

.. rest_method::  GET /v1/{tenant_id}/template_versions

Lists all available template versions.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request_id: request_id
   - template_versions: template_versions
   - alias: template_version_alias
   - type: template_type
   - version: template_version


Response Example
----------------

.. literalinclude:: samples/template-versions-response.json
   :language: javascript


List template functions
=======================

.. rest_method::  GET /v1/{tenant_id}/template_versions/{template_version}/functions

Lists all available functions for a template version.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - template_version: template_version_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - template_functions: template_functions
   - description: function_description
   - functions: functions

Response Example
----------------

.. literalinclude:: samples/template-functions-list-response.json
   :language: javascript


Validate template
=================

.. rest_method::  POST /v1/{tenant_id}/validate

Validates a template.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - environment: environment
   - environment_files: environment_files
   - files: files
   - ignore_errors: ignore_errors
   - show_nested: show_nested
   - template: template
   - template_url: template_url

Request Example
---------------

.. literalinclude:: samples/template-validate-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - Description: Description
   - ParameterGroups: ParameterGroups
   - Parameters: Parameters
   - Environment: Environment

Response Example
----------------

.. literalinclude:: samples/template-validate-response.json
   :language: javascript
