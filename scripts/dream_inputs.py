"""Logical-session increments over independently checkpointed transcript segments."""

import hashlib
import json
from pathlib import Path


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def segment_id(path):
    return fingerprint(str(path).encode())[:20]


def prefix_hash(path, cursor):
    if 'offset' not in cursor:
        return None
    with path.open('rb') as stream:
        remaining = cursor['offset']
        result = hashlib.sha256()
        while remaining:
            data = stream.read(min(remaining, 65536))
            if not data:
                return None
            result.update(data)
            remaining -= len(data)
    return result.hexdigest()


def legacy_path(wiki, source, cursor, paths):
    matches = set()
    for record_path in (wiki / '.dreaming/runs').glob('*/scan.json'):
        sealed_path = record_path.parent / 'sealed.json'
        if not sealed_path.exists():
            continue
        record = json.loads(record_path.read_text())
        sealed = json.loads(sealed_path.read_text())
        if source not in sealed['review']['processed']:
            continue
        for item in record['sources']:
            if item['source_id'] == source and item['next_cursor'] == cursor:
                candidate = Path(item['source_path']).expanduser().resolve()
                if candidate in paths:
                    matches.add(candidate)
    if len(matches) != 1:
        raise ValueError('Ambiguous legacy cursor: cannot identify its original segment; progress was not reset')
    return matches.pop()


def preceding(path, cursor, reader, normalize):
    if not cursor:
        return []
    if path.suffix.lower() == '.json':
        obj = json.loads(path.read_text())
        end = cursor.get('event_count', 0)
        entries = [(i + 1, e) for i, e in enumerate(obj['events'][:end])][-8:]
    elif path.suffix.lower() == '.jsonl':
        end = cursor.get('offset', 0)
        start = max(0, end - 65536)
        with path.open('rb') as stream:
            stream.seek(start)
            data = stream.read(end - start)
        lines = data.splitlines()
        if start and lines:
            lines = lines[1:]
        first_line = cursor.get('line', 0) - len(lines) + 1
        entries = []
        for i, line in enumerate(lines):
            try:
                entries.append((first_line + i, json.loads(line)))
            except ValueError:
                continue
    else:
        end = cursor.get('offset', 0)
        with path.open('rb') as stream:
            stream.seek(max(0, end - 8192))
            data = stream.read(min(end, 8192))
        return [{'kind': 'unstructured', 'position': max(0, end - 8192), 'text': data.decode('utf-8', errors='replace'), 'context_only': True}] if data else []
    result = []
    for position, obj in entries:
        event = normalize(obj, position)
        if event and event['kind'] == 'message':
            result.append({**event, 'context_only': True})
    return result[-4:]


def tool_boundary(events):
    calls, results, interruptions = {}, {}, []
    for index, event in enumerate(events):
        if event is None:
            continue
        if event['kind'] == 'tool_call':
            call = event.get('call_id')
            if not isinstance(call, str) or not call or call in calls:
                raise ValueError('Tool calls require distinct non-empty call_id values in an increment')
            calls[call] = index
        elif event['kind'] == 'tool_result':
            results[event.get('call_id')] = index
        elif event['kind'] == 'interruption':
            interruptions.append(index)
    cancelled = {}
    closed = {index: results[call] for call, index in calls.items() if call in results}
    for call, index in calls.items():
        if call in results:
            continue
        event = events[index]
        for terminal in interruptions:
            marker = events[terminal]
            same_turn = event.get('turn_id') and event.get('turn_id') == marker.get('turn_id')
            same_unscoped_stream = (not event.get('turn_id') and event.get('segment_id') == marker.get('segment_id') and terminal > index)
            if same_turn or same_unscoped_stream:
                cancelled[index] = terminal
                closed[index] = terminal
                break
    limit = min((index for index in calls.values() if index not in closed), default=len(events))
    while True:
        earlier = min((min(start, end) for start, end in closed.items() if min(start, end) < limit <= max(start, end)), default=limit)
        if earlier == limit:
            return limit, cancelled
        limit = earlier


