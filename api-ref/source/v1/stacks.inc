.. -*- rst -*-

======
Stacks
======

Create stack
============

.. rest_method::  POST /v1/{tenant_id}/stacks

Creates a stack.

Error response codes:201,500,409,401,400,

Request Parameters
------------------

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


Preview stack
=============

.. rest_method::  POST /v1/{tenant_id}/stacks/preview

Previews a stack.

Normal response codes: 200
Error response codes:500,409,401,400,

Request Parameters
------------------

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


List stacks
===========

.. rest_method::  GET /v1/{tenant_id}/stacks

Lists active stacks.

Normal response codes: 200
Error response codes:500,401,400,

Request Parameters
------------------

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
   - deletion_time: deleted_at
   - stack_status: stack_status
   - stack_owner: owner_id
   - stack_user_project_id: stack_user_project_id
   - parent: parent
   - id: id

Response Example
----------------

.. literalinclude:: samples/stacks-list-response.json
   :language: javascript


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


Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id

Show stack details
==================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

Shows details for a stack.

Normal response codes: 200
Error response codes:404,500,401,400,

Request Parameters
------------------

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

Request Parameters
------------------

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


Preview stack update
====================

.. rest_method::  PUT /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/preview

Previews an update for a stack.

Normal response codes: 200
Error response codes:

Request Parameters
------------------

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


Delete stack
============

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

Deletes a stack and its snapshots.

Error response codes:500,404,204,401,400,


Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id


Abandon stack
=============

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/abandon

Deletes a stack but leaves its resources intact, and returns data that describes the stack and its resources.

This method can be disabled from the server side. If it is
disabled, this call throws an exception.


Normal response codes: 200
Error response codes:404,500,401,400,

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id

Response Example
----------------

.. literalinclude:: samples/stack-abandon-response.json
   :language: javascript


Adopt stack
===========

.. rest_method::  POST /v1/{tenant_id}/stacks

Creates a stack from existing resources.

Error response codes:201,500,409,401,400,

Request Parameters
------------------

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
