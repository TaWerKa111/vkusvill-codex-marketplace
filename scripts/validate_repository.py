#!/usr/bin/env python3
"""Offline consistency checks, NOT a backend schema or live-import validation.

Uses Python's standard library only. Run from anywhere with --root PATH.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

PLUGIN = Path('plugins/vkusvill-cart')
REFERENCES = PLUGIN / 'skills/grocery-prices-browser/references'
ENUMS = {
    'availability': {'available', 'unavailable', 'unknown'},
    'priceType': {'regular', 'loyalty', 'personal', 'promotion', 'unknown'},
    'fulfillment': {'delivery', 'pickup', 'in_store', 'unknown'},
    'match': {'exact', 'substitute', 'similar', 'unknown'},
    'offerKind': {'offer', 'advertisement', 'catalog', 'unknown'},
}
# Contract invariants: changing an allowlist is a reviewed source change, not an
# arbitrary edit that can silently widen imports through a JSON fixture.
OFFICIAL_DOMAINS = {
    '5ka': ['5ka.ru', 'www.5ka.ru'],
    'perekrestok': ['perekrestok.ru', 'www.perekrestok.ru'],
    'chizhik': ['chizhik.club', 'www.chizhik.club'],
    'magnit': ['magnit.ru', 'dostavka.magnit.ru'],
    'lenta': ['lenta.com', 'www.lenta.com'],
    'vv': ['vkusvill.ru', 'www.vkusvill.ru'],
    'svetofor': ['svetofor-rls.ru'],
    'samokat': ['samokat.ru', 'www.samokat.ru'],
    'auchan': ['auchan.ru', 'www.auchan.ru'],
    'metro': ['online.metro-cc.ru', 'metro-cc.ru', 'www.metro-cc.ru'],
    'spar-middle-volga': ['myspar.ru', 'www.myspar.ru'],
    'smart': ['smart.swnn.ru'],
    'lavka': ['lavka.yandex.ru'],
    'okey': ['okeydostavka.ru', 'www.okeydostavka.ru', 'okmarket.ru', 'www.okmarket.ru'],
    'dixy': ['dixy.ru', 'www.dixy.ru'],
    'monetka': ['monetka.ru', 'www.monetka.ru'],
    'bahetle': ['dostavka.bahetle.com'],
}
WITHOUT_SKILL = {'lavka', 'okey', 'dixy', 'monetka', 'bahetle'}
STRICT_SEMVER = (r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
                 r'(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)'
                 r'(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?'
                 r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?')
STATUSES = {'not_found', 'unsupported_city', 'login_required', 'address_required',
            'captcha', 'browser_unavailable', 'catalog_only', 'error'}


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValidationError('non-finite JSON number: ' + value)


def check_finite(value):
    if isinstance(value, float):
        require(math.isfinite(value), 'non-finite JSON number')
    elif isinstance(value, dict):
        for item in value.values():
            check_finite(item)
    elif isinstance(value, list):
        for item in value:
            check_finite(item)


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'),
                           object_pairs_hook=unique_object,
                           parse_constant=reject_constant)
        check_finite(value)
        return value
    except (OSError, ValueError) as exc:
        raise ValidationError('{}: {}'.format(path, exc)) from exc


def local_path(root, base, value):
    require(isinstance(value, str) and value, 'empty local path')
    result = (base / value).resolve()
    require(result == root or root in result.parents,
            'path escapes repository: ' + value)
    require(result.exists(), 'missing local path: ' + str(result))
    return result


def safe_url(value, hosts=None):
    require(isinstance(value, str) and not re.search(r'[\s\\\x00-\x1f]', value),
            'invalid URL')
    try:
        parsed = urlsplit(value)
        require(parsed.scheme == 'https' and parsed.hostname,
                'URL must use HTTPS')
        require(parsed.username is None and parsed.password is None,
                'URL credentials forbidden')
        require(parsed.port in (None, 443), 'nonstandard URL port')
        if hosts is not None:
            require(parsed.hostname in hosts, 'unapproved URL domain: ' + parsed.hostname)
    except ValidationError:
        raise
    except ValueError as exc:
        raise ValidationError('invalid URL: ' + value) from exc
    return parsed


def validate_manifests(root):
    root = Path(root).resolve()
    base = root / PLUGIN
    public = read_json(base / 'plugin.json')
    codex = read_json(base / '.codex-plugin/plugin.json')
    for field in ('name', 'version'):
        require(public[field] == codex[field], 'manifest mismatch: ' + field)
    require(isinstance(public['version'], str) and re.fullmatch(STRICT_SEMVER, public['version']),
            'invalid plugin version')
    require(public['name'] == 'vkusvill-cart', 'plugin identity changed')
    require(public.get('$schema') == 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',
            'plugin schema changed')
    for interface in (public['extensions']['com.openai']['interface'], codex['interface']):
        require(isinstance(interface['shortDescription'], str) and
                len(interface['shortDescription']) <= 30, 'shortDescription exceeds 30 characters')
        for field in ('logo', 'composerIcon'):
            local_path(root, base, interface[field])
    require(public['extensions']['com.openai']['interface'] == codex['interface'],
            'manifest interface mismatch')
    require(public['description'] == codex['description'], 'manifest description mismatch')
    require(isinstance(codex['interface']['defaultPrompt'], str) and
            codex['interface']['defaultPrompt'].strip(), 'defaultPrompt must remain a nonblank string')
    skills = local_path(root, base, codex['skills'])
    require(skills.is_dir(), 'skills declaration must point to directory')
    for directory in skills.iterdir():
        if directory.is_dir():
            require((directory / 'SKILL.md').is_file(), 'missing declared SKILL.md: ' + str(directory))
            body = (directory / 'SKILL.md').read_text(encoding='utf-8')
            frontmatter = re.match(r'^---\n(.*?)\n---(?:\n|$)', body, re.S)
            require(frontmatter is not None, 'missing skill frontmatter: ' + str(directory))
            name = re.search(r'^name:\s*(.+?)\s*$', frontmatter.group(1), re.M)
            require(name is not None and name.group(1).strip(chr(39) + chr(34)) == directory.name,
                    'skill frontmatter name mismatch: ' + str(directory))
            require(re.search(r'^description:\s*\S', frontmatter.group(1), re.M),
                    'missing skill description: ' + str(directory))
    legacy_path = local_path(root, base, codex['mcpServers'])
    modern_file = read_json(base / 'mcp.json')
    require(modern_file.get('$schema') == 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
            'MCP schema changed')
    modern = modern_file['mcpServers']
    legacy = read_json(legacy_path)['mcpServers']
    require(modern.keys() == legacy.keys(), 'MCP server IDs mismatch')
    require(bool(modern), 'no MCP servers')
    for name, server in modern.items():
        require(server['url'] == legacy[name]['url'], 'MCP endpoint mismatch')
        safe_url(server['url'])
        require(server['url'] == 'https://vkusvill-cart-review.gpilikin.chatgpt.site/api/mcp',
                'MCP endpoint changed')
        require(server['type'] == 'streamable-http' and legacy[name]['type'] == 'http',
                'unexpected MCP transport mapping')
    marketplace = read_json(root / '.agents/plugins/marketplace.json')
    require(marketplace['name'] == 'vkusvill-cloud', 'marketplace identity changed')
    entries = [p for p in marketplace['plugins'] if p['name'] == public['name']]
    require(len(entries) == 1, 'plugin ID missing or duplicated in marketplace')
    require(entries[0].get('policy') == {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'},
            'marketplace policy changed')
    require(local_path(root, root, entries[0]['source']['path']) == base,
            'marketplace plugin path mismatch')


def validate_markdown(root):
    """Check local inline and reference-style link targets (not remote URLs/anchors)."""
    for path in root.rglob('*.md'):
        if '.git' in path.parts:
            continue
        body = re.sub(r'```.*?```|~~~.*?~~~', '', path.read_text(encoding='utf-8'), flags=re.S)
        targets = re.findall(r'!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)', body)
        targets += re.findall(r'^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)', body, re.M)
        for target in targets:
            target = target.strip('<>')
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            try:
                local_path(root, path.parent, unquote(parsed.path))
            except ValidationError as exc:
                raise ValidationError('{}: {}'.format(path.relative_to(root), exc)) from exc


def validate_registry(root):
    root = Path(root).resolve()
    registry = read_json(root / REFERENCES / 'stores.json')
    require(registry['schemaVersion'] == 2, 'unknown registry schemaVersion')
    require(set(registry) == {'schemaVersion', 'documentedPanelStoreCount', 'evidence', 'stores'},
            'unexpected registry field')
    stores = registry['stores']
    require(isinstance(stores, list) and stores, 'empty store registry')
    by_id, seen_skills = {}, set()
    for store in stores:
        sid = store['id']
        require(isinstance(sid, str) and re.fullmatch(r'[a-z0-9-]+', sid), 'invalid store ID')
        require(sid not in by_id, 'duplicate store ID: ' + sid)
        by_id[sid] = store
        nonempty(store.get('name'), 'store name')
        domains = store['officialDomains']
        require(isinstance(domains, list) and domains and len(set(domains)) == len(domains),
                'empty/duplicate official domains: ' + sid)
        safe_url(store['url'], domains)
        if store['skill'] is not None:
            skill = local_path(root, root / REFERENCES, store['skill'])
            require(skill.name == 'SKILL.md' and skill not in seen_skills, 'duplicate/invalid store skill')
            seen_skills.add(skill)
            body = skill.read_text(encoding='utf-8')
            require('Идентификатор в панели и MCP: `{}`'.format(sid) in body,
                    'registry/skill ID mismatch: ' + sid)
            primary = re.search(r'Стартовая витрина:.*?\]\((https://[^)]+)\)', body)
            require(primary is not None, 'missing store primary URL')
            safe_url(primary.group(1), domains)
            require('(../grocery-prices-browser/references/shopping-plan.md)' in body,
                    'missing shopping-plan link: ' + sid)
        require(sid in OFFICIAL_DOMAINS, 'unknown stable store ID: ' + sid)
        require(domains == OFFICIAL_DOMAINS[sid], 'official domain drift: ' + sid)
        require((store['skill'] is None) == (sid in WITHOUT_SKILL), 'nullable skill mismatch: ' + sid)
        caps = store['capabilities']
        require(set(caps) == {'manualLists', 'browserWorkflow', 'browserObservationImport',
                             'connectedCatalog', 'realCartLink', 'verifiedTransfer'},
                'unexpected capability field')
        for key in ('manualLists', 'browserWorkflow', 'browserObservationImport', 'realCartLink', 'verifiedTransfer'):
            require(type(caps[key]) is bool, 'invalid capability: ' + key)
        require(caps['manualLists'] is True, 'manual list capability mismatch')
        require(caps['browserWorkflow'] == (sid not in WITHOUT_SKILL), 'browser workflow capability mismatch')
        require(caps['browserObservationImport'] == (sid != 'bahetle'), 'browser import capability mismatch')
        require(caps['realCartLink'] == (sid == 'vv') and caps['verifiedTransfer'] == (sid == 'vv'),
                'cart capability mismatch')
        expected_catalog = {'vv': 'public_catalog', 'bahetle': 'location_scoped_catalog'}.get(sid, 'not_documented')
        require(caps['connectedCatalog'] == expected_catalog, 'catalog capability mismatch')
    require(set(by_id) == set(OFFICIAL_DOMAINS), 'stable store ID coverage mismatch')
    require(registry['documentedPanelStoreCount'] == len(stores) == 17, 'panel store count mismatch')
    declared_skills = set((root / PLUGIN / 'skills').glob('*/SKILL.md'))
    declared_skills.discard(root / PLUGIN / 'skills/grocery-prices-browser/SKILL.md')
    require(seen_skills == declared_skills and len(seen_skills) == 12,
            'registry does not cover every store skill')
    for key in ('identityAndDomains', 'browserHistory', 'panelAndConnectedCatalogs'):
        local_path(root, root / REFERENCES, registry['evidence'][key])
    return by_id


def nonempty(value, label):
    require(isinstance(value, str) and bool(value.strip()), 'missing text: ' + label)


def timestamp(value):
    nonempty(value, 'checkedAt')
    require(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)', value),
            'checkedAt must be UTC ISO 8601')
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValidationError('invalid checkedAt') from exc


def positive(value, label):
    require(type(value) in (int, float) and value > 0 and
            (not isinstance(value, float) or math.isfinite(value)),
            label + ' must be a finite positive number')


def validate_payload(payload, stores):
    """Validate repository example conventions from observations.md, offline only."""
    require(isinstance(payload, dict), 'payload must be object')
    require(set(payload) <= {'q', 'city', 'products', 'checks', 'correlation'}, 'undocumented payload field')
    if 'correlation' in payload:
        validate_correlation(payload['correlation'])
    nonempty(payload.get('q'), 'q')
    require(1 <= utf16_length(payload['q'].strip()) <= 200, 'q length must be 1–200')
    nonempty(payload.get('city'), 'city')
    for key in ('products', 'checks'):
        require(isinstance(payload.get(key), list) and len(payload[key]) <= 40,
                key + ' must be array of at most 40')
    require(payload['products'] or payload['checks'], 'empty import payload')
    product_contexts, check_contexts = set(), set()
    for key in ('products', 'checks'):
        for row in payload[key]:
            require(isinstance(row, dict), 'import row must be object')
            allowed = ({'store', 'id', 'name', 'price', 'url', 'quantity', 'unit',
                        'scope', 'condition', 'checkedAt', 'locationConfirmed',
                        'conditionsConfirmed'} | set(ENUMS) if key == 'products' else
                       {'store', 'scope', 'fulfillment', 'checkedAt', 'status', 'message', 'url'})
            require(set(row) <= allowed, 'undocumented import row field')
            sid = row.get('store')
            require(isinstance(sid, str) and sid in stores, 'unknown store ID: ' + str(sid))
            require(stores[sid]['capabilities']['browserObservationImport'], 'browser import unsupported: ' + sid)
            nonempty(row.get('scope'), 'scope')
            timestamp(row.get('checkedAt'))
            fulfillment = row.get('fulfillment', 'unknown')
            require(fulfillment in ENUMS['fulfillment'], 'invalid fulfillment')
            context = (sid, row['scope'], fulfillment)
            if 'url' in row:
                safe_url(row['url'], stores[sid]['officialDomains'])
            if key == 'products':
                product_contexts.add(context)
                for field in ('id', 'name', 'condition', 'url'):
                    nonempty(row.get(field), field)
                positive(row.get('price'), 'price')
                require('quantity' in row and 'unit' in row, 'missing quantity/unit pair')
                if row['quantity'] is None:
                    require(row['unit'] is None, 'quantity/unit must both be null')
                else:
                    positive(row['quantity'], 'quantity')
                    require(row['unit'] in {'л', 'кг', 'шт'}, 'invalid unit')
                for field, values in ENUMS.items():
                    if field in row:
                        require(row[field] in values, 'invalid ' + field)
                for field in ('locationConfirmed', 'conditionsConfirmed'):
                    if field in row:
                        require(type(row[field]) is bool, field + ' must be boolean')
            else:
                check_contexts.add(context)
                require(row.get('status') in STATUSES, 'invalid check status')
                nonempty(row.get('message'), 'message')
    require(not product_contexts & check_contexts, 'product/check context collision')


def strict_fields(value, required, optional=()):
    require(isinstance(value, dict), 'expected object')
    require(set(required) <= set(value), 'missing required field')
    require(set(value) <= set(required) | set(optional), 'unknown field')


def uuid(value):
    require(isinstance(value, str) and re.fullmatch(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', value),
        'invalid UUID')


def revision(value, minimum=0):
    require(type(value) is int and minimum <= value <= 9007199254740991, 'invalid revision')


def item_id(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9-]{1,80}', value), 'invalid item ID')


def utf16_length(value):
    # Match the JavaScript/Zod string bounds used by the prepared tool schemas.
    return len(value.encode('utf-16-le', errors='surrogatepass')) // 2


def bounded_text(value, maximum, label):
    nonempty(value, label)
    require(utf16_length(value.strip()) <= maximum, label + ' exceeds limit')


def unique_ids(value, maximum, allow_empty, validate):
    require(isinstance(value, list) and (allow_empty or value) and len(value) <= maximum,
            'invalid ID array length')
    for entry in value:
        validate(entry)
    require(len(set(value)) == len(value), 'duplicate ID')


def validate_correlation(value):
    strict_fields(value, ('workspace_id', 'research_id', 'attempt_id', 'item_id', 'item_revision', 'context_revision'))
    for field in ('workspace_id', 'research_id', 'attempt_id'):
        uuid(value[field])
    item_id(value['item_id'])
    revision(value['item_revision'], 1)
    revision(value['context_revision'])


def validate_command(tool, payload, stores):
    """Check the documented synthetic command contract, not panel application."""
    envelope = {'operation_id', 'workspace_id', 'expected_revision'}
    fields = {
        'shopping_plan_update': (envelope, {'changes', 'store_ids'}),
        'shopping_research_update': (envelope | {'action', 'research_id', 'attempt_id', 'item_ids', 'store_ids'}, set()),
        'shopping_offer_select': (envelope | {'item_id', 'item_revision', 'store', 'observation'}, set()),
    }
    require(tool in fields, 'unknown shopping tool')
    strict_fields(payload, *fields[tool])
    uuid(payload['operation_id'])
    uuid(payload['workspace_id'])
    revision(payload['expected_revision'])

    def store_id(value):
        require(isinstance(value, str) and value in stores, 'unknown store ID')

    if 'store_ids' in payload:
        unique_ids(payload['store_ids'], 17, tool == 'shopping_plan_update', store_id)
    if tool == 'shopping_plan_update':
        changes = payload.get('changes', [])
        require(isinstance(changes, list) and len(changes) <= 100, 'invalid changes length')
        require(changes or 'store_ids' in payload, 'empty plan command')
        seen = set()
        for change in changes:
            require(isinstance(change, dict) and isinstance(change.get('action'), str) and
                    change['action'] in {'upsert', 'remove'}, 'invalid action')
            expected = {'action', 'item_id'}
            if change['action'] == 'upsert':
                expected |= {'name', 'quantity', 'unit'}
            strict_fields(change, expected)
            item_id(change['item_id'])
            require(change['item_id'] not in seen, 'duplicate item ID')
            seen.add(change['item_id'])
            if change['action'] == 'upsert':
                bounded_text(change['name'], 200, 'name')
                positive(change['quantity'], 'quantity')
                require(.01 <= change['quantity'] <= 1000, 'quantity exceeds bounds')
                require(isinstance(change['unit'], str) and change['unit'] in {'шт', 'кг', 'л'}, 'invalid unit')
    elif tool == 'shopping_research_update':
        require(isinstance(payload['action'], str) and
                payload['action'] in {'start', 'resume', 'checking'}, 'invalid research action')
        uuid(payload['research_id'])
        uuid(payload['attempt_id'])
        unique_ids(payload['item_ids'], 100, False, item_id)
    else:
        item_id(payload['item_id'])
        revision(payload['item_revision'], 1)
        store_id(payload['store'])
        observation = payload['observation']
        strict_fields(observation, ('id', 'scope', 'fulfillment', 'checkedAt', 'url'))
        nonempty(observation['id'], 'observation ID')
        require(len(observation['id']) <= 120, 'observation ID exceeds limit')
        bounded_text(observation['scope'], 200, 'scope')
        require(isinstance(observation['fulfillment'], str) and
                observation['fulfillment'] in ENUMS['fulfillment'], 'invalid fulfillment')
        timestamp(observation['checkedAt'])
        require(isinstance(observation['url'], str) and len(observation['url']) <= 1000, 'invalid URL length')
        safe_url(observation['url'], stores[payload['store']]['officialDomains'])


def validate_shopping_examples(root, stores):
    fixtures = read_json(root / REFERENCES / 'shopping-plan-examples.json')
    require(isinstance(fixtures, list) and fixtures, 'empty shopping examples')
    tools, actions = set(), set()
    for index, fixture in enumerate(fixtures):
        try:
            strict_fields(fixture, ('tool', 'arguments'))
            tool, payload = fixture['tool'], fixture['arguments']
            require(isinstance(tool, str), 'invalid tool name')
            tools.add(tool)
            if tool == 'prices_browser_show':
                require('correlation' in payload, 'missing correlation example')
                validate_payload(payload, stores)
            else:
                validate_command(tool, payload, stores)
                if tool == 'shopping_research_update':
                    actions.add(payload['action'])
        except (ValidationError, KeyError, TypeError) as exc:
            raise ValidationError('shopping example {}: {}'.format(index, exc)) from exc
    require(tools == {'shopping_plan_update', 'shopping_research_update', 'shopping_offer_select', 'prices_browser_show'},
            'missing shopping tool example')
    require(actions == {'start', 'resume', 'checking'}, 'missing research action example')
    return len(fixtures)


def validate_repository(root):
    root = Path(root).resolve()
    # Every checked-in JSON document must be strict JSON, even when not a manifest.
    for path in root.rglob('*.json'):
        if '.git' not in path.parts:
            read_json(path)
    validate_manifests(root)
    validate_markdown(root)
    stores = validate_registry(root)
    fixtures = read_json(root / REFERENCES / 'import-examples.json')
    require(isinstance(fixtures, list) and fixtures, 'import examples must be nonempty array')
    for index, payload in enumerate(fixtures):
        try:
            validate_payload(payload, stores)
        except (ValidationError, KeyError, TypeError) as exc:
            raise ValidationError('import example {}: {}'.format(index, exc)) from exc
    commands = validate_shopping_examples(root, stores)
    return len(stores), len(fixtures), commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        stores, examples, commands = validate_repository(args.root)
    except (ValidationError, KeyError, TypeError, OSError) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        return 1
    print('OK: manifests, local links, {} stores, {} import examples, {} shopping examples; offline consistency only.'.format(stores, examples, commands))
    return 0


if __name__ == '__main__':
    sys.exit(main())
