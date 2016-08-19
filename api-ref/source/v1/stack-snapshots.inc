.. -*- rst -*-

===============
Stack Snapshots
===============

Snapshot a stack
================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots

Takes a snapshot of all resources in a stack. All snapshots are deleted when the stack is deleted.

Normal response codes: 200
Error response codes:

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

   - status: snapshot_status
   - name: snapshot_name
   - status_reason: status_reason
   - creation_time: creation_time
   - data: data
   - id: snapshot_id

Response Example
----------------

.. literalinclude:: samples/stack-snapshot-response.json
   :language: javascript


Show snapshot
=============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots/{snapshot_id}

Shows details for a snapshot.


Normal response codes: 200
Error response codes:

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

   - status: snapshot_status
   - name: snapshot_name
   - status_reason: status_reason
   - creation_time: creation_time
   - snapshot: snapshot
   - template: template
   - project_id: project_id
   - data: data
   - id: snapshot_id
   - resources: resources

Response Example
----------------

.. literalinclude:: samples/stack-show-snapshot-response.json
   :language: javascript

List snapshots
==============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots

Lists snapshots for a stack.

Normal response codes: 200
Error response codes:

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_name: stack_name_url
   - stack_id: stack_id_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: snapshot_status
   - name: snapshot_name
   - status_reason: status_reason
   - creation_time: creation_time
   - snapshots: snapshots
   - data: data
   - id: snapshot_id

Response Example
----------------

.. literalinclude:: samples/stack-snapshots-list-response.json
   :language: javascript


Delete snapshot
===============

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots/{snapshot_id}

Deletes a stack snapshot.

Error response codes:204,

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - snapshot_id: snapshot_id_url

Restore snapshot
================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots/{snapshot_id}/restore

Restores a stack snapshot.

You can restore only active stacks from a snapshot. You must
recreate deleted stacks.

Error response codes:202,

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_name: stack_name_url
   - stack_id: stack_id_url
   - snapshot_id: snapshot_id_url
