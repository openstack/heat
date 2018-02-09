.. -*- rst -*-

=============
Stack Outputs
=============

List outputs
============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/outputs

Lists outputs for a stack.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_name: stack_name_url
   - stack_id: stack_id_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - outputs: stack_outputs
   - output_key: output_key
   - description: output_description

Response Example
----------------

.. literalinclude:: samples/stack-outputs-list-response.json
   :language: javascript


Show output
===========

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/outputs/{output_key}

Shows details for a stack output.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - output_key: output_key_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - output: output
   - output_key: output_key
   - output_value: output_value
   - description: output_description
   - output_error: output_error

Response Example
----------------

.. literalinclude:: samples/stack-output-show-response.json
   :language: javascript
