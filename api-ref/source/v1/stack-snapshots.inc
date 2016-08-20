.. -*- rst -*-

===============
Stack Snapshots
===============

Snapshot a stack
================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots

Takes a snapshot of all resources in a stack. All snapshots are deleted when
the stack is deleted.

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
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - name: snapshot_name

Request Example
---------------

.. literalinclude:: samples/stack-snapshot-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - creation_time: creation_time
   - data: snapshot_data
   - id: snapshot_id
   - name: snapshot_name
   - status: snapshot_status
   - status_reason: snapshot_status_reason

Response Example
----------------

.. literalinclude:: samples/stack-snapshot-response.json
   :language: javascript


List snapshots
==============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots

Lists snapshots for a stack.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 401
   - 404

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
   - snapshots: snapshots
   - creation_time: creation_time
   - data: snapshot_data
   - id: snapshot_id
   - name: snapshot_name
   - status: snapshot_status
   - status_reason: snapshot_status_reason

Response Example
----------------

.. literalinclude:: samples/stack-snapshots-list-response.json
   :language: javascript


Show snapshot
=============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots/{snapshot_id}

Shows details for a snapshot.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 401
   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - snapshot_id: snapshot_id_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - snapshot: snapshot
   - creation_time: creation_time
   - data: snapshot_data
   - id: snapshot_id
   - name: snapshot_name
   - status: snapshot_status
   - status_reason: snapshot_status_reason

Response Example
----------------

.. literalinclude:: samples/stack-snapshot-show-response.json
   :language: javascript


Restore snapshot
================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots/{snapshot_id}/restore

Restores a stack snapshot.

You can restore only active stacks from a snapshot. You must recreate deleted
stacks.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 202

.. rest_status_code:: error status.yaml

   - 401
   - 404

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - snapshot_id: snapshot_id_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - code: restore_code
   - message: restore_message
   - title: restore_title

Response Example
----------------

.. literalinclude:: samples/stack-snapshot-restore-response.json
   :language: javascript


Delete a snapshot
=================

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots/{snapshot_id}

Deletes a stack snapshot.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 204

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
   - snapshot_id: snapshot_id_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id

Response Example
----------------

The response to this API does not have a body.
