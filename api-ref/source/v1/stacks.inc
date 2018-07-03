.. -*- rst -*-

======
Stacks
======

Create stack
============

.. rest_method::  POST /v1/{tenant_id}/stacks

Creates a stack.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 201

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 409

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - disable_rollback: disable_rollback
   - environment: environment
   - environment_files: environment_files
   - files: files
   - files_container: files_container
   - parameters: parameters
   - stack_name: stack_name_request
   - tags: tags
   - template: template
   - template_url: template_url
   - timeout_mins: timeout_mins

Request Example
---------------

.. literalinclude:: samples/stack-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - location: location
   - X-Openstack-Request-Id: request_id
   - stack: stack
   - id: stack_id
   - links: links

Response Example
----------------

.. literalinclude:: samples/stack-create-response.json
   :language: javascript


Preview stack
=============

.. rest_method::  POST /v1/{tenant_id}/stacks/preview

Previews a stack.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 409
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - disable_rollback: disable_rollback
   - environment: environment
   - environment_files: environment_files
   - files_container: files_container
   - files: files
   - parameters: parameters
   - stack_name: stack_name_request
   - tags: tags
   - template: template
   - template_url: template_url
   - timeout_mins: timeout_mins

Request Example
---------------

.. literalinclude:: samples/stack-create-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - capabilities: capabilities
   - creation_time: creation_time
   - deletion_time: deletion_time
   - description: description
   - disable_rollback: disable_rollback
   - id: stack_id
   - links: links
   - notification_topics: notification_topics
   - outputs: stack_outputs
   - parameters: stack_parameters
   - parent: parent
   - resources: stack_resources
   - stack: stack
   - stack_name: stack_name
   - stack_owner: stack_owner
   - stack_user_project_id: stack_stack_user_project_id
   - tags: stack_tags
   - template_description: template_description
   - timeout_mins: stack_timeout_mins
   - updated_time: updated_time

Response Example
----------------

.. literalinclude:: samples/stack-preview-response.json
   :language: javascript


List stacks
===========

.. rest_method::  GET /v1/{tenant_id}/stacks

Lists active stacks.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - id: stack_id_query
   - status: stack_status_query
   - name: stack_name_query
   - action: stack_action_query
   - tenant: stack_tenant_query
   - username: stack_user_query
   - owner_id: owner_id_query
   - limit: limit
   - marker: marker
   - sort_keys: stack_sort_keys
   - sort_dir: sort_dir
   - show_deleted: show_deleted
   - show_nested: show_nested
   - tags: tags_query
   - tags_any: tags_any
   - not_tags: not_tags
   - not_tags_any: not_tags_any
   - global_tenant: global_tenant
   - with_count: with_count

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - stacks: stacks
   - creation_time: creation_time
   - deletion_time: deletion_time
   - description: description
   - links: links
   - parent: parent
   - stack_name: stack_name
   - stack_owner: stack_owner
   - stack_status: stack_status
   - stack_status_reason: stack_status_reason
   - tags: stack_tags
   - updated_time: updated_time
   - stack_user_project_id: stack_stack_user_project_id

Response Example
----------------

.. literalinclude:: samples/stacks-list-response.json
   :language: javascript


Find stack
==========

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_identity}

Finds the canonical URL for a stack.

Also works with verbs other than GET, so that you can perform PUT and DELETE
operations on a current stack. Set your client to follow redirects. When
redirecting, the request method should not change as defined in RFC2626.
However, in many clients the default behavior is to change the method to GET
when you receive a ``302`` response code because this behavior is ubiquitous
in web browsers.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 302

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_identity: stack_identity

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - location: location
   - X-Openstack-Request-Id: request_id
   - code: code
   - message: message
   - title: title

Response Example
----------------

.. literalinclude:: samples/stack-find-response.json
   :language: javascript


Show stack details
==================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

