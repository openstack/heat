.. -*- rst -*-

=============
Stack actions
=============

Performs non-lifecycle operations on the stack. Specify the action
in the request body.


Suspend stack
=============

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions

Suspends a stack.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - suspend: suspend
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id

Request Example
---------------

.. literalinclude:: samples/stack-action-suspend-request.json
   :language: javascript





Response Example
----------------

.. literalinclude:: 
   :language: javascript




Resume stack
============

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions

Resumes a suspended stack.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - resume: resume
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id

Request Example
---------------

.. literalinclude:: samples/stack-action-resume-request.json
   :language: javascript





Response Example
----------------

.. literalinclude:: 
   :language: javascript




Cancel stack update
===================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions

Cancels a currently running update of a stack.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - cancel_update: cancel_update
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id

Request Example
---------------

.. literalinclude:: samples/stack-action-cancel-update-request.json
   :language: javascript





Response Example
----------------

.. literalinclude:: 
   :language: javascript




Check stack resources
=====================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/actions

Checks whether the resources are in expected states for a stack.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - check: check
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id

Request Example
---------------

.. literalinclude:: samples/stack-action-check-request.json
   :language: javascript





Response Example
----------------

.. literalinclude:: 
   :language: javascript



