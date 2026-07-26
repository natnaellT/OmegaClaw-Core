import os, sys
root = "/home/natnael/dev/biocypher-kg-/output"
print("root:", root)
print("exists:", os.path.isdir(root))
print("abs:", os.path.abspath(root))
count = 0
for dp, dirs, fns in os.walk(root):
    for f in fns:
        if f.endswith(".metta"):
            count += 1
            if count <= 5:
                print("  found:", os.path.join(dp, f))
print("total .metta files:", count)
