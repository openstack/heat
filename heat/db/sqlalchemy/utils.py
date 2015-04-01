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

# SQLAlchemy helper functions

import sqlalchemy


def clone_table(name, parent, meta, newcols=[], ignorecols=[], swapcols={},
                ignorecons=[]):
    """
    helper function that clones parent table schema onto
    new table.

    :param name: new table name
    :param parent: parent table to copy schema from
    :param newcols: names of new columns to be added
    :param ignorecols: names of columns to be ignored while cloning
    :param swapcols: alternative column schema
    :param ignorecons: names of constraints to be ignored

    :return: sqlalchemy.Table instance
    """

    cols = [c.copy() for c in parent.columns
            if c.name not in ignorecols
            if c.name not in swapcols]
    cols.extend(swapcols.values())
    cols.extend(newcols)
    new_table = sqlalchemy.Table(name, meta, *(cols))

    def _is_ignorable(cons):
        # consider constraints on columns only
        if hasattr(cons, 'columns'):
            for col in ignorecols:
                if col in cons.columns:
                    return True

        return False

    constraints = [c.copy() for c in parent.constraints
                   if c.name not in ignorecons
                   if not _is_ignorable(c)]

    for c in constraints:
        new_table.append_constraint(c)

    new_table.create()
    return new_table


def migrate_data(migrate_engine,
                 table,
                 new_table,
                 skip_columns=None):

    table_name = table.name

    list_of_rows = list(table.select().execute())

    colnames = [c.name for c in table.columns]

    for row in list_of_rows:
        values = dict(zip(colnames,
                          map(lambda colname: getattr(row, colname),
                              colnames)))
        if skip_columns is not None:
            for column in skip_columns:
                del values[column]

        migrate_engine.execute(new_table.insert(values))

    table.drop()

    new_table.rename(table_name)
