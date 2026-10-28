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
        stores, fixtures = validator.validate_repository(self.root)
        self.assertGreater(stores, 0)
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

    def test_invented_extra_store_id(self):
        self.edit_json(validator.REFERENCES / 'stores.json', lambda d: d['additionalNetworks'][0].update(id='invented'))
        self.assert_invalid('undocumented additional store wire ID')

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


if __name__ == '__main__':
    unittest.main()