Shows details for a stack.

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
   - resolve_outputs: resolve_outputs

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - stack: stack
   - capabilities: capabilities
   - creation_time: creation_time
   - deletion_time: deletion_time
   - description: description
   - disable_rollback: stack_disable_rollback
   - id: stack_id
   - links: links
   - notification_topics: notification_topics
   - outputs: stack_outputs
   - parameters: stack_parameters
   - parent: parent
   - stack_name: stack_name
   - stack_owner: stack_owner
   - stack_status: stack_status
   - stack_status_reason: stack_status_reason
   - stack_user_project_id: stack_stack_user_project_id
   - tags: stack_tags
   - template_description: template_description
   - timeout_mins: stack_timeout_mins
   - updated_time: updated_time

Response Example
----------------

.. literalinclude:: samples/stack-show-response.json
   :language: javascript


Update stack
============

.. rest_method::  PUT /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

Updates a stack.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 202

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
   - clear_parameters: clear_parameters
   - disable_rollback: disable_rollback
   - environment: environment
   - environment_files: environment_files
   - files_container: files_container
   - existing: existing
   - files: files
   - parameters: parameters
   - tags: tags
   - template: template
   - template_url: template_url
   - timeout_mins: timeout_mins
   - converge: converge

Request Example
---------------

.. literalinclude:: samples/stack-update-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - code: code
   - message: message
   - title: title

Response Example
----------------

.. literalinclude:: samples/stack-update-response.json
   :language: javascript


Update stack (PATCH)
====================

.. rest_method::  PATCH /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

Updates a stack using the ``PATCH`` verb. The logic is identical to stack
update with a ``PUT`` verb except that the ``existing`` parameter is always
set to True.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 202

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
   - clear_parameters: clear_parameters
   - disable_rollback: disable_rollback
   - environment: environment
   - environment_files: environment_files
   - files_container: files_container
   - existing: existing_patch
   - files: files
   - parameters: parameters
   - tags: tags
   - template: template
   - template_url: template_url
   - timeout_mins: timeout_mins
   - converge: converge

Request Example
---------------

.. literalinclude:: samples/stack-update-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - code: code
   - message: message
   - title: title

Response Example
----------------

.. literalinclude:: samples/stack-update-response.json
   :language: javascript


Preview stack update
====================

.. rest_method::  PUT /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/preview

Previews an update for a stack.

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
   - clear_parameters: clear_parameters
   - disable_rollback: disable_rollback
   - environment: environment
   - environment_files: environment_files
   - files_container: files_container
   - existing: existing
   - files: files
   - parameters: parameters
   - show_nested: update_show_nested
   - tags: tags
   - template: template
   - template_url: template_url
   - timeout_mins: timeout_mins
   - converge: converge

Request Example
---------------

.. literalinclude:: samples/stack-update-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - resource_changes: resource_changes
   - added: preview_added
   - deleted: preview_deleted
   - replaced: preview_replaced
   - unchanged: preview_unchanged
   - updated: preview_updated

Response Example
----------------

.. literalinclude:: samples/stack-update-preview-response.json
   :language: javascript


Preview stack update (PATCH)
============================

.. rest_method::  PATCH /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/preview

Previews an update for a stack using the ``PATCH`` verb. The logic is the same
as that of stack update preview with a ``PUT`` verb except that the
``existing`` parameter is always set to True.

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
   - clear_parameters: clear_parameters
   - disable_rollback: disable_rollback
   - environment: environment
   - environment_files: environment_files
   - files_container: files_container
   - existing: existing_patch
   - files: files
   - parameters: parameters
   - show_nested: update_show_nested
   - tags: tags
   - template: template
   - template_url: template_url
   - timeout_mins: timeout_mins
   - converge: converge

Request Example
---------------

.. literalinclude:: samples/stack-update-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - resource_changes: resource_changes
   - added: preview_added
   - deleted: preview_deleted
   - replaced: preview_replaced
   - unchanged: preview_unchanged
   - updated: preview_updated

