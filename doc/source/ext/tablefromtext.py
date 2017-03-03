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
# -*- coding: utf-8 -*-

import os
import re

from docutils import nodes
from docutils.parsers.rst import directives
from docutils.parsers.rst.directives.tables import Table


class TableFromText(Table):
    """Take input from a file and create a simple table.

    Example:

    .. table_from_text:: ../setup.cfg
    :header: Name,Plug-in
    :regex: (.*)=(.*)
    :start-after: heat.constraints =
    :end-before: heat.stack_lifecycle_plugins =
    :sort:

    file: input file relative to source directory
    header: comma separated list of column titles
    regex: regular expression to parse the source line into columns
    start-after: string to look for to start column data
    end-before: string to look for to end column data
    sort: flag for sorting column data
    """

    required_arguments = 1
    option_spec = {
        'header': directives.unchanged_required,
        'regex': directives.unchanged_required,
        'start-after': directives.unchanged_required,
        'end-before': directives.unchanged_required,
        'sort': directives.flag
    }

    def run(self):
        header = self.options.get('header').split(',')
        lines = self._get_lines()
        regex = self.options.get('regex')
        max_cols = len(header)

        table = nodes.table()
        tgroup = nodes.tgroup(max_cols)
        table += tgroup

        col_widths = self.get_column_widths(max_cols)
        if isinstance(col_widths, tuple):
            col_widths = col_widths[1]
        tgroup.extend(nodes.colspec(colwidth=col_width) for
                      col_width in col_widths)

        thead = nodes.thead()
        tgroup += thead
        thead += self.create_table_row(header)

        tbody = nodes.tbody()
        tgroup += tbody

        for row in lines:
            matched = re.search(regex, row)
            if matched:
                tbody += self.create_table_row(matched.groups())

        return [table]

    def create_table_row(self, row_cells):
        row = nodes.row()

        for cell in row_cells:
            entry = nodes.entry()
            row += entry
            entry += nodes.paragraph(text=cell.strip())

        return row

    def _get_lines(self):
        env = self.state.document.settings.env
        sourcefile = os.path.join(env.srcdir, self.arguments[0])
        startafter = self.options.get('start-after')
        endbefore = self.options.get('end-before')

        lines = [line.strip() for line in open(sourcefile)]

        if startafter is not None or endbefore is not None:
            includeline = not startafter
            result = []
            for line in lines:
                if not includeline and startafter and startafter in line:
                    includeline = True
                elif includeline and endbefore and endbefore in line:
                    includeline = False
                    break
                elif includeline:
                    result.append(line)
            lines = result

        if 'sort' in self.options:
            lines = sorted(lines)

        return lines


def setup(app):
    app.add_directive('table_from_text', TableFromText)
