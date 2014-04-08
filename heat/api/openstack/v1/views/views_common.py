#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from six.moves.urllib import parse as urlparse


def get_collection_links(request, items):
    """Retrieve 'next' link, if applicable."""
    links = []
    try:
        limit = int(request.params.get("limit") or 0)
    except ValueError:
        limit = 0

    if limit > 0 and limit == len(items):
        last_item = items[-1]
        last_item_id = last_item["id"]
        links.append({
            "rel": "next",
            "href": _get_next_link(request, last_item_id)
        })
    return links


def _get_next_link(request, marker):
    """Return href string with proper limit and marker params."""
    params = request.params.copy()
    params['marker'] = marker

    return "%s?%s" % (request.path_url, urlparse.urlencode(params))