Response Example
----------------

.. literalinclude:: samples/stack-update-preview-response.json
   :language: javascript


Find stack for deletion
=======================

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_identity}

Find the canonical URL for a stack for deletion. This request returns a status
code of ``302`` pointing to the location where a DELETE request can be sent to
request a stack deletion.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 302

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_identity: stack_identity

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - location: location
   - code: code
   - message: message
   - title: title

Response Example
----------------

.. literalinclude:: samples/stack-find-delete-response.json
   :language: javascript


Delete stack
============

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}

Deletes a stack. If a stack has snapshots, those snapshots are deleted as well.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 204

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

Response Parameters
-------------------

This request does not return anything in the response body.


Abandon stack
=============

.. rest_method::  DELETE /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/abandon

Deletes a stack but leaves its resources intact, and returns data that
describes the stack and its resources.

This is a preview feature which has to be explicitly enabled by setting the
following option in the ``heat.conf`` file::

  [DEFAULT]
  enable_stack_abandon = True

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

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - action: stack_action
   - environment: stack_environment
   - files: stack_files
   - id: stack_id
   - stack_name: stack_name
   - project_id: project_id
   - resources: resources_abandon
   - stack_user_project_id: stack_stack_user_project_id
   - status: stack_status
   - tags: stack_tags
   - template: stack_template

Response Example
----------------

.. literalinclude:: samples/stack-abandon-response.json
   :language: javascript


Adopt stack
===========

.. rest_method::  POST /v1/{tenant_id}/stacks

Creates a stack from existing resources.

This is a preview feature which has to be explicitly enabled by setting the
following option in the ``heat.conf`` file::

  [DEFAULT]
  enable_stack_adopt = True

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 201

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 409
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - adopt_stack_data: adopt_stack_data
   - disable_rollback: disable_rollback
   - environment: environment
   - files: files
   - parameters: parameters
   - stack_name: stack_name
   - timeout_mins: timeout_mins

Request Example
---------------

.. literalinclude:: samples/stack-adopt-request.json
   :language: javascript

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - location: location
   - X-Openstack-Request-Id: request_id
   - stack: stack
   - id: stack_id
   - links: links

Response Example
----------------

.. literalinclude:: samples/stack-create-response.json
   :language: javascript


Export stack
============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/export

Gets the stack data in JSON format.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 400
   - 401
   - 404
   - 409
   - 500

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - stack_name: stack_name_url
   - stack_id: stack_id_url

Response Parameters
-------------------

The body of the response contains a map of file names and file contents.

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - action: action
   - environment: stack_environment
   - files: stack_files
   - id: stack_id
   - name: stack_name
   - project_id: project_id
   - resources: resources
   - stack_user_project_id: stack_stack_user_project_id
   - status: stack_status
   - tags: stack_tags
   - template: stack_template

Response Example
----------------

.. literalinclude:: samples/stack-export-response.json
   :language: javascript


Get stack template
==================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/template

Gets a template for a stack.

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

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - heat_template_version: heat_template_version
   - outputs: template_outputs
   - parameters: template_parameters
   - description: template_description
   - resources: template_resources

Response Example
----------------

.. literalinclude:: samples/template-show-response.json
   :language: javascript


Get stack environment
=====================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/environment

Gets the environment for a stack.

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

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - encrypted_param_names: encrypted_param_names
   - event_sinks: event_sinks
   - parameter_defaults: parameter_defaults
   - parameters: parameters
   - resource_registry: resource_registry

Response Example
----------------

.. literalinclude:: samples/stack-environment-show-response.json
   :language: javascript


Get stack files
===============

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/files

Gets the files associated with a stack.

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

Response Parameters
-------------------

The body of the response contains a map of file names and file contents.

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id

Response Example
----------------

.. literalinclude:: samples/stack-files-show-response.json
   :language: javascript
