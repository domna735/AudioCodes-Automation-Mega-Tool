import json, statistics
r = json.load(open('results_scan.json', encoding='utf-8'))
res = r.get('results', [])
if not res:
    print('No results')
    raise SystemExit(0)

total = len(res)
found = sum(1 for e in res if e.get('status') == 'FOUND')
not_found = total - found
errored = sum(1 for e in res if e.get('reason'))
elapsed = [e.get('elapsed_ms', 0) for e in res]
avg_all = statistics.mean(elapsed) / 1000.0
max_elapsed = max(elapsed) / 1000.0
min_elapsed = min(elapsed) / 1000.0
avg_found = statistics.mean([e['elapsed_ms'] for e in res if e.get('status')=='FOUND'])/1000.0 if found else 0
avg_notfound = statistics.mean([e['elapsed_ms'] for e in res if e.get('status')!='FOUND'])/1000.0 if not_found else 0

print(f'Total IPs scanned: {total}')
print(f'Found: {found}')
print(f'Not found: {not_found}')
print(f'Errored (has reason): {errored}')
print(f'Avg elapsed per IP: {avg_all:.3f}s')
print(f'Avg elapsed (FOUND): {avg_found:.3f}s')
print(f'Avg elapsed (NOT_FOUND): {avg_notfound:.3f}s')
print(f'Max elapsed: {max_elapsed:.3f}s')
print(f'Min elapsed: {min_elapsed:.3f}s')
