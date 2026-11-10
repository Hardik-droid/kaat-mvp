"""Opt-in compatible chat API planning. Proposals never execute tools.

The deterministic controller works without this module's environment settings.
Only the typed/spoken request and small selected-video context leave this client;
files, microphone audio, history and saved credentials are never sent here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from memory import Memory
from tools.windows_apps import canonical_name, validate_url


# Each value is (required arguments, optional arguments). Approval, shell and
# arbitrary-code tools are deliberately absent. Even allowed steps are inert.
TOOLS = {
    'system.open_application': ({'application'}, set()),
    'system.open_website': ({'url'}, set()),
    'system.open_folder': ({'path'}, set()),
    'system.list_installed_apps': (set(), set()),
    'system.get_active_window': (set(), set()),
    'video.inspect': ({'source'}, set()),
    'video.detect_pauses': (set(), {'min_pause_seconds'}),
    'video.transcribe': (set(), set()),
    'video.detect_retakes': (set(), set()),
    'video.undo': (set(), set()),
    'video.export': ({'output'}, {'subtitles'}),
    'memory.save_preference': ({'key', 'value'}, set()),
    'memory.get_preferences': (set(), set()),
}


def is_configured():
    return bool(os.getenv('KAAT_PLANNER_URL', '').strip() or os.getenv('KAAT_PLANNER_MODEL', '').strip())


def _result(status, message, **extra):
    return {'intent': 'unknown' if status == 'unknown' else 'plan', 'target': 'proposed_workflow',
            'status': status, 'verified': False, 'message': message, 'proposal': [], **extra}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a configured credential to a redirect target.


def _endpoint(value):
    parsed = urlsplit(value)
    local = parsed.hostname in {'localhost', '127.0.0.1', '::1'}
    if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and local)) or not parsed.hostname:
        raise ValueError('Planner URL needs HTTPS, or HTTP on localhost.')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in value):
        raise ValueError('Planner URL must not contain credentials, query parameters, fragments or whitespace.')
    parsed.port  # Validate malformed/out-of-range ports before creating a request.
    return value


def _path_key(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid path in proposed plan.')
    path = Path(value)
    if not path.is_absolute() or value.startswith(('\\\\', '//')):
        raise ValueError('Planner paths must be explicit absolute local paths.')
    return os.path.normcase(os.path.abspath(value))


def _known_paths(text, context):
    paths = {}
    source = context.get('source')
    if source:
        paths[_path_key(source)] = source
    # Quoted paths avoid guessing where a filename containing spaces ends.
    supplied = re.findall(r'["\']([^"\']+)["\']', text)
    supplied += [p for p in context.get('explicit_paths', []) if isinstance(p, str) and p.casefold() in text.casefold()]
    for path in supplied:
        if Path(path).is_absolute():
            paths[_path_key(path)] = path
    return paths


def _validate_proposal(value, known_paths):
    if not isinstance(value, dict) or set(value) - {'steps', 'clarification'}:
        raise ValueError('Planner must return only steps and clarification.')
    clarification = value.get('clarification')
    if clarification is not None and (not isinstance(clarification, str) or len(clarification) > 800):
        raise ValueError('Invalid planner clarification.')
    if clarification:
        return _result('needs_clarification', clarification)
    steps = value.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValueError('Planner must propose between one and eight supported steps.')
    proposal = []
    for step in steps:
        if not isinstance(step, dict) or set(step) != {'tool', 'arguments'} or step.get('tool') not in TOOLS:
            raise ValueError('Planner proposed an unsupported tool or instruction.')
        tool, arguments = step['tool'], step['arguments']
        required, optional = TOOLS[tool]
        if not isinstance(arguments, dict) or not required <= arguments.keys() or arguments.keys() - required - optional:
            raise ValueError('Planner proposed unsupported or missing tool arguments.')
        arguments = dict(arguments)
        if 'application' in arguments:
            arguments['application'] = canonical_name(arguments['application'])
            if re.search(r'[;&|<>/\\`$]', arguments['application']):
                raise ValueError('Application proposals need a name, not a command line.')
        if 'url' in arguments:
            arguments['url'] = validate_url(arguments['url'])
        for key in ('source', 'output', 'path'):
            if key in arguments:
                path = arguments[key]
                if key == 'path' and path in {'downloads', 'desktop', 'documents', 'home'}:
                    continue
                if _path_key(path) not in known_paths:
                    raise ValueError('Planner invented a file path. Select a video or provide explicit quoted paths.')
                if key in {'source', 'path'} and not Path(path).exists():
                    raise ValueError('The proposed source or folder does not exist.')
                if key == 'output' and Path(path).exists():
                    raise ValueError('Choose a new output path; existing files cannot be overwritten.')
        if 'min_pause_seconds' in arguments:
            Memory.validate('pause_threshold', arguments['min_pause_seconds'])
        if 'subtitles' in arguments and not isinstance(arguments['subtitles'], bool):
            raise ValueError('Subtitle preference must be true or false.')
        if tool == 'memory.save_preference':
            Memory.validate(arguments['key'], arguments['value'])
        proposal.append({'tool': tool, 'arguments': arguments, 'requires_review': True})
    return _result('needs_review', 'Proposed steps only. Review them and run individual commands; no action was executed.', proposal=proposal)


def propose_plan(text, context=None):
    """Return an inert validated proposal, clarification, or truthful failure.

    context may contain source, pause_threshold, subtitles and explicit_paths.
    No automatic execution API is provided, including for approval or export.
    """
    if not is_configured():
        return _result('unknown', 'Optional planning is not configured. Deterministic commands remain available.')
    try:
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError('Planner request must contain 1–4000 characters.')
        context = context or {}
        endpoint = _endpoint(os.getenv('KAAT_PLANNER_URL', '').strip())
        model = os.getenv('KAAT_PLANNER_MODEL', '').strip()
        key = os.getenv('KAAT_PLANNER_KEY', '').strip()
        if not model or len(model) > 200:
            raise ValueError('Set KAAT_PLANNER_MODEL alongside KAAT_PLANNER_URL.')
        known_paths = _known_paths(text, context)
        if re.search(r'\b(?:yesterday|kal|last night|previous video|last video)\b|कल\s*(?:वाली|का)', text, re.I):
            return _result('needs_clarification', 'Select the exact video first or give its full quoted path. Date-based video search is not implemented; no file was chosen.')
        minimal_context = {k: context[k] for k in ('source', 'pause_threshold', 'subtitles') if k in context}
        minimal_context['explicit_paths'] = list(known_paths.values())
        catalog = {tool: {'required': sorted(required), 'optional': sorted(optional)} for tool, (required, optional) in TOOLS.items()}
        instruction = ('Propose a KAAT workflow; do not execute or claim anything completed. Return JSON only: '
                       '{"steps":[{"tool":"...","arguments":{}}],"clarification":null}. '
                       'For ambiguity or missing files/output path, return {"steps":[],"clarification":"question"}. '
                       'Only use supplied paths or known folder aliases downloads/desktop/documents/home. '
                       'Never invent timestamps, paths, approvals or search capabilities. Cut suggestions require manual review before export. '
                       'Allowed tools and arguments: ' + json.dumps(catalog))
        payload = {'model': model, 'messages': [{'role': 'system', 'content': instruction},
            {'role': 'user', 'content': json.dumps({'request': text, 'context': minimal_context}, ensure_ascii=False)}]}
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if key:
            headers['Authorization'] = 'Bearer ' + key
        request = Request(endpoint, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('Planner response exceeded the allowed size.')
        envelope = json.loads(raw)
        content = envelope['choices'][0]['message']['content']
        if not isinstance(content, str):
            raise ValueError('Planner did not return text containing a JSON proposal.')
        if key and key in content:
            raise ValueError('Planner returned sensitive content; response was discarded.')
        return _validate_proposal(json.loads(content), known_paths)
    except HTTPError as exc:
        return _result('failed', f'Optional planner HTTP {exc.code}. Check its endpoint, credentials and model. No action executed.')
    except (URLError, TimeoutError, OSError):
        return _result('failed', 'Optional planner connection failed or timed out. No action executed.')
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return _result('failed', 'Optional planner returned an invalid response. No action executed.')
    except ValueError as exc:
        return _result('failed', str(exc))
