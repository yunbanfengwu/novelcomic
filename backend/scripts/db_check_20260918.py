import asyncio
import asyncpg
import json

async def main():
    conn = await asyncpg.connect('postgresql://postgres:123456@localhost:5432/novelcomic')
    rows = await conn.fetch('''SELECT slug, version, graph FROM workflows
        WHERE slug LIKE '%trailer%' ORDER BY slug, version DESC''')
    for r in rows:
        g = r['graph'] if isinstance(r['graph'], dict) else json.loads(r['graph'])
        nodes = g.get('nodes', [])
        kinds = [(n.get('type'), (n.get('config') or {}).get('name'), (n.get('payload') or {}).get('modality')) for n in nodes]
        distill = any((n.get('config') or {}).get('name') == 'trailer.distill' for n in nodes)
        print(r['slug'], 'v' + str(r['version']), '| nodes:', len(nodes), '| has distill:', distill := distill_check(nodes))
        for n in nodes:
            cfg = n.get('config') or {}
            print('   ', n.get('id'), n.get('type'), '| tap:', (n.get('ui') or {}).get('tap'), '| modality:', (n.get('payload') or {}).get('modality'), '| tool:', cfg.get('name'))
    await conn.close()

def distill_check(nodes):
    return any((n.get('config') or {}).get('name') == 'trailer.distill' for n in nodes)

asyncio.run(main())
