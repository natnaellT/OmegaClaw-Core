import subprocess, os

root = "/home/natnael/dev/biocypher-kg-/output"
print("Root exists:", os.path.isdir(root))

try:
    proc = subprocess.run(
        ["find", root, "-name", "*.metta", "-type", "f"],
        capture_output=True, text=True, timeout=60,
    )
    print("Return code:", proc.returncode)
    print("Stdout:", proc.stdout[:200])
    print("Stderr:", proc.stderr)
except Exception as e:
    print("Exception:", e)
