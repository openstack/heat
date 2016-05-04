.. -*- rst -*-

======
Stacks
======




Abandon stack
=============

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/abandon

Deletes a stack but leaves its resources intact, and returns data that describes the stack and its resources.

This method can be disabled from the server side. If it is
disabled, this call throws an exception.


Normal response codes: 200
Error response codes:404,500,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id




Response Example
----------------

.. literalinclude:: samples/stack-abandon-response.json
   :language: javascript








Show snapshot
=============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots/{snapshot_id}

Shows details for a snapshot.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id
   - snapshot_id: snapshot_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - name: name
   - status_reason: status_reason
   - creation_time: creation_time
   - snapshot: snapshot
   - template: template
   - project_id: project_id
   - data: data
   - id: id
   - resources: resources



Response Example
----------------

.. literalinclude:: samples/stack-show-snapshot-response.json
   :language: javascript




Delete snapshot
===============

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots/{snapshot_id}

Deletes a stack snapshot.

Error response codes:204,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id
   - snapshot_id: snapshot_id






Preview stack
=============

.. rest_method::  POST /v1/{tenant_id}/stacks/preview

Previews a stack.


Normal response codes: 200
Error response codes:500,409,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - files: files
   - stack_name: stack_name
   - template_url: template_url
   - template: template
   - parameters: parameters
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: samples/stack-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - parent: parent
   - disable_rollback: disable_rollback
   - description: description
   - links: links
   - stack_name: stack_name
   - timeout_mins: timeout_mins
   - creation_time: creation_time
   - capabilities: capabilities
   - notification_topics: notification_topics
   - updated_time: updated_time
   - stack_owner: stack_owner
   - stack: stack
   - parameters: parameters
   - id: id
   - resources: resources
   - template_description: template_description



Response Example
----------------

.. literalinclude:: samples/stack-preview-response.json
   :language: javascript








Restore snapshot
================

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots/{snapshot_id}/restore

Restores a stack snapshot.

You can restore only active stacks from a snapshot. You must
recreate deleted stacks.

Error response codes:202,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id
   - snapshot_id: snapshot_id






List outputs
============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/outputs

Lists outputs for a stack.


Normal response codes: 200
Error response codes:


Request
-------

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




Preview stack update
====================

.. rest_method::  PUT /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/preview

Previews an update for a stack.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - files: files
   - parameters: parameters
   - tags: tags
   - environment: environment
   - template_url: template_url
   - template: template
   - timeout_mins: timeout_mins
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id

Request Example
---------------

.. literalinclude:: samples/stack-update-request.json
   :language: javascript





Response Example
----------------

.. literalinclude:: samples/stack-update-preview-response.json
   :language: javascript




Find stack resources
====================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/resources

Finds the canonical URL for a resource list of a stack.

The canonical URL is returned for only non-deleted stacks. To fetch
the resource list for deleted stacks, use the following endpoint:

::

   /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources

Error response codes:302,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id






Show stack details
==================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

Shows details for a stack.


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

   - parent: parent
   - updated_time: updated_time
   - description: description
   - links: links
   - stack_status_reason: stack_status_reason
   - stack_name: stack_name
   - outputs: outputs
   - tags: tags
   - creation_time: creation_time
   - capabilities: capabilities
   - notification_topics: notification_topics
   - timeout_mins: timeout_mins
   - stack_owner: stack_owner
   - stack_status: stack_status
   - stack: stack
   - parameters: parameters
   - id: id
   - stack_user_project_id: stack_user_project_id
   - template_description: template_description



Response Example
----------------

.. literalinclude:: samples/stack-show-response.json
   :language: javascript








Update stack
============

.. rest_method::  PUT /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

Updates a stack.

Error response codes:404,202,500,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - files: files
   - disable_rollback: disable_rollback
   - parameters: parameters
   - tags: tags
   - environment: environment
   - template_url: template_url
   - template: template
   - timeout_mins: timeout_mins
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id

Request Example
---------------

.. literalinclude:: samples/stack-update-request.json
   :language: javascript











Delete stack
============

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

Deletes a stack and its snapshots.

Error response codes:500,404,204,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id










Show output
===========

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/outputs/{output_key}

Shows details for a stack output.


Normal response codes: 200
Error response codes:


Request
-------

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




List stack data
===============

.. rest_method::  GET /v1/{tenant_id}/stacks

Lists active stacks.


Normal response codes: 200
Error response codes:500,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - id: id
   - status: status
   - name: name
   - action: action
   - tenant: tenant
   - username: username
   - owner_id: owner_id
   - limit: limit
   - marker: marker
   - show_deleted: show_deleted
   - show_nested: show_nested
   - sort_keys: sort_keys
   - tags: tags
   - tags_any: tags_any
   - not_tags: not_tags
   - not_tags_any: not_tags_any
   - sort_dir: sort_dir
   - global_tenant: global_tenant
   - with_count: with_count


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - description: description
   - links: links
   - stack_status_reason: stack_status_reason
   - stack_name: stack_name
   - tags: tags
   - creation_time: creation_time
   - updated_time: updated_time
   - stack_status: stack_status
   - id: id



Response Example
----------------

.. literalinclude:: samples/stacks-list-response.json
   :language: javascript







Create stack
============

.. rest_method::  POST /v1/{tenant_id}/stacks

Creates a stack.

Error response codes:201,500,409,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - files: files
   - disable_rollback: disable_rollback
   - parameters: parameters
   - tags: tags
   - stack_name: stack_name
   - environment: environment
   - template_url: template_url
   - template: template
   - timeout_mins: timeout_mins
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: samples/stack-create-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - id: id
   - links: links
   - stack: stack









Adopt stack
===========

.. rest_method::  POST /v1/{tenant_id}/stacks

Creates a stack from existing resources.

Error response codes:201,500,409,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - files: files
   - disable_rollback: disable_rollback
   - parameters: parameters
   - stack_name: stack_name
   - adopt_stack_data: adopt_stack_data
   - environment: environment
   - timeout_mins: timeout_mins
   - tenant_id: tenant_id

Request Example
---------------

.. literalinclude:: samples/stack-adopt-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - id: id
   - links: links
   - stack: stack









Find stack
==========

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}

Finds the canonical URL for a stack.

Also works with verbs other than GET , so that you can perform PUT
and DELETE operations on a current stack. Set your client to follow
redirects. When redirecting, the request method should not change
as defined in RFC2626. However, in many clients the default
behavior is to change the method to GET when you receive a ``302``
response code because this behavior is ubiquitous in web browsers.

Error response codes:302,404,500,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id










Snapshot stack
==============

.. rest_method::  POST /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots

Takes a snapshot of all resources in a stack. All snapshots are deleted when the stack is deleted.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - name: name
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id

Request Example
---------------

.. literalinclude:: samples/stack-snapshot-request.json
   :language: javascript



Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - name: name
   - status_reason: status_reason
   - creation_time: creation_time
   - data: data
   - id: id



Response Example
----------------

.. literalinclude:: samples/stack-snapshot-response.json
   :language: javascript




List snapshots
==============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/snapshots

Lists snapshots for a stack.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - name: name
   - status_reason: status_reason
   - creation_time: creation_time
   - snapshots: snapshots
   - data: data
   - id: id



Response Example
----------------

.. literalinclude:: samples/stack-snapshots-list-response.json
   :language: javascript



