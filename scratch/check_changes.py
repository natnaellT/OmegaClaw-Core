import subprocess
import sys

def get_actual_changes():
    # run git diff --ignore-cr-at-eol --name-only
    res = subprocess.run(
        ["git", "diff", "--ignore-cr-at-eol", "--name-only"],
        capture_output=True, text=True, cwd="/home/natnael/PeTTa/repos/OmegaClaw-Core"
    )
    if res.returncode != 0:
        print("Git error:", res.stderr)
        return
        
    files = res.stdout.strip().split("\n")
    actual_files = []
    for f in files:
        if not f:
            continue
        # check if git diff --ignore-cr-at-eol <file> is empty
        diff_res = subprocess.run(
            ["git", "diff", "--ignore-cr-at-eol", f],
            capture_output=True, text=True, cwd="/home/natnael/PeTTa/repos/OmegaClaw-Core"
        )
        if diff_res.stdout.strip():
            actual_files.append(f)
            
    print("\nActual code changes:")
    for f in actual_files:
        print(f)

if __name__ == "__main__":
    get_actual_changes()
