.. -*- rst -*-

=============
Stack Outputs
=============

List outputs
============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/outputs

Lists outputs for a stack.


Normal response codes: 200
Error response codes:

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - output_value: output_value
   - output_error: output_error
   - description: description
   - output_key: output_key

Response Example
----------------

.. literalinclude:: samples/stack-outputs-list-response.json
   :language: javascript


Show output
===========

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/outputs/{output_key}

Shows details for a stack output.

Normal response codes: 200
Error response codes:

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id
   - output_key: output_key

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - output_value: output_value
   - output_error: output_error
   - description: description
   - output_key: output_key

Response Example
----------------

.. literalinclude:: samples/stack-show-output-response.json
   :language: javascript