def read_group(wiki, source, paths, cursor, since, reader, normalize, parse_time):
    paths = sorted(paths)
    segments = dict(cursor.get('segments', {}))
    if cursor and 'segments' not in cursor:
        original = legacy_path(wiki, source, cursor, paths)
        migrated = {**cursor, 'path': str(original)}
        hashed = prefix_hash(original, cursor)
        if 'offset' in cursor and not hashed:
            raise ValueError('Legacy segment cannot establish its processed prefix; progress was not reset')
        if hashed:
            migrated['prefix_hash'] = hashed
        segments[segment_id(original)] = migrated
    seen = dict(cursor.get('processed_ids', {}))
    encountered = dict(seen)
    donors = list(segments.values())
    chunks, rows, context = [], [], []
    raw_donors = []
    for path in paths:
        sid = segment_id(path)
        before = segments.get(sid, {})
        if path.suffix.lower() == '.jsonl':
            for donor in sorted(donors, key=lambda c: c.get('offset', 0), reverse=True):
                if donor.get('offset', 0) > before.get('offset', 0) and donor.get('prefix_hash') and prefix_hash(path, donor) == donor['prefix_hash']:
                    before = {k: v for k, v in donor.items() if k not in ('path', 'prefix_hash')}
                    break
        item = reader(path, before, None, defer_tools=False)
        chunk = {'segment_id': sid, 'path': path, 'before': before, 'item': item}
        chunks.append(chunk)
        copied_prefix = 0
        if path.suffix.lower() == '.jsonl':
            for donor_path, donor_end in raw_donors:
                end = min(item['next_cursor']['offset'], donor_end)
                if end and prefix_hash(path, {'offset': end}) == prefix_hash(donor_path, {'offset': end}):
                    copied_prefix = max(copied_prefix, end)
            raw_donors.append((path, item['next_cursor']['offset']))
        ends = dict(item['positions'])
        for event in preceding(path, before, reader, normalize):
            event.update(segment_id=sid, source_path=str(path), ref=f'{sid}:{event["position"]}')
            context.append(event)
        for event in item['events']:
            event = {**event, 'segment_id': sid, 'source_path': str(path), 'ref': f'{sid}:{event["position"]}'}
            identity = event.get('stable_id')
            value = {k: v for k, v in event.items() if k not in ('position', 'segment_id', 'source_path', 'ref')}
            hashed = fingerprint(json.dumps(value, sort_keys=True).encode())
            if identity and identity in encountered and encountered[identity] != hashed:
                raise ValueError('An event ID has conflicting content; this segment requires explicit reconciliation')
            rows.append({'event': event, 'chunk': chunk, 'identity': identity, 'hash': hashed, 'duplicate': bool((identity and identity in encountered) or (copied_prefix and ends.get(event['position'], copied_prefix + 1) <= copied_prefix))})
            if identity:
                encountered[identity] = hashed
    limit, cancelled = tool_boundary([None if row['duplicate'] else row['event'] for row in rows])
    for index, terminal in cancelled.items():
        rows[index]['event'].update(outcome='cancelled', cancelled_by=rows[terminal]['event']['ref'])
    retained = rows[:limit]
    events = []
    for row in retained:
        if row['duplicate']:
            continue
        event = row['event']
        identity = row['identity']
        if identity:
            if identity in seen:
                continue
            seen[identity] = row['hash']
        if since:
            timestamp = parse_time(event.get('timestamp'))
            if timestamp is None:
                raise ValueError('A relevant event has no timestamp; date filtering cannot be verified')
            if timestamp < since:
                continue
        events.append(event)
    deferred = limit < len(rows)
    for chunk in chunks:
        item, before = chunk['item'], chunk['before']
        blocked = [row['event']['position'] for row in rows[limit:] if row['chunk'] is chunk]
        next_cursor = dict(item['next_cursor'])
        if blocked:
            position = min(blocked)
            allowed = [(n, p) for n, p in item['positions'] if n < position]
            mode = 'event_count' if 'event_count' in next_cursor else 'offset'
            next_cursor = {mode: allowed[-1][1] if allowed else before.get(mode, 0)}
            if mode == 'offset':
                next_cursor['line'] = allowed[-1][0] if allowed else before.get('line', 0)
            turn = item['turns'].get(str(allowed[-1][0])) if allowed else before.get('turn_id')
            if turn:
                next_cursor['turn_id'] = turn
        next_cursor.update(path=str(chunk['path']))
        hashed = prefix_hash(chunk['path'], next_cursor)
        if hashed:
            next_cursor['prefix_hash'] = hashed
        segments[chunk['segment_id']] = next_cursor
    omitted = {}
    for event in events:
        for kind, count in event.get('omitted_content', {}).items():
            omitted[kind] = omitted.get(kind, 0) + count
    public_segments = [{'segment_id': c['segment_id'], 'path': str(c['path']), 'previous_cursor': {k: v for k, v in c['before'].items() if k in ('offset', 'line', 'event_count')}} for c in chunks]
    return {'session_id': next((c['item']['session_id'] for c in chunks if c['item']['session_id']), None),
            'source_id': source, 'source_path': str(paths[0]), 'segments': public_segments,
            'events': events, 'context': context, 'previous_cursor': {}, 'omitted_content': omitted,
            'next_cursor': {'segments': segments, 'processed_ids': seen},
            'deferred_tool_call': deferred,
            'deferred_tail': deferred or any(c['item']['deferred_tail'] for c in chunks),
            'coverage': sorted({c['item']['coverage'] for c in chunks}),
            'ordering': 'Per-segment order only. Compare source timestamps and scope; never infer recency from file order.'}
