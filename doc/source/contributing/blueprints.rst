Blueprints and Specs
====================

The Heat team uses the `heat-specs
<https://git.openstack.org/cgit/openstack/heat-specs>`_ repository for its
specification reviews. Detailed information can be found `here
<https://wiki.openstack.org/wiki/Blueprints#Heat>`_.

Please note that we use a template for spec submissions. Please use the
`template for the latest release
<https://git.openstack.org/cgit/openstack/heat-specs/tree/specs/templates>`_.
It is not required to fill out all sections in the template.

You have to create a Story in StoryBoard `heat storyboard
<https://storyboard.openstack.org/#!/project/989>`_. And create tasks that
fit with the plan to implement this spec (A task to link to a patch in gerrit).

Spec Notes
----------


There are occasions when a spec is approved and the code does not land in
the cycle it was targeted for. For these cases, the workflow to get the spec
into the next release is as below:

* Anyone can propose a patch to heat-specs which moves a spec from the
  previous release backlog into the new release directory.

The specs which are moved in this way can be fast-tracked into the next
release. Please note that it is required to re-propose the spec for the new
release and it'll be evaluated based on the resources available and cycle
priorities.

Heat Spec Lite
--------------

Lite specs are small feature requests tracked as StoryBoard stories, and tagged
with 'spec-lite' and 'priority-wishlist' tag. These allow for submission
and review of these feature requests before code is submitted.

These can be used for small features that don’t warrant a detailed spec to be
proposed, evaluated, and worked on. The team evaluates these requests as it
evaluates specs.

Once a `spec-lite` story has been approved/triaged as a
Request for Enhancement(RFE), it’ll be targeted for a release.

The workflow for the life of a spec-lite in StoryBoard is as follows:

* File a story with a small summary of what the requested change is and
  tag it as `spec-lite` and `priority-wishlist`.
* Create tasks that fit to your plan in story.
* The story is evaluated and marked with tag as `triaged` to announce
  approval or `Invalid` to request a full spec or it's not a valided task.
* The task is moved to `Progress` once the code is up and ready to
  review.
* The task is moved to `Merged` once the patch lands.
* The story is moved to `Merged` once all tasks merged.

The drivers team will discuss the following story reports in IRC meetings:

* `heat stories <https://storyboard.openstack.org/#!/project_group/82>`_
* `heat story filter <https://storyboard.openstack.org/#!/board/71>`_


Lite spec Submission Guidelines
-------------------------------

When a story is submitted, there is field that must be filled: ‘Description’.

The ‘Description’ section must be a description of what you would like
to see implemented in heat. The description should provide enough details for
a knowledgeable developer to understand what is the existing problem and
what’s the proposed solution.

Add `spec-lite` tag to the story.


Lite spec from existing stories
-------------------------------

If there's an already existing story that describes a small feature suitable for
a spec-lite, add a `spec-lite` tag to the story. There is no need to create a new
story. The comments and history of the existing story are important for its review.
