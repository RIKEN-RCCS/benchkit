"""Read-only queries over one consistent derived-catalog snapshot."""

import json
from datetime import datetime

from utils.result_catalog import CatalogUnavailable
from utils.result_records import format_result_timestamp
from utils.result_file import UUID_PATTERN
from utils.table_pagination import normalize_per_page


class ResultQueryReader:
    def __init__(self, conn, sources):
        self.conn, self.sources = conn, sources

    def fiscal_years(self, selection=None):
        clauses, args = ['directory=?', 'timestamp IS NOT NULL'], [self.sources['results']]
        if selection:
            clauses.extend(('timestamp>=?', 'timestamp<?'))
            args.extend((selection['since'].isoformat(), selection['until'].isoformat()))
        return {row[0] for row in self.conn.execute(
            "SELECT DISTINCT CAST(substr(timestamp,1,4) AS INTEGER)-(substr(timestamp,6,2)<='03') "
            'FROM query_records WHERE '+' AND '.join(clauses), args)}

    def records(self, directory, *, prefix='', selection=None):
        from pathlib import Path
        root = str(Path(directory).resolve(strict=True))
        if root not in (self.sources.get('results'), self.sources.get('estimates')):
            raise CatalogUnavailable('Report source is not indexed')
        clauses, args = ['directory=?'], [root]
        if prefix:
            clauses.append('substr(filename,1,?)=?')
            args.extend((len(prefix), prefix))
        if selection:
            clauses.extend(('timestamp>=?', 'timestamp<?'))
            args.extend((selection['since'].isoformat(), selection['until'].isoformat()))
            for field, column in [('code', 'code'), ('system', 'selected_system')]:
                if selection[field]:
                    clauses.append(column+'=?')
                    args.append(selection[field])
        query = ('SELECT filename,timestamp,facts,evidence FROM query_records WHERE '
                 + ' AND '.join(clauses) + ' ORDER BY timestamp DESC,filename DESC')
        for row in self.conn.execute(query, args):
            timestamp = datetime.fromisoformat(row['timestamp']) if row['timestamp'] else None
            yield dict(filename=row['filename'], data=json.loads(row['facts']),
                       evidence=json.loads(row['evidence']), timestamp=timestamp,
                       sort_key=timestamp or datetime.min,
                       timestamp_label=format_result_timestamp(row['filename']))

    def result_page(self, *, public_only, authenticated, affiliations, page, per_page,
                    filter_system=None, filter_code=None, filter_exp=None):
        clauses, args = [], []
        if public_only or not authenticated:
            clauses.append('g.public=1')
        elif 'admin' not in affiliations:
            tags = sorted(set(affiliations))
            clause = 'g.public=1'
            if tags:
                clause += ' OR EXISTS(SELECT 1 FROM group_tags t WHERE t.group_id=g.id AND t.tag IN ('+','.join('?' for _ in tags)+'))'
                args.extend(tags)
            clauses.append('('+clause+')')
        for column, value in [('system', filter_system), ('code', filter_code), ('exp', filter_exp)]:
            if value is not None:
                clauses.append('g.'+column+'=?')
                args.append(value)
        tail = ' FROM result_entries e JOIN candidate_groups g ON g.id=e.group_id'
        if clauses:
            tail += ' WHERE '+' AND '.join(clauses)
        count_query = 'SELECT COALESCE(SUM(g.count),0) FROM candidate_groups g'
        if clauses:
            count_query += ' WHERE '+' AND '.join(clauses)
        total = self.conn.execute(count_query, args).fetchone()[0]
        per_page = normalize_per_page(per_page)
        pages = max(1, (total+per_page-1)//per_page)
        page = max(1, min(int(page), pages))
        names = [row[0] for row in self.conn.execute('SELECT e.filename'+tail+
                 ' ORDER BY e.filename DESC LIMIT ? OFFSET ?', [*args, per_page, (page-1)*per_page])]
        return names, dict(page=page, per_page=per_page, total=total, total_pages=pages)

    def archives(self, directory, result_uuid):
        from pathlib import Path
        if self.sources.get('artifacts') != str(Path(directory).resolve(strict=True)):
            raise CatalogUnavailable('Archive source is not indexed')
        if not UUID_PATTERN.fullmatch(result_uuid):
            # Legacy non-UUID identifiers retain substring matching, but only in SQLite.
            return [row[0] for row in self.conn.execute(
                'SELECT filename FROM artifact_entries WHERE instr(filename,?)>0 ORDER BY filename', (result_uuid,))]
        # UUID comparisons are data, not SQL LIKE patterns or filesystem globs.
        return [row[0] for row in self.conn.execute(
            'SELECT filename FROM artifact_uuids WHERE result_uuid=? ORDER BY filename', (result_uuid,))]
