"""Regression tests for offline repository checks; no network or backend calls."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import validate_repository as validator

ROOT = Path(__file__).resolve().parents[1]


class RepositoryValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        for name in ('plugins', '.agents', 'docs'):
            shutil.copytree(ROOT / name, self.root / name)
        shutil.copy2(ROOT / 'README.md', self.root / 'README.md')

    def edit_json(self, path, mutate):
        target = self.root / path
        data = json.loads(target.read_text(encoding='utf-8'))
        mutate(data)
        target.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')

    def assert_invalid(self, match):
        with self.assertRaisesRegex(validator.ValidationError, match):
            validator.validate_repository(self.root)

    def test_repository_is_consistent(self):
        stores, fixtures, commands = validator.validate_repository(self.root)
        self.assertEqual(stores, 17)
        self.assertEqual(commands, 8)
        self.assertGreater(fixtures, 0)

    def test_version_mismatch(self):
        self.edit_json(validator.PLUGIN / 'plugin.json', lambda d: d.update(version='0.0.0'))
        self.assert_invalid('manifest mismatch: version')

    def test_plugin_id_mismatch(self):
        self.edit_json(validator.PLUGIN / 'plugin.json', lambda d: d.update(name='other'))
        self.assert_invalid('manifest mismatch: name')

    def test_endpoint_mismatch(self):
        self.edit_json(validator.PLUGIN / 'mcp.json', lambda d: d['mcpServers']['vkusvill-cart-cloud'].update(url='https://example.org/api/mcp'))
        self.assert_invalid('MCP endpoint mismatch')

    def test_server_id_mismatch(self):
        def mutate(data):
            data['mcpServers']['other'] = data['mcpServers'].pop('vkusvill-cart-cloud')
        self.edit_json(validator.PLUGIN / 'mcp.json', mutate)
        self.assert_invalid('MCP server IDs mismatch')

    def test_missing_skill(self):
        (self.root / validator.PLUGIN / 'skills/grocery-magnit/SKILL.md').unlink()
        self.assert_invalid('missing declared SKILL.md')

    def test_skill_name_mismatch(self):
        path = self.root / validator.PLUGIN / 'skills/grocery-magnit/SKILL.md'
        path.write_text(path.read_text(encoding='utf-8').replace('name: grocery-magnit', 'name: other'), encoding='utf-8')
        self.assert_invalid('frontmatter name mismatch')

    def test_long_short_description(self):
        self.edit_json(validator.PLUGIN / '.codex-plugin/plugin.json', lambda d: d['interface'].update(shortDescription='x' * 31))
        self.assert_invalid('shortDescription exceeds')

    def test_broken_markdown_link(self):
        with (self.root / 'README.md').open('a', encoding='utf-8') as handle:
            handle.write('\n[broken](missing.md)\n')
        self.assert_invalid('missing local path')

    def test_reference_style_broken_link(self):
        with (self.root / 'README.md').open('a', encoding='utf-8') as handle:
            handle.write('\n[reference]: missing.md\n')
        self.assert_invalid('missing local path')

    def test_path_escape(self):
        with (self.root / 'README.md').open('a', encoding='utf-8') as handle:
            handle.write('\n[escape](../../outside.md)\n')
        self.assert_invalid('path escapes repository')

    def test_duplicate_json_key(self):
        (self.root / 'bad.json').write_text('{"x":1,"x":2}', encoding='utf-8')
        self.assert_invalid('duplicate JSON key')

    def test_nonfinite_json(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e999'):
            with self.subTest(value=value):
                (self.root / 'bad.json').write_text('{"price":' + value + '}', encoding='utf-8')
                self.assert_invalid('non-finite JSON number')

    def test_duplicate_store(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'].append(copy.deepcopy(d['stores'][0])))
        self.assert_invalid('duplicate store ID')

    def test_store_skill_mismatch(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'][0].update(id='invented'))
        self.assert_invalid('registry/skill ID mismatch')

    def test_unapproved_primary_domain(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'][0].update(officialDomains=['evil.example']))
        self.assert_invalid('unapproved URL domain')

    def test_broken_registry_evidence(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['evidence'].update(browserHistory='missing.md'))
        self.assert_invalid('missing local path')

    def test_invented_store_without_skill(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'][-1].update(id='invented'))
        self.assert_invalid('unknown stable store ID')

    def test_missing_store(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'].pop())
        self.assert_invalid('stable store ID coverage')

    def test_additional_domain_rejected(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'][0]['officialDomains'].append('evil.example'))
        self.assert_invalid('official domain drift')

    def test_nullable_skill_contract(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'][0].update(skill=None))
        self.assert_invalid('nullable skill mismatch')

    def test_capability_inventory(self):
        stores = validator.validate_registry(self.root)
        self.assertEqual(sum(s['capabilities']['browserObservationImport'] for s in stores.values()), 16)
        self.assertEqual(sum(s['capabilities']['browserWorkflow'] for s in stores.values()), 12)
        self.assertEqual([s['id'] for s in stores.values() if s['capabilities']['realCartLink']], ['vv'])
        self.assertEqual([s['id'] for s in stores.values() if s['capabilities']['verifiedTransfer']], ['vv'])
        self.assertEqual({s['id'] for s in stores.values() if s['capabilities']['connectedCatalog'] != 'not_documented'}, {'vv', 'bahetle'})

    def test_bahetle_import_not_enabled_by_domain(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'][-1]['capabilities'].update(browserObservationImport=True))
        self.assert_invalid('browser import capability mismatch')

    def test_only_vv_cart_capability(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'][0]['capabilities'].update(realCartLink=True))
        self.assert_invalid('cart capability mismatch')

    def test_no_new_catalog_claim(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['stores'][0]['capabilities'].update(connectedCatalog='public_catalog'))
        self.assert_invalid('catalog capability mismatch')

    def test_strict_semver(self):
        for version in ('01.9.0', '0.09.0', '0.9', '0.9.0-01', '0.9.0+', 'v0.9.0', '1١.9.0'):
            with self.subTest(version=version):
                for name in ('plugin.json', '.codex-plugin/plugin.json'):
                    self.edit_json(validator.PLUGIN / name, lambda d: d.update(version=version))
                self.assert_invalid('invalid plugin version')
        for version in ('0.9.0', '0.9.0-rc.1', '0.9.0+review.1'):
            for name in ('plugin.json', '.codex-plugin/plugin.json'):
                self.edit_json(validator.PLUGIN / name, lambda d: d.update(version=version))
            validator.validate_manifests(self.root)

    def test_default_prompt_type_preserved(self):
        self.edit_json(validator.PLUGIN / 'plugin.json', lambda d: d['extensions']['com.openai']['interface'].update(defaultPrompt=['one']))
        self.edit_json(validator.PLUGIN / '.codex-plugin/plugin.json', lambda d: d['interface'].update(defaultPrompt=['one']))
        self.assert_invalid('defaultPrompt must remain')

    def test_mcp_schema_preserved(self):
        self.edit_json(validator.PLUGIN / 'mcp.json', lambda d: d.update({'$schema': 'https://example.org/schema'}))
        self.assert_invalid('MCP schema changed')

    def test_marketplace_policy_preserved(self):
        self.edit_json(Path('.agents/plugins/marketplace.json'), lambda d: d['plugins'][0]['policy'].update(installation='REQUIRED'))
        self.assert_invalid('marketplace policy changed')


    def test_cli_failure_exit_code(self):
        self.edit_json(validator.PLUGIN / 'plugin.json', lambda d: d.update(version='0.0.0'))
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate_repository.py'), '--root', str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('manifest mismatch', result.stderr)


class ImportFixtureTests(unittest.TestCase):
    def setUp(self):
        self.stores = validator.validate_registry(ROOT)
        fixtures = validator.read_json(ROOT / validator.REFERENCES / 'import-examples.json')
        self.payload = copy.deepcopy(next(p for p in fixtures if p['products']))
        self.product = self.payload['products'][0]

    def reject(self, match):
        with self.assertRaisesRegex(validator.ValidationError, match):
            validator.validate_payload(self.payload, self.stores)

    def test_unknown_store(self):
        self.product['store'] = 'invented'
        self.reject('unknown store ID')

    def test_unsafe_urls(self):
        host = self.stores[self.product['store']]['officialDomains'][0]
        for url in ('http://' + host, 'https://' + host + '.evil.example/x',
                    'https://' + host + '@evil.example/x', 'https://user@' + host,
                    'https://' + host + ':444/x', 'https://' + host + '\\@evil.example',
                    'https://evil.example/?official=' + host):
            with self.subTest(url=url):
                self.product['url'] = url
                self.reject('URL|domain')

    def test_bad_prices(self):
        for price in (0, -1, True, '12', float('nan'), float('inf')):
            with self.subTest(price=price):
                self.product['price'] = price
                self.reject('finite positive number')

    def test_undocumented_field(self):
        self.product['priceBasis'] = 'per_kg'
        self.reject('undocumented import row field')

    def test_bad_quantity_pair(self):
        self.product.update(quantity=None, unit='кг')
        self.reject('both be null')

    def test_bad_enum(self):
        self.product['match'] = 'identical'
        self.reject('invalid match')

    def test_bad_boolean(self):
        self.product['locationConfirmed'] = 'true'
        self.reject('must be boolean')

    def test_bad_timestamp(self):
        for value in ('2026-10-25T12:00:00', 'not-a-dateZ', '2026-10-25T12:00:00+03:00'):
            with self.subTest(value=value):
                self.product['checkedAt'] = value
                self.reject('checkedAt')

    def test_empty_payload(self):
        self.payload.update(products=[], checks=[])
        self.reject('empty import')

    def test_product_check_conflict(self):
        self.payload['checks'].append({
            'store': self.product['store'], 'scope': self.product['scope'],
            'fulfillment': self.product.get('fulfillment', 'unknown'),
            'checkedAt': self.product['checkedAt'], 'status': 'error', 'message': 'Synthetic check'})
        self.reject('context collision')

    def test_array_limit(self):
        self.payload['products'] = [copy.deepcopy(self.product) for _ in range(41)]
        self.reject('at most 40')


class ShoppingContractTests(unittest.TestCase):
    def setUp(self):
        self.stores = validator.validate_registry(ROOT)
        self.examples = validator.read_json(ROOT / validator.REFERENCES / 'shopping-plan-examples.json')

    def command(self, tool):
        return copy.deepcopy(next(e['arguments'] for e in self.examples if e['tool'] == tool))

    def reject(self, tool, payload, match):
        with self.assertRaisesRegex(validator.ValidationError, match):
            validator.validate_command(tool, payload, self.stores)

    def test_all_examples(self):
        self.assertEqual(validator.validate_shopping_examples(ROOT, self.stores), 8)

    def test_envelope_requires_ids_and_revision(self):
        for tool in ('shopping_plan_update', 'shopping_research_update', 'shopping_offer_select'):
            for key, bad in (('operation_id', 'invented'), ('workspace_id', 1),
                             ('expected_revision', -1), ('expected_revision', True),
                             ('expected_revision', '2'), ('expected_revision', 9007199254740992)):
                with self.subTest(tool=tool, key=key, bad=bad):
                    payload = self.command(tool)
                    payload[key] = bad
                    self.reject(tool, payload, 'UUID|revision')

    def test_unknown_fields_rejected(self):
        for tool in ('shopping_plan_update', 'shopping_research_update', 'shopping_offer_select'):
            payload = self.command(tool)
            payload['price'] = 1
            self.reject(tool, payload, 'unknown field')

    def test_plan_cannot_supply_price_or_partial_demand(self):
        for field in ('quantity', 'unit'):
            payload = self.command('shopping_plan_update')
            del payload['changes'][0][field]
            self.reject('shopping_plan_update', payload, 'missing required')
        payload = self.command('shopping_plan_update')
        payload['changes'][0]['price'] = 1
        self.reject('shopping_plan_update', payload, 'unknown field')

    def test_plan_quantity_bounds_and_unit(self):
        for quantity in (0, .001, 1001, True, '2', float('inf'), float('nan')):
            payload = self.command('shopping_plan_update')
            payload['changes'][0]['quantity'] = quantity
            self.reject('shopping_plan_update', payload, 'quantity')
        payload = self.command('shopping_plan_update')
        payload['changes'][0]['unit'] = 'мл'
        self.reject('shopping_plan_update', payload, 'invalid unit')

    def test_duplicate_ids_and_same_names(self):
        payload = self.command('shopping_plan_update')
        payload['changes'][1]['name'] = payload['changes'][0]['name']
        validator.validate_command('shopping_plan_update', payload, self.stores)
        payload['changes'][1]['item_id'] = payload['changes'][0]['item_id']
        self.reject('shopping_plan_update', payload, 'duplicate item ID')

    def test_item_ids_are_stable_bounded_tokens(self):
        for value in ('has space', '_milk', 'a' * 81, '', 7):
            payload = self.command('shopping_plan_update')
            payload['changes'][0]['item_id'] = value
            self.reject('shopping_plan_update', payload, 'invalid item ID')

    def test_empty_scope_is_valid_empty_command_is_not(self):
        payload = self.command('shopping_plan_update')
        payload.pop('changes')
        payload['store_ids'] = []
        validator.validate_command('shopping_plan_update', payload, self.stores)
        payload.pop('store_ids')
        self.reject('shopping_plan_update', payload, 'empty plan command')

    def test_remove_cannot_contain_upsert_fields(self):
        payload = self.command('shopping_plan_update')
        payload['changes'] = [{'action': 'remove', 'item_id': 'milk', 'quantity': 2}]
        self.reject('shopping_plan_update', payload, 'unknown field')

    def test_command_array_limits(self):
        payload = self.command('shopping_plan_update')
        payload['changes'] = [{'action': 'remove', 'item_id': str(n)} for n in range(101)]
        self.reject('shopping_plan_update', payload, 'invalid changes length')
        for ids in (['5ka', '5ka'], ['invented'], [1]):
            payload = self.command('shopping_plan_update')
            payload['store_ids'] = ids
            self.reject('shopping_plan_update', payload, 'duplicate ID|unknown store ID')

    def test_research_action_and_nonempty_unique_scope(self):
        for key, bad in (('action', 'complete'), ('action', []), ('store_ids', []), ('item_ids', []),
                         ('item_ids', ['milk', 'milk']), ('store_ids', ['invented']),
                         ('attempt_id', 'invented'), ('item_ids', 'milk')):
            payload = self.command('shopping_research_update')
            payload[key] = bad
            self.reject('shopping_research_update', payload, 'action|array|duplicate|store ID|UUID')

    def test_selection_requires_complete_reference_without_claimed_price(self):
        for field in ('id', 'scope', 'fulfillment', 'checkedAt', 'url'):
            payload = self.command('shopping_offer_select')
            del payload['observation'][field]
            self.reject('shopping_offer_select', payload, 'missing required field')
        payload = self.command('shopping_offer_select')
        payload['observation']['price'] = 99
        self.reject('shopping_offer_select', payload, 'unknown field')

    def test_selection_rejects_wrong_store_and_item_revision(self):
        payload = self.command('shopping_offer_select')
        payload['store'] = '5ka'
        self.reject('shopping_offer_select', payload, 'unapproved URL domain')
        payload = self.command('shopping_offer_select')
        payload['item_revision'] = 0
        self.reject('shopping_offer_select', payload, 'invalid revision')

    def test_correlated_browser_query_matches_plan_name_boundaries(self):
        # Derive both payloads from the public fixtures, keeping the same item
        # correlation while checking every boundary in the actual contracts.
        for name in ('Я', 'Я' * 121, 'Я' * 200, '🥛' * 100):
            with self.subTest(units=validator.utf16_length(name)):
                plan = self.command('shopping_plan_update')
                browser = self.command('prices_browser_show')
                plan['changes'][0]['name'] = '  ' + name + '  '
                browser['q'] = '  ' + name + '  '
                self.assertEqual(browser['correlation']['item_id'], plan['changes'][0]['item_id'])
                self.assertEqual(browser['q'].strip(), plan['changes'][0]['name'].strip())
                validator.validate_command('shopping_plan_update', plan, self.stores)
                validator.validate_payload(browser, self.stores)

    def test_correlated_browser_query_rejects_empty_or_oversized_plan_names(self):
        for name in ('', '  ', 'Я' * 201, '🥛' * 100 + 'Я'):
            with self.subTest(units=validator.utf16_length(name.strip())):
                plan = self.command('shopping_plan_update')
                browser = self.command('prices_browser_show')
                plan['changes'][0]['name'] = name
                browser['q'] = name
                self.reject('shopping_plan_update', plan, 'name')
                with self.assertRaisesRegex(validator.ValidationError, 'q'):
                    validator.validate_payload(browser, self.stores)

    def test_browser_correlation_is_optional_but_strict(self):
        payload = self.command('prices_browser_show')
        validator.validate_payload(payload, self.stores)
        correlation = payload.pop('correlation')
        validator.validate_payload(payload, self.stores)
        for key, bad in (('workspace_id', 'bad'), ('item_revision', 0),
                         ('context_revision', -1), ('item_id', 'with space')):
            payload['correlation'] = dict(correlation, **{key: bad})
            with self.assertRaisesRegex(validator.ValidationError, 'UUID|revision|item ID'):
                validator.validate_payload(payload, self.stores)
        payload['correlation'] = dict(correlation, price=1)
        with self.assertRaisesRegex(validator.ValidationError, 'unknown field'):
            validator.validate_payload(payload, self.stores)
        payload['correlation'] = dict(correlation)
        del payload['correlation']['attempt_id']
        with self.assertRaisesRegex(validator.ValidationError, 'missing required'):
            validator.validate_payload(payload, self.stores)

    def test_bahetle_cannot_import_observation(self):
        payload = self.command('prices_browser_show')
        payload['products'][0]['store'] = 'bahetle'
        payload['products'][0]['url'] = 'https://dostavka.bahetle.com/'
        with self.assertRaisesRegex(validator.ValidationError, 'browser import unsupported'):
            validator.validate_payload(payload, self.stores)


if __name__ == '__main__':
    unittest.main()
