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
    base = root / PLUGIN
    public = read_json(base / 'plugin.json')
    codex = read_json(base / '.codex-plugin/plugin.json')
    for field in ('name', 'version'):
        require(public[field] == codex[field], 'manifest mismatch: ' + field)
    require(re.fullmatch(r'\d+\.\d+\.\d+', public['version']), 'invalid plugin version')
    for interface in (public['extensions']['com.openai']['interface'], codex['interface']):
        require(isinstance(interface['shortDescription'], str) and
                len(interface['shortDescription']) <= 30, 'shortDescription exceeds 30 characters')
        for field in ('logo', 'composerIcon'):
            local_path(root, base, interface[field])
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
    modern = read_json(base / 'mcp.json')['mcpServers']
    legacy = read_json(legacy_path)['mcpServers']
    require(modern.keys() == legacy.keys(), 'MCP server IDs mismatch')
    require(bool(modern), 'no MCP servers')
    for name, server in modern.items():
        require(server['url'] == legacy[name]['url'], 'MCP endpoint mismatch')
        safe_url(server['url'])
        require(server['type'] == 'streamable-http' and legacy[name]['type'] == 'http',
                'unexpected MCP transport mapping')
    marketplace = read_json(root / '.agents/plugins/marketplace.json')
    entries = [p for p in marketplace['plugins'] if p['name'] == public['name']]
    require(len(entries) == 1, 'plugin ID missing or duplicated in marketplace')
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
    registry = read_json(root / REFERENCES / 'stores.json')
    require(registry['schemaVersion'] == 1, 'unknown registry schemaVersion')
    stores = registry['stores']
    require(isinstance(stores, list) and stores, 'empty store registry')
    by_id = {}
    seen_skills = set()
    for store in stores:
        sid = store['id']
        require(isinstance(sid, str) and re.fullmatch(r'[a-z0-9-]+', sid), 'invalid store ID')
        require(sid not in by_id, 'duplicate store ID: ' + sid)
        by_id[sid] = store
        skill = local_path(root, root / REFERENCES, store['skill'])
        require(skill.name == 'SKILL.md' and skill not in seen_skills, 'duplicate/invalid store skill')
        seen_skills.add(skill)
        body = skill.read_text(encoding='utf-8')
        require('Идентификатор в панели и MCP: `{}`'.format(sid) in body,
                'registry/skill ID mismatch: ' + sid)
        domains = store['officialDomains']
        require(isinstance(domains, list) and domains and len(set(domains)) == len(domains),
                'empty/duplicate official domains: ' + sid)
        for domain in domains:
            require(isinstance(domain, str) and re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}', domain),
                    'invalid official domain: ' + str(domain))
        primary = re.search(r'Стартовая витрина:.*?\]\((https://[^)]+)\)', body)
        require(primary is not None, 'missing store primary URL')
        safe_url(primary.group(1), domains)
        for key in ('manualLists', 'browserWorkflow', 'browserObservationImport'):
            require(type(store['capabilities'][key]) is bool, 'invalid capability: ' + key)
        require(store['capabilities']['connectedCatalog'] in
                {'public_catalog', 'location_scoped_catalog', 'not_documented'}, 'invalid catalog capability')
    declared_skills = set((root / PLUGIN / 'skills').glob('*/SKILL.md'))
    declared_skills.discard(root / PLUGIN / 'skills/grocery-prices-browser/SKILL.md')
    require(seen_skills == declared_skills, 'registry does not cover every store skill')
    for key in ('identityAndDomains', 'browserHistory', 'panelAndConnectedCatalogs'):
        local_path(root, root / REFERENCES, registry['evidence'][key])
    for extra in registry.get('additionalNetworks', []):
        require(extra['id'] is None, 'undocumented additional store wire ID')
        require(extra['officialDomains'] == [], 'undocumented additional store domain')
        require(extra['capabilities']['browserObservationImport'] == 'unverified',
                'undocumented additional store import capability')
        require(extra['supportLevel'] in {'list_only', 'connected_catalog_documented'},
                'invalid additional support level')
        local_path(root, root / REFERENCES, extra['evidence'])
    if 'documentedPanelStoreCount' in registry:
        require(registry['documentedPanelStoreCount'] == len(stores) +
                len(registry.get('additionalNetworks', [])) + registry['unresolvedPanelStoreCount'],
                'panel store count mismatch')
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
    require(set(payload) <= {'q', 'city', 'products', 'checks'}, 'undocumented payload field')
    nonempty(payload.get('q'), 'q')
    require(2 <= len(payload['q']) <= 120, 'q length must be 2–120')
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
    return len(stores), len(fixtures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        stores, examples = validate_repository(args.root)
    except (ValidationError, KeyError, TypeError, OSError) as exc:
        print('FAIL: ' + str(exc), file=sys.stderr)
        return 1
    print('OK: manifests, local links, {} stores, {} import examples; offline consistency only.'.format(stores, examples))
    return 0


if __name__ == '__main__':
    sys.exit(main())
