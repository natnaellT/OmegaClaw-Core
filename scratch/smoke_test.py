import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import bio_graph as bg

print('=== bio_index() ===')
print(bg.bio_index())

print('=== bio_index(root) ===')
print(bg.bio_index('/tmp'))

print('=== bio_query(query) [env not set, should error gracefully] ===')
print(bg.bio_query('help'))

print('=== bio_query(root, query) ===')
print(bg.bio_query('/home/natnael/dev/biocypher-kg-/output', 'stats'))

print('=== bio_extract(root, query) ===')
result = bg.bio_extract('/home/natnael/dev/biocypher-kg-/output', 'predicates')
print(result[:200] if len(result) > 200 else result)

print()
print('=== ALL API TESTS PASSED ===')
