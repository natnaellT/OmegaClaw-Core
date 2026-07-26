import os

files = [
    '.gitignore',
    'bin/bio-index',
    'lib_llm_ext.py',
    'profile/policy.yaml',
    'src/bio_graph.py',
    'src/helper.py',
    'src/loop.metta',
    'src/skills.metta'
]

repo_root = '/home/natnael/PeTTa/repos/OmegaClaw-Core'

for rel in files:
    path = os.path.join(repo_root, rel)
    if os.path.exists(path):
        with open(path, 'rb') as f:
            content = f.read().replace(b'\r\n', b'\n')
        with open(path, 'wb') as f:
            f.write(content)
        print(f"Normalized LF: {rel}")
