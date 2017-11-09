.. -*- rst -*-

=============
Stack actions
=============

Performs non-lifecycle operations on the stack. Specify the action in the
request body.

Suspend stack
=============

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions

Suspends a stack.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - suspend: suspend

Request Example
---------------

.. literalinclude:: samples/stack-action-suspend-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id

Response Example
----------------

This operation does not return a response body.


Resume stack
============

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions

Resumes a suspended stack.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - resume: resume

Request Example
---------------

.. literalinclude:: samples/stack-action-resume-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id

Response Example
----------------

This operation does not return a response body.


Cancel stack update
===================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions

Cancels a currently running update of a stack.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - cancel_update: cancel_update

Request Example
---------------

.. literalinclude:: samples/stack-action-cancel-update-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id

Response Example
----------------

This operation does not return a response body.


Cancel stack create/update without rollback
===========================================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions

Cancels a currently running create/update of a stack without rollback.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - cancel_without_rollback: cancel_without_rollback

Request Example
---------------

.. literalinclude:: samples/stack-action-cancel-without-rollback-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id

Response Example
----------------

This operation does not return a response body.


Check stack resources
=====================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions

Checks whether the resources are in expected states for a stack.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - check: check

Request Example
---------------

.. literalinclude:: samples/stack-action-check-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id

Response Example
----------------

This operation does not return a response body.
