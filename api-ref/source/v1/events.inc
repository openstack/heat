.. -*- rst -*-

======
Events
======

The orchestration service provides APIs to check the events occurred on a
stack or a specific resource in a stack.

List stack events
=================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/events

Lists events for a stack.

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
   - resource_action: resource_action_query
   - resource_status: resource_status_query
   - resource_name: resource_name_query
   - resource_type: resource_type_query
   - limit: limit
   - marker: marker
   - sort_keys: sort_keys
   - sort_dir: sort_dir
   - nested_depth: nested_depth

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - event_time: event_time
   - id: event_id
   - links: event_links
   - logical_resource_id: logical_resource_id
   - physical_resource_id: physical_resource_id
   - resource_name: resource_name
   - resource_status: resource_status
   - resource_status_reason: resource_status_reason

Response Example
----------------

.. literalinclude:: samples/events-list-response.json
   :language: javascript


Find stack events
=================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/events

Finds the canonical URL for the event list of a stack.

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
   - stack_name: stack_name_url

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

.. literalinclude:: samples/events-find-response.json
   :language: javascript


List resource events
====================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/events

Lists events for a stack resource.

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
   - resource_name: resource_name_url
   - resource_action: resource_action_query
   - resource_status: resource_status_query
   - resource_name: resource_name_query
   - resource_type: resource_type_query
   - limit: limit
   - marker: marker
   - sort_keys: sort_keys
   - sort_dir: sort_dir
   - nested_depth: nested_depth

Response Example
----------------

.. literalinclude:: samples/events-list-response.json
   :language: javascript


Show event details
==================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/events/{event_id}

Shows details for an event.

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
   - resource_name: resource_name_url
   - event_id: event_id_url

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - event: event
   - event_time: event_time
   - id: event_id
   - links: event_links
   - logical_resource_id: logical_resource_id
   - physical_resource_id: physical_resource_id
   - resource_name: resource_name
   - resource_properties: resource_properties
   - resource_status: resource_status
   - resource_status_reason: resource_status_reason
   - resource_type: resource_type

Response Example
----------------

.. literalinclude:: samples/event-show-response.json
   :language: javascript
